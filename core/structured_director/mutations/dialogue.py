"""对白 TTS 的选择与真实时序校准；纯函数，不执行 Provider 或文件 I/O。"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite

from core.model_providers.recipe import RecipeInputs, RecipeParams, SlotBinding

from ..candidate_eligibility import generation_is_reviewable
from ..models import (
    ReferenceGenerationKind,
    StructuredDirectorDocument,
)
from ..script_mutations import _invalidate_production_after_script_revision
from ..video_inputs import dialogue_audio_description


def select_dialogue_audio(
    document: StructuredDirectorDocument,
    *,
    dialogue_line_id: str,
    generation_id: str,
) -> StructuredDirectorDocument:
    """选择该 DialogueLine 的成功 WAV，并清除该 Segment 的旧时序。"""
    plan, _scene, segment = _require_dialogue_line(document, dialogue_line_id)
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if (
        generation is None
        or generation.kind is not ReferenceGenerationKind.DIALOGUE_AUDIO
        or generation.target_id != dialogue_line_id
        or not generation_is_reviewable(document, generation)
        or generation.output_asset_id is None
    ):
        raise ValueError("对白候选不存在、尚未完成、已隐藏，或不是该句的 WAV。")
    items = tuple(
        replace(
            item,
            selected_audio_asset_id=(
                generation.output_asset_id
                if item.dialogue_line_id == dialogue_line_id
                else item.selected_audio_asset_id
            ),
            start_seconds=None,
        )
        if item.dialogue_line_id in {line.id for line in segment.dialogue_lines}
        else item
        for item in plan.items
    )
    return _invalidate_segment_video(
        _refresh_explicit_dialogue_references(
            replace(
                document,
                revision=document.revision + 1,
                dialogue_plan=replace(plan, items=items),
            ),
            segment,
        ),
        segment.id,
    )


def _refresh_explicit_dialogue_references(document, segment):
    """换选 TTS 只刷新已存在的本句引用，不建立任何新的视频输入。"""
    if document.video_plan is None:
        return document
    lines = {line.id: line for line in segment.dialogue_lines}
    selected = {
        item.dialogue_line_id: item.selected_audio_asset_id for item in document.dialogue_plan.items
    }
    assets = {asset.id: asset for asset in document.assets}
    replacements = {}
    for generation in document.generations:
        if (
            generation.kind is ReferenceGenerationKind.DIALOGUE_AUDIO
            and generation.target_id in lines
            and generation.output_asset_id is not None
        ):
            asset = assets.get(selected.get(generation.target_id))
            if asset is not None and generation.output_asset_id != asset.id:
                replacements[generation.output_asset_id] = SlotBinding(
                    asset.id,
                    dialogue_audio_description(document, lines[generation.target_id], asset),
                )
    videos = []
    for video in document.video_plan.segments:
        if video.segment_id == segment.id:
            book = video.recipes
            for recipe_id, inputs in video.recipes.entries:
                bindings = []
                for key, entries in inputs.bindings:
                    refreshed = [replacements.get(entry.asset_id, entry) for entry in entries]
                    unique = {entry.asset_id: entry for entry in reversed(refreshed)}
                    bindings.append((key, tuple(reversed(list(unique.values())))))
                book = book.with_entry(recipe_id, RecipeInputs(tuple(bindings), inputs.params))
            video = replace(video, recipes=book)
        videos.append(video)
    return replace(document, video_plan=replace(document.video_plan, segments=tuple(videos)))


def update_dialogue_recipe_params(
    document: StructuredDirectorDocument,
    *,
    dialogue_line_id: str,
    recipe_params: RecipeParams,
) -> StructuredDirectorDocument:
    """保存逐句克隆表演参数，并清除依赖旧参数的选择、时序与视频。"""
    plan, _scene, segment = _require_dialogue_line(document, dialogue_line_id)
    current = next(item for item in plan.items if item.dialogue_line_id == dialogue_line_id)
    if current.recipe_params == recipe_params:
        return document
    line = next(line for line in segment.dialogue_lines if line.id == dialogue_line_id)
    card = (
        None
        if line.character_id is None
        else next(
            item for item in document.reference_library.characters if item.id == line.character_id
        )
    )
    if (card is None or card.voice_reference_asset_id is None) and recipe_params.entries:
        raise ValueError("Voice Design 对白不能保存语音克隆表演参数。")
    segment_line_ids = {line.id for line in segment.dialogue_lines}
    updated_plan = replace(
        plan,
        items=tuple(
            replace(
                item,
                recipe_params=(
                    recipe_params
                    if item.dialogue_line_id == dialogue_line_id
                    else item.recipe_params
                ),
                selected_audio_asset_id=(
                    None
                    if item.dialogue_line_id == dialogue_line_id
                    else item.selected_audio_asset_id
                ),
                start_seconds=None,
            )
            if item.dialogue_line_id in segment_line_ids
            else item
            for item in plan.items
        ),
    )
    return _invalidate_segment_video(
        replace(
            document,
            revision=document.revision + 1,
            dialogue_plan=updated_plan,
        ),
        segment.id,
    )


def set_dialogue_timing(
    document: StructuredDirectorDocument,
    *,
    segment_id: str,
    starts: dict[str, float],
    duration_seconds: float,
) -> StructuredDirectorDocument:
    """按真实 WAV 时长保存发声起点，并把 Segment 视频时长校准到不短于对白。"""
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, int | float)
        or not isfinite(duration_seconds)
        or duration_seconds < 0.2
    ):
        raise ValueError("Segment 时长必须是不短于 0.2 秒的有限数值。")
    plan, scene, segment = _require_dialogue_segment(document, segment_id)
    line_ids = tuple(line.id for line in segment.dialogue_lines)
    if set(starts) != set(line_ids):
        raise ValueError("对白时序必须且只能覆盖该 Segment 的全部 DialogueLine。")
    plan_by_id = {item.dialogue_line_id: item for item in plan.items}
    asset_by_id = {item.id: item for item in document.assets}
    previous_end = 0.0
    normalized: dict[str, float] = {}
    for line_id in line_ids:
        assert line_id is not None
        item = plan_by_id[line_id]
        if item.selected_audio_asset_id is None:
            raise ValueError("请先为该 Segment 的每句对白选择 TTS 音频。")
        asset = asset_by_id[item.selected_audio_asset_id]
        start = starts[line_id]
        if (
            isinstance(start, bool)
            or not isinstance(start, int | float)
            or not isfinite(start)
            or start < 0
        ):
            raise ValueError("对白发声起点必须是非负有限数值。")
        start = float(start)
        if start + 1e-6 < previous_end:
            raise ValueError("对白音频不能重叠；请按剧本顺序安排发声起点。")
        previous_end = start + (asset.duration_seconds or 0.0)
        normalized[line_id] = start
    if duration_seconds + 1e-6 < previous_end:
        raise ValueError(f"Segment 时长不能短于最后一句对白结束时间 {previous_end:.3f} 秒。")
    timed_plan = replace(
        plan,
        items=tuple(
            replace(item, start_seconds=normalized[item.dialogue_line_id])
            if item.dialogue_line_id in normalized
            else item
            for item in plan.items
        ),
    )
    scenes = tuple(
        replace(
            candidate,
            segments=tuple(
                replace(value, duration_estimate_seconds=float(duration_seconds))
                if value.id == segment_id
                else value
                for value in candidate.segments
            ),
        )
        if candidate.id == scene.id
        else candidate
        for candidate in document.director_script.scenes
    )
    return _invalidate_production_after_script_revision(
        document,
        scenes,
        dialogue_plan_override=timed_plan,
    )


def auto_calibrate_dialogue_timings(
    document: StructuredDirectorDocument,
) -> StructuredDirectorDocument:
    """一次性校准所有已选齐 TTS WAV 的 Segment；未选齐的 Segment 保持不变。"""
    plan = document.dialogue_plan
    script = document.director_script
    if not document.is_reviewing or script is None or plan is None:
        raise ValueError("当前不能校准对白时序。")
    plan_by_id = {item.dialogue_line_id: item for item in plan.items}
    asset_by_id = {item.id: item for item in document.assets}
    starts_by_line: dict[str, float] = {}
    durations_by_segment: dict[str, float] = {}
    for scene in script.scenes:
        for segment in scene.segments:
            if not segment.dialogue_lines:
                continue
            durations: list[float] = []
            for line in segment.dialogue_lines:
                item = plan_by_id.get(line.id or "")
                asset = (
                    None
                    if item is None or item.selected_audio_asset_id is None
                    else asset_by_id.get(item.selected_audio_asset_id)
                )
                if asset is None or asset.duration_seconds is None:
                    break
                durations.append(asset.duration_seconds)
            if len(durations) != len(segment.dialogue_lines):
                continue
            cursor = 0.5
            for line, duration in zip(segment.dialogue_lines, durations, strict=True):
                assert line.id is not None
                starts_by_line[line.id] = cursor
                cursor += duration + 0.25
            durations_by_segment[segment.id] = max(0.2, cursor + 0.25)
    if not durations_by_segment:
        raise ValueError("当前没有已选齐全部对白 TTS 的 Segment。")
    current_items = {item.dialogue_line_id: item for item in plan.items}
    current_segments = {
        segment.id: segment for scene in script.scenes for segment in scene.segments
    }
    if all(
        current_items[line_id].start_seconds == start for line_id, start in starts_by_line.items()
    ) and all(
        current_segments[segment_id].duration_estimate_seconds == duration
        for segment_id, duration in durations_by_segment.items()
    ):
        return document
    timed_plan = replace(
        plan,
        items=tuple(
            replace(item, start_seconds=starts_by_line[item.dialogue_line_id])
            if item.dialogue_line_id in starts_by_line
            else item
            for item in plan.items
        ),
    )
    scenes = tuple(
        replace(
            scene,
            segments=tuple(
                replace(
                    segment,
                    duration_estimate_seconds=durations_by_segment[segment.id],
                )
                if segment.id in durations_by_segment
                else segment
                for segment in scene.segments
            ),
        )
        for scene in script.scenes
    )
    return _invalidate_production_after_script_revision(
        document,
        scenes,
        dialogue_plan_override=timed_plan,
    )


def _require_dialogue_line(document, dialogue_line_id):
    plan = document.dialogue_plan
    script = document.director_script
    if not document.is_reviewing or script is None or plan is None:
        raise ValueError("当前不能处理对白 TTS。")
    for scene in script.scenes:
        for segment in scene.segments:
            if any(line.id == dialogue_line_id for line in segment.dialogue_lines):
                return plan, scene, segment
    raise ValueError("DialogueLine 不存在。")


def _require_dialogue_segment(document, segment_id):
    plan = document.dialogue_plan
    script = document.director_script
    if not document.is_reviewing or script is None or plan is None:
        raise ValueError("当前不能校准对白时序。")
    for scene in script.scenes:
        for segment in scene.segments:
            if segment.id == segment_id and segment.dialogue_lines:
                return plan, scene, segment
    raise ValueError("含对白的 Segment 不存在。")


def _invalidate_segment_video(
    document: StructuredDirectorDocument, segment_id: str
) -> StructuredDirectorDocument:
    plan = document.video_plan
    if plan is None:
        return replace(document, final_assembly=None)
    return replace(
        document,
        video_plan=replace(
            plan,
            segments=tuple(
                replace(item, selected_asset_id=None, upscaled_asset_id=None)
                if item.segment_id == segment_id
                else item
                for item in plan.segments
            ),
        ),
        final_assembly=None,
    )
