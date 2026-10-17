from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.director_commands import (
    DirectorCommand,
)

from .models import (
    Scene,
    StructuredDirectorDocument,
)


@dataclass(frozen=True, slots=True)
class _ProductionCommandRequest:
    command: DirectorCommand
    reply_markdown: str
    raw_user_request: str


@dataclass(frozen=True, slots=True)
class _ProductionCommandOutcome:
    document: StructuredDirectorDocument
    reply_markdown: str | None


def _required_keyframe_shared_boundaries(
    compiler_context: str,
) -> tuple[tuple[str, str], ...]:
    try:
        parsed = json.loads(compiler_context)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, dict):
        return ()
    scope_guard = parsed.get("scope_guard", {})
    if not isinstance(scope_guard, dict):
        raise ValueError("Keyframe Compiler scope_guard 必须是 object。")
    raw_boundaries = scope_guard.get("required_shared_boundaries", [])
    if not isinstance(raw_boundaries, list):
        raise ValueError("Keyframe Compiler required_shared_boundaries 必须是数组。")
    boundaries: list[tuple[str, str]] = []
    for item in raw_boundaries:
        if not isinstance(item, dict) or set(item) != {
            "left_segment_id",
            "right_segment_id",
        }:
            raise ValueError("Keyframe Compiler 共享边界字段不合法。")
        left = item["left_segment_id"]
        right = item["right_segment_id"]
        if (
            not isinstance(left, str)
            or not isinstance(right, str)
            or re.fullmatch(r"[0-9a-f]{32}", left) is None
            or re.fullmatch(r"[0-9a-f]{32}", right) is None
        ):
            raise ValueError("Keyframe Compiler 共享边界 ID 不合法。")
        boundaries.append((left, right))
    result = tuple(boundaries)
    if len(result) != len(set(result)):
        raise ValueError("Keyframe Compiler 共享边界不能重复。")
    return result


def _validate_required_keyframe_boundary_scope(
    scenes: tuple[Scene, ...],
    boundaries: tuple[tuple[str, str], ...],
    *,
    target_shot_ids: set[str] | None = None,
) -> None:
    adjacent = {
        (left_shot.segments[-1].id, right_shot.segments[0].id): (
            left_shot.id,
            right_shot.id,
        )
        for scene in scenes
        for left_shot, right_shot in zip(scene.shots, scene.shots[1:], strict=False)
    }
    unknown = set(boundaries) - set(adjacent)
    if unknown:
        raise ValueError("Keyframe Compiler 共享边界超出目标 Scene 或不是真实相邻 Shot。")
    if target_shot_ids is not None:
        missing = tuple(
            dict.fromkeys(
                shot_id
                for boundary in boundaries
                for shot_id in adjacent[boundary]
                if shot_id not in target_shot_ids
            )
        )
        if missing:
            raise ValueError(
                "Keyframe Compiler 共享边界越出可写 Shot；请至少扩大目标范围到："
                + "、".join(missing)
                + "。"
            )


def _production_command_target_ids(command: DirectorCommand) -> tuple[str, ...]:
    required = {"target_ids", "user_instruction"}
    if not required <= set(command.arguments) or not set(command.arguments) <= (
        required | {"options"}
    ):
        raise ValueError("生产 command arguments 包含缺失或未声明字段。")
    value = command.arguments["target_ids"]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("生产 command target_ids 必须是字符串数组。")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise ValueError("生产 command target_ids 不能重复。")
    return result


def _production_command_user_instruction(command: DirectorCommand) -> str:
    value = command.arguments["user_instruction"]
    if not isinstance(value, str) or len(value) > 20_000:
        raise ValueError("生产 command user_instruction 必须是最多 20000 字的文本。")
    return value


def _production_command_options(command: DirectorCommand) -> dict[str, object]:
    value = command.arguments.get("options", {})
    if not isinstance(value, dict):
        raise ValueError("生产 command options 必须是 object。")
    allowed = {
        "video.generate": {"seed"},
        "narration.generate": {"language"},
    }.get(command.name, set())
    if not set(value) <= allowed:
        raise ValueError(f"{command.name} options 包含未声明字段。")
    return dict(value)
