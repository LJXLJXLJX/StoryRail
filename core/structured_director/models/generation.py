"""领域模型：generation 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from core.model_providers.manifest import ProviderSnapshot
from core.model_providers.recipe import RecipeParams

from ._shared import (
    GenerationOperation,
    NarrationLanguage,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)

if TYPE_CHECKING:
    from ..video_contracts import VideoFrameRequest, VideoInputSnapshot
    from .location import PanoramaCaptureRequest


_GENERATION_TRANSITIONS = {
    ReferenceGenerationPhase.SUBMITTING: {
        ReferenceGenerationPhase.QUEUED,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        ReferenceGenerationPhase.FAILED,
    },
    ReferenceGenerationPhase.QUEUED: {
        ReferenceGenerationPhase.QUEUED,
        ReferenceGenerationPhase.RUNNING,
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
    },
    ReferenceGenerationPhase.RUNNING: {
        ReferenceGenerationPhase.RUNNING,
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
    },
}


@dataclass(frozen=True, slots=True)
class ReferenceGeneration:
    id: str
    kind: ReferenceGenerationKind
    operation: GenerationOperation
    target_id: str
    phase: ReferenceGenerationPhase
    progress: float
    message: str
    prompt_text: str
    input_asset_ids: tuple[str, ...]
    sample_text: str | None
    seed: int | None
    plugin_id: str | None
    plugin_version: int | None
    external_id: str | None
    output_asset_id: str | None
    error_code: str | None
    cancellation_requested: bool
    retry_of: str | None
    duration_seconds: float | None = None
    dismissed: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    video_frame_request: VideoFrameRequest | None = None
    video_input_snapshot: VideoInputSnapshot | None = None
    # 旁白音色、旁白音频、Scene 成片与最终成片按语言各自生成；其它 Generation 为 None。
    language: NarrationLanguage | None = None
    # 提交时实际使用的插件、recipe 与生效设置；Core 确定性工具与测试替身为 None。
    provider_snapshot: ProviderSnapshot | None = None
    # 实际提交的插件机制参数（按 provider_snapshot.recipe_id 记录一条）；重试按原值提交。
    recipe_params: RecipeParams = RecipeParams()
    # 角色参考图可指定非项目画幅的比例，地点全景图固定 2:1；None 表示跟随项目画幅。
    aspect_ratio: str | None = None
    # 仅全景取景：提交时冻结源全景 Asset 与绝对机位。
    panorama_capture_request: PanoramaCaptureRequest | None = None

    def __post_init__(self) -> None:
        validate_reference_generation(self)


def transition_generation(
    generation: ReferenceGeneration,
    phase: ReferenceGenerationPhase,
    *,
    progress: float | None = None,
    message: str | None = None,
    error_code: str | None = None,
    plugin_id: str | None = None,
    plugin_version: int | None = None,
    external_id: str | None = None,
    output_asset_id: str | None = None,
    cancellation_requested: bool | None = None,
) -> ReferenceGeneration:
    """执行唯一受支持的 Generation 状态迁移。"""
    if phase not in _GENERATION_TRANSITIONS.get(generation.phase, set()):
        raise ValueError(f"Generation 不能从 {generation.phase.value} 迁移到 {phase.value}。")
    return replace(
        generation,
        phase=phase,
        progress=generation.progress if progress is None else progress,
        message=generation.message if message is None else message,
        error_code=error_code,
        plugin_id=generation.plugin_id if plugin_id is None else plugin_id,
        plugin_version=(generation.plugin_version if plugin_version is None else plugin_version),
        external_id=generation.external_id if external_id is None else external_id,
        output_asset_id=output_asset_id,
        cancellation_requested=(
            generation.cancellation_requested
            if cancellation_requested is None
            else cancellation_requested
        ),
    )


def unresolved_uncertain_ids(generations) -> frozenset[str]:
    """提交结果未知、且尚未被隐藏或显式重试的 Generation。

    这类任务没有可观察的 Provider 句柄，只能由人或 Agent 核查后处理：隐藏表示放弃，
    重试由新 Generation 接替。处理之前它仍占用目标并计入活动任务；处理之后不再阻塞。
    """
    retried = {item.retry_of for item in generations if item.retry_of is not None}
    return frozenset(
        item.id
        for item in generations
        if item.phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN
        and not item.dismissed
        and item.id not in retried
    )


def _set_validator(validate) -> None:
    """由 models/__init__ 在包加载末尾注入校验函数（避免静态 import 环）。

    __post_init__ 在实例化时才解析模块全局 ``validate_reference_generation``；
    任何实例化路径都先完成父包初始化，因此注入必然已发生。
    """
    global validate_reference_generation
    validate_reference_generation = validate
