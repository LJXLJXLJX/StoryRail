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
    if kind is ReferenceGenerationKind.DIALOGUE_AUDIO:
        # 对白候选由人类试听判断；正文、音色或表演参数变化只作软提示。
        # target_id 已把候选约束在同一条 DialogueLine，不能替用户拒绝历史 WAV。
        return _dialogue_line(document, target_id) is not None and asset.media_type == "audio/wav"
    if kind is ReferenceGenerationKind.VIDEO_REFERENCE_IMAGE:
        return (
            document.video_plan is not None
            and any(
                image.id == target_id
                for video in document.video_plan.segments
                for image in video.reference_images
            )
            and asset.media_type.startswith("image/")
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
    if kind in {
        ReferenceGenerationKind.LOCATION_IMAGE,
    }:
        return document.location_library.image_owner(
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


def dialogue_inputs_unchanged(document, generation) -> bool:
    """Return whether a dialogue candidate was generated from the current inputs."""
    if generation.kind is not ReferenceGenerationKind.DIALOGUE_AUDIO:
        return True
    line = _dialogue_line(document, generation.target_id)
    if line is None or generation.prompt_text != line.text:
        return False
    plan_item = next(
        (
            item
            for item in (() if document.dialogue_plan is None else document.dialogue_plan.items)
            if item.dialogue_line_id == generation.target_id
        ),
        None,
    )
    recipe_id = (
        None if generation.provider_snapshot is None else generation.provider_snapshot.recipe_id
    )
    if plan_item is not None and recipe_id is not None:
        configured = plan_item.recipe_params.get(recipe_id)
        submitted = generation.recipe_params.get(recipe_id)
        if configured is not None and submitted != configured:
            return False
        if (
            configured is None
            and submitted is not None
            and "performance_instruction" in submitted
            and submitted["performance_instruction"] != (line.delivery.strip() or None)
        ):
            return False
    if line.character_id is None:
        return (
            generation.operation.value == "voice_design"
            and generation.sample_text == line.voice_description
        )
    card = next(
        (item for item in document.reference_library.characters if item.id == line.character_id),
        None,
    )
    if card is None:
        return False
    if card.voice_reference_asset_id is None:
        return (
            generation.operation.value == "voice_design"
            and generation.sample_text == card.voice_description
        )
    return (
        generation.operation.value == "synthesize"
        and generation.input_asset_ids == (card.voice_reference_asset_id,)
        and generation.sample_text == card.voice_reference_transcript
    )


def _dialogue_line(document, target_id):
    return next(
        (
            line
            for scene in (
                () if document.director_script is None else document.director_script.scenes
            )
            for segment in scene.segments
            for line in segment.dialogue_lines
            if line.id == target_id
        ),
        None,
    )


def reviewable_generations(document, kind, target_ids):
    targets = set(target_ids)
    return tuple(
        generation
        for generation in document.generations
        if generation.kind is kind
        and generation.target_id in targets
        and generation_is_reviewable(document, generation)
    )


def keyframe_references_unchanged(document, generation) -> bool:
    """Keyframe 候选提交时是否包含它参考的每个 Keyframe 与地点图片的当前选中图。

    参考帧被改选后旧候选只作软提示，不阻止选择；上游变化由人或 Agent 决定是否重生成。
    """
    plan = document.keyframe_plan
    if generation.kind is not ReferenceGenerationKind.KEYFRAME_IMAGE or plan is None:
        return True
    frames = {item.id: item for item in plan.keyframes}
    keyframe = frames.get(generation.target_id)
    if keyframe is None:
        return True
    submitted = set(generation.input_asset_ids)
    current = [
        frames[reference_id].selected_asset_id
        for reference_id in keyframe.reference_keyframe_ids
        if reference_id in frames
    ] + [
        document.location_library.selected_image_asset(image_id)
        for image_id in keyframe.reference_location_image_ids
    ]
    return all(asset_id in submitted for asset_id in current if asset_id is not None)
