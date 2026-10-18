"""逐句对白 TTS：有参考音色强制克隆，否则强制 Voice Design。"""

from __future__ import annotations

from uuid import uuid4

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import MediaInput

from ..models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from ..production_context import _TERMINAL_PHASES
from .audio import _submitted_params, prepare_tts_recipe
from .support import _commit_submission


class DialogueSubmission:
    async def _submit_dialogue_generation(
        self,
        document: StructuredDirectorDocument,
        dialogue_line_id: str,
        *,
        retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        line, plan_item = _dialogue_context(document, dialogue_line_id)
        if any(
            generation.kind is ReferenceGenerationKind.DIALOGUE_AUDIO
            and generation.target_id == dialogue_line_id
            and generation.phase not in _TERMINAL_PHASES
            for generation in document.generations
        ):
            raise ValueError("该句对白已有进行中的 TTS 任务。")

        card = (
            None
            if line.character_id is None
            else next(
                (
                    item
                    for item in document.reference_library.characters
                    if item.id == line.character_id
                ),
                None,
            )
        )
        if line.character_id is not None and card is None:
            raise ValueError("对白引用的角色卡不存在。")
        voice_asset_id = None if card is None else card.voice_reference_asset_id
        capability = (
            Capability.SPEECH_SYNTHESIZE if voice_asset_id is not None else Capability.VOICE_DESIGN
        )
        prepared = prepare_tts_recipe(self._registry, capability, retry_of)
        mechanism = plan_item.recipe_params.get(prepared.recipe.id)
        if voice_asset_id is not None:
            if mechanism is None and any(
                field.key == "performance_instruction" and field.role is None
                for field in prepared.recipe.params
            ):
                mechanism = {"performance_instruction": line.delivery.strip() or None}
            transcript = (card.voice_reference_transcript or "").strip()
            if not transcript:
                raise ValueError("该角色已有参考音色，但缺少参考音频的完整文字稿，不能克隆。")
            voice_asset, voice_content = self._store.read_asset(voice_asset_id)
            request, submitted = prepared.request(
                roles={
                    Role.SPEECH_TEXT: line.text,
                    Role.VOICE_TRANSCRIPT: transcript,
                    Role.SEED: plan_item.seed,
                },
                media={Role.VOICE_REFERENCE: (MediaInput(voice_asset.media_type, voice_content),)},
                mechanism=mechanism,
            )
            operation = GenerationOperation.SYNTHESIZE
            sample_text = transcript
            input_asset_ids = (voice_asset_id,)
        else:
            description = (
                line.voice_description if card is None else card.voice_description
            ).strip()
            if not description:
                raise ValueError("该说话者没有参考音色，请先填写音色描述以使用 Voice Design。")
            if mechanism:
                raise ValueError("Voice Design 对白不能携带语音克隆机制参数。")
            request, submitted = prepared.request(
                roles={
                    Role.PROMPT: description,
                    Role.SPEECH_TEXT: line.text,
                    Role.SEED: plan_item.seed,
                }
            )
            operation = GenerationOperation.VOICE_DESIGN
            sample_text = description
            input_asset_ids = ()

        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.DIALOGUE_AUDIO,
            operation=operation,
            target_id=dialogue_line_id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message="正在提交对白 TTS 任务。",
            prompt_text=line.text,
            input_asset_ids=input_asset_ids,
            sample_text=sample_text,
            seed=plan_item.seed,
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
        return await _commit_submission(
            self,
            document,
            generation,
            expected_revision=document.revision,
            submit=lambda: prepared.submit(request),
            capability=f"{prepared.plugin.manifest.label} 对白 TTS",
            queued_message="对白 TTS 任务已提交。",
            retry_of=retry_of,
        )


def _dialogue_context(document, dialogue_line_id):
    if document.director_script is None or document.dialogue_plan is None:
        raise ValueError("对白 TTS 计划不存在。")
    line = next(
        (
            line
            for scene in document.director_script.scenes
            for segment in scene.segments
            for line in segment.dialogue_lines
            if line.id == dialogue_line_id
        ),
        None,
    )
    item = next(
        (
            item
            for item in document.dialogue_plan.items
            if item.dialogue_line_id == dialogue_line_id
        ),
        None,
    )
    if line is None or item is None:
        raise ValueError("DialogueLine 不存在。")
    return line, item
