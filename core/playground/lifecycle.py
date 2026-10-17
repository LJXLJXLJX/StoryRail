"""Playground run 的生命周期纯函数：迁移表、提交失败分类、重试链接与恢复。

语义逐项对照项目的 `generation_lifecycle.py` 与 `mutations/generation.py`；
差异只在「Generation」改称「实验」，「当前项目输入已变化」改称「参数已变化」。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.model_providers.boundary import ModelProviderError

from .models import PlaygroundDocument, PlaygroundRun, RunPhase

RUN_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.SUBMITTING: frozenset(
        {RunPhase.QUEUED, RunPhase.SUBMISSION_UNCERTAIN, RunPhase.FAILED}
    ),
    RunPhase.QUEUED: frozenset(
        {
            RunPhase.QUEUED,
            RunPhase.RUNNING,
            RunPhase.SUCCEEDED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        }
    ),
    RunPhase.RUNNING: frozenset(
        {
            RunPhase.RUNNING,
            RunPhase.SUCCEEDED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        }
    ),
}

_RETRYABLE_PHASES = frozenset({RunPhase.FAILED, RunPhase.CANCELLED, RunPhase.SUBMISSION_UNCERTAIN})


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def transition_run(
    run: PlaygroundRun,
    phase: RunPhase,
    *,
    progress: float | None = None,
    message: str | None = None,
    error_code: str | None = None,
    plugin_id: str | None = None,
    plugin_version: int | None = None,
    external_id: str | None = None,
    output_asset_id: str | None = None,
    cancellation_requested: bool | None = None,
) -> PlaygroundRun:
    """执行唯一受支持的 run 状态迁移。"""
    if phase not in RUN_TRANSITIONS.get(run.phase, frozenset()):
        raise ValueError(f"实验不能从 {run.phase.value} 迁移到 {phase.value}。")
    return replace(
        run,
        phase=phase,
        progress=run.progress if progress is None else progress,
        message=run.message if message is None else message,
        error_code=error_code,
        plugin_id=run.plugin_id if plugin_id is None else plugin_id,
        plugin_version=(run.plugin_version if plugin_version is None else plugin_version),
        external_id=run.external_id if external_id is None else external_id,
        output_asset_id=output_asset_id,
        cancellation_requested=(
            run.cancellation_requested if cancellation_requested is None else cancellation_requested
        ),
    )


def submission_failure(
    run: PlaygroundRun, exc: Exception, *, capability_label: str
) -> PlaygroundRun:
    code = exc.code if isinstance(exc, ModelProviderError) else "provider_error"
    if code == "external_error":
        return transition_run(
            run,
            RunPhase.FAILED,
            message=(
                f"问题出在任务提交：{capability_label}服务明确拒绝了请求，"
                "没有建立可恢复任务。请检查服务配置或请求参数后重试。"
            ),
            error_code="submission_rejected",
        )
    if code == "invalid_response":
        return transition_run(
            run,
            RunPhase.SUBMISSION_UNCERTAIN,
            message=(
                f"问题出在提交响应校验：{capability_label}服务已经响应，但返回格式不符合当前插件约定。"
                "Core 没有拿到可恢复句柄；任务可能已被服务接受，因此不会自动重试。"
            ),
            error_code=code,
        )
    if code == "transport_error":
        return transition_run(
            run,
            RunPhase.SUBMISSION_UNCERTAIN,
            message=(
                f"问题出在提交传输：Core 无法确认请求是否到达{capability_label}服务。"
                "请检查模型节点、网络和服务状态后手动重试；系统不会自动重试。"
            ),
            error_code=code,
        )
    return transition_run(
        run,
        RunPhase.SUBMISSION_UNCERTAIN,
        message=(
            f"问题出在 Core 的{capability_label}插件提交阶段：无法确认外部任务是否已经建立，"
            "因此不会自动重试。"
        ),
        error_code=code,
    )


def run_recovery(run: PlaygroundRun) -> dict[str, object]:
    status = run.phase.value
    if status == "submission_uncertain":
        return {
            "failure_origin": "provider_submission",
            "retry_policy": "inspect_then_explicit_generation_retry",
            "automatic_retry_allowed": False,
        }
    if run.error_code == "submission_rejected":
        return {
            "failure_origin": "provider_submission",
            "retry_policy": "explicit_generation_retry_after_fix",
            "automatic_retry_allowed": False,
        }
    if status == "failed":
        return {
            "failure_origin": "provider_generation",
            "retry_policy": "explicit_generation_retry_if_inputs_unchanged",
            "automatic_retry_allowed": False,
        }
    if run.error_code == "artifact_import_failed":
        return {
            "failure_origin": "artifact_import",
            "retry_policy": "wait_same_generation",
            "automatic_retry_allowed": False,
        }
    if run.cancellation_requested:
        return {
            "failure_origin": "provider_cancellation",
            "retry_policy": "wait_same_generation",
            "automatic_retry_allowed": False,
        }
    if status in {"submitting", "queued", "running"}:
        return {
            "failure_origin": None,
            "retry_policy": "wait_same_generation",
            "automatic_retry_allowed": False,
        }
    return {
        "failure_origin": None,
        "retry_policy": "none",
        "automatic_retry_allowed": False,
    }


def request_signature(run: PlaygroundRun) -> tuple[str, str]:
    return (str(run.capability), run.parameters_json)


def link_retry(
    document: PlaygroundDocument,
    candidate: PlaygroundRun,
    explicit_retry_of: PlaygroundRun | None,
) -> PlaygroundRun:
    """只把相同参数的重提标记为 retry；显式重试要求原实验仍然可重试。"""
    if explicit_retry_of is None:
        signature = request_signature(candidate)
        for previous in reversed(document.runs):
            if request_signature(previous) != signature:
                continue
            if previous.phase in _RETRYABLE_PHASES:
                return replace(candidate, retry_of=previous.id)
            return candidate
        return candidate
    previous = next((item for item in document.runs if item.id == explicit_retry_of.id), None)
    if previous is None or previous != explicit_retry_of:
        raise ValueError("待重试的实验已变化或不存在。")
    if previous.dismissed:
        raise ValueError("已隐藏的实验不能直接重试。")
    if previous.phase not in _RETRYABLE_PHASES:
        raise ValueError("只有失败、已取消或提交结果未知的实验可以重试。")
    if request_signature(previous) != request_signature(candidate):
        raise ValueError("参数已变化，不能把新请求伪装为该实验的重试。")
    return replace(candidate, retry_of=previous.id)


def recover_interrupted(
    document: PlaygroundDocument, *, timestamp: str
) -> tuple[PlaygroundDocument, bool]:
    """启动恢复：提交中的 run 标记为 submission_uncertain（不自动重试）。"""
    recovered = tuple(
        replace(
            transition_run(
                run,
                RunPhase.SUBMISSION_UNCERTAIN,
                message="Core 在提交期间重启，外部任务是否创建未知；系统不会自动重试。",
                error_code="core_restarted_during_submit",
            ),
            updated_at=timestamp,
        )
        if run.phase is RunPhase.SUBMITTING
        else run
        for run in document.runs
    )
    if recovered == document.runs:
        return document, False
    return replace(document, revision=document.revision + 1, runs=recovered), True


def update_run_durable(
    document: PlaygroundDocument, run: PlaygroundRun, *, timestamp: str
) -> tuple[PlaygroundDocument, bool]:
    """应用 Provider 观察；阶段/错误未变时保留原消息。返回 (document, changed)。"""
    runs = {item.id: item for item in document.runs}
    if run.id not in runs:
        raise ValueError("实验不存在。")
    previous = runs[run.id]
    durable = replace(run, progress=previous.progress)
    if run.phase == previous.phase and run.error_code == previous.error_code:
        durable = replace(durable, message=previous.message)
    if durable == previous:
        return document, False
    durable = replace(durable, created_at=previous.created_at, updated_at=timestamp)
    runs[run.id] = durable
    return replace(document, revision=document.revision + 1, runs=tuple(runs.values())), True
