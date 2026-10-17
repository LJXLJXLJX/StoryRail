"""start.sh 无 Provider 模式的启动回归。

锁住 R14：当 `STORYRAIL_AUTOSTART_{WINDOWS,MAC}_PROVIDER=0` 时，
`restart_windows_provider` / `restart_mac_provider` 必须是返回 0 的 no-op，
不能在 `set -euo pipefail` 下让裸 `return` 传播失败测试的状态 1。
测试只从 start.sh 抽取这两个函数定义，在子 shell 中定义相关全局变量后调用，
不联网、不 SSH、不启动任何 Provider。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

START_SH = Path(__file__).resolve().parents[1] / "start.sh"
MAC_RUN_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "default_model_providers_implement"
    / "macos"
    / "run_codex_server.sh"
)


def _function_body(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{.*?^\}}$", START_SH.read_text(), re.S | re.M)
    assert match is not None, f"start.sh 缺少 {name} 定义"
    return match.group(0)


def test_restart_providers_are_noop_and_return_zero_when_autostart_disabled() -> None:
    script = "\n".join(
        [
            "set -euo pipefail",
            "WINDOWS_PROVIDER_AUTOSTART=0",
            "MAC_PROVIDER_AUTOSTART=0",
            _function_body("restart_windows_provider"),
            _function_body("restart_mac_provider"),
            "restart_windows_provider",
            "restart_mac_provider",
        ]
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr == ""


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


def test_whisper_wait_uses_extended_budget() -> None:
    """R15：574MB 模型冷加载可能超过 30s 默认预算，Whisper 步骤显式放宽到 480 次（240s）。"""
    assert (
        'wait_until_ready "Whisper ASR" "$WHISPER_ENDPOINT/" "$whisper_pid" 480'
        in START_SH.read_text()
    )


def test_mac_provider_script_declares_three_lanes() -> None:
    """PG0-T3：Mac 服务用 network_image / mac_heavy / mac_light 三个 lane 启动。"""
    script = MAC_RUN_SCRIPT.read_text()
    assert (
        "network_image:4:codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit"
        in script
    )
    assert (
        "mac_heavy:1:demucs_audio_separation,ffmpeg_audio_remix,ffmpeg_animatic,ffmpeg_final_assembly"
        in script
    )
    assert "mac_light:1:ffmpeg_video_frame,ffmpeg_pano_view" in script
    assert "--resource-name" not in script
    assert "--max-concurrent-tasks" not in script
