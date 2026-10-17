from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from default_model_providers_implement.comfy_core import (
    BUILTIN_NODE_FILES,
    REQUIRED_NODE_TYPES,
    resolve_saved_video,
)
from default_model_providers_implement.comfy_core.runtime import (
    CUSTOM_NODE_PACKAGES,
    _install_progress_hook,
    _ProgressServer,
    reference_frame_indices,
)


class _FakeComfyUtils:
    def __init__(self) -> None:
        self.progress_hook = None

    def set_progress_bar_global_hook(self, hook) -> None:
        self.progress_hook = hook


class ComfyCoreH3RuntimeTests(unittest.TestCase):
    def test_sampling_progress_reports_steps_speed_and_remaining_time(self) -> None:
        reports: list[tuple[float, str]] = []
        server = _ProgressServer(lambda value, message: reports.append((value, message)))
        comfy_utils = _FakeComfyUtils()
        _install_progress_hook(comfy_utils, server)
        self.assertIsNotNone(comfy_utils.progress_hook)
        with patch(
            "default_model_providers_implement.sampling_progress.time.monotonic",
            side_effect=[100.0, 105.0],
        ):
            server.send_sync("executing", {"node": "12"})
            comfy_utils.progress_hook(10, 20, None, "request-1", "12")
            comfy_utils.progress_hook(11, 20, None, "request-1", "12")

        progress, message = reports[-1]
        self.assertAlmostEqual(progress, 0.596)
        self.assertEqual(
            message,
            "H3 FL2VA 扩散采样 11/20 · 本步 5.00 s/iter · 采样预计剩余 45 秒。",
        )

    def test_missing_start_and_interleaved_nodes_do_not_reset_sampling_clock(self) -> None:
        reports = []
        server = _ProgressServer(lambda value, message: reports.append((value, message)))
        with patch(
            "default_model_providers_implement.sampling_progress.time.monotonic",
            side_effect=[100.0, 110.0],
        ):
            server.send_sync("progress", {"node": "12", "value": 7, "max": 20})
            self.assertIn("正在估算", reports[-1][1])
            self.assertNotIn("0.0", reports[-1][1])
            server.send_sync("executing", {"node": "5"})
            server.send_sync("executing", {"node": "12"})
            server.send_sync("progress", {"node": "12", "value": 9, "max": 20})
        self.assertIn("最近 2 步均值 5.00 s/iter", reports[-1][1])
        self.assertIn("采样预计剩余 55 秒", reports[-1][1])
        self.assertEqual([p for p, _ in reports], sorted(p for p, _ in reports))

    def test_task_reset_rejects_late_events_and_decode_ignores_sampler_events(self) -> None:
        reports = []
        server = _ProgressServer(lambda value, message: reports.append((value, message)))
        server.reset("new")
        utils = _FakeComfyUtils()
        _install_progress_hook(utils, server)
        utils.progress_hook(10, 20, None, "old", "12")
        self.assertEqual(reports, [])
        utils.progress_hook(10, 20, None, "new", "12")
        self.assertIn("正在估算", reports[-1][1])
        server.send_sync("executing", {"node": "13", "prompt_id": "new"})
        count = len(reports)
        utils.progress_hook(11, 20, None, "new", "12")
        self.assertEqual(len(reports), count)
        self.assertIn("VAE", reports[-1][1])

    def test_ref2va_progress_uses_its_own_mode_label(self) -> None:
        reports = []
        server = _ProgressServer(lambda value, message: reports.append((value, message)))
        server.reset("ref-task", mode="ref2va")
        server.send_sync("executing", {"node": "7", "prompt_id": "ref-task"})
        self.assertIn("Ref2VA 参考条件", reports[-1][1])
        server.send_sync(
            "progress",
            {"node": "12", "value": 1, "max": 20, "prompt_id": "ref-task"},
        )
        self.assertIn("H3 REF2VA", reports[-1][1])

    def test_invalid_sampling_events_are_ignored(self) -> None:
        reports = []
        server = _ProgressServer(lambda value, message: reports.append((value, message)))
        for value, total in (
            (True, 20),
            (float("nan"), 20),
            (3, 0),
            (1, float("inf")),
            (3.5, 20),
            (-1, 20),
            (21, 20),
        ):
            server.send_sync("progress", {"node": "12", "value": value, "max": total})
        self.assertEqual(reports, [])

    def test_progress_ignores_non_sampler_nodes(self) -> None:
        reports: list[tuple[float, str]] = []
        server = _ProgressServer(lambda value, message: reports.append((value, message)))
        comfy_utils = _FakeComfyUtils()
        _install_progress_hook(comfy_utils, server)

        comfy_utils.progress_hook(1, 2, None, "request-1", "13")

        self.assertEqual(reports, [])

    def test_declares_only_the_required_builtin_extensions(self) -> None:
        self.assertEqual(
            BUILTIN_NODE_FILES,
            (
                "nodes_audio.py",
                "nodes_custom_sampler.py",
                "nodes_minimax_h3.py",
                "nodes_model_advanced.py",
                "nodes_video.py",
            ),
        )
        self.assertEqual(CUSTOM_NODE_PACKAGES, ("comfyui-SelfLift",))
        for node in (
            "MiniMaxH3ImageToVideo",
            "MiniMaxH3ReferenceToVideo",
            "ModelAttentionBackend",
            "SelfLiftH3Sampler",
            "VAEDecodeAudio",
            "LoadVideo",
            "GetVideoComponents",
            "SaveVideo",
        ):
            self.assertIn(node, REQUIRED_NODE_TYPES)
        self.assertNotIn("MiniMaxH3SigmaShift", REQUIRED_NODE_TYPES)
        self.assertNotIn("LTXVAudioVAEDecode", REQUIRED_NODE_TYPES)

    def test_reference_video_resamples_to_24fps_constant_rate(self) -> None:
        # 24fps 源逐帧保留。
        self.assertEqual(reference_frame_indices([i / 24 for i in range(49)]), list(range(49)))
        # 30fps 2 秒源压到 24fps：输出 49 帧，按时间取不晚于目标时刻的最近源帧。
        thirty = reference_frame_indices([i / 30 for i in range(61)])
        self.assertEqual(len(thirty), 49)
        self.assertEqual(thirty[:6], [0, 1, 2, 3, 5, 6])
        self.assertEqual(thirty[-1], 60)
        self.assertEqual(thirty, sorted(thirty))
        # 12fps 源升到 24fps：每帧重复，时间结构不变。
        self.assertEqual(reference_frame_indices([i / 12 for i in range(3)]), [0, 0, 1, 1, 2])
        with self.assertRaisesRegex(RuntimeError, "没有可解码画面"):
            reference_frame_indices([])

    def test_resolves_one_controlled_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "storyrail" / "task_00001_.mp4"
            target.parent.mkdir()
            target.write_bytes(b"\0\0\0\x18ftypisomvideo")
            history = {
                "outputs": {
                    "14": {
                        "images": [
                            {
                                "filename": target.name,
                                "subfolder": "storyrail",
                                "type": "output",
                            }
                        ]
                    }
                }
            }
            self.assertEqual(resolve_saved_video(history, root), target.resolve())

    def test_rejects_output_escape_and_multiple_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / "outside.mp4"
            outside.write_bytes(b"\0\0\0\x18ftypisomvideo")
            try:
                escaped = {
                    "outputs": {
                        "14": {
                            "images": [
                                {"filename": outside.name, "subfolder": "..", "type": "output"}
                            ]
                        }
                    }
                }
                with self.assertRaisesRegex(RuntimeError, "越过"):
                    resolve_saved_video(escaped, root)
                with self.assertRaisesRegex(RuntimeError, "一个视频"):
                    resolve_saved_video({"outputs": {"14": {"images": [{}, {}]}}}, root)
            finally:
                outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
