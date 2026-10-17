"""模型 TLS 出口不缓存凭据；私网/任意端口始终拒绝。"""

import base64
import json
import socket
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from integrations.agent_launcher import gateway


@pytest.mark.parametrize("resolved", [["104.16.1.34"], ["127.0.0.1"], ["104.16.1.34", "10.0.0.1"]])
def test_fake_dns_uses_verified_public_resolution_without_allowing_private_ips(
    monkeypatch, resolved
):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.2.73", 443))],
    )
    calls = []

    class Resolver:
        def __init__(self, host, timeout):
            assert host == "1.1.1.1" and timeout == 10

        def request(self, method, path, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            return SimpleNamespace(
                status=200,
                read=lambda size: json.dumps(
                    {"Status": 0, "Answer": [{"type": 1, "data": ip} for ip in resolved]}
                ).encode(),
            )

        def close(self):
            pass

    monkeypatch.setattr(gateway.http.client, "HTTPSConnection", Resolver)
    if len(resolved) == 1 and resolved[0] == "104.16.1.34":
        assert gateway.public_addresses("registry.npmjs.org")[0][4] == (resolved[0], 443)
    else:
        with pytest.raises(ValueError, match="公网"):
            gateway.public_addresses("registry.npmjs.org")
    assert calls == [
        ("GET", "/dns-query?name=registry.npmjs.org&type=A", {"Accept": "application/dns-json"})
    ]


def test_connect_blocks_private_targets_and_does_not_cache_authentication(monkeypatch):
    monkeypatch.setenv("GATEWAY_TOKEN", "synthetic-proxy")
    token = "Basic " + base64.b64encode(b"pi:synthetic-proxy").decode()
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for target in ("127.0.0.1:443", "localhost:443", "example.com:80"):
            client = HTTPConnection(*server.server_address, timeout=3)
            client.request("CONNECT", target, headers={"Proxy-Authorization": token})
            response = client.getresponse()
            assert response.status == 403
            response.read()
            client.close()
        with socket.socket() as echo:
            echo.bind(("127.0.0.1", 0))
            echo.listen()

            def echo_bytes():
                with echo.accept()[0] as stream:
                    while content := stream.recv(4096):
                        stream.sendall(content)

            peer = threading.Thread(target=echo_bytes, daemon=True)
            peer.start()
            target = echo.getsockname()
            original_socket = socket.socket

            class RoutedSocket(original_socket):
                def connect(self, address):
                    assert address == ("93.184.216.34", 443)
                    return super().connect(target)

            monkeypatch.setattr(
                gateway,
                "socket",
                SimpleNamespace(
                    SOCK_STREAM=socket.SOCK_STREAM,
                    socket=RoutedSocket,
                    getaddrinfo=lambda *args, **kwargs: [
                        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
                    ],
                ),
            )
            with socket.create_connection(server.server_address, timeout=3) as client:
                client.sendall(
                    (
                        "CONNECT provider.test:443 HTTP/1.1\r\nProxy-Authorization: "
                        + token
                        + "\r\n\r\n"
                    ).encode()
                )
                response = b""
                while not response.endswith(b"\r\n\r\n"):
                    response += client.recv(1)
                assert b"200" in response
                for payload in (
                    b"opaque-TLS-with-old-credential",
                    b"opaque-TLS-with-native-refreshed-credential",
                ):
                    client.sendall(payload)
                    assert client.recv(4096) == payload
            peer.join(timeout=3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_fixed_google_targets_keep_domain_for_host_proxy_without_forwarding_auth(monkeypatch):
    monkeypatch.setenv("STORYRAIL_HOST_PROXY_PORT", "7897")
    calls = []
    stream = object()

    class Proxy:
        sock = stream

        def __init__(self, host, port, timeout):
            calls.append(("proxy", host, port, timeout))

        def close(self):
            calls.append(("close",))

        def set_tunnel(self, host, port, headers=None):
            calls.append(("CONNECT", host, port, headers))

        def connect(self):
            calls.append(("connect",))

    monkeypatch.setattr(gateway.http.client, "HTTPConnection", Proxy)
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with gateway.model_upstream("cloudcode-pa.googleapis.com", addresses) as upstream:
        assert upstream is stream
    assert calls == [
        ("proxy", "host.docker.internal", 7897, 30),
        ("CONNECT", "cloudcode-pa.googleapis.com", 443, None),
        ("connect",),
        ("close",),
    ]


def test_real_http_connect_chain_relays_opaque_bytes_and_keeps_gateway_auth_local(monkeypatch):
    monkeypatch.setenv("GATEWAY_TOKEN", "synthetic-proxy")
    monkeypatch.setenv("STORYRAIL_HOST_PROXY_PORT", "7897")
    requests = []

    class ProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_CONNECT(self):  # noqa: N802
            requests.append((self.path, self.headers.get("Proxy-Authorization")))
            self.send_response(200)
            self.end_headers()
            while content := self.connection.recv(4096):
                self.connection.sendall(content)

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()

    def connection(host, port, timeout):
        assert (host, port, timeout) == ("host.docker.internal", 7897, 30)
        return HTTPConnection(*proxy.server_address, timeout=3)

    monkeypatch.setattr(gateway.http.client, "HTTPConnection", connection)
    monkeypatch.setattr(
        gateway,
        "public_addresses",
        lambda host: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=3) as client:
            client.sendall(
                b"CONNECT cloudcode-pa.googleapis.com:443 HTTP/1.1\r\n"
                b"Proxy-Authorization: Basic cGk6c3ludGhldGljLXByb3h5\r\n\r\n"
            )
            headers = b""
            while not headers.endswith(b"\r\n\r\n"):
                headers += client.recv(1)
            assert b"200" in headers
            for payload in (
                b"opaque-TLS-old-native-credential",
                b"opaque-TLS-refreshed-credential",
            ):
                client.sendall(payload)
                assert client.recv(4096) == payload
        assert requests == [("cloudcode-pa.googleapis.com:443", None)]
    finally:
        server.shutdown()
        server.server_close()
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=3)
        proxy_thread.join(timeout=3)


@pytest.mark.parametrize(
    "host",
    ["provider.test", "cloudcode-pa.googleapis.com.attacker.test", "93.184.216.34"],
)
def test_other_targets_remain_pinned_to_verified_ip_with_host_proxy(monkeypatch, host):
    monkeypatch.setenv("STORYRAIL_HOST_PROXY_PORT", "7897")
    calls = []

    class Stream:
        def __init__(self, family, kind):
            assert family == socket.AF_INET and kind == socket.SOCK_STREAM

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def settimeout(self, timeout):
            assert timeout == 30

        def connect(self, address):
            calls.append(address)

    monkeypatch.setattr(
        gateway.http.client, "HTTPConnection", lambda *_a, **_k: pytest.fail("代理越界")
    )
    monkeypatch.setattr(gateway.socket, "socket", Stream)
    monkeypatch.setattr(gateway.socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("DNS 重绑定"))
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with gateway.model_upstream(host, addresses):
        pass
    assert calls == [("93.184.216.34", 443)]


@pytest.mark.parametrize("private_resolution", [False, True])
def test_host_proxy_failures_and_private_google_resolution_are_closed(
    monkeypatch, private_resolution
):
    monkeypatch.setenv("GATEWAY_TOKEN", "synthetic-proxy")
    monkeypatch.setenv("STORYRAIL_HOST_PROXY_PORT", "7897")
    calls = []

    def resolve(host):
        assert host == "cloudcode-pa.googleapis.com"
        if private_resolution:
            raise ValueError("解析结果不是公网目标")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    class FailedProxy:
        def __init__(self, host, port, timeout):
            calls.append(host)

        def close(self):
            pass

        def set_tunnel(self, host, port):
            assert host == "cloudcode-pa.googleapis.com" and port == 443

        def connect(self):
            raise OSError("synthetic proxy unavailable")

    monkeypatch.setattr(gateway, "public_addresses", resolve)
    monkeypatch.setattr(gateway.http.client, "HTTPConnection", FailedProxy)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HTTPConnection(*server.server_address, timeout=3)
        client.request(
            "CONNECT",
            "cloudcode-pa.googleapis.com:443",
            headers={
                "Proxy-Authorization": "Basic " + base64.b64encode(b"pi:synthetic-proxy").decode()
            },
        )
        response = client.getresponse()
        assert response.status == (403 if private_resolution else 502)
        assert response.read() == b""
        assert calls == ([] if private_resolution else ["host.docker.internal"])
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
