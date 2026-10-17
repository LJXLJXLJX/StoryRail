"""角色造型编辑命令：Agent 与人类共用的新增 / 修改造型原子操作。

删除造型只由人类在卡片编辑中完成；造型 ID 由 Core 分配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ID = re.compile(r"[0-9a-f]{32}")
LOOK_TEXT_FIELDS = frozenset({"name", "appearance", "usage"})


@dataclass(frozen=True, slots=True)
class AddLook:
    character_id: str
    name: str
    appearance: str
    usage: str


@dataclass(frozen=True, slots=True)
class UpdateLook:
    look_id: str
    fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class LookOperationsPatch:
    operations: tuple[AddLook | UpdateLook, ...]


def parse_look_operations_patch(value: object) -> LookOperationsPatch:
    root = _exact(value, {"operations"}, "reference.apply_look_operations.arguments")
    raw = root["operations"]
    if not isinstance(raw, list) or not raw or len(raw) > 32:
        raise ValueError("operations 必须是 1–32 个操作。")
    operations: list[AddLook | UpdateLook] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("operations 每项必须是 object。")
        op = item.get("op")
        if op == "add_look":
            fields = _exact(item, {"op", "character_id", *LOOK_TEXT_FIELDS}, "add_look")
            operations.append(
                AddLook(
                    _id(fields["character_id"], "character_id"),
                    *(_text(fields[name], name) for name in ("name", "appearance", "usage")),
                )
            )
        elif op == "update_look":
            fields = _exact(item, {"op", "look_id", "fields"}, "update_look")
            changes = fields["fields"]
            if not isinstance(changes, dict) or not changes or not set(changes) <= LOOK_TEXT_FIELDS:
                raise ValueError("update_look.fields 必须是 name/appearance/usage 的非空子集。")
            operations.append(
                UpdateLook(
                    _id(fields["look_id"], "look_id"),
                    {name: _text(text, name) for name, text in changes.items()},
                )
            )
        else:
            raise ValueError("op 只能是 add_look 或 update_look。")
    return LookOperationsPatch(tuple(operations))


def _exact(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} 包含缺失或未声明字段。")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label} 不合法。")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()
