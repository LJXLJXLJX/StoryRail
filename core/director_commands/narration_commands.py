from __future__ import annotations

import re
from dataclasses import dataclass

from core.director_proposals.wire_fields import (
    NARRATION_CUE_EDIT_FIELDS,
    NARRATION_LANGUAGE_KEYS,
    NARRATION_TRACK_EDIT_FIELDS,
)
from core.model_providers.recipe import RecipeParams

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class NarrationCueUpdate:
    """按语言（zh / en）分组的轨道字段。"""

    scope_scene_ids: tuple[str, ...]
    cue_id: str
    track_fields: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class NarrationSelectionClear:
    scope_scene_ids: tuple[str, ...]
    cue_id: str
    language: str


def parse_narration_cue_update(value: object) -> NarrationCueUpdate:
    root = _exact(value, {"scope", "cue_id", "fields"}, "narration.update_cue.arguments")
    scene_ids = _scope(root["scope"])
    raw_fields = root["fields"]
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise ValueError("narration.update_cue.fields 必须是非空 object。")
    if not set(raw_fields) <= NARRATION_CUE_EDIT_FIELDS:
        raise ValueError("narration.update_cue.fields 包含未声明字段。")
    track_fields = {
        name: _track_fields(item, f"fields.{name}") for name, item in raw_fields.items()
    }
    return NarrationCueUpdate(scene_ids, _id(root["cue_id"], "cue_id"), track_fields)


def _track_fields(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"narration.update_cue.{label} 必须是非空 object。")
    if not set(value) <= NARRATION_TRACK_EDIT_FIELDS:
        raise ValueError(f"narration.update_cue.{label} 包含未声明字段。")
    fields: dict[str, object] = {}
    for name, item in value.items():
        if name == "text":
            fields[name] = _string(item, f"{label}.text")
        elif name == "recipe_params":
            # 逐 recipe 合并；取值是否符合 recipe 由 Core 写入时按 manifest 校验。
            fields[name] = RecipeParams.from_json(item, f"{label}.recipe_params")
        else:
            fields[name] = _seed(item)
    return fields


def parse_narration_selection_clear(value: object) -> NarrationSelectionClear:
    root = _exact(
        value,
        {"scope", "cue_id", "language"},
        "narration.clear_selection.arguments",
    )
    return NarrationSelectionClear(
        _scope(root["scope"]),
        _id(root["cue_id"], "cue_id"),
        parse_narration_language(root["language"]),
    )


def parse_narration_language(value: object) -> str:
    if value not in NARRATION_LANGUAGE_KEYS:
        raise ValueError("language 只允许 zh 或 en。")
    return str(value)


def _scope(value: object) -> tuple[str, ...]:
    item = _exact(value, {"scene_ids"}, "narration scope")
    raw_ids = item["scene_ids"]
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("narration scope.scene_ids 必须是非空 ID 数组。")
    result = tuple(_id(item_id, "scope.scene_ids") for item_id in raw_ids)
    if len(result) != len(set(result)):
        raise ValueError("narration scope.scene_ids 不能重复。")
    return result


def _seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**63 - 1:
        raise ValueError("seed 必须是有效非负整数。")
    return value


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} 包含缺失或未声明字段。")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()


def _id(value: object, label: str) -> str:
    result = _string(value, label)
    if _ID.fullmatch(result) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return result
