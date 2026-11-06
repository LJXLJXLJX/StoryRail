"""Core 消化模型插件结果所需的最小内部边界。

这些类型不是外部 Provider RPC。每个插件的提交请求和外部 API 仍然独立。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GenerationPhase(StrEnum):
    """Core 可以持久化和展示的模型调用观察结果。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProviderHandle:
    """具体插件返回给 Core 的不透明、可持久化调用句柄。"""

    plugin_id: str
    plugin_version: int
    external_id: str


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """已完成输出的受控描述；Core 必须再通过插件读取字节。"""

    artifact_id: str
    media_type: str
    byte_count: int
    sha256: str
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds 必须大于 0。")


@dataclass(frozen=True, slots=True)
class GenerationObservation:
    phase: GenerationPhase
    progress: float
    message: str
    artifact: ArtifactDescriptor | None = None
    error_code: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("progress 必须在 0 到 1 之间。")
        if self.phase is GenerationPhase.SUCCEEDED and self.artifact is None:
            raise ValueError("succeeded 观察结果必须包含 artifact。")
        if self.phase is not GenerationPhase.SUCCEEDED and self.artifact is not None:
            raise ValueError("非 succeeded 观察结果不能包含 artifact。")
        if self.phase is GenerationPhase.FAILED and not self.error_code:
            raise ValueError("failed 观察结果必须包含 error_code。")


class ModelProviderError(RuntimeError):
    """插件拒绝了外部响应，或外部服务无法安全调用。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
