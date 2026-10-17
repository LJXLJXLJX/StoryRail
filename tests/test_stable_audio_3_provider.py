"""Stable Audio 3 插件与 Windows 请求校验。不加载模型。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.model_providers.boundary import GenerationPhase
from core.model_providers.http import HttpResponse
from core.model_providers.stable_audio_3 import StableAudio3Provider
from core.model_providers.stable_audio_3 import StableAudio3Request as TextToAudioRequest
from default_model_providers_implement.request_builders import prepare_stable_audio_3
from default_model_providers_implement.stable_audio_3_worker import load_request
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        del timeout
        self.calls.append((method, url, json_body))
        if method == "POST":
            body = {"generation_id": "ab" * 16}
            return HttpResponse(202, {}, json.dumps(body).encode())
        body = {
            "stage": "done",
            "progress": 1,
            "message": "音频已写好。",
            "audio": {
                "id": "ab" * 16,
                "mime": "audio/wav",
                "bytes": 12,
                "sha256": "cd" * 32,
                "duration_seconds": 10,
            },
        }
        return HttpResponse(200, {}, json.dumps(body).encode())


def test_provider_submits_prompt_and_reads_wav() -> None:
    transport = _Transport()
    provider = StableAudio3Provider("http://windows:8791", transport)
    handle = provider.submit(TextToAudioRequest("安静的钢琴", 10, 7))
    assert handle.plugin_id == "stable-audio-3.medium"
    assert handle.external_id == "ab" * 16
    assert transport.calls[0][0] == "POST"
    assert transport.calls[0][1].endswith("/stable-audio-3/generations")
    assert transport.calls[0][2] == {
        "prompt": "安静的钢琴",
        "duration_seconds": 10.0,
        "seed": 7,
    }
    observation = provider.observe(handle)
    assert observation.phase is GenerationPhase.SUCCEEDED
    assert observation.artifact is not None
    assert observation.artifact.duration_seconds == 10
    transport.request = lambda method, url, *, json_body=None, timeout=30.0: HttpResponse(  # type: ignore[method-assign]
        200, {}, b"RIFFwav"
    )
    assert provider.read_artifact(handle, "ab" * 16) == b"RIFFwav"


def test_prepare_writes_closed_request(tmp_path: Path) -> None:
    record = TaskRecord("ab" * 16, "stable_audio_3", "queued", 0.0, "", str(tmp_path))
    prepare_stable_audio_3({"prompt": "  雨声  ", "duration_seconds": 12, "seed": 3})(record)
    written = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert written == {
        "schema": "stable_audio_3_request_v1",
        "prompt": "雨声",
        "duration_seconds": 12.0,
        "seed": 3,
    }
    assert load_request(tmp_path / "request.json")["prompt"] == "雨声"


def test_prepare_rejects_unknown_field() -> None:
    with pytest.raises(RequestError, match="未知字段"):
        prepare_stable_audio_3({"prompt": "雨声", "duration_seconds": 12, "seed": 3, "steps": 8})
