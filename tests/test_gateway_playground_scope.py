"""PG5-T2：gateway 放行规则按 scope 分支，项目规则保持不变。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from integrations.agent_launcher import gateway

PROJECT_ID = "a" * 32
ASSET_ID = "b" * 32


class _Upstream:
    def __init__(self, body: bytes = b'{"ok":true}') -> None:
        self.status = 200
        self._body = body

    def getheader(self, name, default=None):
        return "application/json"

    def read1(self, size):
        body, self._body = self._body, b""
        return body


class _Connection:
    requests: list[tuple[str, str]] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def request(self, command, path, body=None, headers=None):
        _Connection.requests.append((command, path))

    def getresponse(self):
        return _Upstream()

    def close(self):
        pass


@contextmanager
def gateway_server(monkeypatch, environment):
    for key, value in environment.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    _Connection.requests = []
    monkeypatch.setattr(gateway.http.client, "HTTPConnection", _Connection)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def send(server, method, path, body=None):
    client = HTTPConnection(*server.server_address, timeout=5)
    try:
        client.request(method, path, body=body)
        response = client.getresponse()
        response.read()
        return response.status
    finally:
        client.close()


def test_playground_scope_only_allows_command_endpoint(monkeypatch):
    with gateway_server(
        monkeypatch,
        {"STORYRAIL_SCOPE": "playground", "PROJECT_ID": None, "CORE_PORT": "8765"},
    ) as server:
        for method, path in (
            ("GET", "/api/playground"),
            ("POST", "/api/playground/runs/refresh"),
            ("POST", "/api/playground/assets/media"),
            ("GET", f"/api/playground/assets/{ASSET_ID}/content"),
            ("GET", f"/api/playground/assets/{ASSET_ID}/video-frame-info"),
            ("POST", f"/api/projects/{PROJECT_ID}/structured-director/application/commands"),
            ("GET", f"/api/projects/{PROJECT_ID}/structured-director/assets/{ASSET_ID}/content"),
        ):
            assert send(server, method, path) == 403, (method, path)

        assert (
            send(
                server,
                "POST",
                "/api/playground/commands",
                body=b'{"name":"playground.list_capabilities"}',
            )
            == 200
        )
        assert _Connection.requests == [("POST", "/api/playground/commands")]


def test_project_scope_rules_unchanged_without_scope(monkeypatch):
    with gateway_server(
        monkeypatch,
        {"STORYRAIL_SCOPE": None, "PROJECT_ID": PROJECT_ID, "CORE_PORT": "8765"},
    ) as server:
        prefix = f"/api/projects/{PROJECT_ID}/structured-director"
        assert send(server, "POST", f"{prefix}/application/commands", body=b"{}") == 200
        assert send(server, "GET", f"{prefix}/assets/{ASSET_ID}/content") == 200
        assert _Connection.requests == [
            ("POST", f"{prefix}/application/commands"),
            ("GET", f"{prefix}/assets/{ASSET_ID}/content"),
        ]

        assert send(server, "POST", "/api/playground/commands", body=b"{}") == 403
        assert send(server, "GET", "/api/playground") == 403
        assert (
            send(
                server,
                "POST",
                f"/api/projects/{'c' * 32}/structured-director/application/commands",
                body=b"{}",
            )
            == 403
        )
