"""对白时长只以已选 TTS WAV 的真实时长为准。"""

from __future__ import annotations

from .models import ShotSegment, StructuredDirectorDocument


def actual_dialogue_timing(
    document: StructuredDirectorDocument, segment: ShotSegment
) -> dict[str, object] | None:
    """返回逐句真实 WAV 时序；未全部选择或未完成校准时显式标记未就绪。"""
    if not segment.dialogue_lines:
        return None
    if document.dialogue_plan is None:
        return {"ready": False, "reason": "dialogue_plan_missing"}
    items = {item.dialogue_line_id: item for item in document.dialogue_plan.items}
    assets = {item.id: item for item in document.assets}
    lines = []
    maximum_end = 0.0
    for line in segment.dialogue_lines:
        item = items.get(line.id)
        if item is None or item.selected_audio_asset_id is None:
            return {"ready": False, "reason": "audio_not_selected"}
        asset = assets.get(item.selected_audio_asset_id)
        if asset is None or asset.duration_seconds is None:
            return {"ready": False, "reason": "audio_missing"}
        if item.start_seconds is None:
            return {"ready": False, "reason": "timing_not_set"}
        end = item.start_seconds + asset.duration_seconds
        maximum_end = max(maximum_end, end)
        lines.append(
            {
                "dialogue_line_id": line.id,
                "asset_id": asset.id,
                "start_seconds": item.start_seconds,
                "duration_seconds": asset.duration_seconds,
                "end_seconds": end,
            }
        )
    return {
        "ready": maximum_end <= segment.duration_estimate_seconds + 1e-6,
        "minimum_duration_seconds": maximum_end,
        "duration_seconds": segment.duration_estimate_seconds,
        "lines": lines,
    }
