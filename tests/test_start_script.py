"""start.sh 的可测函数：Provider 目录参数解析与就绪等待预算。

测试只从 start.sh 抽取函数定义，在子 shell 中调用，不启动 Core、Web 或任何 Provider。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


def _function_body(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{.*?^\}}$", START_SH.read_text(), re.S | re.M)
    assert match is not None, f"start.sh 缺少 {name} 定义"
    return match.group(0)


def _parse(tmp_path: Path, *arguments: str, provider_dirs: str = ""):
    script = "\n".join(
        [
            "set -euo pipefail",
            f'ROOT_DIRECTORY="{tmp_path}"',
            f'SLATEHAND_PROVIDER_DIRS="{provider_dirs}"',
            "provider_directories=()",
            "passthrough_arguments=()",
            _function_body("add_provider_directory"),
            _function_body("parse_arguments"),
            'parse_arguments "$@"',
            'printf "dir %s\\n" "${provider_directories[@]+"${provider_directories[@]}"}"',
            'printf "arg %s\\n" "${passthrough_arguments[@]+"${passthrough_arguments[@]}"}"',
        ]
    )
    return subprocess.run(
        ["/bin/bash", "-c", script, "start.sh", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=tmp_path,
    )


def test_provider_directories_keep_command_line_then_configured_order(tmp_path) -> None:
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    result = _parse(
        tmp_path,
        "--provider-dir",
        "a",
        "--port",
        "1",
        "--provider-dir=b",
        provider_dirs=f"c:{tmp_path / 'a'}",
    )
    assert result.returncode == 0, result.stderr
    root = tmp_path.resolve()
    assert result.stdout.splitlines() == [
        f"dir {root / 'a'}",
        f"dir {root / 'b'}",
        f"dir {root / 'c'}",
        f"dir {root / 'a'}",
        "arg --port",
        "arg 1",
    ]


def test_missing_provider_directory_stops_start(tmp_path) -> None:
    result = _parse(tmp_path, "--provider-dir", "missing")
    assert result.returncode == 1
    assert "Provider 目录不存在" in result.stderr


def test_wait_until_ready_honours_explicit_attempt_budget(tmp_path) -> None:
    """慢启动步骤可显式放宽就绪预算；$4 缺省仍是 60 次 × 0.5s（30s）。"""
    counter = tmp_path / "curl-calls"
    script = "\n".join(
        [
            "set -euo pipefail",
            f'counter="{counter}"',
            'curl() { echo x >> "$counter"; return 1; }',
            "sleep() { :; }",
            "kill() { return 0; }",
            'say_error() { printf "启动失败：%s\\n" "$1" >&2; exit 1; }',
            _function_body("wait_until_ready"),
            'wait_until_ready "T" "http://example.invalid/" 1 5',
        ]
    )
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert "等待 T 就绪超时" in result.stderr
    assert len(counter.read_text().splitlines()) == 5
