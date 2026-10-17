from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from default_model_providers_implement.runners import ResidentProcessRunner
from default_model_providers_implement.task_store import TaskRecord

_FAKE_RUNTIME = r"""
import json
import os
import pathlib
import sys

print(json.dumps({"event": "ready", "message": "ready", "value": 0.07,
                  "runtime_pid": os.getpid()}), flush=True)
run_count = 0
for line in sys.stdin:
    command = json.loads(line)
    if command == {"command": "shutdown"}:
        break
    run_count += 1
    request_id = command["request_id"]
    task_dir = pathlib.Path(command["request_file"]).parent
    (task_dir / "output.bin").write_text(
        f"{os.getpid()}:{run_count}", encoding="utf-8"
    )
    print(json.dumps({"event": "progress", "message": "running", "value": 0.5,
                      "request_id": request_id}), flush=True)
    print(json.dumps({"event": "result", "message": "done",
                      "request_id": request_id}), flush=True)
"""


class ResidentRuntimeTests(unittest.TestCase):
    def test_configured_native_startup_failure_retries_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = iter(
                (
                    [sys.executable, "-c", "raise SystemExit(77)"],
                    [sys.executable, "-u", "-c", _FAKE_RUNTIME],
                )
            )
            runner = ResidentProcessRunner(
                name="Fake",
                command_factory=lambda: next(commands),
                stderr_path=root / "runtime.stderr.log",
                output_name="output.bin",
                media_type="application/octet-stream",
                startup_timeout=5,
                startup_retry_exit_codes=frozenset({77}),
            )
            task_dir = root / ("c" * 32)
            task_dir.mkdir()
            (task_dir / "request.json").write_text("{}", encoding="utf-8")
            record = TaskRecord(
                "c" * 32,
                "fake",
                "running",
                0.01,
                "",
                str(task_dir),
            )
            progress: list[tuple[float, str]] = []

            result = runner(
                record,
                threading.Event(),
                lambda value, message: progress.append((value, message)),
            )
            runner.release()

            self.assertTrue(result.artifact_path.is_file())
            self.assertTrue(any("重试一次" in message for _, message in progress))

    def test_two_tasks_reuse_one_process_until_explicit_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = ResidentProcessRunner(
                name="Fake",
                command_factory=lambda: [sys.executable, "-u", "-c", _FAKE_RUNTIME],
                stderr_path=root / "runtime.stderr.log",
                output_name="output.bin",
                media_type="application/octet-stream",
                startup_timeout=5,
            )
            progress: list[tuple[float, str]] = []
            outputs: list[str] = []
            for index, task_id in enumerate(("a" * 32, "b" * 32), start=1):
                task_dir = root / task_id
                task_dir.mkdir()
                (task_dir / "request.json").write_text(
                    json.dumps({"index": index}), encoding="utf-8"
                )
                record = TaskRecord(
                    task_id,
                    "fake",
                    "running",
                    0.01,
                    "",
                    str(task_dir),
                )
                result = runner(
                    record,
                    threading.Event(),
                    lambda value, message: progress.append((value, message)),
                )
                outputs.append(result.artifact_path.read_text(encoding="utf-8"))

            runner.release()

            first_pid, first_count = outputs[0].split(":")
            second_pid, second_count = outputs[1].split(":")
            self.assertEqual(first_pid, second_pid)
            self.assertEqual((first_count, second_count), ("1", "2"))
            self.assertEqual(sum(message == "Fake 已加载并驻留。" for _, message in progress), 1)
            self.assertIn((0.07, "Fake 已加载并驻留。"), progress)

    def test_recycled_runtime_uses_fresh_process_for_each_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = ResidentProcessRunner(
                name="Fake",
                command_factory=lambda: [sys.executable, "-u", "-c", _FAKE_RUNTIME],
                stderr_path=root / "runtime.stderr.log",
                output_name="output.bin",
                media_type="application/octet-stream",
                startup_timeout=5,
                recycle_after_run=True,
            )
            outputs: list[str] = []
            for task_id in ("d" * 32, "e" * 32):
                task_dir = root / task_id
                task_dir.mkdir()
                (task_dir / "request.json").write_text("{}", encoding="utf-8")
                result = runner(
                    TaskRecord(task_id, "fake", "running", 0.01, "", str(task_dir)),
                    threading.Event(),
                    lambda _value, _message: None,
                )
                outputs.append(result.artifact_path.read_text(encoding="utf-8"))

            runner.release()

            first_pid, first_count = outputs[0].split(":")
            second_pid, second_count = outputs[1].split(":")
            self.assertNotEqual(first_pid, second_pid)
            self.assertEqual((first_count, second_count), ("1", "1"))


if __name__ == "__main__":
    unittest.main()
