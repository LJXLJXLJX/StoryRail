"""地点语义与独立图片条目的严格写入契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from typing import TypeAlias

from storyrail_contracts.fields import require_fields

_ID = re.compile(r"[0-9a-f]{32}")
_KEY = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_MAX_OPERATIONS = 100


def is_location_key(value: str) -> bool:
    return _KEY.fullmatch(value) is not None and _ID.fullmatch(value) is None


@dataclass(frozen=True, slots=True)
class LocationKeyLightInput:
    description: str


@dataclass(frozen=True, slots=True)
class PanoramaCaptureSourceInput:
    panorama_image_id: str
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float


@dataclass(frozen=True, slots=True)
class CreateLocation:
    key: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class UpdateLocation:
    location_id: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeleteLocation:
    location_id: str


@dataclass(frozen=True, slots=True)
class UpsertFixture:
    location_id: str
    fixture: str
    name: str
    description: str


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
class CreateLocationImage:
    location_id: str
    key: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class UpdateLocationImage:
    image_id: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeleteLocationImage:
    image_id: str


@dataclass(frozen=True, slots=True)
class BindScene:
    scene_id: str
    location_id: str | None
    state_id: str | None


@dataclass(frozen=True, slots=True)
class ClearLocationImageSelection:
    image_id: str


LocationOperation: TypeAlias = (
    CreateLocation
    | UpdateLocation
    | DeleteLocation
    | UpsertFixture
    | DeleteFixture
    | UpsertState
    | DeleteState
    | CreateLocationImage
    | UpdateLocationImage
    | DeleteLocationImage
    | BindScene
    | ClearLocationImageSelection
)


@dataclass(frozen=True, slots=True)
class LocationOperationsPatch:
    scope_location_ids: tuple[str, ...]
    scope_scene_ids: tuple[str, ...]
    operations: tuple[LocationOperation, ...]


@dataclass(frozen=True, slots=True)
class LocationImageSelection:
    image_id: str
    asset_id: str


_LOCATION_FIELDS = frozenset({"name", "description", "key_light"})
IMAGE_FIELDS = (
    "name",
    "kind",
    "description",
    "prompt_text",
    "reference_asset_ids",
    "source",
)


def parse_location_operations_patch(value: object) -> LocationOperationsPatch:
    root = _exact(value, {"scope", "operations"}, "location.apply_operations.arguments")
    scope = _exact(root["scope"], {"location_ids", "scene_ids"}, "location scope")
    operations = root["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= _MAX_OPERATIONS:
        raise ValueError(f"location operations 必须有 1 到 {_MAX_OPERATIONS} 项。")
    return LocationOperationsPatch(
        _id_list(scope["location_ids"], "scope.location_ids"),
        _id_list(scope["scene_ids"], "scope.scene_ids"),
        tuple(_parse_operation(item) for item in operations),
    )


def parse_location_image_selection(value: object) -> LocationImageSelection:
    item = _exact(value, {"image_id", "asset_id"}, "location.select_image.arguments")
    return LocationImageSelection(
        _id(item["image_id"], "image_id"), _id(item["asset_id"], "asset_id")
    )


def _parse_operation(value: object) -> LocationOperation:
    if not isinstance(value, dict) or not isinstance(value.get("op"), str):
        raise ValueError("location operation 必须是带 op 的 object。")
    op = value["op"]
    if op == "create_location":
        x = _exact(value, {"op", "key", "name", "description"}, op)
        return CreateLocation(
            _key(x["key"]),
            _text(x["name"], "name", 200),
            _text(x["description"], "description", 4_000, allow_empty=True),
        )
    if op == "update_location":
        x = _exact(value, {"op", "location_id", "fields"}, op)
        return UpdateLocation(_ref(x["location_id"], "location_id"), _location_fields(x["fields"]))
    if op == "delete_location":
        x = _exact(value, {"op", "location_id"}, op)
        return DeleteLocation(_id(x["location_id"], "location_id"))
    if op == "upsert_fixture":
        x = _exact(value, {"op", "location_id", "fixture", "name", "description"}, op)
        return UpsertFixture(
            _ref(x["location_id"], "location_id"),
            _ref(x["fixture"], "fixture"),
            _text(x["name"], "name", 200),
            _text(x["description"], "description", 2_000, allow_empty=True),
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
    if op == "create_image":
        x = _exact(value, {"op", "location_id", "key", "fields"}, op)
        fields = x["fields"]
        if not isinstance(fields, dict) or not {"name", "kind", "description"} <= set(fields):
            raise ValueError("create_image.fields 必须包含 name、kind 与 description。")
        return CreateLocationImage(
            _ref(x["location_id"], "location_id"), _key(x["key"]), _image_fields(fields)
        )
    if op == "update_image":
        x = _exact(value, {"op", "image_id", "fields"}, op)
        if not isinstance(x["fields"], dict) or not x["fields"]:
            raise ValueError("update_image.fields 必须是非空 object。")
        return UpdateLocationImage(_ref(x["image_id"], "image_id"), _image_fields(x["fields"]))
    if op == "delete_image":
        x = _exact(value, {"op", "image_id"}, op)
        return DeleteLocationImage(_id(x["image_id"], "image_id"))
    if op == "bind_scene":
        x = _exact(value, {"op", "scene_id", "location_id", "state_id"}, op)
        return BindScene(
            _id(x["scene_id"], "scene_id"),
            _optional_ref(x["location_id"], "location_id"),
            _optional_ref(x["state_id"], "state_id"),
        )
    if op == "clear_image_selection":
        x = _exact(value, {"op", "image_id"}, op)
        return ClearLocationImageSelection(_id(x["image_id"], "image_id"))
    raise ValueError(f"不支持的 location operation：{op}。")


def _location_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not value or not set(value) <= _LOCATION_FIELDS:
        raise ValueError("update_location.fields 为空或包含未声明字段。")
    result: dict[str, object] = {}
    for name, item in value.items():
        if name == "name":
            result[name] = _text(item, name, 200)
        elif name == "description":
            result[name] = _text(item, name, 4_000, allow_empty=True)
        elif item is None:
            result[name] = None
        else:
            light = _exact(item, {"description"}, "key_light")
            result[name] = LocationKeyLightInput(
                _text(light["description"], "key_light.description", 1_000)
            )
    return result


def _image_fields(value: dict[str, object]) -> dict[str, object]:
    if not set(value) <= set(IMAGE_FIELDS):
        raise ValueError("地点图片字段包含未声明字段。")
    result: dict[str, object] = {}
    for name, item in value.items():
        if name == "name":
            result[name] = _text(item, name, 200)
        elif name == "kind":
            if item not in {"image", "panorama"}:
                raise ValueError("image.kind 必须是 image 或 panorama。")
            result[name] = item
        elif name == "description":
            result[name] = _text(item, name, 4_000)
        elif name == "prompt_text":
            result[name] = _text(item, name, 19_000, allow_empty=True)
        elif name == "reference_asset_ids":
            result[name] = _id_list(item, name)
        elif item is None:
            result[name] = None
        else:
            source = _exact(
                item, {"panorama_image_id", "yaw_deg", "pitch_deg", "hfov_deg"}, "source"
            )
            result[name] = PanoramaCaptureSourceInput(
                _ref(source["panorama_image_id"], "source.panorama_image_id"),
                _degrees(source["yaw_deg"], "source.yaw_deg"),
                _degrees(source["pitch_deg"], "source.pitch_deg"),
                _degrees(source["hfov_deg"], "source.hfov_deg"),
            )
    return result


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    require_fields(label, value, keys)
    return value


def _text(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串。")
    text = value.strip()
    if (not text and not allow_empty) or len(text) > maximum:
        raise ValueError(f"{label} 必须是 {0 if allow_empty else 1} 到 {maximum} 字符。")
    return text


def _degrees(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} 必须是有限数值角度。")
    return float(value)


def _key(value: object) -> str:
    if not isinstance(value, str) or not is_location_key(value):
        raise ValueError("key 必须是小写字母开头的 [a-z0-9_-]，且不能是 32 位 ID。")
    return value


def _ref(value: object, label: str) -> str:
    if isinstance(value, str) and (_ID.fullmatch(value) or is_location_key(value)):
        return value
    raise ValueError(f"{label} 必须是正式 ID 或同一 patch 内的新建 key。")


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
