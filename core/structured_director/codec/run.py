"""文档编解码：run 域的 parse/serialize 函数对（纯移动，语义/JSON key/错误消息不变）。"""

from __future__ import annotations

from typing import Any

from ..models import (
    DirectorAuthorization,
    DirectorCandidateSelectionPolicy,
    DirectorCommandReceipt,
    DirectorDirective,
    DirectorRun,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
)
from ._shared import (
    _boolean,
    _exact_object,
    _integer,
    _object_list,
    _optional_string,
    _string,
    _string_list,
)


def _serialize_director_run(run: DirectorRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "kind": run.kind.value,
        "goal": run.goal,
        "status": run.status.value,
        "waiting_reason": run.waiting_reason,
        "authorization": {
            "edit_scopes": list(run.authorization.edit_scopes),
            "generation_scopes": list(run.authorization.generation_scopes),
            "candidate_selection": run.authorization.candidate_selection.value,
            "final_approval": run.authorization.final_approval,
        },
        "cursor": {
            "step": run.cursor.step,
            "pending_target_ids": list(run.cursor.pending_target_ids),
            "waiting_generation_ids": list(run.cursor.waiting_generation_ids),
        },
        "completed_command_ids": list(run.completed_command_ids),
        "command_receipts": [
            {
                "command_id": item.command_id,
                "status": item.status,
                "old_revision": item.old_revision,
                "new_revision": item.new_revision,
                "decision_summary": item.decision_summary,
                "recorded_at": item.recorded_at,
            }
            for item in run.command_receipts
        ],
        "last_project_revision": run.last_project_revision,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _serialize_director_directive(directive: DirectorDirective) -> dict[str, str]:
    return {
        "id": directive.id,
        "run_id": directive.run_id,
        "raw_user_request": directive.raw_user_request,
        "created_at": directive.created_at,
    }


def _parse_director_run(value: object) -> DirectorRun:
    fields = _exact_object(
        value,
        {
            "id",
            "kind",
            "goal",
            "status",
            "waiting_reason",
            "authorization",
            "cursor",
            "completed_command_ids",
            "command_receipts",
            "last_project_revision",
            "created_at",
            "updated_at",
        },
    )
    authorization = _exact_object(
        fields["authorization"],
        {
            "edit_scopes",
            "generation_scopes",
            "candidate_selection",
            "final_approval",
        },
    )
    cursor = _exact_object(
        fields["cursor"],
        {"step", "pending_target_ids", "waiting_generation_ids"},
    )
    return DirectorRun(
        id=_string(fields["id"], "director_run.id"),
        kind=DirectorRunKind(_string(fields["kind"], "director_run.kind")),
        goal=_string(fields["goal"], "director_run.goal"),
        status=DirectorRunStatus(_string(fields["status"], "director_run.status")),
        waiting_reason=_optional_string(fields["waiting_reason"], "director_run.waiting_reason"),
        authorization=DirectorAuthorization(
            edit_scopes=_string_list(
                authorization["edit_scopes"], "director_run.authorization.edit_scopes"
            ),
            generation_scopes=_string_list(
                authorization["generation_scopes"],
                "director_run.authorization.generation_scopes",
            ),
            candidate_selection=DirectorCandidateSelectionPolicy(
                _string(
                    authorization["candidate_selection"],
                    "director_run.authorization.candidate_selection",
                )
            ),
            final_approval=_boolean(
                authorization["final_approval"],
                "director_run.authorization.final_approval",
            ),
        ),
        cursor=DirectorRunCursor(
            step=_integer(cursor["step"], "director_run.cursor.step"),
            pending_target_ids=_string_list(
                cursor["pending_target_ids"], "director_run.cursor.pending_target_ids"
            ),
            waiting_generation_ids=_string_list(
                cursor["waiting_generation_ids"],
                "director_run.cursor.waiting_generation_ids",
            ),
        ),
        completed_command_ids=_string_list(
            fields["completed_command_ids"], "director_run.completed_command_ids"
        ),
        command_receipts=_object_list(fields["command_receipts"], _parse_director_command_receipt),
        last_project_revision=_integer(
            fields["last_project_revision"], "director_run.last_project_revision"
        ),
        created_at=_string(fields["created_at"], "director_run.created_at"),
        updated_at=_string(fields["updated_at"], "director_run.updated_at"),
    )


def _parse_director_command_receipt(value: object) -> DirectorCommandReceipt:
    fields = _exact_object(
        value,
        {
            "command_id",
            "status",
            "old_revision",
            "new_revision",
            "decision_summary",
            "recorded_at",
        },
    )
    return DirectorCommandReceipt(
        command_id=_string(fields["command_id"], "director receipt command_id"),
        status=_string(fields["status"], "director receipt status"),
        old_revision=_integer(fields["old_revision"], "director receipt old_revision"),
        new_revision=_integer(fields["new_revision"], "director receipt new_revision"),
        decision_summary=_string(fields["decision_summary"], "director receipt decision_summary"),
        recorded_at=_string(fields["recorded_at"], "director receipt recorded_at"),
    )


def _parse_director_directive(value: object) -> DirectorDirective:
    fields = _exact_object(value, {"id", "run_id", "raw_user_request", "created_at"})
    return DirectorDirective(
        id=_string(fields["id"], "director_directive.id"),
        run_id=_string(fields["run_id"], "director_directive.run_id"),
        raw_user_request=_string(fields["raw_user_request"], "director_directive.raw_user_request"),
        created_at=_string(fields["created_at"], "director_directive.created_at"),
    )
