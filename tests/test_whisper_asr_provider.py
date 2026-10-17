import asyncio
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import RecordingProposer, create_project, wav_bytes

from core.model_providers.whisper_asr import (
    WhisperASRProvider,
    WhisperASRRequest,
    WhisperASRResult,
)
from core.structured_director import StructuredDirectorHttpApi, StructuredDirectorStore


class _WhisperStub(BaseHTTPRequestHandler):
    requests: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.requests.append(self.rfile.read(length))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"text": " 你好，StoryRail. "}).encode())

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture()
def whisper_stub():
    _WhisperStub.requests = []
    server = HTTPServer(("127.0.0.1", 0), _WhisperStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_whisper_provider_posts_wav_and_returns_trimmed_text(whisper_stub: str) -> None:
    provider = WhisperASRProvider(whisper_stub)
    result = provider.transcribe(WhisperASRRequest(wav_bytes(), "audio/wav"))
    assert result.text == "你好，StoryRail."
    request = _WhisperStub.requests[0]
    assert b'name="file"; filename="reference.wav"' in request
    assert b'name="language"' in request and b"auto" in request
    assert b'name="translate"' in request and b"false" in request


class _RecordingASR:
    plugin_id = "test.asr"
    plugin_version = 1

    def __init__(self) -> None:
        self.requests: list[WhisperASRRequest] = []

    def transcribe(self, request: WhisperASRRequest) -> WhisperASRResult:
        self.requests.append(request)
        return WhisperASRResult("完整的参考音频文字。")


def test_human_transcription_route_reads_project_asset_without_mutating_project() -> None:
    asyncio.run(_exercise_human_transcription_route())


async def _exercise_human_transcription_route() -> None:
    with tempfile.TemporaryDirectory() as directory:
        project_id = "0" * 32
        project = Path(directory) / project_id
        project.mkdir()
        store = StructuredDirectorStore(project, project_id)
        provider = _RecordingASR()
        service = StructuredDirectorService(
            store,
            RecordingProposer(),
            speech_recognition_provider=provider,
        )
        create_project(store)
        prepared = await service.prepare_references()
        character_id = prepared.reference_library.characters[0].id
        uploaded = await service.upload_reference_voice(
            card_id=character_id,
            media_type="audio/wav",
            content=wav_bytes(),
            filename="reference.wav",
            expected_revision=prepared.revision,
        )
        asset_id = uploaded.reference_library.characters[0].voice_reference_asset_id or ""
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        response = await api.handle(
            "POST",
            f"/structured-director/assets/{asset_id}/transcription",
            json.dumps({"language": "auto"}).encode(),
        )
        assert response.status == 200
        assert response.body == {"transcript": "完整的参考音频文字。"}
        assert provider.requests[0].media_type == "audio/wav"
        assert store.read().revision == uploaded.revision
