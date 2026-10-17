"""确定性 fake Agent driver：真实 MCP stdio 子进程 + 真实 Core，不跑模型、不联网。

用法::

    PYTHONPATH=. .venv/bin/python scripts/harness/benchmark/fake_agent_driver.py \
        --scenario reference [--out <path>.json]

设计要点：

- Core 在**本进程**内以真实 loopback HTTP 提供（`StoryRailApi` + 合成媒体 Provider）；
  MCP server 是真实 stdio 子进程（`python -m integrations.storyrail_mcp`），
  与 `tests/oracle/test_oracle_mcp_wire.py`、`tests/test_storyrail_mcp.py` 同一启动方式。
- 项目只创建一次并固定 ID/固定字节；场景脚本按 JSON 顺序发 MCP 调用，
  由 `meter.py` 逐请求计量线上字节。
- 不调用任何真实模型、不读取真实项目、不写仓库内状态；全部落在临时隔离目录。
- 确定性：同一环境连跑两次，除 `date`/`git_sha` 等文档化易变字段外逐字节一致。
  项目 ID 由固定的 `uuid4` 序列产生（uvloop 与 uuid 都是确定性的）；
  合成媒体 Provider 每次 observe 恒返回成功，等待轮次不随机器速度变化。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from core.structured_director.models import NarrationLanguage

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:  # 允许 `python scripts/harness/benchmark/fake_agent_driver.py`
    sys.path.insert(0, str(ROOT))

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from core.application.caller import Caller, current_caller  # noqa: E402
from core.director_proposals import (  # noqa: E402
    CharacterCardProposal,
    DialogueLineProposal,
    KeyframePlanProposal,
    KeyframeSegmentProposal,
    KeyframeShotProposal,
    NarratorProfileProposal,
    ReferenceLibraryProposal,
    SceneProposal,
    ShotProposal,
    ShotSegmentProposal,
    StructuredDirectorScriptProposal,
)
from core.project_settings import ProjectAspectRatio  # noqa: E402
from core.project_workspaces import ProjectWorkspaceStore  # noqa: E402
from core.structured_director import (  # noqa: E402
    StructuredDirectorHttpApi,
    StructuredDirectorService,
    StructuredDirectorStore,
)
from core.structured_director.planning_inputs import keyframe_inputs  # noqa: E402
from core.structured_director.script_proposals import begin, submit  # noqa: E402
from scripts.harness.benchmark.meter import Meter, compact_bytes  # noqa: E402
from scripts.harness.fixtures.synthetic_media import (  # noqa: E402
    provider_set,
    service_registry,
)
from server.api import StoryRailApi  # noqa: E402
from server.http import StoryRailHttpServer  # noqa: E402

AGENT_TOKEN = "benchmark_agent_" + "a" * 32
AGENT_CALLER_ID = "benchmark-agent"
PLAN_MARKDOWN = (
    "# 完整导演方案：末班车\n\n"
    "## 第一场：站台\n"
    "傍晚，空旷站台，冷蓝色天光。小满握着红色行李箱的拉杆，抬头看向站牌。\n\n"
    "## 第二场：车厢\n"
    "末班车进站，小满进入车厢，在靠窗座位坐下。\n"
)
SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
# read_professional_contract / read_professional_workset 的公开 page_bytes 上限。
PAGE_BYTES = 24 * 1024
WAIT_INTERVAL_SECONDS = "0.01"
WAIT_MAX_SECONDS = "0.2"


class ScenarioError(RuntimeError):
    """场景脚本与真实 Core 行为不一致时立即失败，不静默跳过。"""


# ---------------------------------------------------------------------------
# 场景脚本求值
# ---------------------------------------------------------------------------


def _lookup(namespace: dict[str, Any], path: str) -> Any:
    """解析 ``base.expected_revision`` / ``items[*].id`` 一类路径。"""
    head, _, rest = path.partition(".")
    if head.endswith("[*]"):
        values = namespace[head[: -len("[*]")]]
        if not isinstance(values, list):
            raise ScenarioError(f"占位符 {path} 的 {head} 不是列表。")
        tail = rest.split(".", 1)[-1] if "." in rest else None
        if tail is None:
            return list(values)
        return [_lookup({"_": item}, "_." + tail) for item in values]
    if head.endswith("]"):
        name, _, index = head.partition("[")
        values = namespace[name]
        if not isinstance(values, list) or not index[:-1].isdigit():
            raise ScenarioError(f"占位符 {path} 的下标不合法。")
        value = values[int(index[:-1])]
        if not rest:
            return value
        if isinstance(value, dict):
            return _lookup(value, rest)
        return _lookup({"_": value}, "_." + rest)
    value = namespace[head]
    if not rest:
        return value
    if not isinstance(value, dict):
        raise ScenarioError(f"占位符 {path} 的 {head} 不是对象。")
    return _lookup(value, rest)


def evaluate(expression: str, namespace: dict[str, Any]) -> Any:
    """只支持 ``$path`` 与 ``$path + 整数`` 两种形式，避免任意代码执行。"""
    expression = expression.strip()
    if not expression.startswith("$"):
        raise ScenarioError(f"占位符必须以 $ 开头：{expression!r}")
    path, _, suffix = expression[1:].partition(" ")
    if not suffix:
        return _lookup(namespace, path)
    if not suffix.startswith("+ "):
        raise ScenarioError(f"不支持的占位符运算：{expression!r}")
    offset = suffix[2:].strip()
    if not offset.isdigit():
        raise ScenarioError(f"占位符偏移必须是整数：{expression!r}")
    value = _lookup(namespace, path)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ScenarioError(f"占位符 {path} 不是整数，不能做偏移。")
    return value + int(offset)


def resolve(value: Any, namespace: dict[str, Any]) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("$") and "{" not in value:
            return evaluate(value, namespace)
        return value
    if isinstance(value, list):
        return [resolve(item, namespace) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, namespace) for key, item in value.items()}
    return value


# ---------------------------------------------------------------------------
# 合成项目 bootstrap（只做人类审核步骤，不做 Agent 工作）
# ---------------------------------------------------------------------------


def _reference_proposal() -> ReferenceLibraryProposal:
    return ReferenceLibraryProposal(
        (
            CharacterCardProposal(
                "小满", "短发，蓝色外套，一直带着红色行李箱", "年轻、克制、语速偏慢"
            ),
        ),
        NarratorProfileProposal(
            "旁白", "克制、温和、纪录片式表达", "Calm, warm documentary narrator."
        ),
    )


def _script_proposal(character_id: str) -> StructuredDirectorScriptProposal:
    return StructuredDirectorScriptProposal(
        (
            SceneProposal(
                title="末班车",
                summary="小满在停用前的车站等最后一班车。",
                setting="傍晚，空旷站台，冷蓝色天光。",
                narration_cues=(),
                shots=(
                    ShotProposal(
                        visible_character_ids=(character_id,),
                        composition="中远景，人物位于画面右侧。",
                        camera_movement="缓慢推近。",
                        action="小满握住行李箱拉杆，抬头看向站牌。",
                        audio_direction="远处风声和站内电流声。",
                        transition_in=None,
                        segments=(
                            ShotSegmentProposal(
                                duration_estimate_seconds=6.0,
                                action="小满抬头看向站牌。",
                                dialogue_lines=(
                                    DialogueLineProposal(
                                        character_id, "还会来吗？", "轻声，带一点迟疑"
                                    ),
                                ),
                                boundary_from_previous=None,
                            ),
                        ),
                    ),
                ),
            ),
        )
    )


def _keyframe_plan(store: StructuredDirectorStore, target_shot_ids: tuple[str, ...]):
    document = store.read()
    scenes, shots, boundaries = keyframe_inputs(document, target_shot_ids)
    proposals = []
    for scene in scenes:
        for shot in scene.shots:
            if not shot.planning_enabled:
                continue
            character_ids = tuple(item.id for item in shot.visible_characters)
            proposals.append(
                KeyframeShotProposal(
                    shot_id=shot.id,
                    continues_from_previous_shot=False,
                    start_prompt_text=f"{scene.title}的静态首帧。",
                    start_visible_character_ids=character_ids,
                    start_environment_mode=None,
                    start_environment_view_id=None,
                    segments=tuple(
                        KeyframeSegmentProposal(
                            segment_id=segment.id,
                            frame_strategy="both",
                            end_prompt_text=f"{scene.title}的静态尾帧。",
                            end_visible_character_ids=character_ids,
                            end_environment_mode=None,
                            end_environment_view_id=None,
                        )
                        for segment in shot.segments
                    ),
                )
            )
    return KeyframePlanProposal(tuple(proposals)), shots, boundaries


async def bootstrap(store, service, stage: str) -> dict[str, Any]:
    """把合成项目推进到场景声明的状态；返回场景可用的事实。

    只使用 Core 的正式 Store/Service 领域方法；人类审核动作不在 MCP 工具面内，
    因此必须在 bootstrap 完成。
    """
    base: dict[str, Any] = {
        "project_id": store.read().project_id,
        "title": "基准合成项目",
        "aspect_ratio": "16:9",
        "plan_markdown": PLAN_MARKDOWN,
        "expected_revision": store.read().revision,
        "character_id": None,
    }
    if stage == "empty":
        return base

    store.begin_reference_proposal()
    document = store.apply_reference_proposal(_reference_proposal())
    await _human_command(service, "reference.confirm_review", document.revision)
    base["expected_revision"] = store.read().revision
    character_id = store.read().reference_library.characters[0].id
    base["character_id"] = character_id
    if stage == "ready":
        return base
    document, _recovery = begin(store, expected_revision=base["expected_revision"])
    document = submit(
        store,
        _script_proposal(character_id),
        request_id=document.active_director_run.id,
        expected_revision=document.revision,
    )
    document = await service.confirm_script(expected_revision=document.revision)
    script = store.read().director_script
    scene_ids = tuple(scene.id for scene in script.scenes)
    shot_ids = tuple(shot.id for scene in script.scenes for shot in scene.shots)
    base["scene_ids"] = list(scene_ids)
    base["shot_ids"] = list(shot_ids)
    base["expected_revision"] = store.read().revision
    if stage == "timing":
        return base

    document = await service.unlock_visual_production(expected_revision=base["expected_revision"])
    base["expected_revision"] = store.read().revision
    if stage == "unlocked":
        return base

    document, _recovery = store.begin_keyframe_plan(
        expected_revision=document.revision, target_ids=shot_ids
    )
    plan, shots, boundaries = _keyframe_plan(store, shot_ids)
    store.apply_keyframe_plan(plan, target_shot_ids=shots, required_shared_boundaries=boundaries)
    base["expected_revision"] = store.read().revision
    await _finish_keyframe_generations(service)
    document = store.read()
    base["expected_revision"] = document.revision
    base["segment_id"] = document.video_plan.segments[0].segment_id
    base["segment_ids"] = [base["segment_id"]]
    return base


async def _human_command(service, name: str, revision: int):
    """经正式人类入口执行审核动作；bootstrap 不代表 Agent 能力。"""
    caller = Caller(
        "benchmark-human",
        "human",
        frozenset({service.snapshot_required().project_id}),
        frozenset({"human.write"}),
        4102444800,
    )
    token = current_caller.set(caller)
    try:
        response = await StructuredDirectorHttpApi(
            service, resource_path="/structured-director"
        ).handle(
            "POST",
            "/structured-director/application/commands",
            json.dumps(
                {
                    "name": name,
                    "expected_revision": revision,
                    "idempotency_key": f"benchmark-{name}-{revision}",
                    "arguments": {},
                },
                ensure_ascii=False,
            ).encode(),
        )
    finally:
        current_caller.reset(token)
    if response.status != 200:
        raise ScenarioError(f"bootstrap {name} 失败：{response.status} {response.body!r}")
    return response


async def _finish_keyframe_generations(service) -> None:
    """确定性推进关键帧生成：每轮只生成前置已满足的帧，直到全部有成功候选。"""
    for _ in range(12):
        document = await service.generate_keyframe_batch(
            expected_revision=service.snapshot().revision
        )
        pending = [
            frame for frame in document.keyframe_plan.keyframes if frame.selected_asset_id is None
        ]
        await _observe_generations(service)
        document = service.snapshot_required()
        succeeded = {
            generation.target_id
            for generation in document.generations
            if generation.kind.value == "keyframe_image" and generation.phase.value == "succeeded"
        }
        if all(frame.id in succeeded for frame in document.keyframe_plan.keyframes):
            break
        if not pending:  # pragma: no cover - 防御性
            raise ScenarioError("关键帧 bootstrap 无进展。")
    else:  # pragma: no cover - 防御性
        raise ScenarioError("关键帧 bootstrap 轮次超限。")
    document = service.snapshot_required()
    for frame in document.keyframe_plan.keyframes:
        if frame.selected_asset_id is not None:
            continue
        candidates = [
            generation
            for generation in document.generations
            if generation.kind.value == "keyframe_image"
            and generation.target_id == frame.id
            and generation.phase.value == "succeeded"
            and generation.output_asset_id is not None
            and not generation.dismissed
        ]
        if not candidates:
            raise ScenarioError(f"关键帧 {frame.id} 没有成功候选。")
        await service.select_keyframe(
            keyframe_id=frame.id,
            asset_id=candidates[-1].output_asset_id,
            expected_revision=service.snapshot_required().revision,
        )


async def _observe_generations(service) -> None:
    """调用一次真实 observation，让合成 Provider 从 queued 走到 succeeded。"""
    from core.director_commands import DirectorCommand

    document = service.snapshot_required()
    generation_ids = [
        generation.id
        for generation in document.generations
        if generation.phase.value in {"queued", "running", "submitting"}
    ]
    if not generation_ids:
        return
    await service.execute_director_command(
        DirectorCommand(
            "generation.wait",
            document.revision,
            f"benchmark-observe-{document.revision}",
            {"generation_ids": generation_ids},
        )
    )


# ---------------------------------------------------------------------------
# 场景驱动
# ---------------------------------------------------------------------------


@dataclass
class Context:
    base: dict[str, Any]
    meter: Meter
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    workset: dict[str, Any] | None = None

    def namespace(self) -> dict[str, Any]:
        return {"base": self.base, **self.responses}


def load_scenario(name: str) -> dict[str, Any]:
    path = SCENARIO_DIR / f"{name}.json"
    if not path.is_file():
        raise ScenarioError(f"未知场景：{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def scenario_names() -> list[str]:
    return sorted(path.stem for path in SCENARIO_DIR.glob("*.json"))


def _walk(value: Any, path: str) -> list[Any]:
    """按 ``a.b[*].c`` 路径收集叶子值；用于把响应里的稳定 ID 抽成占位符。"""
    parts = path.split(".")
    current = [value]
    for part in parts:
        next_values: list[Any] = []
        for item in current:
            if part.endswith("[*]"):
                key = part[: -len("[*]")]
                if isinstance(item, dict) and isinstance(item.get(key), list):
                    next_values.extend(item[key])
            elif isinstance(item, dict) and part in item:
                next_values.append(item[part])
        current = next_values
    return current


def _keyframe_payload(workset: dict[str, Any]) -> dict[str, Any]:
    scenes = workset["core_facts"]["scenes"]
    proposals = []
    for scene in scenes:
        for shot in scene["shots"]:
            if not shot.get("planning_enabled", True):
                continue
            character_ids = [item["id"] for item in shot.get("visible_characters", [])]
            proposals.append(
                {
                    "shot_id": shot["id"],
                    "continues_from_previous_shot": False,
                    "start_prompt_text": f"{scene['title']}的静态首帧。",
                    "start_visible_character_ids": character_ids,
                    "start_character_references": [],
                    "start_environment_mode": None,
                    "start_environment_view_id": None,
                    "start_environment_none_reason": None,
                    "segments": [
                        {
                            "segment_id": segment["id"],
                            "frame_strategy": "both",
                            "end_prompt_text": f"{scene['title']}的静态尾帧。",
                            "end_visible_character_ids": character_ids,
                            "end_character_references": [],
                            "end_environment_mode": None,
                            "end_environment_view_id": None,
                            "end_environment_none_reason": None,
                        }
                        for segment in shot["segments"]
                    ],
                }
            )
    return {"shots": proposals}


def _location_payload(workset: dict[str, Any]) -> dict[str, Any]:
    """每个 Scene 一个新建室内地点；每个 Shot 绑定该地点的一个主机位视图。"""
    locations, scene_bindings, shot_bindings = [], [], []
    for index, scene in enumerate(workset["core_facts"]["scenes"]):
        key = f"place-{index}"
        view_key = f"{key}-main"
        locations.append(
            {
                "key": key,
                "name": scene["title"],
                "kind": "interior",
                "description": scene["setting"],
                "key_light": {"description": "冷蓝色天光", "azimuth_deg": 270},
                "master_prompt_text": f"{scene['setting']}无人物。",
                "fixtures": [
                    {
                        "key": f"{key}-sign",
                        "name": "站牌",
                        "description": "金属站牌",
                        "azimuth_deg": 0,
                    }
                ],
                "states": [],
                "views": [
                    {
                        "key": view_key,
                        "name": "主机位",
                        "purpose": "人眼高中景，覆盖本 Scene 全部 Shot",
                        "azimuth_deg": 0,
                        "look_at_fixture_id": None,
                        "yaw_offset_deg": None,
                        "pitch_deg": 0,
                        "hfov_deg": 65,
                        "state_id": None,
                        "refine_prompt_text": "",
                        "reference_view_ids": [],
                    }
                ],
            }
        )
        scene_bindings.append({"scene_id": scene["id"], "location_id": key, "state_id": None})
        shot_bindings.extend(
            {"shot_id": shot["id"], "view_id": view_key} for shot in scene["shots"]
        )
    return {
        "locations": locations,
        "scene_bindings": scene_bindings,
        "shot_bindings": shot_bindings,
    }


async def run_steps(client, scenario: dict[str, Any], context: Context) -> None:
    for step in scenario["steps"]:
        namespace = context.namespace()
        if step["action"] == "list_tools":
            listed = await client.list_tools()
            tools = listed.tools
            context.meter.tool_count = len(tools)
            context.meter.tools_list_bytes = sum(
                compact_bytes({"description": tool.description, "input_schema": tool.input_schema})
                for tool in tools
            )
            continue
        if step["action"] == "pages":
            resolved = resolve(step["arguments"], namespace)
            await _read_pages(client, step, resolved, context)
            continue
        if step["action"] == "keyframe_submit":
            if context.workset is None:
                raise ScenarioError("keyframe_submit 之前必须先读关键帧工作集。")
            resolved = resolve(step["arguments"], context.namespace())
            resolved["proposal"] = _keyframe_payload(context.workset)
            await _call_and_record(client, step, resolved, context, action="submit")
            continue
        if step["action"] == "location_submit":
            if context.workset is None:
                raise ScenarioError("location_submit 之前必须先读地点工作集。")
            resolved = resolve(step["arguments"], context.namespace())
            resolved["payload"]["proposal"] = _location_payload(context.workset)
            await _call_and_record(client, step, resolved, context, action="submit")
            continue
        if step["action"] == "wait":
            await _wait(client, step, context)
            continue
        try:
            resolved = resolve(step["arguments"], context.namespace())
        except KeyError as exc:
            raise ScenarioError(
                f"步骤 {step['id']} 的占位符缺失 {exc}；已捕获的步骤={sorted(context.responses)}"
            ) from None
        label = resolved.get("action", step["action"])
        await _call_and_record(client, step, resolved, context, action=str(label))


async def _call_and_record(client, step, arguments, context: Context, *, action: str):
    result = await client.call_tool(step["tool"], arguments)
    payload = result.structured_content or {}
    if not isinstance(payload, dict):
        raise ScenarioError(f"步骤 {step['id']} 返回了非对象 structured_content。")
    record = context.meter.record(
        step=step["id"],
        tool=step["tool"],
        action=action,
        arguments=arguments,
        result=payload,
        is_error=bool(result.is_error),
    )
    if step.get("assert", {}).get("no_error") and (
        result.is_error or payload.get("http_status") != 200
    ):
        raise ScenarioError(f"步骤 {step['id']} 失败：{json.dumps(payload, ensure_ascii=False)}")
    context.responses[step["id"]] = payload
    data = payload.get("data", payload)
    if step["tool"] == "read_professional_workset" and not result.is_error:
        context.workset = data
    if step.get("capture") and isinstance(data, dict):
        context.responses[step["capture"]] = data
    for capture_name, path in step.get("capture_ids", {}).items():
        values: list[str] = []
        for item in _walk(data, path):
            if isinstance(item, list):
                values.extend(str(value) for value in item)
            elif item is not None:
                values.append(str(item))
        context.responses[capture_name] = {"ids": values}
    return record


async def _read_pages(client, step, arguments, context: Context) -> None:
    """按 next_cursor 拼页；记录每轮请求字节与分页轮次。"""
    rounds = 0
    cursor = None
    chunks: list[str] = []
    first: dict[str, Any] | None = None
    while True:
        call_arguments = dict(arguments)
        if cursor is not None:
            call_arguments["cursor"] = cursor
        result = await client.call_tool(step["tool"], call_arguments)
        payload = result.structured_content or {}
        if not isinstance(payload, dict):
            raise ScenarioError(f"步骤 {step['id']} 返回了非对象 structured_content。")
        rounds += 1
        if result.is_error or payload.get("http_status") != 200:
            raise ScenarioError(
                f"步骤 {step['id']} 失败：{json.dumps(payload, ensure_ascii=False)}"
            )
        data = payload.get("data", payload)
        if first is None:
            first = payload
        pagination = data.get("pagination") if isinstance(data, dict) else None
        if isinstance(pagination, dict) and "content_chunk" in data:
            chunks.append(data["content_chunk"])
            cursor = pagination.get("next_cursor")
        else:
            cursor = None
        context.meter.record(
            step=step["id"],
            tool=step["tool"],
            action="pages",
            arguments=call_arguments,
            result=payload,
            is_error=bool(result.is_error),
            pagination_rounds=1,
        )
        if cursor is None:
            break
        if rounds > 50:
            raise ScenarioError(f"步骤 {step['id']} 分页轮次超限。")
    assembled: dict[str, Any] = first if first is not None else {}
    if chunks:
        assembled = json.loads("".join(chunks))
    result_payload = first if first is not None else {}
    merged = {"http_status": 200, "data": assembled}
    context.responses[step["id"]] = merged
    data = assembled.get("data", assembled) if isinstance(assembled, dict) else None
    if step["tool"] == "read_professional_workset":
        context.workset = data
    capture = step.get("capture")
    if capture and isinstance(data, dict):
        context.responses[capture] = data
    for capture_name, path in step.get("capture_ids", {}).items():
        values: list[str] = []
        for item in _walk(data, path):
            if isinstance(item, list):
                values.extend(str(value) for value in item)
            elif item is not None:
                values.append(str(item))
        context.responses[capture_name] = {"ids": values}
    if step.get("assert", {}).get("no_error") and not isinstance(result_payload, dict):
        raise ScenarioError(f"步骤 {step['id']} 未得到可解析结果。")


async def _wait(client, step, context: Context) -> None:
    """确定性等待：同一 idempotency_key 重试直到 wait_again 为 false。"""
    namespace = context.namespace()
    resolved = resolve(step["arguments"], namespace)
    while True:
        result = await client.call_tool(step["tool"], resolved)
        payload = result.structured_content or {}
        if not isinstance(payload, dict):
            raise ScenarioError(f"步骤 {step['id']} 返回了非对象 structured_content。")
        data = payload.get("data", {})
        wait_again = data.get("wait_again") if isinstance(data, dict) else None
        record = context.meter.record(
            step=step["id"],
            tool=step["tool"],
            action="wait",
            arguments=resolved,
            result=payload,
            is_error=bool(result.is_error),
        )
        record.wait_again = wait_again
        if result.is_error or payload.get("http_status") != 200:
            raise ScenarioError(
                f"步骤 {step['id']} 失败：{json.dumps(payload, ensure_ascii=False)}"
            )
        context.responses[step["id"]] = payload
        if wait_again is not True:
            return


# ---------------------------------------------------------------------------
# 运行入口
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    scenario: str
    summary: dict[str, Any]
    requests: list[dict[str, Any]]
    mcp_instructions_bytes: int
    agents_md_bytes: int


def _fixed_uuid_sequence() -> list[UUID]:
    """项目 ID 与其它随机 ID 用固定序列，保证跨运行逐字节一致。"""
    return [
        UUID(bytes=hashlib.sha256(f"storyrail-benchmark-{index}".encode()).digest()[:16])
        for index in range(64)
    ]


def _policy(project_id: str) -> dict[str, Any]:
    return {
        "version": 2,
        "external_mutations": True,
        "callers": [
            {
                "id": AGENT_CALLER_ID,
                "role": "agent",
                "project_ids": [project_id],
                "capabilities": [
                    "project.read",
                    "project.mutate",
                    "project.propose",
                    "project.execute",
                ],
                "expires_at": 4102444800,
                "token_sha256": hashlib.sha256(AGENT_TOKEN.encode()).hexdigest(),
                "grants": [],
            }
        ],
    }


class BenchmarkServer:
    """本进程内的真实 loopback Core；合成媒体 Provider；不接真实作品。"""

    def __init__(self, root: Path) -> None:
        self.workspaces = ProjectWorkspaceStore(root / "stories")
        self.providers = provider_set(root / "providers")
        self.event_loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self.event_loop.run_forever, daemon=True)
        self.policy_path = root / "policy.json"
        self.policy_path.write_text(json.dumps(_policy("0" * 32)))
        self.policy_path.chmod(0o600)
        self._server: StoryRailHttpServer | None = None
        self._server_thread: threading.Thread | None = None
        self.base_url = ""

    def service(self, project_id: str) -> StructuredDirectorService:
        return StructuredDirectorService(
            self.workspaces.structured_director_store(project_id),
            service_registry(self.providers),
        )

    def start(self, project_id: str) -> None:
        self.policy_path.write_text(json.dumps(_policy(project_id)))
        self.policy_path.chmod(0o600)
        self._loop_thread.start()
        api = StoryRailApi(self.workspaces, self.service)
        self._server = StoryRailHttpServer(
            ("127.0.0.1", 0), api, self.event_loop, access_policy_file=self.policy_path
        )
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        self._loop_thread.join(timeout=5)
        self.event_loop.close()


async def _drive(
    scenario_name: str,
    root: Path,
) -> RunResult:
    os.environ.setdefault("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", WAIT_MAX_SECONDS)
    os.environ.setdefault("STORYRAIL_GENERATION_WAIT_POLL_SECONDS", WAIT_INTERVAL_SECONDS)
    scenario = load_scenario(scenario_name)
    server = BenchmarkServer(root)
    token_file = root / "agent_token"
    token_file.write_text(AGENT_TOKEN)
    token_file.chmod(0o600)
    import uuid as uuid_module

    fixed = _fixed_uuid_sequence()
    original_uuid4 = uuid_module.uuid4
    counter = {"index": 0}

    def deterministic_uuid4() -> UUID:
        value = fixed[counter["index"] % len(fixed)]
        counter["index"] += 1
        return value

    uuid_module.uuid4 = deterministic_uuid4  # type: ignore[assignment]
    try:
        project = server.workspaces.create(
            "基准合成项目",
            PLAN_MARKDOWN,
            aspect_ratio=ProjectAspectRatio.LANDSCAPE,
            narration_languages=tuple(NarrationLanguage),
        )
        project_id = project.id
        store = server.workspaces.structured_director_store(project_id)
        service = server.service(project_id)
        base = await bootstrap(store, service, scenario["bootstrap"])
    finally:
        uuid_module.uuid4 = original_uuid4  # type: ignore[assignment]
    server.start(project_id)
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "integrations.storyrail_mcp",
            "--core-origin",
            server.base_url,
            "--token-file",
            str(token_file),
        ],
        cwd=ROOT,
    )
    context = Context(base=base, meter=Meter())
    try:
        async with Client(params) as client:
            await run_steps(client, scenario, context)
    finally:
        server.stop()
    return RunResult(
        scenario=scenario_name,
        summary=context.meter.summary(),
        requests=[record.as_dict() for record in context.meter.records],
        mcp_instructions_bytes=_mcp_instructions_bytes(),
        agents_md_bytes=(ROOT / "AGENTS.md").stat().st_size,
    )


def _mcp_instructions_bytes() -> int:
    import inspect

    import integrations.storyrail_mcp.app as app

    source = inspect.getsource(app)
    marker = "instructions=("
    start = source.index(marker) + len(marker)
    end = source.index("\n        ),\n", start)
    fragments = __import__("re").findall(r'"((?:[^"\\]|\\.)*)"', source[start:end])
    return len("".join(fragments).encode("utf-8"))


def run_scenario(name: str, workdir: Path | None = None) -> RunResult:
    owns_dir = workdir is None
    # macOS 的 /tmp 与 /var 是符号链接；Core 拒绝符号链接祖先路径。
    root = (
        Path(tempfile.mkdtemp(prefix="storyrail-benchmark-")).resolve()
        if workdir is None
        else workdir.resolve()
    )
    try:
        return asyncio.run(_drive(name, root))
    finally:
        if owns_dir:
            shutil.rmtree(root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="all")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="把单场景结果打到 stdout")
    args = parser.parse_args(argv)
    names = scenario_names() if args.scenario == "all" else [args.scenario]
    results = {name: run_scenario(name) for name in names}
    payload = {
        name: {
            "summary": result.summary,
            "requests": result.requests,
            "mcp_instructions_bytes": result.mcp_instructions_bytes,
            "agents_md_bytes": result.agents_md_bytes,
        }
        for name, result in results.items()
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if args.json or args.out is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
