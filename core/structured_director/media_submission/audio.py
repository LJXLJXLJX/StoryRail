from __future__ import annotations

import asyncio
from uuid import uuid4

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import MediaInput, RecipeParams
from core.model_providers.registry import PreparedRecipe

from ..generation_lifecycle import (
    _link_generation_retry,
    _next_generation_seed,
    _submission_failure,
)
from ..models import (
    GenerationOperation,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    transition_generation,
)
from ..store import RevisionConflictError
from .support import _commit_submission

_NO_PARAMS = RecipeParams()


def prepare_tts_recipe(registry, capability: Capability, retry_of: ReferenceGeneration | None):
    """新提交按当前绑定；重试回到原 Generation 记录的插件与 recipe。"""
    snapshot = None if retry_of is None else retry_of.provider_snapshot
    if snapshot is None:
        return registry.prepare_recipe(capability)
    return registry.prepare_recipe(
        capability, plugin_id=snapshot.plugin_id, recipe_id=snapshot.recipe_id
    )


def _asset_audio_request(
    store,
    prepared: PreparedRecipe,
    **fields,
):
    voice_asset_id = fields["voice_asset_id"]
    mechanism = fields["recipe_params"].get(prepared.recipe.id)
    if voice_asset_id is None:
        if fields["reference_transcript"] is not None or mechanism:
            raise ValueError("Voice Design 不能包含参考文字稿或克隆参数。")
        description = (fields["voice_description"] or "").strip()
        text = fields["text"].strip()
        request, submitted = prepared.request(
            roles={Role.PROMPT: description, Role.SPEECH_TEXT: text, Role.SEED: fields["seed"]},
        )
        operation = GenerationOperation.VOICE_DESIGN
        prompt_text = description
        sample_text = text
        input_ids: tuple[str, ...] = ()
    else:
        if fields["voice_description"] is not None:
            raise ValueError("Voice Clone/Direction 不能提交 Voice Description。")
        voice_asset, voice_content = store.read_asset(voice_asset_id)
        text = fields["text"].strip()
        transcript = (fields["reference_transcript"] or "").strip()
        request, submitted = prepared.request(
            roles={
                Role.SPEECH_TEXT: text,
                Role.VOICE_TRANSCRIPT: transcript,
                Role.SEED: fields["seed"],
            },
            media={Role.VOICE_REFERENCE: (MediaInput(voice_asset.media_type, voice_content),)},
            mechanism=mechanism,
        )
        operation = GenerationOperation.SYNTHESIZE
        prompt_text = text
        sample_text = transcript
        input_ids = (voice_asset_id,)
    generation = _submitting_audio(
        generation_id=fields["generation_id"],
        target_id=fields["target_id"],
        operation=operation,
        message=f"正在提交 {prepared.plugin.manifest.label} 音频生成任务。",
        prompt_text=prompt_text,
        input_asset_ids=input_ids,
        sample_text=sample_text,
        seed=fields["seed"],
        prepared=prepared,
        submitted=submitted,
    )
    return request, generation


def _submitting_audio(
    *,
    generation_id: str,
    target_id: str,
    operation: GenerationOperation,
    message: str,
    prompt_text: str,
    input_asset_ids: tuple[str, ...],
    sample_text: str | None,
    seed: int,
    prepared: PreparedRecipe,
    submitted: dict,
) -> ReferenceGeneration:
    return ReferenceGeneration(
        id=generation_id,
        kind=ReferenceGenerationKind.GENERATED_AUDIO,
        operation=operation,
        target_id=target_id,
        phase=ReferenceGenerationPhase.SUBMITTING,
        progress=0.0,
        message=message,
        prompt_text=prompt_text,
        input_asset_ids=input_asset_ids,
        sample_text=sample_text,
        seed=seed,
        plugin_id=None,
        plugin_version=None,
        external_id=None,
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        provider_snapshot=prepared.snapshot,
        recipe_params=_submitted_params(prepared, submitted),
    )


def _submitted_params(prepared: PreparedRecipe, submitted: dict) -> RecipeParams:
    return RecipeParams().with_entry(prepared.recipe.id, submitted) if submitted else RecipeParams()


class AudioSubmission:
    async def generate_asset_audio(
        self,
        *,
        text: str,
        seed: int,
        expected_revision: int,
        voice_description: str | None = None,
        voice_asset_id: str | None = None,
        reference_transcript: str | None = None,
        recipe_params: RecipeParams = _NO_PARAMS,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        capability = (
            Capability.VOICE_DESIGN if voice_asset_id is None else Capability.SPEECH_SYNTHESIZE
        )
        prepared = prepare_tts_recipe(self._registry, capability, _retry_of)
        async with self._lock:
            document = self._store.read()
            if not self._store.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已更新，请刷新后重新生成音频。")
            generation_id = uuid4().hex
            request, generation = _asset_audio_request(
                self._store,
                prepared,
                text=text,
                seed=seed,
                voice_description=voice_description,
                voice_asset_id=voice_asset_id,
                reference_transcript=reference_transcript,
                recipe_params=recipe_params,
                generation_id=generation_id,
                target_id=_retry_of.target_id if _retry_of is not None else generation_id,
            )
            label = prepared.plugin.manifest.label
            return await _commit_submission(
                self,
                document,
                generation,
                expected_revision=expected_revision,
                submit=lambda: prepared.submit(request),
                capability=f"{label} 通用音频生成",
                queued_message=f"{label} 音频生成任务已提交。",
                retry_of=_retry_of,
            )

    async def design_voice(
        self,
        *,
        card_id: str,
        voice_description: str,
        sample_text: str,
        seed: int,
        expected_revision: int,
        narrator_language: NarrationLanguage | None = None,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        """设计角色音色；给出 narrator_language 时为旁白该语言设计参考音色。"""
        prepared = prepare_tts_recipe(self._registry, Capability.VOICE_DESIGN, _retry_of)
        kind = (
            ReferenceGenerationKind.CHARACTER_VOICE
            if narrator_language is None
            else ReferenceGenerationKind.NARRATOR_VOICE
        )
        async with self._lock:
            document = self._store.read()
            if (
                narrator_language is not None
                and narrator_language not in document.narration_languages
            ):
                raise ValueError("项目未启用该旁白语言。")
            request_seed = (
                seed
                if _retry_of is not None
                else _next_generation_seed(
                    document,
                    kind,
                    card_id,
                    seed,
                    maximum=2**32 - 1,
                    language=narrator_language,
                )
            )
            description = voice_description.strip()
            text = sample_text.strip()
            request, submitted = prepared.request(
                roles={Role.PROMPT: description, Role.SPEECH_TEXT: text, Role.SEED: request_seed}
            )
            generation = ReferenceGeneration(
                id=uuid4().hex,
                kind=kind,
                operation=GenerationOperation.VOICE_DESIGN,
                target_id=card_id,
                phase=ReferenceGenerationPhase.SUBMITTING,
                progress=0.0,
                message="正在提交音色设计任务。",
                prompt_text=description,
                input_asset_ids=(),
                sample_text=text,
                seed=request_seed,
                plugin_id=None,
                plugin_version=None,
                external_id=None,
                output_asset_id=None,
                error_code=None,
                cancellation_requested=False,
                retry_of=None,
                language=narrator_language,
                provider_snapshot=prepared.snapshot,
                recipe_params=_submitted_params(prepared, submitted),
            )
            generation = _link_generation_retry(document, generation, _retry_of)
            self._store.create_generation(generation, expected_revision=expected_revision)
            try:
                handle = await asyncio.to_thread(prepared.submit, request)
            except Exception as exc:
                return self._store.update_generation(
                    _submission_failure(generation, exc, capability="音色设计")
                )
            queued = transition_generation(
                generation,
                ReferenceGenerationPhase.QUEUED,
                message="音色设计任务已提交。",
                plugin_id=handle.plugin_id,
                plugin_version=handle.plugin_version,
                external_id=handle.external_id,
            )
            return self._store.update_generation(queued)
