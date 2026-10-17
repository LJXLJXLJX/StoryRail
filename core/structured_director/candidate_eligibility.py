"""候选可审核性的只读共源判定；不选择、不轮询、不修改业务事实。"""

from __future__ import annotations

from .keyframe_requests import _active_keyframe_ids
from .models import ReferenceGenerationKind, ReferenceGenerationPhase
from .video_inputs import video_candidate_selectable


def generation_is_reviewable(document, generation) -> bool:
    """Return whether the current document would accept this output for its target."""
    if (
        generation.phase is not ReferenceGenerationPhase.SUCCEEDED
        or generation.dismissed
        or generation.output_asset_id is None
    ):
        return False
    asset = next((item for item in document.assets if item.id == generation.output_asset_id), None)
    if asset is None:
        return False
    kind = generation.kind
    target_id = generation.target_id
    if kind is ReferenceGenerationKind.NARRATION_AUDIO:
        cue = next(
            (
                cue
                for scene in (
                    () if document.director_script is None else document.director_script.scenes
                )
                for cue in scene.narration_cues
                if cue.id == target_id
            ),
            None,
        )
        return (
            cue is not None
            and generation.language is not None
            and asset.media_type == "audio/wav"
            and generation.prompt_text == cue.track(generation.language).text
        )
    if kind is ReferenceGenerationKind.KEYFRAME_IMAGE:
        return (
            document.keyframe_plan is not None
            and target_id in _active_keyframe_ids(document.keyframe_plan)
            and asset.media_type.startswith("image/")
        )
    if kind is ReferenceGenerationKind.SEGMENT_VIDEO:
        # 输入快照只作提示，不阻止选择；旧候选一样可以被采用。
        return video_candidate_selectable(document, generation)
    if kind is ReferenceGenerationKind.FINAL_VIDEO:
        return (
            document.final_assembly is not None
            and generation.language is not None
            and target_id == document.project_id
            and asset.media_type == "video/mp4"
        )
    if kind is ReferenceGenerationKind.LOCATION_MASTER_IMAGE:
        return document.location_library.location(
            target_id
        ) is not None and asset.media_type.startswith("image/")
    if kind is ReferenceGenerationKind.LOCATION_VIEW_IMAGE:
        return document.location_library.view_owner(
            target_id
        ) is not None and asset.media_type.startswith("image/")
    if kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        return document.reference_library.look_owner(
            target_id
        ) is not None and asset.media_type.startswith("image/")
    if kind is ReferenceGenerationKind.CHARACTER_VOICE:
        return (
            any(item.id == target_id for item in document.reference_library.characters)
            and asset.media_type == "audio/wav"
        )
    if kind is ReferenceGenerationKind.NARRATOR_VOICE:
        return (
            document.reference_library.narrator is not None
            and document.reference_library.narrator.id == target_id
            and asset.media_type == "audio/wav"
        )
    if kind is ReferenceGenerationKind.VIDEO_UPSCALE:
        return (
            document.video_plan is not None
            and any(
                item.segment_id == target_id and item.selected_asset_id is not None
                for item in document.video_plan.segments
            )
            and asset.media_type == "video/mp4"
        )
    return False


def reviewable_generations(document, kind, target_ids):
    targets = set(target_ids)
    return tuple(
        generation
        for generation in document.generations
        if generation.kind is kind
        and generation.target_id in targets
        and generation_is_reviewable(document, generation)
    )
