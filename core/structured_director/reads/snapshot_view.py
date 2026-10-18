from __future__ import annotations

from typing import Any, Protocol

from ..assembly_timeline import (
    _build_final_assembly_plan,
    _build_scene_animatic_spec,
    _build_scene_final_plan,
    _current_scene_final_asset_id,
)
from ..candidate_eligibility import generation_is_reviewable
from ..codec.keyframe import serialize_character_references
from ..dialogue_timing import dialogue_timing_warnings
from ..models import (
    Asset,
    DirectorRunKind,
    DirectorRunStatus,
    NarrationCue,
    NarrationLanguage,
    NarratorVoice,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    asset_deletion_closure,
    asset_usage_reasons,
)
from ..narration_timing import narration_timing_language, narration_timing_seconds
from ..video_inputs import start_frame_extraction_source, video_inputs_unchanged
from .location_view import location_library_projection
from .video_recipes import video_recipe_state
from .workflow_state import production_baseline_issue, references_reviewed, workflow_state


class _ProviderAvailabilityView(Protocol):
    """snapshot 投影所需的 provider 可用性视图（StructuredDirectorService 实现）。"""

    pano_view_available: bool
    image_generation_available: bool
    voice_design_available: bool
    speech_synthesis_available: bool
    speech_recognition_available: bool
    video_generation_available: bool
    video_upscale_available: bool
    final_assembly_available: bool
    scene_animatic_available: bool
    video_frame_available: bool
    audio_separation_available: bool
    audio_remix_available: bool

    provider_catalog: object

    def location_master_candidate_valid(self, asset: Asset) -> bool: ...

    def provider_recipe_views(self) -> list[dict]: ...

    def observed_generation(self, generation: ReferenceGeneration) -> ReferenceGeneration: ...


_STRING_SEED_KINDS = frozenset(
    {
        ReferenceGenerationKind.SEGMENT_VIDEO,
        ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
        ReferenceGenerationKind.LOCATION_MASTER_IMAGE,
        ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
        ReferenceGenerationKind.KEYFRAME_IMAGE,
    }
)


def _start_frame_extraction_projection(document, keyframe_id):
    source = start_frame_extraction_source(document, keyframe_id)
    return {
        "source_segment_id": source["source_segment_id"],
        "source_video_asset_id": source["source_video_asset_id"],
        "state": source["state"],
        "message": source["message"],
    }


def _scene_finals_ready(document: StructuredDirectorDocument) -> bool:
    """最终成片只拼接 Scene 成片；所有 Scene 都必须有基于当前输入生成的成片。"""
    try:
        _build_final_assembly_plan(document)
    except ValueError:
        return False
    return True


def _allowed_actions(document: StructuredDirectorDocument) -> tuple[str, ...]:
    active = document.active_director_run
    if active is not None and not (
        active.kind is DirectorRunKind.DIRECTOR
        and active.status in {DirectorRunStatus.WAITING_USER, DirectorRunStatus.WAITING_JOBS}
    ):
        # 领域 run 进行中：人类入口全部关闭，恢复由外部 Agent 经 request/run 工具完成。
        return ()
    if document.status is StructuredDirectorStatus.APPROVED:
        return ("reopen_video_production",)
    if document.status is StructuredDirectorStatus.AWAITING_PROPOSAL:
        return ()
    actions = [
        "edit_reference_library",
        "import_image_asset",
        "import_media_asset",
        "generate_audio",
        "apply_audio_effect",
        "trim_audio",
        "separate_video_audio",
        "remix_video_audio",
        "delete_asset",
        "attach_reference_image",
        "upload_reference_voice",
    ]
    if document.status is StructuredDirectorStatus.REVIEWING:
        if not references_reviewed(document):
            actions.append("confirm_reference_review")
    elif document.status is StructuredDirectorStatus.REVIEWING_SCRIPT:
        actions.append("edit_script")
        if (
            document.director_script is not None
            and document.director_script.production_baseline_revision
            != document.director_script.revision
        ):
            actions.append("confirm_script")
        elif document.director_script is not None:
            actions.append("unlock_visual_production")
    elif document.status is StructuredDirectorStatus.REVIEWING_NARRATION:
        actions.extend(
            [
                "edit_script",
                "edit_narration",
                "generate_narration",
                "generate_narration_batch",
                "select_narration_audio",
            ]
        )
    elif document.status is StructuredDirectorStatus.REVIEWING_KEYFRAMES:
        actions.extend(
            [
                "edit_script",
                "edit_keyframe_references",
                "generate_keyframe",
                "generate_keyframe_batch",
                "select_keyframe",
            ]
        )
    elif document.status is StructuredDirectorStatus.REVIEWING_VIDEOS:
        actions.extend(
            [
                "edit_script",
                "edit_keyframe_references",
                "generate_keyframe",
                "generate_keyframe_batch",
                "select_keyframe",
                "edit_segment_video_plan",
                "generate_segment_video",
                "attach_segment_video_candidate",
                "select_segment_video",
                "upscale_segment_video",
                "generate_scene_final",
            ]
        )
        # generate_final_video 统一在下方按 Scene 成片就绪情况判定。
    elif document.status is StructuredDirectorStatus.REVIEWING_FINAL:
        actions.extend(
            [
                "edit_script",
                "select_final_video",
                "reopen_video_production",
            ]
        )
        selections = (
            ()
            if document.final_assembly is None
            else tuple(
                document.final_assembly.selected_asset_id(language)
                for language in document.narration_languages
            )
        )
        if any(item is not None for item in selections):
            actions.append("clear_final_selection")
        if selections and all(item is not None for item in selections):
            actions.append("approve_final_video")
    if "edit_script" in actions and "edit_narration" not in actions:
        actions.append("edit_narration")
    # 解锁层是持久能力；状态只锁定正在执行的任务，不能收回先前入口。
    layers = document.workspace_layers
    script = document.director_script
    if script is not None:
        actions.append("edit_script")
        if any(segment.dialogue_lines for scene in script.scenes for segment in scene.segments):
            actions.extend(
                [
                    "generate_dialogue",
                    "generate_dialogue_batch",
                    "select_dialogue_audio",
                    "set_dialogue_timing",
                ]
            )
    if layers.narration_unlocked:
        actions = [action for action in actions if action != "confirm_script"]
        actions.extend(
            [
                "edit_narration",
                "generate_narration",
                "generate_narration_batch",
                "select_narration_audio",
            ]
        )
    baseline_current = script is not None and script.production_baseline_revision == script.revision
    if baseline_current and document.video_plan is None:
        actions.append("unlock_visual_production")
    if layers.keyframes_unlocked and document.keyframe_plan is not None:
        actions.extend(
            [
                "edit_keyframe_references",
                "generate_keyframe",
                "generate_keyframe_batch",
                "select_keyframe",
                "generate_scene_animatic",
            ]
        )
    if layers.videos_unlocked and document.video_plan is not None:
        actions.extend(
            [
                "edit_segment_video_plan",
                "generate_segment_video",
                "attach_segment_video_candidate",
                "select_segment_video",
                "upscale_segment_video",
                "generate_scene_final",
            ]
        )
    videos_ready = document.video_plan is not None and all(
        item.selected_asset_id is not None for item in document.video_plan.segments
    )
    narrations_ready = script is not None and all(
        cue.fully_selected for scene in script.scenes for cue in scene.narration_cues
    )
    actions = [action for action in actions if action != "generate_final_video"]
    if videos_ready and narrations_ready and baseline_current and _scene_finals_ready(document):
        actions.append("generate_final_video")
    if not baseline_current:
        actions = [
            action
            for action in actions
            if action
            not in {
                "unlock_visual_production",
                "generate_segment_video",
                "generate_scene_animatic",
                "generate_scene_final",
            }
        ]
    if document.final_assembly is None:
        actions = [
            action
            for action in actions
            if action
            not in {
                "select_final_video",
                "approve_final_video",
            }
        ]
    if any(
        item.phase
        not in {
            ReferenceGenerationPhase.SUCCEEDED,
            ReferenceGenerationPhase.FAILED,
            ReferenceGenerationPhase.CANCELLED,
            ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        }
        for item in document.generations
    ):
        actions.append("observe_reference_generations")
    return tuple(dict.fromkeys(actions))


def _production_availability(document: StructuredDirectorDocument) -> dict[str, object]:
    script = document.director_script
    layers = document.workspace_layers
    actions = _allowed_actions(document)
    result: dict[str, object] = {}
    for kind, unlocked in (
        ("narration", layers.narration_unlocked),
        ("keyframes", layers.keyframes_unlocked),
        ("videos", layers.videos_unlocked),
        ("final", layers.final_assembly_unlocked),
    ):
        if kind == "final":
            action = "generate_final_video"
            try:
                _build_final_assembly_plan(document)
            except ValueError as exc:
                reason = str(exc)
            else:
                reason = "全部 Scene 成片已就绪，可手动拼接成片候选；选择后仍需单独 Approval。"
            if document.status is StructuredDirectorStatus.APPROVED:
                reason = "成片已批准；修改前请显式重新开放生产。"
            elif document.active_director_run is not None:
                reason = "当前项目有未完成任务，请先等待完成或处理恢复任务。"
        elif unlocked:
            reason, action = "内容层已解锁，可在当前位置编辑和制作；生成依赖会逐项校验。", None
        elif script is None:
            reason, action = "尚无结构化脚本，请审核引用库并让外部 Agent 提交脚本。", None
        elif kind == "narration" or not layers.narration_unlocked:
            reason, action = "请到项目概览确认脚本，解锁旁白审核。", "confirm_script"
        elif script.production_baseline_revision != script.revision:
            reason, action = (
                production_baseline_issue(document) or "生产基线尚未随当前脚本建立。",
                None,
            )
        elif kind == "final":
            reason, action = (
                "请先为全部 Scene 生成基于当前 Segment 与旁白的 Scene 成片，再拼接最终成片。",
                "generate_final_video",
            )
        else:
            reason, action = (
                "请到项目概览解锁视觉生产；地点可稍后再规划。",
                "unlock_visual_production",
            )
        result[kind] = {
            "unlocked": unlocked,
            "reason": reason,
            "next_location": "project",
            "action": action if action in actions else None,
        }
    return result


def _serialize_scene(
    scene: Scene,
    asset_by_id: dict[str, Asset],
    animatic: dict[str, Any] | None = None,
    scene_final: dict[str, Any] | None = None,
) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "id": scene.id,
        "title": scene.title,
        "summary": scene.summary,
        "setting": scene.setting,
        "driver": scene.driver,
        "location_id": scene.location_id,
        "state_id": scene.state_id,
        "shots": [
            {
                "id": shot.id,
                "visible_character_ids": list(shot.visible_character_ids),
                "composition": shot.composition,
                "camera_movement": shot.camera_movement,
                "action": shot.action,
                "audio_direction": shot.audio_direction,
                "transition_in": shot.transition_in,
                "view_id": shot.view_id,
            }
            for shot in scene.shots
        ],
        "segments": [
            {
                "id": segment.id,
                "shot_ids": list(segment.shot_ids),
                "duration_estimate_seconds": segment.duration_estimate_seconds,
                "action": segment.action,
                "dialogue_lines": [
                    {
                        "id": line.id,
                        "character_id": line.character_id,
                        "speaker_label": line.speaker_label,
                        "voice_description": line.voice_description,
                        "text": line.text,
                        "delivery": line.delivery,
                    }
                    for line in segment.dialogue_lines
                ],
                "boundary_from_previous": (
                    None
                    if segment.boundary_from_previous is None
                    else {
                        "reason": segment.boundary_from_previous.reason.value,
                        "continuity_instruction": (
                            segment.boundary_from_previous.continuity_instruction
                        ),
                    }
                ),
            }
            for segment in scene.segments
        ],
        "narration_cues": [
            _serialize_narration_cue(cue, asset_by_id) for cue in scene.narration_cues
        ],
    }
    if animatic is not None:
        serialized["animatic"] = animatic
    if scene_final is not None:
        serialized["scene_final"] = scene_final
    return serialized


def _serialize_narration_cue(cue: NarrationCue, asset_by_id: dict[str, Asset]) -> dict[str, Any]:
    """旁白 Cue：所选语言各自的正文、参数与已选音频时长，以及时间基准语言。"""
    tracks: dict[str, Any] = {"zh": None, "en": None}
    for language, track in cue.tracks:
        asset = (
            None
            if track.selected_audio_asset_id is None
            else asset_by_id.get(track.selected_audio_asset_id)
        )
        tracks[language.value] = {
            "text": track.text,
            "seed": track.seed,
            "selected_audio_asset_id": track.selected_audio_asset_id,
            "recipe_params": track.recipe_params.to_json(),
            "selected_duration_seconds": None if asset is None else asset.duration_seconds,
        }
    try:
        timing_language: str | None = narration_timing_language(cue, asset_by_id).value
        timing_seconds: float | None = narration_timing_seconds(cue, asset_by_id)
    except ValueError:
        timing_language, timing_seconds = None, None
    return {
        "id": cue.id,
        **tracks,
        "timing_language": timing_language,
        "timing_seconds": timing_seconds,
    }


def _scene_animatic_state(
    document: StructuredDirectorDocument,
    scene_id: str,
    service: _ProviderAvailabilityView,
) -> dict[str, Any]:
    try:
        _build_scene_animatic_spec(document, scene_id)
    except ValueError as exc:
        ready, reason = False, str(exc)
    else:
        ready, reason = True, "已就绪。"
    active_generation_id = None
    latest_succeeded_generation_id = None
    for generation in reversed(document.generations):
        if generation.kind is not ReferenceGenerationKind.SCENE_ANIMATIC:
            continue
        if generation.target_id != scene_id:
            continue
        if active_generation_id is None and generation.phase in {
            ReferenceGenerationPhase.SUBMITTING,
            ReferenceGenerationPhase.QUEUED,
            ReferenceGenerationPhase.RUNNING,
        }:
            active_generation_id = generation.id
        if (
            latest_succeeded_generation_id is None
            and generation.phase is ReferenceGenerationPhase.SUCCEEDED
            and not generation.dismissed
        ):
            latest_succeeded_generation_id = generation.id
        if active_generation_id is not None and latest_succeeded_generation_id is not None:
            break
    return {
        "provider_available": service.scene_animatic_available,
        "ready": ready,
        "reason": reason,
        "active_generation_id": active_generation_id,
        "latest_succeeded_generation_id": latest_succeeded_generation_id,
    }


def _scene_final_state(
    document: StructuredDirectorDocument,
    scene_id: str,
    service: _ProviderAvailabilityView,
) -> dict[str, Any]:
    try:
        for language in document.narration_languages:
            _build_scene_final_plan(document, scene_id, language)
    except ValueError as exc:
        ready, reason = False, str(exc)
    else:
        ready, reason = True, "已就绪。"
    state: dict[str, Any] = {
        "provider_available": service.final_assembly_available,
        "ready": ready,
        "reason": reason,
    }
    for language in document.narration_languages:
        state[language.value] = _scene_final_language_state(document, scene_id, language)
    for language in (NarrationLanguage.ZH, NarrationLanguage.EN):
        state.setdefault(language.value, None)
    return state


def _scene_final_language_state(
    document: StructuredDirectorDocument, scene_id: str, language: NarrationLanguage
) -> dict[str, Any]:
    current_asset_id = _current_scene_final_asset_id(document, scene_id, language)
    active_generation_id = None
    latest_succeeded_generation_id = None
    latest_output_asset_id = None
    for generation in reversed(document.generations):
        if (
            generation.kind is not ReferenceGenerationKind.SCENE_FINAL_VIDEO
            or generation.target_id != scene_id
            or generation.language is not language
        ):
            continue
        if active_generation_id is None and generation.phase in {
            ReferenceGenerationPhase.SUBMITTING,
            ReferenceGenerationPhase.QUEUED,
            ReferenceGenerationPhase.RUNNING,
        }:
            active_generation_id = generation.id
        if (
            latest_succeeded_generation_id is None
            and generation.phase is ReferenceGenerationPhase.SUCCEEDED
            and not generation.dismissed
        ):
            latest_succeeded_generation_id = generation.id
            latest_output_asset_id = generation.output_asset_id
        if active_generation_id is not None and latest_succeeded_generation_id is not None:
            break
    return {
        "active_generation_id": active_generation_id,
        "latest_succeeded_generation_id": latest_succeeded_generation_id,
        "current_asset_id": current_asset_id,
        # 已有成片输出，但它不是基于当前 Segment/双语旁白选择生成的，最终装配不接受它。
        "outdated": latest_output_asset_id is not None
        and latest_output_asset_id != current_asset_id,
    }


def _generation_allowed_actions(
    document: StructuredDirectorDocument,
    generation: ReferenceGeneration,
) -> tuple[str, ...]:
    if document.status is StructuredDirectorStatus.APPROVED:
        return ()
    if generation.phase in {
        ReferenceGenerationPhase.QUEUED,
        ReferenceGenerationPhase.RUNNING,
    }:
        return () if generation.cancellation_requested else ("cancel",)
    if generation.dismissed:
        return ()
    if generation.phase in {
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
    }:
        return ("retry", "dismiss_history")
    if (
        generation.phase is not ReferenceGenerationPhase.SUCCEEDED
        or generation.output_asset_id is None
    ):
        return ()
    referenced_asset_ids = {
        asset_id
        for card in document.reference_library.characters
        for asset_id in card.look_asset_ids
    }
    referenced_asset_ids.update(
        card.voice_reference_asset_id
        for card in document.reference_library.characters
        if card.voice_reference_asset_id is not None
    )
    narrator = document.reference_library.narrator
    if narrator is not None:
        referenced_asset_ids.update(narrator.voice_reference_asset_ids)
    if document.director_script is not None:
        referenced_asset_ids.update(
            asset_id
            for scene in document.director_script.scenes
            for cue in scene.narration_cues
            for asset_id in cue.selected_audio_asset_ids
        )
    referenced_asset_ids.update(
        asset_id
        for item in document.location_library.locations
        for asset_id in (
            item.master.selected_asset_id,
            *(view.selected_asset_id for view in item.views),
        )
        if asset_id is not None
    )
    if document.keyframe_plan is not None:
        referenced_asset_ids.update(
            item.selected_asset_id
            for item in document.keyframe_plan.keyframes
            if item.selected_asset_id is not None
        )
    if document.final_assembly is not None:
        referenced_asset_ids.update(
            asset_id
            for language in document.narration_languages
            if (asset_id := document.final_assembly.selected_asset_id(language)) is not None
        )
    if generation.output_asset_id in referenced_asset_ids:
        return ()
    if generation.kind in {
        ReferenceGenerationKind.VIDEO_FRAME,
        ReferenceGenerationKind.LOCATION_VIEW_CROP,
    }:
        return ()
    if generation.kind is ReferenceGenerationKind.KEYFRAME_IMAGE:
        return ("select_output", "dismiss_history")
    if generation.kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        return ("select_look_sheet", "dismiss_history")
    if generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO:
        # 输入快照变化只通过 inputs_outdated 软提示，选择入口始终保留。
        return ("select_segment_video", "dismiss_history")
    if generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE:
        return ("attach_upscaled_video", "dismiss_history")
    if generation.kind is ReferenceGenerationKind.FINAL_VIDEO:
        return ("select_final_video", "dismiss_history")
    if generation.kind is ReferenceGenerationKind.NARRATION_AUDIO:
        cue = next(
            (
                cue
                for scene in (
                    () if document.director_script is None else document.director_script.scenes
                )
                for cue in scene.narration_cues
                if cue.id == generation.target_id
            ),
            None,
        )
        if (
            cue is not None
            and generation.language is not None
            and cue.track(generation.language).text == generation.prompt_text
        ):
            return ("select_narration_audio", "dismiss_history")
        return ("dismiss_history",)
    if generation.kind is ReferenceGenerationKind.DIALOGUE_AUDIO:
        return (
            ("select_dialogue_audio", "dismiss_history")
            if generation_is_reviewable(document, generation)
            else ("dismiss_history",)
        )
    if generation.kind in {
        ReferenceGenerationKind.LOCATION_MASTER_IMAGE,
        ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
        ReferenceGenerationKind.GENERATED_AUDIO,
        ReferenceGenerationKind.SCENE_FINAL_VIDEO,
        ReferenceGenerationKind.SCENE_ANIMATIC,
        ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
        ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
        ReferenceGenerationKind.VIDEO_AUDIO_REMIX,
    }:
        return ("dismiss_history",)
    return ("attach_output", "dismiss_history")


def _asset_projection(
    document: StructuredDirectorDocument,
    asset: Asset,
    allowed_actions: tuple[str, ...],
    resource_path: str,
) -> dict[str, Any]:
    """Core 是 Asset 使用状态、删除动作与清理语义的唯一事实来源。

    Web 只展示 ``is_in_use`` / ``usage_reasons`` / ``retains_derived_assets_on_delete``，
    不得再根据 Generation 数量、``input_asset_ids`` 或 ``output_asset_id`` 自行推断。
    """

    closure = asset_deletion_closure(document, asset.id)
    reasons = asset_usage_reasons(document, asset.id)
    return {
        "id": asset.id,
        "media_type": asset.media_type,
        "image_category": (None if asset.image_category is None else asset.image_category.value),
        "byte_count": asset.byte_count,
        "duration_seconds": asset.duration_seconds,
        "display_name": asset.display_name,
        "content_url": f"{resource_path}/assets/{asset.id}/content",
        "is_in_use": bool(reasons),
        "usage_reasons": [{"code": reason.value, "label": reason.label} for reason in reasons],
        "retains_derived_assets_on_delete": (
            False if closure is None else closure.retains_derived_assets
        ),
        "allowed_actions": [
            *(
                ["audio_trim"]
                if asset.media_type == "audio/wav"
                and asset.duration_seconds is not None
                and "trim_audio" in allowed_actions
                else []
            ),
            *(
                ["audio_effect"]
                if asset.media_type == "audio/wav" and "apply_audio_effect" in allowed_actions
                else []
            ),
            *(
                ["audio_editor"]
                if asset.media_type == "video/mp4" and "separate_video_audio" in allowed_actions
                else []
            ),
            *(
                ["video_frame"]
                if asset.media_type == "video/mp4" and "extract_video_frame" in allowed_actions
                else []
            ),
            *(
                ["delete"]
                if document.status is not StructuredDirectorStatus.APPROVED and closure is not None
                else []
            ),
        ],
    }


def _serialize_narrator_voice(voice: NarratorVoice | None) -> dict[str, Any] | None:
    """未启用语言输出 null，不省略 key。"""
    if voice is None:
        return None
    return {
        "voice_description": voice.voice_description,
        "voice_reference_asset_id": voice.voice_reference_asset_id,
        "voice_reference_transcript": voice.voice_reference_transcript,
    }


def serialize_snapshot(
    document: StructuredDirectorDocument,
    service: _ProviderAvailabilityView,
    resource_path: str,
) -> dict[str, Any]:
    allowed_actions = human_allowed_actions(document)
    if service.video_frame_available and document.status is not StructuredDirectorStatus.APPROVED:
        allowed_actions = (*allowed_actions, "extract_video_frame")
    asset_by_id = {asset.id: asset for asset in document.assets}
    provider_recipes = service.provider_recipe_views()
    return {
        "status": document.status.value,
        "active_director_run": (
            None
            if document.active_director_run is None
            else {
                "id": document.active_director_run.id,
                "kind": document.active_director_run.kind.value,
                "status": document.active_director_run.status.value,
                "waiting_reason": document.active_director_run.waiting_reason,
                "created_at": document.active_director_run.created_at,
                "updated_at": document.active_director_run.updated_at,
            }
        ),
        "revision": document.revision,
        "aspect_ratio": document.aspect_ratio.value,
        "director_plan_markdown": document.director_plan_markdown,
        "narration_languages": [language.value for language in document.narration_languages],
        "workspace_layers": {
            "narration_unlocked": document.workspace_layers.narration_unlocked,
            "keyframes_unlocked": document.workspace_layers.keyframes_unlocked,
            "videos_unlocked": document.workspace_layers.videos_unlocked,
            "final_assembly_unlocked": (document.workspace_layers.final_assembly_unlocked),
        },
        "allowed_actions": list(allowed_actions),
        "workflow": workflow_state(document),
        "capability_gap_alerts": [
            {
                "gap_id": item.gap_id,
                "run_id": item.run_id,
                "missing_command": item.missing_command,
                "raw_user_request_summary": item.raw_user_request_summary,
                "target_ids": list(item.target_ids),
                "scope_scene_ids": list(item.scope_scene_ids),
                "operation_summary": item.operation_summary,
                "old_revision": item.old_revision,
                "new_revision": item.new_revision,
                "result": item.result.value,
                "first_occurred_at": item.first_occurred_at,
                "last_occurred_at": item.last_occurred_at,
                "occurrence_count": item.occurrence_count,
                "closed_revision": item.closed_revision,
                "closed_by_command": item.closed_by_command,
                "status": item.status.value,
            }
            for item in document.capability_gap_alerts
        ],
        # 软提示：对白按字数估算装不进 Segment 预估时长；不阻止任何写入。
        "dialogue_timing_warnings": dialogue_timing_warnings(document),
        "provider_availability": {
            "image_generation": service.image_generation_available,
            "voice_design": service.voice_design_available,
            "speech_synthesis": service.speech_synthesis_available,
            "speech_recognition": service.speech_recognition_available,
            "video_generation": service.video_generation_available,
            "video_upscale": service.video_upscale_available,
            "final_assembly": service.final_assembly_available,
            "scene_animatic": service.scene_animatic_available,
            "audio_separation": service.audio_separation_available,
            "audio_remix": service.audio_remix_available,
        },
        "assets": [
            _asset_projection(document, item, allowed_actions, resource_path)
            for item in document.assets
        ],
        "provider_recipes": provider_recipes,
        "generations": [
            {
                "id": item.id,
                "kind": item.kind.value,
                "operation": item.operation.value,
                "target_id": item.target_id,
                "phase": item.phase.value,
                "progress": service.observed_generation(item).progress,
                "message": service.observed_generation(item).message,
                "prompt_text": item.prompt_text,
                "language": None if item.language is None else item.language.value,
                "input_asset_ids": list(item.input_asset_ids),
                "sample_text": item.sample_text,
                # 63 位 seed 超出 JS 安全整数；视频与图片 seed 以字符串下发。
                "seed": (
                    str(item.seed)
                    if item.kind in _STRING_SEED_KINDS and item.seed is not None
                    else item.seed
                ),
                "aspect_ratio": item.aspect_ratio,
                "duration_seconds": item.duration_seconds,
                "output_asset_id": item.output_asset_id,
                "error_code": item.error_code,
                "cancellation_requested": item.cancellation_requested,
                "retry_of": item.retry_of,
                "dismissed": item.dismissed,
                "provider": (
                    None
                    if item.provider_snapshot is None
                    else {
                        "plugin_id": item.provider_snapshot.plugin_id,
                        "recipe_id": item.provider_snapshot.recipe_id,
                        "summary": item.provider_snapshot.summary,
                    }
                ),
                # 软提示：仅 Segment 视频有意义；输入变化不阻止选择。
                "inputs_outdated": (
                    item.kind is ReferenceGenerationKind.SEGMENT_VIDEO
                    and not video_inputs_unchanged(document, item)
                ),
                "allowed_actions": list(_generation_allowed_actions(document, item)),
            }
            for item in document.generations
        ],
        "reference_library": {
            "reviewed": references_reviewed(document),
            "characters": [
                {
                    "id": item.id,
                    "name": item.name,
                    "visual_description": item.visual_description,
                    "looks": [
                        {
                            "id": look.id,
                            "name": look.name,
                            "appearance": look.appearance,
                            "usage": look.usage,
                            "selected_asset_id": look.selected_asset_id,
                        }
                        for look in item.looks
                    ],
                    "voice_description": item.voice_description,
                    "voice_reference_asset_id": item.voice_reference_asset_id,
                    "voice_reference_transcript": item.voice_reference_transcript,
                }
                for item in document.reference_library.characters
            ],
            "narrator": (
                None
                if document.reference_library.narrator is None
                else {
                    "id": document.reference_library.narrator.id,
                    "name": document.reference_library.narrator.name,
                    "zh": _serialize_narrator_voice(document.reference_library.narrator.zh),
                    "en": _serialize_narrator_voice(document.reference_library.narrator.en),
                }
            ),
        },
        "director_script": (
            None
            if document.director_script is None
            else {
                "revision": document.director_script.revision,
                "source_reference_revision": (document.director_script.source_reference_revision),
                "production_baseline_revision": (
                    document.director_script.production_baseline_revision
                ),
                "production_baseline_scenes": (
                    None
                    if document.director_script.production_baseline_scenes is None
                    else [
                        _serialize_scene(scene, asset_by_id)
                        for scene in document.director_script.production_baseline_scenes
                    ]
                ),
                "scenes": [
                    _serialize_scene(
                        scene,
                        asset_by_id,
                        animatic=_scene_animatic_state(document, scene.id, service),
                        scene_final=_scene_final_state(document, scene.id, service),
                    )
                    for scene in document.director_script.scenes
                ],
            }
        ),
        "dialogue_plan": (
            None
            if document.dialogue_plan is None
            else {
                "source_script_revision": document.dialogue_plan.source_script_revision,
                "items": [
                    {
                        "dialogue_line_id": item.dialogue_line_id,
                        "seed": item.seed,
                        "recipe_params": item.recipe_params.to_json(),
                        "selected_audio_asset_id": item.selected_audio_asset_id,
                        "start_seconds": item.start_seconds,
                    }
                    for item in document.dialogue_plan.items
                ],
            }
        ),
        "production_availability": _production_availability(document),
        "location_library": location_library_projection(document, service),
        "keyframe_plan": (
            None
            if document.keyframe_plan is None
            else {
                "source_script_revision": document.keyframe_plan.source_script_revision,
                "keyframes": [
                    {
                        "id": item.id,
                        "owner_segment_id": item.owner_segment_id,
                        "predecessor_keyframe_id": item.predecessor_keyframe_id,
                        "prompt_text": item.prompt_text,
                        "visible_character_ids": list(item.visible_character_ids),
                        "character_references": serialize_character_references(item),
                        "selected_asset_id": item.selected_asset_id,
                        "environment_mode": item.environment_mode.value,
                        "environment_view_id": item.environment_view_id,
                        "environment_none_reason": item.environment_none_reason,
                    }
                    for item in document.keyframe_plan.keyframes
                ],
                "segments": [
                    {
                        "segment_id": item.segment_id,
                        "start_keyframe_id": item.start_keyframe_id,
                        "end_keyframe_id": item.end_keyframe_id,
                        "start_enabled": item.start_enabled,
                        "end_enabled": item.end_enabled,
                        "reference_asset_ids": list(item.reference_asset_ids),
                        "start_frame_extraction": _start_frame_extraction_projection(
                            document, item.start_keyframe_id
                        ),
                    }
                    for item in document.keyframe_plan.segments
                ],
            }
        ),
        "video_plan": (
            None
            if document.video_plan is None
            else {
                "source_script_revision": document.video_plan.source_script_revision,
                "segments": [
                    {
                        "segment_id": item.segment_id,
                        "prompt_text": item.prompt_text,
                        "active_recipe": item.active_recipe,
                        "recipes": item.recipes.to_json(),
                        "recipe_state": video_recipe_state(
                            document, item, service.provider_catalog, provider_recipes
                        ),
                        "selected_asset_id": item.selected_asset_id,
                        "upscaled_asset_id": item.upscaled_asset_id,
                    }
                    for item in document.video_plan.segments
                ],
            }
        ),
        "final_assembly": (
            None
            if document.final_assembly is None
            else {
                "source_script_revision": document.final_assembly.source_script_revision,
                "clips": [
                    {
                        "scene_id": item.scene_id,
                        "zh_asset_id": item.zh_asset_id,
                        "en_asset_id": item.en_asset_id,
                        "transition_from_previous": (
                            None
                            if item.transition_from_previous is None
                            else item.transition_from_previous.value
                        ),
                    }
                    for item in document.final_assembly.clips
                ],
                "selected_zh_asset_id": document.final_assembly.selected_zh_asset_id,
                "selected_en_asset_id": document.final_assembly.selected_en_asset_id,
            }
        ),
        "final_approval": (
            None
            if document.final_approval is None
            else {
                "zh_asset_id": document.final_approval.zh_asset_id,
                "zh_generation_id": document.final_approval.zh_generation_id,
                "en_asset_id": document.final_approval.en_asset_id,
                "en_generation_id": document.final_approval.en_generation_id,
                "source_script_revision": document.final_approval.source_script_revision,
                "approved_project_revision": (document.final_approval.approved_project_revision),
            }
        ),
    }


def human_allowed_actions(document: StructuredDirectorDocument) -> tuple[str, ...]:
    """Web 与 human handoff 共用的人类动作；专业规划由外部 Agent 经 proposal 工具发起。"""
    return _allowed_actions(document)
