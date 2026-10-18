from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, replace
from uuid import uuid4

from core.application.caller import (
    PROPOSAL_KINDS,
    READ_OPERATIONS,
    authorize_command,
    current_caller,
)
from core.audio_effects import (
    AUDIO_EFFECT_PROCESSOR_VERSION,
    AUDIO_TRIM_PROCESSOR_VERSION,
    AudioEffectRequest,
    AudioTrimRequest,
    audio_effect_record,
    audio_trim_record,
)
from core.audio_effects import (
    apply_audio_effect as render_audio_effect,
)
from core.audio_effects import (
    trim_audio as render_audio_trim,
)
from core.director_commands import (
    CommandExecution,
    CommandReceipt,
    DirectorCommand,
    DirectorCommandRegistry,
    InvalidArgumentsError,
    director_command_id,
    parse_animatic_scene_target,
    parse_empty_arguments,
    parse_final_scene_target,
    parse_generation_target,
    parse_generation_wait,
)
from core.director_proposals import (
    CharacterCardProposal,
    StructuredDirectorScriptRevisionProposal,
)
from core.media_assets import Mp4VideoFrames, read_mp4_video_frames
from core.model_providers.boundary import (
    GenerationObservation,
    ProviderHandle,
)
from core.model_providers.contracts import (
    AudioRemixRequest,
)
from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import MediaInput
from core.model_providers.registry import ProviderRegistry

from .application_requests import execute_application_command
from .assembly_timeline import (
    _align_duration_ranges as _align_duration_ranges,
)
from .assembly_timeline import (
    _build_final_assembly_plan as _build_final_assembly_plan,
)
from .assembly_timeline import (
    _build_scene_animatic_spec as _build_scene_animatic_spec,
)
from .assembly_timeline import (
    _build_scene_final_plan as _build_scene_final_plan,
)
from .assembly_timeline import (
    _clip_starts as _clip_starts,
)
from .assembly_timeline import (
    _final_transition as _final_transition,
)
from .character_look_requests import look_sheet_plan, look_sheet_prompt
from .director_steps import (
    _ProductionCommandOutcome as _ProductionCommandOutcome,
)
from .director_steps import (
    _ProductionCommandRequest as _ProductionCommandRequest,
)
from .external_batches import execute as _execute_external_batch
from .generation_lifecycle import (
    _generation_wait_data as _generation_wait_data,
)
from .generation_lifecycle import (
    _link_retry as _link_retry,
)
from .generation_lifecycle import (
    _next_generation_seed as _next_generation_seed,
)
from .generation_lifecycle import _submission_failure
from .generation_observer import GenerationObserver
from .image_inputs import ImageInputs
from .image_prompt_style import image_prompt_style
from .keyframe_requests import (
    KeyframeSubmissionPreview as KeyframeSubmissionPreview,
)
from .keyframe_requests import (
    _active_keyframe_ids as _active_keyframe_ids,
)
from .keyframe_requests import (
    _find_keyframe as _find_keyframe,
)
from .keyframe_requests import (
    _keyframe_effective_prompt as _keyframe_effective_prompt,
)
from .keyframe_requests import (
    _keyframe_generation_inputs as _keyframe_generation_inputs,
)
from .keyframe_requests import (
    _keyframe_preview_document as _keyframe_preview_document,
)
from .keyframe_requests import (
    _keyframe_reference_prompt as _keyframe_reference_prompt,
)
from .manual_commands import (
    keyframe_activation_command,
    keyframe_edit_command,
    keyframe_references_command,
)
from .media_submission import MediaSubmissionUseCases
from .models import (
    Asset,
    CharacterCard,
    GenerationOperation,
    ImageAssetCategory,
    Keyframe,
    KeyframeCharacterReference,
    KeyframeEnvironmentMode,
    NarrationCue,
    NarrationLanguage,
    NarratorProfile,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    SegmentVideo,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    transition_generation,
)
from .production_commands import (
    _execute_production_command_handler as _production_command_handler_impl,
)
from .production_context import (
    _TERMINAL_PHASES as _TERMINAL_PHASES,
)
from .production_context import (
    _director_recent_scene_ids as _director_recent_scene_ids,
)
from .production_context import (
    _production_state_json as _production_state_json,
)
from .provider_ports import (
    AnimaticProvider as AnimaticProvider,
)
from .provider_ports import (
    AudioRemixProvider as AudioRemixProvider,
)
from .provider_ports import (
    FinalAssemblyProvider as FinalAssemblyProvider,
)
from .provider_ports import (
    RecipeProvider as RecipeProvider,
)
from .provider_ports import (
    VideoFrameProvider as VideoFrameProvider,
)
from .reads.video_recipes import video_recipe_state
from .script_index import find_segment, scene_segments
from .store import RevisionConflictError, StructuredDirectorStore


def _parse_application_arguments(parser, *values):
    try:
        return parser(*values)
    except InvalidArgumentsError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from exc


_KIND_CAPABILITY = {
    ReferenceGenerationKind.NARRATION_AUDIO: Capability.SPEECH_SYNTHESIZE.value,
    ReferenceGenerationKind.VIDEO_UPSCALE: Capability.VIDEO_UPSCALE.value,
    ReferenceGenerationKind.SCENE_ANIMATIC: "animatic",
    ReferenceGenerationKind.VIDEO_FRAME: "video_frame",
    ReferenceGenerationKind.LOCATION_VIEW_CROP: "pano_view",
    ReferenceGenerationKind.VIDEO_AUDIO_REMIX: "audio_remix",
    ReferenceGenerationKind.CHARACTER_VOICE: Capability.VOICE_DESIGN.value,
    ReferenceGenerationKind.NARRATOR_VOICE: Capability.VOICE_DESIGN.value,
    ReferenceGenerationKind.FINAL_VIDEO: "final_assembly",
    ReferenceGenerationKind.SCENE_FINAL_VIDEO: "final_assembly",
    ReferenceGenerationKind.VIDEO_AUDIO_VOICE: Capability.AUDIO_SEPARATE.value,
    ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND: Capability.AUDIO_SEPARATE.value,
}


def _generation_ports(generation: ReferenceGeneration) -> tuple[str, ...]:
    """历史 Generation 可能由哪些端口或语义能力的实现签发句柄。"""
    kind = generation.kind
    if kind is ReferenceGenerationKind.SEGMENT_VIDEO:
        return (Capability.VIDEO_GENERATE.value,)
    if kind in {
        ReferenceGenerationKind.GENERATED_AUDIO,
        ReferenceGenerationKind.DIALOGUE_AUDIO,
    }:
        return (
            (Capability.VOICE_DESIGN.value,)
            if generation.operation is GenerationOperation.VOICE_DESIGN
            else (Capability.SPEECH_SYNTHESIZE.value,)
        )
    if kind in {
        ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
        ReferenceGenerationKind.KEYFRAME_IMAGE,
        ReferenceGenerationKind.LOCATION_MASTER_IMAGE,
        ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
    }:
        return (
            Capability.IMAGE_EDIT.value
            if generation.operation is GenerationOperation.EDIT
            else Capability.IMAGE_GENERATE.value,
        )
    return (_KIND_CAPABILITY[kind],)


class StructuredDirectorService:
    def __init__(
        self,
        store: StructuredDirectorStore,
        registry: ProviderRegistry | None = None,
    ) -> None:
        if registry is None:
            registry = ProviderRegistry()
        elif not isinstance(registry, ProviderRegistry):
            raise TypeError("registry 必须是 ProviderRegistry。")
        self._store = store
        self._registry = registry
        store.attach_provider_catalog(registry)
        self._command_registry = DirectorCommandRegistry(store)
        self._final_assembly_provider = registry.resolve("final_assembly")
        self._animatic_provider = registry.resolve("animatic")
        self._video_frame_provider = registry.resolve("video_frame")
        self._pano_view_provider = registry.resolve("pano_view")
        self._audio_remix_provider = registry.resolve("audio_remix")
        self._lock = asyncio.Lock()
        self._application_lock = asyncio.Lock()
        self._generation_observer = GenerationObserver(store, self._lock, self._provider_for)
        self._media = MediaSubmissionUseCases(
            _store=self._store,
            _lock=self._lock,
            _registry=self._registry,
            _final_assembly_provider=self._final_assembly_provider,
            _animatic_provider=self._animatic_provider,
            _video_frame_provider=self._video_frame_provider,
            _pano_view_provider=self._pano_view_provider,
        )
        if self._store.exists():
            self._store.recover_interrupted_submissions()

    async def execute_director_command(self, command: DirectorCommand) -> CommandExecution:
        caller = current_caller.get()
        if command.name in READ_OPERATIONS and caller is not None:
            authorize_command(caller, self._store.read().project_id, asdict(command))
        if caller is not None and not (
            (command.name.startswith("project.") and command.name != "project.apply_repair_patch")
            or command.name
            in {"run.get_status", *(f"{kind}.get_proposal" for kind in PROPOSAL_KINDS)}
        ):
            return await execute_application_command(self, caller, command)
        return await self._execute_internal_director_command(command)

    async def _execute_internal_director_command(
        self, command: DirectorCommand
    ) -> CommandExecution:
        """执行稳定 Core command；Generation 生命周期命令可观察 Provider。"""
        if command.name in {
            "keyframe.generate_batch",
            "keyframe.continue_batch",
            "location.generate_set",
        }:
            return await _execute_external_batch(self, command)
        if command.name.startswith("generation."):
            return await self.execute_generation_command(command)
        if command.name in {
            "animatic.generate_scene",
            "final.assemble_scene",
            "final.assemble",
        }:
            return await self.execute_media_command(command)
        async with self._lock:
            return self._command_registry.execute(command)

    async def execute_media_command(self, command: DirectorCommand) -> CommandExecution:
        """执行明确授权且会创建 Generation 的装配命令。"""
        before = self._store.read()
        if before.revision != command.expected_revision:
            raise RevisionConflictError("项目已更新，请刷新后重试装配操作。")
        if command.name == "animatic.generate_scene":
            target = _parse_application_arguments(parse_animatic_scene_target, command.arguments)
            updated = await self._media.generate_scene_animatic(
                scene_id=target.scene_id,
                expected_revision=command.expected_revision,
            )
            changed_ids = (target.scene_id, updated.generations[-1].id)
            summary = "已为指定 Scene 提交 Animatic Generation。"
        elif command.name == "final.assemble_scene":
            target = _parse_application_arguments(parse_final_scene_target, command.arguments)
            updated = await self.generate_scene_final_video(
                scene_id=target.scene_id,
                expected_revision=command.expected_revision,
                video_audio_volume=target.video_audio_volume,
                narration_audio_volume=target.narration_audio_volume,
            )
            changed_ids = (target.scene_id, updated.generations[-1].id)
            summary = "已用当前 Scene 的视频与旁白选择提交 Scene 成片 Generation。"
        elif command.name == "final.assemble":
            _parse_application_arguments(parse_empty_arguments, command.arguments, command.name)
            updated = await self.generate_final_video(expected_revision=command.expected_revision)
            changed_ids = (updated.generations[-1].id,)
            summary = "已用当前完整选择提交成片装配 Generation。"
        else:
            raise InvalidArgumentsError(f"尚未注册装配 command：{command.name}。")
        return CommandExecution(
            updated,
            CommandReceipt(
                command_id=director_command_id(command),
                status="succeeded",
                old_revision=before.revision,
                new_revision=updated.revision,
                changed_ids=changed_ids,
                preserved=("source_assets", "generation_history"),
                decision_summary=summary,
                next_allowed_actions=("generation.wait",),
            ),
        )

    async def execute_production_command(
        self,
        command: DirectorCommand,
        *,
        raw_user_request: str = "",
    ) -> StructuredDirectorDocument:
        """让参数完整的 UI 动作复用 Director 的生产 command handlers。"""
        document = self._store.read()
        if document.revision != command.expected_revision:
            raise RevisionConflictError("项目已更新，请刷新后重试。")
        outcome = await self._execute_production_command_handler(
            document,
            _ProductionCommandRequest(command, "", raw_user_request),
        )
        return outcome.document

    def location_master_candidate_valid(self, asset: Asset) -> bool:
        """只读快照复用不可变 Asset 的全景校验缓存；正式选择仍完整校验。"""
        return self._store.is_location_pano_source(asset)

    @property
    def pano_view_available(self) -> bool:
        return self._pano_view_provider is not None

    @property
    def image_generation_available(self) -> bool:
        return self._registry.capability_available(
            Capability.IMAGE_GENERATE
        ) and self._registry.capability_available(Capability.IMAGE_EDIT)

    @property
    def voice_design_available(self) -> bool:
        return self._registry.capability_available(Capability.VOICE_DESIGN)

    @property
    def speech_synthesis_available(self) -> bool:
        return self._registry.capability_available(Capability.SPEECH_SYNTHESIZE)

    @property
    def speech_recognition_available(self) -> bool:
        return self._registry.capability_available(Capability.SPEECH_RECOGNIZE)

    @property
    def video_generation_available(self) -> bool:
        return self._registry.capability_available(Capability.VIDEO_GENERATE)

    @property
    def video_upscale_available(self) -> bool:
        return self._registry.capability_available(Capability.VIDEO_UPSCALE)

    @property
    def final_assembly_available(self) -> bool:
        return self._registry.available("final_assembly")

    @property
    def scene_animatic_available(self) -> bool:
        return self._registry.available("animatic")

    @property
    def video_frame_available(self) -> bool:
        return self._registry.available("video_frame")

    async def generate_location_master(
        self, *, location_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        return await self._media.generate_location_master(
            location_id=location_id, expected_revision=expected_revision
        )

    async def generate_location_view(
        self, *, view_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        return await self._media.generate_location_view(
            view_id=view_id, expected_revision=expected_revision
        )

    def video_frame_info(self, asset_id: str) -> Mp4VideoFrames:
        """抽帧 UI 使用的帧号范围；只读 MP4 容器结构。"""
        asset, content = self._store.read_asset(asset_id)
        if asset.media_type != "video/mp4":
            raise ValueError("只有 MP4 视频可以抽帧。")
        return read_mp4_video_frames(content)

    @property
    def audio_separation_available(self) -> bool:
        return self._registry.capability_available(Capability.AUDIO_SEPARATE)

    @property
    def audio_remix_available(self) -> bool:
        return self._registry.available("audio_remix")

    @property
    def provider_catalog(self):
        return self._registry

    def provider_recipe_views(self) -> list[dict]:
        """当前生效的 recipe 声明：Web 据此渲染机制参数。"""
        return self._registry.recipe_views()

    def observed_generation(self, generation: ReferenceGeneration) -> ReferenceGeneration:
        return self._store.observed_generation(generation)

    def snapshot(self) -> StructuredDirectorDocument | None:
        if not self._store.exists():
            return None
        return self._store.read()

    def snapshot_required(self) -> StructuredDirectorDocument:
        snapshot = self.snapshot()
        if snapshot is None:
            raise FileNotFoundError("结构化导演台尚未建立。")
        return snapshot

    def read_asset(self, asset_id: str) -> tuple[Asset, bytes]:
        return self._store.read_asset(asset_id)

    async def transcribe_audio(self, asset_id: str, *, language: str = "auto"):
        prepared = self._registry.prepare_recipe(Capability.SPEECH_RECOGNIZE)
        asset, content = self._store.read_asset(asset_id)
        request, _mechanism = prepared.request(
            roles={Role.LANGUAGE: language},
            media={
                Role.SOURCE_AUDIO: (
                    MediaInput(asset.media_type, content, duration_seconds=asset.duration_seconds),
                )
            },
        )
        return await asyncio.to_thread(prepared.execute, request)

    async def save_script(
        self,
        proposal: StructuredDirectorScriptRevisionProposal | tuple[Scene, ...],
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.status is not StructuredDirectorStatus.REVIEWING_SCRIPT and not isinstance(
                proposal, tuple
            ):
                return self._store.save_production_script_revision_proposal(
                    proposal,
                    expected_revision=expected_revision,
                )
            if isinstance(proposal, tuple):
                return self._store.save_director_script(
                    proposal,
                    expected_revision=expected_revision,
                )
            return self._store.save_script_revision_proposal(
                proposal, expected_revision=expected_revision
            )

    async def confirm_script(self, *, expected_revision: int) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.confirm_director_script(expected_revision=expected_revision)

    async def save_narration_cue(
        self, *, scene_id: str, cue: NarrationCue, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._command_registry.execute(
                DirectorCommand(
                    "narration.update_cue",
                    expected_revision,
                    f"ui-narration-update:{expected_revision}:{cue.id}",
                    {
                        "scope": {"scene_ids": [scene_id]},
                        "cue_id": cue.id,
                        "fields": {
                            **{
                                language.value: {
                                    "text": track.text,
                                    "seed": track.seed,
                                    "recipe_params": track.recipe_params.to_json(),
                                }
                                for language, track in cue.tracks
                            },
                        },
                    },
                )
            ).document

    async def generate_narration(
        self,
        *,
        cue_id: str,
        language: NarrationLanguage | str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        language = NarrationLanguage(language)
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再生成旁白。")
            cue = _find_narration_cue(document, cue_id)
            return await self._submit_narration_generation(
                document, cue, language, retry_of=_retry_of
            )

    async def generate_narration_batch(
        self, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再批量生成旁白。")
            if document.director_script is None:
                raise ValueError("结构化导演脚本不存在。")
            current = document
            for scene in document.director_script.scenes:
                for cue in scene.narration_cues:
                    for language, track in cue.tracks:
                        if track.selected_audio_asset_id is not None:
                            continue
                        active = any(
                            generation.kind is ReferenceGenerationKind.NARRATION_AUDIO
                            and generation.target_id == cue.id
                            and generation.language is language
                            and generation.phase not in _TERMINAL_PHASES
                            for generation in current.generations
                        )
                        if not active:
                            current = await self._submit_narration_generation(
                                current, cue, language
                            )
            return current

    async def select_narration_audio(
        self, *, cue_id: str, generation_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.select_narration_audio(
                cue_id=cue_id,
                generation_id=generation_id,
                expected_revision=expected_revision,
            )

    async def generate_dialogue(
        self,
        *,
        dialogue_line_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再生成对白。")
            return await self._media._submit_dialogue_generation(
                document,
                dialogue_line_id,
                retry_of=_retry_of,
            )

    async def generate_dialogue_batch(
        self, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再批量生成对白。")
            if document.director_script is None or document.dialogue_plan is None:
                raise ValueError("对白 TTS 计划不存在。")
            selected = {
                item.dialogue_line_id: item.selected_audio_asset_id
                for item in document.dialogue_plan.items
            }
            current = document
            for scene in document.director_script.scenes:
                for segment in scene.segments:
                    for line in segment.dialogue_lines:
                        assert line.id is not None
                        if selected[line.id] is not None:
                            continue
                        active = any(
                            generation.kind is ReferenceGenerationKind.DIALOGUE_AUDIO
                            and generation.target_id == line.id
                            and generation.phase not in _TERMINAL_PHASES
                            for generation in current.generations
                        )
                        if not active:
                            current = await self._media._submit_dialogue_generation(
                                current, line.id
                            )
            return current

    async def select_dialogue_audio(
        self,
        *,
        dialogue_line_id: str,
        generation_id: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.select_dialogue_audio(
                dialogue_line_id=dialogue_line_id,
                generation_id=generation_id,
                expected_revision=expected_revision,
            )

    async def set_dialogue_timing(
        self,
        *,
        segment_id: str,
        starts: dict[str, float],
        duration_seconds: float,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.set_dialogue_timing(
                segment_id=segment_id,
                starts=starts,
                duration_seconds=duration_seconds,
                expected_revision=expected_revision,
            )

    async def unlock_visual_production(
        self, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            script = document.director_script
            if script is None:
                raise ValueError("导演脚本尚未建立。")
            segments = tuple(
                SegmentVideo(
                    segment.id,
                    "",
                )
                for scene in script.scenes
                for segment in scene_segments(scene)
            )
            return self._store.unlock_visual_production(
                segments, expected_revision=expected_revision
            )

    async def save_keyframe(
        self,
        keyframe: Keyframe,
        *,
        expected_revision: int,
        segment_id: str | None = None,
        reference_asset_ids: tuple[str, ...] | None = None,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._command_registry.execute(
                keyframe_edit_command(
                    self._store.read(),
                    keyframe,
                    expected_revision=expected_revision,
                    segment_id=segment_id,
                    reference_asset_ids=reference_asset_ids,
                )
            ).document

    async def preview_keyframe(
        self,
        *,
        keyframe_id: str,
        segment_id: str,
        prompt_text: str,
        visible_character_ids: tuple[str, ...],
        character_references: tuple[KeyframeCharacterReference, ...],
        reference_asset_ids: tuple[str, ...],
        environment_mode: KeyframeEnvironmentMode,
        environment_view_id: str | None,
        environment_none_reason: str | None,
        expected_revision: int,
    ) -> KeyframeSubmissionPreview:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已更新，请刷新后重新读取关键帧预览。")
            preview_document = _keyframe_preview_document(
                document,
                keyframe_id=keyframe_id,
                segment_id=segment_id,
                prompt_text=prompt_text,
                visible_character_ids=visible_character_ids,
                character_references=character_references,
                reference_asset_ids=reference_asset_ids,
                environment_mode=environment_mode,
                environment_view_id=environment_view_id,
                environment_none_reason=environment_none_reason,
            )
            inputs = _keyframe_generation_inputs(preview_document, keyframe_id)
            if inputs is None:
                return KeyframeSubmissionPreview(
                    "图片引用：\n前一时间边界 Keyframe 尚未就绪。",
                    None,
                    False,
                    GenerationOperation.EDIT,
                    (),
                )
            keyframe = _find_keyframe(preview_document, keyframe_id)
            assets = tuple(
                next(asset for asset in preview_document.assets if asset.id == asset_id)
                for asset_id in inputs.asset_ids
            )
            style = image_prompt_style(self._registry, inputs.operation)
            return KeyframeSubmissionPreview(
                _keyframe_reference_prompt(inputs, style),
                _keyframe_effective_prompt(preview_document, keyframe, inputs, style),
                True,
                inputs.operation,
                assets,
                inputs.roles,
                tuple(description for _name, description in inputs.mapping),
            )

    async def save_segment_keyframe_references(
        self,
        *,
        segment_id: str,
        asset_ids: tuple[str, ...],
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._command_registry.execute(
                keyframe_references_command(
                    segment_id=segment_id,
                    asset_ids=asset_ids,
                    expected_revision=expected_revision,
                )
            ).document

    async def save_segment_keyframe_activation(
        self,
        *,
        segment_id: str,
        start_enabled: bool,
        end_enabled: bool,
        expected_revision: int,
        expected_binding: tuple[str, str, bool, bool, str | None, str | None] | None = None,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision and expected_binding is not None:
                plan = document.keyframe_plan
                binding = (
                    None
                    if plan is None
                    else next(
                        (item for item in plan.segments if item.segment_id == segment_id),
                        None,
                    )
                )
                if binding is None or plan is None:
                    raise RevisionConflictError(
                        "项目已更新且 Segment 关键帧绑定已变化，请刷新后重试。"
                    )
                keyframes = {item.id: item for item in plan.keyframes}
                start = keyframes.get(binding.start_keyframe_id)
                end = keyframes.get(binding.end_keyframe_id)
                if start is None or end is None:
                    raise RevisionConflictError(
                        "项目已更新且 Segment 关键帧绑定已变化，请刷新后重试。"
                    )
                current_binding = (
                    binding.start_keyframe_id,
                    binding.end_keyframe_id,
                    binding.start_enabled,
                    binding.end_enabled,
                    start.selected_asset_id,
                    end.selected_asset_id,
                )
                same_target_facts = (
                    current_binding[:2] == expected_binding[:2]
                    and current_binding[4:] == expected_binding[4:]
                )
                if same_target_facts and current_binding[2:4] == (
                    start_enabled,
                    end_enabled,
                ):
                    return document
                if current_binding != expected_binding:
                    raise RevisionConflictError(
                        "项目已更新且该 Segment 的关键帧状态已变化，请刷新后确认。"
                    )
                expected_revision = document.revision
            return self._command_registry.execute(
                keyframe_activation_command(
                    segment_id=segment_id,
                    start_enabled=start_enabled,
                    end_enabled=end_enabled,
                    expected_revision=expected_revision,
                )
            ).document

    async def save_segment_boundary_sharing(
        self, *, segment_id: str, shared: bool, expected_revision: int
    ) -> StructuredDirectorDocument:
        """首帧卡的“与上一段尾帧共享”开关；共享时保留上一段尾帧，拆开时复制为独立首帧。"""
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已更新，请刷新后重试。")
            script = document.director_script
            if script is None or document.keyframe_plan is None:
                raise ValueError("关键帧计划尚未建立。")
            ordered = [segment.id for scene in script.scenes for segment in scene_segments(scene)]
            if segment_id not in ordered or ordered.index(segment_id) == 0:
                raise ValueError("第一个 Segment 没有可共享的上一段尾帧。")
            previous_id = ordered[ordered.index(segment_id) - 1]
            bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
            operation: dict[str, object] = (
                {
                    "op": "share_boundary",
                    "left_segment_id": previous_id,
                    "right_segment_id": segment_id,
                    "source_keyframe_id": bindings[previous_id].end_keyframe_id,
                }
                if shared
                else {
                    "op": "split_boundary",
                    "left_segment_id": previous_id,
                    "right_segment_id": segment_id,
                    "clone_side": "right_start",
                    "copy_selection": True,
                }
            )
            return self._command_registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    expected_revision,
                    f"ui-keyframe-boundary:{expected_revision}:{segment_id}:{int(shared)}",
                    {"operations": [operation]},
                )
            ).document

    async def select_keyframe(
        self, *, keyframe_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.select_keyframe_asset(
                keyframe_id=keyframe_id,
                asset_id=asset_id,
                expected_revision=expected_revision,
            )

    async def generate_keyframe_batch(
        self, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再批量生成。")
            return await self._submit_ready_keyframe_generations(document, report_blocked=True)

    async def generate_keyframe(
        self,
        *,
        keyframe_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再生成。")
            _find_keyframe(document, keyframe_id)
            if keyframe_id not in _active_keyframe_ids(document.keyframe_plan):
                raise ValueError("该 Keyframe 未激活，不能生成。")
            if any(
                item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                and item.target_id == keyframe_id
                and item.phase not in _TERMINAL_PHASES
                for item in document.generations
            ):
                raise ValueError("该 Keyframe 已有进行中的图片任务。")
            inputs = _keyframe_generation_inputs(document, keyframe_id)
            if inputs is None:
                raise ValueError("前置 Keyframe 候选尚未完成，当前不能生成。")
            return await self._submit_keyframe_generation(
                document, keyframe_id, inputs, retry_of=_retry_of
            )

    async def add_character(
        self, proposal: CharacterCardProposal, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.save_character(
                CharacterCard(
                    id=uuid4().hex,
                    name=proposal.name.strip(),
                    visual_description=None
                    if proposal.visual_description is None
                    else proposal.visual_description.strip(),
                    voice_description=proposal.voice_description.strip(),
                ),
                expected_revision=expected_revision,
                must_exist=False,
            )

    async def update_character(
        self,
        card: CharacterCard,
        *,
        expected_revision: int,
        created_look_ids: frozenset[str] = frozenset(),
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.save_character(
                card,
                expected_revision=expected_revision,
                must_exist=True,
                created_look_ids=created_look_ids,
            )

    async def update_narrator(
        self, profile: NarratorProfile, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.save_narrator(profile, expected_revision=expected_revision)

    async def discard_card(
        self, card_id: str, *, kind: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.discard_card(card_id, kind=kind, expected_revision=expected_revision)

    async def import_image_asset(
        self,
        *,
        media_type: str,
        content: bytes,
        category: ImageAssetCategory,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.import_image_asset(
                media_type=media_type,
                content=content,
                category=category,
                filename=filename,
                expected_revision=expected_revision,
            )

    async def import_media_asset(
        self,
        *,
        media_type: str,
        content: bytes,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.import_media_asset(
                media_type=media_type,
                content=content,
                filename=filename,
                expected_revision=expected_revision,
            )

    async def delete_asset(
        self, asset_id: str, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.delete_asset(asset_id, expected_revision=expected_revision)

    async def delete_assets(
        self, asset_ids: tuple[str, ...], *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.delete_assets(asset_ids, expected_revision=expected_revision)

    async def apply_audio_effect(
        self,
        *,
        source_asset_id: str,
        request: AudioEffectRequest,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        before = self._store.read()
        if before.revision != expected_revision:
            raise RevisionConflictError("项目已被更新，请重新读取后再处理音频。")
        source, content = self._store.read_asset(source_asset_id)
        if source.media_type != "audio/wav":
            raise ValueError("音频后处理源必须是项目内 WAV Asset。")
        result = await asyncio.to_thread(render_audio_effect, content, request)
        record = audio_effect_record(request, result)
        async with self._lock:
            return self._store.create_audio_effect_copy(
                source_asset_id=source_asset_id,
                output_content=result.audio,
                effect_record=record,
                preset=request.preset,
                seed=request.seed,
                processor_version=AUDIO_EFFECT_PROCESSOR_VERSION,
                expected_revision=expected_revision,
            )

    async def trim_audio(
        self,
        *,
        source_asset_id: str,
        request: AudioTrimRequest,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        before = self._store.read()
        if before.revision != expected_revision:
            raise RevisionConflictError("项目已被更新，请重新读取后再截取音频。")
        source, content = self._store.read_asset(source_asset_id)
        if source.media_type != "audio/wav":
            raise ValueError("音频截取源必须是项目内 WAV Asset。")
        result = await asyncio.to_thread(render_audio_trim, content, request)
        record = audio_trim_record(request, result)
        async with self._lock:
            return self._store.create_audio_trim_copy(
                source_asset_id=source_asset_id,
                output_content=result.audio,
                trim_record=record,
                start_seconds=result.metadata.start_seconds,
                end_seconds=result.metadata.end_seconds,
                output_duration_seconds=result.metadata.output_duration_seconds,
                processor_version=AUDIO_TRIM_PROCESSOR_VERSION,
                expected_revision=expected_revision,
            )

    async def separate_video_audio(
        self,
        *,
        source_asset_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        prepared = self._registry.prepare_recipe(Capability.AUDIO_SEPARATE)
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再分离音轨。")
            source, content = self._store.read_asset(source_asset_id)
            if source.media_type != "video/mp4":
                raise ValueError("音轨分离源必须是项目内 MP4 Asset。")
            if _retry_of is None and any(
                item.target_id == source_asset_id
                and item.kind
                in {
                    ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
                    ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
                }
                and item.phase not in _TERMINAL_PHASES
                for item in document.generations
            ):
                raise ValueError("该视频已有进行中的音轨分离任务。")
            retry_payload = None
            if _retry_of is not None:
                try:
                    retry_payload = json.loads(_retry_of.prompt_text)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("原音轨分离参数已经失效，不能直接 retry。") from exc
                if retry_payload.get("stem") not in {"voice", "background"}:
                    raise ValueError("原音轨分离参数已经失效，不能直接 retry。")
            batch_id = (
                str(retry_payload["batch_id"])
                if retry_payload is not None and retry_payload.get("batch_id")
                else uuid4().hex
            )
            stems = (
                (
                    (
                        str(retry_payload["stem"]),
                        "人声" if retry_payload["stem"] == "voice" else "背景声",
                    ),
                )
                if retry_payload is not None
                else (("voice", "人声"), ("background", "背景声"))
            )
            requests = tuple(
                prepared.request(
                    roles={Role.AUDIO_STEM: stem},
                    media={
                        Role.SOURCE_VIDEO: (
                            MediaInput(
                                source.media_type, content, duration_seconds=source.duration_seconds
                            ),
                        )
                    },
                )[0]
                for stem, _label in stems
            )
            generations = tuple(
                ReferenceGeneration(
                    id=uuid4().hex,
                    kind=(
                        ReferenceGenerationKind.VIDEO_AUDIO_VOICE
                        if stem == "voice"
                        else ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND
                    ),
                    operation=GenerationOperation.SEPARATE,
                    target_id=source_asset_id,
                    phase=ReferenceGenerationPhase.SUBMITTING,
                    progress=0.0,
                    message=f"正在提交{label}分离任务。",
                    prompt_text=json.dumps(
                        {
                            "schema": "storyrail_audio_separation_v1",
                            "batch_id": batch_id,
                            "stem": stem,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    input_asset_ids=(source_asset_id,),
                    sample_text=None,
                    seed=None,
                    plugin_id=None,
                    plugin_version=None,
                    external_id=None,
                    output_asset_id=None,
                    error_code=None,
                    cancellation_requested=False,
                    retry_of=None if _retry_of is None else _retry_of.id,
                    duration_seconds=source.duration_seconds,
                    provider_snapshot=prepared.snapshot,
                )
                for stem, label in stems
            )
            if _retry_of is None:
                self._store.create_generations(generations, expected_revision=expected_revision)
            else:
                self._store.create_generation(generations[0], expected_revision=expected_revision)
            for generation, recipe_request in zip(generations, requests, strict=True):
                try:
                    handle = await asyncio.to_thread(
                        prepared.submit,
                        recipe_request,
                    )
                except Exception as exc:
                    self._store.update_generation(
                        _submission_failure(generation, exc, capability="人声分离")
                    )
                    continue
                self._store.update_generation(
                    transition_generation(
                        generation,
                        ReferenceGenerationPhase.QUEUED,
                        message="音轨分离任务已提交。",
                        plugin_id=handle.plugin_id,
                        plugin_version=handle.plugin_version,
                        external_id=handle.external_id,
                    )
                )
            return self._store.read()

    async def remix_video_audio(
        self,
        *,
        source_asset_id: str,
        voice_asset_id: str,
        background_asset_id: str,
        voice_gain_db: float,
        background_gain_db: float,
        expected_revision: int,
        voice_gain_start_seconds: float | None = None,
        voice_gain_end_seconds: float | None = None,
        background_gain_start_seconds: float | None = None,
        background_gain_end_seconds: float | None = None,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        provider = self._audio_remix_provider
        if provider is None:
            raise RuntimeError("视频音轨混音服务尚未配置。")
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再混合音轨。")
            source, video = self._store.read_asset(source_asset_id)
            voice_asset, voice = self._store.read_asset(voice_asset_id)
            background_asset, background = self._store.read_asset(background_asset_id)
            request = AudioRemixRequest(
                video,
                voice,
                background,
                voice_gain_db,
                background_gain_db,
                voice_gain_start_seconds,
                voice_gain_end_seconds,
                background_gain_start_seconds,
                background_gain_end_seconds,
            )
            if source.media_type != "video/mp4" or any(
                item.media_type != "audio/wav" for item in (voice_asset, background_asset)
            ):
                raise ValueError("视频音轨混音输入类型不合法。")
            _validate_remix_range(
                voice_gain_start_seconds,
                voice_gain_end_seconds,
                voice_asset.duration_seconds,
                "人声音量",
            )
            _validate_remix_range(
                background_gain_start_seconds,
                background_gain_end_seconds,
                background_asset.duration_seconds,
                "背景声音量",
            )
            generation = ReferenceGeneration(
                id=uuid4().hex,
                kind=ReferenceGenerationKind.VIDEO_AUDIO_REMIX,
                operation=GenerationOperation.REMIX,
                target_id=source_asset_id,
                phase=ReferenceGenerationPhase.SUBMITTING,
                progress=0.0,
                message="正在提交视频音轨混音任务。",
                prompt_text=json.dumps(
                    {
                        "schema": "storyrail_audio_remix_v2",
                        "voice_gain_db": voice_gain_db,
                        "background_gain_db": background_gain_db,
                        "voice_gain_start_seconds": voice_gain_start_seconds,
                        "voice_gain_end_seconds": voice_gain_end_seconds,
                        "background_gain_start_seconds": background_gain_start_seconds,
                        "background_gain_end_seconds": background_gain_end_seconds,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                input_asset_ids=(source_asset_id, voice_asset_id, background_asset_id),
                sample_text=None,
                seed=None,
                plugin_id=None,
                plugin_version=None,
                external_id=None,
                output_asset_id=None,
                error_code=None,
                cancellation_requested=False,
                retry_of=None if _retry_of is None else _retry_of.id,
                duration_seconds=source.duration_seconds,
            )
            self._store.create_generation(generation, expected_revision=expected_revision)
            try:
                handle = await asyncio.to_thread(provider.submit, request)
            except Exception as exc:
                return self._store.update_generation(
                    _submission_failure(generation, exc, capability="视频音轨混音")
                )
            return self._store.update_generation(
                transition_generation(
                    generation,
                    ReferenceGenerationPhase.QUEUED,
                    message="视频音轨混音任务已提交。",
                    plugin_id=handle.plugin_id,
                    plugin_version=handle.plugin_version,
                    external_id=handle.external_id,
                )
            )

    async def select_look_asset(
        self, *, card_id: str, look_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        """人类把资产库已有图片设为造型图；Agent 没有此入口。"""
        async with self._lock:
            return self._store.select_look_asset(
                card_id=card_id,
                look_id=look_id,
                asset_id=asset_id,
                expected_revision=expected_revision,
            )

    async def upload_reference_voice(
        self,
        *,
        card_id: str,
        media_type: str,
        content: bytes,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.attach_uploaded_voice(
                card_id=card_id,
                media_type=media_type,
                content=content,
                filename=filename,
                expected_revision=expected_revision,
            )

    async def upload_narrator_voice(
        self,
        *,
        narrator_id: str,
        language: NarrationLanguage,
        media_type: str,
        content: bytes,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.attach_uploaded_narrator_voice(
                narrator_id=narrator_id,
                language=language,
                media_type=media_type,
                content=content,
                filename=filename,
                expected_revision=expected_revision,
            )

    async def attach_generation_output(
        self,
        *,
        kind: str,
        card_id: str,
        generation_id: str,
        note: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.attach_generation_output(
                kind=kind,
                card_id=card_id,
                generation_id=generation_id,
                note=note,
                expected_revision=expected_revision,
            )

    async def select_look_sheet(
        self,
        *,
        card_id: str,
        look_id: str,
        generation_id: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        """人类为造型选定设定图；Agent 没有此入口。"""
        async with self._lock:
            return self._store.select_look_sheet(
                card_id=card_id,
                look_id=look_id,
                generation_id=generation_id,
                expected_revision=expected_revision,
            )

    async def generate_look_sheet(
        self,
        *,
        look_id: str,
        identity_asset_ids: tuple[str, ...],
        expected_revision: int,
        prompt_text: str | None = None,
    ) -> StructuredDirectorDocument:
        """造型设定图生成；比例由 Core 固定。

        Agent 只用 Core 编译的提示词；人类可提交编辑过的完整提示词（prompt_text）。
        """
        return await self._media.generate_look_sheet(
            look_id=look_id,
            identity_asset_ids=identity_asset_ids,
            expected_revision=expected_revision,
            prompt_text=prompt_text,
        )

    def preview_look_sheet(self, *, look_id: str, identity_asset_ids: tuple[str, ...]) -> str:
        """按当前造型、身份参考与图片插件约定编译完整提示词，供人类查看和编辑；不写入。"""
        document = self._store.read()
        plan = look_sheet_plan(document, look_id, identity_asset_ids)
        return look_sheet_prompt(
            plan, image_prompt_style(self._registry, GenerationOperation.GENERATE)
        )

    async def dismiss_generation(
        self, generation_id: str, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._command_registry.execute(
                DirectorCommand(
                    "generation.dismiss",
                    expected_revision,
                    f"ui-generation-dismiss:{expected_revision}:{generation_id}",
                    {"generation_id": generation_id},
                )
            ).document

    async def execute_generation_command(
        self,
        command: DirectorCommand,
    ) -> CommandExecution:
        """执行可能观察或调用 Provider 的跨媒体 Generation command。"""
        before = self._store.read()
        if command.name != "generation.wait" and before.revision != command.expected_revision:
            raise RevisionConflictError("项目已更新，请刷新后重试 Generation 操作。")
        if command.name == "generation.dismiss":
            async with self._lock:
                return self._command_registry.execute(command)
        if command.name == "generation.wait":
            request = _parse_application_arguments(parse_generation_wait, command.arguments)
            for generation_id in request.generation_ids:
                _find_generation(self._store.read(), generation_id)
            # 默认 18s 在 bridge 20s HTTP timeout 前返回；gateway 30s 覆盖整个往返。
            max_wait = max(
                0.0,
                float(os.environ.get("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", "18")),
            )
            poll_seconds = max(
                0.01,
                float(os.environ.get("STORYRAIL_GENERATION_WAIT_POLL_SECONDS", "2")),
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + max_wait
            while True:
                for generation_id in request.generation_ids:
                    await self._generation_observer.refresh_generation(generation_id)
                updated = self._store.read()
                observed = [
                    _find_generation(updated, generation_id)
                    for generation_id in request.generation_ids
                ]
                wait_again = any(
                    generation.phase not in _TERMINAL_PHASES for generation in observed
                )
                if not wait_again or loop.time() >= deadline:
                    break
                await asyncio.sleep(min(poll_seconds, max(0.0, deadline - loop.time())))
            return CommandExecution(
                updated,
                CommandReceipt(
                    command_id=director_command_id(command),
                    status="noop" if updated.revision == before.revision else "succeeded",
                    old_revision=before.revision,
                    new_revision=updated.revision,
                    changed_ids=request.generation_ids,
                    preserved=("generation_history",),
                    decision_summary=(
                        "已等待并读取指定 Generation 的最新 Provider 状态。"
                        if wait_again
                        else "指定 Generation 已进入终态。"
                    ),
                    next_allowed_actions=("generation.wait",),
                ),
                data={
                    "generations": [
                        _generation_wait_data(self.observed_generation(generation))
                        for generation in observed
                    ],
                    "wait_again": wait_again,
                },
            )
        target = _parse_application_arguments(
            parse_generation_target, command.arguments, command.name
        )
        if command.name == "generation.cancel":
            updated = await self._generation_observer.cancel_generation(
                target.generation_id,
                expected_revision=command.expected_revision,
            )
            summary = "已请求取消指定 Generation，并保存最新 Provider 状态。"
            changed_ids = (target.generation_id,)
        elif command.name == "generation.retry":
            updated = await self.retry_generation(
                target.generation_id,
                expected_revision=command.expected_revision,
            )
            if updated.revision == before.revision:
                summary = "该 Generation 已经创建过 retry，本次未重复提交 Provider。"
                changed_ids = ()
            else:
                summary = "已按原始规范化请求创建新的 retry Generation。"
                changed_ids = (target.generation_id, updated.generations[-1].id)
        else:
            raise InvalidArgumentsError(f"尚未注册 Generation command：{command.name}。")
        return CommandExecution(
            updated,
            CommandReceipt(
                command_id=director_command_id(command),
                status="noop" if updated.revision == before.revision else "succeeded",
                old_revision=before.revision,
                new_revision=updated.revision,
                changed_ids=changed_ids,
                preserved=("generation_history",),
                decision_summary=summary,
                next_allowed_actions=("generation.wait",),
            ),
        )

    def preview_segment_video_inputs(self, segment_id, inputs, expected_revision):
        document = self._store.read()
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已被更新，请重新读取视频输入。")
        video = next(
            (item for item in document.video_plan.segments if item.segment_id == segment_id), None
        )
        if video is None or video.active_recipe is None:
            raise ValueError("请先选择视频 recipe。")
        draft = replace(video, recipes=video.recipes.with_entry(video.active_recipe, inputs))
        return video_recipe_state(document, draft, self._registry, self.provider_recipe_views())

    async def save_segment_video_inputs(
        self,
        *,
        segment_id: str,
        prompt_text: str,
        bindings: dict,
        params: dict,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再保存视频输入。")
            if document.director_script is None:
                raise ValueError("结构化脚本尚未建立。")
            found = find_segment(document.director_script.scenes, segment_id)
            if found is None:
                raise ValueError("Segment 不存在。")
            scene, _segment = found
            return self._command_registry.execute(
                DirectorCommand(
                    "video.update_recipe_inputs",
                    expected_revision,
                    f"ui-video-inputs:{expected_revision}:{segment_id}",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment_id,
                        "prompt_text": prompt_text,
                        "bindings": bindings,
                        "params": params,
                    },
                )
            ).document

    async def save_segment_video_recipe(
        self, *, segment_id: str, recipe_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再保存视频 recipe。")
            if document.director_script is None:
                raise ValueError("结构化脚本尚未建立。")
            found = find_segment(document.director_script.scenes, segment_id)
            if found is None:
                raise ValueError("Segment 不存在。")
            scene, _segment = found
            return self._command_registry.execute(
                DirectorCommand(
                    "video.set_recipe",
                    expected_revision,
                    f"ui-video-recipe:{expected_revision}:{segment_id}",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment_id,
                        "recipe_id": recipe_id,
                    },
                )
            ).document

    async def select_segment_video(
        self, *, segment_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.select_segment_video(
                segment_id=segment_id,
                asset_id=asset_id,
                expected_revision=expected_revision,
            )

    async def attach_segment_video_candidate(
        self, *, segment_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._store.attach_segment_video_candidate(
                segment_id=segment_id,
                asset_id=asset_id,
                expected_revision=expected_revision,
            )

    async def clear_segment_video_selection(
        self, *, segment_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再清除视频选择。")
            found = find_segment(
                document.director_script.scenes if document.director_script else (), segment_id
            )
            if found is None:
                raise ValueError("Segment 不存在。")
            scene, _segment = found
            return self._command_registry.execute(
                DirectorCommand(
                    "video.clear_selection",
                    expected_revision,
                    f"ui-video-clear:{expected_revision}:{segment_id}",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment_id,
                    },
                )
            ).document

    async def enter_final_stage(self, *, expected_revision: int) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再进入成片装配。")
            if not document.is_reviewing or not document.workspace_layers.videos_unlocked:
                raise ValueError("当前视频生产输入不完整。")
            return self._store.enter_final_stage(
                _build_final_assembly_plan(document),
                expected_revision=expected_revision,
            )

    async def generate_final_video(
        self,
        *,
        expected_revision: int,
        language: NarrationLanguage | None = None,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        """装配项目所选语言的单语成片；只指定 language 时（如 retry）只装配该语言。"""
        provider = self._final_assembly_provider
        if provider is None:
            raise RuntimeError("FFmpeg 成片装配服务尚未配置。")
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再装配成片。")
            if document.is_reviewing and document.workspace_layers.videos_unlocked:
                document = self._store.enter_final_stage(
                    _build_final_assembly_plan(document),
                    expected_revision=document.revision,
                )
            if document.status is not StructuredDirectorStatus.REVIEWING_FINAL:
                raise ValueError("当前不在成片装配阶段。")
            plan = document.final_assembly
            if plan is None:
                raise ValueError("成片装配计划不存在。")
            if language is not None and language not in document.narration_languages:
                raise ValueError("项目未启用该旁白语言。")
            languages = document.narration_languages if language is None else (language,)
            if any(
                item.kind is ReferenceGenerationKind.FINAL_VIDEO
                and item.language in languages
                and item.phase not in _TERMINAL_PHASES
                for item in document.generations
            ):
                raise ValueError("已有进行中的成片装配任务。")
            for current_language in languages:
                document = await self._media._submit_final_assembly(
                    document,
                    plan,
                    language=current_language,
                    retry_of=_retry_of,
                )
            return document

    async def generate_scene_final_video(
        self,
        *,
        scene_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
        video_audio_volume: float = 1.0,
        narration_audio_volume: float = 1.0,
        language: NarrationLanguage | None = None,
    ) -> StructuredDirectorDocument:
        """渲染该 Scene 的所选语言成片；只指定 language 时（如 retry）只渲染该语言。"""
        if self._final_assembly_provider is None:
            raise RuntimeError("FFmpeg 成片装配服务尚未配置。")
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再装配 Scene 成片。")
            if not document.is_reviewing or not document.workspace_layers.videos_unlocked:
                raise ValueError("当前不能装配 Scene 成片。")
            if language is not None and language not in document.narration_languages:
                raise ValueError("项目未启用该旁白语言。")
            languages = document.narration_languages if language is None else (language,)
            plans = [_build_scene_final_plan(document, scene_id, item) for item in languages]
            if any(
                item.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
                and item.target_id == scene_id
                and item.language in languages
                and item.phase not in _TERMINAL_PHASES
                for item in document.generations
            ):
                raise ValueError("该 Scene 已有进行中的成片装配任务。")
            for plan in plans:
                document = await self._media._submit_scene_final_assembly(
                    document,
                    plan,
                    scene_id=scene_id,
                    retry_of=_retry_of,
                    video_audio_volume=video_audio_volume,
                    narration_audio_volume=narration_audio_volume,
                )
            return document

    def scene_animatic_ready(self, scene_id: str) -> bool:
        document = self._store.read()
        try:
            _build_scene_animatic_spec(document, scene_id)
        except ValueError:
            return False
        return True

    async def select_final_video(
        self,
        *,
        asset_id: str | None = None,
        generation_id: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            if (asset_id is None) == (generation_id is None):
                raise ValueError("选择成片必须且只能指定 Generation ID 或旧 Asset ID。")
            if generation_id is None:
                document = self._store.read()
                if document.revision != expected_revision:
                    raise RevisionConflictError("项目已被更新，请重新读取后再选择成片。")
                generation = next(
                    (
                        item
                        for item in document.generations
                        if item.kind is ReferenceGenerationKind.FINAL_VIDEO
                        and item.phase is ReferenceGenerationPhase.SUCCEEDED
                        and item.output_asset_id == asset_id
                        and not item.dismissed
                    ),
                    None,
                )
                if generation is None:
                    raise ValueError("只能选择成功的成片候选。")
                generation_id = generation.id
            return self._command_registry.execute(
                DirectorCommand(
                    "final.select_candidate",
                    expected_revision,
                    f"ui-final-select:{expected_revision}:{generation_id}",
                    {"generation_id": generation_id},
                )
            ).document

    async def clear_final_selection(self, *, expected_revision: int) -> StructuredDirectorDocument:
        async with self._lock:
            return self._command_registry.execute(
                DirectorCommand(
                    "final.clear_selection",
                    expected_revision,
                    f"ui-final-clear:{expected_revision}",
                    {},
                )
            ).document

    async def approve_final_video(
        self,
        *,
        expected_revision: int,
        zh_asset_id: str | None = None,
        en_asset_id: str | None = None,
    ) -> StructuredDirectorDocument:
        """一次批准项目所选语言的单语成片；未指定时使用当前选择。"""
        async with self._lock:
            if zh_asset_id is None or en_asset_id is None:
                document = self._store.read()
                if document.revision != expected_revision:
                    raise RevisionConflictError("项目已被更新，请重新读取后再批准成片。")
                plan = document.final_assembly
                zh_asset_id = zh_asset_id or (None if plan is None else plan.selected_zh_asset_id)
                en_asset_id = en_asset_id or (None if plan is None else plan.selected_en_asset_id)
                selected = {NarrationLanguage.ZH: zh_asset_id, NarrationLanguage.EN: en_asset_id}
                if any(selected[item] is None for item in document.narration_languages):
                    raise ValueError("请先选择项目所选语言的全部成片候选，再执行批准。")
            return self._command_registry.execute(
                DirectorCommand(
                    "final.approve",
                    expected_revision,
                    f"ui-final-approve:{expected_revision}:{zh_asset_id}:{en_asset_id}",
                    {"zh_asset_id": zh_asset_id, "en_asset_id": en_asset_id},
                )
            ).document

    async def reopen_video_production(
        self, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        async with self._lock:
            return self._command_registry.execute(
                DirectorCommand(
                    "final.reopen_production",
                    expected_revision,
                    f"ui-final-reopen:{expected_revision}",
                    {},
                )
            ).document

    async def _execute_production_command_handler(
        self,
        document: StructuredDirectorDocument,
        request: _ProductionCommandRequest,
    ) -> _ProductionCommandOutcome:
        return await _production_command_handler_impl(self, document, request)

    async def retry_generation(
        self,
        generation_id: str,
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        """校验后按 kind 查表分派到 media use cases 重新提交。"""
        document = self._store.read()
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已更新，请刷新后重新提交 Generation。")
        generation = _find_generation(document, generation_id)
        if generation.dismissed:
            raise ValueError("已隐藏的 Generation 不能直接重试。")
        if generation.phase not in {
            ReferenceGenerationPhase.FAILED,
            ReferenceGenerationPhase.CANCELLED,
            ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        }:
            raise ValueError("只有失败、已取消或提交结果未知的 Generation 可以重试。")
        if any(item.retry_of == generation.id for item in document.generations):
            return document
        common = {"expected_revision": expected_revision, "_retry_of": generation}
        return await self._retry_dispatch(generation, document, common)

    async def _retry_generated_audio(
        self, generation: ReferenceGeneration, common: dict
    ) -> StructuredDirectorDocument:
        return await self._media.generate_asset_audio(
            text=(
                generation.prompt_text
                if generation.operation is GenerationOperation.SYNTHESIZE
                else (generation.sample_text or generation.prompt_text)
            ),
            seed=generation.seed or 0,
            voice_description=(
                generation.prompt_text
                if generation.operation is GenerationOperation.VOICE_DESIGN
                else None
            ),
            voice_asset_id=(
                generation.input_asset_ids[0]
                if generation.operation is GenerationOperation.SYNTHESIZE
                else None
            ),
            reference_transcript=(
                generation.sample_text
                if generation.operation is GenerationOperation.SYNTHESIZE
                else None
            ),
            recipe_params=generation.recipe_params,
            **common,
        )

    def _retry_remix_parameters(self, generation: ReferenceGeneration) -> dict:
        try:
            parameters = json.loads(generation.prompt_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("原视频音轨混音参数已经失效，不能直接 retry。") from exc
        if len(generation.input_asset_ids) != 3:
            raise ValueError("原视频音轨混音输入已经失效，不能直接 retry。")
        return {
            "source_asset_id": generation.input_asset_ids[0],
            "voice_asset_id": generation.input_asset_ids[1],
            "background_asset_id": generation.input_asset_ids[2],
            "voice_gain_db": parameters.get("voice_gain_db"),
            "background_gain_db": parameters.get("background_gain_db"),
            "voice_gain_start_seconds": parameters.get("voice_gain_start_seconds"),
            "voice_gain_end_seconds": parameters.get("voice_gain_end_seconds"),
            "background_gain_start_seconds": parameters.get("background_gain_start_seconds"),
            "background_gain_end_seconds": parameters.get("background_gain_end_seconds"),
        }

    async def _retry_dispatch(
        self,
        generation: ReferenceGeneration,
        document: StructuredDirectorDocument,
        common: dict,
    ) -> StructuredDirectorDocument:
        """retry 分派表：kind → 重新提交协程（为 P4 registry 准备的查表结构）。"""
        kind = generation.kind
        if kind is ReferenceGenerationKind.VIDEO_FRAME:
            request = generation.video_frame_request
            if request is None or request.frame_index is None:
                raise ValueError("历史尾帧抽取任务不能直接 retry，请重新选择帧号抽取。")
            asset = next(
                (item for item in document.assets if item.id == generation.target_id), None
            )
            if asset is not None and asset.media_type == "video/mp4":
                return await self._media.extract_asset_video_frame(
                    asset_id=asset.id, frame_index=request.frame_index, **common
                )
            return await self._media.extract_keyframe_video_frame(
                keyframe_id=generation.target_id,
                frame_index=request.frame_index,
                expected_source_video_asset_id=request.source_video_asset_id,
                **common,
            )
        if kind is ReferenceGenerationKind.FINAL_VIDEO:
            if document.final_assembly is None:
                raise ValueError("原成片装配输入已经失效，不能直接 retry。")
            return await self.generate_final_video(language=generation.language, **common)
        if kind is ReferenceGenerationKind.VIDEO_AUDIO_REMIX:
            return await self.remix_video_audio(
                **self._retry_remix_parameters(generation), **common
            )

        table = {
            # 重试按原请求：沿用当时提交的完整提示词与身份参考，不按当前造型重新编译。
            ReferenceGenerationKind.CHARACTER_LOOK_SHEET: lambda: self._media.generate_look_sheet(
                look_id=generation.target_id,
                identity_asset_ids=generation.input_asset_ids,
                prompt_text=generation.prompt_text,
                **common,
            ),
            ReferenceGenerationKind.CHARACTER_VOICE: lambda: self._media.design_voice(
                card_id=generation.target_id,
                voice_description=generation.prompt_text,
                sample_text=generation.sample_text or "",
                seed=generation.seed or 0,
                **common,
            ),
            ReferenceGenerationKind.NARRATOR_VOICE: lambda: self._media.design_voice(
                card_id=generation.target_id,
                voice_description=generation.prompt_text,
                sample_text=generation.sample_text or "",
                seed=generation.seed or 0,
                narrator_language=generation.language,
                **common,
            ),
            ReferenceGenerationKind.NARRATION_AUDIO: lambda: self.generate_narration(
                cue_id=generation.target_id, language=generation.language, **common
            ),
            ReferenceGenerationKind.DIALOGUE_AUDIO: lambda: self.generate_dialogue(
                dialogue_line_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.GENERATED_AUDIO: lambda: self._retry_generated_audio(
                generation, common
            ),
            ReferenceGenerationKind.KEYFRAME_IMAGE: lambda: self.generate_keyframe(
                keyframe_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.LOCATION_MASTER_IMAGE: lambda: (
                self._media.generate_location_master(location_id=generation.target_id, **common)
            ),
            # 裁切与细化/转向都经同一入口：入口按当前裁切是否有效决定提交哪一步。
            ReferenceGenerationKind.LOCATION_VIEW_CROP: lambda: self._media.generate_location_view(
                view_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.LOCATION_VIEW_IMAGE: lambda: self._media.generate_location_view(
                view_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.SEGMENT_VIDEO: lambda: self._media.generate_segment_video(
                segment_id=generation.target_id, seed=generation.seed, **common
            ),
            ReferenceGenerationKind.VIDEO_UPSCALE: lambda: self._media.upscale_segment_video(
                segment_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.SCENE_FINAL_VIDEO: lambda: self.generate_scene_final_video(
                scene_id=generation.target_id, language=generation.language, **common
            ),
            ReferenceGenerationKind.SCENE_ANIMATIC: lambda: self._media.generate_scene_animatic(
                scene_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.VIDEO_AUDIO_VOICE: lambda: self.separate_video_audio(
                source_asset_id=generation.target_id, **common
            ),
            ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND: lambda: self.separate_video_audio(
                source_asset_id=generation.target_id, **common
            ),
        }
        handler = table.get(kind)
        if handler is None:
            raise ValueError("该 Generation 类型尚不支持 retry。")
        return await handler()

    async def _apply_observation(
        self,
        provider: (
            RecipeProvider
            | FinalAssemblyProvider
            | AnimaticProvider
            | VideoFrameProvider
            | AudioRemixProvider
        ),
        handle: ProviderHandle,
        generation: ReferenceGeneration,
        observation: GenerationObservation,
    ) -> StructuredDirectorDocument:
        return await self._generation_observer._apply_observation(
            provider, handle, generation, observation
        )

    def _provider_for(self, generation: ReferenceGeneration):
        """历史 Generation 按自己记录的插件身份回到原实现，不跟随之后的全局绑定。"""
        provider = None
        if generation.plugin_id is not None and generation.plugin_version is not None:
            provider = self._registry.resolve_plugin(
                generation.plugin_id,
                generation.plugin_version,
                capabilities=_generation_ports(generation),
            )
        if provider is None:
            raise RuntimeError("Generation 对应的模型服务尚未配置。")
        return provider

    async def _submit_ready_keyframe_generations(
        self,
        document: StructuredDirectorDocument,
        *,
        report_blocked: bool = False,
    ) -> StructuredDirectorDocument:
        return await self._media._submit_ready_keyframe_generations(
            document=document,
            report_blocked=report_blocked,
        )

    async def _submit_keyframe_generation(
        self,
        document: StructuredDirectorDocument,
        keyframe_id: str,
        inputs: ImageInputs,
        *,
        retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        return await self._media._submit_keyframe_generation(
            document=document,
            keyframe_id=keyframe_id,
            inputs=inputs,
            retry_of=retry_of,
        )

    async def _submit_narration_generation(
        self,
        document: StructuredDirectorDocument,
        cue: NarrationCue,
        language: NarrationLanguage,
        *,
        retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        return await self._media._submit_narration_generation(
            document=document,
            cue=cue,
            language=language,
            retry_of=retry_of,
        )


def _validate_remix_range(
    start: float | None,
    end: float | None,
    duration: float | None,
    label: str,
) -> None:
    if start is None or end is None or duration is None:
        return
    if end > duration + 1e-6:
        raise ValueError(f"{label}结束时间不能超过输入音轨时长。")


def _find_narration_cue(document: StructuredDirectorDocument, cue_id: str) -> NarrationCue:
    if document.director_script is None:
        raise ValueError("结构化导演脚本不存在。")
    cue = next(
        (
            item
            for scene in document.director_script.scenes
            for item in scene.narration_cues
            if item.id == cue_id
        ),
        None,
    )
    if cue is None:
        raise ValueError("旁白 Cue 不存在。")
    return cue


def _find_generation(
    document: StructuredDirectorDocument, generation_id: str
) -> ReferenceGeneration:
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if generation is None:
        raise ValueError("Generation 不存在。")
    return generation
