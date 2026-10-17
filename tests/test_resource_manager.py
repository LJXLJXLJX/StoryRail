from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from default_model_providers_implement.resource_manager import (
    CancelledError,
    ExclusiveResourceManager,
    ResourceLeaseRequiredError,
    RunResult,
)
from default_model_providers_implement.task_store import TaskStore


class ResourceManagerTests(unittest.TestCase):
    def test_completed_duration_is_persisted_across_store_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = TaskStore(root)
            now = [100.0]

            def runner(record, _cancel, _progress):
                now[0] = 165.25
                output = Path(record.task_dir) / "output.bin"
                output.write_bytes(b"result")
                return RunResult(output, "application/octet-stream")

            manager = ExclusiveResourceManager(store, {"video": runner})
            with patch(
                "default_model_providers_implement.resource_manager.time.monotonic",
                side_effect=lambda: now[0],
            ):
                manager.start()
                record = manager.submit("video", lambda _: None)
                try:
                    for _ in range(200):
                        if store.get(record.task_id).state == "succeeded":
                            break
                        time.sleep(0.01)
                    completed = store.get(record.task_id)
                    self.assertEqual(completed.state, "succeeded")
                    self.assertIn("生成总用时 65.2 秒", completed.message)
                    self.assertIn("不含排队", completed.message)
                finally:
                    manager.shutdown()
            self.assertEqual(TaskStore(root).get(record.task_id).message, completed.message)

    def test_same_runtime_stays_resident_until_another_runtime_needs_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            events: list[str] = []

            class Runtime:
                def __init__(self, name: str) -> None:
                    self.name = name

                def __call__(self, record, _cancel, _progress):
                    events.append(f"run:{self.name}")
                    output = Path(record.task_dir) / "output.bin"
                    output.write_bytes(self.name.encode())
                    return RunResult(output, "application/octet-stream")

                def release(self) -> None:
                    events.append(f"release:{self.name}")

            speech = Runtime("speech")
            video = Runtime("video")
            manager = ExclusiveResourceManager(
                store,
                {
                    "speech_a": speech,
                    "speech_b": speech,
                    "video": video,
                },
            )
            manager.start()
            records = [
                manager.submit("speech_a", lambda _record: None),
                manager.submit("speech_b", lambda _record: None),
                manager.submit("video", lambda _record: None),
            ]
            deadline = time.monotonic() + 5
            while any(store.get(item.task_id).state != "succeeded" for item in records):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            manager.shutdown()

            self.assertEqual(
                events,
                ["run:speech", "run:speech", "release:speech", "run:video", "release:video"],
            )

    def test_exclusive_resource_never_overlaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            active = 0
            maximum = 0
            lock = threading.Lock()

            def runner(record, _cancel, _progress):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.05)
                output = Path(record.task_dir) / "output.bin"
                output.write_bytes(record.task_id.encode())
                with lock:
                    active -= 1
                return RunResult(output, "application/octet-stream")

            manager = ExclusiveResourceManager(store, {"model": runner})
            manager.start()
            records = [manager.submit("model", lambda _record: None) for _ in range(3)]
            deadline = time.monotonic() + 5
            while any(store.get(item.task_id).state != "succeeded" for item in records):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            manager.shutdown()
            self.assertEqual(maximum, 1)

    def test_stateless_runtime_can_run_independent_tasks_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            active = 0
            maximum = 0
            lock = threading.Lock()
            release = threading.Event()

            def runner(record, _cancel, _progress):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                    if active >= 2:
                        release.set()
                self.assertTrue(release.wait(2))
                output = Path(record.task_dir) / "output.bin"
                output.write_bytes(record.task_id.encode())
                with lock:
                    active -= 1
                return RunResult(output, "application/octet-stream")

            manager = ExclusiveResourceManager(
                store,
                {"model": runner},
                resource_name="stateless-image",
                max_concurrent_tasks=3,
            )
            manager.start()
            records = [manager.submit("model", lambda _record: None) for _ in range(3)]
            deadline = time.monotonic() + 5
            while any(store.get(item.task_id).state != "succeeded" for item in records):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            manager.shutdown()
            self.assertGreaterEqual(maximum, 2)

    def test_parallel_workers_reject_resident_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))

            class Runtime:
                def __call__(self, _record, _cancel, _progress):
                    raise AssertionError

                def release(self) -> None:
                    pass

            with self.assertRaisesRegex(ValueError, "常驻 runtime"):
                ExclusiveResourceManager(
                    store,
                    {"model": Runtime()},
                    max_concurrent_tasks=2,
                )

    def test_running_task_fails_safely_after_restart_without_automatic_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = TaskStore(root)
            record = store.create("model")
            store.update(record.task_id, state="running", progress=0.5)
            restored = TaskStore(root).get(record.task_id)
            self.assertEqual(restored.state, "failed")
            self.assertEqual(restored.progress, 0.5)
            self.assertEqual(restored.error_code, "runtime_interrupted")
            self.assertTrue(restored.retryable)

    def test_running_task_cancellation_reaches_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))

            def runner(_record, cancel, _progress):
                if cancel.wait(2):
                    raise CancelledError
                raise AssertionError("取消事件没有传到 runtime。")

            manager = ExclusiveResourceManager(store, {"model": runner})
            manager.start()
            record = manager.submit("model", lambda _record: None)
            deadline = time.monotonic() + 2
            while store.get(record.task_id).state != "running":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            manager.cancel(record.task_id)
            while store.get(record.task_id).state != "cancelled":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            manager.shutdown()

    def test_controller_revoke_cancels_queue_and_releases_resident_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            events: list[str] = []

            class Runtime:
                def __call__(self, _record, cancel, _progress):
                    events.append("run")
                    if cancel.wait(2):
                        raise CancelledError
                    raise AssertionError("租约撤销没有传到 runtime。")

                def release(self) -> None:
                    events.append("release")

            manager = ExclusiveResourceManager(
                store,
                {"model": Runtime()},
                initially_accepting=False,
            )
            manager.start()
            with self.assertRaises(ResourceLeaseRequiredError):
                manager.submit("model", lambda _record: None)

            manager.activate()
            running = manager.submit("model", lambda _record: None)
            queued = manager.submit("model", lambda _record: None)
            deadline = time.monotonic() + 2
            while store.get(running.task_id).state != "running":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)

            released = manager.revoke(
                message="Mac Core 心跳超时。",
                error_code="controller_lease_expired",
            )
            self.assertTrue(released.wait(2))
            self.assertEqual(store.get(running.task_id).state, "cancelled")
            self.assertEqual(store.get(running.task_id).error_code, "controller_lease_expired")
            self.assertEqual(store.get(queued.task_id).state, "cancelled")
            self.assertEqual(events, ["run", "release"])
            with self.assertRaises(ResourceLeaseRequiredError):
                manager.submit("model", lambda _record: None)
            manager.shutdown()

    def test_recoverable_task_waits_for_controller_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            record = store.create("model")

            def runner(current, _cancel, _progress):
                output = Path(current.task_dir) / "output.bin"
                output.write_bytes(b"done")
                return RunResult(output, "application/octet-stream")

            manager = ExclusiveResourceManager(
                store,
                {"model": runner},
                initially_accepting=False,
            )
            manager.start()
            time.sleep(0.05)
            self.assertEqual(store.get(record.task_id).state, "queued")
            manager.activate()
            deadline = time.monotonic() + 2
            while store.get(record.task_id).state != "succeeded":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
