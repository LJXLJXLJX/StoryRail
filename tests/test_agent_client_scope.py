"""PG5-T2：容器客户端按连接 scope 生成启动契约与 MCP 参数。"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from integrations.agent_launcher import client

PLAYGROUND_CONFIG = {
    "scope": "playground",
    "caller_id": "agent-synthetic",
    "token": "synthetic-agent-token",
    "origin": "http://gateway:8080",
}
PROJECT_CONFIG = {
    "project_id": "a" * 32,
    "revision": 3,
    "caller_id": "agent-synthetic",
    "token": "synthetic-agent-token",
    "origin": "http://gateway:8080",
}


@pytest.fixture
def container(monkeypatch):
    files: dict[str, str] = {"/tmp/.X11-unix/X99": "ready"}
    modes: dict[str, int] = {}

    class _FakePath:
        def __init__(self, value):
            self.value = str(value)

        def read_text(self, **kwargs):
            return files[self.value]

        def write_text(self, text, **kwargs):
            files[self.value] = text

        def chmod(self, mode):
            modes[self.value] = mode

        def exists(self):
            return self.value in files

        def __str__(self):
            return self.value

    monkeypatch.setattr(client, "Path", _FakePath)
    monkeypatch.setattr(
        client.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(poll=lambda: None)
    )
    return files, modes


def _stop_after_exec(monkeypatch, recorded):
    def execv(path, argv):
        recorded.append((path, argv))
        raise SystemExit(0)

    def execvp(name, argv):
        recorded.append((name, argv))
        raise SystemExit(0)

    monkeypatch.setattr(client.os, "execv", execv)
    monkeypatch.setattr(client.os, "execvp", execvp)


def test_playground_start_writes_scope_startup_without_project_id(container, monkeypatch):
    files, _ = container
    files["/workspace/connection.json"] = json.dumps(PLAYGROUND_CONFIG)
    files["/app/PLAYGROUND_PROMPT.md"] = "# Playground 工作区"
    recorded: list[tuple] = []
    _stop_after_exec(monkeypatch, recorded)
    monkeypatch.setattr(sys, "argv", ["client.py", "start", "pi"])

    with pytest.raises(SystemExit):
        asyncio.run(client.main())

    startup = json.loads(files["/workspace/startup.json"])
    assert startup == {"scope": "playground"}
    assert "project_id" not in startup
    assert files["/workspace/AGENTS.md"] == "# Playground 工作区"
    assert recorded[0][0] == "pi"


def test_project_start_contract_unchanged(container, monkeypatch):
    files, _ = container
    files["/workspace/connection.json"] = json.dumps(PROJECT_CONFIG)
    files["/app/PROMPT.md"] = "# 项目连接"
    recorded: list[tuple] = []
    _stop_after_exec(monkeypatch, recorded)
    monkeypatch.setattr(sys, "argv", ["client.py", "start", "pi"])

    with pytest.raises(SystemExit):
        asyncio.run(client.main())

    assert json.loads(files["/workspace/startup.json"]) == {
        "project_id": "a" * 32,
        "revision": 3,
    }
    assert files["/workspace/AGENTS.md"] == "# 项目连接"


def test_playground_mcp_arguments_append_scope(container, monkeypatch):
    files, modes = container
    files["/workspace/connection.json"] = json.dumps(PLAYGROUND_CONFIG)
    recorded: list[tuple] = []
    _stop_after_exec(monkeypatch, recorded)
    monkeypatch.setattr(sys, "argv", ["client.py", "mcp"])

    with pytest.raises(SystemExit):
        asyncio.run(client.main())

    _, argv = recorded[0]
    assert argv[-2:] == ["--scope", "playground"]
    assert modes["/workspace/core-token"] == 0o600


def test_project_mcp_arguments_have_no_scope(container, monkeypatch):
    files, _ = container
    files["/workspace/connection.json"] = json.dumps(PROJECT_CONFIG)
    recorded: list[tuple] = []
    _stop_after_exec(monkeypatch, recorded)
    monkeypatch.setattr(sys, "argv", ["client.py", "mcp"])

    with pytest.raises(SystemExit):
        asyncio.run(client.main())

    _, argv = recorded[0]
    assert argv[1:] == [
        "-m",
        "integrations.storyrail_mcp",
        "--core-origin",
        "http://gateway:8080",
        "--token-file",
        "/workspace/core-token",
    ]


class _FakeClient:
    def __init__(self, params):
        self.params = params

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exception):
        return False

    async def call_tool(self, name, arguments):
        return SimpleNamespace(model_dump_json=lambda: "{}", is_error=False)


def test_playground_manual_call_accepts_only_arguments_without_project_id(
    container, monkeypatch, capsys
):
    files, _ = container
    files["/workspace/connection.json"] = json.dumps(PLAYGROUND_CONFIG)
    monkeypatch.setattr(client, "Client", _FakeClient)
    monkeypatch.setattr(sys, "argv", ["client.py", "/tmp/request.json"])

    files["/tmp/request.json"] = json.dumps(
        {"tool": "playground_capabilities", "arguments": {"project_id": "a" * 32}}
    )
    with pytest.raises(ValueError, match="超出 Playground"):
        asyncio.run(client.main())

    files["/tmp/request.json"] = json.dumps({"tool": "playground_capabilities", "arguments": {}})
    asyncio.run(client.main())
    assert "{}" in capsys.readouterr().out


def test_unknown_scope_is_rejected(container, monkeypatch):
    files, _ = container
    files["/workspace/connection.json"] = json.dumps({**PROJECT_CONFIG, "scope": "other"})
    monkeypatch.setattr(sys, "argv", ["client.py", "mcp"])

    with pytest.raises(ValueError):
        asyncio.run(client.main())
