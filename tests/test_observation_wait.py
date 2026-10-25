"""有界观察：慢刷新不拖过截止时间，后台继续并被下一次等待复用。"""

import asyncio

import pytest

from core.model_providers.observation_wait import BoundedObserver


def test_slow_refresh_returns_at_deadline_and_is_reused_in_background():
    async def run():
        observer = BoundedObserver()
        release = asyncio.Event()
        calls = []
        finished = []

        async def refresh(key):
            calls.append(key)
            await release.wait()
            finished.append(key)

        loop = asyncio.get_running_loop()
        started = loop.time()
        assert not await observer.refresh(("a",), refresh, started + 0.05)
        # 首轮至少等待 1 秒宽限，但不会无界等待慢刷新。
        assert loop.time() - started < 1.5
        assert finished == []
        assert not await observer.refresh(("a",), refresh, loop.time())
        assert calls == ["a"]
        release.set()
        assert await observer.refresh(("a",), refresh, loop.time() + 1)
        assert calls == ["a"] and finished == ["a"]
        # 已完成的刷新不再复用，下一轮重新观察。
        assert await observer.refresh(("a",), refresh, loop.time() + 1)
        assert calls == ["a", "a"]

    asyncio.run(run())


def test_completed_refresh_errors_propagate():
    async def run():
        async def refresh(_key):
            raise RuntimeError("暂时无法读取模型任务状态")

        with pytest.raises(RuntimeError, match="暂时无法读取"):
            await BoundedObserver().refresh(("a",), refresh, asyncio.get_running_loop().time() + 1)

    asyncio.run(run())
