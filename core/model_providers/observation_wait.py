"""项目 generation.wait 与 Playground wait_runs 共用的有界观察。

一轮观察可能卡在 Provider 读取或大文件 Artifact 导入上；等待方必须在 MCP bridge 的 HTTP
超时前返回。未在截止时间内完成的刷新转入后台继续，下一次等待复用同一任务，不重复观察。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable

# 默认 15 秒加单轮至少 1 秒的宽限，仍在 bridge 20 秒 HTTP 超时之前返回。
_DEFAULT_MAX_WAIT_SECONDS = "15"
_MIN_ROUND_SECONDS = 1.0


def wait_budget() -> tuple[float, float]:
    """(最长等待秒数, 轮询间隔)；项目与 Playground 共用同样的两个环境变量。"""
    max_wait = max(
        0.0,
        float(os.environ.get("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", _DEFAULT_MAX_WAIT_SECONDS)),
    )
    poll_seconds = max(0.01, float(os.environ.get("STORYRAIL_GENERATION_WAIT_POLL_SECONDS", "2")))
    return max_wait, poll_seconds


class BoundedObserver:
    """按截止时间等待一轮刷新；超时的刷新留在后台，结果照常落盘。"""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Task[object]] = {}

    async def refresh(
        self,
        ids: Iterable[str],
        refresh: Callable[[str], Awaitable[object]],
        deadline: float,
    ) -> bool:
        """本轮全部刷新在截止前完成时返回 True；已完成刷新的异常照常抛出。"""
        loop = asyncio.get_running_loop()
        tasks = [self._task(item, refresh) for item in ids]
        timeout = max(deadline - loop.time(), _MIN_ROUND_SECONDS)
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in tasks:
            if task in done:
                task.result()
        return not pending

    def _task(self, key: str, refresh: Callable[[str], Awaitable[object]]) -> asyncio.Task[object]:
        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.ensure_future(refresh(key))
            self._inflight[key] = task
            task.add_done_callback(lambda done: self._finished(key, done))
        return task

    def _finished(self, key: str, task: asyncio.Task[object]) -> None:
        if self._inflight.get(key) is task:
            del self._inflight[key]
        # 后台刷新的失败已写入 Generation/run 状态或由下一次等待重新观察；这里只取走异常。
        if not task.cancelled():
            task.exception()
