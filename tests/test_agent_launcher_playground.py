"""启动器的 Playground scope、同范围多开、volume 与 gateway 环境变量。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.agent_launcher import __main__ as launcher

PROJECT_ID = "a" * 32


def _prepare(monkeypatch, tmp_path, calls, requests, *, copied=None):
    copied = [] if copied is None else copied

    def checked(args, **kwargs):
        if args[:3] == ["docker", "image", "inspect"]:
            raise ValueError("镜像未安装")
        calls.append((args, kwargs))
        return b""

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    def copyfile(source, destination, **kwargs):
        copied.append(Path(source).name)

    def control(path, request):
        requests.append(request)
        return {
            "scope": "playground",
            "caller_id": "agent-synthetic",
            "token": "synthetic-agent-token",
        }

    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "pi"))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setattr(launcher, "checked", checked)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(launcher, "control", control)
    monkeypatch.setattr(
        launcher, "run_interactive", lambda args, **kwargs: calls.append((args, kwargs)) or 0
    )
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(launcher.shutil, "copyfile", copyfile)


def test_project_and_playground_flags_are_exclusive(tmp_path, monkeypatch, capsys):
    for argv in (
        ["launcher", "--socket", str(tmp_path / "control.sock")],
        [
            "launcher",
            "--socket",
            str(tmp_path / "control.sock"),
            "--project",
            PROJECT_ID,
            "--playground",
        ],
        ["launcher", "--socket", str(tmp_path / "control.sock"), "--project", "not-hex"],
    ):
        monkeypatch.setattr(sys, "argv", list(argv))
        with pytest.raises(SystemExit) as stopped:
            launcher.main()
        assert stopped.value.code == 1
        assert "请从项目页面或 Playground 页面重新复制启动命令。" in capsys.readouterr().out


def test_playground_scope_key_used_for_volume(tmp_path, monkeypatch, capsys):
    calls: list[tuple] = []
    requests: list[dict] = []
    _prepare(monkeypatch, tmp_path, calls, requests)
    monkeypatch.setattr(launcher.shutil, "copytree", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["launcher", "--socket", str(tmp_path / "control.sock"), "--playground", "--agent", "pi"],
    )

    with pytest.raises(SystemExit) as stopped:
        launcher.main()

    assert stopped.value.code == 0
    assert requests == [{"action": "connect_playground"}]
    assert any(
        "type=volume,source=storyrail-pi-playground,target=/workspace" in str(args)
        for args, _ in calls
    )
    gateways = [entry for entry in calls if "/app/gateway.py" in entry[0]]
    assert len(gateways) == 1
    gateway_args, gateway_options = gateways[0]
    assert "STORYRAIL_SCOPE" in gateway_args and "PROJECT_ID" not in gateway_args
    assert gateway_options["env"]["STORYRAIL_SCOPE"] == "playground"
    assert "PROJECT_ID" not in gateway_options["env"]
    assert "已连接 Playground。你可以描述想做的实验。" in capsys.readouterr().out


def test_build_context_includes_playground_prompt(tmp_path, monkeypatch):
    assert "PLAYGROUND_PROMPT.md" in launcher.BUILD_CONTEXT_FILES
    calls: list[tuple] = []
    requests: list[dict] = []
    copied: list[str] = []
    _prepare(monkeypatch, tmp_path, calls, requests, copied=copied)
    monkeypatch.setattr(launcher.shutil, "copytree", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["launcher", "--socket", str(tmp_path / "control.sock"), "--playground", "--agent", "pi"],
    )

    with pytest.raises(SystemExit):
        launcher.main()

    assert "PLAYGROUND_PROMPT.md" in copied
    assert any(args[:2] == ["docker", "build"] for args, _ in calls)


def test_build_context_includes_shared_wire_contracts() -> None:
    """MCP adapter 的错误信封来自 storyrail_contracts；镜像必须带上它。

    2026-09-26 的重构把这个 import 加进了 bridge.py，但启动器的构建上下文一直
    没有复制该包，导致外部 Agent 容器内的 MCP server 直接 ModuleNotFoundError。
    """

    import inspect

    source = inspect.getsource(launcher)
    assert 'root / "storyrail_contracts"' in source
    assert 'context / "storyrail_contracts"' in source

    dockerfile = Path(launcher.__file__).with_name("Dockerfile").read_text(encoding="utf-8")
    assert "COPY --chmod=0755 storyrail_contracts /app/storyrail_contracts" in dockerfile

    # 摘要必须覆盖共享契约，改契约时镜像会重建。
    repository_root = Path(launcher.__file__).resolve().parents[2]
    digest = launcher.agent_build_digest(repository_root)
    modified = repository_root / "storyrail_contracts" / "errors.py"
    original = modified.read_bytes()
    try:
        modified.write_bytes(original + b"\n# digest probe\n")
        assert launcher.agent_build_digest(repository_root) != digest
    finally:
        modified.write_bytes(original)


def test_build_digest_ignores_caches_excluded_from_context(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repository"
    launcher_file = root / "integrations/agent_launcher/__main__.py"
    launcher_file.parent.mkdir(parents=True)
    monkeypatch.setattr(launcher, "__file__", str(launcher_file))
    for name in launcher.BUILD_CONTEXT_FILES:
        (launcher_file.parent / name).write_text(name)
    for name in (
        "integrations/__init__.py",
        "integrations/storyrail_mcp/__init__.py",
        "storyrail_contracts/errors.py",
        *launcher.CORE_TEXT_FILES,
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    digest = launcher.agent_build_digest(root)
    for package in ("integrations/storyrail_mcp", "storyrail_contracts"):
        cache = root / package / "__pycache__/probe.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"compiled cache changes independently of source")
    assert launcher.agent_build_digest(root) == digest
    context = tmp_path / "context"
    context.mkdir()
    launcher.prepare_build_context(root, context)
    assert not list(context.rglob("__pycache__"))
    (root / "storyrail_contracts/errors.py").write_text("changed actual source")
    assert launcher.agent_build_digest(root) != digest


def test_shared_image_is_reused_and_only_explicit_update_refreshes_dependencies(
    tmp_path, monkeypatch
) -> None:
    state = {"source": "first-source", "installed": None}
    builds = []
    monkeypatch.setattr(launcher, "agent_build_digest", lambda _root: state["source"])
    monkeypatch.setattr(launcher, "prepare_build_context", lambda *_args: None)

    def checked(args, **kwargs):
        if args[:3] == ["docker", "image", "inspect"]:
            assert args[-1] == launcher.AGENT_IMAGE
            if state["installed"] is None:
                raise ValueError("镜像未安装")
            return state["installed"].encode()
        assert args[:2] == ["docker", "build"]
        builds.append(args)
        state["installed"] = state["source"]
        return b""

    monkeypatch.setattr(launcher, "checked", checked)
    # 每个 Agent 的启动都查询同一个镜像；首次之后不重复构建。
    for _agent in ("pi", "codex", "agy", "kimi", "dsh", "grok"):
        assert launcher.prepare_agent_image(tmp_path, tmp_path) == launcher.AGENT_IMAGE
    assert len(builds) == 1
    state["source"] = "changed-client-source"
    launcher.prepare_agent_image(tmp_path, tmp_path)
    assert len(builds) == 2
    assert all("--no-cache" not in args and "--build-arg" not in args for args in builds)
    launcher.prepare_agent_image(tmp_path, tmp_path, update=True)
    assert len(builds) == 3
    assert "--no-cache" in builds[-1]
    launcher.prepare_agent_image(tmp_path, tmp_path)
    assert len(builds) == 3


def test_same_project_and_agent_can_run_concurrently(tmp_path, monkeypatch, capsys):
    calls: list[tuple] = []
    requests: list[dict] = []
    _prepare(monkeypatch, tmp_path, calls, requests)
    monkeypatch.setattr(launcher.shutil, "copytree", lambda *args, **kwargs: None)
    argv = ["launcher", "--socket", str(tmp_path / "control.sock"), "--project", PROJECT_ID]
    monkeypatch.setattr(sys, "argv", [*argv, "--agent", "agy"])
    agent_containers: list[str] = []
    agent_commands: list[list[str]] = []

    def run_interactive(args, *, container, **kwargs):
        agent_containers.append(container)
        agent_commands.append(args)
        if len(agent_containers) == 1:
            # 第一个终端仍在运行时，同一项目、同一 Agent 再次启动。
            with pytest.raises(SystemExit) as nested:
                launcher.main()
            assert nested.value.code == 0
        return 0

    monkeypatch.setattr(launcher, "run_interactive", run_interactive)

    with pytest.raises(SystemExit) as stopped:
        launcher.main()

    assert stopped.value.code == 0
    assert len(agent_containers) == 2 and agent_containers[0] != agent_containers[1]
    assert requests == [{"action": "connect", "project_id": PROJECT_ID}] * 2
    workspace = f"type=volume,source=storyrail-agy-{PROJECT_ID},target=/workspace"
    assert all(workspace in command for command in agent_commands)
    assert "正在运行" not in capsys.readouterr().out


def test_shared_image_build_lock_prevents_duplicate_concurrent_builds(
    tmp_path, monkeypatch
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    state = {"installed": False, "builds": 0}
    building = threading.Event()
    release_build = threading.Event()
    waiting_for_lock = threading.Event()
    original_flock = launcher.fcntl.flock

    def flock(descriptor, operation):
        if building.is_set():
            waiting_for_lock.set()
        return original_flock(descriptor, operation)

    def checked(args, **kwargs):
        if args[:3] == ["docker", "image", "inspect"]:
            if not state["installed"]:
                raise ValueError("镜像未安装")
            return b"shared-source"
        assert args[:2] == ["docker", "build"]
        state["builds"] += 1
        building.set()
        assert release_build.wait(5)
        state["installed"] = True
        return b""

    monkeypatch.setattr(launcher.fcntl, "flock", flock)
    monkeypatch.setattr(launcher, "checked", checked)
    monkeypatch.setattr(launcher, "agent_build_digest", lambda _root: "shared-source")
    monkeypatch.setattr(launcher, "prepare_build_context", lambda *_args: None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(launcher.prepare_agent_image, tmp_path, tmp_path)
        try:
            assert building.wait(5)
            second = executor.submit(launcher.prepare_agent_image, tmp_path, tmp_path)
            assert waiting_for_lock.wait(5)
        finally:
            release_build.set()
        assert first.result(timeout=5) == second.result(timeout=5) == launcher.AGENT_IMAGE
    assert state["builds"] == 1


def test_address_pool_exhaustion_has_specific_error_without_echoing_output(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stderr=b"all predefined address pools have been fully subnetted\nsynthetic-secret",
        ),
    )
    with pytest.raises(ValueError, match="Docker 网络地址池已耗尽") as error:
        launcher.checked(["docker", "network", "create", "storyrail-pi-probe"])
    assert "synthetic-secret" not in str(error.value)


def test_build_context_starts_mcp_handshake_in_isolation(tmp_path) -> None:
    """镜像 /app 布局就是构建上下文；MCP server 必须只靠它完成 initialize。

    MCP instructions 读取 Core skills 中的一致性规则原文，构建上下文曾漏掉该文件，
    导致容器内 server 启动即 FileNotFoundError，Codex 报 required MCP 握手失败。
    """

    import asyncio
    import os

    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    repository_root = Path(launcher.__file__).resolve().parents[2]
    context = tmp_path / "app"
    context.mkdir()
    launcher.prepare_build_context(repository_root, context)
    token = tmp_path / "core-token"
    token.write_text("synthetic-agent-token")

    async def handshake(scope):
        params = StdioServerParameters(
            command=sys.executable,
            cwd=str(context),
            # 与容器一致只暴露 /app，宿主仓库不在导入路径上。
            env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(context)},
            args=[
                "-P",
                "-m",
                "integrations.storyrail_mcp",
                "--core-origin",
                "http://gateway:8080",
                "--token-file",
                str(token),
                "--scope",
                scope,
            ],
        )
        async with Client(params) as client:
            return client.server_info.name, client.instructions or ""

    for scope in ("project", "playground"):
        assert asyncio.run(handshake(scope))[0] == "StoryRail"

    # 摘要覆盖被复制的 Core 文本，改规则时镜像会重建。
    digest = launcher.agent_build_digest(repository_root)
    modified = repository_root / launcher.CORE_TEXT_FILES[0]
    original = modified.read_bytes()
    try:
        modified.write_bytes(original + b"\n")
        assert launcher.agent_build_digest(repository_root) != digest
    finally:
        modified.write_bytes(original)
