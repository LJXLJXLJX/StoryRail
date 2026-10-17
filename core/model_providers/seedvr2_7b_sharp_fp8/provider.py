from __future__ import annotations

import base64
from dataclasses import dataclass
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
class SeedVR2Video:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type != "video/mp4" or not self.content:
            raise ValueError("SeedVR2 输入必须是非空 MP4。")
        if len(self.content) > 512 * 1024 * 1024:
            raise ValueError("SeedVR2 输入视频过大。")


@dataclass(frozen=True, slots=True)
class SeedVR2UpscaleRequest:
    video: SeedVR2Video
    target_short_side: int = 720
    max_long_side: int = 1280
    seed: int = 42

    def __post_init__(self) -> None:
        if not isinstance(self.video, SeedVR2Video):
            raise ValueError("SeedVR2 输入必须是非空 MP4。")
        if self.target_short_side not in {720, 1080, 1440}:
            raise ValueError("SeedVR2 target_short_side 不受支持。")
        if self.max_long_side not in {1280, 1920, 2560}:
            raise ValueError("SeedVR2 max_long_side 不受支持。")
        if not 0 <= self.seed <= 2**63 - 1:
            raise ValueError("SeedVR2 seed 不合法。")


def to_request(contract: RecipeRequest) -> SeedVR2UpscaleRequest:
    video = contract.slot("video")[0]
    return SeedVR2UpscaleRequest(
        SeedVR2Video(video.media_type, video.content), seed=int(contract.param("seed"))
    )


class SeedVR2SevenBSharpFP8Provider:
    plugin_id = "seedvr2.7b-sharp-fp8"
    plugin_version = 1

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        return self.submit(to_request(request))

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: RecipeRequest | SeedVR2UpscaleRequest) -> ProviderHandle:
        if not isinstance(request, SeedVR2UpscaleRequest):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/seedvr2/7b-sharp-fp8/upscales",
                json_body={
                    "source_video": {
                        "mime": request.video.media_type,
                        "base64": base64.b64encode(request.video.content).decode("ascii"),
                    },
                    "target_short_side": request.target_short_side,
                    "max_long_side": request.max_long_side,
                    "seed": request.seed,
                },
            ),
            {202},
        )
        require_keys(data, required={"job_token", "queue_position"})
        token = data["job_token"]
        if not isinstance(token, str) or not token:
            raise ModelProviderError("invalid_response", "SeedVR2 job_token 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, token)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        token = self._token(handle)
        data = require_success(
            self._http.request(
                "GET", f"{self._endpoint}/seedvr2/7b-sharp-fp8/upscales/{quote(token)}"
            ),
            {200},
        )
        require_keys(
            data,
            required={"stage", "ratio", "description"},
            optional={
                "movie",
                "error_tag",
                "can_retry",
            },
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "generating": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "error": GenerationPhase.FAILED,
            "stopped": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "SeedVR2 stage 不合法。")
        artifact = (
            _movie_artifact(data.get("movie")) if phase is GenerationPhase.SUCCEEDED else None
        )
        return GenerationObservation(
            phase,
            float(data["ratio"]),
            str(data["description"]),
            artifact,
            str(data.get("error_tag") or "seedvr2_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("can_retry", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        token = self._token(handle)
        require_success(
            self._http.request(
                "PUT", f"{self._endpoint}/seedvr2/7b-sharp-fp8/upscales/{quote(token)}/abort"
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        token = self._token(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/seedvr2/7b-sharp-fp8/upscales/{quote(token)}/movie/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "SeedVR2 视频不可用。")
        return response.body

    def _token(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 SeedVR2 插件。")
        return handle.external_id


def _movie_artifact(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "SeedVR2 完成响应缺少 movie。")
    require_keys(
        value,
        required={"key", "mime", "length", "digest"},
        optional={"duration_seconds"},
    )
    return ArtifactDescriptor(
        str(value["key"]),
        str(value["mime"]),
        int(value["length"]),
        str(value["digest"]),
        None if value.get("duration_seconds") is None else float(value["duration_seconds"]),
    )
