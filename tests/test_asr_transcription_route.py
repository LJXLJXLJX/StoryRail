"""人类转写入口：读取项目参考音频交给语音转写插件，结果只回填，不改项目。"""

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import RecordingProposer, create_project, wav_bytes

from core.model_providers.recipe import RecipeRequest
from core.structured_director import StructuredDirectorHttpApi, StructuredDirectorStore


class _RecordingASR:
    plugin_id = "test.asr"
    plugin_version = 1

    def __init__(self) -> None:
        self.requests: list[RecipeRequest] = []

    def execute_recipe(self, request: RecipeRequest) -> SimpleNamespace:
        self.requests.append(request)
        return SimpleNamespace(text="完整的参考音频文字。")


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
        assert provider.requests[0].single("audio").media_type == "audio/wav"
        assert provider.requests[0].param("language") == "auto"
        assert store.read().revision == uploaded.revision
