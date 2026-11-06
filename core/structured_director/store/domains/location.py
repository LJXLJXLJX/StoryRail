"""store/domains/location：地点库写入 collaborator。

编辑（人类与 Agent 共用的 `location.apply_operations`）、地点规划 proposal 的落库与人类候选选择
都经同一 commit pipeline；纯函数与失效级联在 `core.structured_director.location_mutations`。
未在域上定义的名字经 __getattr__ 回退到 StructuredDirectorStore。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.director_commands import (
    CommandReceipt,
    LocationImageSelection,
    LocationOperationsPatch,
)
from core.model_providers.contracts import validate_pano_source
from core.structured_director.errors import RevisionConflictError
from core.structured_director.location_mutations import (
    LocationMutation,
    apply_location_operations,
    select_location_image,
)
from core.structured_director.models import (
    CapabilityGapStatus,
    DirectorRunKind,
    DirectorRunStatus,
    LocationImageKind,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
)
from core.structured_director.repair_mutations import (
    _repair_invalidated_items as _repair_invalidated_items,
)
from core.structured_director.run_state import _active_run_is, _start_director_run
from core.structured_director.script_mutations import _finish_director_run
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation

_FORMAL_COMMAND = "location.apply_operations"


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class LocationDomain(_DomainBase):
    def apply_location_operations(
        self,
        patch: LocationOperationsPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, dict[str, object]]:
        """原子应用地点库编辑与 Scene/Shot 绑定；返回局部 key 到正式 ID 的映射。"""
        created: dict[str, str] = {}

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            result = apply_location_operations(document, patch)
            created.update(result.created_ids)
            open_gaps = tuple(
                item
                for item in document.capability_gap_alerts
                if item.status is CapabilityGapStatus.OPEN
                and item.missing_command == _FORMAL_COMMAND
            )
            updated = result.document
            if open_gaps:
                if updated == document:
                    updated = replace(document, revision=document.revision + 1)
                updated = replace(
                    updated,
                    capability_gap_alerts=tuple(
                        replace(
                            item,
                            status=CapabilityGapStatus.CLOSED,
                            closed_revision=updated.revision,
                            closed_by_command=_FORMAL_COMMAND,
                        )
                        if item in open_gaps
                        else item
                        for item in updated.capability_gap_alerts
                    ),
                )
            return _receipt(
                document,
                replace(result, document=updated),
                command_id,
                extra_changed=tuple(item.gap_id for item in open_gaps),
                warnings=tuple(
                    f"CAPABILITY_GAP_CLOSED:{item.missing_command}" for item in open_gaps
                ),
                summary="已原子保存地点库、独立图片与 Scene 语义地点。",
                applied={"operations": len(patch.operations), "created": len(result.created_ids)},
                next_actions=("location.generate_image", "location.capture_panorama"),
            )

        document, receipt = commit_mutation(
            self,
            loader=lambda: self._unlocked_document(expected_revision),
            mutator=mutate,
        )
        return document, receipt, {"created_ids": dict(created)}

    def begin_location_plan(
        self, *, expected_revision: int, user_message: str
    ) -> StructuredDirectorDocument:
        """建立地点规划 run；规划期间锁定其它业务写入，直到 submit 或取消。"""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再规划地点。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if document.active_director_run is not None:
                raise ValueError("已有任务正在执行，请恢复原请求。")
            if document.status is StructuredDirectorStatus.APPROVED:
                raise ValueError("请先显式重新开放生产。")
            if document.director_script is None:
                raise ValueError("导演脚本尚未建立，请先生成结构化脚本再规划地点。")
            raw_user_request = user_message.strip() or "规划地点"
            started = _start_director_run(
                document,
                DirectorRunKind.LOCATION_PLAN,
                goal=raw_user_request,
                raw_user_request=raw_user_request,
            )
            return MutationResult(
                replace(
                    document,
                    revision=document.revision + 1,
                    director_runs=started.runs,
                    director_directives=started.directives,
                ),
                None,
            )

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def apply_location_plan(
        self, patch: LocationOperationsPatch, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        """在规划锁内用与 `location.apply_operations` 相同的 mutation 落库并结束 run。"""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已变化，请重新读取地点规划请求。")
            if not _active_run_is(document, DirectorRunKind.LOCATION_PLAN):
                raise ValueError("当前没有等待保存的地点规划。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated = apply_location_operations(document, patch).document
            if updated == document:
                updated = replace(document, revision=document.revision + 1)
            return MutationResult(
                replace(
                    updated,
                    director_runs=_finish_director_run(document, DirectorRunKind.LOCATION_PLAN),
                ),
                None,
            )

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def scope_location_generation(
        self, location_ids: tuple[str, ...], *, expected_revision: int
    ) -> StructuredDirectorDocument:
        """持久化成套生成批次的精确地点范围，复用现有 run 授权位（同 Keyframe 批次）。"""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已更新，请重新确认地点成套批次。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if (
                active is None
                or active.kind is not DirectorRunKind.DIRECTOR
                or active.status is not DirectorRunStatus.RUNNING
            ):
                raise ValueError("地点成套批次缺少 running Director run。")
            known = {item.id for item in document.location_library.locations}
            if (
                not location_ids
                or len(set(location_ids)) != len(location_ids)
                or not set(location_ids) <= known
            ):
                raise ValueError("地点成套批次必须是明确且不重复的现存地点。")
            scopes = tuple(f"location:{item}" for item in location_ids)
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

    def select_location_image(
        self,
        selection: LocationImageSelection,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            result = select_location_image(document, selection)
            owner = document.location_library.image_owner(selection.image_id)
            if owner is not None and owner[1].kind is LocationImageKind.PANORAMA:
                _asset, content = self.read_asset(selection.asset_id)
                try:
                    validate_pano_source(content)
                except ValueError as exc:
                    raise ValueError(f"全景地点图片必须是 2:1 等距柱状全景：{exc}") from exc
            return _receipt(
                document,
                result,
                command_id,
                summary="已选择地点图片；其它地点图片与生产内容保持不变。",
                next_actions=("location.generate_image", "location.capture_panorama"),
            )

        return commit_mutation(
            self,
            loader=lambda: self._unlocked_document(expected_revision),
            mutator=mutate,
        )


def _receipt(
    document: StructuredDirectorDocument,
    result: LocationMutation,
    command_id: str,
    *,
    summary: str,
    extra_changed: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    applied: dict[str, int] | None = None,
    next_actions: tuple[str, ...] = (),
) -> MutationResult:
    if result.document == document:
        return MutationResult(
            document,
            CommandReceipt(
                command_id=command_id,
                status="noop",
                old_revision=document.revision,
                new_revision=document.revision,
                preserved=("location_selection",),
                decision_summary="地点库已满足目标状态，没有重复写入或清除选择。",
                applied_summary=applied,
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
            changed_ids=tuple(sorted((*result.changed_ids, *extra_changed))),
            invalidated=_repair_invalidated_items(document, result.document),
            preserved=("asset_history", "generation_history"),
            decision_summary=summary,
            applied_summary=applied,
            warnings=warnings,
            next_allowed_actions=next_actions,
        ),
    )
