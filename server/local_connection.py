"""受信本机启动通道；Unix socket 不对外部 Agent 或 HTTP 开放。"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import secrets
import socketserver
import threading
import time
from pathlib import Path

from core.application.caller import AccessPolicy, strict_json

from .access import reject_symlink_ancestors


class LocalConnection:
    def __init__(self, directory: Path, api, loop, project_ids):
        self.directory = reject_symlink_ancestors(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.stat().st_uid != os.geteuid() or self.directory.stat().st_mode & 0o077:
            raise ValueError("本机连接目录必须由当前用户独占。")
        self._lease = os.open(
            self.directory / "connection.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lease)
            raise ValueError("本机连接目录已被其它服务使用。") from None
        self.api, self.loop, self.project_ids = api, loop, project_ids
        self.policy_path = self.directory / "policy.json"
        self.lock = threading.RLock()
        self.logins = {}
        if not self.policy_path.exists():
            self._save({"version": 2, "external_mutations": True, "callers": []})
        else:
            self._load()
        self.socket_path = self.directory / "control.sock"
        if self.socket_path.exists():
            # SingleWriterLease 已经持有；只回收自己的陈旧 socket。
            import stat

            if not stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                raise ValueError("本机控制入口被其它文件占用。")
            self.socket_path.unlink()
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(10)
                try:
                    body = self.rfile.readline(4097)
                    if len(body) > 4096:
                        raise ValueError("请求过大。")
                    result = owner.dispatch(strict_json(body))
                except (OSError, ValueError, KeyError, TimeoutError):
                    result = {"error": "连接准备失败，请重新打开 StoryRail 后重试。"}
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode() + b"\n")

        self.server = socketserver.ThreadingUnixStreamServer(str(self.socket_path), Handler)
        os.chmod(self.socket_path, 0o600)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _load(self):
        from .access import load_access_policy

        load_access_policy(self.policy_path)
        return strict_json(self.policy_path.read_bytes())

    def _save(self, policy):
        data = json.dumps(policy, ensure_ascii=False).encode()
        AccessPolicy.parse(data)
        path = self.directory / (secrets.token_hex(16) + ".tmp")
        with path.open("xb") as target:
            os.chmod(path, 0o600)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(path, self.policy_path)

    def _caller(self, role, projects, capabilities, grants=()):
        token = secrets.token_urlsafe(32)
        return token, {
            "id": role + "-" + secrets.token_hex(12),
            "role": role,
            "project_ids": projects,
            "capabilities": capabilities,
            "expires_at": int(time.time()) + 43200,
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "grants": list(grants),
        }

    def dispatch(self, request):
        with self.lock:
            if request == {"action": "browser"}:
                token, caller = self._caller(
                    "human",
                    list(self.project_ids()),
                    ["project.read", "human.write", "workspace.manage"],
                )
                policy = self._load()
                policy["callers"] = [
                    c
                    for c in policy["callers"]
                    if c["role"] == "agent" or c["expires_at"] > time.time()
                ]
                policy["callers"].append(caller)
                self._save(policy)
                ticket = secrets.token_urlsafe(32)
                self.logins[ticket] = (time.time() + 120, token)
                return {"login": ticket}
            if request == {"action": "connect_playground"}:
                policy = self._load()
                connection_path = self.directory / "playground.json"
                connection = (
                    strict_json(connection_path.read_bytes()) if connection_path.exists() else None
                )
                caller = next(
                    (
                        c
                        for c in policy["callers"]
                        if connection and c["id"] == connection["caller_id"]
                    ),
                    None,
                )
                if caller is None:
                    token, caller = self._caller("agent", [], ["playground.use"])
                    policy["callers"].append(caller)
                else:
                    token = connection["token"]
                # Playground 是懒创建的全局工作区；凭据只有 playground.use，不含任何项目。
                caller["project_ids"] = []
                caller["capabilities"] = ["playground.use"]
                caller["grants"] = []
                caller["expires_at"] = int(time.time()) + 43200
                self._save(policy)
                connection = {
                    "scope": "playground",
                    "caller_id": caller["id"],
                    "token": token,
                }
                temporary = self.directory / (secrets.token_hex(16) + ".tmp")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as target:
                    json.dump(connection, target)
                os.replace(temporary, connection_path)
                return connection
            if set(request) != {"action", "project_id"} or request["action"] != "connect":
                raise ValueError("不支持的连接动作。")
            project_id = request["project_id"]
            if not isinstance(project_id, str) or not re.fullmatch(r"[0-9a-f]{32}", project_id):
                raise ValueError("项目 ID 不合法。")
            future = asyncio.run_coroutine_threadsafe(
                self.api.handle("GET", f"/api/projects/{project_id}/structured-director"), self.loop
            )
            response = future.result(timeout=10)
            if response.status != 200:
                raise ValueError("项目不存在。")
            policy = self._load()
            connection_path = self.directory / (project_id + ".json")
            connection = (
                strict_json(connection_path.read_bytes()) if connection_path.exists() else None
            )
            caller = next(
                (c for c in policy["callers"] if connection and c["id"] == connection["caller_id"]),
                None,
            )
            if caller is None:
                token, caller = self._caller("agent", [project_id], ["project.read"])
                policy["callers"].append(caller)
            else:
                token = connection["token"]
            # 用户从当前项目启动的外部 Agent 获得有限执行委托；启动本身不创建任务。
            caller["capabilities"] = [
                "project.read",
                "project.mutate",
                "project.propose",
                "project.execute",
            ]
            caller["grants"] = []
            caller["expires_at"] = int(time.time()) + 43200
            self._save(policy)
            connection = {
                "project_id": project_id,
                "caller_id": caller["id"],
                "token": token,
                "revision": response.body["revision"],
            }
            temporary = self.directory / (secrets.token_hex(16) + ".tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as target:
                json.dump(connection, target)
            os.replace(temporary, connection_path)
            return connection

    def redeem_login(self, ticket):
        with self.lock:
            item = self.logins.pop(ticket, None) if isinstance(ticket, str) else None
            return item[1] if item and item[0] > time.time() else None

    def refresh_human_projects(self):
        with self.lock:
            policy = self._load()
            for caller in policy["callers"]:
                if caller["role"] == "human":
                    caller["project_ids"] = list(self.project_ids())
            self._save(policy)

    def close(self):
        if self._lease is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.socket_path.unlink(missing_ok=True)
        os.close(self._lease)
        self._lease = None
