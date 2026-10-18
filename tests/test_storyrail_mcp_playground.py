"""PG5-T3：MCP `--scope playground` 的 5 个工具、翻译与项目 scope 不变。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest
from mcp import Client

from integrations.storyrail_mcp.app import create_playground_server, create_server
from integrations.storyrail_mcp.bridge import CoreBridge
from integrations.storyrail_mcp.playground_tools import (
    PLAYGROUND_MODELS,
    PLAYGROUND_TOOL_NAMES,
    PlaygroundAssets,
    PlaygroundCapabilitiesRead,
    PlaygroundManageRun,
    PlaygroundRuns,
    PlaygroundSubmit,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_project_tools.json"
READ_KEY = re.compile(r"^mcp-read:[0-9a-f-]{36}$")
TARGET = "a" * 32


class RecordingBridge:
    """只记录翻译结果，不连接 Core。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def call_playground(self, name, key, arguments):
        self.calls.append((name, key, arguments))
        return 200, {"receipt": {"status": "noop"}, "data": {}}


def call(bridge, tool, arguments):
    async def run():
        async with Client(create_playground_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def test_project_scope_tools_list_unchanged():
    async def run():
        async with Client(create_server(None)) as client:
            listed = await client.list_tools()
        return [tool.model_dump(by_alias=True, exclude_none=True) for tool in listed.tools]

    payload = asyncio.run(run())
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert serialized == FIXTURE.read_text(encoding="utf-8")


def test_playground_scope_lists_exactly_five_tools():
    async def run():
        async with Client(create_playground_server(None)) as client:
            listed = await client.list_tools()
        return listed.tools

    tools = asyncio.run(run())
    assert [tool.name for tool in tools] == list(PLAYGROUND_TOOL_NAMES)
    assert set(PLAYGROUND_MODELS) == set(PLAYGROUND_TOOL_NAMES)
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.description


def test_submit_translates_to_envelope():
    bridge = RecordingBridge()
    result = call(
        bridge,
        "playground_submit",
        {
            "capability": "minimax_h3.fl2va",
            "parameters": {"prompt": "推近", "seed": 1},
            "note": "对比组A",
            "idempotency_key": "submit-1",
        },
    )
    assert not result.is_error
    assert bridge.calls == [
        (
            "playground.submit_run",
            "submit-1",
            {
                "capability": "minimax_h3.fl2va",
                "parameters": {"prompt": "推近", "seed": 1},
                "note": "对比组A",
            },
        )
    ]


def test_runs_action_schema_rejects_mixed_fields():
    with pytest.raises(ValueError):
        PlaygroundRuns.model_validate({"action": "get", "run_ids": [TARGET], "limit": 5})
    with pytest.raises(ValueError):
        PlaygroundRuns.model_validate({"action": "list", "run_ids": [TARGET]})
    with pytest.raises(ValueError):
        PlaygroundRuns.model_validate({"action": "wait", "run_ids": [TARGET] * 9})
    with pytest.raises(ValueError):
        PlaygroundRuns.model_validate({"action": "get"})

    bridge = RecordingBridge()
    included = call(
        bridge,
        "playground_runs",
        {
            "action": "list",
            "limit": 5,
            "cursor": None,
            "capability": None,
            "include_dismissed": True,
        },
    )
    assert not included.is_error
    name, key, arguments = bridge.calls[0]
    assert name == "playground.list_runs"
    assert READ_KEY.match(key)
    assert arguments == {
        "limit": 5,
        "cursor": None,
        "capability": None,
        "include_dismissed": True,
    }

    rejected = call(
        RecordingBridge(), "playground_runs", {"action": "get", "run_ids": [TARGET], "limit": 5}
    )
    assert rejected.is_error
    assert rejected.structured_content["error"]["code"] == "invalid_arguments"


def test_manage_run_note_only_for_set_note():
    with pytest.raises(ValueError):
        PlaygroundManageRun.model_validate(
            {"action": "set_note", "run_id": TARGET, "idempotency_key": "k"}
        )
    with pytest.raises(ValueError):
        PlaygroundManageRun.model_validate(
            {"action": "cancel", "run_id": TARGET, "note": "x", "idempotency_key": "k"}
        )

    bridge = RecordingBridge()
    cleared = call(
        bridge,
        "playground_manage_run",
        {"action": "set_note", "run_id": TARGET, "note": None, "idempotency_key": "note-1"},
    )
    assert not cleared.is_error
    cancelled = call(
        bridge,
        "playground_manage_run",
        {"action": "cancel", "run_id": TARGET, "idempotency_key": "cancel-1"},
    )
    assert not cancelled.is_error
    assert bridge.calls == [
        ("playground.set_note", "note-1", {"run_id": TARGET, "note": None}),
        ("playground.cancel_run", "cancel-1", {"run_id": TARGET}),
    ]


def test_read_tools_generate_internal_keys():
    bridge = RecordingBridge()
    results = [
        call(bridge, "playground_capabilities", {}),
        call(bridge, "playground_assets", {"limit": 10}),
        call(bridge, "playground_runs", {"action": "get", "run_ids": [TARGET]}),
        call(bridge, "playground_runs", {"action": "wait", "run_ids": [TARGET]}),
    ]
    assert all(not result.is_error for result in results)
    assert [name for name, _, _ in bridge.calls] == [
        "playground.list_capabilities",
        "playground.list_assets",
        "playground.get_runs",
        "playground.wait_runs",
    ]
    keys = [key for _, key, _ in bridge.calls]
    assert all(READ_KEY.match(key) for key in keys)
    assert len(set(keys)) == len(keys)
    assert bridge.calls[1][2] == {"limit": 10, "cursor": None, "media_kind": None}

    for model in (PlaygroundCapabilitiesRead, PlaygroundAssets, PlaygroundRuns):
        assert "idempotency_key" not in model.model_fields


def test_playground_tools_reject_project_id_argument():
    arguments = {
        "playground_capabilities": {"project_id": TARGET},
        "playground_submit": {
            "project_id": TARGET,
            "capability": "codex_image.generate",
            "parameters": {},
            "idempotency_key": "k",
        },
        "playground_runs": {"project_id": TARGET, "action": "list"},
        "playground_manage_run": {
            "project_id": TARGET,
            "action": "cancel",
            "run_id": TARGET,
            "idempotency_key": "k",
        },
        "playground_assets": {"project_id": TARGET},
    }
    for name, value in arguments.items():
        with pytest.raises(ValueError):
            PLAYGROUND_MODELS[name].model_validate(value)
        rejected = call(RecordingBridge(), name, value)
        assert rejected.is_error
        assert rejected.structured_content["error"]["code"] == "invalid_arguments"


def test_playground_models_are_strict():
    for model in PLAYGROUND_MODELS.values():
        assert model.model_config["extra"] == "forbid"
    assert "capability" in PlaygroundSubmit.model_fields
    assert "parameters" in PlaygroundSubmit.model_fields


def test_playground_mcp_against_http_server(http_server, tmp_path):
    token = "fixture_playground_" + "a" * 32
    http_server.policy_path.write_text(
        json.dumps(
            {
                "version": 2,
                "external_mutations": False,
                "callers": [
                    {
                        "id": "playground-agent",
                        "grants": [],
                        "role": "agent",
                        "project_ids": [],
                        "capabilities": ["playground.use"],
                        "expires_at": 4102444800,
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                    }
                ],
            }
        )
    )
    http_server.policy_path.chmod(0o600)
    token_file = tmp_path / "core-token"
    token_file.write_text(token)
    token_file.chmod(0o600)
    bridge = CoreBridge(http_server.base_url, token_file)

    async def run():
        async with Client(create_playground_server(bridge)) as client:
            return await client.call_tool("playground_capabilities", {})

    result = asyncio.run(run())
    assert not result.is_error, result
    assert result.structured_content["http_status"] == 200
    assert len(result.structured_content["data"]["capabilities"]) == 12
