from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from default_model_providers_implement.codex_worker import (
    _crop_to_aspect_ratio,
    _format_elapsed,
    _observe_turn,
    _select_generated_image,
    _turn_progress_update,
    _waiting_message,
)
from default_model_providers_implement.request_builders import prepare_codex
from default_model_providers_implement.task_store import TaskRecord


class CodexImageRuntimeTests(unittest.TestCase):
    def test_observe_turn_collects_result_and_emits_waiting_heartbeat(self) -> None:
        image = SimpleNamespace(root=SimpleNamespace(type="imageGeneration"))
        events = [
            SimpleNamespace(
                method="item/started",
                payload=SimpleNamespace(item=image),
            ),
            SimpleNamespace(
                method="item/completed",
                payload=SimpleNamespace(item=image),
            ),
            SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(
                    turn=SimpleNamespace(
                        status=SimpleNamespace(value="completed"),
                        error=None,
                    )
                ),
            ),
        ]

        class FakeTurn:
            async def stream(self):
                for index, event in enumerate(events):
                    if index == 1:
                        await asyncio.sleep(0.02)
                    yield event

        with patch("default_model_providers_implement.codex_worker.emit") as emitted:
            result = asyncio.run(_observe_turn(FakeTurn(), heartbeat_seconds=0.005))

        self.assertEqual(result.status.value, "completed")
        self.assertEqual(result.items, [image])
        messages = [call.args[1] for call in emitted.call_args_list]
        self.assertTrue(any("远端图片服务正在生成图片" in value for value in messages))
        self.assertTrue(any("已等待" in value for value in messages))

    def test_waiting_message_exposes_real_elapsed_time(self) -> None:
        self.assertEqual(_format_elapsed(9.9), "9 秒")
        self.assertEqual(_format_elapsed(65.2), "1 分 5 秒")
        self.assertEqual(
            _waiting_message("远端图片任务仍在处理，等待结果返回", 120),
            "远端图片任务仍在处理，等待结果返回；已等待 2 分钟。",
        )

    def test_turn_events_expose_remote_stage_and_retryable_connection_error(self) -> None:
        started = SimpleNamespace(
            method="item/started",
            payload=SimpleNamespace(
                item=SimpleNamespace(root=SimpleNamespace(type="dynamicToolCall", tool="wait"))
            ),
        )
        self.assertEqual(
            _turn_progress_update(started),
            "远端图片任务仍在处理，等待结果返回",
        )
        interrupted = SimpleNamespace(
            method="error",
            payload=SimpleNamespace(
                error=SimpleNamespace(message="stream disconnected"),
                will_retry=True,
            ),
        )
        self.assertEqual(
            _turn_progress_update(interrupted),
            "Codex 连接中断，正在自动重试：stream disconnected",
        )

    def test_multiple_codex_outputs_use_the_last_candidate(self) -> None:
        first = Path("first.png")
        last = Path("last.png")
        self.assertEqual(_select_generated_image([first, last]), last)

    def test_missing_codex_output_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "没有返回"):
            _select_generated_image([])

    def test_output_keeps_maximum_exact_nine_sixteen_crop(self) -> None:
        source = Image.new("RGB", (1536, 1024))
        result = _crop_to_aspect_ratio(source, "9:16")
        self.assertEqual(result.size, (576, 1024))
        self.assertEqual(result.width * 16, result.height * 9)

        landscape = _crop_to_aspect_ratio(Image.new("RGB", (1024, 1536)), "16:9")
        self.assertEqual(landscape.size, (1024, 576))
        self.assertEqual(landscape.width * 9, landscape.height * 16)

        wide = _crop_to_aspect_ratio(Image.new("RGB", (1536, 1024)), "2:1")
        self.assertEqual(wide.size, (1536, 768))

    def test_request_persists_explicit_aspect_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / ("a" * 32)
            task.mkdir()
            record = TaskRecord(
                task_id="a" * 32,
                kind="codex_image_generate",
                state="accepted",
                progress=0.0,
                message="accepted",
                task_dir=str(task),
            )
            prepare = prepare_codex(
                {
                    "instruction": "竖屏客厅。",
                    "model": "test",
                    "aspect_ratio": "9:16",
                    "source_image": None,
                    "reference_images": [],
                },
                operation="generate",
            )
            prepare(record)
            request = json.loads((task / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["schema"], "codex_image_request_v3")
            self.assertEqual(request["aspect_ratio"], "9:16")


if __name__ == "__main__":
    unittest.main()
