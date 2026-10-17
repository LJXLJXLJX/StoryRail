"""PG2-T2：Playground 异步能力提交、提交失败分类与重试链接。"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from core.model_providers.boundary import (
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
)
from core.model_providers.manifest import Capability
from core.model_providers.registry import PluginInstance
from core.model_providers.whisper_asr.manifest import MANIFEST as ASR_MANIFEST
from core.playground.errors import (
    ProviderUnavailableError,
    RunNotFoundError,
    RunStateConflictError,
)
from core.playground.lifecycle import utc_timestamp
from core.playground.models import AssetOrigin, PlaygroundRun, RunPhase, canonical_json
from core.playground.service import PlaygroundService
from tests.playground_fixtures import png_header_bytes, real_mp4_bytes
from tests.playground_recipes import PlaygroundCapability, recipe_for
from tests.provider_factory import _RecipeAdapter

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42candidate"


def wav(duration_seconds: float = 1.0) -> bytes:
    import io
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(b"\x00\x00" * int(duration_seconds * 8_000))
    return output.getvalue()


WAV = wav()


def ingest(
    service: PlaygroundService,
    media_type: str,
    content: bytes,
    *,
    label: str = "素材",
    duration_seconds: float | None = None,
):
    store = service.store
    holder: dict[str, object] = {}

    def mutate(previous):
        updated, asset = store.ingest_asset(
            previous,
            media_type=media_type,
            content=content,
            origin_dir="imported",
            label=label,
            origin=AssetOrigin("imported"),
            created_at=utc_timestamp(),
            duration_seconds=duration_seconds,
        )
        holder["asset"] = asset
        return replace(updated, revision=previous.revision + 1)

    store.commit(mutate)
    return holder["asset"]


def providers(**overrides) -> dict[str, object]:
    from tests.conftest import SyntheticProvider

    base: dict[str, object] = {
        "image_provider": SyntheticProvider(
            media_type="image/png", content=PNG, plugin_id="test.image"
        ),
        "voice_provider": SyntheticProvider(
            media_type="audio/wav", content=WAV, plugin_id="test.voice"
        ),
        "speech_provider": SyntheticProvider(
            media_type="audio/wav", content=WAV, plugin_id="test.speech"
        ),
        "fl2va_provider": SyntheticProvider(
            media_type="video/mp4",
            content=MP4,
            duration_seconds=6.0,
            plugin_id="test.fl2va",
        ),
        "ref2va_provider": SyntheticProvider(
            media_type="video/mp4",
            content=MP4,
            duration_seconds=6.0,
            plugin_id="test.ref2va",
        ),
        "upscale_provider": SyntheticProvider(
            media_type="video/mp4",
            content=MP4,
            duration_seconds=6.0,
            plugin_id="test.upscale",
        ),
        "video_frame_provider": SyntheticProvider(
            media_type="image/png", content=PNG, plugin_id="test.frame"
        ),
        "pano_view_provider": SyntheticProvider(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + b"pano-view",
            plugin_id="test.pano",
        ),
        "audio_separation_provider": SyntheticProvider(
            media_type="audio/wav", content=WAV, plugin_id="test.separate"
        ),
        "text_to_audio_provider": SyntheticProvider(
            media_type="audio/wav", content=WAV, plugin_id="test.audio"
        ),
        "audio_remix_provider": SyntheticProvider(
            media_type="video/mp4",
            content=MP4,
            duration_seconds=6.0,
            plugin_id="test.remix",
        ),
    }
    base.update(overrides)
    return base


def parameters_for(capability: PlaygroundCapability, assets: dict[str, object]) -> dict:
    image_id = assets["image"].id
    wav_id = assets["wav"].id
    video_id = assets["video"].id
    frame_id = assets["frames"].id
    pano_id = assets["pano"].id
    return {
        PlaygroundCapability.IMAGE_GENERATE: {
            "prompt": "雨夜街道",
            "aspect_ratio": "16:9",
            "reference_image_asset_ids": [],
        },
        PlaygroundCapability.IMAGE_EDIT: {
            "prompt": "改成白天",
            "aspect_ratio": "16:9",
            "source_image_asset_id": image_id,
            "reference_image_asset_ids": [],
        },
        PlaygroundCapability.TTS_VOICE_DESIGN: {
            "text": "你好",
            "voice_description": "中年男声",
            "seed": 42,
        },
        PlaygroundCapability.TTS_VOICE_CLONE: {
            "text": "你好",
            "voice_asset_id": wav_id,
            "reference_transcript": "你好",
            "performance_instruction": None,
            "seed": 42,
        },
        PlaygroundCapability.VIDEO_FL2VA: {
            "prompt": "镜头推近",
            "aspect_ratio": "16:9",
            "duration_seconds": 6.0,
            "seed": 1234,
            "first_frame_asset_id": image_id,
            "last_frame_asset_id": None,
        },
        PlaygroundCapability.VIDEO_REF2VA: {
            "prompt": "<Picture 1> 镜头推近",
            "aspect_ratio": "16:9",
            "duration_seconds": 6.0,
            "seed": 99,
            "first_frame_asset_id": image_id,
            "last_frame_asset_id": None,
            "additional_images": [],
            "reference_audios": [],
            "reference_videos": [],
        },
        PlaygroundCapability.VIDEO_UPSCALE: {"video_asset_id": video_id, "seed": 42},
        PlaygroundCapability.VIDEO_EXTRACT_FRAME: {
            "video_asset_id": frame_id,
            "frame_index": 0,
        },
        PlaygroundCapability.IMAGE_PANO_VIEW: {
            "image_asset_id": pano_id,
            "yaw_deg": 90,
            "pitch_deg": 0,
            "hfov_deg": 90,
            "aspect_ratio": "16:9",
        },
        PlaygroundCapability.AUDIO_SEPARATE: {"video_asset_id": video_id, "stem": "voice"},
        PlaygroundCapability.AUDIO_GENERATE: {
            "prompt": "安静的钢琴",
            "duration_seconds": 10,
            "seed": 7,
        },
        PlaygroundCapability.AUDIO_REMIX: {
            "video_asset_id": video_id,
            "voice_asset_id": wav_id,
            "background_asset_id": wav_id,
            "voice_gain_db": 0.0,
            "background_gain_db": -6.0,
            "voice_gain_start_seconds": None,
            "voice_gain_end_seconds": None,
            "background_gain_start_seconds": None,
            "background_gain_end_seconds": None,
        },
    }[capability]


ASYNC_CAPABILITIES = (
    PlaygroundCapability.IMAGE_GENERATE,
    PlaygroundCapability.IMAGE_EDIT,
    PlaygroundCapability.TTS_VOICE_DESIGN,
    PlaygroundCapability.TTS_VOICE_CLONE,
    PlaygroundCapability.VIDEO_FL2VA,
    PlaygroundCapability.VIDEO_REF2VA,
    PlaygroundCapability.VIDEO_UPSCALE,
    PlaygroundCapability.VIDEO_EXTRACT_FRAME,
    PlaygroundCapability.IMAGE_PANO_VIEW,
    PlaygroundCapability.AUDIO_SEPARATE,
    PlaygroundCapability.AUDIO_GENERATE,
    PlaygroundCapability.AUDIO_REMIX,
)


def build(playground_factory, **overrides):
    service = playground_factory(**providers(**overrides))
    assets = {
        "image": ingest(service, "image/png", PNG, label="首帧"),
        "wav": ingest(service, "audio/wav", WAV, label="音色"),
        "video": ingest(service, "video/mp4", MP4, label="来源", duration_seconds=6.0),
        "frames": ingest(
            service,
            "video/mp4",
            real_mp4_bytes(48, 2.0),
            label="抽帧来源",
            duration_seconds=2.0,
        ),
        "pano": ingest(service, "image/png", png_header_bytes(2048, 1024), label="全景"),
    }
    return service, assets


def test_submit_each_async_capability_reaches_queued(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        for capability in ASYNC_CAPABILITIES:
            run = await service.submit_run(
                capability.value,
                parameters_for(capability, assets),
                note=None,
            )
            assert run.capability == capability
            assert run.phase is RunPhase.QUEUED
            assert run.external_id
            assert run.plugin_id
            assert run.output_asset_id is None
            assert run.retry_of is None
            assert service.snapshot().revision >= 2

    asyncio.run(scenario())


def test_submit_records_provider_request_type(playground_factory) -> None:
    from core.model_providers.minimax_h3.contracts import FL2VARequest, Ref2VARequest
    from core.model_providers.recipe import RecipeRequest as ImageGenerateRequest

    async def scenario() -> None:
        fl2va = playground_factory(**providers())
        assets = {
            "image": ingest(fl2va, "image/png", PNG, label="首帧"),
        }
        await fl2va.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            {
                "prompt": "雨夜街道",
                "aspect_ratio": "16:9",
                "reference_image_asset_ids": [assets["image"].id],
            },
            note=None,
        )
        assert isinstance(
            fl2va.registry.prepare_recipe(Capability.IMAGE_GENERATE)
            .plugin.recipes["codex_image.generate"]
            .provider.requests[0],
            ImageGenerateRequest,
        )

        service, assets = build(playground_factory)
        await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        assert isinstance(
            service.registry.prepare_recipe(Capability.VIDEO_GENERATE, recipe_id="minimax_h3.fl2va")
            .plugin.recipes["minimax_h3.fl2va"]
            .provider.requests[0],
            FL2VARequest,
        )
        await service.submit_run(
            PlaygroundCapability.VIDEO_REF2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_REF2VA, assets),
            note=None,
        )
        assert isinstance(
            service.registry.prepare_recipe(
                Capability.VIDEO_GENERATE, recipe_id="minimax_h3.ref2va"
            )
            .plugin.recipes["minimax_h3.ref2va"]
            .provider.requests[0],
            Ref2VARequest,
        )

    asyncio.run(scenario())


def test_submit_unavailable_capability_rejected(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        availability = service.capability_availability()
        assert availability[PlaygroundCapability.AUDIO_EFFECT] is True
        assert availability[PlaygroundCapability.AUDIO_TRIM] is True
        assert availability.get(PlaygroundCapability.VIDEO_FL2VA, False) is False
        with pytest.raises(ProviderUnavailableError, match="对应 recipe 未配置。"):
            await service.submit_run(
                PlaygroundCapability.VIDEO_FL2VA.value,
                {
                    "prompt": "镜头推近",
                    "aspect_ratio": "16:9",
                    "duration_seconds": 6.0,
                    "seed": 1,
                    "first_frame_asset_id": "a" * 32,
                    "last_frame_asset_id": None,
                },
                note=None,
            )
        with pytest.raises(ProviderUnavailableError, match="对应 recipe 未配置"):
            await service.submit_run("video.nope", {}, note=None)

    asyncio.run(scenario())


def test_submit_rejection_marks_failed_submission_rejected(playground_factory) -> None:
    class Rejecting:
        plugin_id = "test.reject"
        plugin_version = 1

        def submit(self, request: object):
            raise ModelProviderError("external_error", "服务拒绝请求")

    async def scenario() -> None:
        service, assets = build(playground_factory, fl2va_provider=Rejecting())
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        assert run.phase is RunPhase.FAILED
        assert run.error_code == "submission_rejected"
        assert "服务明确拒绝了请求" in run.message

    asyncio.run(scenario())


def test_submit_transport_error_marks_uncertain(playground_factory) -> None:
    class Unreachable:
        plugin_id = "test.unreachable"
        plugin_version = 1

        def submit(self, request: object):
            raise ModelProviderError("transport_error", "网络中断")

    async def scenario() -> None:
        service, assets = build(playground_factory, fl2va_provider=Unreachable())
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        assert run.phase is RunPhase.SUBMISSION_UNCERTAIN
        assert run.error_code == "transport_error"

    asyncio.run(scenario())


def test_auto_retry_link_after_failure_with_same_parameters(playground_factory) -> None:
    class Flaky:
        plugin_id = "test.flaky"
        plugin_version = 1

        def __init__(self) -> None:
            self.fail = True

        def submit(self, request: object):
            from core.model_providers.boundary import ProviderHandle

            if self.fail:
                self.fail = False
                raise ModelProviderError("external_error", "服务拒绝请求")
            return ProviderHandle(self.plugin_id, self.plugin_version, "external-2")

    async def scenario() -> None:
        provider = Flaky()
        service, assets = build(playground_factory, fl2va_provider=provider)
        parameters = parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets)
        failed = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value, parameters, note=None
        )
        assert failed.phase is RunPhase.FAILED
        retried = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value, parameters, note=None
        )
        assert retried.phase is RunPhase.QUEUED
        assert retried.retry_of == failed.id

    asyncio.run(scenario())


def test_explicit_retry_keeps_parameters_and_links(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note="第一次",
        )
        assert run.phase is RunPhase.QUEUED
        cancelled = service._mutate_run(
            run.id,
            lambda current, _document: replace(current, phase=RunPhase.CANCELLED, error_code=None),
        )
        assert cancelled.phase is RunPhase.CANCELLED
        retried = await service.retry_run(run.id)
        assert retried.retry_of == run.id
        assert retried.parameters == run.parameters
        assert retried.note == "第一次"
        assert retried.id != run.id

        with pytest.raises(RunStateConflictError, match="只有失败、已取消或提交结果未知"):
            await service.retry_run(retried.id)

    asyncio.run(scenario())


def test_retry_rejects_when_input_deleted(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_EDIT.value,
            parameters_for(PlaygroundCapability.IMAGE_EDIT, assets),
            note=None,
        )
        service._mutate_run(
            run.id,
            lambda current, _document: replace(current, phase=RunPhase.CANCELLED, error_code=None),
        )
        service.store.commit(
            lambda previous: replace(
                previous,
                revision=previous.revision + 1,
                assets=tuple(asset for asset in previous.assets if asset.id != assets["image"].id),
            )
        )
        with pytest.raises(RunStateConflictError, match="输入 Asset 已删除"):
            await service.retry_run(run.id)

    asyncio.run(scenario())


def test_duplicate_active_frame_extraction_rejected(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        parameters = parameters_for(PlaygroundCapability.VIDEO_EXTRACT_FRAME, assets)
        await service.submit_run(
            PlaygroundCapability.VIDEO_EXTRACT_FRAME.value, parameters, note=None
        )
        with pytest.raises(RunStateConflictError, match="已有抽帧任务在进行中"):
            await service.submit_run(
                PlaygroundCapability.VIDEO_EXTRACT_FRAME.value, parameters, note=None
            )
        # 冲突按来源视频判定，与帧号无关；换一段视频可以继续提交。
        other_video = ingest(
            service,
            "video/mp4",
            real_mp4_bytes(32, 1.0),
            label="另一段来源",
            duration_seconds=1.0,
        )
        second = await service.submit_run(
            PlaygroundCapability.VIDEO_EXTRACT_FRAME.value,
            {"video_asset_id": other_video.id, "frame_index": 1},
            note=None,
        )
        assert second.phase is RunPhase.QUEUED

    asyncio.run(scenario())


def test_service_startup_recovers_submitting_runs(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        store = service.store
        timestamp = utc_timestamp()
        run = PlaygroundRun(
            id="5c9e1a2b3c4d5e6f708192a3b4c5d6e7",
            capability=PlaygroundCapability.VIDEO_FL2VA,
            phase=RunPhase.SUBMITTING,
            progress=0.0,
            message="正在提交首尾帧视频任务。",
            parameters_json=canonical_json(
                parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets)
            ),
            input_asset_ids=(assets["image"].id,),
            seed=1234,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            result_json=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            note=None,
            dismissed=False,
            created_at=timestamp,
            updated_at=timestamp,
            recipe=recipe_for(PlaygroundCapability.VIDEO_FL2VA),
        )
        store.commit(
            lambda previous: replace(
                previous, revision=previous.revision + 1, runs=(*previous.runs, run)
            )
        )
        assert store.read().runs[-1].phase is RunPhase.SUBMITTING

        PlaygroundService(store, service.registry)
        recovered = store.read().runs[-1]
        assert recovered.phase is RunPhase.SUBMISSION_UNCERTAIN
        assert recovered.error_code == "core_restarted_during_submit"

    asyncio.run(scenario())


def test_submit_reports_observation_phase_sequence(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        provider = (
            service.registry.prepare_recipe(Capability.VIDEO_GENERATE, recipe_id="minimax_h3.fl2va")
            .plugin.recipes["minimax_h3.fl2va"]
            .provider
        )
        provider.observations = [GenerationPhase.RUNNING, GenerationPhase.SUCCEEDED]
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        assert run.phase is RunPhase.QUEUED
        assert service.capability_availability()[PlaygroundCapability.VIDEO_FL2VA] is True

    asyncio.run(scenario())


# ------------------------------------------------------------------ PG2-T3


def _queued(service, capability, assets):
    return asyncio.run(
        service.submit_run(capability.value, parameters_for(capability, assets), note=None)
    )


def test_observe_success_ingests_output_asset_with_run_origin(playground_factory) -> None:
    async def scenario() -> None:
        from tests.conftest import SyntheticProvider

        service, assets = build(
            playground_factory,
            image_provider=SyntheticProvider(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\n" + b"generated",
                plugin_id="test.image",
            ),
        )
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        running = await service.refresh_run(run.id)
        assert running.phase is RunPhase.RUNNING
        revision_before = service.snapshot().revision
        final = await service.refresh_run(run.id)
        assert final.phase is RunPhase.SUCCEEDED
        assert final.progress == 1.0
        assert final.output_asset_id
        document = service.snapshot()
        assert document.revision == revision_before + 1
        asset = next(item for item in document.assets if item.id == final.output_asset_id)
        assert asset.origin.kind == "run_output"
        assert asset.origin.run_id == run.id
        assert asset.relative_path.startswith("assets/images/runs/生图-")
        assert asset.media_type == "image/png"

    asyncio.run(scenario())


def test_observe_rejects_unexpected_media_type_as_import_failed(playground_factory) -> None:
    from core.model_providers.boundary import ProviderHandle

    class WrongArtifact:
        plugin_id = "test.wrong"
        plugin_version = 1

        def submit_generate(self, request: object):
            return ProviderHandle(self.plugin_id, self.plugin_version, "external-wrong")

        def observe(self, handle):
            import hashlib

            from core.model_providers.boundary import ArtifactDescriptor

            return GenerationObservation(
                GenerationPhase.SUCCEEDED,
                1.0,
                "完成",
                ArtifactDescriptor(
                    "artifact-1",
                    "video/mp4",
                    len(MP4),
                    hashlib.sha256(MP4).hexdigest(),
                    None,
                ),
            )

        def read_artifact(self, handle, artifact_id):
            return MP4

    async def scenario() -> None:
        service, assets = build(playground_factory, image_provider=WrongArtifact())
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        failed = await service.refresh_run(run.id)
        assert failed.phase is RunPhase.QUEUED
        assert failed.error_code == "artifact_import_failed"
        assert failed.output_asset_id is None
        assert "未能校验并导入产物" in failed.message

    asyncio.run(scenario())


def test_provider_unreachable_keeps_phase(playground_factory) -> None:
    class Unreachable:
        plugin_id = "test.unreachable"
        plugin_version = 1

        def submit(self, request: object):
            from core.model_providers.boundary import ProviderHandle

            return ProviderHandle(self.plugin_id, self.plugin_version, "external-unreachable")

        def observe(self, handle):
            raise ModelProviderError("transport_error", "节点不可达")

    async def scenario() -> None:
        service, assets = build(playground_factory, fl2va_provider=Unreachable())
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        unreachable = await service.refresh_run(run.id)
        assert unreachable.phase is RunPhase.QUEUED
        assert unreachable.error_code == "provider_unreachable"
        assert "模型节点暂时不可达" in unreachable.message

    asyncio.run(scenario())


def test_progress_only_observation_not_persisted_but_visible(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        provider = (
            service.registry.prepare_recipe(Capability.VIDEO_GENERATE, recipe_id="minimax_h3.fl2va")
            .plugin.recipes["minimax_h3.fl2va"]
            .provider
        )
        first = await service.refresh_run(run.id)
        assert first.phase is RunPhase.RUNNING
        revision = service.snapshot().revision

        provider.observations = [GenerationPhase.RUNNING]
        await service.refresh_run(run.id)
        assert service.snapshot().revision == revision
        persisted = service.snapshot().runs[-1]
        assert persisted.phase is RunPhase.RUNNING
        assert persisted.progress == 0.0
        shown = service.observed_run(persisted)
        assert shown.progress == 0.5
        assert shown.message == "生成中"

    asyncio.run(scenario())


def test_cancel_persists_intent_then_applies_observation(playground_factory) -> None:
    seen: dict[str, object] = {}

    from tests.conftest import SyntheticProvider

    class Capturing(SyntheticProvider):
        def __init__(self, store, **kwargs):
            super().__init__(**kwargs)
            self.store = store

        def cancel(self, handle):
            seen["intent"] = self.store.read().runs[-1].cancellation_requested
            return super().cancel(handle)

    async def scenario() -> None:
        service, assets = build(playground_factory)
        provider = Capturing(
            service.store,
            media_type="video/mp4",
            content=MP4,
            duration_seconds=6.0,
            plugin_id="test.capture",
        )
        from provider_factory import _VideoRecipeAdapter

        service.registry._plugins["minimax_h3"].recipes["minimax_h3.fl2va"] = _VideoRecipeAdapter(
            provider
        )
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_FL2VA.value,
            parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            note=None,
        )
        cancelled = await service.cancel_run(run.id)
        assert seen["intent"] is True
        assert cancelled.phase is RunPhase.CANCELLED
        assert cancelled.cancellation_requested is True

    asyncio.run(scenario())


def test_cancel_terminal_run_is_noop(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        service.registry.prepare_recipe(Capability.IMAGE_GENERATE).plugin.recipes[
            "codex_image.generate"
        ].provider.observations = [GenerationPhase.CANCELLED]
        cancelled = await service.refresh_run(run.id)
        assert cancelled.phase is RunPhase.CANCELLED
        revision = service.snapshot().revision
        again = await service.cancel_run(run.id)
        assert again.phase is RunPhase.CANCELLED
        assert service.snapshot().revision == revision

    asyncio.run(scenario())


def test_dismiss_requires_terminal(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        with pytest.raises(RunStateConflictError, match="只有已结束的实验可以隐藏"):
            await service.dismiss_run(run.id)

        service.registry.prepare_recipe(Capability.IMAGE_GENERATE).plugin.recipes[
            "codex_image.generate"
        ].provider.observations = [GenerationPhase.CANCELLED]
        await service.refresh_run(run.id)
        dismissed = await service.dismiss_run(run.id)
        assert dismissed.dismissed is True
        revision = service.snapshot().revision
        assert (await service.dismiss_run(run.id)).dismissed is True
        assert service.snapshot().revision == revision

    asyncio.run(scenario())


def test_set_note_roundtrip_and_clear(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        noted = await service.set_note(run.id, "  cfg 默认  ")
        assert noted.note == "cfg 默认"
        revision = service.snapshot().revision
        assert (await service.set_note(run.id, "cfg 默认")).note == "cfg 默认"
        assert service.snapshot().revision == revision
        assert (await service.set_note(run.id, "   ")).note is None
        assert (await service.set_note(run.id, None)).note is None

    asyncio.run(scenario())


def test_wait_runs_returns_when_all_terminal(playground_factory, monkeypatch) -> None:
    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", "2")
    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_POLL_SECONDS", "0.01")

    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        observed = await service.wait_runs((run.id, run.id))
        assert len(observed) == 1
        assert observed[0].phase is RunPhase.SUCCEEDED

        with pytest.raises(ValueError, match="1 到 8 个"):
            await service.wait_runs(())
        with pytest.raises(RunNotFoundError, match="实验不存在"):
            await service.wait_runs(("f" * 32,))

    asyncio.run(scenario())


def test_upscale_output_inherits_source_duration(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        provider = (
            service.registry.prepare_recipe(Capability.VIDEO_UPSCALE)
            .plugin.recipes["seedvr2_7b_sharp_fp8.upscale"]
            .provider
        )
        provider.duration_seconds = None
        run = await service.submit_run(
            PlaygroundCapability.VIDEO_UPSCALE.value,
            parameters_for(PlaygroundCapability.VIDEO_UPSCALE, assets),
            note=None,
        )
        await service.refresh_run(run.id)
        final = await service.refresh_run(run.id)
        assert final.phase is RunPhase.SUCCEEDED
        asset = next(item for item in service.snapshot().assets if item.id == final.output_asset_id)
        assert asset.duration_seconds == pytest.approx(6.0)

    asyncio.run(scenario())


# ------------------------------------------------------------------ PG2-T4


def sync_assets(service):
    long_wav = wav(3.0)
    return {
        "audio": ingest(service, "audio/wav", long_wav, label="旁白"),
        "short": ingest(service, "audio/wav", wav(1.0), label="短音频"),
    }


def test_audio_effect_creates_succeeded_run_and_asset_in_one_write(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        assets = sync_assets(service)
        revision = service.snapshot().revision
        run = await service.submit_run(
            PlaygroundCapability.AUDIO_EFFECT.value,
            {
                "audio_asset_id": assets["audio"].id,
                "preset": "weak_signal",
                "strength": 0.7,
                "seed": 42,
                "start_seconds": None,
                "end_seconds": None,
            },
            note="试听",
        )
        document = service.snapshot()
        assert document.revision == revision + 1
        assert run.phase is RunPhase.SUCCEEDED
        assert run.progress == 1.0
        assert run.output_asset_id
        assert run.external_id is None
        assert run.plugin_id is None
        result = run.result
        assert result is not None
        assert result["schema"] == "storyrail_audio_effect_v1"
        assert result["request"]["preset"] == "weak_signal"
        asset = next(item for item in document.assets if item.id == run.output_asset_id)
        assert asset.relative_path.startswith("assets/audio/runs/")
        assert asset.origin.kind == "run_output"

    asyncio.run(scenario())


def test_audio_trim_rejects_end_beyond_duration(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        assets = sync_assets(service)
        revision = service.snapshot().revision
        with pytest.raises(ValueError, match="截取结束时间超过音频时长"):
            await service.submit_run(
                PlaygroundCapability.AUDIO_TRIM.value,
                {
                    "audio_asset_id": assets["short"].id,
                    "start_seconds": 0.0,
                    "end_seconds": 5.0,
                },
                note=None,
            )
        assert service.snapshot().revision == revision
        assert service.snapshot().runs == ()

    asyncio.run(scenario())


def test_audio_trim_output_duration(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        assets = sync_assets(service)
        run = await service.submit_run(
            PlaygroundCapability.AUDIO_TRIM.value,
            {
                "audio_asset_id": assets["audio"].id,
                "start_seconds": 1.0,
                "end_seconds": 2.5,
            },
            note=None,
        )
        assert run.phase is RunPhase.SUCCEEDED
        assert run.result is not None
        assert run.result["metadata"]["output_duration_seconds"] == pytest.approx(1.5)
        asset = next(item for item in service.snapshot().assets if item.id == run.output_asset_id)
        assert asset.duration_seconds == pytest.approx(1.5)

    asyncio.run(scenario())


class FakeAsr:
    plugin_id = "test.whisper"
    plugin_version = 1

    def __init__(self) -> None:
        self.requests: list[object] = []
        self.gate: object | None = None
        self.failure: Exception | None = None

    def transcribe(self, request: object):
        from dataclasses import dataclass

        @dataclass
        class Transcript:
            text: str

        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        if self.gate is not None:
            import threading

            gate = self.gate
            assert isinstance(gate, threading.Event)
            gate.wait(2.0)
        return Transcript("你好，世界")


def test_asr_success_records_transcript(playground_factory) -> None:

    async def scenario() -> None:
        service = playground_factory()
        provider = FakeAsr()
        service.registry.install(
            PluginInstance(
                ASR_MANIFEST, recipes={"whisper_asr.transcribe": _RecipeAdapter(provider)}
            )
        )
        assets = sync_assets(service)
        assert service.capability_availability()[PlaygroundCapability.ASR_TRANSCRIBE] is True
        run = await service.submit_run(
            PlaygroundCapability.ASR_TRANSCRIBE.value,
            {"audio_asset_id": assets["audio"].id, "language": "zh"},
            note=None,
        )
        assert run.phase is RunPhase.SUCCEEDED
        assert run.result == {"transcript": "你好，世界"}
        assert run.output_asset_id is None
        assert run.plugin_id == "test.whisper"
        assert run.plugin_version == 1
        assert len(provider.requests) == 1

    asyncio.run(scenario())


def test_asr_failure_records_failed_run(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        provider = FakeAsr()
        provider.failure = ModelProviderError("provider_error", "模型未加载")
        service.registry.install(
            PluginInstance(
                ASR_MANIFEST, recipes={"whisper_asr.transcribe": _RecipeAdapter(provider)}
            )
        )
        assets = sync_assets(service)
        run = await service.submit_run(
            PlaygroundCapability.ASR_TRANSCRIBE.value,
            {"audio_asset_id": assets["audio"].id, "language": "auto"},
            note=None,
        )
        assert run.phase is RunPhase.FAILED
        assert run.error_code == "provider_error"
        assert run.result_json is None
        assert run.message.startswith("语音转写失败：")
        assert "模型未加载" in run.message

    asyncio.run(scenario())


def test_asr_does_not_hold_lock_during_transcribe(playground_factory) -> None:
    import threading

    async def scenario() -> None:
        service = playground_factory()
        provider = FakeAsr()
        gate = threading.Event()
        provider.gate = gate
        service.registry.install(
            PluginInstance(
                ASR_MANIFEST, recipes={"whisper_asr.transcribe": _RecipeAdapter(provider)}
            )
        )
        assets = sync_assets(service)
        other = await service.submit_run(
            PlaygroundCapability.AUDIO_TRIM.value,
            {
                "audio_asset_id": assets["audio"].id,
                "start_seconds": 0.0,
                "end_seconds": 1.0,
            },
            note=None,
        )
        pending = asyncio.create_task(
            service.submit_run(
                PlaygroundCapability.ASR_TRANSCRIBE.value,
                {"audio_asset_id": assets["audio"].id, "language": "auto"},
                note=None,
            )
        )
        for _ in range(200):
            if provider.requests:
                break
            await asyncio.sleep(0.01)
        assert provider.requests, "转写没有开始"
        # 转写阻塞期间，另一个写操作必须能完成。
        await asyncio.wait_for(service.set_note(other.id, "转写中"), timeout=2.0)
        gate.set()
        run = await pending
        assert run.phase is RunPhase.SUCCEEDED

    asyncio.run(scenario())


# ------------------------------------------------------------------ PG2-T5


def test_import_asset_dedupes_and_keeps_first_origin(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        first = await service.import_asset(
            media_type="image/png", content=PNG, filename="雨夜街道.png"
        )
        revision = service.snapshot().revision
        second = await service.copy_in_from_project(
            media_type="image/png",
            content=PNG,
            label="项目里的同一张图",
            project_id="b" * 32,
            source_asset_id="c" * 32,
        )
        assert second == first
        assert second.origin.kind == "imported"
        assert service.snapshot().revision == revision
        assert second.display_name == "雨夜街道"
        assert second.relative_path.startswith("assets/images/imported/雨夜街道-")

        copied = await service.copy_in_from_project(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + b"project",
            label="项目角色参考",
            project_id="b" * 32,
            source_asset_id="c" * 32,
        )
        assert copied.origin.kind == "copied_from_project"
        assert copied.origin.project_id == "b" * 32
        assert copied.relative_path.startswith("assets/images/from-projects/")

    asyncio.run(scenario())


def test_import_rejects_unsupported_media_type(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        with pytest.raises(ValueError, match="不支持的媒体类型"):
            await service.import_asset(media_type="image/gif", content=PNG, filename=None)
        asset = await service.import_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + b"anon",
            filename=None,
        )
        assert asset.display_name == "导入素材"
        named = await service.import_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + b"named",
            filename="  雨夜街道.png  ",
        )
        assert named.display_name == "雨夜街道"

    asyncio.run(scenario())


def test_delete_blocked_by_unfinished_run_input(playground_factory) -> None:
    from core.playground.errors import AssetInUseError

    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_EDIT.value,
            parameters_for(PlaygroundCapability.IMAGE_EDIT, assets),
            note=None,
        )
        assert run.phase is RunPhase.QUEUED
        target = assets["image"].id
        with pytest.raises(AssetInUseError) as error:
            await service.delete_assets((target,))
        assert error.value.asset_ids == (target,)
        assert target in {asset.id for asset in service.snapshot().assets}

    asyncio.run(scenario())


def test_delete_allowed_for_output_of_visible_run(playground_factory) -> None:
    from tests.conftest import SyntheticProvider

    async def scenario() -> None:
        service, assets = build(
            playground_factory,
            image_provider=SyntheticProvider(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\n" + b"generated",
                plugin_id="test.image",
            ),
        )
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        await service.refresh_run(run.id)
        final = await service.refresh_run(run.id)
        assert final.phase is RunPhase.SUCCEEDED
        output_id = final.output_asset_id
        assert output_id is not None
        deleted = await service.delete_assets((output_id,))
        assert deleted == (output_id,)
        document = service.snapshot()
        assert output_id not in {asset.id for asset in document.assets}
        kept = next(item for item in document.runs if item.id == run.id)
        assert kept.output_asset_id == output_id
        assert not (service.store.root_directory / "assets/images/runs").exists() or not any(
            (service.store.root_directory / "assets/images/runs").iterdir()
        )

    asyncio.run(scenario())


def test_delete_restores_files_when_commit_fails(playground_factory, monkeypatch) -> None:
    async def scenario() -> None:
        service = playground_factory()
        asset = await service.import_asset(
            media_type="image/png", content=PNG, filename="雨夜街道.png"
        )
        path = service.store.root_directory / asset.relative_path
        assert path.is_file()

        def explode(_mutate):
            raise RuntimeError("模拟写入失败")

        monkeypatch.setattr(service.store, "commit", explode)
        with pytest.raises(RuntimeError, match="模拟写入失败"):
            await service.delete_assets((asset.id,))
        assert path.is_file()
        assert asset.id in {item.id for item in service.snapshot().assets}

    asyncio.run(scenario())


def test_video_frame_info_requires_mp4(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        video = await service.import_asset(
            media_type="video/mp4",
            content=real_mp4_bytes(48, 2.0),
            filename="镜头.mp4",
        )
        info = service.video_frame_info(video.id)
        assert info.frame_count == 48
        assert info.duration_seconds == pytest.approx(2.0)

        image = await service.import_asset(media_type="image/png", content=PNG, filename="图.png")
        with pytest.raises(ValueError, match="只有 MP4 视频可以抽帧"):
            service.video_frame_info(image.id)
        with pytest.raises(FileNotFoundError):
            service.video_frame_info("f" * 32)

    asyncio.run(scenario())


def test_delete_unknown_asset_404(playground_factory) -> None:
    from core.playground.errors import AssetNotFoundError

    async def scenario() -> None:
        service = playground_factory()
        with pytest.raises(AssetNotFoundError):
            await service.delete_assets(("f" * 32,))
        with pytest.raises(ValueError, match="1 到 200"):
            await service.delete_assets(())

    asyncio.run(scenario())


def test_pano_view_run_creates_new_asset_and_keeps_source(playground_factory) -> None:
    from core.model_providers.contracts import PanoViewRequest

    async def scenario() -> None:
        service, assets = build(playground_factory)
        source = assets["pano"]
        source_bytes = service.read_asset(source.id)[1]
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_PANO_VIEW.value,
            parameters_for(PlaygroundCapability.IMAGE_PANO_VIEW, assets),
            note=None,
        )
        assert run.input_asset_ids == (source.id,)
        assert run.plugin_id == "test.pano"
        provider = service.registry.resolve("pano_view")
        (request,) = provider.requests
        assert isinstance(request, PanoViewRequest)
        assert request.content == source_bytes
        assert (request.yaw_deg, request.pitch_deg, request.hfov_deg) == (90.0, 0.0, 90.0)
        await service.refresh_run(run.id)
        final = await service.refresh_run(run.id)
        assert final.phase is RunPhase.SUCCEEDED
        document = service.snapshot()
        output = next(item for item in document.assets if item.id == final.output_asset_id)
        assert output.id != source.id
        assert output.media_type == "image/png"
        assert output.origin.kind == "run_output"
        assert output.relative_path.startswith("assets/images/runs/全景-全景裁切-yaw90-")
        assert next(item for item in document.assets if item.id == source.id) == source
        assert service.read_asset(source.id)[1] == source_bytes

    asyncio.run(scenario())


def test_pano_view_rejects_image_that_is_not_two_to_one(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        flat = ingest(service, "image/png", png_header_bytes(2048, 1152), label="普通图")
        before = service.snapshot().revision
        with pytest.raises(ValueError, match="2:1 等距柱状图"):
            await service.submit_run(
                PlaygroundCapability.IMAGE_PANO_VIEW.value,
                {
                    **parameters_for(PlaygroundCapability.IMAGE_PANO_VIEW, assets),
                    "image_asset_id": flat.id,
                },
                note=None,
            )
        assert service.snapshot().revision == before
        assert service.registry.resolve("pano_view").requests == []

    asyncio.run(scenario())


def test_pano_view_action_only_on_two_to_one_png_or_jpeg(playground_factory) -> None:
    from core.playground.projection import serialize_snapshot

    service, assets = build(playground_factory)
    jpeg = ingest(
        service,
        "image/jpeg",
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xc0\x00\x11\x08"
        + (2048).to_bytes(2, "big")
        + (4096).to_bytes(2, "big")
        + b"\x03",
        label="全景JPEG",
    )
    off_by_one = ingest(service, "image/png", png_header_bytes(2049, 1024), label="奇数宽")
    flat = ingest(service, "image/png", png_header_bytes(2048, 1152), label="普通图")
    small = ingest(service, "image/png", png_header_bytes(1000, 500), label="小全景")
    webp = ingest(service, "image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", label="webp")
    actions = {
        item["id"]: item["allowed_actions"] for item in serialize_snapshot(service)["assets"]
    }
    for asset in (assets["pano"], jpeg, off_by_one):
        assert "pano_view" in actions[asset.id]
    for asset in (flat, small, webp, assets["image"], assets["video"], assets["wav"]):
        assert "pano_view" not in actions[asset.id]
