from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace

from core.model_providers.boundary import (
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)

from .generation_lifecycle import (
    _phase,
    _provider_handle,
)
from .models import (
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    transition_generation,
)
from .production_context import (
    _TERMINAL_PHASES,
)
from .provider_ports import (
    AnimaticProvider,
    AudioRemixProvider,
    FinalAssemblyProvider,
    RecipeProvider,
    VideoFrameProvider,
)
from .store import RevisionConflictError, StructuredDirectorStore

GenerationProvider = (
    AudioRemixProvider
    | RecipeProvider
    | FinalAssemblyProvider
    | AnimaticProvider
    | VideoFrameProvider
)


class GenerationObserver:
    """Observe/cancel only: same Core Store and lock, no Agent or submit capability."""

    def __init__(
        self,
        store: StructuredDirectorStore,
        lock: asyncio.Lock,
        provider_for: Callable[[ReferenceGeneration], GenerationProvider],
    ) -> None:
        self._store = store
        self._lock = lock
        self._provider_for = provider_for

    async def refresh_generation(self, generation_id: str) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            generation = _find_generation(document, generation_id)
            if generation.phase in _TERMINAL_PHASES:
                return document
            provider = self._provider_for(generation)
            handle = _provider_handle(generation)
            operation = provider.cancel if generation.cancellation_requested else provider.observe
        try:
            observation = await asyncio.to_thread(operation, handle)
        except Exception as exc:
            if isinstance(exc, ModelProviderError) and exc.code == "transport_error":
                async with self._lock:
                    current_document = self._store.read()
                    current = _find_generation(current_document, generation_id)
                    if current.phase in _TERMINAL_PHASES:
                        return current_document
                    unavailable = transition_generation(
                        current,
                        current.phase,
                        message=(
                            "模型节点暂时不可达；任务句柄和最后进度已经保留。"
                            "节点恢复后可继续刷新，不会自动新建或重试任务。"
                        ),
                        error_code="provider_unreachable",
                    )
                    return self._store.update_generation(unavailable)
            raise RuntimeError("暂时无法读取模型任务状态，请稍后重试。") from exc

        content: bytes | None = None
        try:
            if observation.phase is GenerationPhase.SUCCEEDED:
                descriptor = observation.artifact
                if descriptor is None:
                    raise ValueError("成功的 Provider 观察缺少 Artifact。")
                content = await asyncio.to_thread(
                    provider.read_artifact, handle, descriptor.artifact_id
                )
            async with self._lock:
                current_document = self._store.read()
                current = _find_generation(current_document, generation_id)
                if current.phase in _TERMINAL_PHASES:
                    return current_document
                return self._apply_observation_locked(current, observation, content)
        except Exception as exc:
            if observation.phase is GenerationPhase.SUCCEEDED:
                async with self._lock:
                    current_document = self._store.read()
                    current = _find_generation(current_document, generation_id)
                    if current.phase in _TERMINAL_PHASES:
                        return current_document
                    import_failed = transition_generation(
                        current,
                        current.phase,
                        message=(
                            "Provider 已完成任务，但 Core 未能校验并导入产物；"
                            "请保留当前 Generation 并再次等待，不要自动新建任务。"
                        ),
                        error_code="artifact_import_failed",
                    )
                    return self._store.update_generation(import_failed)
            raise RuntimeError("暂时无法应用模型任务状态，请稍后重试。") from exc

    async def refresh_active_generations(self) -> StructuredDirectorDocument:
        """有限并发观察本轮全部非终态 Generation；Provider I/O 不占项目锁。"""
        document = self._store.read()
        generation_ids = tuple(
            generation.id
            for generation in document.generations
            if generation.phase not in _TERMINAL_PHASES
        )
        semaphore = asyncio.Semaphore(16)

        async def refresh(generation_id: str) -> None:
            async with semaphore:
                # Automatic observation is best-effort: a broken or temporarily
                # unavailable Provider must not block unrelated Generation results.
                with suppress(RuntimeError, ValueError):
                    await self.refresh_generation(generation_id)

        await asyncio.gather(*(refresh(generation_id) for generation_id in generation_ids))
        return self._store.read()

    async def cancel_generation(
        self,
        generation_id: str,
        *,
        expected_revision: int | None = None,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if expected_revision is not None and document.revision != expected_revision:
                raise RevisionConflictError("项目已更新，请刷新后重新取消 Generation。")
            generation = _find_generation(document, generation_id)
            if generation.phase in _TERMINAL_PHASES:
                return document
            if generation.cancellation_requested:
                return document
            provider = self._provider_for(generation)
            handle = _provider_handle(generation)
            requested = transition_generation(
                generation,
                generation.phase,
                message="已请求取消，正在等待模型服务确认。",
                cancellation_requested=True,
            )
            self._store.update_generation(requested)
            try:
                observation = await asyncio.to_thread(provider.cancel, handle)
                return await self._apply_observation(provider, handle, requested, observation)
            except Exception as exc:
                raise RuntimeError(
                    "暂时无法取消模型任务；取消意图已保存。"
                    "请继续刷新/等待原 Generation 确认取消，不要重建任务。"
                ) from exc

    async def _apply_observation(
        self,
        provider: (
            AudioRemixProvider
            | RecipeProvider
            | FinalAssemblyProvider
            | AnimaticProvider
            | VideoFrameProvider
        ),
        handle: ProviderHandle,
        generation: ReferenceGeneration,
        observation: GenerationObservation,
    ) -> StructuredDirectorDocument:
        content: bytes | None = None
        if observation.phase is GenerationPhase.SUCCEEDED:
            descriptor = observation.artifact
            if descriptor is None:
                raise ValueError("成功的 Provider 观察缺少 Artifact。")
            content = await asyncio.to_thread(
                provider.read_artifact, handle, descriptor.artifact_id
            )
        return self._apply_observation_locked(generation, observation, content)

    def _apply_observation_locked(
        self,
        generation: ReferenceGeneration,
        observation: GenerationObservation,
        content: bytes | None,
    ) -> StructuredDirectorDocument:
        phase = _phase(observation.phase)
        if phase is ReferenceGenerationPhase.SUCCEEDED:
            descriptor = observation.artifact
            if descriptor is None or content is None:
                raise ValueError("成功的 Provider 观察缺少 Artifact。")
            completed = replace(
                generation,
                progress=1.0,
                message=observation.message,
            )
            completed_document = self._store.complete_generation(
                completed,
                media_type=descriptor.media_type,
                content=content,
                expected_sha256=descriptor.sha256,
                expected_byte_count=descriptor.byte_count,
                actual_duration_seconds=descriptor.duration_seconds,
            )
            if generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE:
                return self._store.attach_upscaled_video(
                    segment_id=generation.target_id,
                    generation_id=generation.id,
                    expected_revision=completed_document.revision,
                )
            return completed_document
        if (
            generation.phase is ReferenceGenerationPhase.RUNNING
            and phase is ReferenceGenerationPhase.QUEUED
        ):
            return self._store.read()
        updated = transition_generation(
            generation,
            phase,
            progress=observation.progress,
            message=observation.message,
            error_code=observation.error_code,
        )
        return self._store.update_generation(updated)


def _find_generation(
    document: StructuredDirectorDocument, generation_id: str
) -> ReferenceGeneration:
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if generation is None:
        raise ValueError("Generation 不存在。")
    return generation
