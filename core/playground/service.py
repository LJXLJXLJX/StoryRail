"""Playground 应用服务：串行化写入、能力检索、提交与 run 管理。

所有写方法都在 ``self._lock``（``asyncio.Lock``）内调用 Store；Store 自身不加锁。
Provider 调用一律通过 ``asyncio.to_thread``，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from core.audio_effects import (
    AudioEffectRequest,
    AudioTrimRequest,
    apply_audio_effect,
    audio_effect_record,
    audio_trim_record,
    trim_audio,
)
from core.media_assets import Mp4VideoFrames, read_mp4_video_frames, uploaded_asset_label
from core.model_providers.boundary import ModelProviderError, ProviderHandle
from core.model_providers.manifest import Capability, ProviderSnapshot, Recipe
from core.model_providers.observation_wait import BoundedObserver, wait_budget
from core.model_providers.recipe import recipe_wire_schema
from core.model_providers.registry import (
    PreparedRecipe,
    PreparedSubmission,
    ProviderRegistry,
    prepare_submission,
)

from .capabilities import (
    CAPABILITY_SPECS,
    CapabilitySpec,
    ResolvedRequest,
    capability_spec,
    recipe_spec,
    resolve_recipe_request,
    resolve_request,
    run_output_label,
)
from .commands import RequestContext, stage_request, write_envelope
from .errors import (
    AssetInUseError,
    AssetNotFoundError,
    ProviderUnavailableError,
    RunNotFoundError,
    RunStateConflictError,
)
from .lifecycle import (
    link_retry,
    submission_failure,
    transition_run,
    utc_timestamp,
)
from .models import (
    MEDIA_TYPES,
    TERMINAL_PHASES,
    UNFINISHED_PHASES,
    AssetOrigin,
    PlaygroundAsset,
    PlaygroundCapability,
    PlaygroundDocument,
    PlaygroundRun,
    RunPhase,
    canonical_json,
)
from .observer import PlaygroundObserver, provider_for_run
from .parameters import (
    input_asset_ids,
    parameter_seed,
    parse_parameters,
    recipe_input_labels,
)
from .projection import serialize_run
from .store import PlaygroundStore
from .usage import asset_usage

_BeforeSubmit = Callable[[PlaygroundDocument], PlaygroundDocument]


def _run_index(runs: tuple[PlaygroundRun, ...], run_id: str) -> int:
    for index, run in enumerate(runs):
        if run.id == run_id:
            return index
    raise RunNotFoundError("实验不存在。")


def find_run(document: PlaygroundDocument, run_id: str) -> PlaygroundRun:
    return document.runs[_run_index(document.runs, run_id)]


class PlaygroundService:
    def __init__(
        self,
        store: PlaygroundStore,
        registry: ProviderRegistry,
    ) -> None:
        self._store = store
        self._registry = registry
        self._lock = asyncio.Lock()
        store.ensure_created()
        store.recover_interrupted_submissions()
        self._observer = PlaygroundObserver(store, self._lock, self.provider_for)
        self._bounded_observer = BoundedObserver()

    @property
    def store(self) -> PlaygroundStore:
        return self._store

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    # ---------------------------------------------------------------- 读

    def snapshot(self) -> PlaygroundDocument:
        return self._store.read()

    def observed_run(self, run: PlaygroundRun) -> PlaygroundRun:
        return self._store.observed_run(run)

    def capability_specs(self) -> dict[str, CapabilitySpec]:
        return {
            **CAPABILITY_SPECS,
            **{
                view["recipe"]["id"]: recipe_spec(
                    self._registry.recipe_definition(
                        Capability(view["capability"]), view["recipe"]["id"]
                    )[1]
                )
                for view in self._registry.recipe_views()
            },
        }

    def capability_availability(self) -> dict[str, bool]:
        return {
            capability: (
                True
                if capability not in CAPABILITY_SPECS or spec.registry_capability is None
                else self._registry.resolve(spec.registry_capability) is not None
            )
            for capability, spec in self.capability_specs().items()
        }

    def capability_recipe(self, capability: str) -> dict[str, object] | None:
        found = self._capability_recipe_definition(capability)
        if found is None:
            return None
        plugin, recipe = found
        return {
            "plugin_id": plugin.plugin_id,
            "plugin_label": plugin.manifest.label,
            "recipe": recipe.to_json(),
            "parameters_schema": recipe_wire_schema(recipe),
        }

    def _capability_recipe_definition(self, capability):
        for view in self._registry.recipe_views():
            if view["recipe"]["id"] == capability:
                return self._registry.recipe_definition(Capability(view["capability"]), capability)
        return None

    def _prepare_recipe(self, capability: str, retry_of: PlaygroundRun | None) -> PreparedRecipe:
        snapshot = None if retry_of is None else retry_of.provider_snapshot
        try:
            if snapshot is None:
                found = self._capability_recipe_definition(capability)
                if found is None:
                    raise RuntimeError("对应 recipe 未配置。")
                return self._registry.prepare_recipe(found[1].capability, recipe_id=capability)
            if retry_of.recipe is None:
                raise RuntimeError("原实验缺少 recipe 声明。")
            return self._registry.prepare_recipe(
                retry_of.recipe.capability,
                plugin_id=snapshot.plugin_id,
                recipe_id=snapshot.recipe_id,
            )
        except (RuntimeError, ValueError) as exc:
            raise ProviderUnavailableError(str(exc)) from exc

    def _capability_spec(
        self, capability: str, retry_of: PlaygroundRun | None = None
    ) -> CapabilitySpec:
        if capability in CAPABILITY_SPECS:
            return CAPABILITY_SPECS[capability]
        if retry_of is not None and retry_of.recipe is not None:
            return recipe_spec(retry_of.recipe)
        found = self._capability_recipe_definition(capability)
        if found is None:
            raise ProviderUnavailableError("对应 recipe 未配置。")
        return recipe_spec(found[1])

    def preview_recipe_inputs(self, capability: str, parameters: object) -> dict[str, object]:
        """未保存表单的只读预览：标签由 Core 编号，生成可用性使用正式解析与媒体约束。"""
        if not isinstance(parameters, dict):
            raise ValueError("parameters 必须是对象。")
        prepared = self._prepare_recipe(capability, None)
        recipe = prepared.recipe
        labels = recipe_input_labels(recipe, parameters, draft=True)
        try:
            parsed = parse_parameters(capability, parameters, recipe=recipe)
            resolve_recipe_request(
                prepared.plugin.manifest,
                recipe,
                parsed,
                read_asset=self.read_asset,
                settings=prepared.settings,
            )
        except (ValueError, FileNotFoundError) as exc:
            return {"ready": False, "reason": str(exc), "input_labels": labels}
        return {"ready": True, "reason": None, "input_labels": labels}

    def read_asset(self, asset_id: str) -> tuple[PlaygroundAsset, bytes]:
        return self._store.read_asset(asset_id)

    def is_pano_source(self, asset: PlaygroundAsset) -> bool:
        return self._store.is_pano_source(asset)

    def provider_for_capability(self, spec: CapabilitySpec) -> object | None:
        if spec.registry_capability is None:
            return None
        return self._registry.resolve(spec.registry_capability)

    # ---------------------------------------------------------------- run

    async def submit_run(
        self,
        capability: str,
        parameters: dict[str, object],
        *,
        note: str | None,
        request: RequestContext | None = None,
        _retry_of: PlaygroundRun | None = None,
        _before_submit: _BeforeSubmit | None = None,
    ) -> PlaygroundRun:
        if not isinstance(capability, str) or not 1 <= len(capability) <= 128:
            raise ValueError("capability 必须是 1 到 128 字符的 recipe 或工具 ID。")
        resolved = (
            PlaygroundCapability(capability) if capability in CAPABILITY_SPECS else capability
        )
        return await self._submit(
            resolved,
            parameters,
            note=note,
            retry_of=_retry_of,
            before_submit=_before_submit,
            request=request,
        )

    async def _submit(
        self,
        capability: PlaygroundCapability,
        parameters: dict[str, object],
        *,
        note: str | None,
        retry_of: PlaygroundRun | None,
        before_submit: _BeforeSubmit | None,
        run_id: str | None = None,
        request: RequestContext | None = None,
    ) -> PlaygroundRun:
        spec = self._capability_spec(capability, retry_of)
        if spec.execution == "sync":
            return await self._submit_sync(
                capability,
                parameters,
                note=note,
                retry_of=retry_of,
                before_submit=before_submit,
                run_id=run_id,
                request=request,
            )
        recipe = (
            self._prepare_recipe(capability, retry_of)
            if capability not in CAPABILITY_SPECS
            else None
        )
        provider = None if recipe is not None else self.provider_for_capability(spec)
        if recipe is None and provider is None:
            raise ProviderUnavailableError("对应模型服务未配置。")
        prepared: dict[str, object] = {}
        async with self._lock:
            self._store.commit(
                self._plan_submission(
                    provider if recipe is None else recipe,
                    capability,
                    parameters,
                    note=note,
                    retry_of=retry_of,
                    before_submit=before_submit,
                    run_id=run_id,
                    prepared=prepared,
                    request=request,
                )
            )
            run: PlaygroundRun = prepared["run"]  # type: ignore[assignment]
            request: ResolvedRequest = prepared["request"]  # type: ignore[assignment]
            submission: PreparedSubmission = prepared["submission"]  # type: ignore[assignment]
        try:
            handle: ProviderHandle = await asyncio.to_thread(
                submission.submit, request.provider_request
            )
        except Exception as exc:
            failure = exc
            label = spec.label

            def transform(current: PlaygroundRun, _document: PlaygroundDocument) -> PlaygroundRun:
                if current.phase is not RunPhase.SUBMITTING:
                    return current
                return submission_failure(current, failure, capability_label=label)

            async with self._lock:
                return self._mutate_run(run.id, transform)
        queued = transition_run(
            run,
            RunPhase.QUEUED,
            message=f"{spec.label}任务已提交。",
            plugin_id=handle.plugin_id,
            plugin_version=handle.plugin_version,
            external_id=handle.external_id,
        )
        async with self._lock:
            return self._mutate_run(
                run.id,
                lambda current, _document: (
                    current if current.phase is not RunPhase.SUBMITTING else queued
                ),
            )

    def _plan_submission(
        self,
        provider: object,
        capability: PlaygroundCapability,
        parameters: dict[str, object],
        *,
        note: str | None,
        retry_of: PlaygroundRun | None,
        before_submit: _BeforeSubmit | None,
        run_id: str | None,
        prepared: dict[str, object],
        request: RequestContext | None = None,
    ) -> Callable[[PlaygroundDocument], PlaygroundDocument]:
        spec = self._capability_spec(capability, retry_of)

        def mutate(previous: PlaygroundDocument) -> PlaygroundDocument:
            if isinstance(provider, PreparedRecipe):
                parsed = parse_parameters(capability, parameters, recipe=provider.recipe)
                resolved_request = resolve_recipe_request(
                    provider.plugin.manifest,
                    provider.recipe,
                    parsed,
                    read_asset=self._store.read_asset,
                    settings=provider.settings,
                )
                submission = PreparedSubmission(provider.plugin, provider.submit, provider.snapshot)
            else:
                parsed = parse_parameters(capability, parameters)
                resolved_request = resolve_request(
                    capability,
                    parsed,
                    document=previous,
                    read_asset=self._store.read_asset,
                )
                submission = prepare_submission(provider, resolved_request.submit_method)
            if capability is PlaygroundCapability.VIDEO_EXTRACT_FRAME:
                _reject_active_frame_extraction(previous, str(parsed["video_asset_id"]))
            timestamp = utc_timestamp()
            run = PlaygroundRun(
                id=run_id or uuid4().hex,
                capability=capability,
                phase=RunPhase.SUBMITTING,
                progress=0.0,
                message=f"正在提交{spec.label}任务。",
                parameters_json=canonical_json(parsed),
                input_asset_ids=input_asset_ids(
                    capability,
                    parsed,
                    recipe=provider.recipe if isinstance(provider, PreparedRecipe) else None,
                ),
                seed=parameter_seed(
                    capability,
                    parsed,
                    recipe=provider.recipe if isinstance(provider, PreparedRecipe) else None,
                ),
                plugin_id=None,
                plugin_version=None,
                external_id=None,
                output_asset_id=None,
                result_json=None,
                error_code=None,
                cancellation_requested=False,
                retry_of=None,
                note=None if note is None else note.strip(),
                dismissed=False,
                created_at=timestamp,
                updated_at=timestamp,
                provider_snapshot=submission.snapshot,
                recipe=provider.recipe if isinstance(provider, PreparedRecipe) else None,
            )
            linked = link_retry(previous, run, retry_of)
            prepared["run"] = linked
            prepared["request"] = resolved_request
            prepared["submission"] = submission
            updated = replace(
                previous,
                revision=previous.revision + 1,
                runs=(*previous.runs, linked),
            )
            if before_submit is not None:
                updated = before_submit(updated)
            return self._stage(
                updated,
                request,
                summary=f"已提交{spec.label}实验。",
                data={"run": serialize_run(linked, observed=self._store.observed_run(linked))},
            )

        return mutate

    async def _submit_sync(
        self,
        capability: PlaygroundCapability,
        parameters: dict[str, object],
        *,
        note: str | None,
        retry_of: PlaygroundRun | None,
        before_submit: _BeforeSubmit | None,
        run_id: str | None,
        request: RequestContext | None = None,
    ) -> PlaygroundRun:
        if capability not in CAPABILITY_SPECS:
            return await self._submit_asr(
                capability,
                parameters,
                note=note,
                retry_of=retry_of,
                before_submit=before_submit,
                run_id=run_id,
                request=request,
            )
        return await self._submit_local_audio(
            capability,
            parameters,
            note=note,
            retry_of=retry_of,
            before_submit=before_submit,
            run_id=run_id,
            request=request,
        )

    async def _submit_local_audio(
        self,
        capability: PlaygroundCapability,
        parameters: dict[str, object],
        *,
        note: str | None,
        retry_of: PlaygroundRun | None,
        before_submit: _BeforeSubmit | None,
        run_id: str | None,
        request: RequestContext | None = None,
    ) -> PlaygroundRun:
        """Core 本地 DSP：锁内读源素材、执行处理，并在一次写入里落产物和 run。"""
        async with self._lock:
            document = self._store.read()
            parsed = parse_parameters(capability, parameters)
            resolve_request(
                capability,
                parsed,
                document=document,
                read_asset=self._store.read_asset,
            )
            source_asset, content = self._store.read_asset(str(parsed["audio_asset_id"]))
            if capability is PlaygroundCapability.AUDIO_EFFECT:
                effect_request = AudioEffectRequest(
                    effect="radio",
                    preset=str(parsed["preset"]),
                    strength=float(parsed["strength"]),  # type: ignore[arg-type]
                    seed=int(parsed["seed"]),  # type: ignore[arg-type]
                    start_seconds=parsed["start_seconds"],  # type: ignore[arg-type]
                    end_seconds=parsed["end_seconds"],  # type: ignore[arg-type]
                )
                result = await asyncio.to_thread(apply_audio_effect, content, effect_request)
                record = audio_effect_record(effect_request, result)
                message = "音频后处理完成。"
            else:
                end_seconds = float(parsed["end_seconds"])  # type: ignore[arg-type]
                duration = source_asset.duration_seconds
                if duration is not None and end_seconds > duration + 1e-9:
                    raise ValueError("截取结束时间超过音频时长。")
                trim_request = AudioTrimRequest(
                    start_seconds=float(parsed["start_seconds"]),  # type: ignore[arg-type]
                    end_seconds=end_seconds,
                )
                result = await asyncio.to_thread(trim_audio, content, trim_request)
                record = audio_trim_record(trim_request, result)
                message = "音频截取完成。"
            return self._commit_sync_run(
                capability=capability,
                parsed=parsed,
                note=note,
                retry_of=retry_of,
                before_submit=before_submit,
                run_id=run_id,
                message=message,
                result_json=canonical_json(json.loads(record)),
                output_content=result.audio,
                plugin_id=None,
                plugin_version=None,
                phase=RunPhase.SUCCEEDED,
                error_code=None,
                request=request,
            )

    async def _submit_asr(
        self,
        capability: PlaygroundCapability,
        parameters: dict[str, object],
        *,
        note: str | None,
        retry_of: PlaygroundRun | None,
        before_submit: _BeforeSubmit | None,
        run_id: str | None,
        request: RequestContext | None = None,
    ) -> PlaygroundRun:
        """同步转写期间不持有业务写锁。"""
        prepared = self._prepare_recipe(capability, retry_of)
        async with self._lock:
            parsed = parse_parameters(capability, parameters, recipe=prepared.recipe)
            resolved_request = resolve_recipe_request(
                prepared.plugin.manifest,
                prepared.recipe,
                parsed,
                read_asset=self._store.read_asset,
                settings=prepared.settings,
            )
        submission = PreparedSubmission(prepared.plugin, prepared.execute, prepared.snapshot)
        implementation = prepared.plugin.recipes[prepared.recipe.id]
        plugin_id = getattr(implementation, "plugin_id", None)
        plugin_version = getattr(implementation, "plugin_version", None)
        failure: Exception | None = None
        transcript = ""
        try:
            result = await asyncio.to_thread(submission.submit, resolved_request.provider_request)
            transcript = str(result.text)
        except Exception as exc:
            failure = exc
        if failure is None:
            async with self._lock:
                return self._commit_sync_run(
                    capability=capability,
                    parsed=parsed,
                    note=note,
                    retry_of=retry_of,
                    before_submit=before_submit,
                    run_id=run_id,
                    message="语音转写完成。",
                    result_json=canonical_json({"transcript": transcript}),
                    output_content=None,
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    provider_snapshot=submission.snapshot,
                    recipe=prepared.recipe,
                    phase=RunPhase.SUCCEEDED,
                    error_code=None,
                    request=request,
                )
        code = failure.code if isinstance(failure, ModelProviderError) else "provider_error"
        reason = str(failure).strip() or failure.__class__.__name__
        async with self._lock:
            return self._commit_sync_run(
                capability=capability,
                parsed=parsed,
                note=note,
                retry_of=retry_of,
                before_submit=before_submit,
                run_id=run_id,
                message=f"语音转写失败：{reason[:200]}",
                result_json=None,
                output_content=None,
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                provider_snapshot=submission.snapshot,
                recipe=prepared.recipe,
                phase=RunPhase.FAILED,
                error_code=code,
                request=request,
            )

    def _commit_sync_run(
        self,
        *,
        capability: PlaygroundCapability,
        parsed: dict[str, object],
        note: str | None,
        retry_of: PlaygroundRun | None,
        before_submit: _BeforeSubmit | None,
        run_id: str | None,
        message: str,
        result_json: str | None,
        output_content: bytes | None,
        plugin_id: str | None,
        plugin_version: int | None,
        phase: RunPhase,
        error_code: str | None,
        request: RequestContext | None = None,
        provider_snapshot: ProviderSnapshot | None = None,
        recipe: Recipe | None = None,
    ) -> PlaygroundRun:
        holder: dict[str, PlaygroundRun] = {}

        def mutate(previous: PlaygroundDocument) -> PlaygroundDocument:
            timestamp = utc_timestamp()
            new_id = run_id or uuid4().hex
            document = previous
            output_asset_id: str | None = None
            if output_content is not None:
                document, asset = self._store.ingest_asset(
                    previous,
                    media_type="audio/wav",
                    content=output_content,
                    origin_dir="runs",
                    label=run_output_label(
                        capability,
                        parsed,
                        run_id=new_id,
                        document=previous,
                    ),
                    origin=AssetOrigin("run_output", run_id=new_id),
                    created_at=timestamp,
                    duration_seconds=None,
                )
                output_asset_id = asset.id
            run = PlaygroundRun(
                id=new_id,
                capability=capability,
                phase=phase,
                progress=1.0 if phase is RunPhase.SUCCEEDED else 0.0,
                message=message,
                parameters_json=canonical_json(parsed),
                input_asset_ids=input_asset_ids(capability, parsed, recipe=recipe),
                seed=parameter_seed(capability, parsed, recipe=recipe),
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                external_id=None,
                output_asset_id=output_asset_id,
                result_json=result_json,
                error_code=error_code,
                cancellation_requested=False,
                retry_of=None,
                note=None if note is None else note.strip(),
                dismissed=False,
                created_at=timestamp,
                updated_at=timestamp,
                provider_snapshot=provider_snapshot,
                recipe=recipe,
            )
            linked = link_retry(previous, run, retry_of)
            holder["run"] = linked
            updated = replace(
                document,
                revision=previous.revision + 1,
                runs=(*document.runs, linked),
            )
            if before_submit is not None:
                updated = before_submit(updated)
            return self._stage(
                updated,
                request,
                summary=f"已完成{capability_spec(capability, recipe=recipe).label}实验。",
                data={"run": serialize_run(linked, observed=self._store.observed_run(linked))},
            )

        self._store.commit(mutate)
        return holder["run"]

    async def retry_run(
        self,
        run_id: str,
        *,
        request: RequestContext | None = None,
        _before_submit: _BeforeSubmit | None = None,
    ) -> PlaygroundRun:
        document = self._store.read()
        run = find_run(document, run_id)
        if run.phase not in {
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.SUBMISSION_UNCERTAIN,
        }:
            raise RunStateConflictError("只有失败、已取消或提交结果未知的实验可以重试。")
        if run.dismissed:
            raise RunStateConflictError("已隐藏的实验不能重试。")
        known = {asset.id for asset in document.assets}
        if any(asset_id not in known for asset_id in run.input_asset_ids):
            raise RunStateConflictError("重试所需的输入 Asset 已删除。")
        return await self._submit(
            run.capability,
            run.parameters,
            note=run.note,
            retry_of=run,
            before_submit=_before_submit,
            request=request,
        )

    def _mutate_run(
        self,
        run_id: str,
        transform: Callable[[PlaygroundRun, PlaygroundDocument], PlaygroundRun],
        *,
        request: RequestContext | None = None,
        summary: str = "已更新实验。",
    ) -> PlaygroundRun:
        holder: dict[str, PlaygroundRun] = {}

        def mutate(previous: PlaygroundDocument) -> PlaygroundDocument:
            index = _run_index(previous.runs, run_id)
            current = previous.runs[index]
            updated = transform(current, previous)
            holder["run"] = updated
            if updated is current:
                return previous
            runs = list(previous.runs)
            runs[index] = updated
            document = replace(previous, revision=previous.revision + 1, runs=tuple(runs))
            return self._stage(
                document,
                request,
                summary=summary,
                data={"run": serialize_run(updated, observed=self._store.observed_run(updated))},
            )

        self._store.commit(mutate)
        return holder["run"]

    def _stage(
        self,
        document: PlaygroundDocument,
        request: RequestContext | None,
        *,
        summary: str,
        data: dict[str, object],
    ) -> PlaygroundDocument:
        """把请求记录和业务变更放进同一次写入；没有 request 时原样返回。"""
        if request is None:
            return document
        return stage_request(
            document,
            request,
            build_receipt=lambda current: write_envelope(
                request,
                current,
                status="succeeded",
                old_revision=current.revision - 1,
                new_revision=current.revision,
                decision_summary=summary,
                data=data,
            ),
        )

    # ------------------------------------------------------------ asset

    async def import_asset(
        self,
        *,
        media_type: str,
        content: bytes,
        filename: str | None,
    ) -> PlaygroundAsset:
        if media_type not in MEDIA_TYPES:
            raise ValueError("不支持的媒体类型。")
        async with self._lock:
            return self._ingest(
                media_type=media_type,
                content=content,
                origin_dir="imported",
                label=uploaded_asset_label(filename, "导入素材"),
                origin=AssetOrigin("imported"),
            )

    async def copy_in_from_project(
        self,
        *,
        media_type: str,
        content: bytes,
        label: str,
        project_id: str,
        source_asset_id: str,
    ) -> PlaygroundAsset:
        if media_type not in MEDIA_TYPES:
            raise ValueError("不支持的媒体类型。")
        async with self._lock:
            return self._ingest(
                media_type=media_type,
                content=content,
                origin_dir="from-projects",
                label=label,
                origin=AssetOrigin(
                    "copied_from_project",
                    project_id=project_id,
                    asset_id=source_asset_id,
                ),
            )

    def _ingest(
        self,
        *,
        media_type: str,
        content: bytes,
        origin_dir: str,
        label: str,
        origin: AssetOrigin,
    ) -> PlaygroundAsset:
        holder: dict[str, PlaygroundAsset] = {}

        def mutate(previous: PlaygroundDocument) -> PlaygroundDocument:
            updated, asset = self._store.ingest_asset(
                previous,
                media_type=media_type,
                content=content,
                origin_dir=origin_dir,
                label=label,
                origin=origin,
                created_at=utc_timestamp(),
            )
            holder["asset"] = asset
            # 重复字节直接返回已有 Asset：不改 origin、不重写文件、不推进 revision。
            if updated is previous:
                return previous
            return replace(updated, revision=previous.revision + 1)

        self._store.commit(mutate)
        return holder["asset"]

    async def delete_assets(self, asset_ids: tuple[str, ...]) -> tuple[str, ...]:
        unique: list[str] = []
        for asset_id in asset_ids:
            if asset_id not in unique:
                unique.append(asset_id)
        if not 1 <= len(unique) <= 200:
            raise ValueError("一次删除 1 到 200 个 Asset。")
        async with self._lock:
            document = self._store.read()
            targets = []
            for asset_id in unique:
                asset = next((item for item in document.assets if item.id == asset_id), None)
                if asset is None:
                    raise AssetNotFoundError("Asset 不存在。")
                targets.append(asset)
            usage = asset_usage(document)
            blocked = tuple(item.id for item in targets if usage.get(item.id))
            if blocked:
                raise AssetInUseError(
                    "该素材正被未结束的实验使用，请等待或取消相关实验后再删除。",
                    blocked,
                )
            staged = self._store.stage_asset_files(tuple(targets))
            try:
                self._store.commit(
                    lambda previous: replace(
                        previous,
                        revision=previous.revision + 1,
                        assets=tuple(
                            item for item in previous.assets if item.id not in set(unique)
                        ),
                    )
                )
            except Exception:
                self._store.restore_staged_asset_files(staged)
                raise
            self._store.unlink_staged_asset_files(staged)
        return tuple(unique)

    def video_frame_info(self, asset_id: str) -> Mp4VideoFrames:
        asset, content = self._store.read_asset(asset_id)
        if asset.media_type != "video/mp4":
            raise ValueError("只有 MP4 视频可以抽帧。")
        return read_mp4_video_frames(content)

    # ------------------------------------------------------------ 观察与管理

    def provider_for(self, run: PlaygroundRun) -> object:
        return provider_for_run(self._registry, run)

    async def refresh_run(self, run_id: str) -> PlaygroundRun:
        return await self._observer.refresh_run(run_id)

    async def refresh_active_runs(self) -> PlaygroundDocument:
        return await self._observer.refresh_active_runs()

    async def cancel_run(
        self, run_id: str, *, request: RequestContext | None = None
    ) -> PlaygroundRun:
        return await self._observer.cancel_run(run_id, request=request)

    async def wait_runs(self, run_ids: tuple[str, ...]) -> tuple[PlaygroundRun, ...]:
        ordered: list[str] = []
        for run_id in run_ids:
            if run_id not in ordered:
                ordered.append(run_id)
        if not 1 <= len(ordered) <= 8:
            raise ValueError("wait_runs 需要 1 到 8 个 run_id。")
        for run_id in ordered:
            find_run(self._store.read(), run_id)
        max_wait, poll_seconds = wait_budget()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait
        while True:
            await self._bounded_observer.refresh(ordered, self.refresh_run, deadline)
            document = self._store.read()
            observed = [find_run(document, run_id) for run_id in ordered]
            if all(run.phase in TERMINAL_PHASES for run in observed):
                break
            if loop.time() >= deadline:
                break
            await asyncio.sleep(min(poll_seconds, max(0.0, deadline - loop.time())))
        return tuple(observed)

    async def dismiss_run(
        self, run_id: str, *, request: RequestContext | None = None
    ) -> PlaygroundRun:
        async with self._lock:
            document = self._store.read()
            run = find_run(document, run_id)
            if run.phase not in TERMINAL_PHASES:
                raise RunStateConflictError("只有已结束的实验可以隐藏。")
            if run.dismissed:
                return run
            return self._mutate_run(
                run_id,
                lambda current, _document: replace(current, dismissed=True),
                request=request,
                summary="已隐藏该实验。",
            )

    async def set_note(
        self, run_id: str, note: str | None, *, request: RequestContext | None = None
    ) -> PlaygroundRun:
        normalized = None if note is None else note.strip() or None
        async with self._lock:
            document = self._store.read()
            run = find_run(document, run_id)
            if run.note == normalized:
                return run
            return self._mutate_run(
                run_id,
                lambda current, _document: replace(current, note=normalized),
                request=request,
                summary="已更新实验备注。",
            )


def _capability(value: object) -> PlaygroundCapability:
    try:
        return PlaygroundCapability(value)
    except ValueError as exc:
        raise ValueError(f"不支持的 capability：{value}") from exc


def _reject_active_frame_extraction(document: PlaygroundDocument, video_asset_id: str) -> None:
    conflict = any(
        run.capability is PlaygroundCapability.VIDEO_EXTRACT_FRAME
        and run.phase in UNFINISHED_PHASES
        and run.parameters.get("video_asset_id") == video_asset_id
        for run in document.runs
    )
    if conflict:
        raise RunStateConflictError("该视频已有抽帧任务在进行中。")
