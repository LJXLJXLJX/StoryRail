from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.http import HttpResponse
from core.model_providers.seedvr2_7b_sharp_fp8 import (
    SeedVR2SevenBSharpFP8Provider,
    SeedVR2UpscaleRequest,
    SeedVR2Video,
)
from default_model_providers_implement.request_builders import prepare_seedvr2_7b_sharp_fp8
from default_model_providers_implement.seedvr2_worker import load
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


def mp4_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


class SeedVR2ProviderTests(unittest.TestCase):
    def test_submit_uses_model_specific_api_and_media_bytes(self) -> None:
        transport = RecordingTransport([response(202, {"job_token": "job-1", "queue_position": 1})])
        provider = SeedVR2SevenBSharpFP8Provider("http://models", transport)

        handle = provider.submit(
            SeedVR2UpscaleRequest(SeedVR2Video("video/mp4", mp4_bytes()), seed=7)
        )

        self.assertEqual(handle.external_id, "job-1")
        method, url, payload = transport.calls[0]
        self.assertEqual((method, url), ("POST", "http://models/seedvr2/7b-sharp-fp8/upscales"))
        self.assertEqual(payload["target_short_side"], 720)
        self.assertEqual(payload["max_long_side"], 1280)
        self.assertNotIn("path", json.dumps(payload))

    def test_success_observation_is_normalized(self) -> None:
        transport = RecordingTransport(
            [
                response(
                    200,
                    {
                        "stage": "done",
                        "ratio": 1.0,
                        "description": "完成",
                        "movie": {
                            "key": "job-1",
                            "mime": "video/mp4",
                            "length": 44,
                            "digest": "a" * 64,
                            "duration_seconds": 3.25,
                        },
                    },
                )
            ]
        )
        provider = SeedVR2SevenBSharpFP8Provider("http://models", transport)

        observation = provider.observe(ProviderHandle(provider.plugin_id, 1, "job-1"))

        self.assertIs(observation.phase, GenerationPhase.SUCCEEDED)
        self.assertEqual(observation.artifact.media_type, "video/mp4")
        self.assertEqual(observation.artifact.duration_seconds, 3.25)

    def test_observe_rejects_unknown_fields(self) -> None:
        transport = RecordingTransport(
            [response(200, {"stage": "queued", "ratio": 0.0, "description": "等待", "cwd": "x"})]
        )
        provider = SeedVR2SevenBSharpFP8Provider("http://models", transport)

        with self.assertRaises(ModelProviderError):
            provider.observe(ProviderHandle(provider.plugin_id, 1, "job-1"))

    def test_media_boundary_rejects_non_mp4(self) -> None:
        with self.assertRaises(ValueError):
            SeedVR2Video("video/webm", b"bytes")


class SeedVR2PrivateRequestTests(unittest.TestCase):
    def test_builder_writes_only_fixed_input_and_strict_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            task_dir = Path(temporary)
            record = TaskRecord(
                "a" * 32,
                "seedvr2_7b_sharp_fp8",
                "queued",
                0.0,
                "等待模型资源。",
                str(task_dir),
            )
            prepare = prepare_seedvr2_7b_sharp_fp8(
                {
                    "source_video": {"mime": "video/mp4", "base64": "AAAAGGZ0eXBpc29tAAAAAA=="},
                    "target_short_side": 1080,
                    "max_long_side": 1920,
                    "seed": 42,
                }
            )

            prepare(record)
            request = load(task_dir / "request.json")

            self.assertEqual(request["source"], (task_dir / "input.mp4").resolve())
            self.assertEqual(request["target_short_side"], 1080)

    def test_builder_rejects_unknown_or_fake_video(self) -> None:
        with self.assertRaises(RequestError):
            prepare_seedvr2_7b_sharp_fp8(
                {
                    "source_video": {"mime": "video/mp4", "base64": "bm90LW1wNA=="},
                    "target_short_side": 1080,
                    "max_long_side": 1920,
                    "seed": 42,
                    "command": "whoami",
                }
            )


if __name__ == "__main__":
    unittest.main()
