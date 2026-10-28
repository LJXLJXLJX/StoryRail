"""PG3-T3：`playground.use` 授权与 authorize 分支。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from core.application.caller import (
    PLAYGROUND_AGENT_OPERATIONS,
    AccessDenied,
    AccessPolicy,
    Caller,
)
from core.playground.commands import ALL_COMMANDS
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from core.project_workspaces import ProjectWorkspaceStore
from server.api import StoryRailApi
from server.http import StoryRailHttpServer

PROJECT_ID = "d" * 32
OTHER_PROJECT_ID = "e" * 32

HUMAN_TOKEN = "fixture_human_" + "b" * 32
AGENT_TOKEN = "fixture_playground_" + "a" * 32


def caller(role: str, capabilities: set[str], project_ids: tuple[str, ...] = ()) -> Caller:
    return Caller(f"{role}-1", role, frozenset(project_ids), frozenset(capabilities), 2**62)


HUMAN = caller("human", {"human.write"}, (PROJECT_ID,))
HUMAN_NO_WRITE = caller("human", set(), (PROJECT_ID,))
PLAYGROUND_AGENT = caller("agent", {"playground.use"})
PROJECT_AGENT = caller("agent", {"project.read", "project.mutate"}, (PROJECT_ID,))


def policy(**callers: tuple[str, set[str], tuple[str, ...], str]) -> AccessPolicy:
    records = []
    for caller_id, (role, capabilities, projects, token) in callers.items():
        records.append(
            {
                "id": caller_id,
                "grants": [],
                "role": role,
                "project_ids": list(projects),
                "capabilities": sorted(capabilities),
                "expires_at": 4102444800,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            }
        )
    return AccessPolicy.parse(
        json.dumps({"version": 2, "external_mutations": False, "callers": records}).encode()
    )


def command(name: str, arguments: dict | None = None) -> bytes:
    return json.dumps({"name": name, "idempotency_key": "k", "arguments": arguments or {}}).encode()


def test_human_with_human_write_can_use_all_playground_routes() -> None:
    policy_obj = policy()
    routes = [
        ("GET", "/api/playground", b""),
        ("POST", "/api/playground/commands", command("playground.list_capabilities")),
        ("POST", "/api/playground/runs/refresh", b""),
        ("POST", "/api/playground/assets/media", b"bytes"),
        ("GET", f"/api/playground/assets/{'a' * 32}/content", b""),
        ("GET", f"/api/playground/assets/{'a' * 32}/video-frame-info", b""),
        ("DELETE", "/api/playground/assets", b'{"asset_ids": []}'),
        (
            "POST",
            "/api/playground/assets/copy-from-project",
            json.dumps({"project_id": PROJECT_ID, "asset_id": "a" * 32}).encode(),
        ),
    ]
    for method, route, body in routes:
        policy_obj.authorize(HUMAN, method, route, body)


def test_human_without_human_write_denied() -> None:
    with pytest.raises(AccessDenied) as error:
        policy().authorize(HUMAN_NO_WRITE, "GET", "/api/playground", b"")
    assert error.value.code == "capability_denied"


def test_human_copy_from_project_requires_project_scope() -> None:
    body = json.dumps({"project_id": OTHER_PROJECT_ID, "asset_id": "a" * 32}).encode()
    with pytest.raises(AccessDenied) as error:
        policy().authorize(HUMAN, "POST", "/api/playground/assets/copy-from-project", body)
    assert error.value.code == "scope_denied"


@pytest.mark.parametrize("name", sorted(ALL_COMMANDS))
def test_playground_agent_can_run_all_commands(name: str) -> None:
    policy().authorize(PLAYGROUND_AGENT, "POST", "/api/playground/commands", command(name))


def test_playground_agent_denied_other_routes() -> None:
    for method, route, body in (
        ("GET", "/api/playground", b""),
        ("GET", f"/api/playground/assets/{'a' * 32}/content", b""),
        ("POST", "/api/playground/assets/media", b"bytes"),
        ("DELETE", "/api/playground/assets", b'{"asset_ids": []}'),
        ("POST", "/api/playground/runs/refresh", b""),
        (
            "POST",
            "/api/playground/assets/copy-from-project",
            json.dumps({"project_id": PROJECT_ID, "asset_id": "a" * 32}).encode(),
        ),
    ):
        with pytest.raises(AccessDenied) as error:
            policy().authorize(PLAYGROUND_AGENT, method, route, body)
        assert error.value.code == "capability_denied", (method, route)


def test_playground_agent_denied_unknown_command_name() -> None:
    with pytest.raises(AccessDenied) as error:
        policy().authorize(
            PLAYGROUND_AGENT,
            "POST",
            "/api/playground/commands",
            command("playground.drop_everything"),
        )
    assert error.value.code == "capability_denied"


def test_playground_agent_denied_project_routes() -> None:
    with pytest.raises(AccessDenied) as error:
        policy().authorize(
            PLAYGROUND_AGENT,
            "POST",
            f"/api/projects/{PROJECT_ID}/structured-director/application/commands",
            command("project.get_projection"),
        )
    assert error.value.code == "scope_denied"


def test_project_agent_denied_playground() -> None:
    with pytest.raises(AccessDenied) as error:
        policy().authorize(
            PROJECT_AGENT,
            "POST",
            "/api/playground/commands",
            command("playground.list_capabilities"),
        )
    assert error.value.code == "scope_denied"


def test_policy_parse_accepts_playground_use_for_agent() -> None:
    parsed = policy(
        **{
            "playground-agent": (
                "agent",
                {"playground.use"},
                (),
                AGENT_TOKEN,
            )
        }
    )
    authenticated = parsed.authenticate("Bearer " + AGENT_TOKEN)
    assert authenticated.capabilities == frozenset({"playground.use"})
    assert authenticated.project_ids == frozenset()

    with pytest.raises(ValueError, match="人类 capability"):
        policy(
            **{
                "bad": ("agent", {"human.write"}, (), AGENT_TOKEN),
            }
        )


def test_playground_operation_constants_match() -> None:
    assert PLAYGROUND_AGENT_OPERATIONS == ALL_COMMANDS
    assert len(PLAYGROUND_AGENT_OPERATIONS) == 11


def test_playground_agent_token_end_to_end(tmp_path: Path) -> None:
    stories_root = tmp_path / ".stories"
    stories_root.mkdir()
    from tests.conftest import provider_registry

    playground = PlaygroundService(
        PlaygroundStore(stories_root / ".playground"), provider_registry()
    )
    workspaces = ProjectWorkspaceStore(stories_root)
    api = StoryRailApi(
        workspaces,
        lambda project_id: None,  # type: ignore[arg-type,return-value]
        playground_service=playground,
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(
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
                        "token_sha256": hashlib.sha256(AGENT_TOKEN.encode()).hexdigest(),
                    }
                ],
            }
        ).encode()
    )
    policy_path.chmod(0o600)

    loop = asyncio.new_event_loop()
    worker = threading.Thread(target=loop.run_forever, daemon=True)
    worker.start()
    server = StoryRailHttpServer(("127.0.0.1", 0), api, loop, access_policy_file=policy_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    try:
        connection = HTTPConnection(host, port, timeout=10)
        payload = command("playground.list_capabilities")
        connection.request(
            "POST",
            "/api/playground/commands",
            body=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + AGENT_TOKEN,
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode())
        assert response.status == 200, body
        assert len(body["data"]["capabilities"]) == 5
        assert body["receipt"]["status"] == "noop"

        connection.request(
            "GET",
            "/api/playground",
            headers={"Authorization": "Bearer " + AGENT_TOKEN},
        )
        denied = connection.getresponse()
        assert denied.status == 403
        assert json.loads(denied.read().decode())["error"]["code"] == "capability_denied"
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        worker.join(timeout=5)
        loop.close()
