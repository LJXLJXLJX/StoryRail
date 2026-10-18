from __future__ import annotations

from dataclasses import replace

from core.model_providers.boundary import (
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)

from .models import (
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    transition_generation,
)


def _next_generation_seed(
    document: StructuredDirectorDocument,
    kind: ReferenceGenerationKind,
    target_id: str,
    initial_seed: int,
    *,
    maximum: int = 2**63 - 1,
    language: NarrationLanguage | None = None,
) -> int:
    """每次持久化提交消耗一个 seed；失败、取消和隐藏的记录也不重复使用。

    旁白按语言各自递增 seed，中英文互不影响。
    """
    if not 0 <= initial_seed <= maximum:
        raise ValueError("Seed 超出 Provider 支持范围。")
    previous = next(
        (
            item.seed
            for item in reversed(document.generations)
            if item.kind is kind
            and item.target_id == target_id
            and item.language is language
            and item.seed is not None
        ),
        None,
    )
    if previous is None:
        return initial_seed
    if previous == maximum:
        raise ValueError("Seed 已达到 Provider 上限，无法继续递增。")
    return max(initial_seed, previous + 1)


def _link_retry(
    document: StructuredDirectorDocument,
    candidate: ReferenceGeneration,
) -> ReferenceGeneration:
    """只把相同规范化请求的失败后重提标记为 retry。"""

    signature = _generation_request_signature(candidate)
    for previous in reversed(document.generations):
        if _generation_request_signature(previous) != signature:
            continue
        if previous.phase in {
            ReferenceGenerationPhase.FAILED,
            ReferenceGenerationPhase.CANCELLED,
            ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        }:
            return replace(candidate, retry_of=previous.id)
        return candidate
    return candidate


def _link_generation_retry(
    document: StructuredDirectorDocument,
    candidate: ReferenceGeneration,
    explicit_retry_of: ReferenceGeneration | None,
) -> ReferenceGeneration:
    if explicit_retry_of is None:
        return _link_retry(document, candidate)
    previous = next(
        (item for item in document.generations if item.id == explicit_retry_of.id),
        None,
    )
    if previous is None or previous != explicit_retry_of:
        raise ValueError("待重试的 Generation 已变化或不存在。")
    if previous.dismissed:
        raise ValueError("已隐藏的 Generation 不能直接重试。")
    if previous.phase not in {
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
    }:
        raise ValueError("只有失败、已取消或提交结果未知的 Generation 可以重试。")
    if _generation_request_signature(previous) != _generation_request_signature(candidate):
        raise ValueError("当前项目输入已变化，不能把新请求伪装为该 Generation 的重试。")
    return replace(candidate, retry_of=previous.id)


def _generation_request_signature(generation: ReferenceGeneration) -> tuple[object, ...]:
    return (
        generation.kind,
        generation.operation,
        generation.target_id,
        generation.prompt_text,
        generation.input_asset_ids,
        generation.sample_text,
        generation.seed,
        generation.duration_seconds,
        generation.aspect_ratio,
        generation.panorama_capture_request,
    )


def _generation_wait_data(generation: ReferenceGeneration) -> dict[str, object]:
    return {
        "generation_id": generation.id,
        "phase": generation.phase.value,
        "progress": generation.progress,
        "message": generation.message,
        "error_code": generation.error_code,
        "cancellation_requested": generation.cancellation_requested,
        "dismissed": generation.dismissed,
        "output_asset_id": generation.output_asset_id,
        "created_at": generation.created_at,
        "updated_at": generation.updated_at,
        "retry_of": generation.retry_of,
        "recovery": _generation_recovery(generation),
    }


def _generation_recovery(generation: ReferenceGeneration) -> dict[str, object]:
    status = generation.phase.value
    if status == "submission_uncertain":
        return {
            "failure_origin": "provider_submission",
            "retry_policy": "inspect_then_explicit_generation_retry",
            "automatic_retry_allowed": False,
        }
    if generation.error_code == "submission_rejected":
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
    if generation.error_code == "artifact_import_failed":
        return {
            "failure_origin": "artifact_import",
            "retry_policy": "wait_same_generation",
            "automatic_retry_allowed": False,
        }
    if generation.cancellation_requested:
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


def _provider_handle(generation: ReferenceGeneration) -> ProviderHandle:
    if (
        generation.plugin_id is None
        or generation.plugin_version is None
        or generation.external_id is None
    ):
        raise ValueError("Generation 没有可恢复的 Provider handle。")
    return ProviderHandle(
        generation.plugin_id,
        generation.plugin_version,
        generation.external_id,
    )


def _phase(phase: GenerationPhase) -> ReferenceGenerationPhase:
    return ReferenceGenerationPhase(phase.value)


def _provider_error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, ModelProviderError) else "provider_error"


def _submission_failure(
    generation: ReferenceGeneration,
    exc: Exception,
    *,
    capability: str,
) -> ReferenceGeneration:
    code = _provider_error_code(exc)
    if code == "external_error":
        return transition_generation(
            generation,
            ReferenceGenerationPhase.FAILED,
            message=(
                f"问题出在任务提交：{capability}服务明确拒绝了请求，"
                "没有建立可恢复任务。请检查服务配置或请求参数后重试。"
            ),
            error_code="submission_rejected",
        )
    if code == "invalid_response":
        return transition_generation(
            generation,
            ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
            message=(
                f"问题出在提交响应校验：{capability}服务已经响应，但返回格式不符合当前插件约定。"
                "Core 没有拿到可恢复句柄；任务可能已被服务接受，因此不会自动重试。"
            ),
            error_code=code,
        )
    if code == "transport_error":
        return transition_generation(
            generation,
            ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
            message=(
                f"问题出在提交传输：Core 无法确认请求是否到达{capability}服务。"
                "请检查模型节点、网络和服务状态后手动重试；系统不会自动重试。"
            ),
            error_code=code,
        )
    return transition_generation(
        generation,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        message=(
            f"问题出在 Core 的{capability}插件提交阶段：无法确认外部任务是否已经建立，"
            "因此不会自动重试。"
        ),
        error_code=code,
    )
