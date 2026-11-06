"""进程内的本机媒体任务执行器：按 lane 排队、可取消、产物留在任务目录直到过期。

任务只存在于当前 Core 进程。Core 重启时清空工作目录；旧句柄观察到的是带
``local_task_lost`` 的失败结果，由用户显式重试（新 Generation 带 ``retry_of``）。
"""

from __future__ import annotations

import hashlib
import queue
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
)

from .ffmpeg import MediaToolCancelled
from .timeline import Progress

Job = Callable[[Path, threading.Event, Progress], Path]

DEFAULT_LANES: Mapping[str, int] = {"heavy": 1, "light": 1}
_RETENTION_SECONDS = 24 * 3600
_TERMINAL = frozenset(
    {GenerationPhase.SUCCEEDED, GenerationPhase.FAILED, GenerationPhase.CANCELLED}
)


@dataclass(slots=True)
class _Task:
    task_id: str
    directory: Path
    job: Job
    media_type: str
    failure_code: str
    duration_probe: Callable[[Path], float] | None
    cancel: threading.Event = field(default_factory=threading.Event)
    phase: GenerationPhase = GenerationPhase.QUEUED
    progress: float = 0.0
    message: str = "排队中。"
    artifact: ArtifactDescriptor | None = None
    output: Path | None = None
    error_code: str | None = None
    finished_at: float | None = None


class LocalMediaExecutor:
    def __init__(
        self,
        root: Path,
        *,
        lanes: Mapping[str, int] = DEFAULT_LANES,
        retention_seconds: float = _RETENTION_SECONDS,
    ) -> None:
        self._root = Path(root)
        if self._root.exists():
            shutil.rmtree(self._root)
        self._root.mkdir(parents=True)
        self._retention_seconds = retention_seconds
        self._lock = threading.Lock()
        self._tasks: dict[str, _Task] = {}
        self._queues: dict[str, queue.Queue[_Task | None]] = {}
        self._threads: list[threading.Thread] = []
        for lane, workers in lanes.items():
            if workers < 1:
                raise ValueError("lane 并发数必须至少为 1。")
            self._queues[lane] = queue.Queue()
            for index in range(workers):
                thread = threading.Thread(
                    target=self._work,
                    args=(self._queues[lane],),
                    name=f"media-tools-{lane}-{index}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)

    def submit(
        self,
        lane: str,
        job: Job,
        *,
        media_type: str,
        failure_code: str,
        duration_probe: Callable[[Path], float] | None = None,
    ) -> str:
        if lane not in self._queues:
            raise ValueError(f"未知 lane：{lane}")
        self._expire()
        task_id = uuid.uuid4().hex
        directory = self._root / task_id
        directory.mkdir()
        task = _Task(task_id, directory, job, media_type, failure_code, duration_probe)
        with self._lock:
            self._tasks[task_id] = task
        self._queues[lane].put(task)
        return task_id

    def observe(self, task_id: str) -> GenerationObservation:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return GenerationObservation(
                    GenerationPhase.FAILED,
                    0.0,
                    "本机媒体任务已不存在（Core 重启或产物已过期），请重新生成。",
                    error_code="local_task_lost",
                    retryable=True,
                )
            return GenerationObservation(
                task.phase,
                task.progress,
                task.message,
                task.artifact,
                task.error_code,
                False,
            )

    def cancel(self, task_id: str) -> GenerationObservation:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and task.phase not in _TERMINAL:
                task.cancel.set()
                if task.phase is GenerationPhase.QUEUED:
                    self._finish(task, GenerationPhase.CANCELLED, "已取消。")
        return self.observe(task_id)

    def read_artifact(self, task_id: str, artifact_id: str) -> bytes:
        with self._lock:
            task = self._tasks.get(task_id)
            output = None if task is None or artifact_id != task_id else task.output
        if output is None or not output.is_file():
            raise ModelProviderError("artifact_unavailable", "本机媒体产物不可用。")
        return output.read_bytes()

    def close(self) -> None:
        with self._lock:
            for task in self._tasks.values():
                task.cancel.set()
        for lane_queue in self._queues.values():
            for _ in range(len(self._threads)):
                lane_queue.put(None)

    # ------------------------------------------------------------ 内部

    def _work(self, lane_queue: queue.Queue[_Task | None]) -> None:
        while True:
            task = lane_queue.get()
            if task is None:
                return
            with self._lock:
                if task.phase is not GenerationPhase.QUEUED:
                    continue
                task.phase = GenerationPhase.RUNNING
                task.message = "处理中。"

            def progress(value: float, message: str, task: _Task = task) -> None:
                with self._lock:
                    if task.phase is GenerationPhase.RUNNING:
                        task.progress = max(task.progress, min(1.0, max(0.0, value)))
                        task.message = message

            try:
                output = task.job(task.directory, task.cancel, progress)
                if task.cancel.is_set():
                    raise MediaToolCancelled
                artifact = self._describe(task, output)
            except MediaToolCancelled:
                with self._lock:
                    self._finish(task, GenerationPhase.CANCELLED, "已取消。")
            except Exception as exc:
                with self._lock:
                    if task.cancel.is_set():
                        self._finish(task, GenerationPhase.CANCELLED, "已取消。")
                    else:
                        detail = f"{type(exc).__name__}: {exc}"[-1_500:]
                        task.error_code = task.failure_code
                        self._finish(task, GenerationPhase.FAILED, detail)
            else:
                with self._lock:
                    task.output = output
                    task.artifact = artifact
                    task.progress = 1.0
                    self._finish(task, GenerationPhase.SUCCEEDED, "已完成。")

    def _describe(self, task: _Task, output: Path) -> ArtifactDescriptor:
        output = output.resolve(strict=True)
        output.relative_to(task.directory.resolve(strict=True))
        content = output.read_bytes()
        if not content:
            raise RuntimeError("媒体工具没有产生有效输出。")
        return ArtifactDescriptor(
            task.task_id,
            task.media_type,
            len(content),
            hashlib.sha256(content).hexdigest(),
            None if task.duration_probe is None else task.duration_probe(output),
        )

    def _finish(self, task: _Task, phase: GenerationPhase, message: str) -> None:
        task.phase = phase
        task.message = message
        task.finished_at = time.monotonic()

    def _expire(self) -> None:
        deadline = time.monotonic() - self._retention_seconds
        with self._lock:
            expired = [
                task
                for task in self._tasks.values()
                if task.finished_at is not None and task.finished_at < deadline
            ]
            for task in expired:
                del self._tasks[task.task_id]
        for task in expired:
            shutil.rmtree(task.directory, ignore_errors=True)
