from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from .models import (
    DirectorAuthorization,
    DirectorCandidateSelectionPolicy,
    DirectorDirective,
    DirectorRun,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)

_RUN_WAIT_TERMINAL_PHASES = {
    ReferenceGenerationPhase.SUCCEEDED,
    ReferenceGenerationPhase.FAILED,
    ReferenceGenerationPhase.CANCELLED,
    ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
}


def _active_run_is(document: StructuredDirectorDocument, kind: DirectorRunKind) -> bool:
    active = document.active_director_run
    return active is not None and active.kind is kind


def _wake_director_run_for_completed_generations(
    document: StructuredDirectorDocument,
) -> StructuredDirectorDocument:
    active = document.active_director_run
    if active is None or active.status is not DirectorRunStatus.WAITING_JOBS:
        return document
    generation_by_id = {item.id: item for item in document.generations}
    if any(
        generation_by_id.get(item) is None
        or generation_by_id[item].phase not in _RUN_WAIT_TERMINAL_PHASES
        for item in active.cursor.waiting_generation_ids
    ):
        return document
    now = datetime.now(UTC).isoformat()
    resumed = replace(
        active,
        status=DirectorRunStatus.RUNNING,
        waiting_reason=None,
        cursor=replace(active.cursor, waiting_generation_ids=()),
        last_project_revision=document.revision,
        updated_at=now,
    )
    return replace(
        document,
        director_runs=tuple(
            resumed if item.id == active.id else item for item in document.director_runs
        ),
    )


@dataclass(frozen=True, slots=True)
class _StartedDirectorRun:
    runs: tuple[DirectorRun, ...]
    directives: tuple[DirectorDirective, ...]


def _start_director_run(
    document: StructuredDirectorDocument,
    kind: DirectorRunKind,
    *,
    goal: str,
    raw_user_request: str,
    pending_target_ids: tuple[str, ...] = (),
) -> _StartedDirectorRun:
    if document.active_director_run is not None:
        raise ValueError("同一项目不能并行启动多个 Director Agent 任务。")
    now = datetime.now(UTC).isoformat()
    run_id = uuid4().hex
    edit_scopes, generation_scopes = _default_director_authorization(kind)
    run = DirectorRun(
        id=run_id,
        kind=kind,
        goal=goal,
        status=DirectorRunStatus.RUNNING,
        waiting_reason=None,
        authorization=DirectorAuthorization(
            edit_scopes=edit_scopes,
            generation_scopes=generation_scopes,
            candidate_selection=DirectorCandidateSelectionPolicy.EXPLICIT_ONLY,
            final_approval=False,
        ),
        cursor=DirectorRunCursor(0, pending_target_ids, ()),
        completed_command_ids=(),
        command_receipts=(),
        last_project_revision=document.revision + 1,
        created_at=now,
        updated_at=now,
    )
    directive = DirectorDirective(uuid4().hex, run_id, raw_user_request, now)
    return _StartedDirectorRun(
        (*document.director_runs, run),
        (*document.director_directives, directive),
    )


def _default_director_authorization(
    kind: DirectorRunKind,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return {
        DirectorRunKind.REFERENCE_PROPOSAL: (("reference_library:*",), ()),
        DirectorRunKind.SCRIPT_PROPOSAL: (("script:*",), ()),
        DirectorRunKind.SCRIPT_EDIT: (("script:*",), ()),
        DirectorRunKind.NARRATION_EDIT: (("narration:*",), ("narration:*",)),
        DirectorRunKind.KEYFRAME_PLAN: (("keyframe:*",), ()),
        DirectorRunKind.LOCATION_PLAN: (("location:*",), ()),
        DirectorRunKind.DIRECTOR: (
            ("project:*",),
            ("location:*", "keyframe:*", "segment:*", "final:*"),
        ),
    }[kind]
