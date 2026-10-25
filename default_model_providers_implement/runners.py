from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .breeze_tts2_worker import breeze_process_pattern
from .resource_manager import (
    CancelledError,
    Progress,
    RetryableRuntimeError,
    RunResult,
)
from .task_store import TaskRecord


class ResidentProcessRunner:
    """串行 JSONL worker 客户端；可按模型族选择跨任务驻留或任务后回收。"""

    def __init__(
        self,
        *,
        name: str,
        command_factory: Callable[[], list[str]],
        stderr_path: Path,
        output_name: str,
        media_type: str,
        terminate_runtime: Callable[[int], None] | None = None,
        request_path: Callable[[Path], str] = str,
        cwd_factory: Callable[[], str | None] | None = None,
        environment_factory: Callable[[], dict[str, str] | None] | None = None,
        startup_timeout: float = 900.0,
        startup_retry_exit_codes: frozenset[int] = frozenset(),
        recycle_after_run: bool = False,
    ) -> None:
        self._request_path = request_path
        self._name = name
        self._command_factory = command_factory
        self._stderr_path = stderr_path
        self._output_name = output_name
        self._media_type = media_type
        self._terminate_runtime = terminate_runtime
        self._cwd_factory = cwd_factory
        self._environment_factory = environment_factory
        self._startup_timeout = startup_timeout
        self._startup_retry_exit_codes = startup_retry_exit_codes
        self._recycle_after_run = recycle_after_run
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] | None = None
        self._reader: threading.Thread | None = None
        self._stderr: Any | None = None
        self._runtime_pid: int | None = None

    def __call__(
        self, record: TaskRecord, cancel: threading.Event, progress: Progress
    ) -> RunResult:
        self._ensure_started(cancel, progress)
        process = self._process
        lines = self._lines
        if process is None or process.stdin is None or lines is None:
            raise RuntimeError(f"{self._name} 常驻 runtime 未建立。")
        command = {
            "command": "run",
            "request_id": record.task_id,
            "request_file": self._request_path(Path(record.task_dir) / "request.json"),
        }
        try:
            process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.release()
            raise RetryableRuntimeError(f"{self._name} 常驻 runtime 已意外退出。") from exc

        while True:
            if cancel.is_set():
                self.release()
                raise CancelledError
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None:
                    self.release()
                    raise RetryableRuntimeError(
                        f"{self._name} 常驻 runtime 意外退出，退出码 {process.returncode}。"
                    ) from None
                continue
            if line is None:
                self.release()
                raise RetryableRuntimeError(f"{self._name} 常驻 runtime 输出流已关闭。")
            try:
                event = self._event(line)
            except RuntimeError:
                self.release()
                raise
            self._capture_runtime_pid(event)
            request_id = event.get("request_id")
            if request_id is not None and request_id != record.task_id:
                self.release()
                raise RuntimeError(f"{self._name} runtime 返回了错误的 request_id。")
            kind = event.get("event")
            if kind == "progress":
                progress(float(event["value"]), str(event["message"]))
            elif kind == "result":
                output = Path(record.task_dir) / self._output_name
                if not output.is_file():
                    self.release()
                    raise RuntimeError(f"{self._name} runtime 未产生 {self._output_name}。")
                summary = event.get("summary")
                result = RunResult(
                    output, self._media_type, summary if isinstance(summary, str) else None
                )
                if self._recycle_after_run:
                    # DynamicVRAM 的 mmap、HostBuffer 与原生分配不都属于
                    # torch CUDA cache。长视频模型连续复用同一 Windows
                    # 进程会让 Private Commit 累积；进程边界是可靠的回收点。
                    self.release()
                return result
            elif kind == "error":
                raise RuntimeError(str(event.get("message") or f"{self._name} runtime 失败。"))
            else:
                self.release()
                raise RuntimeError(f"{self._name} runtime 返回了未知事件。")

    def release(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write('{"command":"shutdown"}\n')
                process.stdin.flush()
                process.wait(timeout=30)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self._terminate_process(process)
        self._reset_process()

    def _ensure_started(self, cancel: threading.Event, progress: Progress) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        attempts = 2 if self._startup_retry_exit_codes else 1
        for attempt in range(1, attempts + 1):
            self._start_process()
            deadline = time.monotonic() + self._startup_timeout
            while True:
                if cancel.is_set():
                    self.release()
                    raise CancelledError
                if time.monotonic() >= deadline:
                    self.release()
                    raise RetryableRuntimeError(f"{self._name} 常驻 runtime 启动超时。")
                try:
                    assert self._lines is not None
                    line = self._lines.get(timeout=0.25)
                except queue.Empty:
                    assert self._process is not None
                    if self._process.poll() is None:
                        continue
                    code = self._process.returncode
                    self.release()
                    if code in self._startup_retry_exit_codes and attempt < attempts:
                        progress(0.04, f"{self._name} 原生启动瞬态异常，已释放并重试一次。")
                        break
                    raise RetryableRuntimeError(
                        f"{self._name} 常驻 runtime 启动失败，退出码 {code}。"
                    ) from None
                if line is None:
                    assert self._process is not None
                    code = self._process.wait(timeout=2)
                    self.release()
                    if code in self._startup_retry_exit_codes and attempt < attempts:
                        progress(0.04, f"{self._name} 原生启动瞬态异常，已释放并重试一次。")
                        break
                    raise RetryableRuntimeError(f"{self._name} 常驻 runtime 启动时关闭输出。")
                try:
                    event = self._event(line)
                except RuntimeError:
                    self.release()
                    raise
                self._capture_runtime_pid(event)
                kind = event.get("event")
                if kind == "progress":
                    progress(float(event["value"]), str(event["message"]))
                elif kind == "ready":
                    progress(float(event.get("value", 0.12)), f"{self._name} 已加载并驻留。")
                    return
                elif kind == "error":
                    message = str(event.get("message") or f"{self._name} runtime 启动失败。")
                    self.release()
                    raise RuntimeError(message)
                else:
                    self.release()
                    raise RuntimeError(f"{self._name} runtime 启动时返回了未知事件。")

    def _start_process(self) -> None:
        self._reset_process()
        command = self._command_factory()
        self._stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr = self._stderr_path.open("ab")
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                # stdin 也使用同一编码；utf-8-sig 会给第一条 JSON command 写入 BOM。
                encoding="utf-8",
                cwd=None if self._cwd_factory is None else self._cwd_factory(),
                env=(None if self._environment_factory is None else self._environment_factory()),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self._reset_process()
            raise
        self._lines, self._reader = _start_line_reader(self._process)

    def _capture_runtime_pid(self, event: dict[str, Any]) -> None:
        if isinstance(event.get("runtime_pid"), int):
            self._runtime_pid = event["runtime_pid"]

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if self._runtime_pid is not None and self._terminate_runtime is not None:
            self._terminate_runtime(self._runtime_pid)
        if process.poll() is None:
            _terminate(process)

    def _reset_process(self) -> None:
        process, reader, stderr = self._process, self._reader, self._stderr
        if process is not None and process.poll() is None:
            self._terminate_process(process)
        if reader is not None:
            reader.join(timeout=2)
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
        if stderr is not None:
            stderr.close()
        self._process = None
        self._lines = None
        self._reader = None
        self._stderr = None
        self._runtime_pid = None

    @staticmethod
    def _event(line: str) -> dict[str, Any]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("常驻 runtime 输出了非法 JSON 事件。") from exc
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            raise RuntimeError("常驻 runtime 事件结构不合法。")
        return event


def mock_runner(record: TaskRecord, cancel: threading.Event, progress: Progress) -> RunResult:
    task_dir = Path(record.task_dir)
    request = _read_request(task_dir)
    delay_ms = int(request["delay_ms"])
    for index in range(4):
        if cancel.wait(delay_ms / 4000):
            raise CancelledError
        progress((index + 1) / 5, "Mock 正在生成确定性输出。")
    output = task_dir / "mock-output.txt"
    output.write_text(f"StoryRail Mock Artifact\n{request['text']}\n", encoding="utf-8")
    return RunResult(output, "text/plain")


def codex_runner(record: TaskRecord, cancel: threading.Event, progress: Progress) -> RunResult:
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.codex_worker",
        python=os.environ.get("STORYRAIL_CODEX_PYTHON", sys.executable),
        output_name="output.png",
        media_type="image/png",
    )


def agy_runner(record: TaskRecord, cancel: threading.Event, progress: Progress) -> RunResult:
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.agy_worker",
        python=sys.executable,
        output_name="output.png",
        media_type="image/png",
    )


def ffmpeg_final_assembly_runner(
    record: TaskRecord, cancel: threading.Event, progress: Progress
) -> RunResult:
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.ffmpeg_final_assembly_worker",
        python=sys.executable,
        output_name="output.mp4",
        media_type="video/mp4",
    )


def ffmpeg_animatic_runner(
    record: TaskRecord, cancel: threading.Event, progress: Progress
) -> RunResult:
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.ffmpeg_animatic_worker",
        python=sys.executable,
        output_name="output.mp4",
        media_type="video/mp4",
    )


def demucs_audio_separation_runner(
    record: TaskRecord, cancel: threading.Event, progress: Progress
) -> RunResult:
    repository_runtime = Path(__file__).resolve().parents[1] / ".demucs-venv" / "bin" / "python"
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.demucs_audio_worker",
        python=os.environ.get("STORYRAIL_DEMUCS_PYTHON")
        or (str(repository_runtime) if repository_runtime.is_file() else sys.executable),
        output_name="output.wav",
        media_type="audio/wav",
    )


def ffmpeg_audio_remix_runner(
    record: TaskRecord, cancel: threading.Event, progress: Progress
) -> RunResult:
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.ffmpeg_audio_remix_worker",
        python=sys.executable,
        output_name="output.mp4",
        media_type="video/mp4",
    )


def create_h3_fl2va_comfy_core_runner(runtime_root: Path) -> ResidentProcessRunner:
    """建立无 HTTP/UI 的固定 Comfy Core FL2VA 子进程。"""

    return _create_h3_comfy_core_runner(runtime_root, mode="fl2va")


def create_h3_ref2va_comfy_core_runner(runtime_root: Path) -> ResidentProcessRunner:
    """建立无 HTTP/UI 的固定 Comfy Core Ref2VA 子进程。"""

    return _create_h3_comfy_core_runner(runtime_root, mode="ref2va")


def create_qwen_image_comfy_core_runner(runtime_root: Path) -> ResidentProcessRunner:
    """建立无 HTTP/UI 的固定 Comfy Core Qwen Image 子进程；相邻图片任务复用。"""

    return _create_comfy_core_runner(
        runtime_root,
        mode="qwen_image",
        name="Qwen Image Comfy Core",
        stderr_name="qwen-image-comfy-core.stderr.log",
        output_name="output.png",
        media_type="image/png",
    )


def _create_h3_comfy_core_runner(runtime_root: Path, *, mode: str) -> ResidentProcessRunner:
    if mode not in {"fl2va", "ref2va"}:
        raise ValueError("Comfy Core H3 mode 不受支持。")
    return _create_comfy_core_runner(
        runtime_root,
        mode=mode,
        name=f"MiniMax H3 {mode.upper()} Comfy Core",
        stderr_name=f"minimax-h3-{mode}-comfy-core.stderr.log",
        output_name="output.mp4",
        media_type="video/mp4",
    )


def _create_comfy_core_runner(
    runtime_root: Path,
    *,
    mode: str,
    name: str,
    stderr_name: str,
    output_name: str,
    media_type: str,
) -> ResidentProcessRunner:
    def comfy_root() -> str:
        value = os.environ.get("STORYRAIL_COMFYUI_ROOT")
        if not value:
            raise RuntimeError("未配置 STORYRAIL_COMFYUI_ROOT。")
        return value

    def environment() -> dict[str, str]:
        value = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[1])
        value["PYTHONPATH"] = (
            f"{package_root}{os.pathsep}{value['PYTHONPATH']}"
            if value.get("PYTHONPATH")
            else package_root
        )
        value["PYTHONUTF8"] = "1"
        value["PYTHONIOENCODING"] = "utf-8"
        value["STORYRAIL_COMFY_CORE_MODE"] = mode
        # 工作区目录名沿用已部署的 h3-<mode>-comfy-core。
        work = f"h3-{mode}-comfy-core" if mode in {"fl2va", "ref2va"} else f"{mode}-comfy-core"
        value["STORYRAIL_COMFY_CORE_WORK_ROOT"] = str((runtime_root / work).resolve())
        # SageAttention 的 Triton kernel 缓存固定在服务状态目录，两种 mode 共用。
        value["TRITON_CACHE_DIR"] = str((runtime_root / "triton-cache").resolve())
        return value

    def command() -> list[str]:
        return [
            os.environ.get("STORYRAIL_H3_PYTHON", sys.executable),
            "-m",
            "default_model_providers_implement.comfy_core.worker",
            "--serve",
        ]

    return ResidentProcessRunner(
        name=name,
        command_factory=command,
        stderr_path=runtime_root / stderr_name,
        output_name=output_name,
        media_type=media_type,
        cwd_factory=comfy_root,
        environment_factory=environment,
        startup_retry_exit_codes=frozenset({3221225477, -1073741819}),
        recycle_after_run=False,
    )


def create_indextts2_resident_runner(runtime_root: Path) -> ResidentProcessRunner:
    """按需加载独立 WSL runtime，服从 exclusive_gpu 的切换与取消。"""
    wsl = os.environ.get("STORYRAIL_WSL_EXE", r"C:\Windows\System32\wsl.exe")
    distribution = os.environ.get("STORYRAIL_WSL_DISTRIBUTION", "Ubuntu")

    def command() -> list[str]:
        if os.name != "nt":
            raise RuntimeError("默认 IndexTTS2.5 runtime 只能从 Windows 调用 WSL。")
        root = Path(os.environ.get("STORYRAIL_INDEXTTS2_ROOT", r"E:\Project\index-tts"))
        model = Path(os.environ.get("STORYRAIL_INDEXTTS2_MODEL_ROOT", str(root / "checkpoints")))
        python = os.environ.get("STORYRAIL_INDEXTTS2_PYTHON", _wsl_path(root / ".venv/bin/python"))
        return [
            wsl,
            "--distribution",
            distribution,
            "--cd",
            _wsl_path(root),
            "--exec",
            "env",
            "HF_HUB_OFFLINE=1",
            "TRANSFORMERS_OFFLINE=1",
            "HF_HUB_DISABLE_TELEMETRY=1",
            python,
            _wsl_path(Path(__file__).with_name("indextts2_worker.py")),
            "--serve",
            "--model-root",
            _wsl_path(model),
        ]

    def terminate_runtime(pid: int) -> None:
        subprocess.run(
            [wsl, "-d", distribution, "--exec", "/bin/kill", "-TERM", "--", str(pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    return ResidentProcessRunner(
        name="IndexTTS2.5",
        command_factory=command,
        stderr_path=runtime_root / "indextts2.stderr.log",
        output_name="output.wav",
        media_type="audio/wav",
        request_path=_wsl_path,
        terminate_runtime=terminate_runtime,
    )


def create_breeze_resident_runner(runtime_root: Path) -> ResidentProcessRunner:
    """Create a lightweight supervisor; Breeze's large WSL process is lazy."""

    def command() -> list[str]:
        if os.name != "nt":
            raise RuntimeError("默认 Breeze TTS 2 runtime 只能从 Windows 调用 WSL。")
        script = Path(__file__).with_name("breeze_tts2_worker.py").resolve()
        return [
            os.environ.get("STORYRAIL_BREEZE_PYTHON_HOST", sys.executable),
            str(script),
            "--serve",
        ]

    def environment() -> dict[str, str]:
        value = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[1])
        value["PYTHONPATH"] = (
            f"{package_root}{os.pathsep}{value['PYTHONPATH']}"
            if value.get("PYTHONPATH")
            else package_root
        )
        value["PYTHONUTF8"] = "1"
        value["PYTHONIOENCODING"] = "utf-8"
        value.setdefault("STORYRAIL_BREEZE_API_LOG", str(runtime_root / "breeze-api.log"))
        return value

    def terminate_runtime(_pid: int) -> None:
        if os.name != "nt":
            return
        wsl = os.environ.get("STORYRAIL_WSL_EXE", r"C:\Windows\System32\wsl.exe")
        distribution = os.environ.get("STORYRAIL_WSL_DISTRIBUTION", "Ubuntu")
        port = os.environ.get("STORYRAIL_BREEZE_PORT", "7860")
        model = os.environ.get("STORYRAIL_BREEZE_MODEL", "/home/ljx/ai/models/Breeze-TTS-2")
        subprocess.run(
            [
                wsl,
                "--distribution",
                distribution,
                "--exec",
                "/bin/pkill",
                "-TERM",
                "-f",
                breeze_process_pattern(model, port),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    return ResidentProcessRunner(
        name="Breeze TTS 2",
        command_factory=command,
        stderr_path=runtime_root / "breeze-tts2.stderr.log",
        output_name="output.wav",
        media_type="audio/wav",
        terminate_runtime=terminate_runtime,
        environment_factory=environment,
        startup_timeout=30.0,
    )


def create_seedvr2_resident_runner(runtime_root: Path) -> ResidentProcessRunner:
    def python_path() -> str:
        return os.environ.get(
            "STORYRAIL_SEEDVR2_PYTHON",
            r"E:\Programs\Dev\MiniForge3\envs\storyrail-seedvr2\python.exe",
        )

    def root() -> str:
        value = os.environ.get("STORYRAIL_SEEDVR2_ROOT", r"E:\Project\seedvr2")
        return str(Path(value).resolve())

    def command() -> list[str]:
        script = Path(__file__).with_name("seedvr2_worker.py").resolve()
        model_root = os.environ.get(
            "STORYRAIL_SEEDVR2_MODEL_ROOT", r"E:\Project\seedvr2\models\SEEDVR2"
        )
        return [
            python_path(),
            str(script),
            "--serve",
            "--repository-root",
            root(),
            "--model-root",
            model_root,
        ]

    def environment() -> dict[str, str]:
        value = os.environ.copy()
        environment_root = Path(python_path()).resolve().parent
        executable_paths = (
            environment_root,
            environment_root / "Scripts",
            environment_root / "Library" / "bin",
        )
        value["PATH"] = os.pathsep.join([*(str(item) for item in executable_paths), value["PATH"]])
        value["PYTHONUTF8"] = "1"
        value["PYTHONIOENCODING"] = "utf-8"
        return value

    return ResidentProcessRunner(
        name="SeedVR2 7B Sharp FP8",
        command_factory=command,
        stderr_path=runtime_root / "seedvr2-7b-sharp-fp8.stderr.log",
        output_name="output.mp4",
        media_type="video/mp4",
        cwd_factory=root,
        environment_factory=environment,
        startup_timeout=180.0,
    )


def _wsl_path(path: Path) -> str:
    text = str(path.resolve())
    if len(text) >= 3 and text[1] == ":":
        return f"/mnt/{text[0].lower()}{text[2:].replace(chr(92), '/')}"
    return text.replace(chr(92), "/")


def stable_audio_3_runner(
    record: TaskRecord, cancel: threading.Event, progress: Progress
) -> RunResult:
    if os.name != "nt":
        raise RuntimeError("Stable Audio 3 只在 Windows 模型服务里通过 WSL 执行。")
    python = os.environ.get(
        "STORYRAIL_STABLE_AUDIO_PYTHON",
        "/home/ljx/ai/stable-audio-3/.venv/bin/python",
    )
    pythonpath = os.environ.get(
        "STORYRAIL_STABLE_AUDIO_PYTHONPATH",
        "/mnt/e/Project/StoryRail",
    )
    distro = os.environ.get("STORYRAIL_WSL_DISTRIBUTION", "Ubuntu")
    request_file = _wsl_path(Path(record.task_dir) / "request.json")
    command = [
        "wsl.exe",
        "-d",
        distro,
        "--exec",
        "env",
        "HF_HUB_OFFLINE=1",
        "TRANSFORMERS_OFFLINE=1",
        "HF_HUB_DISABLE_TELEMETRY=1",
        f"PYTHONPATH={pythonpath}",
        python,
        "-m",
        "default_model_providers_implement.stable_audio_3_worker",
        "--request-file",
        request_file,
    ]
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.stable_audio_3_worker",
        python=python,
        output_name="output.wav",
        media_type="audio/wav",
        command=command,
    )


def _module_runner(
    record: TaskRecord,
    cancel: threading.Event,
    progress: Progress,
    *,
    module: str,
    python: str,
    output_name: str,
    media_type: str,
    command: list[str] | None = None,
) -> RunResult:
    task_dir = Path(record.task_dir)
    if command is None:
        command = [python, "-m", module, "--request-file", str(task_dir / "request.json")]
    environment = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = f"{package_root}{os.pathsep}{environment.get('PYTHONPATH', '')}"
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=(task_dir / "runtime.stderr.log").open("wb"),
        text=True,
        encoding="utf-8-sig",
        env=environment,
        start_new_session=os.name != "nt",
    )
    assert process.stdout is not None
    lines, reader = _start_line_reader(process)
    stream_closed = False
    try:
        while process.poll() is None or not stream_closed:
            if cancel.is_set():
                _terminate(process, process_group=os.name != "nt")
                raise CancelledError
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                stream_closed = True
                continue
            event = json.loads(line)
            if event.get("event") == "progress":
                progress(float(event["value"]), str(event["message"]))
            elif event.get("event") == "error":
                raise RuntimeError(str(event.get("message") or "模型 runtime 失败。"))
        output = task_dir / output_name
        if process.returncode != 0 or not output.is_file():
            raise RuntimeError(f"模型 runtime 未产生有效输出，退出码 {process.returncode}。")
        return RunResult(output, media_type)
    finally:
        if process.poll() is None:
            _terminate(process, process_group=os.name != "nt")
        reader.join(timeout=2)


def _terminate(process: subprocess.Popen[str], *, process_group: bool = False) -> None:
    if process_group:
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if process_group:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=10)


def _read_request(task_dir: Path) -> dict[str, Any]:
    value = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("内部 request.json 顶层不合法。")
    return value


def _start_line_reader(
    process: subprocess.Popen[str],
) -> tuple[queue.Queue[str | None], threading.Thread]:
    assert process.stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()

    def read_stdout() -> None:
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_stdout, name="runtime-stdout", daemon=True)
    reader.start()
    return lines, reader


def ffmpeg_video_frame_runner(record, cancel, progress):
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.ffmpeg_video_frame_worker",
        python=sys.executable,
        output_name="output.png",
        media_type="image/png",
    )


def ffmpeg_pano_view_runner(record, cancel, progress):
    return _module_runner(
        record,
        cancel,
        progress,
        module="default_model_providers_implement.ffmpeg_pano_view_worker",
        python=sys.executable,
        output_name="output.png",
        media_type="image/png",
    )
