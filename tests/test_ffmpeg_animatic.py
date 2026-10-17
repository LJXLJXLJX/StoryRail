from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core.model_providers.boundary import GenerationPhase, ProviderHandle
from core.model_providers.ffmpeg_animatic import (
    AnimaticClipInput,
    AnimaticNarrationInput,
    AnimaticRequest,
    FFmpegAnimaticProvider,
)
from core.model_providers.http import HttpResponse, UrllibTransport
from default_model_providers_implement import server as server_module
from default_model_providers_implement.ffmpeg_animatic_worker import (
    _clip_starts,
    _required_duration,
    _transition_plan,
    render,
)
from default_model_providers_implement.request_builders import prepare_ffmpeg_animatic
from default_model_providers_implement.resource_manager import RunResult
from default_model_providers_implement.server import ModelApiServer, _video_duration_seconds
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord


class RecordingTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        self.calls.append((method, url, json_body))
        return self.responses.pop(0)


def response(status: int, value: dict) -> HttpResponse:
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(value).encode())


def fake_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def fake_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 32


def fake_wav() -> bytes:
    return b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 32


def valid_payload() -> dict:
    return {
        "aspect_ratio": "16:9",
        "transition_seconds": 0.35,
        "clips": [
            {
                "mime": "image/png",
                "base64": base64.b64encode(fake_png()).decode(),
                "transition_from_previous": None,
                "duration_seconds": 2.0,
            },
            {
                "mime": "image/jpeg",
                "base64": base64.b64encode(fake_jpeg()).decode(),
                "transition_from_previous": "seam_blend",
                "duration_seconds": 3.0,
            },
        ],
        "narrations": [
            {
                "mime": "audio/wav",
                "base64": base64.b64encode(fake_wav()).decode(),
                "start_clip_index": 1,
            }
        ],
    }


class FFmpegAnimaticProviderTests(unittest.TestCase):
    def test_submit_uses_fixed_typed_media_contract(self) -> None:
        transport = RecordingTransport([response(202, {"animatic_id": "animatic-1"})])
        provider = FFmpegAnimaticProvider("http://models", transport)
        request = AnimaticRequest(
            (
                AnimaticClipInput(fake_png(), None, 2.0),
                AnimaticClipInput(fake_jpeg(), None, 3.0),
            ),
            (AnimaticNarrationInput(fake_wav(), 1),),
            "16:9",
        )

        handle = provider.submit(request)

        self.assertEqual(handle.external_id, "animatic-1")
        method, url, payload = transport.calls[0]
        self.assertEqual((method, url), ("POST", "http://models/ffmpeg/animatics"))
        self.assertEqual(payload["clips"][0]["mime"], "image/png")
        self.assertIsNone(payload["clips"][0]["transition_from_previous"])
        self.assertEqual(payload["clips"][1]["transition_from_previous"], None)
        self.assertEqual(payload["clips"][1]["duration_seconds"], 3.0)
        self.assertEqual(payload["narrations"][0]["start_clip_index"], 1)
        self.assertNotIn("path", json.dumps(payload))
        self.assertNotIn("filter", json.dumps(payload))

    def test_success_observation_is_normalized(self) -> None:
        transport = RecordingTransport(
            [
                response(
                    200,
                    {
                        "stage": "done",
                        "progress": 1.0,
                        "message": "完成",
                        "movie": {
                            "id": "animatic-1",
                            "mime": "video/mp4",
                            "bytes": 44,
                            "sha256": "a" * 64,
                            "duration_seconds": 8.75,
                        },
                    },
                )
            ]
        )
        provider = FFmpegAnimaticProvider("http://models", transport)

        observed = provider.observe(ProviderHandle(provider.plugin_id, 1, "animatic-1"))

        self.assertIs(observed.phase, GenerationPhase.SUCCEEDED)
        self.assertEqual(observed.artifact.media_type, "video/mp4")
        self.assertEqual(observed.artifact.duration_seconds, 8.75)


class FFmpegAnimaticBuilderTests(unittest.TestCase):
    def test_valid_payload_writes_request_and_media_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = TaskRecord("b" * 32, "ffmpeg_animatic", "queued", 0.0, "等待", temporary)
            prepare = prepare_ffmpeg_animatic(valid_payload())
            prepare(record)

            request = json.loads((Path(temporary) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["schema"], "ffmpeg_animatic_request_v1")
            self.assertEqual(request["aspect_ratio"], "16:9")
            self.assertEqual(
                [item["file"] for item in request["clips"]],
                ["clip-0000.png", "clip-0001.jpg"],
            )
            self.assertEqual(request["clips"][1]["transition_from_previous"], "seam_blend")
            self.assertTrue((Path(temporary) / "clip-0000.png").is_file())
            self.assertTrue((Path(temporary) / "narration-0000.wav").is_file())

    def test_unknown_field_is_rejected(self) -> None:
        with self.assertRaises(RequestError):
            prepare_ffmpeg_animatic({**valid_payload(), "shell": "whoami"})

    def test_bad_aspect_ratio_is_rejected(self) -> None:
        with self.assertRaisesRegex(RequestError, "aspect_ratio"):
            prepare_ffmpeg_animatic({**valid_payload(), "aspect_ratio": "1:1"})

    def test_non_image_clip_is_rejected(self) -> None:
        payload = valid_payload()
        payload["clips"][0] = {
            "mime": "video/mp4",
            "base64": base64.b64encode(b"\x00" * 24).decode(),
            "transition_from_previous": None,
            "duration_seconds": 2.0,
        }
        with self.assertRaisesRegex(RequestError, "PNG 或 JPEG"):
            prepare_ffmpeg_animatic(payload)

    def test_image_bytes_must_match_declared_mime(self) -> None:
        payload = valid_payload()
        payload["clips"][0] = {
            "mime": "image/png",
            "base64": base64.b64encode(fake_jpeg()).decode(),
            "transition_from_previous": None,
            "duration_seconds": 2.0,
        }
        with self.assertRaisesRegex(RequestError, "media type"):
            prepare_ffmpeg_animatic(payload)

    def test_first_clip_cannot_have_transition(self) -> None:
        payload = valid_payload()
        payload["clips"][0]["transition_from_previous"] = "seam_blend"
        with self.assertRaisesRegex(RequestError, "首个片段"):
            prepare_ffmpeg_animatic(payload)

    def test_unknown_transition_is_rejected(self) -> None:
        payload = valid_payload()
        payload["clips"][1]["transition_from_previous"] = "wipe"
        with self.assertRaisesRegex(RequestError, "转场"):
            prepare_ffmpeg_animatic(payload)

    def test_out_of_range_duration_is_rejected(self) -> None:
        payload = valid_payload()
        payload["clips"][0]["duration_seconds"] = 0.01
        with self.assertRaises(RequestError):
            prepare_ffmpeg_animatic(payload)
        payload = valid_payload()
        payload["clips"][1]["duration_seconds"] = 700.0
        with self.assertRaises(RequestError):
            prepare_ffmpeg_animatic(payload)

    def test_narration_must_be_real_wav(self) -> None:
        payload = valid_payload()
        payload["narrations"][0]["mime"] = "audio/mpeg"
        with self.assertRaisesRegex(RequestError, "WAV"):
            prepare_ffmpeg_animatic(payload)
        payload = valid_payload()
        payload["narrations"][0]["base64"] = base64.b64encode(b"NOPE" * 8).decode()
        with self.assertRaisesRegex(RequestError, "真实 WAV"):
            prepare_ffmpeg_animatic(payload)

    def test_start_clip_index_must_exist(self) -> None:
        payload = valid_payload()
        payload["narrations"][0]["start_clip_index"] = 2
        with self.assertRaises(RequestError):
            prepare_ffmpeg_animatic(payload)
        payload = valid_payload()
        payload["narrations"][0]["start_clip_index"] = -1
        with self.assertRaises(RequestError):
            prepare_ffmpeg_animatic(payload)


class FFmpegAnimaticTimelineTests(unittest.TestCase):
    def test_transition_plan_allows_hard_cuts(self) -> None:
        durations = [2.0, 4.0, 1.0]
        transitions = [None, "seam_blend", None]
        self.assertEqual(_transition_plan(durations, transitions, 0.35), [0.0, 0.35, 0.0])

    def test_transition_plan_clamps_to_half_clip(self) -> None:
        durations = [0.4, 0.4]
        transitions = [None, "seam_blend"]
        self.assertEqual(_transition_plan(durations, transitions, 0.35), [0.0, 0.2])

    def test_clip_starts_account_for_transitions(self) -> None:
        durations = [2.0, 4.0, 1.0]
        transitions = [0.0, 0.35, 0.0]
        self.assertEqual(_clip_starts(durations, transitions), [0.0, 1.65, 5.65])

    def test_required_duration_covers_late_narration(self) -> None:
        starts = [0.0, 1.65, 5.65]
        narrations = [{"start_clip_index": 2}]
        visual = 6.65
        self.assertEqual(_required_duration(visual, starts, narrations, [1.5]), 7.15)
        self.assertEqual(_required_duration(visual, starts, narrations, [0.5]), visual)


@unittest.skipIf(shutil.which("ffmpeg") is None, "本机没有 ffmpeg。")
class FFmpegAnimaticWorkerTests(unittest.TestCase):
    def test_real_ffmpeg_renders_transitions_audio_and_narration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clips = []
            for index, color in enumerate(("red", "green", "blue")):
                path = root / f"source-{index}.png"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={color}:s=320x180:r=24:d=0.2",
                        "-frames:v",
                        "1",
                        str(path),
                    ],
                    check=True,
                )
                clips.append(path.read_bytes())
            narration = root / "narration.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=700:sample_rate=48000:duration=1.2",
                    "-c:a",
                    "pcm_s16le",
                    str(narration),
                ],
                check=True,
            )
            task_root = root / "task"
            task_root.mkdir()
            record = TaskRecord("c" * 32, "ffmpeg_animatic", "queued", 0.0, "等待", str(task_root))
            prepare = prepare_ffmpeg_animatic(
                {
                    "aspect_ratio": "16:9",
                    "transition_seconds": 0.2,
                    "clips": [
                        {
                            "mime": "image/png",
                            "base64": base64.b64encode(content).decode(),
                            "transition_from_previous": transition,
                            "duration_seconds": target_duration,
                        }
                        for content, transition, target_duration in zip(
                            clips,
                            (None, None, "seam_blend"),
                            (0.8, 0.8, 1.2),
                            strict=True,
                        )
                    ],
                    "narrations": [
                        {
                            "mime": "audio/wav",
                            "base64": base64.b64encode(narration.read_bytes()).decode(),
                            "start_clip_index": 2,
                        }
                    ],
                }
            )
            prepare(record)

            render(task_root / "request.json")

            output = task_root / "output.mp4"
            self.assertTrue(output.is_file())
            record.artifact_name = output.name
            record.artifact_media_type = "video/mp4"
            probe = json.loads(
                subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_streams",
                        "-show_format",
                        "-of",
                        "json",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            self.assertEqual({item["codec_type"] for item in probe["streams"]}, {"video", "audio"})
            self.assertAlmostEqual(float(probe["format"]["duration"]), 2.6, delta=0.05)
            self.assertAlmostEqual(
                _video_duration_seconds(record), float(probe["format"]["duration"]), places=5
            )


@unittest.skipIf(shutil.which("ffmpeg") is None, "本机没有 ffmpeg。")
class FFmpegAnimaticServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        fixture_root = Path(self.temporary.name) / "fixture"
        fixture_root.mkdir()
        self.fixture_mp4 = fixture_root / "fixture.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=160x90:r=24:d=0.4",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(self.fixture_mp4),
            ],
            check=True,
        )

        def fake_animatic_runner(record, cancel, progress) -> RunResult:
            progress(0.5, "伪造 Animatic 合成。")
            output = Path(record.task_dir) / "output.mp4"
            shutil.copyfile(self.fixture_mp4, output)
            return RunResult(output, "video/mp4")

        self.patch = mock.patch.object(
            server_module, "ffmpeg_animatic_runner", fake_animatic_runner
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.server = ModelApiServer(
            ("127.0.0.1", 0),
            Path(self.temporary.name) / "state",
            enabled_services={"ffmpeg_animatic"},
        )
        self.server.manager.start()
        self.addCleanup(self.server.manager.shutdown)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        host, port = self.server.server_address
        self.endpoint = f"http://{host}:{port}"
        self.provider = FFmpegAnimaticProvider(self.endpoint, UrllibTransport())

    def test_post_status_and_artifact_round_trip(self) -> None:
        handle = self.provider.submit(
            AnimaticRequest(
                (
                    AnimaticClipInput(fake_png(), None, 1.0),
                    AnimaticClipInput(fake_jpeg(), "seam_blend", 1.5),
                ),
                (AnimaticNarrationInput(fake_wav(), 1),),
                "16:9",
            )
        )
        self.assertEqual(self.server.store.get(handle.external_id).kind, "ffmpeg_animatic")

        observation = self.provider.observe(handle)
        deadline = time.monotonic() + 10
        while observation.phase not in {
            GenerationPhase.SUCCEEDED,
            GenerationPhase.FAILED,
            GenerationPhase.CANCELLED,
        }:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
            observation = self.provider.observe(handle)
        self.assertIs(observation.phase, GenerationPhase.SUCCEEDED)
        self.assertEqual(observation.artifact.media_type, "video/mp4")
        self.assertGreater(observation.artifact.duration_seconds or 0, 0)

        content = self.provider.read_artifact(handle, observation.artifact.artifact_id)
        self.assertEqual(content, self.fixture_mp4.read_bytes())

    def test_invalid_transition_returns_422(self) -> None:
        payload = valid_payload()
        payload["clips"][1]["transition_from_previous"] = "wipe"
        http_response = UrllibTransport().request(
            "POST", self.endpoint + "/ffmpeg/animatics", json_body=payload
        )
        self.assertEqual(http_response.status, 422)

    def test_disabled_final_assembly_route_does_not_exist(self) -> None:
        response = UrllibTransport().request(
            "POST",
            self.endpoint + "/ffmpeg/final-assemblies",
            json_body=valid_payload(),
        )
        self.assertEqual(response.status, 404)

    def test_abort_unknown_animatic_returns_404(self) -> None:
        response = UrllibTransport().request(
            "PUT", self.endpoint + f"/ffmpeg/animatics/{'d' * 32}/abort"
        )
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
