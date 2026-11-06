from __future__ import annotations

import asyncio
from uuid import uuid4

from core.media_assets.media_bytes import prepend_wav_silence
from core.model_providers.contracts import (
    AssemblyClip,
    AssemblyNarration,
    FinalAssemblyRequest,
)

from ..assembly_timeline import (
    _align_clip_durations_to_narration,
    _clip_starts,
    scene_final_input_asset_ids,
)
from ..generation_lifecycle import (
    _link_generation_retry,
    _submission_failure,
)
from ..models import (
    FinalAssemblyPlan,
    GenerationOperation,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    SceneAssemblyPlan,
    StructuredDirectorDocument,
    transition_generation,
)
from ..provider_ports import (
    FinalAssemblyProvider,
)
from .support import (
    _ASSEMBLY_TRANSITION_SECONDS,
)

_LABELS = {NarrationLanguage.ZH: "中文", NarrationLanguage.EN: "英文"}


class AssemblySubmission:
    async def _submit_scene_final_assembly(
        self,
        document: StructuredDirectorDocument,
        plan: SceneAssemblyPlan,
        *,
        scene_id: str,
        retry_of: ReferenceGeneration | None,
        video_audio_volume: float = 1.0,
        narration_audio_volume: float = 1.0,
    ) -> StructuredDirectorDocument:
        """渲染单个 Scene 某一语言的成片：Segment 视频按序拼接并精确混入该语言旁白。

        画面按已选旁白的时间基准对齐，因此两种语言的成片画面时间轴完全一致。
        """
        provider = self._final_assembly_provider
        if provider is None:
            raise RuntimeError("FFmpeg 成片装配服务尚未配置。")
        clip_index = {item.segment_id: index for index, item in enumerate(plan.clips)}
        clip_contents: list[bytes] = []
        clip_durations: list[float] = []
        for item in plan.clips:
            asset, content = self._store.read_asset(item.asset_id)
            clip_contents.append(content)
            clip_durations.append(asset.duration_seconds or 0.0)
        narration_inputs = []
        narration_durations: dict[str, float] = {}
        for item in plan.narrations:
            _asset, content = self._store.read_asset(item.asset_id)
            start = clip_index[item.start_segment_id]
            # 旁白居中：在 WAV 前补静音，FFmpeg 仍从起始 clip 对齐。
            content = prepend_wav_silence(content, item.start_offset_seconds)
            narration_inputs.append(AssemblyNarration(content, start))
            narration_durations[item.cue_id] = item.timing_seconds
        clip_durations = _align_clip_durations_to_narration(
            document,
            plan,
            clip_durations,
            narration_durations,
            _ASSEMBLY_TRANSITION_SECONDS,
            scene_ids={scene_id},
        )
        clip_inputs = [
            AssemblyClip(
                content,
                None
                if item.transition_from_previous is None
                else item.transition_from_previous.value,
                clip_durations[index],
            )
            for index, (item, content) in enumerate(zip(plan.clips, clip_contents, strict=True))
        ]
        starts = _clip_starts(
            clip_durations,
            _ASSEMBLY_TRANSITION_SECONDS,
            [clip.transition_from_previous for clip in plan.clips],
        )
        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.SCENE_FINAL_VIDEO,
            operation=GenerationOperation.ASSEMBLE,
            target_id=scene_id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message=f"正在提交{_LABELS[plan.language]} Scene 成片装配任务。",
            prompt_text=(
                f"按脚本顺序装配 {len(plan.clips)} 个 Segment；"
                "启用的共享边界使用短接缝融合，否则硬切；"
                f"画面按已选旁白的时间基准对齐，定位并混入 {len(plan.narrations)} 条"
                f"已审核{_LABELS[plan.language]}旁白。"
            ),
            input_asset_ids=scene_final_input_asset_ids(plan),
            sample_text=None,
            seed=None,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            duration_seconds=starts[-1] + clip_durations[-1],
            language=plan.language,
        )
        return await self._submit_assembly_request(
            document,
            provider=provider,
            generation=generation,
            clip_inputs=tuple(clip_inputs),
            narration_inputs=tuple(narration_inputs),
            retry_of=retry_of,
            video_audio_volume=video_audio_volume,
            narration_audio_volume=narration_audio_volume,
            capability="FFmpeg Scene 成片装配",
            queued_message="Scene 成片装配任务已提交。",
        )

    async def _submit_final_assembly(
        self,
        document: StructuredDirectorDocument,
        plan: FinalAssemblyPlan,
        *,
        language: NarrationLanguage,
        retry_of: ReferenceGeneration | None,
    ) -> StructuredDirectorDocument:
        """某一语言的最终成片只按脚本顺序拼接该语言的 Scene 成片，不重新混入旁白。"""
        provider = self._final_assembly_provider
        if provider is None:
            raise RuntimeError("FFmpeg 成片装配服务尚未配置。")
        clip_contents: list[bytes] = []
        input_asset_ids: list[str] = []
        clip_durations: list[float] = []
        for item in plan.clips:
            asset, content = self._store.read_asset(item.asset_id(language))
            clip_contents.append(content)
            input_asset_ids.append(asset.id)
            clip_durations.append(asset.duration_seconds or 0.0)
        if any(duration <= 0 for duration in clip_durations):
            raise ValueError("Scene 成片缺少真实时长，请重新生成对应 Scene 成片。")
        clip_inputs = [
            AssemblyClip(
                content,
                None
                if item.transition_from_previous is None
                else item.transition_from_previous.value,
                clip_durations[index],
            )
            for index, (item, content) in enumerate(zip(plan.clips, clip_contents, strict=True))
        ]
        starts = _clip_starts(
            clip_durations,
            _ASSEMBLY_TRANSITION_SECONDS,
            [clip.transition_from_previous for clip in plan.clips],
        )
        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.FINAL_VIDEO,
            operation=GenerationOperation.ASSEMBLE,
            target_id=document.project_id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message=f"正在提交{_LABELS[language]}最终成片装配任务。",
            prompt_text=(
                f"按脚本顺序拼接 {len(plan.clips)} 个{_LABELS[language]} Scene 成片；"
                "Scene 内转场与旁白已固化在成片字节里；"
                "跨 Scene 的共享边界使用短接缝融合，否则硬切。"
            ),
            input_asset_ids=tuple(dict.fromkeys(input_asset_ids)),
            sample_text=None,
            seed=None,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            duration_seconds=starts[-1] + clip_durations[-1],
            language=language,
        )
        return await self._submit_assembly_request(
            document,
            provider=provider,
            generation=generation,
            clip_inputs=tuple(clip_inputs),
            narration_inputs=(),
            retry_of=retry_of,
            video_audio_volume=1.0,
            narration_audio_volume=1.0,
            capability="FFmpeg 成片装配",
            queued_message="最终成片装配任务已提交。",
        )

    async def _submit_assembly_request(
        self,
        document: StructuredDirectorDocument,
        *,
        provider: FinalAssemblyProvider,
        generation: ReferenceGeneration,
        clip_inputs: tuple[AssemblyClip, ...],
        narration_inputs: tuple[AssemblyNarration, ...],
        retry_of: ReferenceGeneration | None,
        video_audio_volume: float,
        narration_audio_volume: float,
        capability: str,
        queued_message: str,
    ) -> StructuredDirectorDocument:
        generation = _link_generation_retry(document, generation, retry_of)
        request = FinalAssemblyRequest(
            clip_inputs,
            narration_inputs,
            document.aspect_ratio.value,
            _ASSEMBLY_TRANSITION_SECONDS,
            video_audio_volume,
            narration_audio_volume,
        )
        self._store.create_generation(generation, expected_revision=document.revision)
        try:
            handle = await asyncio.to_thread(provider.submit, request)
        except Exception as exc:
            return self._store.update_generation(
                _submission_failure(generation, exc, capability=capability)
            )
        return self._store.update_generation(
            transition_generation(
                generation,
                ReferenceGenerationPhase.QUEUED,
                message=queued_message,
                plugin_id=handle.plugin_id,
                plugin_version=handle.plugin_version,
                external_id=handle.external_id,
            )
        )
