"""四个 Agent-facing 边界共用完整错误信封。"""

from __future__ import annotations

from pathlib import Path

from core.structured_director.http_requests import _error as structured_error
from integrations.storyrail_mcp.bridge import CoreBridge
from server.api import _error as server_error
from storyrail_contracts.errors import error_payload

_FIELDS = {
    "code",
    "message",
    "recoverable",
    "origin",
    "state_changed",
    "retry_policy",
    "automatic_retry_allowed",
}


def _assert_complete(value: dict) -> None:
    assert set(value) == {"error"}
    assert set(value["error"]) >= _FIELDS
    assert value["error"]["automatic_retry_allowed"] is False


def test_single_builder_profiles_parser_errors():
    payload = error_payload("invalid_request", "请求不合法。")
    _assert_complete(payload)
    assert payload["error"]["origin"] == "core_parser"
    assert payload["error"]["retry_policy"] == "fix_arguments_and_retry"


def test_server_and_structured_http_use_complete_envelope():
    for response in (
        server_error(400, "invalid_request", "请求不合法。"),
        structured_error(400, "invalid_request", "请求不合法。"),
    ):
        _assert_complete(response.body)
        assert response.body["error"]["origin"] == "core_parser"


def test_mcp_bridge_local_error_uses_complete_envelope():
    status, payload = CoreBridge("http://127.0.0.1:1", Path("unused"))._send(
        "invalid-project", "project.get_handoff", None, "read", {}
    )
    assert status == 400
    _assert_complete(payload)
    assert payload["error"]["origin"] == "connector_serialization"
