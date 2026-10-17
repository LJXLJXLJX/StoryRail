"""Playground 不知道插件名字：目录、输入、标签与向量都由 recipe 声明。"""

from __future__ import annotations

import asyncio

import pytest

from core.model_providers.boundary import ProviderHandle
from core.model_providers.manifest import (
    Capability,
    Field,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
)
from core.model_providers.recipe import RecipeInputs, RecipeParams
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.playground.projection import capability_descriptors
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from server.provider_plugins import load_plugin

MANIFEST = PluginManifest(
    "second_sample",
    1,
    "第二样本",
    (
        Recipe(
            "second_sample.speak",
            Capability.SPEECH_SYNTHESIZE,
            "通用语音",
            slots=(
                Slot(
                    "speaker",
                    Role.VOICE_REFERENCE,
                    "参考音色",
                    minimum=1,
                    media_types=("audio/wav",),
                    namespace="voice",
                ),
            ),
            params=(
                Field("content", Widget.PROMPT, "朗读正文", min_length=1, role=Role.SPEECH_TEXT),
                Field("randomness", Widget.SEED, "随机种子", default=42, role=Role.SEED),
                Field(
                    "emotion",
                    Widget.VECTOR,
                    "情感",
                    default=[0.0, 0.0],
                    dimension=2,
                    minimum=-1,
                    maximum=1,
                    component_labels=("喜悦", "平静"),
                ),
            ),
            label_namespaces=(("voice", "<Voice {n}>"),),
        ),
    ),
)


class SampleProvider:
    plugin_id = "second_sample.speak"
    plugin_version = 1

    def __init__(self):
        self.requests = []

    def submit_recipe(self, request):
        self.requests.append(request)
        return ProviderHandle(self.plugin_id, self.plugin_version, "sample-1")

    def observe(self, handle):
        raise AssertionError("本测试不观察模型")

    def cancel(self, handle):
        raise AssertionError("本测试不取消模型")

    def read_artifact(self, handle, artifact_id):
        raise AssertionError("本测试不读取产物")


def test_arbitrary_recipe_catalog_preview_and_vector_roundtrip(tmp_path, wav_bytes):
    async def scenario():
        registry = ProviderRegistry()
        provider = SampleProvider()
        registry.install(PluginInstance(MANIFEST, recipes={"second_sample.speak": provider}))
        service = PlaygroundService(PlaygroundStore(tmp_path), registry)
        descriptor = next(
            item
            for item in capability_descriptors(service, include_schema=True)
            if item["id"] == "second_sample.speak"
        )
        assert descriptor["group"] == "speech"
        assert descriptor["recipe"]["recipe"] == MANIFEST.recipes[0].to_json()
        assert descriptor["parameters_schema"]["properties"]["emotion"]["minItems"] == 2
        voice = await service.import_asset(
            media_type="audio/wav", content=wav_bytes, filename="音色.wav"
        )
        parameters = {
            "speaker_asset_id": voice.id,
            "content": "你好",
            "randomness": 17,
            "emotion": [0.4, -0.2],
        }
        revision = service.snapshot().revision
        preview = service.preview_recipe_inputs("second_sample.speak", parameters)
        assert preview["ready"] is True
        assert preview["input_labels"][0]["label"] == "<Voice 1>"
        assert service.snapshot().revision == revision
        run = await service.submit_run("second_sample.speak", parameters, note=None)
        assert run.seed == 17
        assert run.input_asset_ids == (voice.id,)
        assert provider.requests[0].param("emotion") == [0.4, -0.2]
        restored = service.store.read().runs[-1]
        assert restored.recipe == MANIFEST.recipes[0]
        assert restored.parameters == parameters
        assert restored.provider_snapshot.recipe_id == "second_sample.speak"
        bad = {**parameters, "emotion": [2, 0]}
        assert service.preview_recipe_inputs("second_sample.speak", bad)["ready"] is False
        with pytest.raises(ValueError, match="情感"):
            await service.submit_run("second_sample.speak", bad, note=None)
        assert len(provider.requests) == 1

    asyncio.run(scenario())


def test_recipe_book_vectors_thaw_for_manifest_validation():
    registry = ProviderRegistry()
    registry.install(PluginInstance(MANIFEST, recipes={"second_sample.speak": SampleProvider()}))
    inputs = RecipeInputs.from_json({"bindings": {}, "params": {"emotion": [0.2, 0.1]}})
    registry.validate_recipe_inputs(Capability.SPEECH_SYNTHESIZE, "second_sample.speak", inputs, ())
    params = RecipeParams.from_json({"second_sample.speak": {"emotion": [0.2, 0.1]}})
    assert registry.validate_recipe_params(
        Capability.SPEECH_SYNTHESIZE, "second_sample.speak", params.get("second_sample.speak")
    ) == {"emotion": [0.2, 0.1]}


def test_startup_plugin_loader_keeps_package_identity_and_validates_connection():
    plugin = load_plugin("codex_image=http://127.0.0.1:8792")
    assert plugin.plugin_id == "codex_image"
    assert plugin.endpoint == "http://127.0.0.1:8792"
    assert set(plugin.recipes) == {"codex_image.generate", "codex_image.edit"}
    for invalid in (
        "../arbitrary=http://localhost",
        "codex_image=file:///tmp/image",
        "codex_image=http://user:password@localhost",
        "codex_image=http://localhost?token=private",
    ):
        with pytest.raises(ValueError):
            load_plugin(invalid)
