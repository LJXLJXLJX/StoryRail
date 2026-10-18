"""store/domains/script：script 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.director_commands import CommandReceipt, RepairPatch, RepairReceipt, ScriptOperationsPatch
from core.director_proposals import (
    StructuredDirectorScriptProposal,
    StructuredDirectorScriptRevisionProposal,
)
from core.structured_director.errors import RevisionConflictError as RevisionConflictError
from core.structured_director.models import (
    CapabilityGapAlert,
    CapabilityGapResult,
    CapabilityGapStatus,
    DirectorRunKind,
    PendingScriptEdit,
    Scene,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
)
from core.structured_director.reads.workflow_state import (
    require_workflow_action as require_workflow_action,
)
from core.structured_director.repair_mutations import (
    _apply_repair_operations as _apply_repair_operations,
)
from core.structured_director.repair_mutations import (
    _formal_script_command_names as _formal_script_command_names,
)
from core.structured_director.repair_mutations import _repair_gap_id as _repair_gap_id
from core.structured_director.repair_mutations import (
    _repair_invalidated_items as _repair_invalidated_items,
)
from core.structured_director.repair_mutations import (
    _repair_operation_for_alert as _repair_operation_for_alert,
)
from core.structured_director.repair_mutations import (
    _repair_operation_from_alert as _repair_operation_from_alert,
)
from core.structured_director.repair_mutations import (
    _repair_operation_summary as _repair_operation_summary,
)
from core.structured_director.repair_mutations import (
    _repair_request_summary as _repair_request_summary,
)
from core.structured_director.run_state import _active_run_is as _active_run_is
from core.structured_director.run_state import _start_director_run as _start_director_run
from core.structured_director.script_mutations import (
    _apply_script_operations as _apply_script_operations,
)
from core.structured_director.script_mutations import (
    _apply_script_scene_operations as _apply_script_scene_operations,
)
from core.structured_director.script_mutations import (
    _assign_missing_dialogue_ids as _assign_missing_dialogue_ids,
)
from core.structured_director.script_mutations import _finish_director_run as _finish_director_run
from core.structured_director.script_mutations import (
    _invalidate_production_after_script_revision as _invalidate_production_after_script_revision,
)
from core.structured_director.script_mutations import _materialize_script as _materialize_script
from core.structured_director.script_mutations import (
    _materialize_script_revision as _materialize_script_revision,
)
from core.structured_director.script_mutations import (
    _validate_script_references as _validate_script_references,
)
from core.structured_director.script_mutations import (
    _with_production_baseline as _with_production_baseline,
)
from core.structured_director.script_mutations import dialogue_plan_for_script
from core.structured_director.store import (
    _validate_proposal_references as _validate_proposal_references,
)
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class ScriptDomain(_DomainBase):
    def begin_script_proposal(
        self, *, expected_revision: int, raw_user_request: str = "生成结构化导演脚本"
    ) -> tuple[StructuredDirectorDocument, bool]:
        aux_cell: dict[str, bool] = {}

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再生成脚本。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if active is not None:
                if active.kind is not DirectorRunKind.SCRIPT_PROPOSAL:
                    raise ValueError("另一个 Director Agent 任务正在执行。")
                aux_cell["already_active"] = True
                return MutationResult(document, None, write=False)
            if document.status is not StructuredDirectorStatus.REVIEWING:
                raise ValueError("当前不能生成结构化导演脚本。")
            require_workflow_action(document, "script.request_proposal")
            started = _start_director_run(
                document,
                DirectorRunKind.SCRIPT_PROPOSAL,
                goal="生成结构化导演脚本",
                raw_user_request=raw_user_request,
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                director_runs=started.runs,
                director_directives=started.directives,
            )
            aux_cell["already_active"] = False
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated, aux_cell["already_active"]

    def apply_script_proposal(
        self, proposal: StructuredDirectorScriptProposal
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if document.status is not StructuredDirectorStatus.REVIEWING or not _active_run_is(
                document, DirectorRunKind.SCRIPT_PROPOSAL
            ):
                raise ValueError("当前没有等待保存的结构化脚本 proposal。")
            _validate_proposal_references(proposal, document.reference_library)
            script = _materialize_script(
                proposal,
                source_reference_revision=document.revision - 1,
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                status=StructuredDirectorStatus.REVIEWING_SCRIPT,
                director_script=script,
                dialogue_plan=dialogue_plan_for_script(script),
                director_runs=_finish_director_run(document, DirectorRunKind.SCRIPT_PROPOSAL),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def begin_script_edit(
        self,
        message: str | None,
        *,
        expected_revision: int,
    ) -> tuple[StructuredDirectorDocument, bool]:
        aux_cell: dict[str, bool] = {}

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再请求 Agent 修改。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if active is not None:
                if active.kind is not DirectorRunKind.SCRIPT_EDIT:
                    raise ValueError("另一个 Director Agent 任务正在执行。")
                aux_cell["already_active"] = True
                return MutationResult(document, None, write=False)
            if not document.is_reviewing or document.director_script is None or message is None:
                raise ValueError("当前不能请求 Agent 修改结构化导演脚本。")
            pending = PendingScriptEdit(document.director_script.revision, message.strip())
            started = _start_director_run(
                document,
                DirectorRunKind.SCRIPT_EDIT,
                goal=message.strip(),
                raw_user_request=message.strip(),
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                pending_script_edit=pending,
                director_runs=started.runs,
                director_directives=started.directives,
            )
            aux_cell["already_active"] = False
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated, aux_cell["already_active"]

    def apply_script_revision_proposal(
        self,
        proposal: StructuredDirectorScriptRevisionProposal,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if (
                not _active_run_is(document, DirectorRunKind.SCRIPT_EDIT)
                or document.pending_script_edit is None
                or document.director_script is None
            ):
                raise ValueError("当前没有等待保存的结构化脚本 Agent 修改。")
            if proposal.scenes:
                raise ValueError("脚本 Agent 必须返回局部操作，不能返回完整脚本。")
            if proposal.operations:
                scenes = _apply_script_scene_operations(
                    proposal.operations, document.director_script.scenes
                )
            else:
                updated = replace(
                    document,
                    revision=document.revision + 1,
                    pending_script_edit=None,
                    director_runs=_finish_director_run(document, DirectorRunKind.SCRIPT_EDIT),
                )
                return MutationResult(updated, None)
            if scenes == document.director_script.scenes:
                updated = replace(
                    document,
                    revision=document.revision + 1,
                    pending_script_edit=None,
                    director_runs=_finish_director_run(document, DirectorRunKind.SCRIPT_EDIT),
                )
                return MutationResult(updated, None)
            _validate_script_references(
                scenes,
                document.reference_library,
                previous_scenes=document.director_script.scenes,
            )
            updated = _invalidate_production_after_script_revision(document, scenes)
            updated = replace(
                updated,
                director_runs=_finish_director_run(document, DirectorRunKind.SCRIPT_EDIT),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def save_director_script(
        self,
        scenes: tuple[Scene, ...],
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再保存脚本。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if not document.is_reviewing or document.director_script is None:
                raise ValueError("结构化导演脚本尚未生成。")
            normalized_scenes = _assign_missing_dialogue_ids(scenes)
            _validate_script_references(
                normalized_scenes,
                document.reference_library,
                previous_scenes=document.director_script.scenes,
            )
            script = replace(
                document.director_script,
                revision=document.director_script.revision + 1,
                scenes=normalized_scenes,
            )
            return MutationResult(
                _invalidate_production_after_script_revision(document, script.scenes), None
            )

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def save_script_revision_proposal(
        self,
        proposal: StructuredDirectorScriptRevisionProposal,
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        """保存人工编辑；新节点没有 ID，由 Core 在此分配。"""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再保存脚本。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if not document.is_reviewing or document.director_script is None:
                raise ValueError("结构化导演脚本尚未生成或 Agent 正在修改。")
            scenes = _materialize_script_revision(
                proposal.scenes,
                document.director_script.scenes,
            )
            _validate_script_references(
                scenes,
                document.reference_library,
                previous_scenes=document.director_script.scenes,
            )
            script = replace(
                document.director_script,
                revision=document.director_script.revision + 1,
                scenes=scenes,
            )
            return MutationResult(
                _invalidate_production_after_script_revision(document, script.scenes), None
            )

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def confirm_director_script(self, *, expected_revision: int) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再确认脚本。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if not document.is_reviewing or document.director_script is None:
                raise ValueError("结构化导演脚本尚未生成。")
            if document.workspace_layers.narration_unlocked:
                # 解锁后生产基线由每次脚本写入自动维护，重复确认不改动任何事实。
                return MutationResult(document, None, write=False)
            unlocked = replace(
                document,
                revision=document.revision + 1,
                status=StructuredDirectorStatus.REVIEWING_NARRATION,
                workspace_layers=replace(
                    document.workspace_layers,
                    narration_unlocked=True,
                ),
            )
            script = _with_production_baseline(unlocked, document.director_script)
            if script.scenes != document.director_script.scenes:
                # 解锁前 Narration Scene 尚无 Shot，Drama Scene 没有旁白，校准不会改写时长。
                raise ValueError("脚本时长与旁白不一致，请修改脚本后再确认。")
            return MutationResult(replace(unlocked, director_script=script), None)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def apply_production_script_operations(
        self,
        proposal: StructuredDirectorScriptRevisionProposal,
        *,
        target_scene_ids: tuple[str, ...],
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if (
                not _active_run_is(document, DirectorRunKind.DIRECTOR)
                or document.director_script is None
            ):
                raise ValueError("当前没有等待保存的生产期脚本修改。")
            if proposal.scenes:
                raise ValueError("Director 必须返回局部脚本操作，不能返回完整脚本。")
            if not proposal.operations:
                updated = replace(
                    document,
                    revision=document.revision + 1,
                    director_runs=_finish_director_run(document, DirectorRunKind.DIRECTOR),
                )
                return MutationResult(updated, None)
            scenes = _apply_script_scene_operations(
                proposal.operations,
                document.director_script.scenes,
                target_scene_ids=target_scene_ids,
            )
            if scenes == document.director_script.scenes:
                updated = replace(
                    document,
                    revision=document.revision + 1,
                    director_runs=_finish_director_run(document, DirectorRunKind.DIRECTOR),
                )
                return MutationResult(updated, None)
            _validate_script_references(
                scenes,
                document.reference_library,
                previous_scenes=document.director_script.scenes,
            )
            updated = _invalidate_production_after_script_revision(document, scenes)
            updated = replace(
                updated,
                director_runs=_finish_director_run(document, DirectorRunKind.DIRECTOR),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def save_production_script_revision_proposal(
        self,
        proposal: StructuredDirectorScriptRevisionProposal,
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再保存生产期脚本。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if (
                document.status
                not in {
                    StructuredDirectorStatus.REVIEWING_NARRATION,
                    StructuredDirectorStatus.REVIEWING_KEYFRAMES,
                    StructuredDirectorStatus.REVIEWING_VIDEOS,
                    StructuredDirectorStatus.REVIEWING_FINAL,
                }
                or document.director_script is None
            ):
                raise ValueError("当前不能保存生产期脚本修改。")
            scenes = _materialize_script_revision(proposal.scenes, document.director_script.scenes)
            _validate_script_references(
                scenes,
                document.reference_library,
                previous_scenes=document.director_script.scenes,
            )
            updated = _invalidate_production_after_script_revision(document, scenes)
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def apply_script_operations(
        self,
        patch: ScriptOperationsPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        """顺序应用 Scene/Shot/Segment 原子操作，并只校验最终脚本状态。"""

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            script = document.director_script
            if script is None:
                raise ValueError("结构化导演脚本尚未建立。")
            scenes, changed_ids = _apply_script_operations(
                script.scenes,
                patch,
                command_id=command_id,
            )
            formal_names = _formal_script_command_names(patch)
            open_gaps = tuple(
                item
                for item in document.capability_gap_alerts
                if item.status is CapabilityGapStatus.OPEN and item.missing_command in formal_names
            )
            if scenes == script.scenes and not open_gaps:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id=command_id,
                        status="noop",
                        old_revision=document.revision,
                        new_revision=document.revision,
                        decision_summary="脚本目标状态已经满足，没有重复写入。",
                        next_allowed_actions=("script.apply_operations",),
                    ),
                    write=False,
                )
            if scenes != script.scenes:
                _validate_script_references(
                    scenes,
                    document.reference_library,
                    previous_scenes=script.scenes,
                )
                updated = _invalidate_production_after_script_revision(document, scenes)
            else:
                updated = replace(document, revision=document.revision + 1)
            if open_gaps:
                updated = replace(
                    updated,
                    capability_gap_alerts=tuple(
                        replace(
                            item,
                            status=CapabilityGapStatus.CLOSED,
                            closed_revision=updated.revision,
                            closed_by_command="script.apply_operations",
                        )
                        if item in open_gaps
                        else item
                        for item in updated.capability_gap_alerts
                    ),
                )
            invalidated = _repair_invalidated_items(document, updated)
            previous_scene_ids = {scene.id for scene in script.scenes}
            created_scene_ids = [scene.id for scene in scenes if scene.id not in previous_scene_ids]
            decision_summary = "已原子应用 Script operations。"
            if created_scene_ids:
                decision_summary += f"新建 Scene：{'、'.join(created_scene_ids)}。"
            return MutationResult(
                updated,
                CommandReceipt(
                    command_id=command_id,
                    status="succeeded",
                    old_revision=document.revision,
                    new_revision=updated.revision,
                    changed_ids=tuple(sorted((*changed_ids, *(item.gap_id for item in open_gaps)))),
                    invalidated=invalidated,
                    preserved=("asset_history", "generation_history"),
                    decision_summary=decision_summary,
                    applied_summary={"operations": len(patch.operations)},
                    next_allowed_actions=("script.apply_operations",),
                    warnings=tuple(
                        f"CAPABILITY_GAP_CLOSED:{item.missing_command}" for item in open_gaps
                    ),
                ),
            )

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def apply_repair_patch(
        self,
        patch: RepairPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, RepairReceipt]:
        """以字段白名单原子修复脚本实体，并持久记录能力缺口。"""
        document = self.read()
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已被更新，请重新读取后再执行 repair patch。")
        replay = next(
            (alert for alert in document.capability_gap_alerts if command_id in alert.command_ids),
            None,
        )
        if replay is not None:
            return (
                document,
                CommandReceipt(
                    command_id=command_id,
                    status="noop",
                    old_revision=document.revision,
                    new_revision=document.revision,
                    preserved=(f"capability_gap:{replay.gap_id}",),
                    decision_summary="相同 repair patch 已经执行，本次未重复写入。",
                    warnings=(f"CAPABILITY_GAP:{replay.missing_command}",),
                ),
                RepairReceipt(
                    replay.gap_id,
                    replay.missing_command,
                    tuple(_repair_operation_from_alert(item) for item in replay.operations),
                    tuple(_repair_operation_from_alert(item) for item in replay.reverse_operations),
                ),
            )

        def mutate(current: StructuredDirectorDocument) -> MutationResult:
            script = current.director_script
            if script is None:
                raise ValueError("repair patch 只能修改已经建立的导演脚本。")
            scenes, reverse_operations, target_ids = _apply_repair_operations(
                script.scenes,
                patch,
            )
            changed = scenes != script.scenes
            repaired = (
                _invalidate_production_after_script_revision(current, scenes)
                if changed
                else replace(current, revision=current.revision + 1)
            )
            invalidated = _repair_invalidated_items(current, repaired)
            now = datetime.now(UTC).isoformat(timespec="seconds")
            gap_id = _repair_gap_id(patch)
            previous = next(
                (item for item in current.capability_gap_alerts if item.gap_id == gap_id),
                None,
            )
            operations = tuple(_repair_operation_for_alert(item) for item in patch.operations)
            reverse = tuple(_repair_operation_for_alert(item) for item in reverse_operations)
            alert = CapabilityGapAlert(
                gap_id=gap_id,
                command_id=command_id,
                command_ids=(
                    (*previous.command_ids, command_id)
                    if previous is not None and command_id not in previous.command_ids
                    else previous.command_ids
                    if previous is not None
                    else (command_id,)
                ),
                run_id=patch.run_id,
                missing_command=patch.missing_command,
                raw_user_request_summary=_repair_request_summary(patch.raw_user_request),
                target_ids=target_ids,
                scope_scene_ids=patch.scope_scene_ids,
                operations=operations,
                reverse_operations=reverse,
                operation_summary=_repair_operation_summary(patch.operations),
                old_revision=current.revision,
                new_revision=repaired.revision,
                result=(CapabilityGapResult.SUCCEEDED if changed else CapabilityGapResult.NOOP),
                first_occurred_at=(previous.first_occurred_at if previous is not None else now),
                last_occurred_at=now,
                occurrence_count=(previous.occurrence_count + 1 if previous is not None else 1),
                status=CapabilityGapStatus.OPEN,
            )
            alerts = tuple(
                alert if item.gap_id == gap_id else item for item in current.capability_gap_alerts
            )
            if previous is None:
                alerts = (*alerts, alert)
            repaired = replace(repaired, capability_gap_alerts=alerts)
            return MutationResult(
                repaired,
                CommandReceipt(
                    command_id=command_id,
                    status="succeeded",
                    old_revision=current.revision,
                    new_revision=repaired.revision,
                    changed_ids=tuple(sorted(target_ids)),
                    invalidated=invalidated,
                    preserved=(f"capability_gap:{gap_id}",),
                    decision_summary=(
                        "已使用受控 repair patch 完成字段修改并记录能力缺口。"
                        if changed
                        else "字段已经满足要求；已记录仍需收口的能力缺口。"
                    ),
                    applied_summary={"operations": len(patch.operations)},
                    warnings=(f"CAPABILITY_GAP:{patch.missing_command}",),
                ),
                aux=(gap_id, reverse_operations),
            )

        aux_cell: dict[str, object] = {}

        def mutate_with_aux(current: StructuredDirectorDocument) -> MutationResult:
            outcome = mutate(current)
            aux_cell["value"] = outcome.aux
            return outcome

        _, receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate_with_aux,
        )
        gap_id, reverse_operations = aux_cell["value"]
        repaired = self.read()
        return (
            repaired,
            receipt,
            RepairReceipt(
                gap_id,
                patch.missing_command,
                patch.operations,
                reverse_operations,
            ),
        )
