"""隔离网络出口：固定 Core 路由与公共 HTTPS 隧道，不接管模型鉴权。"""

import base64
import hmac
import http.client
import ipaddress
import json
import os
import re
import select
import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 这些固定的 Google 服务域名由厂商控制，不接受 Agent 自定义链式代理目标。
# 标准 CONNECT 会由宿主代理重新解析域名，只有这些目标委托给受信宿主代理。
HOST_PROXY_TARGETS = frozenset(
    {
        "cloudcode-pa.googleapis.com",
        "daily-cloudcode-pa.googleapis.com",
        "autopush-cloudcode-pa.sandbox.googleapis.com",
        "preprod-daily-cloudcode-pa.sandbox.googleapis.com",
        "generativelanguage.googleapis.com",
        "aiplatform.googleapis.com",
        "s-aiplatform.googleapis.com",
        "oauth2.googleapis.com",
        "oauth2.mtls.googleapis.com",
    }
)


def public_addresses(host):
    """仅连接校验后的公网 IP；本机 DNS 被代理替换时通过固定 TLS 出口重新解析。"""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("私网目标不可访问")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host) or "." not in host:
        raise ValueError("目标域名不合法")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if addresses and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        return addresses
    # 固定公网 IP + 标准 TLS 证书校验，避免系统 DNS 的 Fake-IP 再次介入。
    connection = http.client.HTTPSConnection("1.1.1.1", timeout=10)
    try:
        connection.request(
            "GET", f"/dns-query?name={host}&type=A", headers={"Accept": "application/dns-json"}
        )
        response = connection.getresponse()
        body = response.read(65537)
        if response.status != 200 or len(body) > 65536:
            raise ValueError("公网解析失败")
        answer = json.loads(body)
        if not isinstance(answer, dict) or answer.get("Status") != 0:
            raise ValueError("公网解析失败")
        ips = [ipaddress.IPv4Address(a["data"]) for a in answer.get("Answer", []) if a["type"] == 1]
        if not ips or any(not ip.is_global for ip in ips):
            raise ValueError("解析结果不是公网目标")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (str(ip), 443)) for ip in ips]
    finally:
        connection.close()


@contextmanager
def model_upstream(host, addresses):
    """固定 Google 服务保留域名经宿主代理分流；其它目标始终连接已校验 IP。"""
    proxy_port = os.environ.get("STORYRAIL_HOST_PROXY_PORT")
    if proxy_port and host.lower().rstrip(".") in HOST_PROXY_TARGETS:
        port = int(proxy_port)
        if not 1 <= port <= 65535:
            raise ValueError("宿主代理端口不合法")
        proxy = http.client.HTTPConnection("host.docker.internal", port, timeout=30)
        try:
            proxy.set_tunnel(host, 443)
            proxy.connect()
            yield proxy.sock
        finally:
            proxy.close()
        return
    with socket.socket(addresses[0][0], socket.SOCK_STREAM) as upstream:
        upstream.settimeout(30)
        upstream.connect(addresses[0][4])
        yield upstream


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802
        self.forward()

    def do_POST(self):  # noqa: N802
        self.forward()

    def do_CONNECT(self):  # noqa: N802
        expected = (
            "Basic " + base64.b64encode(("pi:" + os.environ["GATEWAY_TOKEN"]).encode()).decode()
        )
        if not hmac.compare_digest(self.headers.get("Proxy-Authorization", ""), expected):
            return self.reject(403)
        tunnel_open = False
        try:
            host, port = self.path.rsplit(":", 1)
            if port != "443" or not host or any(c in host for c in "/@?#[]"):
                return self.reject(403)
            try:
                addresses = public_addresses(host)
            except (ValueError, OSError, KeyError, TypeError, http.client.HTTPException):
                return self.reject(403)
            with model_upstream(host, addresses) as upstream:
                self.send_response(200)
                self.end_headers()
                tunnel_open = True
                peers = (self.connection, upstream)
                while ready := select.select(peers, [], [], 300)[0]:
                    for source in ready:
                        content = source.recv(65536)
                        if not content:
                            return
                        (upstream if source is self.connection else self.connection).sendall(
                            content
                        )
        except (OSError, ValueError, http.client.HTTPException):
            # 指定宿主代理失败时拒绝，不回退到另一个出口；错误正文不含凭据。
            if not tunnel_open:
                self.reject(502)
            self.close_connection = True

    def forward(self):
        if os.environ.get("STORYRAIL_SCOPE") == "playground":
            # Playground scope 只有一条命令入口，不携带项目身份。
            allowed = self.command == "POST" and self.path == "/api/playground/commands"
        else:
            prefix = "/api/projects/" + os.environ["PROJECT_ID"] + "/structured-director"
            allowed = (
                self.command == "POST" and self.path == prefix + "/application/commands"
            ) or (
                self.command == "GET"
                and re.fullmatch(re.escape(prefix) + r"/assets/[0-9a-f]{32}/content", self.path)
            )
        if not allowed:
            return self.reject(403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 65536:
                return self.reject(413)
            body = self.rfile.read(size)
            connection = http.client.HTTPConnection(
                "host.docker.internal", int(os.environ["CORE_PORT"]), timeout=30
            )
            path = self.path
            headers = {
                "Authorization": self.headers.get("Authorization", ""),
                "Content-Type": "application/json",
            }
            try:
                connection.request(self.command, path, body=body, headers=headers)
                response = connection.getresponse()
                self.send_response(response.status)
                self.send_header(
                    "Content-Type", response.getheader("Content-Type", "application/json")
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException):
            # 不重试、不打印请求/凭据。
            self.close_connection = True

    def reject(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Gateway).serve_forever()
