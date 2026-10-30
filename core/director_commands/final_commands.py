from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite

from storyrail_contracts.fields import require_fields

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class AnimaticSceneTarget:
    scene_id: str


@dataclass(frozen=True, slots=True)
class FinalSceneTarget:
    scene_id: str
    video_audio_volume: float = 1.0
    narration_audio_volume: float = 1.0


@dataclass(frozen=True, slots=True)
class FinalCandidateSelection:
    generation_id: str


@dataclass(frozen=True, slots=True)
class FinalApprovalRequest:
    """一次 Approval 同时批准中英两个单语成片的精确 Asset。"""

    zh_asset_id: str | None
    en_asset_id: str | None


def parse_empty_arguments(value: object, command_name: str) -> None:
    _exact(value, set(), command_name)


def parse_animatic_scene_target(value: object) -> AnimaticSceneTarget:
    item = _exact(value, {"scene_id"}, "animatic.generate_scene")
    return AnimaticSceneTarget(_id(item["scene_id"], "scene_id"))


def parse_final_scene_target(value: object) -> FinalSceneTarget:
    require_fields(
        "final.assemble_scene.arguments",
        value,
        {"scene_id"},
        {"video_audio_volume", "narration_audio_volume"},
    )
    return FinalSceneTarget(
        _id(value["scene_id"], "scene_id"),
        _volume(value.get("video_audio_volume", 1.0), "video_audio_volume"),
        _volume(value.get("narration_audio_volume", 1.0), "narration_audio_volume"),
    )


def parse_final_candidate_selection(value: object) -> FinalCandidateSelection:
    item = _exact(value, {"generation_id"}, "final.select_candidate")
    return FinalCandidateSelection(_id(item["generation_id"], "generation_id"))


def parse_final_approval(value: object) -> FinalApprovalRequest:
    item = _exact(value, {"zh_asset_id", "en_asset_id"}, "final.approve")
    return FinalApprovalRequest(
        None if item["zh_asset_id"] is None else _id(item["zh_asset_id"], "zh_asset_id"),
        None if item["en_asset_id"] is None else _id(item["en_asset_id"], "en_asset_id"),
    )


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    require_fields(f"{label}.arguments", value, keys)
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value


def _volume(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} 必须是有限数字。")
    if not 0.0 <= value <= 2.0:
        raise ValueError(f"{label} 必须在 0 到 2 之间。")
    return float(value)
