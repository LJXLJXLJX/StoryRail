"""Lazy Breeze-TTS-2 bridge used by the Windows exclusive GPU scheduler.

The lightweight JSONL worker itself starts with the Provider service.  The
large Breeze WSL process is started only when the first Breeze task arrives and
is stopped when the scheduler switches to H3/another model family.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import traceback
import wave
from pathlib import Path
from typing import Any

_CURRENT_REQUEST_ID: str | None = None
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")
_SYNTHESIS_TIMEOUT_SECONDS = 1_800.0
# --fast-all 在加载后捕获 CUDA Graph 并编译 depth decoder，16 GB 卡上实测约 70 秒。
_STARTUP_TIMEOUT_SECONDS = 600.0
# 启动期段错误（128 + SIGSEGV）与非法指令（128 + SIGILL）实测来自 WSL 虚拟机 GPU 半虚拟化失效：
# 同一虚拟机内重试必然再崩，重启发行版后即恢复。
# exclusive_gpu 保证此时没有其它 WSL runtime（IndexTTS2）在运行。
_WSL_RESET_EXIT_CODES = frozenset({132, 139})
_API_LOG_LIMIT_BYTES = 16 * 1024 * 1024
_API_LOG_TAIL_BYTES = 600


def emit(event: str, message: str, **values: Any) -> None:
    payload = {"event": event, "message": message, **values}
    if _CURRENT_REQUEST_ID is not None:
        payload["request_id"] = _CURRENT_REQUEST_ID
    print(json.dumps(payload, ensure_ascii=False), flush=True)


class BreezeApi:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._wsl = os.environ.get("STORYRAIL_WSL_EXE", r"C:\Windows\System32\wsl.exe")
        self._distribution = os.environ.get("STORYRAIL_WSL_DISTRIBUTION", "Ubuntu")
        self._port = int(os.environ.get("STORYRAIL_BREEZE_PORT", "7860"))
        self._repository = os.environ.get("STORYRAIL_BREEZE_REPOSITORY", "/home/ljx/ai/breeze-tts")
        self._python = os.environ.get(
            "STORYRAIL_BREEZE_PYTHON", "/home/ljx/ai/breeze-tts/.venv/bin/python"
        )
        self._model = os.environ.get("STORYRAIL_BREEZE_MODEL", "/home/ljx/ai/models/Breeze-TTS-2")
        # Breeze API 的 stdout/stderr 落到 Windows 侧日志；未配置时（测试）丢弃。
        log = os.environ.get("STORYRAIL_BREEZE_API_LOG")
        self._log_path = Path(log) if log else None
        # WSL NAT 模式的 localhost 转发在虚拟机冷启动后可能不建立，因此 API 绑定并直连
        # WSL eth0 地址；该地址只在 Windows 主机与 WSL 之间的 NAT 网段内可达。
        self._host = "127.0.0.1"

    def ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if os.name != "nt":
            raise RuntimeError("Breeze runtime 只能从 Windows 调用 WSL。")
        code = self._start_once()
        if code is None:
            return
        if code not in _WSL_RESET_EXIT_CODES:
            raise RuntimeError(self._startup_failure(code))
        emit(
            "progress",
            f"Breeze API 启动崩溃（退出码 {code}），正在重启 WSL 后重试一次。",
            value=0.05,
        )
        self.stop()
        self._reset_wsl()
        code = self._start_once()
        if code is not None:
            raise RuntimeError(self._startup_failure(code) + "已重启 WSL 并重试一次。")

    def _start_once(self) -> int | None:
        """启动并等到端口可连；进程在启动期退出时返回退出码。"""
        probe = (
            f"test -x '{self._python}' && test -d '{self._model}' && "
            f"test -f '{self._repository}/breeze_infer/api.py' && hostname -I"
        )
        # 本 worker 的 stdin 是调度器的 JSONL 命令管道；所有子进程（尤其 wsl.exe）
        # 必须显式断开 stdin，否则会吞掉下一条 run 命令，第二个任务永远等不到。
        check = subprocess.run(
            [self._wsl, "--distribution", self._distribution, "--", "/bin/bash", "-lc", probe],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if check.returncode != 0:
            raise RuntimeError("Breeze WSL 部署预检失败：固定仓库、Python 或模型不存在。")
        self._host = _wsl_address(check.stdout)
        command = (
            f"cd '{self._repository}' && exec '{self._python}' -m breeze_infer.api "
            f"'{self._model}' --host {self._host} --port {self._port} --fast-all"
        )
        with self._open_log() as log:
            self._process = subprocess.Popen(
                [
                    self._wsl,
                    "--distribution",
                    self._distribution,
                    "--",
                    "/bin/bash",
                    "-lc",
                    command,
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        emit("progress", "Breeze TTS 2 正在加载并预热快速推理路径。", value=0.05)
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                code = self._process.returncode
                self._process = None
                return code
            try:
                with socket.create_connection((self._host, self._port), timeout=0.5):
                    emit("progress", "Breeze TTS 2 已加载并驻留。", value=0.18)
                    return None
            except OSError:
                time.sleep(0.25)
        self.stop()
        raise RuntimeError("Breeze API 启动超时。")

    def _open_log(self) -> Any:
        if self._log_path is None:
            return contextlib.nullcontext(subprocess.DEVNULL)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        # 子进程继承句柄后父进程即可关闭；超过上限时从头写，保留最近几次启动。
        with contextlib.suppress(OSError):
            if self._log_path.stat().st_size > _API_LOG_LIMIT_BYTES:
                self._log_path.unlink()
        log = self._log_path.open("ab")
        log.write(f"\n===== Breeze API start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
        log.flush()
        return log

    def _startup_failure(self, code: int) -> str:
        message = f"Breeze API 启动失败，退出码 {code}。"
        tail = _log_tail(self._log_path)
        return f"{message}最后输出：{tail}" if tail else message

    def _reset_wsl(self) -> None:
        subprocess.run(
            [self._wsl, "--terminate", self._distribution],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def synthesize(self, request: dict[str, Any], task_dir: Path, cancel: Any) -> Path:
        self.ensure_started()
        boundary = "----StoryRailBreeze" + os.urandom(12).hex()
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        field("text", request["text"])
        field("cfg_scale", str(_effective_cfg_scale(request)))
        field("seed", str(request["seed"]))
        if request.get("instruction"):
            field("instruction", request["instruction"])
        if request.get("reference_transcript"):
            field("ref_text", request["reference_transcript"])
        voice_name = request.get("voice")
        if voice_name:
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        f'Content-Disposition: form-data; name="ref_audio"; '
                        f'filename="{voice_name}"\r\n'
                    ).encode(),
                    f"Content-Type: {request['voice_media_type']}\r\n\r\n".encode(),
                    (task_dir / voice_name).read_bytes(),
                    b"\r\n",
                ]
            )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        # A socket read that times out poisons the response stream ("cannot read
        # from timed out object"), so a short poll-and-retry timeout is unsafe.
        # Breeze may pause for long stretches between PCM chunks while decoding.
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=_SYNTHESIS_TIMEOUT_SECONDS
        )
        try:
            connection.request(
                "POST",
                "/v1/audio/speech",
                body=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Accept": "audio/pcm",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                detail = response.read(4096).decode("utf-8", errors="replace")
                raise RuntimeError(f"Breeze 返回 HTTP {response.status}：{detail[:500]}")
            chunks: list[bytes] = []
            while True:
                if cancel.is_set():
                    raise _Cancelled
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            pcm = b"".join(chunks)
            if not pcm or len(pcm) % 2:
                raise RuntimeError("Breeze 没有返回合法的 PCM 音频。")
            sample_rate = int(response.headers.get("X-Sample-Rate", "24000"))
            output = task_dir / "output.wav"
            partial = task_dir / "output.partial.wav"
            with wave.open(str(partial), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(sample_rate)
                writer.writeframes(pcm)
            os.replace(partial, output)
            return output
        finally:
            connection.close()

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        # The WSL launcher owns the API child; use the exact fixed command
        # signature so a stale Breeze process cannot survive a model switch.
        pattern = breeze_process_pattern(self._model, self._port)
        with contextlib.suppress(Exception):
            subprocess.run(
                [
                    self._wsl,
                    "--distribution",
                    self._distribution,
                    "--exec",
                    "/bin/pkill",
                    "-TERM",
                    "-f",
                    pattern,
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        with contextlib.suppress(Exception):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()


def breeze_process_pattern(model: str, port: int | str) -> str:
    """pkill -f 的固定命令签名；host 随 WSL 地址变化，只放宽为 IPv4。"""
    return f"breeze_infer.api {model} --host [0-9.]+ --port {port}( |$)"


def _effective_cfg_scale(request: dict[str, Any]) -> float:
    """Keep bare voice cloning compatible with Breeze's available CFG branches.

    The deployed ``ref_clone_tata`` template has no negative prompt, so its
    inference runtime rejects any CFG value other than 1. Voice Direction uses
    ``ref_edit_tata`` and retains the configured guidance scale.
    """
    if request.get("voice") and not request.get("instruction"):
        return 1.0
    return float(request["cfg_scale"])


def _log_tail(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        with path.open("rb") as log:
            log.seek(max(0, log.seek(0, os.SEEK_END) - _API_LOG_TAIL_BYTES))
            data = log.read()
    except OSError:
        return ""
    return " ".join(data.decode("utf-8", errors="replace").split())[-_API_LOG_TAIL_BYTES:]


def _wsl_address(output: str) -> str:
    for token in output.split():
        try:
            address = ipaddress.ip_address(token)
        except ValueError:
            continue
        if address.version == 4 and not address.is_loopback:
            return str(address)
    raise RuntimeError("Breeze WSL 预检没有返回可用的 IPv4 地址。")


class _Cancelled(RuntimeError):
    pass


def _serve() -> int:
    global _CURRENT_REQUEST_ID
    api = BreezeApi()
    emit("ready", "Breeze TTS 2 调度 runtime 已就绪；模型按需加载。", runtime_pid=os.getpid())
    try:
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if value == {"command": "shutdown"}:
                    emit("stopping", "Breeze TTS 2 正在释放。")
                    return 0
                if (
                    not isinstance(value, dict)
                    or set(value) != {"command", "request_id", "request_file"}
                    or value["command"] != "run"
                    or not isinstance(value["request_id"], str)
                    or not _REQUEST_ID.fullmatch(value["request_id"])
                    or not isinstance(value["request_file"], str)
                ):
                    raise ValueError("Breeze runtime command schema 不合法。")
                _CURRENT_REQUEST_ID = value["request_id"]
                request_path = Path(value["request_file"]).resolve(strict=True)
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(request, dict)
                    or request.get("schema") != "breeze_tts2_request_v1"
                ):
                    raise ValueError("Breeze 内部请求 schema 不合法。")
                output = api.synthesize(request, request_path.parent, _CancelProbe())
                emit("result", "Breeze TTS 2 音频生成完成，runtime 继续驻留。", output=str(output))
            except _Cancelled:
                emit("error", "Breeze TTS 2 任务已取消。")
            except Exception as exc:
                print(traceback.format_exc(), file=sys.stderr, flush=True)
                emit("error", f"Breeze TTS 2 失败（{type(exc).__name__}）：{str(exc)[:1000]}")
            finally:
                _CURRENT_REQUEST_ID = None
        return 0
    finally:
        api.stop()


class _CancelProbe:
    def is_set(self) -> bool:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", required=True)
    parser.parse_args(argv)
    return _serve()


if __name__ == "__main__":
    raise SystemExit(main())
