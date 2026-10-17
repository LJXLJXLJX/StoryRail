from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from core.model_providers.boundary import GenerationPhase
from core.model_providers.breeze_tts2 import (
    BreezeTTS2Provider,
    BreezeTTS2Request,
    BreezeVoiceReference,
)
from core.model_providers.http import HttpResponse


class _BreezeStub(BaseHTTPRequestHandler):
    requests: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.requests.append(self.rfile.read(length))
        self.send_response(200)
        self.send_header("Content-Type", "audio/pcm")
        self.send_header("X-Sample-Rate", "24000")
        self.end_headers()
        self.wfile.write(b"\x00\x00" * 480)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture()
def breeze_stub():
    _BreezeStub.requests = []
    server = HTTPServer(("127.0.0.1", 0), _BreezeStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_voice_design_spools_wav_and_preserves_description(
    tmp_path: Path, breeze_stub: str
) -> None:
    provider = BreezeTTS2Provider(breeze_stub, tmp_path)
    handle = provider.submit(BreezeTTS2Request("欢迎来到镜序。", instruction="温柔、清晰的女声"))
    observation = provider.observe(handle)
    assert observation.phase is GenerationPhase.SUCCEEDED
    assert observation.artifact is not None
    assert observation.artifact.media_type == "audio/wav"
    assert provider.read_artifact(handle, observation.artifact.artifact_id).startswith(b"RIFF")
    assert "instruction" in _BreezeStub.requests[0].decode("utf-8", errors="ignore")


def test_voice_direction_requires_complete_reference_transcript() -> None:
    with pytest.raises(ValueError, match="完整文字稿"):
        BreezeTTS2Request(
            "当前台词",
            voice=BreezeVoiceReference("audio/wav", b"RIFF"),
        )


def test_scheduler_endpoint_uses_durable_generation_contract(tmp_path: Path) -> None:
    class Transport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
            self.calls.append((method, url, json_body))
            if method == "POST":
                return HttpResponse(
                    202,
                    {"content-type": "application/json"},
                    json.dumps({"speech_id": "b" * 32}).encode(),
                )
            if method == "GET" and url.endswith("/audio/" + "b" * 32):
                return HttpResponse(200, {"content-type": "audio/wav"}, b"RIFF")
            return HttpResponse(
                200,
                {"content-type": "application/json"},
                (
                    '{"condition":"available","progress_fraction":1,'
                    '"status_text":"done","audio_file":{"name":"'
                    + "b" * 32
                    + '","format":"audio/wav","bytes":4,"hash":"h"}}'
                ).encode(),
            )

    transport = Transport()
    provider = BreezeTTS2Provider("http://provider", tmp_path, transport)
    handle = provider.submit(BreezeTTS2Request("测试"))
    assert handle.external_id == "b" * 32
    observation = provider.observe(handle)
    assert observation.phase is GenerationPhase.SUCCEEDED
    assert provider.read_artifact(handle, "b" * 32) == b"RIFF"
    assert transport.calls[0][1].endswith("/breeze-tts2/speech")
