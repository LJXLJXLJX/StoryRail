from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .task_store import TERMINAL_STATES, TaskRecord, TaskStore

Progress = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class RunResult:
    artifact_path: Path
    media_type: str
    # 可选的实际生效参数摘要，写在完成消息的用时之前。
    summary: str | None = None


Runner = Callable[[TaskRecord, threading.Event, Progress], RunResult]


@dataclass(frozen=True, slots=True)
class _ReleaseRuntime:
    completed: threading.Event


class ManagedRunner(Protocol):
    """可在相邻同族任务间保留模型，并在资源切换时显式释放。"""

    def __call__(
        self, record: TaskRecord, cancel: threading.Event, progress: Progress
    ) -> RunResult: ...

    def release(self) -> None: ...


class ExclusiveResourceManager:
    """私有默认实现的资源调度器；Core 不知道它的存在。

    默认仍以单 worker 管理可驻留 runtime。只有全部 runner 都是无驻留状态的
    一次性调用时，才允许显式开启多个 worker。
    """

    def __init__(
        self,
        store: TaskStore,
        runners: dict[str, Runner],
        *,
        resource_name: str = "exclusive_gpu",
        initially_accepting: bool = True,
        max_concurrent_tasks: int = 1,
    ) -> None:
        if not 1 <= max_concurrent_tasks <= 8:
            raise ValueError("并发任务数必须在 1 到 8 之间。")
        if max_concurrent_tasks > 1 and any(
            callable(getattr(runner, "release", None)) for runner in runners.values()
        ):
            raise ValueError("常驻 runtime 只能使用单 worker 互斥调度。")
        self.store = store
        self._runners = dict(runners)
        self._resource_name = resource_name
        self._queue: queue.Queue[str | _ReleaseRuntime | None] = queue.Queue()
        self._stop = threading.Event()
        self._state_lock = threading.RLock()
        self._accepting = initially_accepting
        self._acceptance_epoch = 0
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_details: dict[str, tuple[str, str | None]] = {}
        # 还没被 worker 取走的 task_id，按入队顺序排列；由 _state_lock 保护。
        self._pending: list[str] = []
        self._active_runner: Runner | ManagedRunner | None = None
        self._max_concurrent_tasks = max_concurrent_tasks
        self._threads = tuple(
            threading.Thread(
                target=self._work,
                name=f"{resource_name}-worker-{index + 1}",
                daemon=True,
            )
            for index in range(max_concurrent_tasks)
        )

    def start(self) -> None:
        for thread in self._threads:
            thread.start()
        with self._state_lock:
            if self._accepting:
                self._enqueue_recoverable()

    def activate(self) -> None:
        """允许受控调用；用于私有部署的 Core 租约，不属于 Provider contract。"""

        with self._state_lock:
            if self._stop.is_set():
                raise RuntimeError("资源调度器已经停止。")
            if self._accepting:
                return
            self._accepting = True
            self._enqueue_recoverable()

    def revoke(
        self,
        *,
        message: str,
        error_code: str,
    ) -> threading.Event:
        """停止接收任务、取消未完成调用，并在调度线程内释放驻留 runtime。"""

        completed = threading.Event()
        with self._state_lock:
            self._accepting = False
            self._acceptance_epoch += 1
            records = [
                record for record in self.store.list_recoverable() if record.kind in self._runners
            ]
            for record in records:
                self._cancel_locked(record.task_id, message=message, error_code=error_code)
            self._queue.put(_ReleaseRuntime(completed))
        return completed

    def submit(self, kind: str, prepare: Callable[[TaskRecord], None]) -> TaskRecord:
        if kind not in self._runners:
            raise ValueError(f"没有为 {kind} 注册 runtime。")
        with self._state_lock:
            if not self._accepting:
                raise ResourceLeaseRequiredError("Mac Core 资源租约尚未建立。")
            acceptance_epoch = self._acceptance_epoch
            record = self.store.create(kind)
        self.store.update(record.task_id, message=f"等待 {self._resource_name}。")
        try:
            prepare(record)
        except Exception:
            self.store.update(
                record.task_id,
                state="failed",
                message="写入受控任务输入失败。",
                error_code="prepare_failed",
            )
            raise
        with self._state_lock:
            if not self._accepting or acceptance_epoch != self._acceptance_epoch:
                self._cancel_locked(
                    record.task_id,
                    message="Mac Core 资源租约已失效，任务没有进入执行队列。",
                    error_code="controller_lease_expired",
                )
                raise ResourceLeaseRequiredError("Mac Core 资源租约已失效。")
            self._queue.put(record.task_id)
            self._pending.append(record.task_id)
        return record

    def cancel(
        self,
        task_id: str,
        *,
        message: str = "模型调用已取消。",
        error_code: str | None = None,
    ) -> TaskRecord | None:
        record = self.store.get(task_id)
        if record is None:
            return None
        with self._state_lock:
            return self._cancel_locked(task_id, message=message, error_code=error_code)

    def shutdown(self, timeout: float = 15.0) -> None:
        self._stop.set()
        with self._state_lock:
            for event in self._cancel_events.values():
                event.set()
        for _thread in self._threads:
            self._queue.put(None)
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        # 运行线程负责取消正在执行的外部调用；不能从这里并发操作同一个 stdin。
        if not any(thread.is_alive() for thread in self._threads):
            self._release_active_runner()

    def _work(self) -> None:
        while not self._stop.is_set():
            command = self._queue.get()
            if command is None:
                return
            if isinstance(command, _ReleaseRuntime):
                try:
                    self._release_active_runner()
                finally:
                    command.completed.set()
                continue
            task_id = command
            with self._state_lock:
                if task_id in self._pending:
                    self._pending.remove(task_id)
            record = self.store.get(task_id)
            if record is None or record.state in TERMINAL_STATES:
                continue
            runner = self._runners.get(record.kind)
            if runner is None:
                self.store.update(
                    task_id,
                    state="failed",
                    message="Runtime 未注册。",
                    error_code="runtime_missing",
                )
                continue
            cancel_event = threading.Event()
            with self._state_lock:
                self._cancel_events[task_id] = cancel_event
            if record.cancel_requested:
                cancel_event.set()

            def progress(value: float, message: str, current_task_id: str = task_id) -> None:
                self.store.update(
                    current_task_id,
                    progress=max(0.0, min(0.99, value)),
                    message=message,
                )

            started_at = time.monotonic()
            self.store.update(
                task_id,
                state="running",
                progress=0.01,
                message=f"已取得 {self._resource_name}。",
            )
            try:
                if self._max_concurrent_tasks == 1:
                    self._select_runner(runner, task_id)
                result = runner(record, cancel_event, progress)
                if cancel_event.is_set():
                    self._finish_cancelled(task_id)
                    continue
                path = result.artifact_path.resolve()
                root = Path(record.task_dir).resolve()
                path.relative_to(root)
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                        digest.update(chunk)
                with self._state_lock:
                    if cancel_event.is_set():
                        self._finish_cancelled(task_id)
                    else:
                        self.store.update(
                            task_id,
                            state="succeeded",
                            progress=1.0,
                            message=(
                                (f"{result.summary}；" if result.summary else "")
                                + f"生成总用时 {max(0.0, time.monotonic() - started_at):.1f} 秒"
                                "（含模型准备、采样及产物处理，不含排队）。"
                            ),
                            artifact_name=str(path.relative_to(root)),
                            artifact_media_type=result.media_type,
                            artifact_size=path.stat().st_size,
                            artifact_sha256=digest.hexdigest(),
                        )
            except CancelledError:
                self._finish_cancelled(task_id)
            except Exception as exc:
                self.store.update(
                    task_id,
                    state="failed",
                    message=str(exc)[:1000] or "模型调用失败。",
                    error_code=type(exc).__name__,
                    retryable=isinstance(exc, RetryableRuntimeError),
                )
            finally:
                with self._state_lock:
                    self._cancel_events.pop(task_id, None)
                    self._cancel_details.pop(task_id, None)

    def _enqueue_recoverable(self) -> None:
        for record in self.store.list_recoverable():
            if record.kind in self._runners and record.state == "queued":
                self._queue.put(record.task_id)
                self._pending.append(record.task_id)

    def queue_index(self, task_id: str) -> int | None:
        """返回该任务前面还有几个尚未被 worker 取走的任务；不在队列中时返回 None。"""

        with self._state_lock:
            try:
                return self._pending.index(task_id)
            except ValueError:
                return None

    def _cancel_locked(
        self,
        task_id: str,
        *,
        message: str,
        error_code: str | None,
    ) -> TaskRecord:
        self._cancel_details[task_id] = (message, error_code)
        if task_id in self._pending:
            self._pending.remove(task_id)
        updated = self.store.request_cancel(
            task_id,
            message=message,
            error_code=error_code,
        )
        event = self._cancel_events.get(task_id)
        if event:
            event.set()
        if updated.state in TERMINAL_STATES:
            self._cancel_details.pop(task_id, None)
        return updated

    def _finish_cancelled(self, task_id: str) -> None:
        with self._state_lock:
            message, error_code = self._cancel_details.get(task_id, ("模型调用已取消。", None))
        self.store.update(
            task_id,
            state="cancelled",
            message=message,
            error_code=error_code,
            retryable=False,
        )

    def _select_runner(self, runner: Runner | ManagedRunner, task_id: str) -> None:
        if self._active_runner is runner:
            return
        if self._active_runner is not None:
            self.store.update(
                task_id,
                message=f"正在释放上一项 {self._resource_name} runtime。",
            )
            self._release_active_runner()
        self._active_runner = runner

    def _release_active_runner(self) -> None:
        runner, self._active_runner = self._active_runner, None
        if runner is None:
            return
        release = getattr(runner, "release", None)
        if callable(release):
            release()
            _wait_for_gpu_release()


class CancelledError(RuntimeError):
    pass


class RetryableRuntimeError(RuntimeError):
    pass


class ResourceLeaseRequiredError(RuntimeError):
    pass


def _wait_for_gpu_release() -> None:
    # 驻留 runtime 退出后短暂等待驱动完成异步清理，再启动另一模型族。
    time.sleep(0.25)
