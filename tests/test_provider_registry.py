"""ProviderRegistry 的注册、能力解析和历史 plugin_id 路由。"""

from __future__ import annotations

from conftest import provider_registry
from structured_director_fixtures import RecordingProvider

from core.model_providers.manifest import Capability
from core.model_providers.registry import ProviderRegistry
from core.structured_director import StructuredDirectorService, StructuredDirectorStore


class _Provider:
    def __init__(
        self,
        plugin_id: str,
        *,
        version: int = 1,
        plugin_ids: frozenset[str] | None = None,
    ):
        self.plugin_id = plugin_id
        self.plugin_version = version
        if plugin_ids is not None:
            self.plugin_ids = plugin_ids


def test_resolve_returns_registered_provider() -> None:
    image = _Provider("image.generate")
    registry = ProviderRegistry()
    assert registry.resolve("final_assembly") is None
    registry.register("final_assembly", image)
    assert registry.resolve("final_assembly") is image
    assert registry.resolve_plugin("image.generate", 1) is image
    assert registry.resolve_plugin("image.generate", 2) is None


def test_plugin_route_can_be_limited_to_capabilities() -> None:
    fl2va = RecordingProvider(media_type="video/mp4", content=b"fixture")
    fl2va.plugin_id = "video.fl2va"
    image = _Provider("image.generate")
    registry = provider_registry(fl2va_provider=fl2va)
    registry.register("final_assembly", image)
    assert (
        registry.resolve_plugin("video.fl2va", 1, capabilities=("video.generate",)).provider
        is fl2va
    )
    assert registry.resolve_plugin("image.generate", 1, capabilities=("video.generate",)) is None


def test_selection_strategy_is_found_by_each_plugin_id() -> None:
    codex = _Provider("codex.generate")
    registry = ProviderRegistry()
    registry.register(
        "final_assembly",
        _Provider("unused", plugin_ids=frozenset({"codex.generate", "agy.generate"})),
    )
    assert registry.resolve_plugin("agy.generate", 1) is registry.resolve("final_assembly")
    assert registry.resolve_plugin("codex.generate", 1) is not codex


def test_duplicate_capability_is_rejected_and_shared_plugin_id_stays_ambiguous() -> None:
    registry = ProviderRegistry()
    shared = _Provider("speech.main")
    registry.register("final_assembly", shared)
    try:
        registry.register("final_assembly", _Provider("speech.other"))
    except ValueError as exc:
        assert "已注册" in str(exc)
    else:
        raise AssertionError("重复能力必须拒绝。")
    other = _Provider("speech.main")
    registry.register("animatic", other)
    assert registry.resolve_plugin("speech.main", 1) is None
    assert registry.resolve_plugin("speech.main", 1, capabilities=("final_assembly",)) is shared
    assert registry.resolve_plugin("speech.main", 1, capabilities=("animatic",)) is other


def test_service_accepts_only_registry_construction(tmp_path) -> None:
    image = _Provider("test.image")
    registry = provider_registry(final_assembly_provider=image)
    assert registry.resolve("final_assembly") is image
    assert not registry.capability_available(Capability.VIDEO_UPSCALE)

    project = tmp_path / "project"
    project.mkdir()
    store = StructuredDirectorStore(project, "a" * 32)
    service = StructuredDirectorService(store, registry)
    assert service._final_assembly_provider is image
    assert not service._registry.capability_available(Capability.VIDEO_GENERATE)

    empty = StructuredDirectorService(store)
    assert empty._final_assembly_provider is None
    try:
        StructuredDirectorService(store, image_provider=image)
    except TypeError as exc:
        assert "unexpected keyword argument" in str(exc)
    else:
        raise AssertionError("Service 只接受 registry 构造。")
