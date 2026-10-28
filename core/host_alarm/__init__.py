"""Core 主机闹钟：循环播放系统提示音并弹出原生对话框，点“知道了”或到时即停。

只是提醒，不写项目或 Playground 状态；同一时刻只响一个闹钟。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from collections.abc import Callable

ALARM_SECONDS = 120
MESSAGE_MAX_CHARS = 200

# $1 为提示文字、$2 为最长秒数，均经 argv 传入，不拼进脚本或 AppleScript 源码。
_SCRIPT = r"""
end=$((SECONDS + $2))
(
  trap 'kill "$player" 2>/dev/null; exit 0' TERM
  while (( SECONDS < end )); do
    afplay /System/Library/Sounds/Glass.aiff & player=$!
    wait "$player"
  done
) &
loop=$!
osascript \
  -e 'on run argv' \
  -e 'set msg to item 1 of argv' \
  -e 'set secs to (item 2 of argv) as integer' \
  -e 'set opts to {"知道了"}' \
  -e 'set t to "StoryRail"' \
  -e 'display dialog msg buttons opts default button 1 with title t giving up after secs' \
  -e 'end run' "$1" "$2" >/dev/null 2>&1
kill "$loop" 2>/dev/null
wait "$loop" 2>/dev/null
"""


def _spawn(message: str, seconds: int) -> subprocess.Popen:
    if sys.platform != "darwin" or not all(shutil.which(item) for item in ("afplay", "osascript")):
        raise RuntimeError("当前 Core 主机不支持闹钟提示音（需要 macOS 的 afplay 与 osascript）。")
    return subprocess.Popen(
        ["/bin/bash", "-c", _SCRIPT, "storyrail-alarm", message, str(seconds)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class HostAlarm:
    def __init__(self, spawn: Callable[[str, int], subprocess.Popen] = _spawn) -> None:
        self._spawn = spawn
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def ring(self, message: object) -> dict[str, object]:
        if not isinstance(message, str):
            raise ValueError("message 必须是文本。")
        text = " ".join(message.split())
        if not text or len(text) > MESSAGE_MAX_CHARS:
            raise ValueError(f"message 必须是 1–{MESSAGE_MAX_CHARS} 字的非空文本。")
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return {"status": "already_ringing", "max_seconds": ALARM_SECONDS}
            self._process = self._spawn(text, ALARM_SECONDS)
        return {"status": "ringing", "max_seconds": ALARM_SECONDS}


HOST_ALARM = HostAlarm()

__all__ = ["ALARM_SECONDS", "HOST_ALARM", "MESSAGE_MAX_CHARS", "HostAlarm"]
