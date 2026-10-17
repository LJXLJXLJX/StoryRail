from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.model_providers.boundary import GenerationPhase, ProviderHandle
from core.model_providers.ffmpeg_final_assembly import (
    FFmpegFinalAssemblyProvider,
    FinalAssemblyClipInput,
    FinalAssemblyNarrationInput,
    FinalAssemblyRequest,
)
from core.model_providers.http import HttpResponse
from default_model_providers_implement.ffmpeg_final_assembly_worker import render
from default_model_providers_implement.request_builders import prepare_ffmpeg_final_assembly
from default_model_providers_implement.server import _video_duration_seconds
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


def fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


def fake_wav() -> bytes:
    return b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 32


class FFmpegFinalAssemblyProviderTests(unittest.TestCase):
    def test_submit_uses_fixed_typed_media_contract(self) -> None:
        transport = RecordingTransport([response(202, {"assembly_id": "assembly-1"})])
        provider = FFmpegFinalAssemblyProvider("http://models", transport)
        request = FinalAssemblyRequest(
            (
                FinalAssemblyClipInput(fake_mp4(), None, 1.25),
                FinalAssemblyClipInput(fake_mp4(), None, 1.5),
            ),
            (FinalAssemblyNarrationInput(fake_wav(), 1),),
            "16:9",
            0.1,
            0.65,
            1.35,
        )

        handle = provider.submit(request)

        self.assertEqual(handle.external_id, "assembly-1")
        method, url, payload = transport.calls[0]
        self.assertEqual((method, url), ("POST", "http://models/ffmpeg/final-assemblies"))
        self.assertEqual(payload["clips"][1]["transition_from_previous"], None)
        self.assertEqual(payload["clips"][1]["duration_seconds"], 1.5)
        self.assertEqual(payload["narrations"][0]["start_clip_index"], 1)
        self.assertEqual(payload["video_audio_volume"], 0.65)
        self.assertEqual(payload["narration_audio_volume"], 1.35)
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
                            "id": "assembly-1",
                            "mime": "video/mp4",
                            "bytes": 44,
                            "sha256": "a" * 64,
                            "duration_seconds": 8.75,
                        },
                    },
                )
            ]
        )
        provider = FFmpegFinalAssemblyProvider("http://models", transport)

        observed = provider.observe(ProviderHandle(provider.plugin_id, 1, "assembly-1"))

        self.assertIs(observed.phase, GenerationPhase.SUCCEEDED)
        self.assertEqual(observed.artifact.media_type, "video/mp4")
        self.assertEqual(observed.artifact.duration_seconds, 8.75)


class FFmpegFinalAssemblyWorkerTests(unittest.TestCase):
    def test_real_ffmpeg_renders_transitions_audio_and_narration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clips = []
            for index, color in enumerate(("red", "green", "blue")):
                path = root / f"source-{index}.mp4"
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
                        f"color=c={color}:s=320x180:r=24:d=0.8",
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
            record = TaskRecord(
                "a" * 32, "ffmpeg_final_assembly", "queued", 0.0, "等待", str(task_root)
            )
            prepare = prepare_ffmpeg_final_assembly(
                {
                    "aspect_ratio": "16:9",
                    "transition_seconds": 0.2,
                    "clips": [
                        {
                            "mime": "video/mp4",
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
            video_stream = next(item for item in probe["streams"] if item["codec_type"] == "video")
            self.assertAlmostEqual(float(video_stream["duration"]), 2.6, delta=0.05)
            self.assertAlmostEqual(
                _video_duration_seconds(record), float(probe["format"]["duration"]), places=5
            )

    def test_real_ffmpeg_crops_to_two_to_one_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
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
                    "color=c=red:s=320x180:r=24:d=0.5",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(source),
                ],
                check=True,
            )
            task_root = root / "task"
            task_root.mkdir()
            record = TaskRecord(
                "b" * 32, "ffmpeg_final_assembly", "queued", 0.0, "等待", str(task_root)
            )
            prepare_ffmpeg_final_assembly(
                {
                    "aspect_ratio": "2:1",
                    "transition_seconds": 0.2,
                    "clips": [
                        {
                            "mime": "video/mp4",
                            "base64": base64.b64encode(source.read_bytes()).decode(),
                            "transition_from_previous": None,
                            "duration_seconds": 0.5,
                        }
                    ],
                    "narrations": [],
                }
            )(record)

            render(task_root / "request.json")

            probe = json.loads(
                subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_streams",
                        "-of",
                        "json",
                        str(task_root / "output.mp4"),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            stream = probe["streams"][0]
            self.assertEqual((stream["width"], stream["height"]), (1920, 960))


if __name__ == "__main__":
    unittest.main()
