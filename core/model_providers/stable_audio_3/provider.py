from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from urllib.parse import quote

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success
from core.model_providers.recipe import RecipeRequest


@dataclass(frozen=True, slots=True)
class StableAudio3Request:
    prompt: str
    duration_seconds: float
    seed: int

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt) > 1000:
            raise ValueError("文生音频提示词必须是 1 到 1000 个字符。")
        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, (int, float))
            or not isfinite(self.duration_seconds)
            or not 1 <= self.duration_seconds <= 380
        ):
            raise ValueError("文生音频时长必须在 1 到 380 秒之间。")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("文生音频 seed 不合法。")


def to_request(contract: RecipeRequest) -> StableAudio3Request:
    return StableAudio3Request(
        str(contract.param("prompt")),
        float(contract.param("duration_seconds")),
        int(contract.param("seed")),
    )


class StableAudio3Provider:
    plugin_id = "stable-audio-3.medium"
    plugin_version = 1

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        return self.submit(to_request(request))

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: RecipeRequest | StableAudio3Request) -> ProviderHandle:
        if not isinstance(request, StableAudio3Request):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/stable-audio-3/generations",
                json_body={
                    "prompt": request.prompt,
                    "duration_seconds": request.duration_seconds,
                    "seed": request.seed,
                },
            ),
            {202},
        )
        require_keys(data, required={"generation_id"})
        task_id = data["generation_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ModelProviderError("invalid_response", "Stable Audio generation_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle) -> GenerationObservation:
        task_id = self._id(handle)
        data = require_success(
            self._http.request(
                "GET", f"{self._endpoint}/stable-audio-3/generations/{quote(task_id)}"
            ),
            {200},
        )
        require_keys(
            data,
            required={"stage", "progress", "message"},
            optional={"audio", "error_code", "retryable"},
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "generating": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "Stable Audio stage 不合法。")
        artifact = _audio(data.get("audio")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "text_to_audio_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle) -> GenerationObservation:
        task_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT",
                f"{self._endpoint}/stable-audio-3/generations/{quote(task_id)}/abort",
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle, artifact_id: str) -> bytes:
        task_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/stable-audio-3/generations/{quote(task_id)}/audio/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "文生音频产物不可用。")
        return response.body

    def _id(self, handle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 Stable Audio 3 插件。")
        return handle.external_id


def _audio(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "Stable Audio 完成响应缺少 audio。")
    require_keys(
        value,
        required={"id", "mime", "bytes", "sha256"},
        optional={"duration_seconds"},
    )
    return ArtifactDescriptor(
        str(value["id"]),
        str(value["mime"]),
        int(value["bytes"]),
        str(value["sha256"]),
        None if value.get("duration_seconds") is None else float(value["duration_seconds"]),
    )
