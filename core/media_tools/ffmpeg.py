"""本机 ffmpeg/ffprobe 调用：可取消的子进程、受控任务目录与媒体探测。"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUTPUT_CANVAS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "2:1": (1920, 960)}
_POLL_SECONDS = 0.25


class MediaToolCancelled(Exception):
    """任务在执行中被取消。"""


@dataclass(frozen=True, slots=True)
class FFmpeg:
    """一对可执行文件路径；所有调用都只读写任务目录内的文件。"""

    ffmpeg: str
    ffprobe: str

    @classmethod
    def discover(cls) -> FFmpeg | None:
        """按 ``SLATEHAND_FFMPEG`` / ``SLATEHAND_FFPROBE`` 或 PATH 查找；任一缺失返回 None。"""
        ffmpeg = os.environ.get("SLATEHAND_FFMPEG") or shutil.which("ffmpeg")
        ffprobe = os.environ.get("SLATEHAND_FFPROBE") or shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            return None
        return cls(ffmpeg, ffprobe)

    def run(self, arguments: list[str], cancel: threading.Event, *, log: Path) -> None:
        """运行一次 ffmpeg；取消时终止整个进程组。stderr 写入任务目录，失败时截取末尾报告。"""
        with log.open("wb") as stderr:
            process = subprocess.Popen(
                [self.ffmpeg, "-nostdin", *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                start_new_session=os.name != "nt",
            )
            try:
                while True:
                    try:
                        returncode = process.wait(timeout=_POLL_SECONDS)
                        break
                    except subprocess.TimeoutExpired:
                        if cancel.is_set():
                            raise MediaToolCancelled from None
            finally:
                if process.poll() is None:
                    _terminate(process)
        if returncode != 0:
            detail = log.read_text(encoding="utf-8", errors="replace").strip()[-2_000:]
            raise RuntimeError(f"FFmpeg 执行失败：{detail or f'退出码 {returncode}'}")

    def probe(self, path: Path, *arguments: str, timeout: float = 120) -> dict[str, Any]:
        result = subprocess.run(
            [self.ffprobe, "-v", "error", *arguments, "-of", "json", str(path)],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[-500:]
            raise ValueError(f"ffprobe 无法读取媒体：{detail or result.returncode}")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("ffprobe 没有返回有效媒体信息。")
        if result.stderr.strip():
            value["_stderr"] = result.stderr.decode("utf-8", "replace")
        return value

    def format_info(self, path: Path) -> dict[str, Any]:
        value = self.probe(path, "-show_streams", "-show_format")
        if not isinstance(value.get("format"), dict):
            raise ValueError("ffprobe 没有返回有效媒体信息。")
        return value

    def duration_seconds(self, path: Path) -> float:
        duration = float(self.format_info(path)["format"]["duration"])
        if duration <= 0:
            raise ValueError("媒体时长无效。")
        return duration


def has_audio(info: dict[str, Any]) -> bool:
    return any(item.get("codec_type") == "audio" for item in info.get("streams", []))


def write_input(directory: Path, name: str, content: bytes) -> Path:
    """把输入字节写入任务目录；文件名只能是单段名称。"""
    if Path(name).name != name:
        raise ValueError("内部媒体文件名不合法。")
    path = directory / name
    path.write_bytes(content)
    return path


def image_suffix(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError("图片必须是 PNG 或 JPEG。")


def _terminate(process: subprocess.Popen) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass
    process.wait()
