from __future__ import annotations

import asyncio
from uuid import uuid4

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import MediaInput

from ..generation_lifecycle import (
    _link_generation_retry,
    _next_generation_seed,
    _submission_failure,
)
from ..models import (
    GenerationOperation,
    NarrationCue,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    transition_generation,
)
from ..production_context import (
    _TERMINAL_PHASES,
)
from .audio import _submitted_params, prepare_tts_recipe


class NarrationSubmission:
    async def _submit_narration_generation(
        self,
        document: StructuredDirectorDocument,
        cue: NarrationCue,
        language: NarrationLanguage,
        *,
        retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        """为 Cue 的某一语言提交 TTS；只用旁白身份同语言的参考音色克隆。"""
        prepared = prepare_tts_recipe(self._registry, Capability.SPEECH_SYNTHESIZE, retry_of)
        narrator = document.reference_library.narrator
        label = "中文" if language is NarrationLanguage.ZH else "英文"
        if narrator is None:
            raise ValueError("请先在引用库建立独立旁白身份。")
        voice = narrator.voice(language)
        if voice.voice_reference_asset_id is None:
            raise ValueError(f"请先为独立旁白身份选择{label}参考音色。")
        if any(
            generation.kind is ReferenceGenerationKind.NARRATION_AUDIO
            and generation.target_id == cue.id
            and generation.language is language
            and generation.phase not in _TERMINAL_PHASES
            for generation in document.generations
        ):
            raise ValueError("该旁白此语言已有进行中的生成任务。")
        track = cue.track(language)
        voice_asset, voice_content = self._store.read_asset(voice.voice_reference_asset_id)
        seed = (
            retry_of.seed
            if retry_of is not None
            else _next_generation_seed(
                document,
                ReferenceGenerationKind.NARRATION_AUDIO,
                cue.id,
                track.seed,
                language=language,
            )
        )
        if not voice.voice_reference_transcript:
            raise ValueError(f"请先在引用库为旁白{label}参考音色填写完整文字稿。")
        try:
            request, submitted = prepared.request(
                roles={
                    Role.SPEECH_TEXT: track.text,
                    Role.VOICE_TRANSCRIPT: voice.voice_reference_transcript,
                    Role.SEED: seed,
                    Role.LANGUAGE: language.value,
                },
                media={Role.VOICE_REFERENCE: (MediaInput(voice_asset.media_type, voice_content),)},
                mechanism=track.recipe_params.get(prepared.recipe.id),
            )
        except ValueError as exc:
            raise ValueError(f"旁白{label}合成参数需要更新：{exc}") from exc
        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.NARRATION_AUDIO,
            operation=GenerationOperation.SYNTHESIZE,
            target_id=cue.id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message="正在提交旁白生成任务。",
            prompt_text=track.text,
            input_asset_ids=(voice.voice_reference_asset_id,),
            seed=seed,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            sample_text=voice.voice_reference_transcript,
            language=language,
            provider_snapshot=prepared.snapshot,
            recipe_params=_submitted_params(prepared, submitted),
        )
        generation = _link_generation_retry(document, generation, retry_of)
        self._store.create_generation(generation, expected_revision=document.revision)
        try:
            handle = await asyncio.to_thread(prepared.submit, request)
        except Exception as exc:
            return self._store.update_generation(
                _submission_failure(
                    generation,
                    exc,
                    capability=f"{prepared.plugin.manifest.label} 旁白生成",
                )
            )
        queued = transition_generation(
            generation,
            ReferenceGenerationPhase.QUEUED,
            message="旁白生成任务已提交。",
            plugin_id=handle.plugin_id,
            plugin_version=handle.plugin_version,
            external_id=handle.external_id,
        )
        return self._store.update_generation(queued)
