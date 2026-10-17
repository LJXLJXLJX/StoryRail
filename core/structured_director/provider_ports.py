from __future__ import annotations

from typing import Protocol

from core.model_providers.boundary import (
    GenerationObservation,
    ProviderHandle,
)
from core.model_providers.contracts import (
    AnimaticRequest,
    AudioRemixRequest,
    FinalAssemblyRequest,
    PanoViewRequest,
    VideoFrameRequest,
)
from core.model_providers.recipe import RecipeRequest


class RecipeProvider(Protocol):
    """按插件 recipe 提交的实现：Core 构造经 manifest 校验的 RecipeRequest。"""

    plugin_id: str
    plugin_version: int

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle: ...

    def observe(self, handle: ProviderHandle) -> GenerationObservation: ...

    def cancel(self, handle: ProviderHandle) -> GenerationObservation: ...

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes: ...


class FinalAssemblyProvider(Protocol):
    plugin_id: str
    plugin_version: int

    def submit(self, request: FinalAssemblyRequest) -> ProviderHandle: ...

    def observe(self, handle: ProviderHandle) -> GenerationObservation: ...

    def cancel(self, handle: ProviderHandle) -> GenerationObservation: ...

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes: ...


class AnimaticProvider(Protocol):
    plugin_id: str
    plugin_version: int

    def submit(self, request: AnimaticRequest) -> ProviderHandle: ...

    def observe(self, handle: ProviderHandle) -> GenerationObservation: ...

    def cancel(self, handle: ProviderHandle) -> GenerationObservation: ...

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes: ...


class VideoFrameProvider(Protocol):
    plugin_id: str
    plugin_version: int

    def submit(self, request: VideoFrameRequest) -> ProviderHandle: ...

    def observe(self, handle: ProviderHandle) -> GenerationObservation: ...

    def cancel(self, handle: ProviderHandle) -> GenerationObservation: ...

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes: ...


class PanoViewProvider(Protocol):
    plugin_id: str
    plugin_version: int

    def submit(self, request: PanoViewRequest) -> ProviderHandle: ...

    def observe(self, handle: ProviderHandle) -> GenerationObservation: ...

    def cancel(self, handle: ProviderHandle) -> GenerationObservation: ...

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes: ...


class AudioRemixProvider(Protocol):
    plugin_id: str
    plugin_version: int

    def submit(self, request: AudioRemixRequest) -> ProviderHandle: ...

    def observe(self, handle: ProviderHandle) -> GenerationObservation: ...

    def cancel(self, handle: ProviderHandle) -> GenerationObservation: ...

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes: ...
