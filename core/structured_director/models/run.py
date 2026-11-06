"""领域模型：run 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ._shared import _require_id, _require_text, _validate_timestamp, _validate_unique_ids


class DirectorRunKind(StrEnum):
    REFERENCE_PROPOSAL = "reference_proposal"
    SCRIPT_PROPOSAL = "script_proposal"
    SCRIPT_EDIT = "script_edit"
    NARRATION_EDIT = "narration_edit"
    KEYFRAME_PLAN = "keyframe_plan"
    LOCATION_PLAN = "location_plan"
    DIRECTOR = "director"


class DirectorRunStatus(StrEnum):
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    WAITING_JOBS = "waiting_jobs"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DirectorCandidateSelectionPolicy(StrEnum):
    EXPLICIT_ONLY = "explicit_only"


@dataclass(frozen=True, slots=True)
class DirectorAuthorization:
    edit_scopes: tuple[str, ...]
    generation_scopes: tuple[str, ...]
    candidate_selection: DirectorCandidateSelectionPolicy
    final_approval: bool

    def __post_init__(self) -> None:
        _validate_scope_list(self.edit_scopes, "authorization.edit_scopes")
        _validate_scope_list(self.generation_scopes, "authorization.generation_scopes")
        if not isinstance(self.final_approval, bool):
            raise ValueError("authorization.final_approval 必须是 boolean。")


@dataclass(frozen=True, slots=True)
class DirectorRunCursor:
    step: int
    pending_target_ids: tuple[str, ...]
    waiting_generation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.step, bool) or self.step < 0:
            raise ValueError("director_run.cursor.step 必须是非负整数。")
        _validate_unique_ids(self.pending_target_ids, "cursor.pending_target_ids")
        _validate_unique_ids(self.waiting_generation_ids, "cursor.waiting_generation_ids")


@dataclass(frozen=True, slots=True)
class DirectorCommandReceipt:
    command_id: str
    status: str
    old_revision: int
    new_revision: int
    decision_summary: str
    recorded_at: str

    def __post_init__(self) -> None:
        _require_text(self.command_id, "director receipt command_id", 200)
        if self.status not in {"succeeded", "noop"}:
            raise ValueError("director receipt status 不合法。")
        if (
            isinstance(self.old_revision, bool)
            or isinstance(self.new_revision, bool)
            or self.old_revision < 1
            or self.new_revision < self.old_revision
        ):
            raise ValueError("director receipt revision 不合法。")
        _require_text(self.decision_summary, "director receipt decision_summary", 2_000)
        _validate_timestamp(self.recorded_at, "director receipt recorded_at")


@dataclass(frozen=True, slots=True)
class DirectorRun:
    id: str
    kind: DirectorRunKind
    goal: str
    status: DirectorRunStatus
    waiting_reason: str | None
    authorization: DirectorAuthorization
    cursor: DirectorRunCursor
    completed_command_ids: tuple[str, ...]
    command_receipts: tuple[DirectorCommandReceipt, ...]
    last_project_revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _require_id(self.id, "director_run.id")
        _require_text(self.goal, "director_run.goal", 20_000)
        if self.status in {DirectorRunStatus.WAITING_USER, DirectorRunStatus.WAITING_JOBS}:
            if self.waiting_reason is None:
                raise ValueError("等待中的 Director run 必须保存原因。")
            _require_text(self.waiting_reason, "director_run.waiting_reason", 2_000)
        elif self.waiting_reason is not None:
            raise ValueError("非等待 Director run 不能保存 waiting_reason。")
        if self.status is DirectorRunStatus.WAITING_JOBS:
            if not self.cursor.waiting_generation_ids:
                raise ValueError("waiting_jobs Director run 必须保存等待的 Generation。")
        elif self.cursor.waiting_generation_ids:
            raise ValueError("只有 waiting_jobs Director run 能保存等待的 Generation。")
        if isinstance(self.last_project_revision, bool) or self.last_project_revision < 1:
            raise ValueError("director_run.last_project_revision 不合法。")
        if len(self.completed_command_ids) != len(set(self.completed_command_ids)):
            raise ValueError("director_run.completed_command_ids 不能重复。")
        receipt_ids = tuple(item.command_id for item in self.command_receipts)
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("director_run.command_receipts 不能重复。")
        if receipt_ids != self.completed_command_ids:
            raise ValueError("Director run 的完成命令与 receipt 摘要不一致。")
        if any(item.new_revision > self.last_project_revision for item in self.command_receipts):
            raise ValueError("Director receipt 不能引用 last_project_revision 之后的状态。")
        _validate_timestamp(self.created_at, "director_run.created_at")
        _validate_timestamp(self.updated_at, "director_run.updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("director_run.updated_at 不能早于 created_at。")


@dataclass(frozen=True, slots=True)
class DirectorDirective:
    id: str
    run_id: str
    raw_user_request: str
    created_at: str

    def __post_init__(self) -> None:
        _require_id(self.id, "director_directive.id")
        _require_id(self.run_id, "director_directive.run_id")
        _require_text(
            self.raw_user_request,
            "director_directive.raw_user_request",
            20_000,
        )
        _validate_timestamp(self.created_at, "director_directive.created_at")


def _validate_scope_list(values: tuple[str, ...], field: str) -> None:
    if len(values) > 1_000 or len(values) != len(set(values)):
        raise ValueError(f"{field} 过多或重复。")
    for value in values:
        _require_text(value, field, 200)
