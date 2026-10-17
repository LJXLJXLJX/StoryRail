"""进程内多 lane 调度：按 service kind 把任务路由到各自的资源管理器。

私有部署细节：lane 只是同一个 HTTP 服务进程内的调度分组，不是 Core 协议的一部分。
lane 内部沿用 `ExclusiveResourceManager` 的 FIFO 与并发上限，lane 之间互不等待。
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .resource_manager import ExclusiveResourceManager, Runner
from .task_store import TaskRecord, TaskStore

LANE_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
REVOKE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class LaneSpec:
    """一个调度 lane 的静态定义；服务集合在 lane 之间必须互不相交。"""

    name: str
    services: frozenset[str]
    max_concurrent_tasks: int

    def __post_init__(self) -> None:
        if LANE_NAME.fullmatch(self.name) is None:
            raise ValueError(
                "lane 名必须匹配 [a-z][a-z0-9_]{0,39}：小写字母开头，"
                "只包含小写字母、数字和下划线，长度不超过 40。"
            )
        if not self.services:
            raise ValueError("lane 至少要包含一个服务。")
        if not 1 <= self.max_concurrent_tasks <= 8:
            raise ValueError("并发任务数必须在 1 到 8 之间。")


class LaneDispatcher:
    """按 service kind 把任务路由到各自的 ExclusiveResourceManager；lane 之间互不等待。"""

    def __init__(
        self,
        store: TaskStore,
        runners: dict[str, Runner],
        lanes: tuple[LaneSpec, ...],
        *,
        initially_accepting: bool,
    ) -> None:
        self.store = store
        self.lanes = tuple(lanes)
        names: set[str] = set()
        claimed: set[str] = set()
        for lane in self.lanes:
            if lane.name in names:
                raise ValueError(f"lane 名不能重复：{lane.name}。")
            names.add(lane.name)
            overlap = claimed & set(lane.services)
            if overlap:
                raise ValueError("服务不能同时属于多个 lane：" + "、".join(sorted(overlap)) + "。")
            claimed |= set(lane.services)
        if claimed != set(runners):
            details: list[str] = []
            missing = sorted(set(runners) - claimed)
            if missing:
                details.append("没有分配 lane：" + "、".join(missing))
            unknown = sorted(claimed - set(runners))
            if unknown:
                details.append("没有注册 runtime：" + "、".join(unknown))
            raise ValueError("lane 的服务并集必须等于全部注册服务（" + "；".join(details) + "）。")

        self.managers = tuple(
            ExclusiveResourceManager(
                store,
                {kind: runners[kind] for kind in lane.services},
                resource_name=lane.name,
                initially_accepting=initially_accepting,
                max_concurrent_tasks=lane.max_concurrent_tasks,
            )
            for lane in self.lanes
        )
        self._managers_by_kind: dict[str, ExclusiveResourceManager] = {
            kind: manager
            for lane, manager in zip(self.lanes, self.managers, strict=True)
            for kind in lane.services
        }

    def start(self) -> None:
        for manager in self.managers:
            manager.start()

    def activate(self) -> None:
        for manager in self.managers:
            manager.activate()

    def revoke(self, *, message: str, error_code: str) -> threading.Event:
        """撤销所有 lane；返回的 Event 在全部 lane 完成后才 set（最多等 30 秒）。"""

        completed = threading.Event()
        pending = [
            manager.revoke(message=message, error_code=error_code) for manager in self.managers
        ]

        def _wait_for_all() -> None:
            deadline = time.monotonic() + REVOKE_TIMEOUT_SECONDS
            for event in pending:
                event.wait(max(0.0, deadline - time.monotonic()))
            completed.set()

        threading.Thread(
            target=_wait_for_all,
            name="lane-dispatcher-revoke",
            daemon=True,
        ).start()
        return completed

    def submit(self, kind: str, prepare: Callable[[TaskRecord], None]) -> TaskRecord:
        manager = self._managers_by_kind.get(kind)
        if manager is None:
            raise ValueError(f"没有为 {kind} 注册 runtime。")
        return manager.submit(kind, prepare)

    def cancel(self, task_id: str, **kwargs: object) -> TaskRecord | None:
        record = self.store.get(task_id)
        if record is None:
            return None
        manager = self._managers_by_kind.get(record.kind)
        if manager is None:
            return None
        return manager.cancel(task_id, **kwargs)

    def shutdown(self, timeout: float = 15.0) -> None:
        for manager in self.managers:
            manager.shutdown(timeout)

    def queue_message(self, record: TaskRecord) -> str | None:
        """排队任务的进度提示；不是 Core 协议字段，只是状态响应里的 message 文本。"""

        if record.state != "queued":
            return None
        manager = self._managers_by_kind.get(record.kind)
        if manager is None:
            return None
        index = manager.queue_index(record.task_id)
        if index is None:
            return None
        if index == 0:
            return "排队中：即将开始。"
        return f"排队中：前面还有 {index} 个任务。"
