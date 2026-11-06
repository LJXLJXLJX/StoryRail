"""conftest 公共工厂的自测：验证 fixture 本身可用（P1-T1 验收）。"""

from __future__ import annotations

from core.model_providers.boundary import GenerationPhase


def test_store_factory_creates_project(store_factory):
    store = store_factory()
    document = store.read()
    assert store.path.is_file()
    assert document.revision == 1
    assert document.title == "测试项目"


def test_http_server_serves_projects_list(http_server):
    status, body = http_server.request("GET", "/api/projects")
    assert status == 200
    assert body == {"projects": []}


def test_synthetic_provider_produces_wav(synthetic_provider, wav_bytes):
    provider = synthetic_provider(media_type="audio/wav", content=wav_bytes)
    handle = provider.submit(object())
    running = provider.observe(handle)
    assert running.phase is GenerationPhase.RUNNING
    succeeded = provider.observe(handle)
    assert succeeded.phase is GenerationPhase.SUCCEEDED
    assert succeeded.artifact is not None
    assert provider.read_artifact(handle, succeeded.artifact.artifact_id) == wav_bytes


def test_synthetic_provider_repeats_final_phase(synthetic_provider):
    provider = synthetic_provider(
        media_type="image/png",
        content=b"\x89PNG\r\n\x1a\nframe",
        phases=[GenerationPhase.SUCCEEDED],
    )
    first = provider.observe(provider.submit(object()))
    second = provider.observe(provider.submit(object()))
    assert first.phase is GenerationPhase.SUCCEEDED
    assert second.phase is GenerationPhase.SUCCEEDED
