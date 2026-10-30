"""真实 socket/HTTP 的只读接入、空闲启动与重连权限回归。"""

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path

import pytest
from mcp.types import ListToolsResult, Tool

from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService
from integrations.agent_launcher.__main__ import control
from integrations.agent_launcher.client import _render_tool_listing
from server.api import StoryRailApi
from server.http import StoryRailHttpServer
from server.local_connection import LocalConnection


@contextmanager
def running():
    with tempfile.TemporaryDirectory(prefix="sr-connect-") as directory:
        root = Path(directory).resolve()
        workspaces = ProjectWorkspaceStore(root / "stories")
        api = StoryRailApi(
            workspaces,
            lambda pid: StructuredDirectorService(workspaces.structured_director_store(pid)),
        )
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever)
        thread.start()
        local = LocalConnection(
            root / "access", api, loop, lambda: [p.id for p in workspaces.list()]
        )
        server = StoryRailHttpServer(
            ("127.0.0.1", 0), api, loop, access_policy_file=local.policy_path
        )
        server.local_connection = local
        http_thread = threading.Thread(target=server.serve_forever)
        http_thread.start()
        try:
            yield server, local, workspaces
        finally:
            server.shutdown()
            server.server_close()
            http_thread.join()
            local.close()
            loop.call_soon_threadsafe(loop.stop)
            thread.join()
            loop.close()


def request(server, method, path, value=None, headers=None):
    client = HTTPConnection(*server.server_address, timeout=5)
    try:
        client.request(
            method,
            path,
            json.dumps(value) if value is not None else None,
            {"Content-Type": "application/json", **(headers or {})},
        )
        response = client.getresponse()
        body = response.read()
        return response.status, json.loads(body) if body else {}, dict(response.getheaders())
    finally:
        client.close()


def login(server, local):
    ticket = control(local.socket_path, {"action": "browser"})["login"]
    status, _, headers = request(
        server,
        "POST",
        "/api/local-session",
        {"ticket": ticket},
        {"Origin": "http://127.0.0.1:5173"},
    )
    assert status == 204
    assert "HttpOnly" in headers["Set-Cookie"]
    assert (
        request(
            server,
            "POST",
            "/api/local-session",
            {"ticket": ticket},
            {"Origin": "http://127.0.0.1:5173"},
        )[0]
        == 401
    )
    return {"Cookie": headers["Set-Cookie"].split(";")[0], "Origin": "http://127.0.0.1:5173"}


def test_client_tool_listing_defaults_to_names_and_can_select_one_schema():
    listed = ListToolsResult(
        tools=[
            Tool(name="read_human_handoff", inputSchema={"type": "object"}),
            Tool(
                name="read_professional_contract",
                inputSchema={"type": "object", "required": ["capability"]},
            ),
        ]
    )

    assert json.loads(_render_tool_listing(listed)) == {
        "tools": ["read_human_handoff", "read_professional_contract"]
    }
    detailed = json.loads(_render_tool_listing(listed, "read_professional_contract"))
    assert [tool["name"] for tool in detailed["tools"]] == ["read_professional_contract"]
    assert detailed["tools"][0]["input_schema"]["required"] == ["capability"]
    with pytest.raises(ValueError, match="未知工具：missing"):
        _render_tool_listing(listed, "missing")


def create(server, headers):
    status, result, _ = request(
        server,
        "POST",
        "/api/projects",
        {
            "title": "连接验收",
            "aspect_ratio": "16:9",
            "director_plan_markdown": "# 末班车\n小满独自等车。",
            "narration_languages": ["zh", "en"],
        },
        headers,
    )
    assert status == 201, result
    return result["project"]["id"]


def test_connect_delegates_current_project_without_starting_a_task():
    with running() as (server, local, workspaces):
        headers = login(server, local)
        pid = create(server, headers)
        before = workspaces.structured_director_store(pid).path.read_bytes()
        connection = control(local.socket_path, {"action": "connect", "project_id": pid})
        assert "initial_request" not in connection
        assert workspaces.structured_director_store(pid).path.read_bytes() == before
        assert control(local.socket_path, {"action": "connect", "project_id": pid}) == connection
        resource = f"/api/projects/{pid}/structured-director/application/commands"
        agent = {"Authorization": "Bearer " + connection["token"]}
        status, result, _ = request(
            server,
            "POST",
            resource,
            {
                "name": "project.get_handoff",
                "expected_revision": connection["revision"],
                "idempotency_key": "read-handoff",
                "arguments": {},
            },
            agent,
        )
        assert status == 200, result
        status, _, _ = request(
            server,
            "POST",
            resource,
            {
                "name": "reference.request_proposal",
                "expected_revision": connection["revision"],
                "idempotency_key": "explicit-user-request",
                "arguments": {"raw_user_instruction": "整理引用库"},
            },
            agent,
        )
        assert status == 200
        assert workspaces.structured_director_store(pid).read().active_director_run is not None
        assert request(server, "GET", "/api/projects")[0] == 401
        with pytest.raises(ValueError):
            control(local.socket_path, {"action": "reference", "project_id": pid})


def test_connection_replaces_old_automatic_grants_without_business_writes():
    with running() as (server, local, workspaces):
        pid = create(server, login(server, local))
        connection = control(local.socket_path, {"action": "connect", "project_id": pid})
        policy = local._load()
        caller = next(c for c in policy["callers"] if c["id"] == connection["caller_id"])
        caller["capabilities"] = ["project.read", "project.mutate", "project.propose"]
        caller["grants"] = [
            {"id": "old", "project_id": pid, "command_digest": "a" * 64, "expires_at": 9999999999}
        ]
        caller["expires_at"] = 1
        local._save(policy)
        before = workspaces.structured_director_store(pid).path.read_bytes()
        assert control(local.socket_path, {"action": "connect", "project_id": pid}) == connection
        renewed = next(c for c in local._load()["callers"] if c["id"] == connection["caller_id"])
        assert set(renewed["capabilities"]) == {
            "project.read",
            "project.mutate",
            "project.propose",
            "project.execute",
        }
        assert renewed["grants"] == []
        assert workspaces.structured_director_store(pid).path.read_bytes() == before


def test_connection_directory_cannot_be_shared_by_two_writers():
    with running() as (server, local, _), pytest.raises(ValueError, match="其它服务"):
        LocalConnection(local.directory, server.api, server.event_loop, lambda: [])


def test_local_agent_reference_then_script_without_manual_policy_edits():
    from test_external_reference_proposals import PROPOSAL
    from test_external_script_proposals import mixed_proposal

    with running() as (server, local, workspaces):
        human = login(server, local)
        pid = create(server, human)
        connection = control(local.socket_path, {"action": "connect", "project_id": pid})
        agent = {"Authorization": "Bearer " + connection["token"]}
        store = workspaces.structured_director_store(pid)
        resource = f"/api/projects/{pid}/structured-director/application/commands"

        def execute(name, key, **arguments):
            command = {
                "name": name,
                "expected_revision": store.read().revision,
                "idempotency_key": key,
                "arguments": arguments,
            }
            status, result, _ = request(server, "POST", resource, command, agent)
            assert status == 200, result
            return command, result

        _, ref = execute(
            "reference.request_proposal", "reference-request", raw_user_instruction="整理引用库"
        )
        execute(
            "reference.submit_proposal",
            "reference-submit",
            request_id=ref["data"]["request_id"],
            proposal=PROPOSAL,
        )
        status, result, _ = request(
            server,
            "POST",
            resource,
            {
                "name": "reference.confirm_review",
                "expected_revision": store.read().revision,
                "idempotency_key": "human-review",
                "arguments": {},
            },
            human,
        )
        assert status == 200, result
        # 后继指令不需要修改 policy，也不借用人类身份。
        _, script = execute(
            "script.request_proposal", "script-request", raw_user_instruction="按当前引用库生成脚本"
        )
        rid = script["data"]["request_id"]
        # 重连不丢失请求归属，读取进度不会被旧的精确 grant 阻断。
        control(local.socket_path, {"action": "connect", "project_id": pid})
        execute("script.get_proposal", "script-get", request_id=rid)
        command, saved = execute(
            "script.submit_proposal",
            "script-submit",
            request_id=rid,
            proposal=mixed_proposal(store.read().reference_library.characters[0].id),
        )
        status, replay, _ = request(server, "POST", resource, command, agent)
        assert status == 200 and replay["receipt"] == saved["receipt"]
        assert store.read().director_script is not None
        before = store.path.read_bytes()
        for name in (
            "final.approve",
            "project.apply_repair_patch",
            "final.select_candidate",
            "script.confirm",
        ):
            assert request(server, "POST", resource, {**command, "name": name}, agent)[0] == 403
        assert (
            request(
                server, "POST", resource, {**command, "idempotency_key": "stale-submit"}, agent
            )[0]
            == 409
        )
        other = create(server, human)
        assert request(server, "POST", resource.replace(pid, other), command, agent)[0] == 403
        assert store.path.read_bytes() == before
        # 撤权后连精确重放也拒绝。
        policy = local._load()
        caller = next(c for c in policy["callers"] if c["id"] == connection["caller_id"])
        caller["capabilities"] = ["project.read"]
        local._save(policy)
        assert request(server, "POST", resource, command, agent)[0] == 403


@pytest.mark.parametrize("agent", ["pi", "codex", "agy", "kimi", "dsh", "grok"])
@pytest.mark.parametrize("proxy_source", ["environment", "macos"])
@pytest.mark.parametrize("image_installed", [False, True])
def test_launcher_does_not_choose_models_export_tokens_or_send_a_prompt(
    tmp_path, monkeypatch, agent, proxy_source, image_installed
):
    from types import SimpleNamespace

    from integrations.agent_launcher import __main__ as launcher

    calls = []
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(key, raising=False)
    if proxy_source == "environment":
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    else:
        monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "pi"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    if agent == "codex":
        (tmp_path / "codex").mkdir()
        (tmp_path / "codex/auth.json").write_text('{"synthetic": "login-cache"}')
        (tmp_path / "codex/config.toml").write_text('[mcp_servers.unrelated]\ncommand="host-only"')

    def checked(args, **kwargs):
        calls.append((args, kwargs))
        assert args[0] not in ("pi", "codex")  # 不调用厂商鉴权/模型导出命令
        if image_installed and args[:3] == ["docker", "image", "inspect"]:
            return launcher.agent_build_digest(Path(__file__).resolve().parents[1]).encode()
        return b""

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args == ["scutil", "--proxy"]:
            assert proxy_source == "macos"
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "<dictionary> {\n  HTTPSEnable : 1\n"
                    "  HTTPSProxy : 127.0.0.1\n  HTTPSPort : 7897\n}"
                ),
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher, "checked", checked)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(
        launcher,
        "run_interactive",
        lambda args, **kwargs: calls.append((args, kwargs)) or 0,
    )
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(launcher, "browser", lambda *args: pytest.fail("打开 Agent 不打开浏览器"))
    monkeypatch.setattr(
        launcher,
        "control",
        lambda *args: {
            "project_id": "a" * 32,
            "caller_id": "agent-a",
            "token": "synthetic-agent-token",
            "revision": 1,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "launcher",
            "--socket",
            str(tmp_path / "control.sock"),
            "--project",
            "a" * 32,
            "--agent",
            agent,
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        launcher.main()
    assert stopped.value.code == 0
    assert all("KIMI_TOKEN" not in str(args) and "--model" not in args for args, _ in calls)
    assert all("type=bind" not in str(args) for args, _ in calls)
    assert any("--internal" in args for args, _ in calls)
    assert any(args[:3] == ["docker", "network", "rm"] for args, _ in calls)
    gateway_run = next((args, options) for args, options in calls if "/app/gateway.py" in args)
    assert "STORYRAIL_HOST_PROXY_PORT" in gateway_run[0]
    assert gateway_run[1]["env"]["STORYRAIL_HOST_PROXY_PORT"] == "7897"
    agent_run = next(args for args, _ in calls if "start" in args and agent in args)
    assert "STORYRAIL_HOST_PROXY_PORT" not in agent_run
    builds = [args for args, _ in calls if args[:2] == ["docker", "build"]]
    if image_installed:
        assert builds == []
    else:
        assert len(builds) == 1
        assert "--no-cache" not in builds[0]
        assert "--build-arg" not in builds[0]
        assert builds[0][builds[0].index("-t") + 1] == launcher.AGENT_IMAGE
    for args, _ in calls:
        if args[0] == "docker" and "python" in args:
            assert args[args.index("python") - 1] == launcher.AGENT_IMAGE
    if agent == "codex":
        payloads = [json.loads(options["input"]) for _, options in calls if "input" in options]
        assert payloads[-1] == {"auth.json": {"synthetic": "login-cache"}}
        assert all("host-only" not in str(call) for call in calls)
        assert any("target=/codex" in str(args) for args, _ in calls)
    elif agent == "agy":
        assert any("target=/agy" in str(args) for args, _ in calls)
        assert all("host-only" not in str(call) for call in calls)
    elif agent == "kimi":
        assert any("target=/kimi-code" in str(args) for args, _ in calls)
        assert all("host-only" not in str(call) for call in calls)
    elif agent == "dsh":
        assert any("target=/dsh" in str(args) for args, _ in calls)
        assert any("127.0.0.1:" in str(args) for args, _ in calls)
        assert all("host-only" not in str(call) for call in calls)
    elif agent == "grok":
        assert any("target=/grok" in str(args) for args, _ in calls)
        assert all("host-only" not in str(call) for call in calls)


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, None),
        ({"HTTPS_PROXY": "http://127.0.0.1:7897"}, "7897"),
        ({"https_proxy": "http://localhost:7897"}, "7897"),
        ({"HTTP_PROXY": "http://[::1]:7897"}, "7897"),
        ({"HTTPS_PROXY": "http://localhost"}, "80"),
        ({"HTTPS_PROXY": "http://localhost:7897", "HTTP_PROXY": "http://localhost:1234"}, "7897"),
    ],
)
def test_host_proxy_port_accepts_only_local_http_proxy(environment, expected):
    from integrations.agent_launcher.__main__ import host_proxy_port

    assert host_proxy_port(environment) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com:7897",
        "http://192.168.0.1:7897",
        "socks5://localhost:7897",
        "https://localhost:7897",
        "http://user:synthetic-secret@localhost:7897",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:7897/arbitrary-path",
        "http://localhost:7897?target=private",
    ],
)
def test_host_proxy_port_rejects_remote_credentials_and_invalid_ports(value):
    from integrations.agent_launcher.__main__ import host_proxy_port

    with pytest.raises(ValueError, match="本机 HTTP 代理") as error:
        host_proxy_port({"HTTPS_PROXY": value})
    assert value not in str(error.value)


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ("  HTTPSEnable : 1\n  HTTPSProxy : 127.0.0.1\n  HTTPSPort : 7897", "7897"),
        (
            "  HTTPSEnable : 0\n  HTTPEnable : 1\n  HTTPProxy : localhost\n  HTTPPort : 7898",
            "7898",
        ),
        ("  HTTPSEnable : 1\n  HTTPSProxy : ::1\n  HTTPSPort : 7897", "7897"),
        ("  HTTPSEnable : 0\n  HTTPSProxy : 127.0.0.1\n  HTTPSPort : 7897", None),
        ("  __SCOPED__ : <dictionary> {\n    HTTPEnable : 1\n    HTTPPort : 7897", None),
    ],
)
def test_system_proxy_fallback_uses_only_enabled_top_level_settings(
    monkeypatch, settings, expected
):
    from types import SimpleNamespace

    from integrations.agent_launcher import __main__ as launcher

    monkeypatch.setattr(launcher.sys, "platform", "darwin")

    def run(args, **kwargs):
        assert args == ["scutil", "--proxy"]
        assert kwargs == {"capture_output": True, "text": True, "check": True, "timeout": 5}
        return SimpleNamespace(stdout="<dictionary> {\n" + settings + "\n}")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.effective_host_proxy_port({}) == expected


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_proxy_environment_takes_precedence_without_system_lookup(monkeypatch, platform):
    from integrations.agent_launcher import __main__ as launcher

    monkeypatch.setattr(launcher.sys, "platform", platform)
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *_a, **_k: pytest.fail("不应读取系统代理")
    )
    assert launcher.effective_host_proxy_port({"HTTPS_PROXY": "http://localhost:7899"}) == "7899"
    with pytest.raises(ValueError, match="本机 HTTP 代理"):
        launcher.effective_host_proxy_port({"HTTPS_PROXY": "http://remote.test:7899"})
    if platform == "linux":
        assert launcher.effective_host_proxy_port({}) is None


def test_system_proxy_lookup_failure_does_not_silently_change_route(monkeypatch):
    from integrations.agent_launcher import __main__ as launcher

    monkeypatch.setattr(launcher.sys, "platform", "darwin")

    def run(*_args, **_kwargs):
        raise launcher.subprocess.TimeoutExpired("scutil", 5)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    with pytest.raises(ValueError, match="无法读取 macOS 系统代理"):
        launcher.effective_host_proxy_port({})


@pytest.mark.parametrize(
    "settings",
    [
        "  HTTPSEnable : 1\n  HTTPSProxy : remote.test\n  HTTPSPort : 7897",
        "  HTTPSEnable : 1\n  HTTPSProxy : 127.0.0.1",
        "  HTTPSEnable : 1\n  HTTPSProxy : 127.0.0.1\n  HTTPSPort : 0",
    ],
)
def test_invalid_system_proxy_is_rejected(monkeypatch, settings):
    from types import SimpleNamespace

    from integrations.agent_launcher import __main__ as launcher

    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout=settings)
    )
    with pytest.raises(ValueError, match="代理"):
        launcher.effective_host_proxy_port({})


def test_codex_command_has_native_mcp_without_task_or_secret():
    from integrations.agent_launcher.client import codex_command

    command = codex_command()
    assert command[:3] == ["codex", "--cd", "/workspace"]
    assert 'mcp_servers.storyrail.args=["/app/client.py","mcp"]' in command
    assert not any("token" in item or "--model" in item or item == "exec" for item in command)


def test_agy_command_adds_only_native_mcp_without_task_or_model(monkeypatch):
    from integrations.agent_launcher.client import agy_command

    calls = []
    monkeypatch.setenv("HOME", "/synthetic-home")
    monkeypatch.setattr(
        "integrations.agent_launcher.client.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    assert agy_command() == ["agy", "--dangerously-skip-permissions"]
    assert calls[0][0][0:4] == ["agy", "mcp", "add", "storyrail"]
    assert calls[0][0][-2:] == ["/app/client.py", "mcp"]
    assert not any("--model" in value or "token" in value for value in calls[0][0])


def test_kimi_command_writes_only_native_mcp_and_uses_auto_mode(monkeypatch, tmp_path):
    from integrations.agent_launcher.client import kimi_command

    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi-code"))
    assert kimi_command() == ["kimi", "--auto"]
    config = json.loads((tmp_path / "kimi-code/mcp.json").read_text())
    assert config == {
        "mcpServers": {"storyrail": {"command": sys.executable, "args": ["/app/client.py", "mcp"]}}
    }


def test_grok_command_replaces_only_storyrail_mcp_in_isolated_profile(monkeypatch, tmp_path):
    from integrations.agent_launcher.client import grok_command

    calls = []
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok"))
    monkeypatch.setattr(
        "integrations.agent_launcher.client.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    assert grok_command() == ["grok"]
    assert calls[0][0] == ["grok", "mcp", "remove", "storyrail"]
    assert calls[0][1]["check"] is False
    assert calls[1][0] == [
        "grok",
        "mcp",
        "add",
        "storyrail",
        "--",
        sys.executable,
        "/app/client.py",
        "mcp",
    ]
    assert calls[1][1]["check"] is True
    assert not any("token" in value or "--model" in value for value in calls[1][0])


def test_dsh_command_uses_fixed_patch_and_full_permission_mode(monkeypatch):
    from integrations.agent_launcher.client import dsh_command

    calls = []
    monkeypatch.setenv("STORYRAIL_DSH_HOST_PORT", "43210")
    monkeypatch.setenv("DSH_HOME", "/tmp/dsh-test")
    monkeypatch.setenv("NARB_DISABLE_NATIVE_CACHE", "0")
    monkeypatch.setattr(
        "integrations.agent_launcher.client.Path.read_text",
        lambda path, **kwargs: "patch" if str(path) == "/app/dsh-storyrail.cordis.yml" else "",
    )
    written = []
    monkeypatch.setattr(
        "integrations.agent_launcher.client.Path.write_text",
        lambda path, content, **kwargs: written.append((str(path), content)),
    )
    monkeypatch.setattr(
        "integrations.agent_launcher.client.Path.mkdir", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "integrations.agent_launcher.client.subprocess.Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    assert dsh_command() == [
        "node",
        "--expose-internals",
        "/usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js",
        "--profile",
        "web",
        "--port",
        "3080",
        "--trusted-host",
        "127.0.0.1:43210",
        "--no-open",
    ]
    assert calls[0][0][0] == "socat"
    assert written == [("/tmp/dsh-test/cordis.patch.yml", "patch")]
    assert os.environ["NARB_DISABLE_NATIVE_CACHE"] == "1"


def test_dsh_web_prints_host_port_url_and_saves_token(monkeypatch, capsys):
    from integrations.agent_launcher import client

    class Process:
        stdout = iter(["warning\n", "dsh web: http://127.0.0.1:3080/?token=abc_DEF-1\n"])

        def wait(self):
            return 0

    monkeypatch.setenv("STORYRAIL_DSH_HOST_PORT", "43210")
    monkeypatch.setattr(client, "dsh_command", lambda: ["dsh"])
    monkeypatch.setattr(client.subprocess, "Popen", lambda *args, **kwargs: Process())
    written = []
    monkeypatch.setattr(
        client.Path,
        "write_text",
        lambda path, content, **kwargs: written.append((str(path), content)),
    )
    assert client.run_dsh_web() == 0
    assert capsys.readouterr().out == (
        "warning\ndsh web: http://127.0.0.1:43210/?token=abc_DEF-1\n"
    )
    assert written == [("/tmp/dsh-browser-token", "abc_DEF-1")]


def test_local_session_204_sends_no_body_or_content_length():
    """回归：204 若带 body/Content-Length，严格代理（Vite/Node）会报解析错误。

    重构前 `server/http.py` 的 local-session 分支发的是 `204` + `Content-Length: 0` 且无 body；
    P5-A3 收进 api 管线后变成 `CookieResponse(204, {}, ...)`，一度给 204 也发了 `{}` 与长度。
    Python 的 http.client 对 204 不读 body，所以只有原始 socket 断言能锁住它。
    """
    with running() as (server, local, _workspaces):
        ticket = control(local.socket_path, {"action": "browser"})["login"]
        payload = json.dumps({"ticket": ticket}).encode()
        with socket.create_connection(server.server_address, timeout=5) as client:
            client.sendall(
                b"POST /api/local-session HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Origin: http://127.0.0.1:5173\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + payload
            )
            received = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                received += chunk
        head, separator, body = received.partition(b"\r\n\r\n")
        assert separator, received
        assert b" 204 " in head, head
        assert b"Set-Cookie: storyrail_human=" in head, head
        assert b"Content-Length" not in head, head
        assert body == b"", body


def test_response_write_tolerates_client_disconnect():
    """客户端提前断开时，写响应体不应把 BrokenPipeError 漏成 socketserver traceback。"""
    from email.message import Message

    from server.http import BinaryResponse, StoryRailRequestHandler

    written: list[bytes] = []

    class _AbortingWriter:
        def write(self, body):
            written.append(bytes(body))
            raise BrokenPipeError(32, "Broken pipe")

    handler = StoryRailRequestHandler.__new__(StoryRailRequestHandler)
    handler.wfile = _AbortingWriter()
    handler.headers = Message()
    handler.close_connection = False
    handler.send_response = lambda status: None
    handler.send_header = lambda *header: None
    handler.end_headers = lambda: None

    handler._send_binary(BinaryResponse(200, b"x" * 4096, "image/png"))

    assert written == [b"x" * 4096]
    assert handler.close_connection is True
