"""store/domains/run：run 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from uuid import uuid4

from core.director_commands import CommandReceipt, RunResume, RunTarget
from core.structured_director.errors import RevisionConflictError as RevisionConflictError
from core.structured_director.models import (
    DirectorRunCursor,
    DirectorRunStatus,
    StructuredDirectorDocument,
)
from core.structured_director.mutations import run as _run
from core.structured_director.store import _generation_timestamp as _generation_timestamp
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class RunDomain(_DomainBase):
    def set_director_run_cursor(
        self,
        *,
        run_id: str,
        cursor: DirectorRunCursor,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        """在执行长步骤前持久化其精确目标集合，不伪造 command receipt。"""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再保存 run cursor。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _run.set_director_run_cursor(
                    document, run_id=run_id, cursor=cursor, now=_generation_timestamp()
                ),
                None,
            ),
        )
        return updated

    def record_director_run_progress(
        self,
        *,
        run_id: str,
        cursor: DirectorRunCursor,
        receipt: CommandReceipt,
        expected_revision: int,
    ) -> tuple[StructuredDirectorDocument, bool]:
        """持久化已执行命令的最小回执与下一 cursor，不保存模型推理。"""

        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再保存 run 进度。")
            return document

        aux_cell: dict[str, bool] = {}

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, already_recorded = _run.record_director_run_progress(
                document, run_id=run_id, cursor=cursor, receipt=receipt, now=_generation_timestamp()
            )
            aux_cell["already_recorded"] = already_recorded
            return MutationResult(updated, None, write=not already_recorded)

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated, aux_cell["already_recorded"]

    def wait_director_run(
        self,
        *,
        run_id: str,
        status: DirectorRunStatus,
        reason: str,
        waiting_generation_ids: tuple[str, ...] = (),
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再暂停 run。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _run.wait_director_run(
                    document,
                    run_id=run_id,
                    status=status,
                    reason=reason,
                    waiting_generation_ids=waiting_generation_ids,
                    now=_generation_timestamp(),
                ),
                None,
            ),
        )
        return updated

    def resume_director_run(
        self,
        *,
        run_id: str,
        expected_revision: int,
        raw_user_request: str | None = None,
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再恢复 run。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _run.resume_director_run(
                    document,
                    run_id=run_id,
                    raw_user_request=raw_user_request,
                    now=_generation_timestamp(),
                    new_directive_id=uuid4().hex,
                ),
                None,
            ),
        )
        return updated

    def cancel_director_run(
        self, *, run_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再取消 run。")
            return document

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=lambda document: MutationResult(
                _run.cancel_director_run(document, run_id=run_id, now=_generation_timestamp()),
                None,
            ),
        )
        return updated

    def cancel_director_run_command(
        self,
        target: RunTarget,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再取消 run。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            run = next((item for item in document.director_runs if item.id == target.run_id), None)
            if run is None:
                raise ValueError("Director run 不存在。")
            if run.status is DirectorRunStatus.CANCELLED:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id,
                        "noop",
                        document.revision,
                        document.revision,
                        preserved=tuple(f"generation:{item.id}" for item in document.generations),
                        decision_summary="Director run 已经取消；Provider Generation 未受影响。",
                    ),
                    write=False,
                )
            if document.active_director_run is None or document.active_director_run.id != run.id:
                raise ValueError("只有尚未结束的 Director run 可以取消。")
            updated = _run.cancel_director_run(document, run_id=run.id, now=_generation_timestamp())
            return MutationResult(
                updated,
                CommandReceipt(
                    command_id,
                    "succeeded",
                    document.revision,
                    updated.revision,
                    changed_ids=(run.id,),
                    preserved=tuple(f"generation:{item.id}" for item in document.generations),
                    decision_summary=(
                        "已停止 Director 的后续执行；已提交的 Provider Generation 继续保留。"
                    ),
                ),
            )

        return commit_mutation(self, loader=load, mutator=mutate)

    def resume_director_run_command(
        self,
        resume: RunResume,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def load() -> StructuredDirectorDocument:
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已被更新，请重新读取后再恢复 run。")
            return document

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            run = next((item for item in document.director_runs if item.id == resume.run_id), None)
            if run is None:
                raise ValueError("Director run 不存在。")
            if run.status is DirectorRunStatus.RUNNING:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id,
                        "noop",
                        document.revision,
                        document.revision,
                        changed_ids=(run.id,),
                        decision_summary="Director run 已处于可继续执行状态。",
                        next_allowed_actions=("director.recover",),
                    ),
                    write=False,
                )
            updated = _run.resume_director_run(
                document,
                run_id=run.id,
                raw_user_request=resume.raw_user_request,
                now=_generation_timestamp(),
                new_directive_id=uuid4().hex,
            )
            return MutationResult(
                updated,
                CommandReceipt(
                    command_id,
                    "succeeded",
                    document.revision,
                    updated.revision,
                    changed_ids=(run.id,),
                    decision_summary=(
                        "已从持久 cursor 恢复 Director run，可基于最新 revision 继续。"
                    ),
                    next_allowed_actions=("director.recover",),
                ),
            )

        return commit_mutation(self, loader=load, mutator=mutate)
