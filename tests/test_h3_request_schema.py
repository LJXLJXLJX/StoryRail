from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from default_model_providers_implement.h3_request import parse_request
from default_model_providers_implement.request_builders import (
    prepare_h3_fl2va,
    prepare_h3_ref2va,
)
from default_model_providers_implement.sampling_progress import SamplingProgress
from default_model_providers_implement.task_store import TaskRecord


class H3RequestSchemaTests(unittest.TestCase):
    def test_sampling_progress_message_includes_speed_and_remaining_time(self) -> None:
        sampling = SamplingProgress("H3")
        with patch(
            "default_model_providers_implement.sampling_progress.time.monotonic",
            side_effect=[0.0, 5.0],
        ):
            sampling.update(10, 20)
            message = sampling.update(11, 20)
        self.assertEqual(
            message,
            "H3 扩散采样 11/20 · 本步 5.00 s/iter · 采样预计剩余 45 秒。",
        )

    def test_duplicate_reset_and_completion_measure_real_intervals(self) -> None:
        sampling = SamplingProgress("H3")
        with patch(
            "default_model_providers_implement.sampling_progress.time.monotonic",
            side_effect=[0.0, 2.0, 5.0, 7.0, 9.0, 10.0, 15.0],
        ):
            sampling.update(1, 20)
            self.assertEqual(sampling.update(1, 20), "")
            self.assertIn("本步 5.00 s/iter", sampling.update(2, 20))
            self.assertIn("正在估算", sampling.update(1, 20))
            self.assertIn("本步 2.00 s/iter", sampling.update(2, 20))
            self.assertIn("正在估算", sampling.update(19, 21))
            final = sampling.update(21, 21)
            self.assertIn("最近 2 步均值 2.50 s/iter", final)
            self.assertIn("采样完成，等待解码", final)
            self.assertNotIn("剩余 0", final)

    def _request(
        self,
        *,
        first: bool,
        last: bool,
        additional: int = 0,
        videos: int = 0,
        duration: float = 3.0,
    ):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        if first:
            (root / "first.png").write_bytes(b"x")
        if last:
            (root / "last.png").write_bytes(b"x")
        (root / "voice.wav").write_bytes(b"x")
        for index in range(additional):
            (root / f"additional-{index + 1}.png").write_bytes(b"x")
        for index in range(videos):
            (root / f"video-{index + 1}.mp4").write_bytes(b"x")
        value = {
            "schema": "storyrail_h3_runtime_request_v5",
            "mode": "ref2va",
            "prompt": "A red car moves toward the flag.",
            "width": 832,
            "height": 480,
            "duration_seconds": duration,
            "seed": 42,
            "steps": 20,
            "cfg": 1.0,
            "sage_attention": True,
            "selflift": True,
            "save_audio": False,
            "first_image": "first.png" if first else None,
            "last_image": "last.png" if last else None,
            "additional_images": [f"additional-{index + 1}.png" for index in range(additional)],
            "reference_audios": ["voice.wav"],
            "reference_videos": [f"video-{index + 1}.mp4" for index in range(videos)],
        }
        path = root / "request.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        request = parse_request(path)
        self.addCleanup(temporary.cleanup)
        return request

    def test_frame_count_aligns_to_17k_plus_5(self) -> None:
        request = self._request(first=True, last=False)
        self.assertEqual((request.frame_count - 5) % 17, 0)
        self.assertGreaterEqual(request.frame_count, 72)

    def test_duration_has_no_upper_limit(self) -> None:
        # 超过 15 秒可能 OOM，但这是 Agent 侧软约束；运行时请求不拒绝。
        request = self._request(first=True, last=False, duration=20.0)
        self.assertEqual(request.duration_seconds, 20.0)
        self.assertEqual((request.frame_count - 5) % 17, 0)
        self.assertGreaterEqual(request.frame_count, 480)
        with self.assertRaisesRegex(ValueError, "duration_seconds"):
            self._request(first=True, last=False, duration=0.1)

    def test_ref2va_request_builder_preserves_additional_picture_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
            wav = base64.b64encode(b"RIFFfixture").decode()
            record = TaskRecord("a" * 32, "h3_ref2va", "pending", 0.0, "", directory)
            prepare_h3_ref2va(
                {
                    "direction": "Use Picture 2 as the suitcase reference.",
                    "first_reference": {"media_type": "image/png", "content": png},
                    "last_reference": None,
                    "additional_references": [
                        {"media_type": "image/png", "content": png},
                    ],
                    "width_px": 832,
                    "height_px": 480,
                    "duration_s": 3,
                    "random_seed": 42,
                    "step_count": 20,
                    "guidance": 1,
                    "sage_attention": True,
                    "selflift": False,
                    "audio": True,
                    "audio_references": [{"media_type": "audio/wav", "content": wav}],
                    "video_references": [],
                }
            )(record)
            request = json.loads((root / "request.json").read_text())
            self.assertEqual(request["schema"], "storyrail_h3_runtime_request_v5")
            self.assertEqual(request["additional_images"], ["additional-1.png"])
            self.assertEqual((root / "additional-1.png").read_bytes(), base64.b64decode(png))

    def test_ref2va_request_builder_accepts_image_only_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
            record = TaskRecord("b" * 32, "h3_ref2va", "pending", 0.0, "", directory)

            prepare_h3_ref2va(
                {
                    "direction": "Keep the warehouse consistent with Picture 2.",
                    "first_reference": {"media_type": "image/png", "content": png},
                    "last_reference": None,
                    "additional_references": [
                        {"media_type": "image/png", "content": png},
                    ],
                    "width_px": 832,
                    "height_px": 480,
                    "duration_s": 3,
                    "random_seed": 42,
                    "step_count": 20,
                    "guidance": 1,
                    "sage_attention": True,
                    "selflift": False,
                    "audio": True,
                    "audio_references": [],
                    "video_references": [],
                }
            )(record)

            request = json.loads((root / "request.json").read_text())
            self.assertEqual(request["reference_audios"], [])
            self.assertEqual(request["reference_videos"], [])

    def test_ref2va_preserves_multiple_reference_audio_order(self) -> None:
        request = self._request(first=False, last=True)
        (request.task_dir / "voice-2.wav").write_bytes(b"second")
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["reference_audios"] = ["voice-2.wav", "voice.wav"]
        path.write_text(json.dumps(value))

        parsed = parse_request(path)

        self.assertEqual(
            [item.name for item in parsed.reference_audios],
            ["voice-2.wav", "voice.wav"],
        )

    def test_ref2va_accepts_no_reference_audio(self) -> None:
        request = self._request(first=True, last=False, additional=1)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["reference_audios"] = []
        path.write_text(json.dumps(value))

        parsed = parse_request(path)

        self.assertEqual(parsed.reference_audios, ())
        self.assertEqual(len(parsed.additional_images), 1)

    def test_ref2va_accepts_no_images_when_audio_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = TaskRecord("d" * 32, "h3_ref2va", "pending", 0.0, "", directory)
            wav = base64.b64encode(b"RIFFfixture").decode()
            prepare_h3_ref2va(
                {
                    "direction": "Only the text prompt defines this shot.",
                    "first_reference": None,
                    "last_reference": None,
                    "additional_references": [],
                    "width_px": 832,
                    "height_px": 480,
                    "duration_s": 3,
                    "random_seed": 42,
                    "step_count": 20,
                    "guidance": 1,
                    "sage_attention": True,
                    "selflift": False,
                    "audio": True,
                    "audio_references": [{"media_type": "audio/wav", "content": wav}],
                    "video_references": [],
                }
            )(record)

            request = parse_request(root / "request.json")
            self.assertIsNone(request.first_image)
            self.assertIsNone(request.last_image)
            self.assertEqual(request.additional_images, ())
            self.assertEqual(len(request.reference_audios), 1)
            self.assertEqual(request.reference_videos, ())

    def test_ref2va_rejects_no_media_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = TaskRecord("e" * 32, "h3_ref2va", "pending", 0.0, "", directory)
            with self.assertRaisesRegex(ValueError, "至少需要一个媒体参考"):
                prepare_h3_ref2va(
                    {
                        "direction": "Only text.",
                        "first_reference": None,
                        "last_reference": None,
                        "additional_references": [],
                        "width_px": 832,
                        "height_px": 480,
                        "duration_s": 3,
                        "random_seed": 42,
                        "step_count": 20,
                        "guidance": 1,
                        "sage_attention": True,
                        "selflift": False,
                        "audio": True,
                        "audio_references": [],
                        "video_references": [],
                    }
                )(record)

    def test_ref2va_request_builder_preserves_reference_video_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
            mp4_first = base64.b64encode(b"\x00\x00\x00\x18ftypfirst").decode()
            mp4_second = base64.b64encode(b"\x00\x00\x00\x18ftypsecond").decode()
            record = TaskRecord("c" * 32, "h3_ref2va", "pending", 0.0, "", directory)

            prepare_h3_ref2va(
                {
                    "direction": "Video 1 sets the walk cycle; Video 2 sets the run cycle.",
                    "first_reference": {"media_type": "image/png", "content": png},
                    "last_reference": None,
                    "additional_references": [],
                    "width_px": 832,
                    "height_px": 480,
                    "duration_s": 3,
                    "random_seed": 42,
                    "step_count": 20,
                    "guidance": 1,
                    "sage_attention": True,
                    "selflift": False,
                    "audio": True,
                    "audio_references": [],
                    "video_references": [
                        {"media_type": "video/mp4", "content": mp4_first},
                        {"media_type": "video/mp4", "content": mp4_second},
                    ],
                }
            )(record)

            request = json.loads((root / "request.json").read_text())
            self.assertEqual(request["schema"], "storyrail_h3_runtime_request_v5")
            self.assertEqual(request["reference_videos"], ["video-1.mp4", "video-2.mp4"])
            self.assertEqual((root / "video-1.mp4").read_bytes(), base64.b64decode(mp4_first))
            self.assertEqual((root / "video-2.mp4").read_bytes(), base64.b64decode(mp4_second))

    def test_ref2va_request_builder_rejects_more_than_three_reference_videos(self) -> None:
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
        mp4 = base64.b64encode(b"\x00\x00\x00\x18ftypfixture").decode()

        with self.assertRaisesRegex(ValueError, "最多 3 项"):
            prepare_h3_ref2va(
                {
                    "direction": "Too many motion references.",
                    "first_reference": {"media_type": "image/png", "content": png},
                    "last_reference": None,
                    "additional_references": [],
                    "width_px": 832,
                    "height_px": 480,
                    "duration_s": 3,
                    "random_seed": 42,
                    "step_count": 20,
                    "guidance": 1,
                    "sage_attention": True,
                    "selflift": False,
                    "audio": True,
                    "audio_references": [],
                    "video_references": [
                        {"media_type": "video/mp4", "content": mp4} for _ in range(4)
                    ],
                }
            )

    def test_ref2va_request_builder_rejects_non_mp4_reference_video(self) -> None:
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()

        with self.assertRaisesRegex(ValueError, "参考视频只接受 MP4"):
            prepare_h3_ref2va(
                {
                    "direction": "Wrong media type.",
                    "first_reference": {"media_type": "image/png", "content": png},
                    "last_reference": None,
                    "additional_references": [],
                    "width_px": 832,
                    "height_px": 480,
                    "duration_s": 3,
                    "random_seed": 42,
                    "step_count": 20,
                    "guidance": 1,
                    "sage_attention": True,
                    "selflift": False,
                    "audio": True,
                    "audio_references": [],
                    "video_references": [
                        {"media_type": "video/webm", "content": base64.b64encode(b"x").decode()}
                    ],
                }
            )

    def test_ref2va_preserves_reference_video_order(self) -> None:
        request = self._request(first=False, last=True, videos=2)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["reference_videos"] = ["video-2.mp4", "video-1.mp4"]
        path.write_text(json.dumps(value))

        parsed = parse_request(path)

        self.assertEqual(
            [item.name for item in parsed.reference_videos],
            ["video-2.mp4", "video-1.mp4"],
        )

    def test_ref2va_rejects_more_than_three_reference_videos(self) -> None:
        request = self._request(first=False, last=True, videos=3)
        (request.task_dir / "video-4.mp4").write_bytes(b"x")
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["reference_videos"] = [f"video-{index}.mp4" for index in range(1, 5)]
        path.write_text(json.dumps(value))

        with self.assertRaisesRegex(ValueError, "参考视频列表不合法"):
            parse_request(path)

    def test_fl2va_rejects_reference_videos(self) -> None:
        request = self._request(first=True, last=False, videos=1)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["mode"] = "fl2va"
        value["reference_audios"] = []
        path.write_text(json.dumps(value))

        with self.assertRaisesRegex(ValueError, "不能携带参考视频"):
            parse_request(path)

    def test_v4_internal_request_is_rejected(self) -> None:
        request = self._request(first=True, last=False)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["schema"] = "storyrail_h3_runtime_request_v4"
        path.write_text(json.dumps(value))

        with self.assertRaisesRegex(ValueError, "版本或 mode 不受支持"):
            parse_request(path)

    def test_unknown_internal_field_is_rejected(self) -> None:
        request = self._request(first=True, last=False)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["cwd"] = "C:/arbitrary"
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            parse_request(path)

    def test_fl2va_accepts_either_endpoint_but_not_neither(self) -> None:
        for first, last in ((True, False), (False, True), (True, True)):
            request = self._request(first=first, last=last)
            path = request.task_dir / "request.json"
            value = json.loads(path.read_text())
            value["mode"] = "fl2va"
            value["reference_audios"] = []
            path.write_text(json.dumps(value))
            parsed = parse_request(path)
            self.assertEqual(parsed.first_image is not None, first)
            self.assertEqual(parsed.last_image is not None, last)

        request = self._request(first=True, last=False)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["mode"] = "fl2va"
        value["first_image"] = None
        value["last_image"] = None
        value["reference_audios"] = []
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "至少需要"):
            parse_request(path)

    def test_v5_carries_steps_sage_and_selflift(self) -> None:
        request = self._request(first=True, last=False)
        self.assertEqual(
            (request.steps, request.sage_attention, request.selflift), (20, True, True)
        )

    def test_only_twenty_or_eight_steps_are_accepted(self) -> None:
        request = self._request(first=True, last=False)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["steps"] = 8
        path.write_text(json.dumps(value))
        self.assertEqual(parse_request(path).steps, 8)
        for steps in (12, True):
            value["steps"] = steps
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "20 或 8"):
                parse_request(path)

    def test_switches_must_be_booleans(self) -> None:
        request = self._request(first=True, last=False)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["selflift"] = 1
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "selflift"):
            parse_request(path)

    def test_canvas_uses_the_32_pixel_grid(self) -> None:
        request = self._request(first=True, last=False)
        path = request.task_dir / "request.json"
        value = json.loads(path.read_text())
        value["width"], value["height"] = 1920, 1088
        path.write_text(json.dumps(value))
        self.assertEqual((parse_request(path).width, parse_request(path).height), (1920, 1088))
        value["height"] = 720
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "画布"):
            parse_request(path)

    def test_fl2va_builder_requires_sampling_switches(self) -> None:
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
        payload = {
            "prompt": "A red car.",
            "canvas": {"width": 1280, "height": 704},
            "seconds": 3,
            "seed": 1,
            "sampling": {"steps": 8, "cfg": 1, "sage_attention": False, "selflift": True},
            "include_audio": True,
            "opening_frame": {"mime": "image/png", "base64": png},
            "closing_frame": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            record = TaskRecord("d" * 32, "h3_fl2va", "pending", 0.0, "", directory)
            prepare_h3_fl2va(payload)(record)
            request = json.loads((Path(directory) / "request.json").read_text())
        self.assertEqual(
            (request["steps"], request["sage_attention"], request["selflift"]), (8, False, True)
        )
        del payload["sampling"]["selflift"]
        with self.assertRaises(ValueError):
            prepare_h3_fl2va(payload)
        payload["sampling"]["selflift"] = True
        payload["sampling"]["steps"] = 12
        with self.assertRaisesRegex(ValueError, "20 或 8"):
            prepare_h3_fl2va(payload)


if __name__ == "__main__":
    unittest.main()
