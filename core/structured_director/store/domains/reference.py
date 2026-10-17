"""store/domains/reference：reference 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from core.director_commands import CommandReceipt
from core.director_commands.reference_commands import LookOperationsPatch
from core.director_proposals import ReferenceLibraryProposal
from core.structured_director.models import (
    CharacterCard,
    CharacterLook,
    DirectorRunKind,
    NarratorProfile,
    NarratorVoice,
    ReferenceLibrary,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
)
from core.structured_director.mutations import reference as _reference
from core.structured_director.run_state import _active_run_is as _active_run_is
from core.structured_director.run_state import _start_director_run as _start_director_run
from core.structured_director.script_mutations import _finish_director_run as _finish_director_run
from core.structured_director.store.pipeline import (
    MutationResult as MutationResult,
)
from core.structured_director.store.pipeline import (
    commit_mutation as commit_mutation,
)


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class ReferenceDomain(_DomainBase):
    def apply_look_operations(
        self,
        patch: LookOperationsPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            outcome = _reference.apply_look_operations(document, patch, command_id)
            return MutationResult(outcome.document, outcome.receipt, write=outcome.write)

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def begin_reference_proposal(
        self, *, raw_user_request: str = "生成引用库 proposal"
    ) -> tuple[StructuredDirectorDocument, bool]:
        aux_cell: dict[str, bool] = {}

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if active is not None:
                if active.kind is not DirectorRunKind.REFERENCE_PROPOSAL:
                    raise ValueError("另一个 Director Agent 任务正在执行。")
                aux_cell["already_active"] = True
                return MutationResult(document, None, write=False)
            if document.status is not StructuredDirectorStatus.AWAITING_PROPOSAL:
                raise ValueError("引用库 proposal 已经完成。")
            started = _start_director_run(
                document,
                DirectorRunKind.REFERENCE_PROPOSAL,
                goal="生成项目引用库 proposal",
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

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated, aux_cell["already_active"]

    def apply_reference_proposal(
        self, proposal: ReferenceLibraryProposal
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            awaiting = StructuredDirectorStatus.AWAITING_PROPOSAL
            if document.status is not awaiting or not _active_run_is(
                document, DirectorRunKind.REFERENCE_PROPOSAL
            ):
                raise ValueError("当前没有等待保存的引用库 proposal。")
            library = ReferenceLibrary(
                characters=tuple(
                    CharacterCard(
                        id=uuid4().hex,
                        name=item.name.strip(),
                        visual_description=None
                        if item.visual_description is None
                        else item.visual_description.strip(),
                        voice_description=item.voice_description.strip(),
                        looks=tuple(
                            CharacterLook(
                                id=uuid4().hex,
                                name=look.name.strip(),
                                appearance=look.appearance.strip(),
                                usage=look.usage.strip(),
                            )
                            for look in item.looks
                        ),
                    )
                    for item in proposal.characters
                ),
                narrator=(
                    None
                    if proposal.narrator is None
                    else NarratorProfile(
                        id=uuid4().hex,
                        name=proposal.narrator.name.strip(),
                        zh=None
                        if proposal.narrator.zh_voice_description is None
                        else NarratorVoice(proposal.narrator.zh_voice_description.strip()),
                        en=None
                        if proposal.narrator.en_voice_description is None
                        else NarratorVoice(proposal.narrator.en_voice_description.strip()),
                    )
                ),
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                status=StructuredDirectorStatus.REVIEWING,
                reference_library=library,
                director_runs=_finish_director_run(document, DirectorRunKind.REFERENCE_PROPOSAL),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated
