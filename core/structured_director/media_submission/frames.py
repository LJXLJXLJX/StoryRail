from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

from core.media_assets import read_mp4_video_frames
from core.model_providers.contracts import (
    VideoFrameRequest as SubmissionVideoFrameRequest,
)
from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import MediaInput

from ..generation_lifecycle import (
    _link_generation_retry,
    _next_generation_seed,
    _submission_failure,
)
from ..models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    transition_generation,
)
from ..production_context import (
    _TERMINAL_PHASES,
)
from ..video_contracts import VideoFrameRequest as CoreVideoFrameRequest
from ..video_inputs import start_frame_extraction_source


class FrameSubmission:
    async def extract_keyframe_video_frame(
        self,
        *,
        keyframe_id: str,
        frame_index: int,
        expected_source_video_asset_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        """从上一 Segment 当前视频抽取一帧，成功后成为该首帧的候选（不自动选择）。"""
        provider = self._video_frame_provider
        if provider is None:
            raise RuntimeError("FFmpeg 视频抽帧服务尚未配置。")
        async with self._lock:
            document = self._store.read()
            if not self._store.revision_matches(document, expected_revision):
                raise ValueError("项目已被更新，请刷新后再抽帧。")
            if not document.is_reviewing or not document.workspace_layers.keyframes_unlocked:
                raise ValueError("当前不在关键帧生产阶段。")
            source = start_frame_extraction_source(document, keyframe_id)
            if source["state"] != "ready":
                raise ValueError(source["message"])
            if source["source_video_asset_id"] != expected_source_video_asset_id:
                raise ValueError("上一段视频已变化，请刷新后重新选择帧号。")
            _reject_active_frame_extraction(document, keyframe_id)
            asset, content = self._store.read_asset(expected_source_video_asset_id)
            request_meta = _frame_request(asset, content, frame_index, source["source_segment_id"])
            generation = _frame_generation(
                keyframe_id,
                asset.id,
                request_meta,
                prompt_text=f"从上一 Segment 视频抽取第 {frame_index} 帧作为首帧候选。",
            )
            generation = _link_generation_retry(document, generation, _retry_of)
            return await self._submit_frame(provider, generation, content, document.revision)

    async def extract_asset_video_frame(
        self,
        *,
        asset_id: str,
        frame_index: int,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        provider = self._video_frame_provider
        if provider is None:
            raise RuntimeError("FFmpeg 视频抽帧服务尚未配置。")
        async with self._lock:
            document = self._store.read()
            if not self._store.revision_matches(document, expected_revision):
                raise ValueError("项目已被更新，请刷新后再抽帧。")
            asset, content = self._store.read_asset(asset_id)
            if asset.media_type != "video/mp4":
                raise ValueError("只有 MP4 视频可以抽帧。")
            _reject_active_frame_extraction(document, asset_id)
            request_meta = _frame_request(asset, content, frame_index, None)
            generation = _frame_generation(
                asset_id,
                asset.id,
                request_meta,
                prompt_text=f"从资产中心视频抽取第 {frame_index} 帧。",
            )
            generation = _link_generation_retry(document, generation, _retry_of)
            return await self._submit_frame(provider, generation, content, document.revision)

    async def _submit_frame(self, provider, generation, content, revision):
        request = generation.video_frame_request
        assert request is not None and request.frame_index is not None
        self._store.create_generation(generation, expected_revision=revision)
        try:
            handle = await asyncio.to_thread(
                provider.submit, SubmissionVideoFrameRequest(content, request.frame_index)
            )
        except Exception as exc:
            return self._store.update_generation(
                _submission_failure(generation, exc, capability="视频抽帧")
            )
        return self._store.update_generation(
            transition_generation(
                generation,
                ReferenceGenerationPhase.QUEUED,
                message="视频抽帧任务已提交。",
                plugin_id=handle.plugin_id,
                plugin_version=handle.plugin_version,
                external_id=handle.external_id,
            )
        )

    async def upscale_segment_video(
        self,
        *,
        segment_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        prepared = self._registry.prepare_recipe(Capability.VIDEO_UPSCALE)
        async with self._lock:
            document = self._store.read()
            if not self._store.revision_matches(document, expected_revision):
                raise ValueError("项目已被更新，请重新读取后再提交超分。")
            if not document.is_reviewing or not document.workspace_layers.videos_unlocked:
                raise ValueError("当前不在视频生产阶段。")
            plan = document.video_plan
            if plan is None:
                raise ValueError("视频计划不存在。")
            item = next((value for value in plan.segments if value.segment_id == segment_id), None)
            if item is None or item.selected_asset_id is None:
                raise ValueError("请先选择该 Segment 的原始视频。")
            if item.upscaled_asset_id is not None:
                raise ValueError("该 Segment 已经完成超分。")
            if any(
                generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE
                and generation.target_id == segment_id
                and generation.phase not in _TERMINAL_PHASES
                for generation in document.generations
            ):
                raise ValueError("该 Segment 已有进行中的超分任务。")
            asset, content = self._store.read_asset(item.selected_asset_id)
            generation = ReferenceGeneration(
                id=uuid4().hex,
                kind=ReferenceGenerationKind.VIDEO_UPSCALE,
                operation=GenerationOperation.UPSCALE,
                target_id=segment_id,
                phase=ReferenceGenerationPhase.SUBMITTING,
                progress=0.0,
                message="正在提交视频超分任务。",
                prompt_text=prepared.recipe.label,
                input_asset_ids=(asset.id,),
                sample_text=None,
                seed=(
                    _retry_of.seed
                    if _retry_of is not None
                    else _next_generation_seed(
                        document,
                        ReferenceGenerationKind.VIDEO_UPSCALE,
                        segment_id,
                        int(segment_id[:16], 16) % (2**63),
                    )
                ),
                plugin_id=None,
                plugin_version=None,
                external_id=None,
                output_asset_id=None,
                error_code=None,
                cancellation_requested=False,
                retry_of=None,
                duration_seconds=None,
            )
            generation = _link_generation_retry(document, generation, _retry_of)
            request, _mechanism = prepared.request(
                roles={Role.SEED: generation.seed if generation.seed is not None else 42},
                media={
                    Role.SOURCE_VIDEO: (
                        MediaInput(
                            asset.media_type, content, duration_seconds=asset.duration_seconds
                        ),
                    )
                },
            )
            generation = replace(generation, provider_snapshot=prepared.snapshot)
            self._store.create_generation(generation, expected_revision=document.revision)
            try:
                handle = await asyncio.to_thread(prepared.submit, request)
            except Exception as exc:
                return self._store.update_generation(
                    _submission_failure(generation, exc, capability="视频超分")
                )
            return self._store.update_generation(
                transition_generation(
                    generation,
                    ReferenceGenerationPhase.QUEUED,
                    message="视频超分任务已提交。",
                    plugin_id=handle.plugin_id,
                    plugin_version=handle.plugin_version,
                    external_id=handle.external_id,
                )
            )


def _reject_active_frame_extraction(document, target_id):
    if any(
        item.kind is ReferenceGenerationKind.VIDEO_FRAME
        and item.target_id == target_id
        and item.phase not in _TERMINAL_PHASES
        for item in document.generations
    ):
        raise ValueError("已有进行中的抽帧任务，请等待完成或取消后再抽取。")


def _frame_request(asset, content, frame_index, source_segment_id):
    frames = read_mp4_video_frames(content)
    return CoreVideoFrameRequest(
        source_video_asset_id=asset.id,
        source_sha256=asset.sha256,
        frame_index=frame_index,
        frame_count=frames.frame_count,
        source_segment_id=source_segment_id,
    )


def _frame_generation(target_id, source_asset_id, request_meta, *, prompt_text):
    return ReferenceGeneration(
        id=uuid4().hex,
        kind=ReferenceGenerationKind.VIDEO_FRAME,
        operation=GenerationOperation.PROCESS,
        target_id=target_id,
        phase=ReferenceGenerationPhase.SUBMITTING,
        progress=0.0,
        message="正在提交视频抽帧任务。",
        prompt_text=prompt_text,
        input_asset_ids=(source_asset_id,),
        sample_text=None,
        seed=None,
        plugin_id=None,
        plugin_version=None,
        external_id=None,
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=None,
        video_frame_request=request_meta,
    )
