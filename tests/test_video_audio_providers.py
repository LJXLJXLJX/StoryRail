from __future__ import annotations

import array
import base64
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.model_providers.ffmpeg_audio_remix import FFmpegAudioRemixRequest
from default_model_providers_implement.ffmpeg_audio_remix_worker import main as remix_main
from default_model_providers_implement.request_builders import (
    prepare_demucs_audio_separation,
    prepare_ffmpeg_audio_remix,
)
from default_model_providers_implement.server import build_parser
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord


def _record(root: Path, kind: str) -> TaskRecord:
    root.mkdir()
    return TaskRecord("a" * 32, kind, "queued", 0.0, "等待", str(root))


def _media(media_type: str, content: bytes) -> dict[str, str]:
    return {"mime": media_type, "base64": base64.b64encode(content).decode("ascii")}


def _fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


def _fake_wav() -> bytes:
    return b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 32


class VideoAudioProviderContractTests(unittest.TestCase):
    def test_server_cli_accepts_audio_services(self) -> None:
        arguments = build_parser().parse_args(
            [
                "--state-root",
                "/tmp/storyrail-provider-test",
                "--services",
                "demucs_audio_separation,ffmpeg_audio_remix",
            ]
        )
        self.assertEqual(
            arguments.services,
            "demucs_audio_separation,ffmpeg_audio_remix",
        )

    def test_request_builders_write_only_fixed_media_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            separation_record = _record(root / "separation", "demucs_audio_separation")
            prepare_demucs_audio_separation(
                {"video": _media("video/mp4", _fake_mp4()), "stem": "voice"}
            )(separation_record)
            separation = json.loads(
                (Path(separation_record.task_dir) / "request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(separation["stem"], "voice")
            self.assertEqual(separation["input"], "input.mp4")
            self.assertNotIn("path", json.dumps(separation))

            remix_record = _record(root / "remix", "ffmpeg_audio_remix")
            prepare_ffmpeg_audio_remix(
                {
                    "video": _media("video/mp4", _fake_mp4()),
                    "voice": _media("audio/wav", _fake_wav()),
                    "background": _media("audio/wav", _fake_wav()),
                    "voice_gain_db": -3,
                    "background_gain_db": 2.5,
                    "voice_gain_start_seconds": 0.25,
                    "voice_gain_end_seconds": 0.75,
                    "background_gain_start_seconds": 0.1,
                    "background_gain_end_seconds": 0.9,
                }
            )(remix_record)
            remix = json.loads(
                (Path(remix_record.task_dir) / "request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(remix["voice_gain_db"], -3.0)
            self.assertEqual(remix["background_gain_db"], 2.5)
            self.assertEqual(remix["schema"], "ffmpeg_audio_remix_request_v2")
            self.assertEqual(remix["voice_gain_start_seconds"], 0.25)
            self.assertEqual(remix["voice_gain_end_seconds"], 0.75)
            self.assertEqual(remix["background_gain_start_seconds"], 0.1)
            self.assertEqual(remix["background_gain_end_seconds"], 0.9)
            self.assertNotIn("base64", json.dumps(remix))

    def test_request_builders_reject_unknown_fields_and_invalid_stem(self) -> None:
        with self.assertRaises(RequestError):
            prepare_demucs_audio_separation(
                {
                    "video": _media("video/mp4", _fake_mp4()),
                    "stem": "music",
                    "path": "/tmp/input.mp4",
                }
            )

    def test_remix_request_rejects_non_numeric_or_non_finite_gain(self) -> None:
        for value in (True, "0", float("nan"), float("inf"), -101, 25):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FFmpegAudioRemixRequest(_fake_mp4(), _fake_wav(), _fake_wav(), value, 0)

    def test_remix_request_rejects_invalid_gain_ranges(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须同时提供"):
            FFmpegAudioRemixRequest(
                _fake_mp4(),
                _fake_wav(),
                _fake_wav(),
                0,
                0,
                voice_gain_start_seconds=0.2,
            )
        with self.assertRaisesRegex(ValueError, "时间范围不合法"):
            FFmpegAudioRemixRequest(
                _fake_mp4(),
                _fake_wav(),
                _fake_wav(),
                0,
                0,
                background_gain_start_seconds=0.8,
                background_gain_end_seconds=0.2,
            )


class FFmpegAudioRemixWorkerTests(unittest.TestCase):
    def test_real_ffmpeg_keeps_video_and_creates_mixed_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
                    "color=c=black:s=320x180:r=24:d=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=220:sample_rate=44100:duration=1",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(root / "input.mp4"),
                ],
                check=True,
            )
            for name, frequency in (("voice.wav", 440), ("background.wav", 880)):
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
                        f"sine=frequency={frequency}:sample_rate=44100:duration=1",
                        "-c:a",
                        "pcm_s16le",
                        str(root / name),
                    ],
                    check=True,
                )
            (root / "request.json").write_text(
                json.dumps(
                    {
                        "schema": "ffmpeg_audio_remix_request_v2",
                        "video": "input.mp4",
                        "voice": "voice.wav",
                        "background": "background.wav",
                        "voice_gain_db": -18,
                        "background_gain_db": -100,
                        "voice_gain_start_seconds": 0.5,
                        "voice_gain_end_seconds": 1.0,
                        "background_gain_start_seconds": 0.0,
                        "background_gain_end_seconds": 1.0,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "sys.argv",
                ["ffmpeg_audio_remix_worker", "--request-file", str(root / "request.json")],
            ):
                self.assertEqual(remix_main(), 0)

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
                        str(root / "output.mp4"),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            self.assertEqual({item["codec_type"] for item in probe["streams"]}, {"video", "audio"})
            self.assertAlmostEqual(float(probe["format"]["duration"]), 1.0, delta=0.08)
            raw = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(root / "output.mp4"),
                    "-map",
                    "0:a:0",
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                    "-f",
                    "f32le",
                    "-",
                ],
                check=True,
                capture_output=True,
            ).stdout
            samples = array.array("f")
            samples.frombytes(raw)

            def rms(start: float, end: float) -> float:
                values = samples[round(start * 44100) : round(end * 44100)]
                return math.sqrt(sum(value * value for value in values) / len(values))

            self.assertGreater(rms(0.1, 0.4), rms(0.65, 0.9) * 5)


if __name__ == "__main__":
    unittest.main()
