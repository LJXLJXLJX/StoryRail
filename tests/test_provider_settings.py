"""全局 Provider 设置：manifest 校验、能力绑定、插件设置、提交快照与设置 HTTP API。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from provider_factory import _VideoRecipeAdapter

from core.model_providers.boundary import (
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.codex_image import MANIFEST as CODEX_MANIFEST
from core.model_providers.manifest import (
    Capability,
    Field,
    Option,
    PluginManifest,
    ProviderSnapshot,
    Recipe,
    Role,
    Slot,
    Widget,
)
from core.model_providers.minimax_h3 import MANIFEST as H3_MANIFEST
from core.model_providers.minimax_h3 import render_settings
from core.model_providers.minimax_h3.render import H3RenderSettings, H3Resolution
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.model_providers.settings import ProviderSettingsStore
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService
from server.api import StoryRailApi

AGY_MANIFEST = PluginManifest(
    plugin_id="agy_image",
    plugin_version=1,
    label="AGY 图片",
    recipes=(
        Recipe("agy_image.generate", Capability.IMAGE_GENERATE, "生图"),
        Recipe("agy_image.edit", Capability.IMAGE_EDIT, "改图"),
    ),
)


@dataclass
class RecordingImageProvider:
    name: str
    plugin_version: int = 1
    calls: list[tuple[str, str]] = field(default_factory=list)

    @property
    def generate_plugin_id(self) -> str:
        return f"{self.name}.image.generate"

    @property
    def edit_plugin_id(self) -> str:
        return f"{self.name}.image.edit"

    def submit_recipe(self, request):
        return (
            self.submit_edit(request)
            if request.recipe_id.endswith(".edit")
            else self.submit_generate(request)
        )

    def submit_generate(self, _request: object) -> ProviderHandle:
        self.calls.append(("submit", self.name))
        return ProviderHandle(self.generate_plugin_id, 1, f"{self.name}-request")

    def submit_edit(self, _request: object) -> ProviderHandle:
        return ProviderHandle(self.edit_plugin_id, 1, f"{self.name}-edit")

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        self.calls.append(("observe", handle.external_id))
        return GenerationObservation(GenerationPhase.RUNNING, 0.5, self.name)

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        self.calls.append(("cancel", handle.external_id))
        return GenerationObservation(GenerationPhase.CANCELLED, 0.5, self.name)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        self.calls.append(("read", handle.external_id))
        return f"{self.name}:{artifact_id}".encode()


def _image_plugin(manifest: PluginManifest, provider: RecordingImageProvider) -> PluginInstance:
    return PluginInstance(manifest, recipes={recipe.id: provider for recipe in manifest.recipes})


def _image_request(prepared):
    from core.model_providers.recipe import RecipeRequest

    return RecipeRequest(prepared.recipe.id, (), ())


def _handle_provider(registry, handle):
    found = registry.resolve_plugin(
        handle.plugin_id, handle.plugin_version, capabilities=("image.generate", "image.edit")
    )
    if found is None:
        raise ModelProviderError("invalid_handle", "句柄不属于已安装图片插件。")
    return found


@dataclass
class RecordingVideoProvider:
    plugin_id: str = "minimax.h3.fl2va"
    plugin_version: int = 1

    def submit(self, _request: object) -> ProviderHandle:
        return ProviderHandle(self.plugin_id, self.plugin_version, "video")

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        return GenerationObservation(GenerationPhase.RUNNING, 0.5, "video")

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        return b""


def _registry(tmp_path: Path) -> tuple[ProviderRegistry, RecordingImageProvider, ...]:
    codex = RecordingImageProvider("codex")
    agy = RecordingImageProvider("agy")
    registry = ProviderRegistry(ProviderSettingsStore(tmp_path / "providers.json"))
    registry.install(_image_plugin(CODEX_MANIFEST, codex))
    registry.install(_image_plugin(AGY_MANIFEST, agy))
    return registry, codex, agy


# ---------------------------------------------------------------- manifest


def test_manifest_rejects_inconsistent_declarations() -> None:
    with pytest.raises(ValueError, match="选项"):
        Field("mode", Widget.ENUM, "模式", default="a")
    with pytest.raises(ValueError, match="取值不受支持"):
        Field("mode", Widget.ENUM, "模式", default="b", options=(Option("a", "A"),))
    with pytest.raises(ValueError, match="数量范围"):
        Slot("images", Role.REFERENCE_IMAGE, "图", minimum=2, maximum=1)
    with pytest.raises(ValueError, match="require_any"):
        Recipe("x.y", Capability.VIDEO_GENERATE, "Y", require_any=("first_frame",))
    with pytest.raises(ValueError, match="命名空间"):
        Recipe(
            "x.y",
            Capability.VIDEO_GENERATE,
            "Y",
            slots=(Slot("first", Role.FIRST_FRAME, "首帧", namespace="picture"),),
        )
    with pytest.raises(ValueError, match="不重复"):
        PluginManifest(
            "x",
            1,
            "X",
            recipes=(
                Recipe("x.a", Capability.IMAGE_GENERATE, "A"),
                Recipe("x.a", Capability.IMAGE_EDIT, "B"),
            ),
        )


def test_settings_validation_is_exact_and_typed() -> None:
    defaults = H3_MANIFEST.default_settings()
    assert defaults == {
        "preset": "hybrid_v2",
        "resolution": "720p",
        "sage_attention": True,
        "selflift": True,
    }
    assert H3_MANIFEST.validate_settings(defaults) == defaults
    for invalid in (
        {**defaults, "preset": "unknown"},
        {**defaults, "resolution": "4k"},
        {**defaults, "selflift": 1},
        {**defaults, "extra": True},
        {"preset": "turbo_v2"},
        [],
    ):
        with pytest.raises(ValueError):
            H3_MANIFEST.validate_settings(invalid)


def test_h3_preset_binds_base_model_and_steps() -> None:
    assert render_settings(H3_MANIFEST.default_settings()) == H3RenderSettings()
    turbo = {**H3_MANIFEST.default_settings(), "preset": "turbo_v2", "resolution": "1080p"}
    assert render_settings(turbo) == H3RenderSettings(H3Resolution.P1080, 8, True, True)
    assert H3_MANIFEST.settings_summary(turbo) == "Turbo V2 · 8 步 · 1080p · Sage · SelfLift"
    assert H3_MANIFEST.hint("soft_duration_limit_seconds") == 15


def test_h3_render_canvas_tiers_follow_the_32_pixel_grid() -> None:
    expected = {
        H3Resolution.P480: (864, 480),
        H3Resolution.P720: (1280, 704),
        H3Resolution.P1080: (1920, 1088),
    }
    for resolution, (width, height) in expected.items():
        settings = H3RenderSettings(resolution)
        assert settings.canvas("16:9") == (width, height)
        assert settings.canvas("9:16") == (height, width)
        assert (width % 32, height % 32) == (0, 0)
    wide = {
        H3Resolution.P480: (960, 480),
        H3Resolution.P720: (1408, 704),
        H3Resolution.P1080: (1920, 960),
    }
    for resolution, (width, height) in wide.items():
        assert H3RenderSettings(resolution).canvas("2:1") == (width, height)
        assert (width % 32, height % 32) == (0, 0)


def test_snapshot_round_trips_and_rejects_unsorted_settings() -> None:
    snapshot = ProviderSnapshot.build(
        H3_MANIFEST, "minimax_h3.ref2va", H3_MANIFEST.default_settings()
    )
    assert ProviderSnapshot.from_json(snapshot.to_json()) == snapshot
    assert snapshot.summary == "DaSiWa Hybrid V2 · 20 步 · 720p · Sage · SelfLift"
    with pytest.raises(ValueError, match="排序"):
        ProviderSnapshot("minimax_h3", "minimax_h3.fl2va", (("z", 1), ("a", 2)))
    with pytest.raises(ValueError, match="recipe"):
        ProviderSnapshot.build(H3_MANIFEST, "minimax_h3.unknown", {})


# ---------------------------------------------------------------- 绑定


def test_binding_persists_and_new_submissions_use_bound_plugin(tmp_path) -> None:
    registry, codex, agy = _registry(tmp_path)

    first = registry.prepare_recipe(Capability.IMAGE_GENERATE)
    assert first.snapshot.plugin_id == "codex_image"
    assert first.submit(_image_request(first)).plugin_id == "codex.image.generate"
    registry.bind("image.generate", "agy_image")
    second = registry.prepare_recipe(Capability.IMAGE_GENERATE)
    assert second.snapshot == ProviderSnapshot("agy_image", "agy_image.generate")
    assert second.submit(_image_request(second)).plugin_id == "agy.image.generate"
    # 生图与改图是两个能力，各自绑定。
    assert registry.prepare_recipe(Capability.IMAGE_EDIT).snapshot.plugin_id == "codex_image"

    restarted = ProviderRegistry(ProviderSettingsStore(tmp_path / "providers.json"))
    restarted.install(_image_plugin(CODEX_MANIFEST, RecordingImageProvider("codex")))
    restarted.install(_image_plugin(AGY_MANIFEST, RecordingImageProvider("agy")))
    assert restarted.prepare_recipe(Capability.IMAGE_GENERATE).snapshot.plugin_id == "agy_image"


def test_history_routes_by_handle_after_global_switch(tmp_path) -> None:
    registry, codex, agy = _registry(tmp_path)
    prepared = registry.prepare_recipe(Capability.IMAGE_GENERATE)
    old = prepared.submit(_image_request(prepared))
    registry.bind("image.generate", "agy_image")
    prepared = registry.prepare_recipe(Capability.IMAGE_GENERATE)
    new = prepared.submit(_image_request(prepared))

    assert _handle_provider(registry, old).observe(old).message == "codex"
    assert _handle_provider(registry, new).read_artifact(new, "asset") == b"agy:asset"
    assert ("observe", "codex-request") in codex.calls
    assert ("read", "agy-request") in agy.calls
    assert (
        registry.resolve_plugin(
            "codex.image.generate", 1, capabilities=("image.generate", "image.edit")
        )
        is codex
    )


def test_binding_rejects_unknown_capability_plugin_and_handle(tmp_path) -> None:
    registry, _codex, _agy = _registry(tmp_path)
    with pytest.raises(ValueError, match="不受支持"):
        registry.bind("image.paint", "codex_image")
    with pytest.raises(ValueError, match="未安装或不实现"):
        registry.bind("image.generate", "unknown")
    with pytest.raises(ValueError, match="未安装或不实现"):
        registry.bind("video.generate", "codex_image")
    with pytest.raises(ModelProviderError, match="不属于"):
        _handle_provider(registry, ProviderHandle("unknown.image.generate", 1, "x"))


def test_binding_to_uninstalled_plugin_makes_capability_unavailable(tmp_path) -> None:
    registry, _codex, _agy = _registry(tmp_path)
    registry.bind("image.generate", "agy_image")
    restarted = ProviderRegistry(ProviderSettingsStore(tmp_path / "providers.json"))
    restarted.install(_image_plugin(CODEX_MANIFEST, RecordingImageProvider("codex")))

    assert restarted.capability_available(Capability.IMAGE_GENERATE) is False
    with pytest.raises(RuntimeError, match="agy_image 当前未安装"):
        restarted.prepare_recipe(Capability.IMAGE_GENERATE)
    capability = next(
        item for item in restarted.describe()["capabilities"] if item["id"] == "image.generate"
    )
    assert capability["bound_plugin_id"] is None
    assert "agy_image" in capability["message"]


def test_settings_update_is_validated_snapshotted_and_invalid_storage_falls_back(
    tmp_path,
) -> None:
    store = ProviderSettingsStore(tmp_path / "providers.json")
    registry = ProviderRegistry(store)
    registry.install(
        PluginInstance(
            H3_MANIFEST, recipes={"minimax_h3.fl2va": _VideoRecipeAdapter(RecordingVideoProvider())}
        )
    )
    turbo = {**H3_MANIFEST.default_settings(), "preset": "turbo_v2"}
    assert registry.update_plugin_settings("minimax_h3", turbo) == turbo
    assert registry.prepare_recipe(Capability.VIDEO_GENERATE).snapshot.settings == tuple(
        sorted(turbo.items())
    )
    with pytest.raises(ValueError, match="多出"):
        registry.update_plugin_settings("minimax_h3", {**turbo, "steps": 8})
    with pytest.raises(ValueError, match="未安装"):
        registry.update_plugin_settings("unknown", turbo)

    raw = json.loads((tmp_path / "providers.json").read_text(encoding="utf-8"))
    raw["settings"]["minimax_h3"]["preset"] = "retired_model"
    (tmp_path / "providers.json").write_text(json.dumps(raw), encoding="utf-8")
    restarted = ProviderRegistry(ProviderSettingsStore(tmp_path / "providers.json"))
    restarted.install(
        PluginInstance(
            H3_MANIFEST, recipes={"minimax_h3.fl2va": _VideoRecipeAdapter(RecordingVideoProvider())}
        )
    )
    assert restarted.plugin_settings("minimax_h3") == H3_MANIFEST.default_settings()
    plugin = restarted.describe()["plugins"][0]
    assert "不兼容" in plugin["settings_error"]
    # 不兼容的旧值原样保留，直到人类重新保存。
    stored = json.loads((tmp_path / "providers.json").read_text(encoding="utf-8"))
    assert stored["settings"]["minimax_h3"]["preset"] == "retired_model"


def test_settings_file_is_strict(tmp_path) -> None:
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"schema_version": 1, "bindings": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="不合法"):
        ProviderSettingsStore(path)


def test_plugin_instance_rejects_mismatched_recipe(tmp_path) -> None:
    with pytest.raises(ValueError, match="execute_recipe"):
        PluginInstance(
            PluginManifest(
                "sync", 1, "转写", (Recipe("sync.transcribe", Capability.SPEECH_RECOGNIZE, "转写"),)
            ),
            recipes={"sync.transcribe": RecordingImageProvider("codex")},
        )
    with pytest.raises(ValueError, match="没有 recipe"):
        PluginInstance(CODEX_MANIFEST, recipes={"paint.unknown": RecordingImageProvider("codex")})


def test_provider_settings_http_is_strict_and_persistent(tmp_path) -> None:
    async def scenario() -> None:
        workspaces = ProjectWorkspaceStore(tmp_path)
        registry, _codex, _agy = _registry(tmp_path)
        registry.install(
            PluginInstance(
                H3_MANIFEST,
                recipes={"minimax_h3.fl2va": _VideoRecipeAdapter(RecordingVideoProvider())},
            )
        )
        api = StoryRailApi(
            workspaces,
            lambda project_id: StructuredDirectorService(
                workspaces.structured_director_store(project_id), registry
            ),
            provider_registry=registry,
        )
        listed = await api.handle("GET", "/api/settings/providers")
        assert listed.status == 200
        image = next(item for item in listed.body["capabilities"] if item["id"] == "image.generate")
        assert image["bound_plugin_id"] == "codex_image"
        assert [item["plugin_id"] for item in image["candidates"]] == ["codex_image", "agy_image"]
        h3 = next(item for item in listed.body["plugins"] if item["plugin_id"] == "minimax_h3")
        assert h3["manifest"]["settings"][0]["key"] == "preset"
        assert h3["settings_summary"] == "DaSiWa Hybrid V2 · 20 步 · 720p · Sage · SelfLift"

        bound = await api.handle(
            "PUT",
            "/api/settings/providers/bindings",
            json.dumps({"capability": "image.generate", "plugin_id": "agy_image"}).encode(),
        )
        assert bound.status == 200
        turbo = {**H3_MANIFEST.default_settings(), "preset": "turbo_v2", "selflift": False}
        changed = await api.handle(
            "PUT",
            "/api/settings/providers/plugins/minimax_h3",
            json.dumps({"settings": turbo}).encode(),
        )
        assert changed.status == 200
        stored = json.loads((tmp_path / "providers.json").read_text(encoding="utf-8"))
        assert stored["bindings"] == {"image.generate": "agy_image"}
        assert stored["settings"]["minimax_h3"] == turbo

        for path, body in (
            ("/api/settings/providers/bindings", {"capability": "image.generate"}),
            (
                "/api/settings/providers/bindings",
                {"capability": "image.generate", "plugin_id": "agy_image", "extra": 1},
            ),
            ("/api/settings/providers/bindings", {"capability": "x", "plugin_id": "agy_image"}),
            ("/api/settings/providers/plugins/minimax_h3", {"settings": {"preset": "x"}}),
            ("/api/settings/providers/plugins/unknown", {"settings": {}}),
        ):
            response = await api.handle("PUT", path, json.dumps(body).encode())
            assert response.status == 400, (path, body)
        assert (await api.handle("PUT", "/api/settings/providers/other", b"{}")).status == 404
        assert registry.plugin_settings("minimax_h3") == turbo
        projects = await api.handle("GET", "/api/projects")
        assert set(projects.body) == {"projects"}

    asyncio.run(scenario())
