from __future__ import annotations

import re
from dataclasses import dataclass

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class GenerationTarget:
    generation_id: str


@dataclass(frozen=True, slots=True)
class GenerationWait:
    generation_ids: tuple[str, ...]


def parse_generation_target(value: object, command_name: str) -> GenerationTarget:
    item = _exact(value, {"generation_id"}, command_name)
    return GenerationTarget(_id(item["generation_id"], "generation_id"))


def parse_generation_wait(value: object) -> GenerationWait:
    item = _exact(value, {"generation_ids"}, "generation.wait")
    raw_ids = item["generation_ids"]
    if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 100:
        raise ValueError("generation.wait.generation_ids 必须包含 1 到 100 个 ID。")
    result = tuple(_id(value, "generation_ids") for value in raw_ids)
    if len(result) != len(set(result)):
        raise ValueError("generation.wait.generation_ids 不能重复。")
    return GenerationWait(result)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label}.arguments 包含缺失或未声明字段。")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value
