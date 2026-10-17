"""对白时长软提示：按字数估算台词需要的秒数，超出 Segment 预估时长时提示，不阻止任何写入。"""

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


def dialogue_timing_warnings(document: StructuredDirectorDocument) -> list[dict[str, object]]:
    """脚本中对白装不进预估时长的 Segment，按脚本顺序。"""
    warnings: list[dict[str, object]] = []
    for scene in document.director_script.scenes if document.director_script else ():
        for shot in scene.shots:
            for segment in shot.segments:
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
