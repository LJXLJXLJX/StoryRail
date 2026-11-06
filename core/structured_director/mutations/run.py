"""Director run 生命周期 mutations：纯函数化的 run 状态机（P2-C3）。

从 store run 方法原样抽取：每个函数接收权威 document，执行 run 守卫与
cursor/receipt/directive 变换，返回变更后的 document（或附带标志）。
不做文件 I/O；revision CAS、_atomic_write、now/ID 生成由 store pipeline 负责。
"""

from __future__ import annotations

from dataclasses import replace

from core.director_commands import CommandReceipt

from ..models import (
    DirectorCommandReceipt,
    DirectorDirective,
    DirectorRunCursor,
    DirectorRunStatus,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)

_RUN_WAIT_TERMINAL_PHASES = frozenset(
    {
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
    }
)


def set_director_run_cursor(
    document: StructuredDirectorDocument,
    *,
    run_id: str,
    cursor: DirectorRunCursor,
    now: str,
) -> StructuredDirectorDocument:
    """在执行长步骤前持久化其精确目标集合。"""
    active = document.active_director_run
    if active is None or active.id != run_id or active.status is not DirectorRunStatus.RUNNING:
        raise ValueError("Director run 不存在或当前不能更新 cursor。")
    if cursor.step < active.cursor.step:
        raise ValueError("Director run cursor 不能回退。")
    if cursor.waiting_generation_ids:
        raise ValueError("运行中的 Director run cursor 不能保存等待 Generation。")
    next_revision = document.revision + 1
    updated_run = replace(
        active,
        cursor=cursor,
        last_project_revision=next_revision,
        updated_at=now,
    )
    return replace(
        document,
        revision=next_revision,
        director_runs=tuple(
            updated_run if item.id == run_id else item for item in document.director_runs
        ),
    )


def record_director_run_progress(
    document: StructuredDirectorDocument,
    *,
    run_id: str,
    cursor: DirectorRunCursor,
    receipt: CommandReceipt,
    now: str,
) -> tuple[StructuredDirectorDocument, bool]:
    """持久化已执行命令的最小回执与下一 cursor；重复记录时返回 (document, True)。"""
    run = next((item for item in document.director_runs if item.id == run_id), None)
    if run is None:
        raise ValueError("Director run 不存在。")
    if run.status in {DirectorRunStatus.FAILED, DirectorRunStatus.CANCELLED}:
        raise ValueError("失败或已取消的 Director run 不能追加 receipt。")
    if cursor.step < run.cursor.step:
        raise ValueError("Director run cursor 不能回退。")
    decision_summary = receipt.decision_summary or "Core 命令已执行。"
    existing = next(
        (item for item in run.command_receipts if item.command_id == receipt.command_id),
        None,
    )
    if existing is not None:
        if (
            existing.status != receipt.status
            or existing.old_revision != receipt.old_revision
            or existing.new_revision != receipt.new_revision
            or existing.decision_summary != decision_summary
        ):
            raise ValueError("同一 command_id 的 Director receipt 内容不一致。")
        return document, True
    if receipt.new_revision > document.revision:
        raise ValueError("Director receipt 引用了尚未提交的 project revision。")
    summary = DirectorCommandReceipt(
        command_id=receipt.command_id,
        status=receipt.status,
        old_revision=receipt.old_revision,
        new_revision=receipt.new_revision,
        decision_summary=decision_summary,
        recorded_at=now,
    )
    next_revision = document.revision + 1
    updated_run = replace(
        run,
        cursor=cursor,
        completed_command_ids=(*run.completed_command_ids, receipt.command_id),
        command_receipts=(*run.command_receipts, summary),
        last_project_revision=next_revision,
        updated_at=now,
    )
    return (
        replace(
            document,
            revision=next_revision,
            director_runs=tuple(
                updated_run if item.id == run_id else item for item in document.director_runs
            ),
        ),
        False,
    )


def wait_director_run(
    document: StructuredDirectorDocument,
    *,
    run_id: str,
    status: DirectorRunStatus,
    reason: str,
    now: str,
    waiting_generation_ids: tuple[str, ...] = (),
) -> StructuredDirectorDocument:
    """把运行中的 run 暂停为 waiting_user / waiting_jobs。"""
    active = document.active_director_run
    if active is None or active.id != run_id or active.status is not DirectorRunStatus.RUNNING:
        raise ValueError("Director run 不存在或当前不能暂停。")
    if status not in {DirectorRunStatus.WAITING_USER, DirectorRunStatus.WAITING_JOBS}:
        raise ValueError("Director run 只能暂停为 waiting_user 或 waiting_jobs。")
    if status is DirectorRunStatus.WAITING_USER and waiting_generation_ids:
        raise ValueError("waiting_user 不能绑定 Generation。")
    if status is DirectorRunStatus.WAITING_JOBS:
        if not waiting_generation_ids:
            raise ValueError("waiting_jobs 必须绑定至少一个 Generation。")
        generation_by_id = {item.id: item for item in document.generations}
        if any(item not in generation_by_id for item in waiting_generation_ids):
            raise ValueError("waiting_jobs 引用了不存在的 Generation。")
        if all(
            generation_by_id[item].phase in _RUN_WAIT_TERMINAL_PHASES
            for item in waiting_generation_ids
        ):
            raise ValueError("指定 Generation 已全部结束，无需进入 waiting_jobs。")
    next_revision = document.revision + 1
    waiting = replace(
        active,
        status=status,
        waiting_reason=reason.strip(),
        cursor=replace(
            active.cursor,
            step=active.cursor.step + 1,
            waiting_generation_ids=waiting_generation_ids,
        ),
        last_project_revision=next_revision,
        updated_at=now,
    )
    return replace(
        document,
        revision=next_revision,
        director_runs=tuple(
            waiting if item.id == run_id else item for item in document.director_runs
        ),
    )


def resume_director_run(
    document: StructuredDirectorDocument,
    *,
    run_id: str,
    raw_user_request: str | None,
    now: str,
    new_directive_id: str,
) -> StructuredDirectorDocument:
    """从 waiting_user / waiting_jobs 恢复 run；可附带新的用户指令 directive。"""
    run = next((item for item in document.director_runs if item.id == run_id), None)
    if run is None or run.status not in {
        DirectorRunStatus.WAITING_USER,
        DirectorRunStatus.WAITING_JOBS,
    }:
        raise ValueError("Director run 当前不在等待状态。")
    if run.status is DirectorRunStatus.WAITING_USER and (
        raw_user_request is None or not raw_user_request.strip()
    ):
        raise ValueError("waiting_user run 需要新的用户指令才能恢复。")
    if run.status is DirectorRunStatus.WAITING_JOBS:
        generation_by_id = {item.id: item for item in document.generations}
        if any(
            generation_by_id.get(item) is None
            or generation_by_id[item].phase not in _RUN_WAIT_TERMINAL_PHASES
            for item in run.cursor.waiting_generation_ids
        ):
            raise ValueError("仍有 Provider Generation 未结束。")
    next_revision = document.revision + 1
    resumed = replace(
        run,
        status=DirectorRunStatus.RUNNING,
        waiting_reason=None,
        cursor=replace(run.cursor, waiting_generation_ids=()),
        last_project_revision=next_revision,
        updated_at=now,
    )
    directives = document.director_directives
    if raw_user_request is not None and raw_user_request.strip():
        directives = (
            *directives,
            DirectorDirective(new_directive_id, run.id, raw_user_request.strip(), now),
        )
    return replace(
        document,
        revision=next_revision,
        director_runs=tuple(
            resumed if item.id == run_id else item for item in document.director_runs
        ),
        director_directives=directives,
    )


def cancel_director_run(
    document: StructuredDirectorDocument, *, run_id: str, now: str
) -> StructuredDirectorDocument:
    """取消未结束的 run 并释放 pending edit 请求。"""
    active = document.active_director_run
    if active is None or active.id != run_id:
        raise ValueError("Director run 不存在或已经结束。")
    next_revision = document.revision + 1
    cancelled = replace(
        active,
        status=DirectorRunStatus.CANCELLED,
        waiting_reason=None,
        cursor=replace(active.cursor, waiting_generation_ids=()),
        last_project_revision=next_revision,
        updated_at=now,
    )
    return replace(
        document,
        revision=next_revision,
        pending_script_edit=None,
        pending_narration_edit=None,
        director_runs=tuple(
            cancelled if item.id == run_id else item for item in document.director_runs
        ),
    )
