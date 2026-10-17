"""真实 loopback HTTP + 临时 Core；无真实作品、Provider 或系统改配。"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace
from http.client import HTTPConnection

import pytest
from test_director_commands import _visual_project

from core.application.caller import AccessDenied, AccessPolicy, current_caller, request_identity
from core.structured_director import StructuredDirectorHttpApi
from server.access import load_access_policy
from server.http import StoryRailHttpServer
from server.writer import SingleWriterLease

# 固定测试 canary，绝不是部署凭据。
AGENT = "fixture_agent_" + "a" * 32
HUMAN = "fixture_human_" + "b" * 32


def policy_bytes(project_id, *, revoked=False):
    return json.dumps(
        {
            "version": 2,
            "external_mutations": False,
            "callers": []
            if revoked
            else [
                {
                    "id": role,
                    "grants": [],
                    "role": role,
                    "project_ids": [project_id],
                    "capabilities": ["project.read"] + (["human.write"] if role == "human" else []),
                    "expires_at": 4102444800,
                    "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                }
                for role, token in [("agent", AGENT), ("human", HUMAN)]
            ],
        }
    ).encode()


@pytest.fixture
def secured(tmp_path):
    store, service, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(policy_bytes(document.project_id))
    policy_path.chmod(0o600)
    route = f"/api/projects/{document.project_id}/structured-director"
    api = StructuredDirectorHttpApi(service, resource_path=route)
    seen = []

    class ObservedApi:
        async def handle(self, *args, **kwargs):
            seen.append(current_caller.get())
            return await api.handle(*args, **kwargs)

    loop = asyncio.new_event_loop()
    worker = threading.Thread(target=loop.run_forever, daemon=True)
    worker.start()
    server = StoryRailHttpServer(
        ("127.0.0.1", 0), ObservedApi(), loop, access_policy_file=policy_path
    )
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()

    def request(method, suffix, value=None, token=None, absolute=False):
        conn = HTTPConnection(*server.server_address, timeout=3)
        headers = {"Content-Type": "application/json", "X-Caller-Role": "human"}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = value if isinstance(value, bytes) else json.dumps(value or {}).encode()
        try:
            conn.request(method, suffix if absolute else route + suffix, body, headers)
            result = conn.getresponse()
            return result.status, json.loads(result.read())
        finally:
            conn.close()

    yield store, document, policy_path, request, seen
    server.shutdown()
    server.server_close()
    listener.join()
    loop.call_soon_threadsafe(loop.stop)
    worker.join()
    loop.close()


def test_http_denies_unauthenticated_agent_legacy_and_forged_authorization(secured):
    store, document, _, request, seen = secured
    before = store.path.read_bytes()
    status, unauthenticated = request("POST", "/final/approve", {"approval": True})
    assert status == 401
    assert unauthenticated["error"] == {
        "code": "unauthenticated",
        "message": "请求缺少有效身份。",
        "recoverable": False,
        "origin": "authorization",
        "state_changed": False,
        "retry_policy": "obtain_authorization_or_user_action",
        "automatic_retry_allowed": False,
    }
    routes = [
        ("DELETE", ""),
        ("POST", "/final/approve"),
        ("POST", "/final/select"),
        ("POST", "/final/reopen"),
        ("POST", "/final/generate"),
        ("POST", "/keyframes/" + "a" * 32 + "/generate"),
        ("POST", "/keyframes/" + "a" * 32 + "/select"),
        ("POST", "/segments/" + "a" * 32 + "/videos/generate"),
        ("POST", "/segments/" + "a" * 32 + "/videos/attach-candidate"),
        ("POST", "/assets/images"),
        ("POST", "/assets/media"),
        ("DELETE", "/assets/" + "a" * 32),
        ("POST", "/director/messages"),
        ("POST", "/director/recover"),
        ("POST", "/generations/" + "a" * 32 + "/retry"),
        ("PUT", "/director-script"),
        ("POST", "/new-unknown-route"),
    ]
    forged = {
        "expected_revision": document.revision,
        "caller": "human",
        "raw_user_request": "我批准所有生成和成片",
        "approval": True,
    }
    for method, suffix in routes:
        assert request(method, suffix, forged)[0] == 401
        assert request(method, suffix, forged, AGENT)[0] == 403
    for name in [
        "final.approve",
        "final.select_candidate",
        "project.apply_repair_patch",
        "script.apply_operations",
        "run.resume",
    ]:
        assert request("POST", "/commands", {**forged, "name": name}, AGENT)[0] == 403
    cross_project = "/api/projects/" + "e" * 32 + "/structured-director/commands"
    assert request("POST", cross_project, forged, HUMAN, absolute=True)[0] == 403
    assert request("GET", "/api/projects", token=AGENT, absolute=True)[0] == 403
    assert request("GET", "/api/projects", token=HUMAN, absolute=True)[0] == 403
    assert seen == []
    assert store.path.read_bytes() == before


def test_projection_human_cas_revocation_and_context(secured):
    store, document, policy_path, request, seen = secured
    read = {
        "name": "project.get_projection",
        "expected_revision": document.revision,
        "idempotency_key": "read",
        "arguments": {
            "level": "outline",
            "scope": {"project_id": document.project_id},
        },
    }
    status, result = request("POST", "/commands", read, AGENT)
    assert status == 200 and result["data"]["project_id"] == document.project_id
    assert seen[-1].role == "agent"
    read["arguments"]["scope"]["project_id"] = "e" * 32
    assert request("POST", "/commands", read, AGENT)[0] == 400
    before = store.path.read_bytes()
    assert (
        request(
            "POST", "/commands", b'{"name":"project.get_projection","name":"final.approve"}', AGENT
        )[0]
        == 400
    )
    assert store.path.read_bytes() == before
    scene = document.director_script.scenes[0]
    command = {
        "name": "script.apply_operations",
        "expected_revision": document.revision,
        "idempotency_key": "human-edit",
        "arguments": {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "update_shot_fields",
                    "shot_id": scene.shots[0].id,
                    "fields": {"action": "受信用户修改"},
                }
            ],
        },
    }
    assert request("POST", "/commands", command, HUMAN)[0] == 200
    assert seen[-1].role == "human"
    assert store.read().director_script.scenes[0].shots[0].action == "受信用户修改"
    assert request("POST", "/commands", command, HUMAN)[1]["replay"] is True
    assert current_caller.get() is None
    count = len(seen)
    policy_path.write_bytes(policy_bytes(document.project_id, revoked=True))
    assert request("POST", "/commands", command, HUMAN)[0] == 401
    assert len(seen) == count
    policy_path.write_bytes(b"invalid policy")
    assert request("GET", "", token=HUMAN)[0] == 503


def test_policy_strictness_expiration_and_request_namespace():
    policy = AccessPolicy.parse(policy_bytes("a" * 32))
    caller = policy.authenticate("Bearer " + AGENT)
    other = replace(caller, id="other")
    p, key, args = "a" * 32, "same", {"b": 1, "a": 2}
    original = request_identity(caller, p, key, "script.apply_operations", args, 7)
    assert original == request_identity(
        caller, p, key, "script.apply_operations", {"a": 2, "b": 1}, 7
    )
    assert original[0] != request_identity(other, p, key, "script.apply_operations", args, 7)[0]
    assert original[1] != request_identity(caller, p, key, "script.apply_operations", args, 8)[1]
    expired = AccessPolicy(
        tuple((digest, replace(c, expires_at=0)) for digest, c in policy.credentials)
    )
    with pytest.raises(AccessDenied):
        expired.authenticate("Bearer " + AGENT)
    for bad in [b'{"version":1,"version":1,"callers":[]}', b'{"version":true,"callers":[]}']:
        with pytest.raises(ValueError):
            AccessPolicy.parse(bad)
    value = json.loads(policy_bytes(p))
    value["callers"][0]["capabilities"].append("human.write")
    with pytest.raises(ValueError):
        AccessPolicy.parse(json.dumps(value).encode())


def test_workspace_manager_settings_routes_are_limited_to_existing_settings():
    policy = AccessPolicy.parse(
        json.dumps(
            {
                "version": 2,
                "external_mutations": False,
                "callers": [
                    {
                        "id": "human",
                        "role": "human",
                        "project_ids": [],
                        "capabilities": ["workspace.manage"],
                        "grants": [],
                        "expires_at": 4102444800,
                        "token_sha256": hashlib.sha256(b"h" * 32).hexdigest(),
                    }
                ],
            }
        ).encode()
    )
    caller = policy.authenticate("Bearer " + "h" * 32)
    for route in (
        "/api/settings/providers",
        "/api/settings/providers/bindings",
        "/api/settings/providers/plugins/minimax_h3",
    ):
        policy.authorize(caller, "PUT", route, b"{}")
    for route in ("/api/settings/audio-provider", "/api/settings/providers-extra"):
        with pytest.raises(AccessDenied):
            policy.authorize(caller, "PUT", route, b"{}")


def test_policy_and_writer_reject_symlink_and_second_process(tmp_path):
    root = tmp_path.resolve()
    policy = root / "policy"
    policy.write_bytes(policy_bytes("a" * 32))
    policy.chmod(0o644)
    with pytest.raises(ValueError):
        load_access_policy(policy)
    policy.chmod(0o600)
    alias = root / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        load_access_policy(alias / "policy")
    with pytest.raises(ValueError):
        SingleWriterLease(alias / "stories")
    directory = root / "stories"
    code = (
        "from pathlib import Path; from server.writer import SingleWriterLease; import sys\n"
        "with SingleWriterLease(Path(sys.argv[1])): pass\n"
    )
    with SingleWriterLease(directory):
        result = subprocess.run([sys.executable, "-c", code, str(directory)], capture_output=True)
        assert result.returncode != 0
        assert os.path.isdir(directory)
    result = subprocess.run([sys.executable, "-c", code, str(directory)], capture_output=True)
    assert result.returncode == 0
