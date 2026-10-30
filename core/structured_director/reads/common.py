"""read_tools 与 reads 包共享的纯读辅助函数（参数校验、JSON 投影、结果界）。

从 read_tools.py 下沉的叶子模块：只依赖 errors/models，供同包模块模块级复用，
避免 read_tools ↔ execution_reads / semantic_projection / professional_worksets
互相 `from import` 造成运行时环。
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from storyrail_contracts.fields import require_fields

from ..errors import InvalidArgumentsError
from ..models import Asset

_MAX_RESULT_BYTES = 128 * 1024
_MAX_RESULT_OBJECTS = 500


class ReadResultTooLarge(ValueError):
    """调用方可缩小读取页，不能吞掉其他契约错误。"""


def _validate_result_bounds(result: dict[str, object]) -> None:
    if _object_count(result) > _MAX_RESULT_OBJECTS:
        raise ReadResultTooLarge("Director read tool 结果对象过多，请缩小 scope 或使用分页。")
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_RESULT_BYTES:
        raise ReadResultTooLarge("Director read tool 结果超过 128 KiB，请缩小 layers 或使用分页。")


def _object_count(value: object) -> int:
    if isinstance(value, dict):
        return 1 + sum(_object_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_object_count(item) for item in value)
    return 0


def _exact_arguments(
    arguments: dict[str, object],
    *,
    required: set[str] = frozenset(),
    optional: set[str] = frozenset(),
) -> None:
    require_fields("读取参数", arguments, required, optional, error=InvalidArgumentsError)


def _ids(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise InvalidArgumentsError(f"{label} 必须是非空 ID 数组。")
    result = tuple(_id(item, label) for item in value)
    if len(result) != len(set(result)):
        raise InvalidArgumentsError(f"{label} 不能重复。")
    return result


def _id(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise InvalidArgumentsError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _asset_summary(asset: Asset) -> dict[str, object]:
    return {
        "id": asset.id,
        "display_name": asset.display_name,
        "media_type": asset.media_type,
        "byte_count": asset.byte_count,
        "duration_seconds": asset.duration_seconds,
        "image_category": None if asset.image_category is None else asset.image_category.value,
    }
