"""Typed intent handoff, never an alternative source of project facts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

CompilerName = Literal[
    "reference_library",
    "script",
    "narration",
    "keyframe_plan",
    "keyframe_prompt",
    "video_prompt",
]
COMPILER_NAMES = (
    "reference_library",
    "script",
    "narration",
    "keyframe_plan",
    "keyframe_prompt",
    "video_prompt",
)
_ID = re.compile(r"[0-9a-f]{32}")
_FIELDS = {
    "raw_user_request",
    "user_constraints",
    "director_hypotheses",
    "core_facts",
    "scope_guard",
    "target_ids",
}


@dataclass(frozen=True, slots=True)
class SharedBoundaryConstraint:
    left_segment_id: str
    right_segment_id: str


@dataclass(frozen=True, slots=True)
class CompilerIntent:
    name: CompilerName
    raw_user_request: str
    user_constraints: tuple[str, ...]
    director_hypotheses: tuple[str, ...]
    target_ids: tuple[str, ...]
    scope_kind: Literal["project", "scene", "shot", "segment"] | None
    required_shared_boundaries: tuple[SharedBoundaryConstraint, ...]

    def context_json(self) -> str:
        scope: dict[str, object] = {"target_ids": list(self.target_ids)}
        if self.scope_kind is not None:
            scope["kind"] = self.scope_kind
        if self.name == "keyframe_plan":
            scope["required_shared_boundaries"] = [
                {"left_segment_id": x.left_segment_id, "right_segment_id": x.right_segment_id}
                for x in self.required_shared_boundaries
            ]
        return json.dumps(
            {
                "compiler_name": self.name,
                "raw_user_request": self.raw_user_request,
                "user_constraints": list(self.user_constraints),
                "director_hypotheses": list(self.director_hypotheses),
                # Actual facts arrive separately in each capability's typed Core input.
                "core_facts": {"source": "project.json"},
                "scope_guard": scope,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def parse_compiler_intent(
    name: str,
    arguments: object,
    *,
    raw_user_request: str,
) -> CompilerIntent:
    if name not in COMPILER_NAMES:
        raise ValueError("Director compiler name 不合法。")
    if not isinstance(arguments, dict) or not set(arguments) <= _FIELDS:
        raise ValueError("Director compiler arguments 包含未声明字段。")
    if not isinstance(raw_user_request, str) or not raw_user_request.strip():
        raise ValueError("Compiler 必须保留本轮真实用户原话。")
    if len(raw_user_request) > 20_000:
        raise ValueError("Compiler 用户原话过长。")
    targets = _strings(arguments.get("target_ids", []), "target_ids", 500)
    if len(set(targets)) != len(targets) or any(not _ID.fullmatch(x) for x in targets):
        raise ValueError("Compiler target_ids 必须是不重复的有效 ID。")
    facts = arguments.get("core_facts", {})
    if not isinstance(facts, dict) or facts not in ({}, {"source": "project.json"}):
        raise ValueError("Compiler core_facts 只能声明来源，事实必须由 Core 注入。")
    scope = arguments.get("scope_guard", {})
    if not isinstance(scope, dict) or not set(scope) <= {"kind", "required_shared_boundaries"}:
        raise ValueError("Compiler scope_guard 包含未声明字段。")
    kind = scope.get("kind")
    if kind is not None and kind not in {"project", "scene", "shot", "segment"}:
        raise ValueError("Compiler scope kind 不合法。")
    boundaries = scope.get("required_shared_boundaries", [])
    if not isinstance(boundaries, list) or len(boundaries) > 500:
        raise ValueError("Compiler 共享边界必须是有界数组。")
    if boundaries and name != "keyframe_plan":
        raise ValueError("只有 Keyframe plan Compiler 接受共享边界约束。")
    parsed = []
    for item in boundaries:
        if not isinstance(item, dict) or set(item) != {"left_segment_id", "right_segment_id"}:
            raise ValueError("Compiler 共享边界字段不合法。")
        left, right = item["left_segment_id"], item["right_segment_id"]
        if any(not isinstance(x, str) or not _ID.fullmatch(x) for x in (left, right)):
            raise ValueError("Compiler 共享边界 ID 不合法。")
        if left == right:
            raise ValueError("Compiler 共享边界必须连接不同 Segment。")
        parsed.append(SharedBoundaryConstraint(left, right))
    if len(set(parsed)) != len(parsed):
        raise ValueError("Compiler 共享边界不能重复。")
    return CompilerIntent(
        name=name,
        raw_user_request=raw_user_request,
        user_constraints=_strings(arguments.get("user_constraints", []), "user_constraints", 100),
        director_hypotheses=_strings(
            arguments.get("director_hypotheses", []),
            "director_hypotheses",
            100,
        ),
        target_ids=targets,
        scope_kind=kind,
        required_shared_boundaries=tuple(parsed),
    )


def _strings(value: object, field: str, maximum: int) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(not isinstance(x, str) or not x.strip() or len(x) > 20_000 for x in value)
    ):
        raise ValueError(f"Compiler {field} 必须是有界非空字符串数组。")
    return tuple(value)


def context_value(user_message: str) -> str | dict[str, object]:
    """Avoid JSON-inside-JSON escaping, without treating free user text as authority."""
    try:
        value = json.loads(user_message)
    except json.JSONDecodeError:
        return user_message
    if not isinstance(value, dict) or value.get("compiler_name") not in COMPILER_NAMES:
        return user_message
    if set(value) != {
        "compiler_name",
        "raw_user_request",
        "user_constraints",
        "director_hypotheses",
        "core_facts",
        "scope_guard",
    }:
        return user_message
    scope = value.get("scope_guard")
    if not isinstance(scope, dict):
        return user_message
    scope = dict(scope)
    arguments = {k: v for k, v in value.items() if k != "compiler_name"}
    arguments["target_ids"] = scope.pop("target_ids", [])
    arguments["scope_guard"] = scope
    try:
        intent = parse_compiler_intent(
            value["compiler_name"],
            arguments,
            raw_user_request=value["raw_user_request"],
        )
    except ValueError:
        return user_message
    return json.loads(intent.context_json())
