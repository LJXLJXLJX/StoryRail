"""O7 · 纯净安装 oracle。

ARRIVE   `.venv/bin/python -m build --wheel` 从仓库源码产 wheel（构建目录与源码
         分离，cwd 不在仓库内，避免仓库根 build/ 目录遮蔽 build 包）；在 tmp 下
         `python -m venv` 全新环境，`pip install <wheel>[mcp]`（不复制源码、不
         editable）；socket 预绑空闲端口（server/__main__.py 拒绝 port 0），用
         **新 venv 的 python** 起真实 `python -m server` 子进程（参照收编
         scripts/harness/real_agent/clean_install_probe.py）。wheel 与 venv 为 module
         scope，本文件全部用例共享。
ORACLE   断言可达状态谓词：
         - 纯净 venv 中 `import core / server / integrations.storyrail_mcp` 成功且
           解析到 site-packages（不依赖未声明包、不依赖源码树）；
         - `POST /api/projects` 201，响应含结构化导演 snapshot；
         - 全部专业契约（core.director_proposals.professional_contracts
           CONTRACTS：reference_library / script / narration /
           keyframe / video_prompt）经真实 HTTP
           `project.get_contract` 可读，skill_name 与 resources 来自安装的
           wheel（package-data 完整性）。
覆盖领域规则：唯一权威入口（Core HTTP）在纯净安装下可用；专业契约随包分发；
不依赖开发树或内置 Agent runtime。
BUDGET   全场景 ≤60s（build + venv + install + 探针；wheel/venv module 级共享）。
CI       需要网络（pip install [mcp] 依赖与 build isolation 拉 setuptools）。
           GitHub runner 有网；若后续 CI 拆出 "slow" job，本文件是第一候选，
           拆分留给后续卡。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_PYTHON = Path(sys.executable)


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    subprocess.run(
        [str(BUILD_PYTHON), "-m", "build", "--wheel", "--outdir", str(out), str(REPO_ROOT)],
        cwd=out,  # 仓库根 build/ 目录会遮蔽 build 包，构建 cwd 必须与源码分离。
        check=True,
        capture_output=True,
        timeout=600,
        env=env,
    )
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="module")
def clean_venv(tmp_path_factory, wheel_path: Path) -> Path:
    venv = tmp_path_factory.mktemp("venv") / "env"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
    pip = venv / "bin" / "pip"
    subprocess.run(
        [str(pip), "install", "--quiet", f"{wheel_path}[mcp]"],
        check=True,
        capture_output=True,
        timeout=600,
    )
    return venv


@pytest.fixture()
def clean_server(clean_venv: Path, tmp_path):
    """新 venv 的 python 起真实 server 子进程；预绑端口（CLI 拒绝 port 0）。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    stories = tmp_path / "stories"
    stories.mkdir()
    log = (tmp_path / "server.log").open("w")
    proc = subprocess.Popen(
        [
            str(clean_venv / "bin" / "python"),
            "-m",
            "server",
            "--port",
            str(port),
            "--stories-directory",
            str(stories),
        ],
        cwd=tmp_path,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"

    def wait_ready() -> None:
        for _ in range(200):
            try:
                with urllib.request.urlopen(f"{base}/api/projects", timeout=2) as response:
                    assert response.status == 200
                return
            except OSError:
                if proc.poll() is not None:
                    log.flush()
                    raise RuntimeError(
                        f"纯净安装 server 进程提前退出（code {proc.returncode}）："
                        f"{Path(log.name).read_text()[-2000:]}"
                    ) from None
                time.sleep(0.05)
        log.flush()
        raise RuntimeError(f"纯净安装 server 启动超时：{Path(log.name).read_text()[-2000:]}")

    try:
        wait_ready()
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()


def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:  # noqa: PERF203 - 探针需要错误体
        return exc.code, json.loads(exc.read().decode())


@pytest.mark.oracle
def test_oracle_clean_install_server_create_and_imports(clean_venv: Path, clean_server: str):
    # ORACLE：纯净 venv 的 import 解析到 site-packages，不依赖源码树
    # （cwd 必须在仓库外，否则 Python 会把仓库根目录加进 sys.path）。
    check = subprocess.run(
        [
            str(clean_venv / "bin" / "python"),
            "-c",
            "import core, server, integrations.storyrail_mcp; print(core.__file__)",
        ],
        cwd=Path.home(),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    core_file = check.stdout.strip()
    assert "site-packages" in core_file
    assert str(REPO_ROOT) not in core_file

    # ORACLE：真实 server 进程创建项目 201，含结构化导演 snapshot。
    status, body = _post(
        clean_server,
        "/api/projects",
        {
            "title": "O7纯净安装",
            "aspect_ratio": "16:9",
            "director_plan_markdown": "# 合成方案\n静态海岸。",
            "narration_languages": ["zh", "en"],
        },
    )
    assert status == 201
    assert body["structured_director"]["director_plan_markdown"].startswith("# 合成")
    assert "assistant_mode" not in body["structured_director"]


@pytest.mark.oracle
def test_oracle_clean_install_professional_contracts_readable(clean_server: str):
    from core.director_proposals.professional_contracts import CONTRACTS

    status, created = _post(
        clean_server,
        "/api/projects",
        {
            "title": "O7契约可读",
            "aspect_ratio": "16:9",
            "director_plan_markdown": "# 合成方案",
            "narration_languages": ["zh", "en"],
        },
    )
    assert status == 201
    project_id = created["project"]["id"]
    resource = f"/api/projects/{project_id}/structured-director/application/commands"
    assert len(CONTRACTS) == 6
    for capability in CONTRACTS:
        status, body = _post(
            clean_server,
            resource,
            {
                "name": "project.get_contract",
                "idempotency_key": f"O7-contract-{capability}",
                "arguments": {
                    "capability": capability,
                    "include": ["consistency-review"],
                },
            },
        )
        assert status == 200, body
        data = body["data"]
        assert data["capability"] == capability
        assert data["skill_name"] == CONTRACTS[capability][1]
        names = [item["name"] for item in data["resources"]]
        assert "SKILL.md" in names
        assert any(name.startswith("shared/storyrail-consistency-review/") for name in names)
