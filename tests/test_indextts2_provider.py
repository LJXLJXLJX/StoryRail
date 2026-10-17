"""IndexTTS2.5 的历史 HTTP 协议与通用 recipe 接入。"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace

import pytest
from test_scene_driver_invariants import narration_project

from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.http import HttpResponse
from core.model_providers.indextts2.manifest import MANIFEST
from core.model_providers.indextts2.provider import IndexTTS2Provider
from core.model_providers.manifest import Capability
from core.model_providers.recipe import RecipeParams
from core.model_providers.registry import ProviderRegistry
from core.playground.projection import capability_descriptors
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from server.provider_plugins import load_plugin


class RecordingTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, json_body=None, timeout=30.0):
        self.calls.append((method, url, json_body))
        return self.responses.pop(0)


def response(status, value):
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(value).encode())


def status(condition="speaking", **extra):
    return {"condition": condition, "progress_fraction": 0.5, "status_text": "生成中", **extra}


def test_plugin_loads_playground_vector_form_and_preserves_historical_request(tmp_path, wav_bytes):
    async def scenario():
        transport = RecordingTransport(response(202, {"speech_id": "speech-1"}))
        plugin = load_plugin("indextts2=http://models", transport=transport)
        registry = ProviderRegistry()
        registry.install(plugin)
        service = PlaygroundService(PlaygroundStore(tmp_path), registry)
        catalog = capability_descriptors(service, include_schema=True)
        descriptor = next(item for item in catalog if item["id"] == "indextts2.synthesize")
        assert descriptor["recipe"]["recipe"] == MANIFEST.recipes[0].to_json()
        fields = descriptor["parameters_schema"]["properties"]
        assert fields["emotion_vector"]["minItems"] == fields["emotion_vector"]["maxItems"] == 8
        voice = await service.import_asset(
            media_type="audio/wav", content=wav_bytes, filename="参考音色.wav"
        )
        parameters = {
            "voice_asset_id": voice.id,
            "text": "你好，世界。",
            "seed": 17,
            "language": "auto",
            "duration_factor": 1.2,
            "emotion_vector": [0.1, -0.2, 0, 0, 0, 0, 0, 0.5],
        }
        run = await service.submit_run("indextts2.synthesize", parameters, note=None)
        assert run.phase.value == "queued"
        assert run.seed == 17 and run.input_asset_ids == (voice.id,)
        assert run.provider_snapshot.plugin_id == "indextts2"
        assert run.provider_snapshot.recipe_id == "indextts2.synthesize"
        assert run.plugin_id == "indextts2.synthesize"
        restored = service.store.read().runs[-1]
        assert restored.parameters == parameters and restored.recipe == MANIFEST.recipes[0]
        assert transport.calls == [
            (
                "POST",
                "http://models/indextts2/speech",
                {
                    "content": "你好，世界。",
                    "voice_sample": {
                        "type": "audio/wav",
                        "encoded": base64.b64encode(wav_bytes).decode("ascii"),
                    },
                    "randomness": 17,
                    "language": "auto",
                    "pace": 1.2,
                    "emotion": parameters["emotion_vector"],
                },
            )
        ]
        for invalid in (
            {"duration_factor": 0.49},
            {"duration_factor": True},
            {"emotion_vector": [0] * 7},
            {"emotion_vector": [2] * 8},
            {"emotion_vector": [False] * 8},
            {"seed": -1},
            {"language": "ja"},
            {"voice_asset_id": None},
            {"extra": "undeclared"},
        ):
            with pytest.raises(ValueError):
                await service.submit_run(
                    "indextts2.synthesize", {**parameters, **invalid}, note=None
                )
        assert len(transport.calls) == 1

    asyncio.run(scenario())


def test_narration_uses_new_plugin_without_domain_changes(tmp_path):
    async def scenario():
        store, service, _, document = await narration_project(tmp_path)
        transport = RecordingTransport(response(202, {"speech_id": "narration-1"}))
        service.provider_catalog.install(
            load_plugin("indextts2=http://models", transport=transport)
        )
        service.provider_catalog.bind(Capability.SPEECH_SYNTHESIZE.value, "indextts2")
        scene = document.director_script.scenes[0]
        cue = scene.narration_cues[0]
        params = {"duration_factor": 0.9, "emotion_vector": [0.2] * 8}
        track = replace(
            cue.track("en"),
            seed=29,
            recipe_params=RecipeParams.from_json({"indextts2.synthesize": params}),
        )
        cue = replace(cue, en=track)
        document = store.save_narration_cue(scene.id, cue, expected_revision=document.revision)
        submitted = await service.generate_narration(
            cue_id=cue.id, language="en", expected_revision=document.revision
        )
        generation = submitted.generations[-1]
        assert generation.phase.value == "queued" and generation.language.value == "en"
        assert generation.provider_snapshot.plugin_id == "indextts2"
        assert generation.recipe_params.get("indextts2.synthesize") == params
        voice_id = submitted.reference_library.narrator.voice("en").voice_reference_asset_id
        assert generation.input_asset_ids == (voice_id,)
        _, voice_bytes = store.read_asset(voice_id)
        payload = transport.calls[0][2]
        assert payload["content"] == track.text and payload["randomness"] == 29
        assert payload["pace"] == 0.9 and payload["emotion"] == [0.2] * 8
        assert payload["language"] == "en"
        assert base64.b64decode(payload["voice_sample"]["encoded"]) == voice_bytes
        assert all(item.selected_audio_asset_id is None for _, item in cue.tracks)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "condition,phase",
    [
        ("waiting_for_gpu", GenerationPhase.QUEUED),
        ("speaking", GenerationPhase.RUNNING),
        ("available", GenerationPhase.SUCCEEDED),
        ("fault", GenerationPhase.FAILED),
        ("cancelled", GenerationPhase.CANCELLED),
    ],
)
def test_observe_translates_all_phases(condition, phase):
    extra = {}
    if phase is GenerationPhase.SUCCEEDED:
        extra["audio_file"] = {
            "name": "sound.wav",
            "format": "audio/wav",
            "bytes": 44,
            "hash": "a" * 64,
        }
    if phase is GenerationPhase.FAILED:
        extra["reason"] = "model_failed"
    transport = RecordingTransport(response(200, status(condition, **extra)))
    provider = IndexTTS2Provider("http://models", transport)
    observed = provider.observe(ProviderHandle(provider.plugin_id, 1, "a/b"))
    assert observed.phase is phase and observed.progress == 0.5
    assert transport.calls[0][1].endswith("/a%2Fb")
    if phase is GenerationPhase.SUCCEEDED:
        assert observed.artifact.media_type == "audio/wav" and observed.artifact.byte_count == 44
    if phase is GenerationPhase.FAILED:
        assert observed.error_code == "model_failed"


@pytest.mark.parametrize(
    "change",
    [
        {"condition": []},
        {"condition": "unknown"},
        {"progress_fraction": True},
        {"progress_fraction": 1.1},
        {"status_text": 5},
        {"reason": {}},
        {"extra": "unknown"},
        {"condition": "available"},
        {
            "condition": "available",
            "audio_file": {"name": "x", "format": "audio/wav", "bytes": True, "hash": "a" * 64},
        },
        {
            "condition": "available",
            "audio_file": {"name": "x", "format": "audio/wav", "bytes": 44, "hash": "bad"},
        },
    ],
)
def test_invalid_observation_is_rejected(change):
    transport = RecordingTransport(response(200, {**status(), **change}))
    provider = IndexTTS2Provider("http://models", transport)
    with pytest.raises(ModelProviderError, match="IndexTTS2|未知字段"):
        provider.observe(ProviderHandle(provider.plugin_id, 1, "job"))


def test_cancel_artifact_and_handle_boundaries():
    transport = RecordingTransport(
        response(409, {}),
        response(200, status("cancelled")),
        HttpResponse(200, {}, b"audio"),
        HttpResponse(404, {}, b""),
    )
    provider = IndexTTS2Provider("http://models", transport)
    handle = ProviderHandle(provider.plugin_id, 1, "job/a")
    assert provider.cancel(handle).phase is GenerationPhase.CANCELLED
    assert transport.calls[0] == (
        "PATCH",
        "http://models/indextts2/speech/job%2Fa",
        {"cancel": True},
    )
    assert provider.read_artifact(handle, "sound/a.wav") == b"audio"
    assert transport.calls[2][1].endswith("/job%2Fa/audio/sound%2Fa.wav")
    with pytest.raises(ModelProviderError, match="不可用"):
        provider.read_artifact(handle, "missing")
    for invalid in (
        ProviderHandle("other", 1, "x"),
        ProviderHandle(provider.plugin_id, 2, "x"),
        ProviderHandle(provider.plugin_id, 1, ""),
    ):
        with pytest.raises(ModelProviderError, match="句柄|任务 ID"):
            provider.observe(invalid)
    assert len(transport.calls) == 4
