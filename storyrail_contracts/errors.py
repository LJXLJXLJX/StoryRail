"""Agent-facing HTTP/MCP 错误信封的唯一构造入口。"""

from __future__ import annotations

from typing import Any


def error_profile(code: str) -> tuple[str, str]:
    if code in {
        "invalid_json",
        "invalid_request",
        "invalid_content_length",
        "unsupported_media_type",
        "request_too_large",
    }:
        return "core_parser", "fix_arguments_and_retry"
    if code == "revision_conflict":
        return "core_revision", "reread_then_reissue_if_still_intended"
    if code in {"provider_unavailable", "agent_unavailable"}:
        return "provider_boundary", "restore_dependency_then_replay_same_request"
    if code == "result_too_large":
        return "response_envelope", "narrow_or_continue_read"
    if code in {"not_found", "project_not_found", "project_state_missing"}:
        return "core_routing", "correct_target_and_retry"
    return "core_domain", "change_business_state_or_request"


def error_payload(
    code: str,
    message: str,
    *,
    recoverable: bool = False,
    details: dict[str, object] | None = None,
    origin: str | None = None,
    state_changed: bool | str = False,
    retry_policy: str | None = None,
    automatic_retry_allowed: bool = False,
) -> dict[str, Any]:
    """构造 docs/error-contract.md 定义的完整错误信封。"""
    profile_origin, profile_retry = error_profile(code)
    return {
        "error": {
            "code": code,
            "message": message,
            "recoverable": recoverable,
            "origin": origin or profile_origin,
            "state_changed": state_changed,
            "retry_policy": retry_policy or profile_retry,
            "automatic_retry_allowed": automatic_retry_allowed,
            **({} if details is None else details),
        }
    }
