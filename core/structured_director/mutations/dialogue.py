"""对白 TTS 的选择与真实时序校准；纯函数，不执行 Provider 或文件 I/O。"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite

from ..candidate_eligibility import generation_is_reviewable
from ..models import (
    ReferenceGenerationKind,
    StructuredDirectorDocument,
)
from ..script_mutations import _invalidate_production_after_script_revision


def select_dialogue_audio(
    document: StructuredDirectorDocument,
    *,
    dialogue_line_id: str,
    generation_id: str,
) -> StructuredDirectorDocument:
    """选择当前正文和当前音色路由生成的 WAV，并清除该 Segment 的旧时序。"""
    plan, _scene, segment = _require_dialogue_line(document, dialogue_line_id)
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if (
        generation is None
        or generation.kind is not ReferenceGenerationKind.DIALOGUE_AUDIO
        or generation.target_id != dialogue_line_id
        or not generation_is_reviewable(document, generation)
        or generation.output_asset_id is None
    ):
        raise ValueError("对白候选不存在、尚未完成，或已不匹配当前正文与音色。")
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
        replace(
            document,
            revision=document.revision + 1,
            dialogue_plan=replace(plan, items=items),
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
