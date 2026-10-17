"""地点库与 Scene/Shot 地点绑定的窄写入契约。

`location.apply_operations` 是人类与 Agent 共用的编辑入口；候选选择（主图、视图）只有人类入口
`location.select_master` / `location.select_view`。同一 patch 内新建的地点、陈设、状态和视图
用局部 `key` 互相引用，Core 落库时分配正式 ID；上限、角度范围与二选一朝向由领域模型统一校验。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from typing import TypeAlias

_ID = re.compile(r"[0-9a-f]{32}")
_KEY = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_MAX_OPERATIONS = 100


def is_location_key(value: str) -> bool:
    """局部 key 与正式 ID 互斥：32 位十六进制一律按正式 ID 解析。"""
    return _KEY.fullmatch(value) is not None and _ID.fullmatch(value) is None


@dataclass(frozen=True, slots=True)
class LocationKeyLightInput:
    description: str
    azimuth_deg: float | None


@dataclass(frozen=True, slots=True)
class CreateLocation:
    key: str
    name: str
    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class UpdateLocation:
    """`fields` 只含请求中出现的字段：name、kind、description、key_light、
    master_prompt_text、master_reference_asset_ids。"""

    location_id: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeleteLocation:
    location_id: str


@dataclass(frozen=True, slots=True)
class UpsertFixture:
    """`fixture` 是已有陈设 ID（整体替换）或局部 key（首次出现即新建）。"""

    location_id: str
    fixture: str
    name: str
    description: str
    azimuth_deg: float | None


@dataclass(frozen=True, slots=True)
class DeleteFixture:
    location_id: str
    fixture_id: str


@dataclass(frozen=True, slots=True)
class UpsertState:
    location_id: str
    state: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class DeleteState:
    location_id: str
    state_id: str


@dataclass(frozen=True, slots=True)
class CreateView:
    """`fields` 必含 name、purpose 与一种朝向；未给出的几何与计划取模型默认值。"""

    location_id: str
    key: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class UpdateView:
    view_id: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeleteView:
    view_id: str


@dataclass(frozen=True, slots=True)
class CalibrateLocation:
    """按当前已选主图标定陈设方位；`key_light_azimuth_deg` 为 null 表示不改主光方位。"""

    location_id: str
    fixture_azimuths: tuple[tuple[str, float], ...]
    key_light_azimuth_deg: float | None


@dataclass(frozen=True, slots=True)
class BindScene:
    scene_id: str
    location_id: str | None
    state_id: str | None


@dataclass(frozen=True, slots=True)
class BindShot:
    """Shot 的地点视图建议（软参考）；删除该视图时清空绑定，已规划 Keyframe 不因此改写。"""

    shot_id: str
    view_id: str | None


@dataclass(frozen=True, slots=True)
class ClearMasterSelection:
    location_id: str


@dataclass(frozen=True, slots=True)
class ClearViewSelection:
    view_id: str


LocationOperation: TypeAlias = (
    CreateLocation
    | UpdateLocation
    | DeleteLocation
    | UpsertFixture
    | DeleteFixture
    | UpsertState
    | DeleteState
    | CreateView
    | UpdateView
    | DeleteView
    | CalibrateLocation
    | BindScene
    | BindShot
    | ClearMasterSelection
    | ClearViewSelection
)


@dataclass(frozen=True, slots=True)
class LocationOperationsPatch:
    scope_location_ids: tuple[str, ...]
    scope_scene_ids: tuple[str, ...]
    scope_shot_ids: tuple[str, ...]
    operations: tuple[LocationOperation, ...]


@dataclass(frozen=True, slots=True)
class LocationMasterSelection:
    location_id: str
    asset_id: str


@dataclass(frozen=True, slots=True)
class LocationViewSelection:
    view_id: str
    asset_id: str


_LOCATION_FIELDS = frozenset(
    {
        "name",
        "kind",
        "description",
        "key_light",
        "master_prompt_text",
        "master_reference_asset_ids",
    }
)
VIEW_FIELDS = (
    "name",
    "purpose",
    "azimuth_deg",
    "look_at_fixture_id",
    "yaw_offset_deg",
    "pitch_deg",
    "hfov_deg",
    "state_id",
    "refine_prompt_text",
    "reference_view_ids",
)


def parse_location_operations_patch(value: object) -> LocationOperationsPatch:
    root = _exact(value, {"scope", "operations"}, "location.apply_operations.arguments")
    scope = _exact(root["scope"], {"location_ids", "scene_ids", "shot_ids"}, "location scope")
    operations = root["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= _MAX_OPERATIONS:
        raise ValueError(f"location operations 必须有 1 到 {_MAX_OPERATIONS} 项。")
    return LocationOperationsPatch(
        _id_list(scope["location_ids"], "scope.location_ids"),
        _id_list(scope["scene_ids"], "scope.scene_ids"),
        _id_list(scope["shot_ids"], "scope.shot_ids"),
        tuple(_parse_operation(item) for item in operations),
    )


def parse_location_master_selection(value: object) -> LocationMasterSelection:
    item = _exact(value, {"location_id", "asset_id"}, "location.select_master.arguments")
    return LocationMasterSelection(
        _id(item["location_id"], "location_id"), _id(item["asset_id"], "asset_id")
    )


def parse_location_view_selection(value: object) -> LocationViewSelection:
    item = _exact(value, {"view_id", "asset_id"}, "location.select_view.arguments")
    return LocationViewSelection(_id(item["view_id"], "view_id"), _id(item["asset_id"], "asset_id"))


def _parse_operation(value: object) -> LocationOperation:
    if not isinstance(value, dict) or not isinstance(value.get("op"), str):
        raise ValueError("location operation 必须是带 op 的 object。")
    op = value["op"]
    if op == "create_location":
        x = _exact(value, {"op", "key", "name", "kind", "description"}, op)
        return CreateLocation(
            _key(x["key"]),
            _text(x["name"], "name", 200),
            _kind(x["kind"]),
            _text(x["description"], "description", 4_000, allow_empty=True),
        )
    if op == "update_location":
        x = _exact(value, {"op", "location_id", "fields"}, op)
        return UpdateLocation(_ref(x["location_id"], "location_id"), _location_fields(x["fields"]))
    if op == "delete_location":
        x = _exact(value, {"op", "location_id"}, op)
        return DeleteLocation(_id(x["location_id"], "location_id"))
    if op == "upsert_fixture":
        x = _exact(
            value, {"op", "location_id", "fixture", "name", "description", "azimuth_deg"}, op
        )
        return UpsertFixture(
            _ref(x["location_id"], "location_id"),
            _ref(x["fixture"], "fixture"),
            _text(x["name"], "name", 200),
            _text(x["description"], "description", 2_000, allow_empty=True),
            _optional_degrees(x["azimuth_deg"], "azimuth_deg"),
        )
    if op == "delete_fixture":
        x = _exact(value, {"op", "location_id", "fixture_id"}, op)
        return DeleteFixture(
            _ref(x["location_id"], "location_id"), _id(x["fixture_id"], "fixture_id")
        )
    if op == "upsert_state":
        x = _exact(value, {"op", "location_id", "state", "name", "description"}, op)
        return UpsertState(
            _ref(x["location_id"], "location_id"),
            _ref(x["state"], "state"),
            _text(x["name"], "name", 200),
            _text(x["description"], "description", 2_000),
        )
    if op == "delete_state":
        x = _exact(value, {"op", "location_id", "state_id"}, op)
        return DeleteState(_ref(x["location_id"], "location_id"), _id(x["state_id"], "state_id"))
    if op == "create_view":
        x = _exact(value, {"op", "location_id", "key", "fields"}, op)
        fields = x["fields"]
        if not isinstance(fields, dict) or not {"name", "purpose"} <= set(fields):
            raise ValueError("create_view.fields 必须包含 name 与 purpose。")
        return CreateView(
            _ref(x["location_id"], "location_id"), _key(x["key"]), _view_fields(fields)
        )
    if op == "update_view":
        x = _exact(value, {"op", "view_id", "fields"}, op)
        fields = x["fields"]
        if not isinstance(fields, dict) or not fields:
            raise ValueError("update_view.fields 必须是非空 object。")
        return UpdateView(_ref(x["view_id"], "view_id"), _view_fields(fields))
    if op == "delete_view":
        x = _exact(value, {"op", "view_id"}, op)
        return DeleteView(_id(x["view_id"], "view_id"))
    if op == "calibrate":
        x = _exact(value, {"op", "location_id", "fixture_azimuths", "key_light_azimuth_deg"}, op)
        azimuths = x["fixture_azimuths"]
        if not isinstance(azimuths, dict):
            raise ValueError("calibrate.fixture_azimuths 必须是 {fixture_id: azimuth_deg} object。")
        return CalibrateLocation(
            _ref(x["location_id"], "location_id"),
            tuple(
                (_ref(fixture, "fixture_azimuths key"), _degrees(degrees, "fixture_azimuths"))
                for fixture, degrees in azimuths.items()
            ),
            _optional_degrees(x["key_light_azimuth_deg"], "key_light_azimuth_deg"),
        )
    if op == "bind_scene":
        x = _exact(value, {"op", "scene_id", "location_id", "state_id"}, op)
        return BindScene(
            _id(x["scene_id"], "scene_id"),
            _optional_ref(x["location_id"], "location_id"),
            _optional_ref(x["state_id"], "state_id"),
        )
    if op == "bind_shot":
        x = _exact(value, {"op", "shot_id", "view_id"}, op)
        return BindShot(_id(x["shot_id"], "shot_id"), _optional_ref(x["view_id"], "view_id"))
    if op == "clear_master_selection":
        x = _exact(value, {"op", "location_id"}, op)
        return ClearMasterSelection(_id(x["location_id"], "location_id"))
    if op == "clear_view_selection":
        x = _exact(value, {"op", "view_id"}, op)
        return ClearViewSelection(_id(x["view_id"], "view_id"))
    raise ValueError(f"不支持的 location operation：{op}。")


def _location_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError("update_location.fields 必须是非空 object。")
    if not set(value) <= _LOCATION_FIELDS:
        raise ValueError("update_location.fields 包含未声明字段。")
    result: dict[str, object] = {}
    for name, item in value.items():
        if name == "name":
            result[name] = _text(item, name, 200)
        elif name == "kind":
            result[name] = _kind(item)
        elif name == "description":
            result[name] = _text(item, name, 4_000, allow_empty=True)
        elif name == "master_prompt_text":
            result[name] = _text(item, name, 19_000, allow_empty=True)
        elif name == "master_reference_asset_ids":
            result[name] = _id_list(item, name)
        elif item is None:
            result[name] = None
        else:
            light = _exact(item, {"description", "azimuth_deg"}, "key_light")
            result[name] = LocationKeyLightInput(
                _text(light["description"], "key_light.description", 1_000),
                _optional_degrees(light["azimuth_deg"], "key_light.azimuth_deg"),
            )
    return result


def _view_fields(value: dict[str, object]) -> dict[str, object]:
    if not set(value) <= set(VIEW_FIELDS):
        raise ValueError("视图字段包含未声明字段。")
    result: dict[str, object] = {}
    for name, item in value.items():
        if name == "name":
            result[name] = _text(item, name, 200)
        elif name == "purpose":
            result[name] = _text(item, name, 1_000)
        elif name == "refine_prompt_text":
            result[name] = _text(item, name, 19_000, allow_empty=True)
        elif name in {"look_at_fixture_id", "state_id"}:
            result[name] = _optional_ref(item, name)
        elif name == "reference_view_ids":
            if not isinstance(item, list):
                raise ValueError("reference_view_ids 必须是数组。")
            refs = tuple(_ref(x, name) for x in item)
            if len(refs) != len(set(refs)):
                raise ValueError("reference_view_ids 不能重复。")
            result[name] = refs
        elif name in {"pitch_deg", "hfov_deg"}:
            result[name] = _degrees(item, name)
        else:
            result[name] = _optional_degrees(item, name)
    return result


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} 包含缺失或未声明字段。")
    return value


def _text(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串。")
    text = value.strip()
    if (not text and not allow_empty) or len(text) > maximum:
        raise ValueError(f"{label} 必须是 {0 if allow_empty else 1} 到 {maximum} 字符。")
    return text


def _kind(value: object) -> str:
    if value not in {"interior", "exterior"}:
        raise ValueError("kind 必须是 interior 或 exterior。")
    return value


def _degrees(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} 必须是有限数值角度。")
    return float(value)


def _optional_degrees(value: object, label: str) -> float | None:
    return None if value is None else _degrees(value, label)


def _key(value: object) -> str:
    if not isinstance(value, str) or not is_location_key(value):
        raise ValueError("key 必须是 1 到 64 位小写字母开头的 [a-z0-9_-]，且不能是 32 位 ID。")
    return value


def _ref(value: object, label: str) -> str:
    if isinstance(value, str) and (_ID.fullmatch(value) or is_location_key(value)):
        return value
    raise ValueError(f"{label} 必须是 32 位小写十六进制 ID 或同一 patch 内新建项的 key。")


def _optional_ref(value: object, label: str) -> str | None:
    return None if value is None else _ref(value, label)


def _id_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 ID 数组。")
    result = tuple(_id(x, label) for x in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} 不能重复。")
    return result


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value
