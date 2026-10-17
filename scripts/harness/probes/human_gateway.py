"""临时系统 Chrome 验收页面；不进入产品，不暴露无认证的人类写代理。"""

import argparse
import hmac
import html
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RESOURCE = "/api/projects/" + "a" * 32 + "/structured-director"


class Gateway(BaseHTTPRequestHandler):
    def authorized(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            value = cookies["storyrail_synthetic_human"].value
        except (KeyError, ValueError):
            return False
        return hmac.compare_digest(value, self.server.browser_token)

    def send(self, status, body, cookie=None):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.authorized():
            self.send(
                200,
                '<html lang="zh"><h1>StoryRail 合成隔离验收</h1>'
                '<form method="post" action="/login">'
                '<label>临时验收口令<input name="token" type="password">'
                "</label><button>登录验收</button></form></html>",
            )
            return
        self.send(
            200,
            '<html lang="zh"><h1>系统 Chrome · 人类操作验收</h1>'
            '<p>只操作隔离合成项目，不涉及现有作品。</p><form method="post" action="/action">'
            '<button>执行合成项目修改</button></form><form method="post" action="/action">'
            "<button>重放同一请求</button></form><pre>"
            + html.escape(self.server.last_result)
            + "</pre></html>",
        )

    def do_POST(self):
        if self.headers.get("Origin") != self.server.origin:
            self.send(403, "拒绝非同源请求。")
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= 4096:
            self.send(400, "请求不合法。")
            return
        body = self.rfile.read(length).decode()
        if self.path == "/login":
            token = urllib.parse.parse_qs(body).get("token", [""])[0]
            if not hmac.compare_digest(token, self.server.browser_token):
                self.send(403, "口令无效。")
                return
            self.send(
                200,
                '<h1>登录成功</h1><a href="/">打开验收页</a>',
                "storyrail_synthetic_human=" + token + "; HttpOnly; SameSite=Strict; Path=/",
            )
            return
        if self.path != "/action" or not self.authorized():
            self.send(403, "未获得人类会话授权。")
            return
        if self.server.command is None:
            snapshot = self.core("GET", "")
            scene = snapshot["director_script"]["scenes"][0]
            self.server.command = {
                "name": "script.apply_operations",
                "expected_revision": snapshot["revision"],
                "idempotency_key": "system-chrome-" + secrets.token_hex(8),
                "arguments": {
                    "scope": {"scene_ids": [scene["id"]]},
                    "operations": [
                        {
                            "op": "update_shot_fields",
                            "shot_id": scene["shots"][0]["id"],
                            "fields": {"action": "系统 Chrome 的受信用户修改"},
                        }
                    ],
                },
            }
        result = self.core("POST", "/application/commands", self.server.command)
        summary = {
            "receipt": result.get("receipt"),
            "replay": result.get("replay"),
            "application_request_id": result.get("application_request_id"),
        }
        self.server.last_result = json.dumps(summary, ensure_ascii=False, indent=2)
        self.server.evidence.write_text(self.server.last_result)
        self.send(
            200,
            "<h1>Core 操作成功</h1><pre>"
            + html.escape(self.server.last_result)
            + '</pre><a href="/">返回验收页</a>',
        )

    def core(self, method, suffix, value=None):
        request = urllib.request.Request(
            self.server.core_url + RESOURCE + suffix,
            data=None if value is None else json.dumps(value).encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + self.server.core_token,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-token-file", type=Path, required=True)
    parser.add_argument("--browser-token-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--core-url", default="http://127.0.0.1:18765")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Gateway)
    server.core_token = args.core_token_file.read_text().strip()
    server.browser_token = args.browser_token_file.read_text().strip()
    server.core_url, server.evidence = args.core_url, args.evidence
    server.origin = f"http://127.0.0.1:{args.port}"
    server.last_result, server.command = "尚未操作", None
    print("SYSTEM_CHROME_FIXTURE_READY", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
