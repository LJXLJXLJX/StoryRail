"""外部 Agent 保存视频 recipe 输入：与人类同一条 video.update_recipe_inputs 校验路径。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from urllib.parse import urlencode

import pytest
from conftest import Journey, JourneyStepError
from golden_provider_requests import mp4_bytes, png_bytes, wav_bytes
from mcp import Client
from test_director_commands import _visual_project
from test_storyrail_mcp import endpoint

from core.application.caller import AccessDenied, Caller, authorize_command
from integrations.storyrail_mcp.app import VideoPrompt, create_server, published_tool_schema


def _upload(journey: Journey, label: str, content: bytes, media_type: str) -> str:
    query = {"expected_revision": journey._revision(), "filename": label}
    route = "media"
    if media_type.startswith("image/"):
        route, query["category"] = "images", "keyframe"
    path = f"{journey.resource}/assets/{route}?" + urlencode(query)
    status, body = journey._server.upload(path, content, media_type)
    assert status < 400, body
    digest = hashlib.sha256(content).hexdigest()
    return next(item["id"] for item in journey.document()["assets"] if item["sha256"] == digest)


def _workset(journey: Journey, scene_id: str, segment_id: str) -> dict:
    """按 next_cursor 拼接分页的 video_prompt 工作集。"""
    chunks: list[str] = []
    cursor = None
    while True:
        arguments = {
            "capability": "video_prompt",
            "scope": {"scene_ids": [scene_id]},
            "target_ids": [segment_id],
            "page_bytes": 24576,
        }
        if cursor is not None:
            arguments["cursor"] = cursor
        data = journey._command("project.get_workset", arguments, role="agent")["data"]
        if "content_chunk" not in data:
            return data
        chunks.append(data["content_chunk"])
        cursor = data["pagination"]["next_cursor"]
        if cursor is None:
            return json.loads("".join(chunks))


def _segment_ids(snapshot: dict) -> list[tuple[str, str]]:
    return [
        (scene["id"], segment["id"])
        for scene in snapshot["director_script"]["scenes"]
        for segment in scene["segments"]
    ]


def _video(snapshot: dict, segment_id: str) -> dict:
    return next(
        item for item in snapshot["video_plan"]["segments"] if item["segment_id"] == segment_id
    )


@pytest.fixture
def ref2va_journey(journey: Journey):
    journey.create_project(title="Agent 视频输入")
    journey.propose_references()
    character_id = journey.snapshot()["reference_library"]["characters"][0]["id"]
    journey.approve_references()
    journey.apply_script(
        scenes=[
            journey.drama_scene(character_id),
            journey.drama_scene(character_id, title="第二场"),
        ]
    )
    journey.unlock_visual_production()
    # 每帧不同字节，避免内容去重把不同 Scene 的关键帧合并成同一 Asset。
    journey._server.providers.image._contents = [png_bytes(f"关键帧{i}.png") for i in range(4)]
    journey.generate_keyframes()
    return journey


def test_agent_binds_ref2va_inputs_and_rejects_invalid_requests(ref2va_journey: Journey):
    journey = ref2va_journey
    (scene, segment), (other_scene, other_segment) = _segment_ids(journey.snapshot())
    assert _video(journey.snapshot(), segment)["active_recipe"] == "minimax_h3.ref2va"
    audio = _upload(journey, "小满原声.wav", wav_bytes("小满原声.wav", 1.5), "audio/wav")
    video = _upload(journey, "推镜参考.mp4", mp4_bytes("推镜参考.mp4", 3.0), "video/mp4")
    short = _upload(journey, "过短.mp4", mp4_bytes("过短.mp4", 1.0), "video/mp4")
    image = _upload(journey, "站牌字样.png", png_bytes("站牌字样.png"), "image/png")
    # 本 Scene 一帧再生成一个候选但不选择：未选择的生成候选不列入可绑定素材。
    first_frame = next(
        frame
        for frame in journey.snapshot()["keyframe_plan"]["keyframes"]
        if frame["owner_segment_id"] == segment
    )
    journey._server.providers.image._contents = [png_bytes("未选候选.png")]
    journey._command("keyframe.generate", {"keyframe_id": first_frame["id"]}, role="agent")
    snapshot = journey.wait_generations(kind="keyframe_image")
    unselected = [
        item["output_asset_id"]
        for item in snapshot["generations"]
        if item["kind"] == "keyframe_image" and item["target_id"] == first_frame["id"]
    ][-1]
    assert unselected != first_frame["selected_asset_id"]

    workset = _workset(journey, scene, segment)
    facts = workset["core_facts"]
    assert facts["recipe_inputs"] == {"bindings": {}, "params": {}}
    bindable = {item["asset_id"]: item for item in facts["bindable_assets"]}
    assert bindable[audio] == {
        "asset_id": audio,
        "name": "小满原声.wav",
        "media_type": "audio/wav",
        "duration_seconds": 1.5,
        "slots": ["reference_audios"],
    }
    assert bindable[video]["slots"] == ["reference_videos"]
    assert bindable[image]["slots"] == ["additional_images"]
    frames = journey.snapshot()["keyframe_plan"]["keyframes"]
    own = {item["selected_asset_id"] for item in frames if item["owner_segment_id"] == segment}
    others = {
        item["selected_asset_id"] for item in frames if item["owner_segment_id"] == other_segment
    }
    assert own <= set(bindable) and others.isdisjoint(own)
    assert others.isdisjoint(bindable)
    assert short not in bindable and unselected not in bindable

    arguments = {
        "scope": {"scene_ids": [scene]},
        "segment_id": segment,
        "prompt_text": "<Picture 1> 小满抬头，用 <Audio 1> 的声音说“还会来吗？”",
        "bindings": {
            "additional_images": [{"asset_id": image, "description": "站牌上的站名字样"}],
            "reference_audios": [{"asset_id": audio, "description": "小满的音色参考"}],
            "reference_videos": [{"asset_id": video, "description": "缓慢推近的运镜参考"}],
        },
        "params": {},
    }
    preview = journey._command(
        "project.preview_impact",
        {
            "command": {
                "name": "video.update_recipe_inputs",
                "expected_revision": journey._revision(),
                "idempotency_key": "preview",
                "arguments": arguments,
            }
        },
        role="human",
    )["data"]
    assert preview["will_write"] is True and preview["changed_ids"] == [segment]

    before = journey.document()
    invalid = [
        ({**arguments, "scope": {"scene_ids": [other_scene]}}, "超出已授权 Scene scope"),
        (
            {**arguments, "bindings": {"first_frame": [{"asset_id": image, "description": None}]}},
            "不支持槽位",
        ),
        (
            {
                **arguments,
                "bindings": {"reference_videos": [{"asset_id": video, "description": "参考"}] * 4},
            },
            "0 到 3 项",
        ),
        (
            {
                **arguments,
                "bindings": {"reference_audios": [{"asset_id": image, "description": "图片"}]},
            },
            "只接受 audio/wav",
        ),
        (
            {
                **arguments,
                "bindings": {"reference_audios": [{"asset_id": audio, "description": None}]},
            },
            "必须填写说明",
        ),
        ({**arguments, "params": {"seed": 1}}, "多出 seed"),
    ]
    for value, message in invalid:
        with pytest.raises(JourneyStepError) as raised:
            journey._command("video.update_recipe_inputs", value, role="agent")
        assert raised.value.status == 409
        assert message in raised.value.body["error"]["message"]
        assert journey.document() == before

    saved = journey._command("video.update_recipe_inputs", arguments, role="agent")
    assert saved["receipt"]["status"] == "succeeded"
    assert saved["receipt"]["changed_ids"] == preview["changed_ids"]
    stored = _video(journey.snapshot(), segment)
    assert stored["prompt_text"] == arguments["prompt_text"]
    assert stored["recipes"]["minimax_h3.ref2va"] == {
        "bindings": arguments["bindings"],
        "params": {},
    }
    reread = _workset(journey, scene, segment)["core_facts"]
    assert reread["recipe_inputs"] == {"bindings": arguments["bindings"], "params": {}}
    # 写入回执直接带回与工作集一致的输入摘要，Agent 无需重读整份工作集。
    digest = saved["data"]
    assert digest["segment_id"] == segment
    assert digest["recipe_id"] == "minimax_h3.ref2va"
    assert digest["prompt_chars"] == len(arguments["prompt_text"])
    assert digest["recipe_inputs"] == reread["recipe_inputs"]
    assert digest["asset_inputs"] == reread["asset_inputs"]
    assert digest["prompt_problems"] == reread["prompt_problems"]
    assert digest["dialogue_audio"] == {
        key: reread["dialogue_audio"][key] for key in ("error", "unbound_lines")
    }
    assert reread["context"]["actual_provider_inputs"]["allowed_asset_reference_labels"] == [
        "<Picture 1>",
        "<Picture 2>",
        "<Picture 3>",
        "<Audio 1>",
        "<Video 1>",
    ]

    # 候选选择、清除选择仍只属于人类。
    with pytest.raises(JourneyStepError) as denied:
        journey._command(
            "video.clear_selection",
            {"scope": {"scene_ids": [scene]}, "segment_id": segment},
            role="agent",
        )
    assert denied.value.status == 403


def test_agent_allowlist_keeps_human_video_operations_closed():
    caller = Caller(
        "agent",
        "agent",
        frozenset({"a" * 32}),
        frozenset({"project.mutate", "project.execute"}),
        4102444800,
        (),
        True,
    )
    authorize_command(caller, "a" * 32, {"name": "video.update_recipe_inputs"})
    with pytest.raises(AccessDenied):
        authorize_command(caller, "a" * 32, {"name": "video.clear_selection"})


def test_save_video_prompt_schema_publishes_compact_recipe_inputs():
    schema = published_tool_schema("save_video_prompt", VideoPrompt)
    assert "$defs" not in schema
    assert schema["properties"]["recipe_inputs"] == {"type": "object"}
    assert "recipe_inputs" not in schema["required"]
    base = {
        "project_id": "a" * 32,
        "expected_revision": 1,
        "idempotency_key": "k",
        "scene_ids": ["b" * 32],
        "segment_id": "c" * 32,
        "prompt_text": "正文",
    }
    VideoPrompt.model_validate({**base, "recipe_inputs": {"bindings": {}, "params": {}}})
    # Core 按槽位、按键合并，bindings 与 params 都可以省略。
    assert VideoPrompt.model_validate({**base, "recipe_inputs": {"bindings": {}}})
    assert VideoPrompt.model_validate({**base, "attach_dialogue_audio": True})
    for value in (
        {"bindings": {}, "params": {}, "extra": 1},
        {"bindings": {"reference_audios": [{"asset_id": "d" * 32}]}, "params": {}},
    ):
        with pytest.raises(ValueError):
            VideoPrompt.model_validate({**base, "recipe_inputs": value})


def test_mcp_save_video_prompt_translates_recipe_inputs(tmp_path):
    (tmp_path / "project").mkdir()
    store, service, document, _ = asyncio.run(_visual_project(str(tmp_path / "project")))
    scene = document.director_script.scenes[0]
    segment = scene.segments[0]
    caller = Caller(
        "recipe-inputs",
        "agent",
        frozenset({document.project_id}),
        frozenset({"project.read", "project.mutate", "project.execute"}),
        4102444800,
        (),
        True,
    )

    async def run(bridge):
        async with Client(create_server(bridge)) as client:
            base = {
                "project_id": document.project_id,
                "scene_ids": [scene.id],
                "segment_id": segment.id,
                "prompt_text": "固定机位，小满抬头。",
            }
            inputs = await client.call_tool(
                "save_video_prompt",
                {
                    **base,
                    "expected_revision": document.revision,
                    "idempotency_key": "inputs",
                    "recipe_inputs": {"bindings": {}, "params": {}},
                },
            )
            assert not inputs.is_error, inputs.structured_content
            saved = store.read()
            assert saved.revision == document.revision + 1
            assert saved.application_requests[-1].operation == "video.update_recipe_inputs"
            rejected = await client.call_tool(
                "save_video_prompt",
                {
                    **base,
                    "expected_revision": saved.revision,
                    "idempotency_key": "bad",
                    "recipe_inputs": {
                        "bindings": {"first_frame": [{"asset_id": "f" * 32, "description": None}]},
                        "params": {},
                    },
                },
            )
            assert rejected.is_error and store.read() == saved
            prompt = await client.call_tool(
                "save_video_prompt",
                {
                    **base,
                    "expected_revision": saved.revision,
                    "idempotency_key": "prompt",
                    "prompt_text": "固定机位，小满低头。",
                },
            )
            assert not prompt.is_error
            assert store.read().application_requests[-1].operation == "video.set_prompt"
            # 只带 attach_dialogue_audio 也翻译为 video.update_recipe_inputs。
            current = store.read()
            attach = await client.call_tool(
                "save_video_prompt",
                {
                    **base,
                    "expected_revision": current.revision,
                    "idempotency_key": "attach",
                    "attach_dialogue_audio": True,
                },
            )
            assert attach.is_error and store.read() == current
            assert "尚未选择 TTS 音频" in attach.structured_content["error"]["message"]

    with endpoint(tmp_path, store, service, caller) as (_, bridge):
        asyncio.run(run(bridge))
