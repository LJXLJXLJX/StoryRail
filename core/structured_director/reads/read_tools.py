from __future__ import annotations

import re
from typing import Any

from core.director_commands import parse_director_command

from ..candidate_eligibility import generation_is_reviewable
from ..models import (
    Asset,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from ..script_index import scene_segments, script_segments
from .batch_observation import batch_observation, owned_batch_id_for_run
from .common import ReadResultTooLarge as ReadResultTooLarge
from .common import (
    _asset_summary,
    _exact_arguments,
    _id,
    _ids,
    _json_value,
    _validate_result_bounds,
)
from .common import _object_count as _object_count
from .dependencies import _get_dependencies, _selected_assets
from .execution_reads import asset_manifest, handoff_read, request_read
from .impact import preview_command_impact
from .professional_worksets import contract_page_read, workset_page_read
from .proposal_observation import proposal_observation
from .semantic_projection import build_semantic_projection, build_semantic_tree

_MAX_RESULT_BYTES = 128 * 1024
_MAX_RESULT_OBJECTS = 500
_DEFAULT_PAGE_SIZE = 30
_MAX_PAGE_SIZE = 100


def execute_project_read(
    document: StructuredDirectorDocument,
    name: str,
    arguments: dict[str, object],
    *,
    provider_recipes: list[dict] | None = None,
    provider_catalog=None,
) -> dict[str, object]:
    readers = {
        "project.get_asset_manifest": asset_manifest,
        "project.get_handoff": handoff_read,
        "project.get_workflow_state": handoff_read,
        "project.get_request": request_read,
        "project.get_contract": contract_page_read,
        "project.get_workset": lambda current, args: workset_page_read(
            current,
            args,
            provider_recipes=provider_recipes or [],
            provider_catalog=provider_catalog,
        ),
        "project.get_projection": lambda current, args: build_semantic_projection(
            current, args, provider_recipes=provider_recipes, provider_catalog=provider_catalog
        ),
        "project.locate_story": _locate_story,
        "project.get_outline": _get_outline,
        "project.get_entities": _get_entities,
        "project.get_scene": _get_scene,
        "project.get_target": _get_target,
        "project.list_candidates": _list_candidates,
        "project.get_dependencies": lambda current, args: _get_dependencies(
            current, args, catalog=provider_catalog
        ),
        "project.preview_impact": _preview_impact,
        "run.get_status": _get_run_status,
    }
    reader = readers.get(name)
    if reader is None:
        raise ValueError(f"尚未注册 Director read tool：{name}。")
    result = reader(document, arguments)
    _validate_result_bounds(result)
    return result


def _get_run_status(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    _exact_arguments(arguments, required={"run_id"})
    run_id = _id(arguments["run_id"], "run_id")
    run = next((item for item in document.director_runs if item.id == run_id), None)
    if run is None:
        raise ValueError("Director run 不存在。")
    batch_id = owned_batch_id_for_run(document, run_id)

    return {
        "project_revision": document.revision,
        "run": _json_value(run),
        "proposal_observation": proposal_observation(document, run),
        "batch_observation": (None if batch_id is None else batch_observation(document, batch_id)),
        "directives": [
            _json_value(item) for item in document.director_directives if item.run_id == run_id
        ],
    }


def _preview_impact(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    _exact_arguments(arguments, required={"command"})
    return preview_command_impact(document, parse_director_command(arguments["command"]))


def _get_projection(document, arguments):
    return build_semantic_projection(document, arguments)


_STORY_LOCATION = re.compile(
    r"^\s*场景\s*(?P<scene>\d+)"
    r"(?:\s*[－—–-]\s*(?P<kind>镜头|片段)\s*(?P<index>\d+))?\s*$"
)


def _locate_story(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    """Resolve a human-readable one-based story path from the current Core revision."""
    _exact_arguments(arguments, required={"location"})
    location = arguments["location"]
    message = "location 必须是“场景 N”、“场景 N－镜头 N”或“场景 N－片段 N”。"
    if not isinstance(location, str) or not location.strip():
        raise ValueError(message)
    match = _STORY_LOCATION.fullmatch(location)
    if match is None:
        raise ValueError(message)
    scene_index = int(match["scene"])
    index = None if match["index"] is None else int(match["index"])
    if scene_index < 1 or (index is not None and index < 1):
        raise ValueError("场景、镜头和片段序号必须从 1 开始。")
    script = document.director_script
    if script is None:
        raise ValueError("当前项目尚无结构化脚本，无法定位故事节点。")
    if scene_index > len(script.scenes):
        raise ValueError(f"场景 {scene_index} 不存在。")
    scene = script.scenes[scene_index - 1]
    result: dict[str, object] = {
        "revision": document.revision,
        "location": f"场景 {scene_index}",
        "target_type": "scene",
        "target_id": scene.id,
        "scene": {"id": scene.id, "index": scene_index, "title": scene.title},
    }
    if index is None:
        return result
    canonical = f"场景 {scene_index}－{match['kind']} {index}"
    if match["kind"] == "镜头":
        if index > len(scene.shots):
            raise ValueError(f"{canonical} 不存在。")
        shot = scene.shots[index - 1]
        result.update(
            location=canonical,
            target_type="shot",
            target_id=shot.id,
            shot={"id": shot.id, "index": index, "action": shot.action},
        )
        return result
    if index > len(scene.segments):
        raise ValueError(f"{canonical} 不存在。")
    segment = scene.segments[index - 1]
    result.update(
        location=canonical,
        target_type="segment",
        target_id=segment.id,
        segment={
            "id": segment.id,
            "index": index,
            "shot_ids": list(segment.shot_ids),
            "action": segment.action,
        },
    )
    return result


def _get_outline(document, arguments):
    _exact_arguments(arguments, optional={"depth", "cursor", "limit"})
    depth = arguments.get("depth", "scene")
    if depth not in {"scene", "shot", "segment"}:
        raise ValueError("project.get_outline.depth 只允许 scene、shot 或 segment。")
    result = _get_projection(
        document,
        {
            "level": "outline",
            "scope": {"project_id": document.project_id},
            **{key: value for key, value in arguments.items() if key != "depth"},
        },
    )
    if depth != "scene" and result["items"]:
        tree = build_semantic_tree(document, tuple(item["id"] for item in result["items"]))
        result["items"] = tree["scenes"]
        if depth == "shot":
            for scene in result["items"]:
                scene.pop("segments")
    return result


def _get_entities(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    _exact_arguments(
        arguments,
        required={"entity_type"},
        optional={"ids", "cursor", "limit"},
    )
    entity_type = arguments["entity_type"]
    ids = _optional_ids(arguments.get("ids"))
    items = _entities(document, entity_type)
    missing_ids: list[str] = []
    if ids is not None:
        by_id = {item["id"]: item for item in items}
        missing_ids = [item for item in ids if item not in by_id]
        items = [by_id[item] for item in ids if item in by_id]
    page, next_cursor = _page(items, arguments)
    return {
        "revision": document.revision,
        "entity_type": entity_type,
        "items": list(page),
        "missing_ids": missing_ids,
        "next_cursor": next_cursor,
    }


def _get_scene(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    _exact_arguments(arguments, required={"scene_id"}, optional={"layers"})
    scene_id = _id(arguments["scene_id"], "scene_id")
    layers = arguments.get(
        "layers",
        ["script"],
    )
    allowed_layers = {"script", "location", "keyframes", "videos", "generations"}
    if (
        not isinstance(layers, list)
        or any(not isinstance(item, str) or item not in allowed_layers for item in layers)
        or len(layers) != len(set(layers))
    ):
        raise ValueError("project.get_scene.layers 不合法或重复。")
    script = document.director_script
    scene = (
        None
        if script is None
        else next((item for item in script.scenes if item.id == scene_id), None)
    )
    if scene is None:
        raise ValueError("指定 Scene 不存在。")
    segment_ids = {segment.id for segment in scene_segments(scene)}
    shot_ids = {shot.id for shot in scene.shots}
    cue_ids = {cue.id for cue in scene.narration_cues}
    result: dict[str, object] = {"revision": document.revision, "scene_id": scene_id}
    if "script" in layers:
        tree = build_semantic_tree(document, (scene_id,))
        result.update({key: value for key, value in tree.items() if key != "scenes"})
        result["script"] = tree["scenes"][0]
    if "location" in layers:
        location = (
            None
            if scene.location_id is None
            else document.location_library.location(scene.location_id)
        )
        result["location"] = None if location is None else _json_value(location)
    frame_ids: set[str] = set()
    if document.keyframe_plan is not None:
        bindings = [
            item for item in document.keyframe_plan.segments if item.segment_id in segment_ids
        ]
        frame_ids = {
            value for item in bindings for value in (item.start_keyframe_id, item.end_keyframe_id)
        }
        if "keyframes" in layers:
            result["keyframes"] = {
                "segments": [_json_value(item) for item in bindings],
                "frames": [
                    _json_value(item)
                    for item in document.keyframe_plan.keyframes
                    if item.id in frame_ids
                ],
            }
    if "videos" in layers:
        result["videos"] = [
            _json_value(item)
            for item in (() if document.video_plan is None else document.video_plan.segments)
            if item.segment_id in segment_ids
        ]
    if "generations" in layers:
        targets = {scene_id, *shot_ids, *segment_ids, *cue_ids, *frame_ids}
        result["generations"] = [
            _generation_summary(item) for item in document.generations if item.target_id in targets
        ]
    return result


def _get_target(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    _exact_arguments(arguments, required={"target_id"})
    target_id = _id(arguments["target_id"], "target_id")
    script = document.director_script
    if script is not None:
        timeline = script_segments(script)
        for scene in script.scenes:
            if scene.id == target_id:
                return _semantic_target(document, "scene", scene.id, scene.id, {})
            for shot in scene.shots:
                if shot.id == target_id:
                    return _semantic_target(
                        document, "shot", shot.id, scene.id, {"scene_id": scene.id}
                    )
            for segment in scene.segments:
                if segment.id == target_id:
                    index = next(
                        index for index, item in enumerate(timeline) if item.id == target_id
                    )
                    return _semantic_target(
                        document,
                        "segment",
                        segment.id,
                        scene.id,
                        {
                            "scene_id": scene.id,
                            "shot_ids": list(segment.shot_ids),
                            "previous_segment_id": (timeline[index - 1].id if index > 0 else None),
                            "next_segment_id": (
                                timeline[index + 1].id if index + 1 < len(timeline) else None
                            ),
                        },
                    )
            for cue in scene.narration_cues:
                if cue.id == target_id:
                    return _target_result(document, "narration_cue", cue, {"scene_id": scene.id})
    if document.keyframe_plan is not None:
        for keyframe in document.keyframe_plan.keyframes:
            if keyframe.id == target_id:
                segment_ids = [
                    item.segment_id
                    for item in document.keyframe_plan.segments
                    if target_id in {item.start_keyframe_id, item.end_keyframe_id}
                ]
                return _target_result(document, "keyframe", keyframe, {"segment_ids": segment_ids})
    for entity_type, items in (
        ("character", document.reference_library.characters),
        ("asset", document.assets),
        ("generation", document.generations),
    ):
        entity = next((item for item in items if item.id == target_id), None)
        if entity is not None:
            value = (
                _asset_summary(entity)
                if isinstance(entity, Asset)
                else _generation_summary(entity)
                if isinstance(entity, ReferenceGeneration)
                else _json_value(entity)
            )
            return {
                "revision": document.revision,
                "target_type": entity_type,
                "target": value,
                "context": {},
            }
    raise ValueError("指定 target 不存在。")


def _list_candidates(
    document: StructuredDirectorDocument, arguments: dict[str, object]
) -> dict[str, object]:
    _exact_arguments(
        arguments,
        required={"kind", "target_ids"},
        optional={"phases", "cursor", "limit"},
    )
    try:
        kind = ReferenceGenerationKind(arguments["kind"])
    except (TypeError, ValueError) as exc:
        raise ValueError("project.list_candidates.kind 不合法。") from exc
    target_ids = _ids(arguments["target_ids"], "target_ids")
    phases_value = arguments.get("phases")
    if phases_value is None:
        phases = set(ReferenceGenerationPhase)
    else:
        if not isinstance(phases_value, list):
            raise ValueError("project.list_candidates.phases 必须是数组。")
        try:
            phases = {ReferenceGenerationPhase(item) for item in phases_value}
        except (TypeError, ValueError) as exc:
            raise ValueError("project.list_candidates.phases 不合法。") from exc
    assets = {item.id: item for item in document.assets}
    selected = _selected_assets(document, kind)
    candidates = [
        {
            **_generation_summary(item),
            "output_asset": (
                None
                if item.output_asset_id is None or item.output_asset_id not in assets
                else _asset_summary(assets[item.output_asset_id])
            ),
            "selected": item.output_asset_id is not None
            and item.output_asset_id in selected.get(item.target_id, set()),
            "reviewable": generation_is_reviewable(document, item),
        }
        for item in document.generations
        if item.kind is kind and item.target_id in target_ids and item.phase in phases
    ]
    page, next_cursor = _page(candidates, arguments)
    return {
        "revision": document.revision,
        "kind": kind.value,
        "items": list(page),
        "next_cursor": next_cursor,
    }


def _entities(document: StructuredDirectorDocument, entity_type: object) -> list[dict[str, object]]:
    if entity_type == "character":
        return [_json_value(item) for item in document.reference_library.characters]
    if entity_type == "narration_cue":
        return [
            {**_json_value(cue), "scene_id": scene.id}
            for scene in (
                () if document.director_script is None else document.director_script.scenes
            )
            for cue in scene.narration_cues
        ]
    if entity_type == "location":
        return [_json_value(item) for item in document.location_library.locations]
    if entity_type == "asset":
        return [_asset_summary(item) for item in document.assets]
    if entity_type == "generation":
        return [_generation_summary(item) for item in document.generations]
    raise ValueError("project.get_entities.entity_type 不合法。")


def _semantic_target(document, kind, node_id, scene_id, context):
    projection = _get_projection(
        document,
        {
            "level": kind,
            "scope": {"scene_ids": [scene_id]},
            **({"ids": [node_id]} if kind != "scene" else {}),
        },
    )
    return {
        **{key: value for key, value in projection.items() if key != "items"},
        "target_type": kind,
        "target": projection["items"][0],
        "context": context,
    }


def _target_result(
    document: StructuredDirectorDocument,
    target_type: str,
    target: object,
    context: dict[str, object],
) -> dict[str, object]:
    return {
        "revision": document.revision,
        "target_type": target_type,
        "target": _json_value(target),
        "context": context,
    }


def _generation_summary(generation: ReferenceGeneration) -> dict[str, object]:
    return {
        "id": generation.id,
        "kind": generation.kind.value,
        "operation": generation.operation.value,
        "target_id": generation.target_id,
        "phase": generation.phase.value,
        "progress": generation.progress,
        "message": generation.message,
        "output_asset_id": generation.output_asset_id,
        "retry_of": generation.retry_of,
        "dismissed": generation.dismissed,
    }


def _page(items: object, arguments: dict[str, object]) -> tuple[tuple[Any, ...], str | None]:
    values = tuple(items)  # type: ignore[arg-type]
    offset = _offset(arguments)
    limit_value = arguments.get("limit", _DEFAULT_PAGE_SIZE)
    if (
        isinstance(limit_value, bool)
        or not isinstance(limit_value, int)
        or not 1 <= limit_value <= _MAX_PAGE_SIZE
    ):
        raise ValueError(f"limit 必须是 1 到 {_MAX_PAGE_SIZE} 的整数。")
    if offset > len(values):
        raise ValueError("cursor 超出结果范围。")
    result = values[offset : offset + limit_value]
    next_offset = offset + len(result)
    return result, str(next_offset) if next_offset < len(values) else None


def _offset(arguments: dict[str, object]) -> int:
    cursor = arguments.get("cursor")
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor.isascii() or not cursor.isdigit():
        raise ValueError("cursor 不合法。")
    return int(cursor)


def _optional_ids(value: object) -> tuple[str, ...] | None:
    return None if value is None else _ids(value, "ids")
