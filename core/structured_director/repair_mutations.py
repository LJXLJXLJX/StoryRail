from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from core.director_commands import (
    RepairOperation,
    RepairPatch,
    ScriptOperationsPatch,
)

from .models import (
    CapabilityGapRepairOperation,
    Scene,
    Shot,
    ShotSegment,
    StructuredDirectorDocument,
)


def _formal_script_command_names(patch: ScriptOperationsPatch) -> set[str]:
    return {"script.apply_operations"} | {
        f"script.{operation.op}" for operation in patch.operations
    }


def _apply_repair_operations(
    scenes: tuple[Scene, ...],
    patch: RepairPatch,
) -> tuple[tuple[Scene, ...], tuple[RepairOperation, ...], tuple[str, ...]]:
    scene_ids = {scene.id for scene in scenes}
    if not set(patch.scope_scene_ids) <= scene_ids:
        raise ValueError("repair scope 包含不存在的 Scene。")
    current_scenes = scenes
    reverse_operations: list[RepairOperation] = []
    target_ids: list[str] = []
    for operation in patch.operations:
        found = False
        next_scenes: list[Scene] = []
        for scene in current_scenes:
            if operation.entity_type == "scene" and scene.id == operation.entity_id:
                if scene.id not in patch.scope_scene_ids:
                    raise ValueError("repair operation 超出已授权 Scene scope。")
                reverse_operations.append(
                    RepairOperation(
                        "scene",
                        scene.id,
                        {name: getattr(scene, name) for name in operation.fields},
                    )
                )
                next_scenes.append(replace(scene, **operation.fields))
                found = True
                continue
            next_shots: list[Shot] = []
            scene_changed = False
            for shot in scene.shots:
                if operation.entity_type == "shot" and shot.id == operation.entity_id:
                    if scene.id not in patch.scope_scene_ids:
                        raise ValueError("repair operation 超出已授权 Scene scope。")
                    reverse_operations.append(
                        RepairOperation(
                            "shot",
                            shot.id,
                            {name: getattr(shot, name) for name in operation.fields},
                        )
                    )
                    next_shots.append(replace(shot, **operation.fields))
                    found = True
                    scene_changed = True
                else:
                    next_shots.append(shot)
            next_segments: list[ShotSegment] = []
            for segment in scene.segments:
                if operation.entity_type == "segment" and segment.id == operation.entity_id:
                    if scene.id not in patch.scope_scene_ids:
                        raise ValueError("repair operation 超出已授权 Scene scope。")
                    reverse_operations.append(
                        RepairOperation(
                            "segment",
                            segment.id,
                            {name: getattr(segment, name) for name in operation.fields},
                        )
                    )
                    next_segments.append(replace(segment, **operation.fields))
                    found = True
                    scene_changed = True
                else:
                    next_segments.append(segment)
            next_scenes.append(
                replace(scene, shots=tuple(next_shots), segments=tuple(next_segments))
                if scene_changed
                else scene
            )
        if not found:
            raise ValueError("repair operation 目标不存在或类型不匹配。")
        current_scenes = tuple(next_scenes)
        target_ids.append(operation.entity_id)
    return current_scenes, tuple(reverse_operations), tuple(target_ids)


def _repair_gap_id(patch: RepairPatch) -> str:
    canonical = json.dumps(
        {
            "missing_command": patch.missing_command,
            "scope_scene_ids": sorted(patch.scope_scene_ids),
            "operations": sorted(
                (
                    item.entity_type,
                    item.entity_id,
                    tuple(sorted(item.fields.items())),
                )
                for item in patch.operations
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _repair_request_summary(raw_user_request: str) -> str:
    compact = " ".join(raw_user_request.split())
    return compact if len(compact) <= 500 else compact[:497] + "..."


def _repair_operation_summary(operations: tuple[RepairOperation, ...]) -> str:
    return "；".join(
        f"{item.entity_type}:{item.entity_id} set {','.join(sorted(item.fields))}"
        for item in operations
    )


def _repair_operation_for_alert(
    operation: RepairOperation,
) -> CapabilityGapRepairOperation:
    return CapabilityGapRepairOperation(
        operation.entity_type,
        operation.entity_id,
        dict(operation.fields),
    )


def _repair_operation_from_alert(
    operation: CapabilityGapRepairOperation,
) -> RepairOperation:
    return RepairOperation(
        operation.entity_type,
        operation.entity_id,
        dict(operation.fields),
    )


def _location_image_selections(document: StructuredDirectorDocument) -> dict[str, str]:
    return {
        image.id: image.selected_asset_id
        for item in document.location_library.locations
        for image in item.images
        if image.selected_asset_id is not None
    }


def _repair_invalidated_items(
    previous: StructuredDirectorDocument,
    current: StructuredDirectorDocument,
) -> tuple[str, ...]:
    invalidated: set[str] = set()
    for prefix, selections in (("location_image_selection", _location_image_selections),):
        previous_selected = selections(previous)
        current_selected = selections(current)
        invalidated.update(
            f"{prefix}:{target_id}"
            for target_id, asset_id in previous_selected.items()
            if current_selected.get(target_id) != asset_id
        )
    previous_cues = {
        (cue.id, language.value): track.selected_audio_asset_id
        for scene in (previous.director_script.scenes if previous.director_script else ())
        for cue in scene.narration_cues
        for language, track in cue.tracks
    }
    current_cues = {
        (cue.id, language.value): track.selected_audio_asset_id
        for scene in (current.director_script.scenes if current.director_script else ())
        for cue in scene.narration_cues
        for language, track in cue.tracks
    }
    invalidated.update(
        f"narration_selection:{cue_id}:{language}"
        for (cue_id, language), asset_id in previous_cues.items()
        if asset_id is not None and current_cues.get((cue_id, language)) is None
    )
    previous_keyframes = {
        item.id: item.selected_asset_id
        for item in (previous.keyframe_plan.keyframes if previous.keyframe_plan else ())
    }
    current_keyframes = {
        item.id: item.selected_asset_id
        for item in (current.keyframe_plan.keyframes if current.keyframe_plan else ())
    }
    invalidated.update(
        f"keyframe_selection:{keyframe_id}"
        for keyframe_id, asset_id in previous_keyframes.items()
        if asset_id is not None and current_keyframes.get(keyframe_id) is None
    )
    previous_videos = {
        item.segment_id: item
        for item in (previous.video_plan.segments if previous.video_plan else ())
    }
    current_videos = {
        item.segment_id: item
        for item in (current.video_plan.segments if current.video_plan else ())
    }
    for segment_id, item in previous_videos.items():
        current_item = current_videos.get(segment_id)
        if item.selected_asset_id is not None and (
            current_item is None or current_item.selected_asset_id is None
        ):
            invalidated.add(f"video_selection:{segment_id}")
        if item.upscaled_asset_id is not None and (
            current_item is None or current_item.upscaled_asset_id is None
        ):
            invalidated.add(f"video_upscale:{segment_id}")
    if previous.final_assembly is not None and current.final_assembly is None:
        invalidated.add("final_assembly")
    return tuple(sorted(invalidated))
