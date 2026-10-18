"""对白时长：脚本期保留估算；生产期只以已选 TTS WAV 的真实时长为准。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import DialogueLine, ShotSegment, StructuredDirectorDocument

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")

# 中文约每秒 4–5 字、英文约每秒 2–3 词；每句前后留停顿，整段再留起止余量。
CJK_CHARS_PER_SECOND = 4.5
WORDS_PER_SECOND = 2.5
LINE_PAUSE_SECONDS = 0.5
EDGE_SECONDS = 0.5


def dialogue_seconds_estimate(lines: Iterable[DialogueLine]) -> float | None:
    """台词全部念完至少需要的秒数；没有对白时为 None。"""
    lines = tuple(lines)
    if not lines:
        return None
    total = EDGE_SECONDS
    for line in lines:
        cjk = len(_CJK.findall(line.text))
        words = len(_WORD.findall(_CJK.sub(" ", line.text)))
        total += cjk / CJK_CHARS_PER_SECOND + words / WORDS_PER_SECOND + LINE_PAUSE_SECONDS
    return round(total, 1)


def dialogue_timing(segment: ShotSegment) -> dict[str, object] | None:
    estimate = dialogue_seconds_estimate(segment.dialogue_lines)
    if estimate is None:
        return None
    return {
        "estimated_seconds": estimate,
        "exceeds_duration": estimate > segment.duration_estimate_seconds,
    }


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


def dialogue_timing_warnings(document: StructuredDirectorDocument) -> list[dict[str, object]]:
    """脚本中对白装不进预估时长的 Segment，按脚本顺序。"""
    warnings: list[dict[str, object]] = []
    for scene in document.director_script.scenes if document.director_script else ():
        for segment in scene.segments:
            timing = dialogue_timing(segment)
            if timing is not None and timing["exceeds_duration"]:
                warnings.append(
                    {
                        "segment_id": segment.id,
                        "estimated_seconds": timing["estimated_seconds"],
                        "duration_seconds": segment.duration_estimate_seconds,
                    }
                )
    return warnings
