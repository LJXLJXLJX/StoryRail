"""Playground 的 Provider 观察、取消意图持久化与产物回收。

对照项目的 core/structured_director/generation_observer.py 编写；文案逐字复制，
只把「Generation」替换成「实验」。
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import replace

from core.model_providers.boundary import (
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.manifest import Capability

from .capabilities import capability_spec, run_output_label
from .commands import stage_request, write_envelope
from .errors import ProviderUnavailableError
from .lifecycle import transition_run, update_run_durable, utc_timestamp
from .models import (
    TERMINAL_PHASES,
    AssetOrigin,
    PlaygroundDocument,
    PlaygroundRun,
    RunPhase,
)
from .projection import serialize_run

_UNREACHABLE_MESSAGE = (
    "模型节点暂时不可达；任务句柄和最后进度已经保留。节点恢复后可继续刷新，不会自动新建或重试任务。"
)
_IMPORT_FAILED_MESSAGE = (
    "Provider 已完成任务，但 Core 未能校验并导入产物；请保留当前实验并再次等待，不要自动新建任务。"
)
_CANCEL_REQUESTED_MESSAGE = "已请求取消，正在等待模型服务确认。"
_CANCEL_FAILED_MESSAGE = (
    "暂时无法取消模型任务；取消意图已保存。请继续刷新/等待原实验确认取消，不要重建任务。"
)
_OBSERVE_FAILED_MESSAGE = "暂时无法读取模型任务状态，请稍后重试。"
_APPLY_FAILED_MESSAGE = "暂时无法应用模型任务状态，请稍后重试。"


def provider_handle(run: PlaygroundRun) -> ProviderHandle:
    if run.plugin_id is None or run.plugin_version is None or run.external_id is None:
        raise ValueError("实验没有可恢复的 Provider handle。")
    return ProviderHandle(run.plugin_id, run.plugin_version, run.external_id)


def run_index(runs: tuple[PlaygroundRun, ...], run_id: str) -> int:
    for index, run in enumerate(runs):
        if run.id == run_id:
            return index
    raise ValueError("实验不存在。")


def provider_for_run(registry, run: PlaygroundRun) -> object:
    spec = capability_spec(run.capability, recipe=run.recipe)
    semantic = None if run.recipe is None else run.recipe.capability
    if semantic is not None:
        found = (
            None
            if run.plugin_id is None or run.plugin_version is None
            else registry.resolve_plugin(
                run.plugin_id, run.plugin_version, capabilities=(semantic.value,)
            )
        )
        if found is None:
            raise ProviderUnavailableError("对应模型服务未配置。")
        return found
    capability = spec.registry_capability
    if capability is None:
        raise ProviderUnavailableError("对应模型服务未配置。")
    if run.plugin_id is not None and run.plugin_version is not None:
        found = registry.resolve_plugin(
            run.plugin_id,
            run.plugin_version,
            capabilities=(capability,),
        )
        if found is not None:
            return found
    found = registry.resolve(capability)
    if found is None:
        raise ProviderUnavailableError("对应模型服务未配置。")
    return found


class PlaygroundObserver:
    """只做观察与取消：与 Service 共用同一个 Store 和锁，不提供提交能力。"""

    def __init__(
        self,
        store,
        lock: asyncio.Lock,
        provider_for: Callable[[PlaygroundRun], object],
    ) -> None:
        self._store = store
        self._lock = lock
        self._provider_for = provider_for

    async def refresh_run(self, run_id: str) -> PlaygroundRun:
        async with self._lock:
            document = self._store.read()
            run = document.runs[run_index(document.runs, run_id)]
            if run.phase in TERMINAL_PHASES:
                return run
            provider = self._provider_for(run)
            handle = provider_handle(run)
            try:
                operation = provider.cancel if run.cancellation_requested else provider.observe
                observation = await asyncio.to_thread(operation, handle)
            except Exception as exc:
                if isinstance(exc, ModelProviderError) and exc.code == "transport_error":
                    return self._durable(
                        run.id,
                        lambda current: transition_run(
                            current,
                            current.phase,
                            message=_UNREACHABLE_MESSAGE,
                            error_code="provider_unreachable",
                        ),
                    )
                raise RuntimeError(_OBSERVE_FAILED_MESSAGE) from exc
            try:
                return await self._apply_observation(provider, handle, run, observation)
            except Exception as exc:
                if observation.phase is GenerationPhase.SUCCEEDED:
                    return self._durable(
                        run.id,
                        lambda current: transition_run(
                            current,
                            current.phase,
                            message=_IMPORT_FAILED_MESSAGE,
                            error_code="artifact_import_failed",
                        ),
                    )
                raise RuntimeError(_APPLY_FAILED_MESSAGE) from exc

    async def refresh_active_runs(self) -> PlaygroundDocument:
        """串行观察本轮已存在的全部非终态 run。"""
        document = self._store.read()
        run_ids = tuple(run.id for run in document.runs if run.phase not in TERMINAL_PHASES)
        for run_id in run_ids:
            try:
                await self.refresh_run(run_id)
            except (RuntimeError, ValueError):
                # 自动观察是尽力而为：单个不可达的 Provider 不能阻塞其它实验。
                continue
        return self._store.read()

    async def cancel_run(self, run_id: str, *, request=None) -> PlaygroundRun:
        async with self._lock:
            document = self._store.read()
            run = document.runs[run_index(document.runs, run_id)]
            if run.phase in TERMINAL_PHASES:
                return run
            if run.cancellation_requested:
                return run
            provider = self._provider_for(run)
            handle = provider_handle(run)
            requested = self._durable(
                run.id,
                lambda current: transition_run(
                    current,
                    current.phase,
                    message=_CANCEL_REQUESTED_MESSAGE,
                    cancellation_requested=True,
                ),
                request=request,
                summary="已请求取消该实验。",
            )
            try:
                observation = await asyncio.to_thread(provider.cancel, handle)
                return await self._apply_observation(provider, handle, requested, observation)
            except Exception as exc:
                raise RuntimeError(_CANCEL_FAILED_MESSAGE) from exc

    # ------------------------------------------------------------ 内部

    def _durable(
        self,
        run_id: str,
        derive: Callable[[PlaygroundRun], PlaygroundRun],
        *,
        request=None,
        summary: str = "已更新实验。",
    ) -> PlaygroundRun:
        """按项目 update_generation 的持久化规则写入，并记录观察缓存。"""
        holder: dict[str, PlaygroundRun] = {}

        def mutate(previous: PlaygroundDocument) -> PlaygroundDocument:
            index = run_index(previous.runs, run_id)
            candidate = derive(previous.runs[index])
            updated, changed = update_run_durable(previous, candidate, timestamp=utc_timestamp())
            holder["candidate"] = candidate
            holder["run"] = updated.runs[index] if changed else previous.runs[index]
            if not changed:
                return previous
            if request is None:
                return updated
            return stage_request(
                updated,
                request,
                build_receipt=lambda current: write_envelope(
                    request,
                    current,
                    status="succeeded",
                    old_revision=current.revision - 1,
                    new_revision=current.revision,
                    decision_summary=summary,
                    data={
                        "run": serialize_run(
                            holder["run"], observed=self._store.observed_run(holder["run"])
                        )
                    },
                ),
            )

        self._store.commit(mutate)
        # 缓存本次观察的 progress/message；持久值仍是文档里的值。
        self._store.record_observation(holder["candidate"])
        return holder["run"]

    async def _apply_observation(
        self,
        provider,
        handle: ProviderHandle,
        run: PlaygroundRun,
        observation: GenerationObservation,
    ) -> PlaygroundRun:
        if observation.phase is not GenerationPhase.SUCCEEDED:
            phase = RunPhase(observation.phase.value)
            return self._durable(
                run.id,
                lambda current: transition_run(
                    current,
                    phase,
                    progress=observation.progress,
                    message=observation.message,
                    error_code=observation.error_code,
                ),
            )
        descriptor = observation.artifact
        if descriptor is None:
            raise ValueError("成功的 Provider 观察缺少 Artifact。")
        content = await asyncio.to_thread(provider.read_artifact, handle, descriptor.artifact_id)
        if (
            len(content) != descriptor.byte_count
            or hashlib.sha256(content).hexdigest() != descriptor.sha256
        ):
            raise ValueError("Provider 产物与描述不符。")
        spec = capability_spec(run.capability, recipe=run.recipe)
        if descriptor.media_type not in spec.output_media_types:
            raise ValueError("Provider 产物媒体类型不受支持。")
        return self._complete(run, spec, descriptor, content, observation.message)

    def _complete(self, run, spec, descriptor, content: bytes, message: str) -> PlaygroundRun:
        holder: dict[str, PlaygroundRun] = {}

        def mutate(previous: PlaygroundDocument) -> PlaygroundDocument:
            index = run_index(previous.runs, run.id)
            current = previous.runs[index]
            duration = descriptor.duration_seconds
            if (
                duration is None
                and current.recipe is not None
                and current.recipe.capability is Capability.VIDEO_UPSCALE
            ):
                # 与项目 complete_generation 的超分分支一致：产物缺时长时沿用源视频。
                source_id = current.parameters.get("video_asset_id")
                source = next((asset for asset in previous.assets if asset.id == source_id), None)
                duration = None if source is None else source.duration_seconds
            updated, asset = self._store.ingest_asset(
                previous,
                media_type=descriptor.media_type,
                content=content,
                origin_dir="runs",
                label=run_output_label(
                    current.capability,
                    current.parameters,
                    run_id=current.id,
                    document=previous,
                    recipe=current.recipe,
                ),
                origin=AssetOrigin("run_output", run_id=current.id),
                created_at=utc_timestamp(),
                duration_seconds=duration,
            )
            succeeded = transition_run(
                updated.runs[index],
                RunPhase.SUCCEEDED,
                progress=1.0,
                message=message,
                output_asset_id=asset.id,
            )
            runs = list(updated.runs)
            runs[index] = succeeded
            holder["run"] = succeeded
            return replace(updated, revision=previous.revision + 1, runs=tuple(runs))

        self._store.commit(mutate)
        return holder["run"]
