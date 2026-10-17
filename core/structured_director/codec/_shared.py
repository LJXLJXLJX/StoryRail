"""文档编解码：_shared 域的 parse/serialize 函数对（纯移动，语义/JSON key/错误消息不变）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _exact_object(value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("project.json 包含缺失或未声明的字段。")
    return value


def _object_list(value: object, parser: Callable[[object], Any]) -> tuple[Any, ...]:
    return tuple(parser(item) for item in _object_list_raw(value))


def _object_list_raw(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("project.json 集合必须是数组。")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串。")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须是整数。")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是数字。")
    return float(value)


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    return _number(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} 必须是布尔值。")
    return value


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} 必须是字符串数组。")
    return tuple(value)
