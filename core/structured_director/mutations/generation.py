"""Generation 生命周期 mutations：纯函数化的生成状态机（P2-C4）。

从 store generation 方法原样抽取的**纯文档变换**：目标校验、create 暂存、
complete 落账、dismiss 级联、恢复提交中断。文件字节写入（asset ingest、
Scene 输出归档）留在 store，由 mutator 闭包编排后统一走 commit_mutation。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

from core.director_commands import CommandReceipt, GenerationTarget

from ..models import (
    CharacterCard,
    GenerationOperation,
    LocationLibrary,
    NarratorVoice,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    StructuredDirectorDocument,
    transition_generation,
)
from ..run_state import _wake_director_run_for_completed_generations
from ..video_mutations import _apply_reference_library_change
from .reference import set_look_asset

_TERMINAL_OR_UNCERTAIN = frozenset(
    {
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
    }
)
_SCENE_OUTPUT_KINDS = frozenset(
    {
        ReferenceGenerationKind.SCENE_FINAL_VIDEO,
        ReferenceGenerationKind.SCENE_ANIMATIC,
    }
)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def validate_generation_target(
    document: StructuredDirectorDocument, generation: ReferenceGeneration
) -> None:
    """按 kind 校验 Generation 目标存在性与类型。"""
    if generation.kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        if document.reference_library.look_owner(generation.target_id) is None:
            raise ValueError("Generation 目标造型不存在。")
    elif generation.kind in {
        ReferenceGenerationKind.LOCATION_IMAGE,
        ReferenceGenerationKind.PANORAMA_CAPTURE,
    }:
        if document.location_library.image_owner(generation.target_id) is None:
            raise ValueError("Generation 目标地点图片不存在。")
    elif generation.kind is ReferenceGenerationKind.KEYFRAME_IMAGE:
        keyframe_ids = (
            set()
            if document.keyframe_plan is None
            else {item.id for item in document.keyframe_plan.keyframes}
        )
        if generation.target_id not in keyframe_ids:
            raise ValueError("Generation 目标 Keyframe 不存在。")
    elif generation.kind is ReferenceGenerationKind.NARRATION_AUDIO:
        cue_ids = {
            cue.id
            for scene in (
                () if document.director_script is None else document.director_script.scenes
            )
            for cue in scene.narration_cues
        }
        if generation.target_id not in cue_ids:
            raise ValueError("Generation 目标旁白 Cue 不存在。")
    elif generation.kind is ReferenceGenerationKind.DIALOGUE_AUDIO:
        line_ids = {
            line.id
            for scene in (
                () if document.director_script is None else document.director_script.scenes
            )
            for segment in scene.segments
            for line in segment.dialogue_lines
        }
        if generation.target_id not in line_ids:
            raise ValueError("Generation 目标 DialogueLine 不存在。")
    else:
        _validate_media_generation_target(document, generation)


def _validate_media_generation_target(
    document: StructuredDirectorDocument, generation: ReferenceGeneration
) -> None:
    """视频/抽帧/成片/Scene 输出与旁白身份等媒体类 Generation 的目标校验。"""
    if generation.kind is ReferenceGenerationKind.GENERATED_AUDIO:
        # 通用音频不是角色或 Cue 候选；target_id 仅稳定关联同一请求的 retry 血缘。
        return
    if generation.kind in {
        ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
        ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
        ReferenceGenerationKind.VIDEO_AUDIO_REMIX,
    }:
        target = next((item for item in document.assets if item.id == generation.target_id), None)
        if target is None or target.media_type != "video/mp4":
            raise ValueError("视频音轨 Generation 目标必须是项目内 MP4 Asset。")
        return
    _validate_video_generation_target(document, generation)


def _validate_video_generation_target(
    document: StructuredDirectorDocument, generation: ReferenceGeneration
) -> None:
    """Segment 视频/超分/抽帧的 Segment、Keyframe 与 MP4 目标校验。"""
    if generation.kind is ReferenceGenerationKind.VIDEO_FRAME:
        keyframe_ids = (
            set()
            if document.keyframe_plan is None
            else {item.id for item in document.keyframe_plan.keyframes}
        )
        asset = next((item for item in document.assets if item.id == generation.target_id), None)
        if generation.target_id not in keyframe_ids and (
            asset is None or asset.media_type != "video/mp4"
        ):
            raise ValueError("抽帧 Generation 目标必须是 Keyframe 或项目内 MP4 Asset。")
        return
    if generation.kind in {
        ReferenceGenerationKind.SEGMENT_VIDEO,
        ReferenceGenerationKind.VIDEO_UPSCALE,
    }:
        segment_ids = (
            set()
            if document.video_plan is None
            else {item.segment_id for item in document.video_plan.segments}
        )
        if generation.target_id not in segment_ids:
            raise ValueError("Generation 目标 Segment 不存在。")
        return
    if generation.kind is ReferenceGenerationKind.FINAL_VIDEO:
        if document.final_assembly is None or generation.target_id != document.project_id:
            raise ValueError("Generation 目标成片装配不存在。")
        return
    if generation.kind in _SCENE_OUTPUT_KINDS:
        scene_ids = {
            scene.id
            for scene in (
                () if document.director_script is None else document.director_script.scenes
            )
        }
        if generation.target_id not in scene_ids:
            raise ValueError("Generation 目标 Scene 不存在。")
        return
    if generation.kind is ReferenceGenerationKind.NARRATOR_VOICE:
        narrator = document.reference_library.narrator
        if narrator is None or generation.target_id != narrator.id:
            raise ValueError("Generation 目标旁白身份不存在。")
        return
    card_ids = {item.id for item in document.reference_library.characters}
    if generation.target_id not in card_ids:
        raise ValueError("Generation 目标卡片不存在。")


def stage_generation(
    document: StructuredDirectorDocument,
    generation: ReferenceGeneration,
    *,
    timestamp: str,
) -> StructuredDirectorDocument:
    """追加 Generation。"""
    generation = replace(generation, created_at=timestamp, updated_at=timestamp)
    return replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, generation),
    )


def create_generations(
    document: StructuredDirectorDocument,
    generations: tuple[ReferenceGeneration, ...],
    *,
    timestamp: str,
) -> StructuredDirectorDocument:
    """批量创建（仅关联音轨分离）并统一时间戳。"""
    if not generations:
        raise ValueError("必须创建至少一个 Generation。")
    if len({item.id for item in generations}) != len(generations):
        raise ValueError("Generation ID 不能重复。")
    known_assets = {item.id: item for item in document.assets}
    for generation in generations:
        if generation.kind not in {
            ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
            ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
        }:
            raise ValueError("批量 Generation 入口仅用于关联音轨分离。")
        target = known_assets.get(generation.target_id)
        if target is None or target.media_type != "video/mp4":
            raise ValueError("视频音轨分离目标必须是项目内 MP4 Asset。")
    generations = tuple(
        replace(item, created_at=timestamp, updated_at=timestamp) for item in generations
    )
    return replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, *generations),
    )


# ---------------------------------------------------------------------------
# update / recover
# ---------------------------------------------------------------------------


def update_generation(
    document: StructuredDirectorDocument,
    generation: ReferenceGeneration,
    *,
    timestamp: str,
) -> tuple[StructuredDirectorDocument, bool]:
    """应用 Provider 观察；阶段/错误未变时保留原消息。返回 (document, changed)。"""
    generations = {item.id: item for item in document.generations}
    if generation.id not in generations:
        raise ValueError("Generation 不存在。")
    previous = generations[generation.id]
    durable = replace(generation, progress=previous.progress)
    if generation.phase == previous.phase and generation.error_code == previous.error_code:
        durable = replace(durable, message=previous.message)
    if durable == previous:
        return document, False
    durable = replace(
        durable,
        created_at=previous.created_at,
        updated_at=timestamp,
    )
    generations[generation.id] = durable
    updated = replace(
        document,
        revision=document.revision + 1,
        generations=tuple(generations.values()),
    )
    return _wake_director_run_for_completed_generations(updated), True


def recover_interrupted_submissions(
    document: StructuredDirectorDocument, *, timestamp: str
) -> tuple[StructuredDirectorDocument, bool]:
    """启动恢复：提交中的 Generation 标记为 submission_uncertain（不自动重试）。"""
    recovered = tuple(
        replace(
            transition_generation(
                generation,
                ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
                message="Core 在提交期间重启，外部任务是否创建未知；系统不会自动重试。",
                error_code="core_restarted_during_submit",
            ),
            updated_at=timestamp,
        )
        if generation.phase is ReferenceGenerationPhase.SUBMITTING
        else generation
        for generation in document.generations
    )
    if recovered == document.generations:
        return document, False
    updated = replace(
        document,
        revision=document.revision + 1,
        generations=recovered,
    )
    return _wake_director_run_for_completed_generations(updated), True


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------


def validate_completion_payload(
    generation: ReferenceGeneration,
    *,
    media_type: str,
    content: bytes,
    expected_sha256: str,
    expected_byte_count: int,
) -> None:
    """complete 前置校验：产出媒体类型与 Provider Artifact 字节一致性。"""
    if generation.kind in {
        ReferenceGenerationKind.CHARACTER_VOICE,
        ReferenceGenerationKind.NARRATOR_VOICE,
        ReferenceGenerationKind.NARRATION_AUDIO,
        ReferenceGenerationKind.GENERATED_AUDIO,
        ReferenceGenerationKind.DIALOGUE_AUDIO,
        ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
        ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
    }:
        if media_type != "audio/wav":
            raise ValueError("音色 Generation 只能产出 WAV Asset。")
    elif generation.kind in {
        ReferenceGenerationKind.SEGMENT_VIDEO,
        ReferenceGenerationKind.VIDEO_UPSCALE,
        ReferenceGenerationKind.FINAL_VIDEO,
        ReferenceGenerationKind.SCENE_FINAL_VIDEO,
        ReferenceGenerationKind.SCENE_ANIMATIC,
        ReferenceGenerationKind.VIDEO_AUDIO_REMIX,
    }:
        if media_type != "video/mp4":
            raise ValueError("视频 Generation 只能产出 MP4 Asset。")
    elif not media_type.startswith("image/"):
        raise ValueError("图片 Generation 只能产出图片 Asset。")
    if (
        len(content) != expected_byte_count
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise ValueError("Provider Artifact 字节与描述不一致。")


def complete_generation_document(
    document: StructuredDirectorDocument,
    generation: ReferenceGeneration,
    *,
    asset_id: str,
    timestamp: str,
) -> StructuredDirectorDocument:
    """complete 的纯文档部分：状态迁移、Scene 历史级联、装配失效与帧绑定落定。"""
    completed = transition_generation(
        generation,
        ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        output_asset_id=asset_id,
        error_code=None,
    )
    generations = {item.id: item for item in document.generations}
    if completed.id not in generations:
        raise ValueError("Generation 不存在。")
    previous = generations[completed.id]
    completed = replace(
        completed,
        created_at=previous.created_at,
        updated_at=timestamp,
    )
    if completed.kind in _SCENE_OUTPUT_KINDS:
        generations = _dismiss_superseded_scene_outputs(generations, completed, timestamp)
    generations[completed.id] = completed
    updated = replace(
        document,
        revision=document.revision + 1,
        generations=tuple(generations.values()),
        # 最终成片直接拼接 Scene 成片字节；任一 Scene 成片变化都会让已有装配计划过期。
        final_assembly=(
            None
            if completed.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
            else document.final_assembly
        ),
    )
    if completed.kind is ReferenceGenerationKind.VIDEO_FRAME and updated.keyframe_plan:
        updated = _attach_extracted_keyframe_candidate(updated, completed, timestamp)
    if completed.kind is ReferenceGenerationKind.PANORAMA_CAPTURE:
        updated = _attach_panorama_capture(updated, completed)
    return _wake_director_run_for_completed_generations(updated)


def _attach_panorama_capture(
    updated: StructuredDirectorDocument, completed: ReferenceGeneration
) -> StructuredDirectorDocument:
    """全景取景是确定性产物，成功后直接成为目标普通图片的当前图片。"""
    owner = updated.location_library.image_owner(completed.target_id)
    if owner is None:
        return updated
    location, image = owner
    request = completed.panorama_capture_request
    if image.source is None or request is None:
        return updated
    source_owner = updated.location_library.image_owner(image.source.panorama_image_id)
    if source_owner is None or source_owner[1].selected_asset_id != request.panorama_asset_id:
        return updated
    if (
        image.source.yaw_deg,
        image.source.pitch_deg,
        image.source.hfov_deg,
    ) != (request.yaw_deg, request.pitch_deg, request.hfov_deg):
        return updated
    images = tuple(
        replace(item, selected_asset_id=completed.output_asset_id) if item.id == image.id else item
        for item in location.images
    )
    library = LocationLibrary(
        tuple(
            replace(location, images=images) if item.id == location.id else item
            for item in updated.location_library.locations
        )
    )
    return replace(updated, location_library=library)


def _dismiss_superseded_scene_outputs(
    generations: dict[str, ReferenceGeneration],
    completed: ReferenceGeneration,
    timestamp: str,
) -> dict[str, ReferenceGeneration]:
    """Scene 输出重渲时级联隐藏同目标、同语言的历史终态卡片。"""
    return {
        item.id: (
            replace(item, dismissed=True, updated_at=timestamp)
            if item.kind is completed.kind
            and item.target_id == completed.target_id
            and item.language is completed.language
            and item.id != completed.id
            and item.phase in _TERMINAL_OR_UNCERTAIN
            else item
        )
        for item in generations.values()
    }


def _attach_extracted_keyframe_candidate(
    updated: StructuredDirectorDocument, completed: ReferenceGeneration, timestamp: str
) -> StructuredDirectorDocument:
    """目标为 Keyframe 的抽帧成功后，把产物登记为该 Keyframe 的候选；不自动选择。"""
    if not any(item.id == completed.target_id for item in updated.keyframe_plan.keyframes):
        return updated
    request = completed.video_frame_request
    frame = "" if request is None or request.frame_index is None else f"第 {request.frame_index} 帧"
    candidate = ReferenceGeneration(
        id=hashlib.sha256(f"video-frame-candidate:{completed.id}".encode()).hexdigest()[:32],
        kind=ReferenceGenerationKind.KEYFRAME_IMAGE,
        operation=GenerationOperation.ATTACH,
        target_id=completed.target_id,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        message=f"已从上一 Segment 视频抽取{frame}，作为首帧候选。",
        prompt_text=f"从上一 Segment 视频抽取{frame}。",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id="storyrail.video_frame",
        plugin_version=1,
        external_id=completed.id,
        output_asset_id=completed.output_asset_id,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    return replace(updated, generations=(*updated.generations, candidate))


# ---------------------------------------------------------------------------
# dismiss / attach
# ---------------------------------------------------------------------------


def _asset_is_referenced(document: StructuredDirectorDocument, asset_id: str) -> bool:
    for card in document.reference_library.characters:
        if card.voice_reference_asset_id == asset_id or asset_id in card.look_asset_ids:
            return True
    narrator = document.reference_library.narrator
    if narrator is not None and asset_id in narrator.voice_reference_asset_ids:
        return True
    if document.director_script is not None and any(
        asset_id in cue.selected_audio_asset_ids
        for scene in document.director_script.scenes
        for cue in scene.narration_cues
    ):
        return True
    if document.dialogue_plan is not None and any(
        item.selected_audio_asset_id == asset_id for item in document.dialogue_plan.items
    ):
        return True
    if any(
        asset_id in tuple(image.selected_asset_id for image in item.images)
        for item in document.location_library.locations
    ):
        return True
    if document.keyframe_plan is not None and any(
        item.selected_asset_id == asset_id for item in document.keyframe_plan.keyframes
    ):
        return True
    if document.video_plan is not None and any(
        item.selected_asset_id == asset_id or item.upscaled_asset_id == asset_id
        for item in document.video_plan.segments
    ):
        return True
    return document.final_assembly is not None and (
        asset_id
        in (
            document.final_assembly.selected_zh_asset_id,
            document.final_assembly.selected_en_asset_id,
        )
        or any(
            asset_id in (item.zh_asset_id, item.en_asset_id)
            for item in document.final_assembly.clips
        )
    )


def _require_generation(
    document: StructuredDirectorDocument, generation_id: str
) -> ReferenceGeneration:
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if generation is None:
        raise ValueError("Generation 不存在。")
    return generation


def dismiss_generation(
    document: StructuredDirectorDocument,
    target: GenerationTarget,
    *,
    command_id: str,
    timestamp: str,
) -> tuple[StructuredDirectorDocument, CommandReceipt, bool]:
    """隐藏终态 Generation 卡片；Scene 输出 kind 级联隐藏全部历史。"""
    generation = _require_generation(document, target.generation_id)
    if generation.dismissed:
        return (
            document,
            CommandReceipt(
                command_id,
                "noop",
                document.revision,
                document.revision,
                decision_summary="Generation 历史已经隐藏。",
            ),
            False,
        )
    if generation.phase not in _TERMINAL_OR_UNCERTAIN:
        raise ValueError("只有已经结束的 Generation 可以删除历史卡片。")
    # 最终成片直接引用 Scene 成片 Asset；删除 Scene 成片会同时作废这份派生装配计划，
    # 因此引用检查必须在没有该计划的投影状态上判断。
    references_document = (
        replace(document, final_assembly=None)
        if generation.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
        else document
    )
    if generation.output_asset_id is not None and _asset_is_referenced(
        references_document, generation.output_asset_id
    ):
        raise ValueError("该候选已经成为参考素材，请先解除引用。")
    scene_output_history_ids = {
        item.id
        for item in document.generations
        if item.kind is generation.kind
        and item.target_id == generation.target_id
        and item.language is generation.language
        and item.phase in _TERMINAL_OR_UNCERTAIN
    }
    dismissed_ids = (
        scene_output_history_ids
        if generation.kind in _SCENE_OUTPUT_KINDS
        else {target.generation_id}
    )
    generations = {
        item.id: replace(item, dismissed=True, updated_at=timestamp)
        if item.id in dismissed_ids
        else item
        for item in document.generations
    }
    updated = replace(
        document,
        revision=document.revision + 1,
        generations=tuple(generations.values()),
        final_assembly=(
            None
            if generation.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
            else document.final_assembly
        ),
    )
    receipt = CommandReceipt(
        command_id,
        "succeeded",
        document.revision,
        updated.revision,
        changed_ids=tuple(sorted(dismissed_ids)),
        preserved=("generation_history", "output_asset"),
        decision_summary=(
            "已隐藏该 Scene 的当前输出及全部历史卡片，历史事实与产物仍保留。"
            if generation.kind in _SCENE_OUTPUT_KINDS
            else "已隐藏终态 Generation 卡片，历史事实与产物仍保留。"
        ),
    )
    return updated, receipt, True


def _map_card(
    library: ReferenceLibrary,
    kind: str,
    card_id: str,
    transform,
) -> ReferenceLibrary:
    if kind == "characters":
        found = False
        cards = []
        for card in library.characters:
            if card.id == card_id:
                updated = transform(card)
                if not isinstance(updated, CharacterCard):
                    raise TypeError("角色卡转换结果不合法。")
                cards.append(updated)
                found = True
            else:
                cards.append(card)
        if not found:
            raise ValueError("角色卡不存在。")
        return replace(library, characters=tuple(cards))
    raise ValueError("未知的卡片类型。")


def attach_generation_output(
    document: StructuredDirectorDocument,
    *,
    kind: str,
    card_id: str,
    generation_id: str,
    note: str,
) -> StructuredDirectorDocument:
    """把成功 Generation 的输出挂为角色/旁白参考或角色参考图。"""
    generation = _require_generation(document, generation_id)
    if generation.dismissed:
        raise ValueError("已删除的候选不能成为参考素材。")
    if generation.phase is not ReferenceGenerationPhase.SUCCEEDED:
        raise ValueError("只有成功的 Generation 可以成为参考素材。")
    if generation.target_id != card_id:
        raise ValueError("Generation 不属于该卡片。")
    if generation.output_asset_id is None:
        raise ValueError("Generation 缺少输出 Asset。")
    if kind == "voice":
        if generation.kind is not ReferenceGenerationKind.CHARACTER_VOICE:
            raise ValueError("该 Generation 不是参考音色。")
        characters = []
        found = False
        for card in document.reference_library.characters:
            if card.id == card_id:
                characters.append(
                    replace(
                        card,
                        voice_description=generation.prompt_text,
                        voice_reference_asset_id=generation.output_asset_id,
                        voice_reference_transcript=generation.sample_text,
                    )
                )
                found = True
            else:
                characters.append(card)
        if not found:
            raise ValueError("角色卡不存在。")
        return _bump(
            document,
            _apply_reference_library_change(
                document, replace(document.reference_library, characters=tuple(characters))
            ),
        )
    if kind == "narrator_voice":
        if generation.kind is not ReferenceGenerationKind.NARRATOR_VOICE:
            raise ValueError("该 Generation 不是旁白参考音色。")
        narrator = document.reference_library.narrator
        if narrator is None or narrator.id != card_id:
            raise ValueError("旁白音色身份不存在。")
        language = generation.language
        return _bump(
            document,
            _apply_reference_library_change(
                document,
                replace(
                    document.reference_library,
                    narrator=narrator.with_voice(
                        language,
                        NarratorVoice(
                            voice_description=generation.prompt_text,
                            voice_reference_asset_id=generation.output_asset_id,
                            voice_reference_transcript=generation.sample_text,
                        ),
                    ),
                ),
            ),
        )
    raise ValueError("未知的参考素材类型。")


def select_look_sheet(
    document: StructuredDirectorDocument,
    *,
    card_id: str,
    look_id: str,
    generation_id: str,
) -> StructuredDirectorDocument:
    """人类把成功的设定图候选选为造型图；Keyframe 引用造型，不需要改写。"""
    generation = _require_generation(document, generation_id)
    if generation.kind is not ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        raise ValueError("该 Generation 不是造型设定图。")
    if generation.dismissed:
        raise ValueError("已删除的候选不能成为造型图。")
    if generation.phase is not ReferenceGenerationPhase.SUCCEEDED:
        raise ValueError("只有成功的 Generation 可以成为造型图。")
    if generation.target_id != look_id or generation.output_asset_id is None:
        raise ValueError("Generation 不属于该造型或缺少输出 Asset。")
    return _bump(
        document,
        set_look_asset(
            document, card_id=card_id, look_id=look_id, asset_id=generation.output_asset_id
        ),
    )


def _bump(
    document: StructuredDirectorDocument, updated: StructuredDirectorDocument
) -> StructuredDirectorDocument:
    return replace(updated, revision=document.revision + 1)
