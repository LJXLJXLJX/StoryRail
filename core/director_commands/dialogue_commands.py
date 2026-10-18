from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite

from .models import InvalidArgumentsError

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class DialogueTimingUpdate:
    scope_scene_ids: tuple[str, ...]
    segment_id: str
    starts: tuple[tuple[str, float], ...]
    duration_seconds: float


def parse_dialogue_timing_update(value: object) -> DialogueTimingUpdate:
    if not isinstance(value, dict) or set(value) != {
        "scope",
        "segment_id",
        "starts",
        "duration_seconds",
    }:
        raise InvalidArgumentsError("dialogue.set_timing arguments 包含缺失或未声明字段。")
    scope = value["scope"]
    if not isinstance(scope, dict) or set(scope) != {"scene_ids"}:
        raise InvalidArgumentsError("dialogue.set_timing scope 字段不合法。")
    scene_ids = scope["scene_ids"]
    if (
        not isinstance(scene_ids, list)
        or not scene_ids
        or any(not isinstance(item, str) or _ID.fullmatch(item) is None for item in scene_ids)
        or len(scene_ids) != len(set(scene_ids))
    ):
        raise InvalidArgumentsError("dialogue.set_timing scope.scene_ids 不合法。")
    segment_id = value["segment_id"]
    if not isinstance(segment_id, str) or _ID.fullmatch(segment_id) is None:
        raise InvalidArgumentsError("dialogue.set_timing segment_id 不合法。")
    raw_starts = value["starts"]
    if not isinstance(raw_starts, dict) or not raw_starts:
        raise InvalidArgumentsError("dialogue.set_timing starts 必须是非空对象。")
    starts = []
    for line_id, start in raw_starts.items():
        if not isinstance(line_id, str) or _ID.fullmatch(line_id) is None:
            raise InvalidArgumentsError("dialogue.set_timing starts 包含非法 DialogueLine ID。")
        if (
            isinstance(start, bool)
            or not isinstance(start, int | float)
            or not isfinite(start)
            or start < 0
        ):
            raise InvalidArgumentsError("dialogue.set_timing starts 必须是非负有限秒数。")
        starts.append((line_id, float(start)))
    duration = value["duration_seconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not isfinite(duration)
        or duration < 0.2
    ):
        raise InvalidArgumentsError("dialogue.set_timing duration_seconds 不合法。")
    return DialogueTimingUpdate(tuple(scene_ids), segment_id, tuple(starts), float(duration))
