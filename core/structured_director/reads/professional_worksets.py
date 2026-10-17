"""当前 revision 的专业读取入口；没有执行器、业务写入或任意文件访问。"""

import hashlib
import json

from core.director_proposals.keyframe_codec import _output_schema as keyframe_schema
from core.director_proposals.location_codec import output_schema as location_schema
from core.director_proposals.narration_codec import _OUTPUT_SCHEMA as NARRATION_SCHEMA
from core.director_proposals.professional_contracts import CONTRACTS, read_contract
from core.director_proposals.reference_library_codec import REFERENCE_LIBRARY_OUTPUT_SCHEMA
from core.director_proposals.schema_gen import narration_language_schema
from core.director_proposals.script_codec import _OUTPUT_SCHEMA as SCRIPT_SCHEMA
from core.director_proposals.video_prompt import OUTPUT_SCHEMA as H3_SCHEMA

from ..codec.keyframe import serialize_character_references
from ..planning_inputs import (
    keyframe_inputs,
    location_inputs,
    narration_inputs,
    reference_characters,
)
from ..prompt_worksets import image_prompt_guide, video_prompt_workset
from ..script_index import scene_segments
from .common import _exact_arguments, _ids, _json_value
from .semantic_projection import build_semantic_projection, build_semantic_tree
from .workflow_state import workflow_state

_CAPABILITY_ACTION_NAMESPACE = {
    "reference_library": "reference",
    "script": "script",
    "narration": "narration",
    "keyframe": "keyframe",
    "location": "location",
    "video_prompt": "video",
}

_AGENT_RESULT_MAX_BYTES = 64 * 1024
_AGENT_PAGE_BYTES = 24 * 1024
_AGENT_MIN_PAGE_BYTES = 4 * 1024


def _content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_if_hash(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        raise ValueError("if_hash 必须是 64 位小写十六进制内容 hash。")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("if_hash 必须是 64 位小写十六进制内容 hash。") from exc
    return value


def _saved_keyframe_plan(document, scene_ids):
    plan = document.keyframe_plan
    if plan is None:
        return {
            "status": "not_established",
            "source_script_revision": None,
            "segments": [],
            "keyframes": [],
        }
    script = document.director_script
    if script is None:
        raise ValueError("Keyframe 计划缺少当前导演脚本。")
    scoped_segment_ids = {
        segment.id
        for scene in script.scenes
        if scene.id in scene_ids
        for segment in scene_segments(scene)
    }
    bindings = [item for item in plan.segments if item.segment_id in scoped_segment_ids]
    frame_bindings: dict[str, list[dict[str, str]]] = {}
    for binding in bindings:
        frame_bindings.setdefault(binding.start_keyframe_id, []).append(
            {"segment_id": binding.segment_id, "slot": "start"}
        )
        frame_bindings.setdefault(binding.end_keyframe_id, []).append(
            {"segment_id": binding.segment_id, "slot": "end"}
        )
    frame_ids = set(frame_bindings)
    return {
        "status": "established",
        "source_script_revision": plan.source_script_revision,
        "segments": [
            {
                "segment_id": item.segment_id,
                "start_keyframe_id": item.start_keyframe_id,
                "end_keyframe_id": item.end_keyframe_id,
                "start_enabled": item.start_enabled,
                "end_enabled": item.end_enabled,
                "reference_asset_ids": list(item.reference_asset_ids),
            }
            for item in bindings
        ],
        "keyframes": [
            {
                "id": item.id,
                "owner_segment_id": item.owner_segment_id,
                "predecessor_keyframe_id": item.predecessor_keyframe_id,
                "prompt_text": item.prompt_text,
                "visible_character_ids": list(item.visible_character_ids),
                "character_references": serialize_character_references(item),
                "environment_mode": item.environment_mode.value,
                "environment_view_id": item.environment_view_id,
                "environment_none_reason": item.environment_none_reason,
                "selected_asset_id": item.selected_asset_id,
                "bindings": frame_bindings[item.id],
            }
            for item in plan.keyframes
            if item.id in frame_ids
        ],
    }


def _location_library_facts(document):
    """完整地点库加上派生状态：主图是否已选、是否已按当前主图标定、视图裁切/选图是否就绪。"""
    result = []
    for location in document.location_library.locations:
        item = _json_value(location)
        item["master_selected"] = location.master.selected_asset_id is not None
        item["calibrated"] = location.calibrated
        for view, value in zip(location.views, item["views"], strict=True):
            value["has_crop"] = view.crop_asset_id is not None
            value["has_selected_image"] = view.selected_asset_id is not None
        result.append(item)
    return result


def _keyframe_location_views(document):
    """Keyframe 规划可引用的全部地点视图（Keyframe 可覆盖 Shot 绑定）。

    每项带所属地点名与状态、purpose 和已选图；`selected_asset_id` 为 null 时可以规划，
    但生成前必须先选图或把帧改为 none。
    """
    result = []
    for location in document.location_library.locations:
        states = {item.id: item.name for item in location.states}
        result.extend(
            {
                "view_id": view.id,
                "name": view.name,
                "purpose": view.purpose,
                "location_id": location.id,
                "location_name": location.name,
                "location_kind": location.kind.value,
                "state_id": view.state_id,
                "state_name": None if view.state_id is None else states.get(view.state_id),
                "selected_asset_id": view.selected_asset_id,
            }
            for view in location.views
        )
    return result


def contract_read(document, arguments):
    _exact_arguments(
        arguments,
        required={"capability"},
        optional={"if_hash", "include"},
    )
    include = arguments.get("include", [])
    if not isinstance(include, list) or any(item != "consistency-review" for item in include):
        raise ValueError("include 只接受 consistency-review。")
    if len(include) != len(set(include)):
        raise ValueError("include 不能重复。")
    body = read_contract(arguments["capability"], include=tuple(include))
    digest = _content_hash(body)
    if_hash = _validate_if_hash(arguments.get("if_hash"))
    if if_hash is not None and if_hash == digest:
        return {"unchanged": True, "hash": digest}
    return {
        "project_id": document.project_id,
        "hash": digest,
        **body,
    }


def contract_page_read(document, arguments):
    _exact_arguments(
        arguments,
        required={"capability"},
        optional={"if_hash", "include", "cursor", "page_bytes"},
    )
    query = {"capability": arguments["capability"]}
    if "if_hash" in arguments:
        query["if_hash"] = arguments["if_hash"]
    if "include" in arguments:
        query["include"] = arguments["include"]
    return _agent_page(
        contract_read(document, query),
        query={"project_id": document.project_id, "capability": arguments["capability"]},
        cursor=arguments.get("cursor"),
        page_bytes=arguments.get("page_bytes", _AGENT_PAGE_BYTES),
    )


def speech_recipe(provider_recipes: list[dict]) -> dict | None:
    """旁白合成当前生效的 recipe。

    Agent 只填写其中 editable_params，按 recipe_id 写入 recipe_params。
    """
    return next(
        (item for item in provider_recipes if item["capability"] == "speech.synthesize"), None
    )


def workset_read(
    document, arguments, *, provider_recipes: list[dict] | None = None, provider_catalog=None
):
    _exact_arguments(
        arguments,
        required={"capability", "scope"},
        optional={"target_ids", "if_hash"},
    )
    capability = arguments["capability"]
    if not isinstance(capability, str) or capability not in CONTRACTS:
        raise ValueError("未知专业能力。")
    scope = arguments["scope"]
    targets = _ids(arguments["target_ids"], "target_ids") if "target_ids" in arguments else None
    if capability in {"reference_library", "script"}:
        if scope != {"project_id": document.project_id} or targets is not None:
            raise ValueError("首次专业草稿必须指定当前项目 scope，不能带 target_ids。")
        facts = {"director_plan_markdown": document.director_plan_markdown}
        schema = REFERENCE_LIBRARY_OUTPUT_SCHEMA
        if capability == "script":
            facts["characters"] = _json_value(reference_characters(document))
            facts["speech_recipe"] = speech_recipe(provider_recipes or [])
            schema = SCRIPT_SCHEMA
        provenance = ["director_plan_markdown", "reference_library.characters"]
    elif capability == "location":
        if scope != {"project_id": document.project_id} or targets is not None:
            raise ValueError("地点规划工作集使用当前项目 scope，不能带 target_ids。")
        scenes, _existing = location_inputs(document)
        facts = {
            "director_plan_markdown": document.director_plan_markdown,
            "aspect_ratio": document.aspect_ratio.value,
            "scenes": _json_value(scenes),
            "location_library": _location_library_facts(document),
            "image_prompt": image_prompt_guide(provider_catalog),
        }
        schema = location_schema()
        provenance = [
            "director_plan_markdown",
            "director_script.scenes",
            "reference_library.characters",
            "location_library",
        ]
    else:
        # 使用既有投影校验 Scene ID、重复项、scope，不能静默回退全项目。
        build_semantic_projection(document, {"level": "scene", "scope": scope})
        scene_ids = tuple(scope["scene_ids"])
        if targets is not None and len(targets) > 100:
            raise ValueError("target_ids 最多包含 100 项。")
        provenance = ["director_script", "reference_library", "assets"]
        if capability == "video_prompt":
            if targets is None or len(targets) != 1:
                raise ValueError("视频提示词工作集必须指定一个 Segment。")
            build_semantic_projection(
                document, {"level": "segment", "scope": scope, "ids": list(targets)}
            )
            facts, schema = (
                video_prompt_workset(
                    document,
                    targets[0],
                    provider_recipes=provider_recipes,
                    provider_catalog=provider_catalog,
                ),
                H3_SCHEMA,
            )
        elif capability == "keyframe":
            if targets is not None:
                build_semantic_projection(
                    document, {"level": "shot", "scope": scope, "ids": list(targets)}
                )
            scenes, shots, boundaries = keyframe_inputs(document, tuple(targets or scene_ids))
            facts = {
                "scenes": _json_value(scenes),
                "context_shot_ids": [shot.id for scene in scenes for shot in scene.shots],
                "writable_shot_ids": list(shots),
                "target_shot_ids": list(shots),
                "required_shared_boundaries": _json_value(boundaries),
                "aspect_ratio": document.aspect_ratio.value,
                "saved_keyframe_plan": _saved_keyframe_plan(document, scene_ids),
                "location_views": _keyframe_location_views(document),
                "image_prompt": image_prompt_guide(provider_catalog),
            }
            schema = keyframe_schema(scenes)
            provenance.extend(["keyframe_plan", "generations", "location_library"])
        else:
            cues = narration_inputs(document)
            scoped_ids = {
                cue.id
                for scene in document.director_script.scenes
                if scene.id in scene_ids
                for cue in scene.narration_cues
            }
            if targets is not None and set(targets) - scoped_ids:
                raise ValueError("Cue 未知或越出 scope。")
            selected_ids = set(targets) if targets is not None else scoped_ids
            facts = {
                "cues": _json_value(tuple(c for c in cues if c.id in selected_ids)),
                "story": build_semantic_tree(document, scene_ids, full_text=True),
                "speech_recipe": speech_recipe(provider_recipes or []),
            }
            schema = NARRATION_SCHEMA
    if capability in {"reference_library", "script", "narration"}:
        facts["narration_languages"] = [item.value for item in document.narration_languages]
        provenance.append("narration_languages")
    if capability in {"reference_library", "script"}:
        schema = narration_language_schema(schema, document.narration_languages)
    workflow = workflow_state(document)
    action_namespace = _CAPABILITY_ACTION_NAMESPACE[capability]
    blocked = workflow["blocked_actions"].get(action_namespace)
    not_current_stage = capability != workflow["current_stage"]
    result = {
        "workflow": workflow,
        "observation_revision": document.revision,
        "not_current_stage": not_current_stage,
        "not_current_stage_semantics": "informational_primary_workflow_relevance_only",
        "mutation_blocked": blocked is not None,
        "mutation_blocked_reason": None if blocked is None else blocked["reason"],
        "mutation_blocked_semantics": (
            "known_workflow_prerequisite_only_final_authorization_occurs_on_write"
        ),
        "workset_version": 1,
        "project_id": document.project_id,
        "source_revision": document.revision,
        "capability": capability,
        "scope": scope,
        "target_ids": targets,
        "core_facts": facts,
        "output_schema": schema,
        "provenance": {"authority": "project.json", "fields": provenance},
        "contract": {"capability": capability, "read_command": "project.get_contract"},
    }
    if_hash = _validate_if_hash(arguments.get("if_hash"))
    if if_hash is not None:
        digest = _content_hash(result)
        if if_hash == digest:
            return {
                "unchanged": True,
                "hash": digest,
                "source_revision": document.revision,
            }
        result["hash"] = digest
    return result


def workset_page_read(
    document, arguments, *, provider_recipes: list[dict] | None = None, provider_catalog=None
):
    _exact_arguments(
        arguments,
        required={"capability", "scope"},
        optional={"target_ids", "if_hash", "cursor", "page_bytes"},
    )
    query = {key: value for key, value in arguments.items() if key not in {"cursor", "page_bytes"}}
    return _agent_page(
        workset_read(
            document, query, provider_recipes=provider_recipes, provider_catalog=provider_catalog
        ),
        query={"project_id": document.project_id, "revision": document.revision, **query},
        cursor=arguments.get("cursor"),
        page_bytes=arguments.get("page_bytes", _AGENT_PAGE_BYTES),
    )


def _agent_page(result, *, query, cursor, page_bytes):
    if (
        isinstance(page_bytes, bool)
        or not isinstance(page_bytes, int)
        or not _AGENT_MIN_PAGE_BYTES <= page_bytes <= _AGENT_PAGE_BYTES
    ):
        raise ValueError(
            f"page_bytes 必须是 {_AGENT_MIN_PAGE_BYTES} 到 {_AGENT_PAGE_BYTES} 的整数。"
        )
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if cursor is None and len(encoded) <= _AGENT_RESULT_MAX_BYTES:
        return result
    content_sha256 = hashlib.sha256(encoded).hexdigest()
    query_digest = hashlib.sha256(
        json.dumps(
            {**query, "page_bytes": page_bytes, "content_sha256": content_sha256},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    offset = 0
    if cursor is not None:
        if not isinstance(cursor, str):
            raise ValueError("专业读取 cursor 不合法。")
        parts = cursor.split(":")
        if (
            len(parts) != 2
            or parts[0] != query_digest
            or not parts[1].isascii()
            or not parts[1].isdigit()
        ):
            raise ValueError("cursor 不属于当前项目、revision 或专业查询。")
        offset = int(parts[1])
        if offset <= 0 or offset >= len(encoded):
            raise ValueError("cursor 超出专业读取结果范围。")
    end = min(offset + page_bytes, len(encoded))
    while end > offset:
        try:
            content_chunk = encoded[offset:end].decode("utf-8")
            break
        except UnicodeDecodeError:
            end -= 1
    else:  # pragma: no cover - page minimum ensures at least one full codepoint
        raise RuntimeError("专业读取分页失败。")
    next_cursor = f"{query_digest}:{end}" if end < len(encoded) else None
    return {
        "project_id": result["project_id"],
        "observation_revision": result.get("source_revision", query.get("revision")),
        "capability": result["capability"],
        "scope": result.get("scope"),
        "target_ids": result.get("target_ids"),
        "pagination": {
            "mode": "json_utf8_chunks",
            "content_sha256": content_sha256,
            "total_bytes": len(encoded),
            "offset": offset,
            "byte_count": end - offset,
            "next_cursor": next_cursor,
            "is_last": next_cursor is None,
            "instruction": (
                "使用相同 project/revision/capability/scope/target_ids/page_bytes 和 next_cursor "
                "续读；按 offset 拼接 content_chunk 后校验 SHA-256 并解析 JSON。"
            ),
        },
        "content_chunk": content_chunk,
    }
