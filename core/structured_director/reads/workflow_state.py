"""主流程的同源只读投影与 mutation 前置条件，不持久化第二份状态。"""

from ..assembly_timeline import _build_final_assembly_plan, _scenes_missing_final
from ..candidate_eligibility import reviewable_generations
from ..dialogue_timing import actual_dialogue_timing
from ..keyframe_requests import _active_keyframe_ids
from ..models import (
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    unresolved_uncertain_ids,
)
from ..models import (
    StructuredDirectorStatus as Status,
)
from ..narration_timing import conform_production_scenes, conform_scene_narration
from ..script_index import shot_segments
from .batch_observation import batch_observations
from .dependencies import _dependency
from .proposal_observation import proposal_observation
from .video_recipes import keyframe_video_context

_ACTIVE_GENERATION_PHASES = frozenset({"submitting", "queued", "running"})


class StagePrerequisiteError(ValueError):
    def __init__(self, document, reason):
        self.workflow = workflow_state(document)
        self.reason = reason
        super().__init__(
            "当前阶段前置条件未满足，请按主流程完成引用 proposal、人工审核或脚本准备。"
        )


def workflow_state(document, *, provider_catalog=None):
    status = document.status
    script = document.director_script
    run = document.active_director_run
    active_task = None
    if run is not None:
        active_task = proposal_observation(document, run)
        if active_task is not None:
            stage = active_task["proposal_kind"]
            phase = active_task["phase"]
            required = [active_task["actions"][0]]
            return _workflow_result(
                document,
                stage,
                phase,
                required,
                active_task=active_task,
            )
        stage, phase = "execution", "in_progress"
        required = [
            _action(
                "run.get_status",
                tool="read_run",
                target_ids=run.cursor.pending_target_ids,
                run_id=run.id,
            )
        ]
        return _workflow_result(document, stage, phase, required, active_task={"run_id": run.id})

    if status is Status.APPROVED:
        return _workflow_result(document, "final", "approved", [])
    if status is Status.AWAITING_PROPOSAL:
        return _workflow_result(
            document,
            "reference_library",
            "awaiting_proposal",
            [
                _action(
                    "reference.request_proposal",
                    tool="reference_proposal",
                    tool_action="request",
                )
            ],
        )
    if not references_reviewed(document):
        return _workflow_result(
            document,
            "reference_library",
            "awaiting_human_review",
            [_human_action(document, "reference.confirm_review")],
        )
    if script is None:
        return _workflow_result(
            document,
            "script",
            "awaiting_proposal",
            [
                _action(
                    "script.request_proposal",
                    tool="script_proposal",
                    tool_action="request",
                )
            ],
        )
    if not document.workspace_layers.narration_unlocked:
        return _workflow_result(
            document,
            "script",
            "awaiting_human_review",
            [_human_action(document, "script.confirm")],
        )
    if script.production_baseline_revision != script.revision:
        return _narration_workflow(document)
    if not document.workspace_layers.videos_unlocked:
        dialogue = _dialogue_workflow(document)
        if dialogue is not None:
            stage, phase, required = dialogue
            return _workflow_result(document, stage, phase, required)
        return _workflow_result(
            document,
            "visual_production",
            "awaiting_unlock",
            [
                _action(
                    "visual_production.unlock",
                    tool="unlock_production",
                    tool_action="unlock_visual_production",
                )
            ],
        )

    keyframe = _keyframe_workflow(document, provider_catalog=provider_catalog)
    if keyframe is not None:
        stage, phase, required = keyframe
        active_batches = [
            item
            for item in batch_observations(document)
            if item["batch_kind"] == "keyframe"
            and not item["is_terminal"]
            and set(item["target_ids"]) & set(_action_targets(required))
        ]
        if active_batches:
            active_task = {"task_type": "keyframe_batch", **active_batches[-1]}
            if active_task["phase"] == "awaiting_explicit_continue":
                required = [item for item in required if item["action"] != "keyframe.generate"]
                required.insert(
                    0,
                    _action(
                        "keyframe.continue_batch",
                        tool="media_batch",
                        tool_action="continue",
                        kind="keyframe",
                        target_ids=active_task["target_ids"],
                        batch_id=active_task["batch_id"],
                    ),
                )
            phase = active_task["phase"]
        return _workflow_result(document, stage, phase, required, active_task=active_task)
    dialogue = _dialogue_workflow(document)
    if dialogue is not None:
        stage, phase, required = dialogue
        return _workflow_result(document, stage, phase, required)
    video = _video_workflow(document, provider_catalog=provider_catalog)
    if video is not None:
        stage, phase, required = video
        return _workflow_result(document, stage, phase, required)
    return _final_workflow(document)


def _workflow_result(document, stage, phase, required, *, active_task=None):
    blocked = {}
    if document.director_script is None:
        for prefix in (
            "keyframe",
            "video",
            "narration",
            "dialogue",
            "final",
            "animatic",
        ):
            blocked[prefix] = {"reason": "reference_review_or_script_required"}
    if document.director_script is None and not references_reviewed(document):
        blocked["script"] = {"reason": "reference_review_required"}
    return {
        "current_stage": stage,
        "stage_status": phase,
        "semantics": {
            "current_stage": "primary_workflow_focus_not_capability_lock",
            "active_task": "primary_workflow_task_only_parallel_activity_uses_task_discovery",
            "required_next_actions": "primary_workflow_actions_only",
        },
        "required_next_actions": required,
        # 可选建议（地点规划/成套生成）；永不进入 required，也不改变 allowed_actions。
        "recommended_next_actions": _location_recommendations(document),
        "blocking_prerequisites": sorted({v["reason"] for v in blocked.values()}),
        "blocked_actions": blocked,
        "workspace_capabilities": _workspace_capabilities(document),
        "activity_summary": _activity_summary(document),
        "requires_explicit_user_request": True,
        "active_task": active_task,
    }


def location_binding_gaps(document):
    """返回尚未建立语义地点关系的 Scene IDs；Shot 不持有地点事实。"""
    script = document.director_script
    if script is None:
        return ()
    return tuple(scene.id for scene in script.scenes if scene.location_id is None)


def _location_recommendations(document):
    """地点相关的可选建议：规划、成套生成、批次显式继续。

    只在生产基线已建立、引用库已确认且没有活跃 run 时出现。存在等待显式继续的地点
    批次时只提示继续；批次仍在推进或等待人类选择/标定时不再推荐新的成套生成。
    地点批次的继续提示只认 batch_kind == "location"，不会与 Keyframe 批次混淆。
    视觉生产解锁后不再推荐规划与成套生成（解锁本身就是跳过），只保留在途批次的
    继续提示。规划推荐只给缺口数量，完整 ID 列表见 visual_production.unlock 的
    location_advisory。
    """
    script = document.director_script
    if (
        script is None
        or not references_reviewed(document)
        or script.production_baseline_revision != script.revision
        or document.active_director_run is not None
    ):
        return []
    location_batches = [
        item
        for item in batch_observations(document)
        if item["batch_kind"] == "location" and not item["is_terminal"]
    ]
    pending_continue = next(
        (
            item
            for item in reversed(location_batches)
            if item["phase"] == "awaiting_explicit_continue"
        ),
        None,
    )
    if pending_continue is not None:
        return [
            _action(
                "location.continue_set",
                tool="media_batch",
                tool_action="continue",
                kind="location",
                target_ids=pending_continue["target_ids"],
                batch_id=pending_continue["batch_id"],
                message=(
                    "地点成套批次里已有条件满足的项可以提交；用户明确要求后继续该批次，"
                    "回调不会自动推进。此为可选建议，不阻塞当前流程。"
                ),
            )
        ]
    if document.workspace_layers.videos_unlocked:
        return []
    actions = []
    scenes_without_location = location_binding_gaps(document)
    if scenes_without_location:
        actions.append(
            _action(
                "location.request_proposal",
                tool="submit_proposal",
                tool_action="request",
                capability="location",
                unbound_scene_count=len(scenes_without_location),
                message=(
                    f"{len(scenes_without_location)} 个 Scene 尚未绑定地点；"
                    "可让 Director 补充地点语义与地点图片，提升同场景镜头"
                    "的背景一致性。此为可选建议，不阻塞当前流程。"
                ),
            )
        )
    asset_ids = {item.id for item in document.assets}
    incomplete = tuple(
        image.id
        for location in document.location_library.locations
        for image in location.images
        if image.selected_asset_id not in asset_ids
    )
    if incomplete and not location_batches:
        actions.append(
            _action(
                "location.generate_set",
                tool="media_batch",
                tool_action="start",
                kind="location",
                target_ids=incomplete,
                message=(
                    f"{len(incomplete)} 张地点图片还没有选定图片；"
                    "用户明确要求后可成套生成。此为可选建议，不阻塞当前流程。"
                ),
            )
        )
    return actions


def _workspace_capabilities(document):
    layers = document.workspace_layers
    mapping = (
        ("narration", layers.narration_unlocked),
        ("keyframe", layers.keyframes_unlocked),
        ("video", layers.videos_unlocked),
        ("final", layers.final_assembly_unlocked),
    )
    return {
        "semantics": "cumulative_unlocked_layers_not_primary_workflow",
        "unlocked": [name for name, unlocked in mapping if unlocked],
    }


def _activity_summary(document):
    unresolved_uncertain = unresolved_uncertain_ids(document.generations)
    active_generations = [
        generation
        for generation in document.generations
        if generation.phase.value in _ACTIVE_GENERATION_PHASES
        or generation.id in unresolved_uncertain
    ]
    return {
        "active_generation_count": len(active_generations),
        "has_active_generations": bool(active_generations),
        "task_discovery_tool": "read_workflow",
        "semantics": "parallel_project_activity_not_primary_workflow",
    }


def _action(action, *, tool=None, target_ids=(), human_only=False, **details):
    return {
        "action": action,
        "tool": tool,
        "target_ids": list(target_ids),
        "human_only": human_only,
        "requires_explicit_user_request": not human_only,
        **details,
    }


def _action_targets(actions):
    return tuple(dict.fromkeys(target_id for item in actions for target_id in item["target_ids"]))


def _human_action(document, action, *, target_ids=(), **details):
    return _action(
        action,
        target_ids=target_ids,
        human_only=True,
        web_path=f"/?project={document.project_id}",
        **details,
    )


def _active_generations(document, kind, target_ids):
    targets = set(target_ids)
    return tuple(
        item
        for item in document.generations
        if item.kind is kind
        and item.target_id in targets
        and item.phase
        in {
            ReferenceGenerationPhase.SUBMITTING,
            ReferenceGenerationPhase.QUEUED,
            ReferenceGenerationPhase.RUNNING,
        }
    )


def _uncertain_generations(document, kind, target_ids):
    targets = set(target_ids)
    unresolved = unresolved_uncertain_ids(document.generations)
    return tuple(
        item
        for item in document.generations
        if item.kind is kind and item.target_id in targets and item.id in unresolved
    )


def _candidate_action(document, kind, target_ids):
    candidates = reviewable_generations(document, kind, target_ids)
    if not candidates:
        return None
    candidate_targets = tuple(dict.fromkeys(item.target_id for item in candidates))
    if kind is ReferenceGenerationKind.KEYFRAME_IMAGE:
        # Keyframe 候选 Agent 与人类都可采用；人类随时可改选。
        return _action(
            "keyframe.select_candidate",
            tool="select_keyframe_candidate",
            target_ids=candidate_targets,
            kind=kind.value,
            candidate_count=len(candidates),
            candidate_count_unit="generation_outputs",
            verification_tool="list_candidates",
        )
    return _human_action(
        document,
        "candidate_selection",
        target_ids=candidate_targets,
        kind=kind.value,
        candidate_count=len(candidates),
        candidate_count_unit="generation_outputs",
        verification_tool="list_candidates",
    )


def _generation_actions(
    document,
    kind,
    target_ids,
    *,
    generate_action,
    tool_kind,
    ready_target_ids=None,
):
    actions = []
    active = _active_generations(document, kind, target_ids)
    if active:
        actions.append(
            _action(
                "generation.wait",
                tool="manage_generation",
                tool_action="wait",
                target_ids=tuple(dict.fromkeys(item.target_id for item in active)),
                generation_ids=[item.id for item in active],
            )
        )
    uncertain = _uncertain_generations(document, kind, target_ids)
    if uncertain:
        actions.append(
            _action(
                "generation.inspect_uncertain",
                tool="read_human_handoff",
                target_ids=tuple(dict.fromkeys(item.target_id for item in uncertain)),
                generation_ids=[item.id for item in uncertain],
            )
        )
    occupied = {item.target_id for item in (*active, *uncertain)}
    ready = [
        target_id
        for target_id in (target_ids if ready_target_ids is None else ready_target_ids)
        if target_id not in occupied
    ]
    if ready:
        actions.append(
            _action(
                generate_action,
                tool="generate_media",
                tool_kind=tool_kind,
                target_ids=ready,
            )
        )
    return actions


def _narration_workflow(document):

    asset_ids = {item.id for item in document.assets if item.media_type == "audio/wav"}
    cues = tuple(cue for scene in document.director_script.scenes for cue in scene.narration_cues)
    pending = tuple(
        cue.id
        for cue in cues
        if any(track.selected_audio_asset_id not in asset_ids for _, track in cue.tracks)
    )
    if not pending:
        unplanned_scene_ids = tuple(
            scene.id for scene in document.director_script.scenes if not scene.shots
        )
        if unplanned_scene_ids:
            return _workflow_result(
                document,
                "narration",
                "awaiting_plan",
                [
                    _action(
                        "script.apply_operations",
                        tool="edit_script",
                        target_ids=unplanned_scene_ids,
                        purpose="plan_shots_from_selected_narration_timing",
                        reason="narration_shot_plan_required",
                    )
                ],
            )
        issue = production_baseline_issue(document)
        return _workflow_result(
            document,
            "narration",
            "needs_attention",
            [
                _action(
                    "script.apply_operations",
                    tool="edit_script",
                    target_ids=_timing_conflict_scene_ids(document),
                    purpose="fix_narration_timing_conflict",
                    reason="narration_timing_conflict",
                    message=issue
                    or "生产基线未随当前脚本更新；下一次脚本写入时 Core 会自动重新校准。",
                )
            ],
        )
    candidate = _candidate_action(document, ReferenceGenerationKind.NARRATION_AUDIO, pending)
    candidate_targets = set(() if candidate is None else candidate["target_ids"])
    remaining = tuple(target_id for target_id in pending if target_id not in candidate_targets)
    actions = [] if candidate is None else [candidate]
    actions.extend(
        _generation_actions(
            document,
            ReferenceGenerationKind.NARRATION_AUDIO,
            pending,
            generate_action="narration.generate",
            tool_kind="narration",
            ready_target_ids=remaining,
        )
    )
    phase = (
        "awaiting_human_review"
        if candidate is not None
        else "in_progress"
        if any(item["action"] == "generation.wait" for item in actions)
        else "needs_attention"
        if any(item["action"] == "generation.inspect_uncertain" for item in actions)
        else "ready_to_generate"
    )
    return _workflow_result(document, "narration", phase, actions)


def _dialogue_workflow(document):
    script = document.director_script
    plan = document.dialogue_plan
    lines = tuple(
        line
        for scene in (() if script is None else script.scenes)
        for segment in scene.segments
        for line in segment.dialogue_lines
    )
    if not lines:
        return None
    if plan is None:
        return (
            "dialogue",
            "inconsistency",
            [_action("dialogue.read_plan", tool="read_professional_workset")],
        )
    selected = {item.dialogue_line_id: item.selected_audio_asset_id for item in plan.items}
    pending = tuple(line.id for line in lines if selected.get(line.id) is None)
    if pending:
        candidate = _candidate_action(document, ReferenceGenerationKind.DIALOGUE_AUDIO, pending)
        candidate_targets = set(() if candidate is None else candidate["target_ids"])
        remaining = tuple(target for target in pending if target not in candidate_targets)
        actions = [] if candidate is None else [candidate]
        actions.extend(
            _generation_actions(
                document,
                ReferenceGenerationKind.DIALOGUE_AUDIO,
                pending,
                generate_action="dialogue.generate",
                tool_kind="dialogue",
                ready_target_ids=remaining,
            )
        )
        phase = (
            "awaiting_human_review"
            if candidate is not None
            else "in_progress"
            if any(item["action"] == "generation.wait" for item in actions)
            else "needs_attention"
            if any(item["action"] == "generation.inspect_uncertain" for item in actions)
            else "ready_to_generate"
        )
        return "dialogue", phase, actions
    timing_targets = tuple(
        segment.id
        for scene in script.scenes
        for segment in scene.segments
        if segment.dialogue_lines
        and not (actual_dialogue_timing(document, segment) or {}).get("ready", False)
    )
    if timing_targets:
        return (
            "dialogue",
            "awaiting_timing",
            [
                _action(
                    "dialogue.set_timing",
                    tool="set_dialogue_timing",
                    target_ids=timing_targets,
                    purpose="calibrate_video_duration_from_selected_tts",
                )
            ],
        )
    return None


def production_baseline_issue(document):
    """旁白层解锁后生产基线失效的原因；Core 每次脚本写入都会自动校准，这里只解释失败。"""
    script = document.director_script
    if (
        script is None
        or not document.workspace_layers.narration_unlocked
        or script.production_baseline_revision == script.revision
    ):
        return None
    try:
        conform_production_scenes(
            script.scenes,
            {asset.id: asset for asset in document.assets},
            narrator_ready=document.reference_library.narrator is not None,
        )
    except ValueError as exc:
        return str(exc)
    return None


def _timing_conflict_scene_ids(document):
    scenes = document.director_script.scenes
    assets = {asset.id: asset for asset in document.assets}
    blocked = []
    for scene in scenes:
        try:
            conform_scene_narration(scene, assets, scenes)
        except ValueError:
            blocked.append(scene.id)
    return blocked


def _keyframe_workflow(document, *, provider_catalog=None):

    plan = document.keyframe_plan
    script = document.director_script
    if plan is None or script is None:
        return (
            "keyframe",
            "inconsistency",
            [_action("keyframe.read_plan", tool="read_professional_workset")],
        )
    active = _active_keyframe_ids(plan)
    active_ids = tuple(item.id for item in plan.keyframes if item.id in active)
    asset_ids = {item.id for item in document.assets if item.media_type.startswith("image/")}
    frames = {item.id: item for item in plan.keyframes}
    unselected = tuple(
        target_id
        for target_id in active_ids
        if target_id not in frames or frames[target_id].selected_asset_id not in asset_ids
    )
    unplanned_segments = {
        binding.segment_id
        for binding in plan.segments
        if not binding.start_enabled
        and not binding.end_enabled
        and "none"
        not in keyframe_video_context(document, binding.segment_id, catalog=provider_catalog)[
            "frame_strategies"
        ]
    }
    unplanned_segments.update(
        frames[target_id].owner_segment_id
        for target_id in unselected
        if target_id in frames and not frames[target_id].prompt_text.strip()
    )
    if not unselected and not unplanned_segments:
        return None
    shot_ids = tuple(
        shot.id
        for scene in script.scenes
        for shot in scene.shots
        if any(segment.id in unplanned_segments for segment in shot_segments(scene, shot.id))
    )
    actions = []
    if shot_ids:
        actions.append(
            _action(
                "keyframe.request_proposal",
                tool="keyframe_proposal",
                tool_action="request",
                target_ids=shot_ids,
            )
        )
    candidate = _candidate_action(document, ReferenceGenerationKind.KEYFRAME_IMAGE, unselected)
    if candidate is not None:
        actions.append(candidate)
    candidate_targets = set(() if candidate is None else candidate["target_ids"])
    generation_targets = tuple(
        target_id
        for target_id in unselected
        if target_id in frames and frames[target_id].prompt_text.strip()
    )
    planned_targets = tuple(
        target_id for target_id in generation_targets if target_id not in candidate_targets
    )
    active_targets = {
        item.target_id
        for item in _active_generations(
            document, ReferenceGenerationKind.KEYFRAME_IMAGE, planned_targets
        )
    }
    uncertain_targets = {
        item.target_id
        for item in _uncertain_generations(
            document, ReferenceGenerationKind.KEYFRAME_IMAGE, planned_targets
        )
    }
    dependencies = [
        _dependency(document, "keyframe.generate", target_id) for target_id in planned_targets
    ]
    ready = tuple(item["target_id"] for item in dependencies if item["ready"])
    actions.extend(
        _generation_actions(
            document,
            ReferenceGenerationKind.KEYFRAME_IMAGE,
            generation_targets,
            generate_action="keyframe.generate",
            tool_kind="keyframe",
            ready_target_ids=ready,
        )
    )
    blocked = [
        item
        for item in dependencies
        if not item["ready"] and item["target_id"] not in active_targets | uncertain_targets
    ]
    if blocked:
        actions.append(
            _action(
                "keyframe.resolve_inputs",
                tool="read_professional_workset",
                target_ids=[item["target_id"] for item in blocked],
                blocking_reasons={item["target_id"]: item["reasons"] for item in blocked},
            )
        )
    phase = (
        "awaiting_human_review"
        if candidate is not None
        else "in_progress"
        if any(item["action"] == "generation.wait" for item in actions)
        else "needs_attention"
        if any(item["action"] == "generation.inspect_uncertain" for item in actions)
        else "awaiting_plan"
        if shot_ids
        else "blocked"
        if blocked and not ready
        else "ready_to_generate"
    )
    return "keyframe", phase, actions


def _video_workflow(document, *, provider_catalog=None):

    plan = document.video_plan
    if plan is None:
        return (
            "video",
            "inconsistency",
            [_action("video.read_plan", tool="read_professional_workset")],
        )
    asset_ids = {item.id for item in document.assets if item.media_type == "video/mp4"}
    pending = tuple(
        item.segment_id for item in plan.segments if item.selected_asset_id not in asset_ids
    )
    if not pending:
        return None
    actions = []
    candidate = _candidate_action(document, ReferenceGenerationKind.SEGMENT_VIDEO, pending)
    if candidate is not None:
        actions.append(candidate)
    candidate_targets = set(() if candidate is None else candidate["target_ids"])
    unresolved = tuple(target_id for target_id in pending if target_id not in candidate_targets)
    dependencies = [
        _dependency(document, "video.generate", target_id, catalog=provider_catalog)
        for target_id in unresolved
    ]
    active_targets = {
        item.target_id
        for item in _active_generations(document, ReferenceGenerationKind.SEGMENT_VIDEO, unresolved)
    }
    uncertain_targets = {
        item.target_id
        for item in _uncertain_generations(
            document, ReferenceGenerationKind.SEGMENT_VIDEO, unresolved
        )
    }
    ready = tuple(
        item["target_id"]
        for item in dependencies
        if item["ready"] and item["target_id"] not in active_targets | uncertain_targets
    )
    actions.extend(
        _generation_actions(
            document,
            ReferenceGenerationKind.SEGMENT_VIDEO,
            pending,
            generate_action="video.generate",
            tool_kind="video",
            ready_target_ids=ready,
        )
    )
    blocked = [
        item
        for item in dependencies
        if not item["ready"] and item["target_id"] not in active_targets | uncertain_targets
    ]
    missing_prompts = [
        item["target_id"]
        for item in blocked
        if any("视频提示词为空" in reason for reason in item["reasons"])
    ]
    if missing_prompts:
        actions.append(
            _action(
                "video.set_prompt",
                tool="save_video_prompt",
                target_ids=missing_prompts,
            )
        )
    other_blocked = [item for item in blocked if item["target_id"] not in missing_prompts]
    if other_blocked:
        actions.append(
            _action(
                "video.resolve_inputs",
                tool="read_professional_workset",
                target_ids=[item["target_id"] for item in other_blocked],
                blocking_reasons={item["target_id"]: item["reasons"] for item in other_blocked},
            )
        )
    phase = (
        "awaiting_human_review"
        if candidate is not None
        else "in_progress"
        if any(item["action"] == "generation.wait" for item in actions)
        else "needs_attention"
        if any(item["action"] == "generation.inspect_uncertain" for item in actions)
        else "blocked"
        if blocked and not ready
        else "ready_to_generate"
    )
    return "video", phase, actions


def _final_workflow(document):
    plan = document.final_assembly
    asset_ids = {item.id for item in document.assets if item.media_type == "video/mp4"}
    if plan is not None:
        # 项目所选语言的单语成片都已选择有效候选后，才进入一次性 Approval。
        selected = [plan.selected_asset_id(language) for language in document.narration_languages]
        valid = all(
            asset_id in asset_ids
            and any(
                item.kind is ReferenceGenerationKind.FINAL_VIDEO
                and item.language is language
                and item.phase is ReferenceGenerationPhase.SUCCEEDED
                and item.output_asset_id == asset_id
                and not item.dismissed
                for item in document.generations
            )
            for language, asset_id in zip(document.narration_languages, selected, strict=True)
        )
        if valid:
            return _workflow_result(
                document,
                "final",
                "awaiting_human_review",
                [_human_action(document, "final.approve", target_ids=selected)],
            )
    candidate = _candidate_action(
        document, ReferenceGenerationKind.FINAL_VIDEO, (document.project_id,)
    )
    if candidate is not None:
        return _workflow_result(document, "final", "awaiting_human_review", [candidate])
    active = _active_generations(
        document, ReferenceGenerationKind.FINAL_VIDEO, (document.project_id,)
    )
    if active:
        return _workflow_result(
            document,
            "final",
            "in_progress",
            [
                _action(
                    "generation.wait",
                    tool="manage_generation",
                    tool_action="wait",
                    target_ids=[document.project_id],
                    generation_ids=[item.id for item in active],
                )
            ],
        )
    try:
        _build_final_assembly_plan(document)
    except ValueError as exc:
        missing_scene_ids = _scenes_missing_final(document)
        actions = [
            _action(
                "final.assemble_scene",
                tool="assemble_media",
                tool_kind="scene",
                target_ids=[scene_id],
            )
            for scene_id in missing_scene_ids
        ]
        actions.append(
            _action(
                "final.resolve_inputs",
                tool="read_professional_workset",
                target_ids=[document.project_id],
                blocking_reasons=[str(exc)],
            )
        )
        return _workflow_result(document, "final", "blocked", actions)
    return _workflow_result(
        document,
        "final",
        "ready_to_generate",
        [
            _action(
                "final.assemble",
                tool="assemble_media",
                tool_kind="final",
                target_ids=[document.project_id],
            )
        ],
    )


def require_workflow_action(document, action):
    # 观察、取消与迟到响应清理不能被阶段门禁困住。
    if action.endswith((".get_proposal", ".cancel_proposal", ".reject_proposal")):
        return
    if action == "script.request_proposal" and not references_reviewed(document):
        raise StagePrerequisiteError(document, "reference_review_required")
    prefix = action.split(".")[0]
    if prefix in workflow_state(document)["blocked_actions"]:
        raise StagePrerequisiteError(document, "reference_review_or_script_required")
    if document.status is Status.AWAITING_PROPOSAL and prefix == "script":
        raise StagePrerequisiteError(document, "reference_proposal_required")


def reference_fingerprint(document):
    import hashlib
    import json
    from dataclasses import asdict

    return hashlib.sha256(
        json.dumps(asdict(document.reference_library), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def references_reviewed(document):
    import json

    fingerprint = reference_fingerprint(document)
    return any(
        record.operation == "reference.confirm_review"
        and record.phase == "committed"
        and record.receipt_json is not None
        and json.loads(record.receipt_json).get("data", {}).get("reference_fingerprint")
        == fingerprint
        for record in document.application_requests
    )
