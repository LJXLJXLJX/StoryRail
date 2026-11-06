"""store/domains/keyframe：keyframe 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from core.director_commands import (
    CommandReceipt,
    KeyframeCandidateSelection,
    KeyframeOperation,
    SetKeyframeActivation,
    ShareKeyframeBoundary,
    SplitKeyframeBoundary,
    UpdateKeyframeFields,
    parse_keyframe_operations,
)
from core.director_proposals import (
    KeyframeOperationsProposal,
    KeyframePlanProposal,
)
from core.director_proposals.keyframe_codec import (
    KeyframePlanSlot,
    compile_plan_operations,
)
from core.structured_director.errors import RevisionConflictError as RevisionConflictError
from core.structured_director.keyframe_mutations import (
    _apply_keyframe_operations as _apply_keyframe_operations,
)
from core.structured_director.keyframe_mutations import (
    _KeyframeMutationOperation,
    _validate_planned_shared_boundaries,
)
from core.structured_director.manual_commands import (
    keyframe_activation_command,
    keyframe_edit_command,
    keyframe_references_command,
)
from core.structured_director.models import (
    DirectorRunKind,
    DirectorRunStatus,
    Keyframe,
    KeyframePlan,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    SegmentKeyframes,
    SegmentVideo,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    VideoPlan,
    blank_keyframe,
)
from core.structured_director.reference_image_mutations import (
    reference_image_slot,
    save_reference_image_plan,
)
from core.structured_director.run_state import _active_run_is as _active_run_is
from core.structured_director.run_state import _start_director_run as _start_director_run
from core.structured_director.script_mutations import _finish_director_run as _finish_director_run
from core.structured_director.store import _keyframe_is_enabled as _keyframe_is_enabled
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation

from ...script_index import (
    scene_segments,
    segment_continues_previous,
    segment_visible_character_ids,
)


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


def _keyframe_planning_context(
    document: StructuredDirectorDocument,
    *,
    target_segment_ids: tuple[str, ...],
    missing_message: str,
    invalid_scope_message: str,
):
    script = document.director_script
    plan = document.keyframe_plan
    if (
        not _active_run_is(document, DirectorRunKind.KEYFRAME_PLAN)
        or script is None
        or script.production_baseline_revision is None
        or script.production_baseline_scenes is None
        or plan is None
    ):
        raise ValueError(missing_message)
    baseline_segments = {
        segment.id for scene in script.production_baseline_scenes for segment in scene.segments
    }
    if (
        len(target_segment_ids) != len(set(target_segment_ids))
        or not set(target_segment_ids) <= baseline_segments
    ):
        raise ValueError(invalid_scope_message)
    planning_scene_ids = {
        scene.id
        for scene in script.production_baseline_scenes
        if any(segment.id in target_segment_ids for segment in scene.segments)
    }
    planning_scenes = tuple(
        scene
        for scene in script.production_baseline_scenes
        if not target_segment_ids or scene.id in planning_scene_ids
    )
    allowed_segment_ids = {
        segment.id
        for scene in script.production_baseline_scenes
        for segment in scene.segments
        if not target_segment_ids or segment.id in target_segment_ids
    }
    protected_keyframe_ids = {
        item.id for item in plan.keyframes if item.selected_asset_id is not None
    } | {
        item.target_id
        for item in document.generations
        if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
        and item.phase is ReferenceGenerationPhase.SUCCEEDED
        and item.output_asset_id is not None
        and not item.dismissed
    }
    locked_segment_ids = {
        item.segment_id
        for item in plan.segments
        if item.start_keyframe_id in protected_keyframe_ids
        or item.end_keyframe_id in protected_keyframe_ids
    }
    return (
        script,
        plan,
        planning_scenes,
        allowed_segment_ids,
        protected_keyframe_ids,
        locked_segment_ids,
    )


def _translate_keyframe_plan_to_operations(
    document: StructuredDirectorDocument,
    proposal: KeyframePlanProposal,
    *,
    target_segment_ids: tuple[str, ...],
) -> tuple[_KeyframeMutationOperation, ...]:
    """Translate the whole-plan Segment proposal to the canonical operation list."""
    (
        _script,
        plan,
        planning_scenes,
        allowed_segment_ids,
        _protected_keyframe_ids,
        locked_segment_ids,
    ) = _keyframe_planning_context(
        document,
        target_segment_ids=target_segment_ids,
        missing_message="当前没有等待保存的关键帧计划。",
        invalid_scope_message="关键帧规划包含不存在或重复的目标 Segment。",
    )
    expected_segments = [
        segment
        for scene in planning_scenes
        for segment in scene.segments
        if segment.id in allowed_segment_ids
    ]
    if [item.segment_id for item in proposal.segments] != [
        segment.id for segment in expected_segments
    ]:
        raise ValueError("关键帧计划必须完整对应生产基线 Segment。")
    proposal_by_id = {item.segment_id: item for item in proposal.segments}
    bindings = {item.segment_id: item for item in plan.segments}
    for scene in planning_scenes:
        for index, segment in enumerate(scene.segments):
            planned = proposal_by_id.get(segment.id)
            if planned is None:
                continue
            allowed_character_ids = set(segment_visible_character_ids(scene, segment.id))
            if planned.continues_from_previous:
                if index == 0:
                    raise ValueError("Scene 首个 Segment 不能承接上一 Segment。")
            elif not set(planned.start_visible_character_ids) <= allowed_character_ids:
                raise ValueError("关键帧可见角色必须属于所属 Segment。")
            next_segment = scene.segments[index + 1] if index + 1 < len(scene.segments) else None
            boundary_character_ids = set(allowed_character_ids)
            if next_segment is not None:
                next_planned = (
                    proposal_by_id.get(next_segment.id)
                    if next_segment.id in allowed_segment_ids
                    else None
                )
                if (next_planned is not None and next_planned.continues_from_previous) or (
                    next_planned is None
                    and bindings[next_segment.id].start_keyframe_id
                    == bindings[segment.id].end_keyframe_id
                ):
                    boundary_character_ids.update(
                        segment_visible_character_ids(scene, next_segment.id)
                    )
            if not set(planned.end_visible_character_ids) <= boundary_character_ids:
                raise ValueError(
                    "Keyframe 可见角色必须属于所属 Segment；跨 Segment 共享边界允许两侧角色并集。"
                )
    scene_slots = tuple(
        tuple(
            KeyframePlanSlot(
                segment.id,
                bindings[segment.id].start_keyframe_id,
                bindings[segment.id].end_keyframe_id,
                segment.id in allowed_segment_ids,
                segment.id in locked_segment_ids,
                segment_continues_previous(scene, segment.id),
            )
            for segment in scene.segments
        )
        for scene in planning_scenes
    )
    operations = compile_plan_operations(proposal, scene_slots)
    if operations is None:
        raise ValueError("当前 Keyframe 槽位缺失，不能重新分配替代恢复。")
    return operations


def _validate_keyframe_planner_operations(
    document: StructuredDirectorDocument,
    operations: tuple[_KeyframeMutationOperation, ...],
    *,
    allowed_segment_ids: set[str],
    protected_keyframe_ids: set[str],
    locked_segment_ids: set[str],
) -> None:
    assert document.keyframe_plan is not None
    bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
    keyframe_segments: dict[str, set[str]] = {}
    for item in document.keyframe_plan.segments:
        keyframe_segments.setdefault(item.start_keyframe_id, set()).add(item.segment_id)
        keyframe_segments.setdefault(item.end_keyframe_id, set()).add(item.segment_id)
    for operation in operations:
        if isinstance(operation, SetKeyframeActivation):
            if operation.segment_id not in allowed_segment_ids:
                raise ValueError("Keyframe Planner operation 超出目标 Segment 范围。")
            affected_segments = {operation.segment_id}
            affected_keyframes: set[str] = set()
        elif isinstance(operation, UpdateKeyframeFields):
            affected_segments = keyframe_segments.get(operation.keyframe_id, set())
            affected_keyframes = {operation.keyframe_id}
            if not affected_segments or not affected_segments <= allowed_segment_ids:
                raise ValueError("Keyframe Planner 字段修改超出目标 Segment 范围。")
        elif isinstance(operation, (ShareKeyframeBoundary, SplitKeyframeBoundary)):
            affected_segments = {
                operation.left_segment_id,
                operation.right_segment_id,
            }
            if not affected_segments <= allowed_segment_ids or not affected_segments <= set(
                bindings
            ):
                raise ValueError("Keyframe Planner 边界修改超出目标 Segment 范围。")
            affected_keyframes = {
                keyframe_id
                for segment_id in affected_segments
                for keyframe_id in (
                    bindings[segment_id].start_keyframe_id,
                    bindings[segment_id].end_keyframe_id,
                )
            }
        else:
            raise ValueError("Keyframe Planner 只能提交字段、激活和边界 operations。")
        if affected_segments & locked_segment_ids or affected_keyframes & protected_keyframe_ids:
            raise ValueError("Keyframe Planner 不能修改已有成功候选或已选图片的锁定节点。")


def _finish_keyframe_operation_plan(
    document: StructuredDirectorDocument,
    operations: tuple[_KeyframeMutationOperation, ...],
    *,
    required_shared_boundaries: tuple[tuple[str, str], ...],
) -> StructuredDirectorDocument:
    result = _apply_keyframe_operations(document, operations)
    updated = (
        replace(document, revision=document.revision + 1)
        if result.document == document
        else result.document
    )
    updated = replace(
        updated,
        director_runs=_finish_director_run(document, DirectorRunKind.KEYFRAME_PLAN),
    )
    assert updated.keyframe_plan is not None
    _validate_planned_shared_boundaries(updated.keyframe_plan, required_shared_boundaries)
    return updated


def _selection_asset_id(
    document: StructuredDirectorDocument,
    keyframe_id: str,
    selection: KeyframeCandidateSelection,
) -> str:
    """把 Agent 给出的来源解析为 Asset ID：本帧候选、另一帧当前选中图或项目图片。"""
    if selection.generation_id is not None:
        generation = next(
            (item for item in document.generations if item.id == selection.generation_id),
            None,
        )
        if (
            generation is None
            or generation.kind
            not in {ReferenceGenerationKind.KEYFRAME_IMAGE, ReferenceGenerationKind.VIDEO_FRAME}
            or generation.target_id != keyframe_id
        ):
            raise ValueError("该 Generation 不是这个 Keyframe 的候选。")
        if (
            generation.phase is not ReferenceGenerationPhase.SUCCEEDED
            or generation.dismissed
            or generation.output_asset_id is None
        ):
            raise ValueError("只能采用成功、未隐藏且产出图片的 Keyframe 候选。")
        return generation.output_asset_id
    if selection.source_keyframe_id is not None:
        keyframes = () if document.keyframe_plan is None else document.keyframe_plan.keyframes
        source = next((item for item in keyframes if item.id == selection.source_keyframe_id), None)
        if source is None:
            raise ValueError("来源 Keyframe 不存在。")
        if source.selected_asset_id is None:
            raise ValueError("来源 Keyframe 尚未选定图片。")
        return source.selected_asset_id
    assert selection.asset_id is not None
    return selection.asset_id


class KeyframeDomain(_DomainBase):
    def begin_keyframe_plan(
        self,
        *,
        expected_revision: int,
        target_ids: tuple[str, ...] = (),
        user_message: str = "",
    ) -> tuple[StructuredDirectorDocument, bool]:
        aux_cell: dict[str, bool] = {}

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再准备关键帧。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if active is not None:
                if active.kind is not DirectorRunKind.KEYFRAME_PLAN:
                    raise ValueError("另一个 Director Agent 任务正在执行。")
                aux_cell["already_active"] = True
                return MutationResult(document, None, write=False)
            script = document.director_script
            from_visual_production = (
                document.is_reviewing and document.workspace_layers.videos_unlocked
            )
            if (
                not from_visual_production
                or script is None
                or script.production_baseline_revision != script.revision
                or script.production_baseline_scenes is None
            ):
                raise ValueError("请先确认当前导演脚本。")
            raw_user_request = user_message.strip() or "规划关键帧"
            started = _start_director_run(
                document,
                DirectorRunKind.KEYFRAME_PLAN,
                goal=raw_user_request,
                raw_user_request=raw_user_request,
                pending_target_ids=target_ids,
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                workspace_layers=replace(
                    document.workspace_layers,
                    keyframes_unlocked=True,
                ),
                director_runs=started.runs,
                director_directives=started.directives,
            )
            aux_cell["already_active"] = False
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated, aux_cell["already_active"]

    def finish_keyframe_plan_without_changes(self) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if not _active_run_is(document, DirectorRunKind.KEYFRAME_PLAN):
                raise ValueError("当前没有等待放弃的关键帧规划。")
            updated = replace(
                document,
                revision=document.revision + 1,
                director_runs=_finish_director_run(document, DirectorRunKind.KEYFRAME_PLAN),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def unlock_visual_production(
        self,
        segments: tuple[SegmentVideo, ...],
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再解锁视觉生产。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated = _unlock(document, segments)
            return MutationResult(updated, None)

        def _unlock(
            document: StructuredDirectorDocument, segments: tuple[SegmentVideo, ...]
        ) -> StructuredDirectorDocument:
            script = document.director_script
            if (
                not document.is_reviewing
                or script is None
                or (
                    script.production_baseline_revision != script.revision
                    or script.production_baseline_scenes is None
                )
            ):
                raise ValueError("请先确认当前导演脚本。")

            keyframes: list[Keyframe] = []
            bindings: list[SegmentKeyframes] = []
            # 每个 Segment 都有独立首尾 Keyframe；是否共享边界由用户或 Director 显式决定。
            for scene in script.production_baseline_scenes:
                for segment in scene_segments(scene):
                    start_keyframe_id = uuid4().hex
                    end_keyframe_id = uuid4().hex
                    keyframes.extend(
                        (
                            blank_keyframe(start_keyframe_id, segment.id, None),
                            blank_keyframe(end_keyframe_id, segment.id, start_keyframe_id),
                        )
                    )
                    bindings.append(
                        SegmentKeyframes(
                            segment_id=segment.id,
                            start_keyframe_id=start_keyframe_id,
                            end_keyframe_id=end_keyframe_id,
                        )
                    )

            plan = KeyframePlan(
                source_script_revision=script.production_baseline_revision,
                keyframes=tuple(keyframes),
                segments=tuple(bindings),
            )
            expected_ids = {
                segment.id for scene in script.scenes for segment in scene_segments(scene)
            }
            if {item.segment_id for item in segments} != expected_ids:
                raise ValueError("视频计划必须完整对应当前 Segment。")
            return replace(
                document,
                revision=document.revision + 1,
                status=(
                    document.review_status
                    if document.workspace_layers.final_assembly_unlocked
                    else StructuredDirectorStatus.REVIEWING_VIDEOS
                ),
                workspace_layers=replace(
                    document.workspace_layers,
                    keyframes_unlocked=True,
                    videos_unlocked=True,
                ),
                keyframe_plan=plan,
                video_plan=VideoPlan(script.revision, segments),
            )

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def save_keyframe(
        self,
        keyframe: Keyframe,
        *,
        expected_revision: int,
        segment_id: str | None = None,
        reference_asset_ids: tuple[str, ...] | None = None,
    ) -> StructuredDirectorDocument:
        document = self._editable_document(expected_revision)
        command = keyframe_edit_command(
            document,
            keyframe,
            expected_revision=document.revision,
            segment_id=segment_id,
            reference_asset_ids=reference_asset_ids,
        )
        return self.apply_keyframe_operations(
            parse_keyframe_operations(command.arguments["operations"]),
            expected_revision=document.revision,
            command_id=command.idempotency_key,
        )[0]

    def apply_keyframe_operations(
        self,
        operations: tuple[KeyframeOperation, ...],
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        """原子应用细粒度 Keyframe 操作；整个事务只产生一次 project revision。"""

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if not operations:
                raise ValueError("Keyframe operations 不能为空。")
            result = _apply_keyframe_operations(document, operations)
            if result.document == document:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id=command_id,
                        status="noop",
                        old_revision=document.revision,
                        new_revision=document.revision,
                        decision_summary=result.decision_summary,
                        applied_summary=result.applied_summary,
                        next_allowed_actions=("keyframe.generate",),
                    ),
                    write=False,
                )
            return MutationResult(
                result.document,
                CommandReceipt(
                    command_id=command_id,
                    status="succeeded",
                    old_revision=document.revision,
                    new_revision=result.document.revision,
                    changed_ids=tuple(sorted(result.changed_ids)),
                    invalidated=tuple(sorted(result.invalidated)),
                    preserved=tuple(sorted(result.preserved)),
                    decision_summary=result.decision_summary,
                    applied_summary=result.applied_summary,
                    next_allowed_actions=("keyframe.generate",),
                ),
            )

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def apply_keyframe_operation_plan(
        self,
        proposal: KeyframeOperationsProposal,
        *,
        target_segment_ids: tuple[str, ...] = (),
        required_shared_boundaries: tuple[tuple[str, str], ...] = (),
        reference_image_updates: tuple = (),
    ) -> StructuredDirectorDocument:
        """在规划锁内校验并应用 compiler operations，然后一次性回到审核态。"""

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            (
                _script,
                _plan,
                _planning_scenes,
                allowed_segment_ids,
                protected_keyframe_ids,
                locked_segment_ids,
            ) = _keyframe_planning_context(
                document,
                target_segment_ids=target_segment_ids,
                missing_message="当前没有等待保存的关键帧 operations。",
                invalid_scope_message="关键帧 operations 包含不存在或重复的目标 Segment。",
            )
            _validate_keyframe_planner_operations(
                document,
                proposal.operations,
                allowed_segment_ids=allowed_segment_ids,
                protected_keyframe_ids=protected_keyframe_ids,
                locked_segment_ids=locked_segment_ids,
            )
            updated = _finish_keyframe_operation_plan(
                document, proposal.operations, required_shared_boundaries=required_shared_boundaries
            )
            for update in reference_image_updates:
                if update.segment_id not in allowed_segment_ids:
                    raise ValueError("其他图片规划越出授权 Segment。")
                video = next(
                    item
                    for item in updated.video_plan.segments
                    if item.segment_id == update.segment_id
                )
                updated = save_reference_image_plan(
                    updated,
                    update,
                    reference_image_slot(self._provider_catalog, video),
                    planning=True,
                )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def apply_keyframe_plan(
        self,
        proposal: KeyframePlanProposal,
        *,
        target_segment_ids: tuple[str, ...] = (),
        required_shared_boundaries: tuple[tuple[str, str], ...] = (),
    ) -> StructuredDirectorDocument:

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            operations = _translate_keyframe_plan_to_operations(
                document,
                proposal,
                target_segment_ids=target_segment_ids,
            )
            return MutationResult(
                _finish_keyframe_operation_plan(
                    document,
                    operations,
                    required_shared_boundaries=required_shared_boundaries,
                ),
                None,
            )

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def save_segment_keyframe_references(
        self,
        *,
        segment_id: str,
        asset_ids: tuple[str, ...],
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        command = keyframe_references_command(
            segment_id=segment_id,
            asset_ids=asset_ids,
            expected_revision=expected_revision,
        )
        return self.apply_keyframe_operations(
            parse_keyframe_operations(command.arguments["operations"]),
            expected_revision=expected_revision,
            command_id=command.idempotency_key,
        )[0]

    def save_segment_keyframe_activation(
        self,
        *,
        segment_id: str,
        start_enabled: bool,
        end_enabled: bool,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        command = keyframe_activation_command(
            segment_id=segment_id,
            start_enabled=start_enabled,
            end_enabled=end_enabled,
            expected_revision=expected_revision,
        )
        return self.apply_keyframe_operations(
            parse_keyframe_operations(command.arguments["operations"]),
            expected_revision=expected_revision,
            command_id=command.idempotency_key,
        )[0]

    def select_keyframe_asset(
        self, *, keyframe_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan = document.keyframe_plan
            if plan is None:
                raise ValueError("关键帧计划尚未建立。")
            asset = next((item for item in document.assets if item.id == asset_id), None)
            if asset is None or not asset.media_type.startswith("image/"):
                raise ValueError("关键帧只能选择项目内的图片 Asset。")
            if not _keyframe_is_enabled(plan, keyframe_id):
                raise ValueError("该 Keyframe 未激活，不能选择候选。")
            found = False
            keyframes = []
            for item in plan.keyframes:
                if item.id == keyframe_id:
                    item = replace(item, selected_asset_id=asset_id)
                    found = True
                keyframes.append(item)
            if not found:
                raise ValueError("Keyframe 不存在。")
            updated = replace(
                document,
                revision=document.revision + 1,
                keyframe_plan=replace(plan, keyframes=tuple(keyframes)),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def select_keyframe_candidate(
        self,
        selection: KeyframeCandidateSelection,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        """Agent 为 Keyframe 选定图片；与人类选择同一字段，任一方随时可以改选。

        来源可以是本帧候选、另一 Keyframe 当前选中图（原样复用）或任一项目图片。
        """

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan = document.keyframe_plan
            if plan is None:
                raise ValueError("关键帧计划尚未建立。")
            keyframe = next(
                (item for item in plan.keyframes if item.id == selection.keyframe_id), None
            )
            if keyframe is None:
                raise ValueError("Keyframe 不存在。")
            if not _keyframe_is_enabled(plan, keyframe.id):
                raise ValueError("该 Keyframe 未激活，不能选择候选。")
            asset_id = _selection_asset_id(document, keyframe.id, selection)
            asset = next((item for item in document.assets if item.id == asset_id), None)
            if asset is None or not asset.media_type.startswith("image/"):
                raise ValueError("关键帧只能选择项目内的图片 Asset。")
            if keyframe.selected_asset_id == asset.id:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id=command_id,
                        status="noop",
                        old_revision=document.revision,
                        new_revision=document.revision,
                        preserved=("keyframe_selection",),
                        decision_summary="该图片已经是当前选择。",
                    ),
                    write=False,
                )
            updated = replace(
                document,
                revision=document.revision + 1,
                keyframe_plan=replace(
                    plan,
                    keyframes=tuple(
                        replace(item, selected_asset_id=asset.id)
                        if item.id == keyframe.id
                        else item
                        for item in plan.keyframes
                    ),
                ),
            )
            return MutationResult(
                updated,
                CommandReceipt(
                    command_id=command_id,
                    status="succeeded",
                    old_revision=document.revision,
                    new_revision=updated.revision,
                    changed_ids=(keyframe.id,),
                    preserved=("asset_history", "generation_history"),
                    decision_summary="已为该 Keyframe 选定图片；人类可随时改选。",
                    next_allowed_actions=(
                        "keyframe.generate",
                        "keyframe.continue_batch",
                        "video.generate",
                    ),
                ),
            )

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def scope_keyframe_generation(
        self, target_ids: tuple[str, ...], *, expected_revision: int
    ) -> StructuredDirectorDocument:
        """Persist the exact batch before submission, using existing run authorization."""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已更新，请重新确认关键帧批次。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if (
                active is None
                or active.kind is not DirectorRunKind.DIRECTOR
                or active.status is not DirectorRunStatus.RUNNING
            ):
                raise ValueError("关键帧批次缺少 running Director run。")
            plan = document.keyframe_plan
            known = (
                set()
                if plan is None
                else {
                    frame_id
                    for item in plan.segments
                    for enabled, frame_id in (
                        (item.start_enabled, item.start_keyframe_id),
                        (item.end_enabled, item.end_keyframe_id),
                    )
                    if enabled
                }
            )
            if (
                not target_ids
                or len(set(target_ids)) != len(target_ids)
                or not set(target_ids) <= known
            ):
                raise ValueError("关键帧批次必须是明确且不重复的已启用 Keyframe。")
            scopes = tuple(f"keyframe:{item}" for item in target_ids)
            updated_run = replace(
                active,
                authorization=replace(active.authorization, generation_scopes=scopes),
                last_project_revision=document.revision + 1,
                updated_at=datetime.now(UTC).isoformat(),
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                director_runs=tuple(
                    updated_run if item.id == active.id else item for item in document.director_runs
                ),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated
