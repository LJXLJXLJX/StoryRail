"""store/domains/final：final 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from core.director_commands import CommandReceipt, FinalApprovalRequest, FinalCandidateSelection
from core.structured_director.errors import RevisionConflictError as RevisionConflictError
from core.structured_director.models import (
    FinalAssemblyPlan,
    StructuredDirectorDocument,
)
from core.structured_director.mutations import final as _final_mutations
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class FinalDomain(_DomainBase):
    def enter_final_stage(
        self, plan: FinalAssemblyPlan, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再进入成片装配。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _final_mutations.enter_final_stage(document, plan), None
            ),
        )
        return updated

    def select_final_candidate_command(
        self,
        selection: FinalCandidateSelection,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, receipt, write = _final_mutations.select_final_candidate(
                document, selection, command_id=command_id
            )
            return MutationResult(updated, receipt, write=write)

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def clear_final_selection_command(
        self,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, receipt, write = _final_mutations.clear_final_selection(
                document, command_id=command_id
            )
            return MutationResult(updated, receipt, write=write)

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def approve_final_command(
        self,
        approval: FinalApprovalRequest,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再批准成片。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, receipt, write = _final_mutations.approve_final(
                document, approval, command_id=command_id
            )
            return MutationResult(updated, receipt, write=write)

        return commit_mutation(self, loader=load, mutator=mutate)

    def reopen_final_production_command(
        self,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再返回视频生产。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, receipt, write = _final_mutations.reopen_final_production(
                document, command_id=command_id
            )
            return MutationResult(updated, receipt, write=write)

        return commit_mutation(self, loader=load, mutator=mutate)
