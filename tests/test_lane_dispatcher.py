"""PG0：进程内多 lane 调度与排队位置提示。

沿用 `tests/test_resource_manager.py` 的风格：unittest、临时目录、轮询等待状态。
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from default_model_providers_implement.lane_dispatcher import LaneDispatcher, LaneSpec
from default_model_providers_implement.resource_manager import RunResult
from default_model_providers_implement.task_store import TaskStore


def _store_result(record) -> RunResult:
    output = Path(record.task_dir) / "output.bin"
    output.write_bytes(record.task_id.encode())
    return RunResult(output, "application/octet-stream")


def _plain_runner(record, _cancel, _progress) -> RunResult:
    return _store_result(record)


class _ResidentRunner:
    """带 release() 的常驻 runner；并发大于 1 的 lane 必须拒绝它。"""

    def __call__(self, record, _cancel, _progress) -> RunResult:
        return _store_result(record)

    def release(self) -> None:
        pass


class LaneDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _wait_until(self, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "等待任务状态超时。")
            time.sleep(0.01)

    def _two_lane_dispatcher(self, runners: dict[str, object]) -> LaneDispatcher:
        return LaneDispatcher(
            self.store,
            runners,
            (
                LaneSpec("lane_a", frozenset({"lane_a_task"}), 1),
                LaneSpec("lane_b", frozenset({"lane_b_task"}), 1),
            ),
            initially_accepting=True,
        )

    def test_tasks_in_different_lanes_do_not_wait_for_each_other(self) -> None:
        gate = threading.Event()

        def blocked(record, _cancel, _progress) -> RunResult:
            gate.wait(10)
            return _store_result(record)

        dispatcher = self._two_lane_dispatcher(
            {"lane_a_task": blocked, "lane_b_task": _plain_runner}
        )
        dispatcher.start()
        try:
            blocked_task = dispatcher.submit("lane_a_task", lambda _record: None)
            free_task = dispatcher.submit("lane_b_task", lambda _record: None)
            # lane B 不等待 lane A 放行。
            self._wait_until(lambda: self.store.get(free_task.task_id).state == "succeeded")
            self.assertIn(self.store.get(blocked_task.task_id).state, {"queued", "running"})
            gate.set()
            self._wait_until(lambda: self.store.get(blocked_task.task_id).state == "succeeded")
        finally:
            gate.set()
            dispatcher.shutdown()

    def test_same_lane_runs_fifo_with_single_worker(self) -> None:
        started: list[str] = []
        lock = threading.Lock()

        def runner(record, _cancel, _progress) -> RunResult:
            with lock:
                started.append(record.task_id)
            time.sleep(0.01)
            return _store_result(record)

        dispatcher = LaneDispatcher(
            self.store,
            {"task": runner},
            (LaneSpec("lane", frozenset({"task"}), 1),),
            initially_accepting=True,
        )
        dispatcher.start()
        try:
            records = [dispatcher.submit("task", lambda _record: None) for _ in range(3)]
            self._wait_until(
                lambda: all(self.store.get(item.task_id).state == "succeeded" for item in records)
            )
            self.assertEqual(started, [item.task_id for item in records])
        finally:
            dispatcher.shutdown()

    def test_multi_worker_lane_starts_in_submission_order(self) -> None:
        condition = threading.Condition()
        submission: dict[str, int] = {}
        started: list[str] = []
        registered: set[str] = set()
        first_two_running = threading.Event()
        proceed = threading.Event()

        def runner(record, _cancel, _progress) -> RunResult:
            index = submission[record.task_id]
            with condition:
                # 并发启动的登记顺序本身有竞争；这里按提交序放行登记，
                # 让「开始顺序」成为可观察、可断言的事实。
                while any(
                    other not in registered
                    for other, position in submission.items()
                    if position < index
                ):
                    condition.wait(5)
                started.append(record.task_id)
                registered.add(record.task_id)
                if len(started) == 2:
                    first_two_running.set()
                condition.notify_all()
            if index < 2:
                # 前两个任务必须同时在跑，第三个只能等其中一个让出 worker。
                proceed.wait(10)
            return _store_result(record)

        dispatcher = LaneDispatcher(
            self.store,
            {"task": runner},
            (LaneSpec("lane", frozenset({"task"}), 2),),
            initially_accepting=True,
        )
        dispatcher.start()
        try:
            records = []
            for position in range(4):

                def prepare(record, position: int = position) -> None:
                    with condition:
                        submission[record.task_id] = position

                records.append(dispatcher.submit("task", prepare))
            self.assertTrue(first_two_running.wait(5))
            self.assertEqual(len(started), 2)
            self.assertEqual(set(started), {records[0].task_id, records[1].task_id})
            self.assertEqual(self.store.get(records[2].task_id).state, "queued")
            self.assertEqual(self.store.get(records[3].task_id).state, "queued")
            proceed.set()
            self._wait_until(
                lambda: all(self.store.get(item.task_id).state == "succeeded" for item in records)
            )
            self.assertEqual(started, [item.task_id for item in records])
        finally:
            proceed.set()
            dispatcher.shutdown()

    def test_revoke_only_cancels_tasks_of_each_lane_and_waits_all(self) -> None:
        dispatcher = self._two_lane_dispatcher(
            {"lane_a_task": _plain_runner, "lane_b_task": _plain_runner}
        )
        first = dispatcher.submit("lane_a_task", lambda _record: None)
        second = dispatcher.submit("lane_b_task", lambda _record: None)

        completed = dispatcher.revoke(
            message="Mac Core 心跳超时。",
            error_code="controller_lease_expired",
        )
        self.assertEqual(self.store.get(first.task_id).state, "cancelled")
        self.assertEqual(self.store.get(first.task_id).error_code, "controller_lease_expired")
        self.assertEqual(self.store.get(second.task_id).state, "cancelled")

        dispatcher.start()
        try:
            self.assertTrue(completed.wait(5))
        finally:
            dispatcher.shutdown()

    def test_manager_revoke_ignores_other_lane_records(self) -> None:
        dispatcher = self._two_lane_dispatcher(
            {"lane_a_task": _plain_runner, "lane_b_task": _plain_runner}
        )
        first = dispatcher.submit("lane_a_task", lambda _record: None)
        second = dispatcher.submit("lane_b_task", lambda _record: None)

        dispatcher.managers[0].revoke(
            message="Mac Core 已关闭。",
            error_code="controller_lease_released",
        )
        self.assertEqual(self.store.get(first.task_id).state, "cancelled")
        self.assertEqual(self.store.get(second.task_id).state, "queued")
        self.assertFalse(self.store.get(second.task_id).cancel_requested)

    def test_invalid_lane_layout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            # 服务重叠。
            LaneDispatcher(
                self.store,
                {"a": _plain_runner, "b": _plain_runner},
                (
                    LaneSpec("lane_a", frozenset({"a", "b"}), 1),
                    LaneSpec("lane_b", frozenset({"b"}), 1),
                ),
                initially_accepting=True,
            )
        with self.assertRaises(ValueError):
            # 服务缺失。
            LaneDispatcher(
                self.store,
                {"a": _plain_runner, "b": _plain_runner},
                (LaneSpec("lane_a", frozenset({"a"}), 1),),
                initially_accepting=True,
            )
        with self.assertRaises(ValueError):
            # lane 名重复。
            LaneDispatcher(
                self.store,
                {"a": _plain_runner, "b": _plain_runner},
                (
                    LaneSpec("lane_a", frozenset({"a"}), 1),
                    LaneSpec("lane_a", frozenset({"b"}), 1),
                ),
                initially_accepting=True,
            )
        with self.assertRaises(ValueError):
            # 名字非法。
            LaneSpec("Lane-A", frozenset({"a"}), 1)
        with self.assertRaises(ValueError):
            # 并发越界。
            LaneSpec("lane_a", frozenset({"a"}), 9)
        with self.assertRaises(ValueError):
            # 空服务集合。
            LaneSpec("lane_a", frozenset(), 1)

    def test_multi_worker_lane_rejects_resident_runner(self) -> None:
        with self.assertRaisesRegex(ValueError, "常驻 runtime"):
            LaneDispatcher(
                self.store,
                {"task": _ResidentRunner()},
                (LaneSpec("lane", frozenset({"task"}), 2),),
                initially_accepting=True,
            )

    def test_queue_message_counts_tasks_ahead(self) -> None:
        gate = threading.Event()
        blocked_ids: list[str] = []

        def runner(record, _cancel, _progress) -> RunResult:
            if blocked_ids and record.task_id == blocked_ids[0]:
                gate.wait(10)
            return _store_result(record)

        dispatcher = LaneDispatcher(
            self.store,
            {"task": runner},
            (LaneSpec("lane", frozenset({"task"}), 1),),
            initially_accepting=True,
        )
        dispatcher.start()
        try:

            def block_first(record) -> None:
                blocked_ids.append(record.task_id)

            running = dispatcher.submit("task", block_first)
            self._wait_until(lambda: self.store.get(running.task_id).state == "running")
            queued = [dispatcher.submit("task", lambda _record: None) for _ in range(3)]

            self.assertEqual(
                dispatcher.queue_message(self.store.get(queued[0].task_id)),
                "排队中：即将开始。",
            )
            self.assertEqual(
                dispatcher.queue_message(self.store.get(queued[1].task_id)),
                "排队中：前面还有 1 个任务。",
            )
            self.assertEqual(
                dispatcher.queue_message(self.store.get(queued[2].task_id)),
                "排队中：前面还有 2 个任务。",
            )
            # 正在运行的任务不再有排队位置。
            self.assertIsNone(dispatcher.queue_message(self.store.get(running.task_id)))

            gate.set()
            self._wait_until(
                lambda: self.store.get(queued[0].task_id).state in {"running", "succeeded"}
            )
            self.assertIsNone(dispatcher.queue_message(self.store.get(queued[0].task_id)))
        finally:
            gate.set()
            dispatcher.shutdown()

    def test_cancelled_task_leaves_pending_order(self) -> None:
        gate = threading.Event()
        blocked_ids: list[str] = []

        def runner(record, _cancel, _progress) -> RunResult:
            if blocked_ids and record.task_id == blocked_ids[0]:
                gate.wait(10)
            return _store_result(record)

        dispatcher = LaneDispatcher(
            self.store,
            {"task": runner},
            (LaneSpec("lane", frozenset({"task"}), 1),),
            initially_accepting=True,
        )
        dispatcher.start()
        try:

            def block_first(record) -> None:
                blocked_ids.append(record.task_id)

            running = dispatcher.submit("task", block_first)
            self._wait_until(lambda: self.store.get(running.task_id).state == "running")
            queued = [dispatcher.submit("task", lambda _record: None) for _ in range(3)]

            cancelled = dispatcher.cancel(queued[1].task_id)
            self.assertIsNotNone(cancelled)
            self.assertEqual(self.store.get(queued[1].task_id).state, "cancelled")
            self.assertEqual(
                dispatcher.queue_message(self.store.get(queued[2].task_id)),
                "排队中：前面还有 1 个任务。",
            )
        finally:
            gate.set()
            dispatcher.shutdown()


if __name__ == "__main__":
    unittest.main()
