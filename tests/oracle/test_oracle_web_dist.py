"""O6 · Web dist smoke oracle。

ARRIVE   subprocess 无条件 `npm run build`（cwd=web；CI fresh checkout 无 dist），
         用 stdlib http.server 线程伺服 web/dist（Core server 无静态能力、不新增），
         并起 OracleHttpServer 作为同测可达的 Core。
ORACLE   断言可达状态谓词：
         - dist 的 `GET /` 200，HTML 引用的 JS/CSS 资源逐一 200（至少一个 JS）；
         - dist JS 中的 API origin 逻辑指向同测可达的 Core：web/src/api.ts 的
           request() 使用相对路径 `fetch(url)`（同源约定），因此断言产物 JS 含
           相对 API 路径 `/api/projects`、不烘焙任何绝对 API origin
           （无 http(s)://…:8765 / localhost / 127.0.0.1 形式），index.html 的
           script/link 也不引用外部源——页面部署后与 Core 同源，等价于
           "API origin 指向 Core"；
         - Core 自身 `GET /api/projects` 200（同测可达的语义端点）。
覆盖领域规则：Web 只消费服务端资源；Core 不提供也不伪装静态能力；
dist 产物与 Core API 的同源契约。
BUDGET   单场景 ≤60s（含 web build，实测见报告）；静态伺服与断言本身 <2s。
CI       需要 node/npm（仓库已有 web job）；build 预算 ≤60s 为警告级，不红。
"""

from __future__ import annotations

import functools
import http.server
import re
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
DIST = WEB_ROOT / "dist"
_BAKED_ORIGIN = re.compile(r"https?://(127\.0\.0\.1|localhost|0\.0\.0\.0)(:\d+)?")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def dist_directory() -> Path:
    """无条件构建 dist：CI fresh checkout 没有产物，不能靠跳过 rebuild 省时。"""
    completed = subprocess.run(
        ["npm", "run", "build"],
        cwd=WEB_ROOT,
        capture_output=True,
        timeout=420,
    )
    assert completed.returncode == 0, (
        f"npm run build failed (exit {completed.returncode})\n"
        f"--- stdout ---\n{completed.stdout.decode(errors='replace')[-4000:]}\n"
        f"--- stderr ---\n{completed.stderr.decode(errors='replace')[-4000:]}"
    )
    assert (DIST / "index.html").is_file()
    return DIST


@pytest.fixture()
def static_origin(dist_directory: Path) -> str:
    handler = functools.partial(_QuietHandler, directory=str(dist_directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(origin: str, path: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(f"{origin}{path}", timeout=10) as response:
        return response.status, response.read()


@pytest.mark.oracle
def test_oracle_web_dist_smoke(static_origin: str, http_server) -> None:
    # ORACLE：dist 首页 200，引用的 JS/CSS 逐一 200。
    status, html = _get(static_origin, "/")
    assert status == 200
    text = html.decode()
    referenced = re.findall(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', text)
    assert referenced, "index.html 应引用至少一个 JS/CSS 产物"
    assert any(path.endswith(".js") for path in referenced)
    for path in referenced:
        assert _get(static_origin, path)[0] == 200, path

    # ORACLE：产物 JS 的 API origin 逻辑——相对路径（同源约定），无烘焙绝对源。
    scripts = [path for path in referenced if path.endswith(".js")]
    combined = b"".join(_get(static_origin, path)[1] for path in scripts).decode()
    assert '"/api/projects"' in combined or "/api/projects" in combined
    assert not _BAKED_ORIGIN.search(text), "index.html 不应引用外部绝对源"
    for path in scripts:
        assert not _BAKED_ORIGIN.search(_get(static_origin, path)[1].decode()), (
            f"{path} 不应烘焙绝对 API origin"
        )

    # ORACLE：Core 语义端点同测可达。
    status, body = http_server.request("GET", "/api/projects")
    assert status == 200
    assert body == {"projects": []}
