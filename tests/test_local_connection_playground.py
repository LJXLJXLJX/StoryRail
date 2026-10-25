"""PG5-T1：本机连接的 Playground 凭据动作。"""

from __future__ import annotations

import asyncio
import json
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.application.caller import AccessDenied, AccessPolicy
from integrations.agent_launcher.__main__ import control
from server.local_connection import LocalConnection

PROJECT_ID = "a" * 32


class _Response:
    status = 200

    def __init__(self, revision: int = 7) -> None:
        self.body = {"revision": revision}


class _Api:
    """最小 Core 替身：connect 只读取项目快照 revision。"""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def handle(self, method: str, path: str) -> _Response:
        self.paths.append(path)
        return _Response()


@contextmanager
def local_connection(*, api=None, project_ids=()):
    # Unix socket 路径有长度上限，使用与 test_agent_onboarding 相同的短临时目录。
    with tempfile.TemporaryDirectory(prefix="sr-connect-") as temporary:
        directory = Path(temporary).resolve() / "access"
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        local = LocalConnection(directory, api, loop, lambda: list(project_ids))
        try:
            yield local
        finally:
            local.close()
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()


def test_connect_playground_creates_agent_caller_with_only_playground_use():
    with local_connection() as local:
        connection = control(local.socket_path, {"action": "connect_playground"})

        assert set(connection) == {"scope", "caller_id", "token"}
        assert connection["scope"] == "playground"
        assert connection["token"]

        policy = local._load()  # noqa: SLF001
        assert len(policy["callers"]) == 1
        caller = policy["callers"][0]
        assert caller["id"] == connection["caller_id"]
        assert caller["role"] == "agent"
        assert caller["project_ids"] == []
        assert caller["capabilities"] == ["playground.use"]
        assert caller["grants"] == []

        path = local.directory / "playground.json"
        assert json.loads(path.read_text()) == connection
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert not (local.directory / (PROJECT_ID + ".json")).exists()


def test_connect_playground_reuses_token_and_renews():
    with local_connection() as local:
        first = control(local.socket_path, {"action": "connect_playground"})

        policy = local._load()  # noqa: SLF001
        caller = next(c for c in policy["callers"] if c["id"] == first["caller_id"])
        # 模拟旧凭据被改宽、过期后的重连：必须回到只有 playground.use 的 30 天凭据。
        caller["project_ids"] = [PROJECT_ID]
        caller["capabilities"] = ["project.read"]
        caller["expires_at"] = 1
        local._save(policy)

        second = control(local.socket_path, {"action": "connect_playground"})

        assert second["token"] == first["token"]
        assert second["caller_id"] == first["caller_id"]
        assert second["scope"] == "playground"
        renewed = local._load()["callers"][0]  # noqa: SLF001
        assert renewed["project_ids"] == []
        assert renewed["capabilities"] == ["playground.use"]
        assert renewed["grants"] == []
        assert renewed["expires_at"] > int(time.time()) + 29 * 24 * 3600


def test_connect_playground_token_cannot_access_projects():
    with local_connection() as local:
        connection = control(local.socket_path, {"action": "connect_playground"})

        policy = AccessPolicy.parse(local.policy_path.read_bytes())
        caller = policy.authenticate("Bearer " + connection["token"])
        assert caller.capabilities == frozenset({"playground.use"})
        with pytest.raises(AccessDenied) as error:
            policy.authorize(
                caller,
                "POST",
                f"/api/projects/{PROJECT_ID}/structured-director/application/commands",
                b"{}",
            )
        assert error.value.code == "scope_denied"


def test_existing_project_connect_unchanged():
    api = _Api()
    with local_connection(api=api) as local:
        connection = control(local.socket_path, {"action": "connect", "project_id": PROJECT_ID})

        assert set(connection) == {"project_id", "caller_id", "token", "revision"}
        assert connection["project_id"] == PROJECT_ID
        assert connection["revision"] == 7
        assert api.paths == [f"/api/projects/{PROJECT_ID}/structured-director"]

        policy = local._load()  # noqa: SLF001
        caller = policy["callers"][0]
        assert caller["role"] == "agent"
        assert caller["project_ids"] == [PROJECT_ID]
        assert set(caller["capabilities"]) == {
            "project.read",
            "project.mutate",
            "project.propose",
            "project.execute",
        }

        assert (
            control(local.socket_path, {"action": "connect", "project_id": PROJECT_ID})
            == connection
        )
        assert (local.directory / (PROJECT_ID + ".json")).is_file()
        assert not (local.directory / "playground.json").exists()
