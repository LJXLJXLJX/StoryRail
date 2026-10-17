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
class DemucsAudioSeparationRequest:
    video: bytes
    stem: str

    def __post_init__(self) -> None:
        if not 12 <= len(self.video) <= 512 * 1024 * 1024 or self.video[4:8] != b"ftyp":
            raise ValueError("音轨分离输入必须是真实 MP4。")
        if self.stem not in {"voice", "background"}:
            raise ValueError("音轨分离 stem 只允许 voice 或 background。")


def to_request(contract: RecipeRequest) -> DemucsAudioSeparationRequest:
    return DemucsAudioSeparationRequest(
        contract.slot("video")[0].content, str(contract.param("stem"))
    )


class DemucsAudioSeparationProvider:
    plugin_id = "demucs.audio-separation"
    plugin_version = 1

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        return self.submit(to_request(request))

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: RecipeRequest | DemucsAudioSeparationRequest) -> ProviderHandle:
        if not isinstance(request, DemucsAudioSeparationRequest):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/demucs/audio-separations",
                json_body={
                    "video": {
                        "mime": "video/mp4",
                        "base64": base64.b64encode(request.video).decode("ascii"),
                    },
                    "stem": request.stem,
                },
            ),
            {202},
        )
        require_keys(data, required={"separation_id"})
        task_id = data["separation_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ModelProviderError("invalid_response", "Demucs separation_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        task_id = self._id(handle)
        data = require_success(
            self._http.request(
                "GET", f"{self._endpoint}/demucs/audio-separations/{quote(task_id)}"
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
            "separating": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "Demucs stage 不合法。")
        artifact = _audio(data.get("audio")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "audio_separation_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        task_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT", f"{self._endpoint}/demucs/audio-separations/{quote(task_id)}/abort"
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        task_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/demucs/audio-separations/{quote(task_id)}/audio/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "分离音轨不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 Demucs 音轨分离插件。")
        return handle.external_id


def _audio(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "Demucs 完成响应缺少 audio。")
    require_keys(value, required={"id", "mime", "bytes", "sha256"}, optional={"duration_seconds"})
    return ArtifactDescriptor(
        str(value["id"]),
        str(value["mime"]),
        int(value["bytes"]),
        str(value["sha256"]),
        None if value.get("duration_seconds") is None else float(value["duration_seconds"]),
    )
