"""生产依赖就绪评估（project.get_dependencies 的纯读实现）。

从 read_tools.py 下沉：供 read_tools 分发器与 workflow_state/semantic_projection
模块级复用，避免 reads 包内互相 import 成环。
"""

from __future__ import annotations

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import validate_required_slots

from ..models import (
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from ..script_index import scene_segments
from ..video_inputs import dialogue_audio_inputs, validate_dialogue_video_bindings
from .common import _exact_arguments, _ids

_TERMINAL_PHASES = {
    ReferenceGenerationPhase.SUCCEEDED,
    ReferenceGenerationPhase.FAILED,
    ReferenceGenerationPhase.CANCELLED,
}


def _get_dependencies(
    document: StructuredDirectorDocument, arguments: dict[str, object], *, catalog=None
) -> dict[str, object]:
    _exact_arguments(arguments, required={"action", "target_ids"})
    action = arguments["action"]
    if action not in {
        "keyframe.generate",
        "video.generate",
        "video.upscale",
    }:
        raise ValueError("project.get_dependencies.action 暂不支持。")
    target_ids = _ids(arguments["target_ids"], "target_ids")
    items = [_dependency(document, action, target_id, catalog=catalog) for target_id in target_ids]
    return {
        "revision": document.revision,
        "action": action,
        "items": items,
        "ready_target_ids": [item["target_id"] for item in items if item["ready"]],
        "blocked_target_ids": [item["target_id"] for item in items if not item["ready"]],
    }


def _dependency(
    document: StructuredDirectorDocument, action: object, target_id: str, *, catalog=None
) -> dict[str, object]:
    reasons: list[str] = []
    if action == "keyframe.generate":
        plan = document.keyframe_plan
        frame = (
            None
            if plan is None
            else next((item for item in plan.keyframes if item.id == target_id), None)
        )
        if plan is None or frame is None:
            reasons.append("Keyframe 不存在。")
        else:
            binding = next(
                (
                    item
                    for item in plan.segments
                    if (item.start_enabled and item.start_keyframe_id == target_id)
                    or (item.end_enabled and item.end_keyframe_id == target_id)
                ),
                None,
            )
            if binding is None:
                reasons.append("Keyframe 尚未激活。")
            if not frame.prompt_text.strip():
                reasons.append("Keyframe 提示词为空。")
            if (
                binding is not None
                and frame.predecessor_keyframe_id is not None
                and binding.start_enabled
                and _available_asset(
                    document, ReferenceGenerationKind.KEYFRAME_IMAGE, frame.predecessor_keyframe_id
                )
                is None
            ):
                reasons.append("前置 Keyframe 尚无已选图片或成功候选。")
    elif action == "video.generate":
        script_segment = next(
            (
                segment
                for scene in (
                    () if document.director_script is None else document.director_script.scenes
                )
                for segment in scene_segments(scene)
                if segment.id == target_id
            ),
            None,
        )
        video = next(
            (
                item
                for item in (() if document.video_plan is None else document.video_plan.segments)
                if item.segment_id == target_id
            ),
            None,
        )
        binding = next(
            (
                item
                for item in (
                    () if document.keyframe_plan is None else document.keyframe_plan.segments
                )
                if item.segment_id == target_id
            ),
            None,
        )
        if video is None or binding is None:
            reasons.append("Segment 视频或 Keyframe 计划不存在。")
        else:
            if (
                document.director_script is None
                or document.director_script.production_baseline_revision
                != document.director_script.revision
            ):
                reasons.append("当前 Shot timing 已失效；请先确认时序。")
            if not video.prompt_text.strip():
                reasons.append("视频提示词为空。")
            start_asset = (
                _selected_keyframe_asset(document, binding.start_keyframe_id)
                if binding.start_enabled
                else None
            )
            end_asset = (
                _selected_keyframe_asset(document, binding.end_keyframe_id)
                if binding.end_enabled
                else None
            )
            frame_assets = [
                asset_id
                for enabled, asset_id in (
                    (binding.start_enabled, start_asset),
                    (binding.end_enabled, end_asset),
                )
                if enabled
            ]
            if any(asset_id is None for asset_id in frame_assets):
                reasons.append("所有启用的边界 Keyframe 必须先选择图片。")
            known_assets = {item.id for item in document.assets}
            if any(asset_id not in known_assets for asset_id in frame_assets if asset_id):
                reasons.append("已选 Keyframe Asset 不存在。")
            if script_segment is None:
                reasons.append("Segment 不在当前脚本中。")
            elif script_segment.dialogue_lines:
                try:
                    dialogue_audio_inputs(document, target_id)
                except (ValueError, KeyError) as exc:
                    reasons.append(str(exc))
            if catalog is not None:
                try:
                    _plugin, recipe = catalog.recipe_definition(
                        Capability.VIDEO_GENERATE, video.active_recipe
                    )
                    bindings = dict(video.recipe_inputs.bindings)
                    boundary_assets = {
                        Role.FIRST_FRAME: () if start_asset is None else (start_asset,),
                        Role.LAST_FRAME: () if end_asset is None else (end_asset,),
                    }
                    for slot in recipe.slots:
                        if slot.role in boundary_assets:
                            bindings[slot.key] = boundary_assets[slot.role]
                    validate_dialogue_video_bindings(document, target_id, recipe, bindings)
                    validate_required_slots(recipe, bindings)
                    catalog.validate_recipe_inputs(
                        Capability.VIDEO_GENERATE,
                        video.active_recipe,
                        video.recipe_inputs,
                        document.assets,
                    )
                except (ValueError, RuntimeError) as exc:
                    reasons.append(str(exc))
    else:
        video = next(
            (
                item
                for item in (() if document.video_plan is None else document.video_plan.segments)
                if item.segment_id == target_id
            ),
            None,
        )
        if video is None or video.selected_asset_id is None:
            reasons.append("Segment 尚未选择原始视频。")
    if any(
        item.target_id == target_id and item.phase not in _TERMINAL_PHASES
        for item in document.generations
    ):
        reasons.append("目标已有进行中的 Generation。")
    return {"target_id": target_id, "ready": not reasons, "reasons": reasons}


def _selected_assets(
    document: StructuredDirectorDocument, kind: ReferenceGenerationKind
) -> dict[str, set[str]]:
    if kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        return {
            look.id: {look.selected_asset_id}
            for item in document.reference_library.characters
            for look in item.looks
            if look.selected_asset_id is not None
        }
    if kind is ReferenceGenerationKind.CHARACTER_VOICE:
        return {
            item.id: {item.voice_reference_asset_id}
            for item in document.reference_library.characters
            if item.voice_reference_asset_id is not None
        }
    if kind is ReferenceGenerationKind.NARRATOR_VOICE:
        narrator = document.reference_library.narrator
        return (
            {}
            if narrator is None or not narrator.voice_reference_asset_ids
            else {narrator.id: set(narrator.voice_reference_asset_ids)}
        )
    if kind is ReferenceGenerationKind.KEYFRAME_IMAGE and document.keyframe_plan is not None:
        return {
            item.id: {item.selected_asset_id}
            for item in document.keyframe_plan.keyframes
            if item.selected_asset_id is not None
        }
    if (
        kind in {ReferenceGenerationKind.SEGMENT_VIDEO, ReferenceGenerationKind.VIDEO_UPSCALE}
        and document.video_plan is not None
    ):
        return {
            item.segment_id: {asset_id}
            for item in document.video_plan.segments
            if (
                asset_id := (
                    item.selected_asset_id
                    if kind is ReferenceGenerationKind.SEGMENT_VIDEO
                    else item.upscaled_asset_id
                )
            )
            is not None
        }
    if kind in {
        ReferenceGenerationKind.LOCATION_IMAGE,
    }:
        return {
            image.id: {image.selected_asset_id}
            for item in document.location_library.locations
            for image in item.images
            if image.selected_asset_id is not None
        }
    if kind is ReferenceGenerationKind.NARRATION_AUDIO and document.director_script is not None:
        return {
            cue.id: set(cue.selected_audio_asset_ids)
            for scene in document.director_script.scenes
            for cue in scene.narration_cues
            if cue.selected_audio_asset_ids
        }
    if kind is ReferenceGenerationKind.FINAL_VIDEO and document.final_assembly is not None:
        selected = {
            asset_id
            for language in document.narration_languages
            if (asset_id := document.final_assembly.selected_asset_id(language)) is not None
        }
        return {document.project_id: selected} if selected else {}
    return {}


def _selected_keyframe_asset(document: StructuredDirectorDocument, keyframe_id: str) -> str | None:
    if document.keyframe_plan is None:
        return None
    frame = next(
        (item for item in document.keyframe_plan.keyframes if item.id == keyframe_id), None
    )
    return None if frame is None else frame.selected_asset_id


def _available_asset(
    document: StructuredDirectorDocument,
    kind: ReferenceGenerationKind,
    target_id: str,
) -> str | None:
    selected = _selected_assets(document, kind).get(target_id, set())
    if selected:
        return next(iter(selected))
    return next(
        (
            item.output_asset_id
            for item in reversed(document.generations)
            if item.kind is kind
            and item.target_id == target_id
            and item.phase is ReferenceGenerationPhase.SUCCEEDED
            and not item.dismissed
            and item.output_asset_id is not None
        ),
        None,
    )
