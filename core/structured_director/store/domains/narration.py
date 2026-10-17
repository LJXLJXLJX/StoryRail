"""store/domains/narration：narration 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from core.director_commands import CommandReceipt, NarrationCueUpdate, NarrationSelectionClear
from core.director_proposals import NarrationReviewProposal
from core.structured_director.errors import RevisionConflictError as RevisionConflictError
from core.structured_director.models import NarrationCue, StructuredDirectorDocument
from core.structured_director.mutations import narration as _narration
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class NarrationDomain(_DomainBase):
    def save_narration_cue(
        self, scene_id: str, cue: NarrationCue, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再保存旁白。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _narration.save_narration_cue(document, scene_id, cue), None
            ),
        )
        return updated

    def update_narration_cue(
        self,
        update: NarrationCueUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            outcome = _narration.update_narration_cue(document, update, command_id)
            return MutationResult(outcome.document, outcome.receipt, write=outcome.write)

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def clear_narration_selection(
        self,
        clear: NarrationSelectionClear,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            outcome = _narration.clear_narration_selection(document, clear, command_id)
            return MutationResult(outcome.document, outcome.receipt, write=outcome.write)

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def select_narration_audio(
        self,
        *,
        cue_id: str,
        generation_id: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再选择旁白。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _narration.select_narration_audio(
                    document, cue_id=cue_id, generation_id=generation_id
                ),
                None,
            ),
        )
        return updated

    def begin_narration_edit(
        self, message: str | None, *, expected_revision: int
    ) -> tuple[StructuredDirectorDocument, bool]:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if document.revision != expected_revision:
                raise RevisionConflictError("项目已被更新，请重新读取后再请求旁白 Agent。")
            return document

        aux_cell: dict[str, bool] = {}

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, already_active = _narration.begin_narration_edit(document, message)
            aux_cell["already_active"] = already_active
            return MutationResult(updated, None, write=not already_active)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated, aux_cell["already_active"]

    def apply_narration_review_proposal(
        self, proposal: NarrationReviewProposal
    ) -> StructuredDirectorDocument:
        updated, _receipt = commit_mutation(
            self,
            loader=self.read,
            mutator=lambda document: MutationResult(
                _narration.apply_narration_review_proposal(document, proposal), None
            ),
        )
        return updated
