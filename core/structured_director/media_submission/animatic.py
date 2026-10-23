from __future__ import annotations

import asyncio
from uuid import uuid4

from core.media_assets.media_bytes import prepend_wav_silence
from core.model_providers.contracts import (
    AnimaticClip,
    AnimaticNarration,
    AnimaticRequest,
)

from ..assembly_timeline import (
    _build_scene_animatic_spec,
)
from ..generation_lifecycle import (
    _link_generation_retry,
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
from ..store import RevisionConflictError


class AnimaticSubmission:
    async def generate_scene_animatic(
        self,
        *,
        scene_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        provider = self._animatic_provider
        if provider is None:
            raise RuntimeError("FFmpeg Animatic 服务尚未配置。")
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再合成 Animatic 预览。")
            if not document.is_reviewing or not document.workspace_layers.keyframes_unlocked:
                raise ValueError("当前不能合成 Scene Animatic 预览。")
            spec = _build_scene_animatic_spec(document, scene_id)
            if any(
                item.kind is ReferenceGenerationKind.SCENE_ANIMATIC
                and item.target_id == scene_id
                and item.phase not in _TERMINAL_PHASES
                for item in document.generations
            ):
                raise ValueError("该 Scene 已有进行中的 Animatic 合成任务。")
            transition_seconds = 0.1
            clip_inputs = []
            input_asset_ids: list[str] = []
            for asset_id, transition, duration in zip(
                spec.clip_asset_ids,
                spec.clip_transitions,
                spec.clip_durations,
                strict=True,
            ):
                asset, content = self._store.read_asset(asset_id)
                clip_inputs.append(AnimaticClip(content, transition, duration))
                input_asset_ids.append(asset.id)
            narration_inputs = []
            for asset_id, start, offset in zip(
                spec.narration_asset_ids,
                spec.narration_start_clip_indices,
                spec.narration_start_offsets,
                strict=True,
            ):
                asset, content = self._store.read_asset(asset_id)
                content = prepend_wav_silence(content, offset)
                narration_inputs.append(AnimaticNarration(content, start))
                input_asset_ids.append(asset.id)
            generation = ReferenceGeneration(
                id=uuid4().hex,
                kind=ReferenceGenerationKind.SCENE_ANIMATIC,
                operation=GenerationOperation.ASSEMBLE,
                target_id=scene_id,
                phase=ReferenceGenerationPhase.SUBMITTING,
                progress=0.0,
                message="正在提交 Animatic 合成任务。",
                prompt_text=(
                    f"按脚本顺序展示 {len(clip_inputs)} 张关键帧画面；"
                    "首尾帧齐备的 Segment 平分展示时长；"
                    f"定位并混入 {len(narration_inputs)} 条已审核旁白。"
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
                duration_seconds=spec.duration_seconds,
            )
            generation = _link_generation_retry(document, generation, _retry_of)
            request = AnimaticRequest(
                tuple(clip_inputs),
                tuple(narration_inputs),
                document.aspect_ratio.value,
                transition_seconds,
            )
            self._store.create_generation(generation, expected_revision=document.revision)
            try:
                handle = await asyncio.to_thread(provider.submit, request)
            except Exception as exc:
                return self._store.update_generation(
                    _submission_failure(generation, exc, capability="FFmpeg Animatic 合成")
                )
            return self._store.update_generation(
                transition_generation(
                    generation,
                    ReferenceGenerationPhase.QUEUED,
                    message="Animatic 合成任务已提交。",
                    plugin_id=handle.plugin_id,
                    plugin_version=handle.plugin_version,
                    external_id=handle.external_id,
                )
            )
