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
from core.model_providers.contracts import AnimaticRequest as AnimaticContract
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success

_IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
)


@dataclass(frozen=True, slots=True)
class AnimaticClipInput:
    content: bytes
    transition_from_previous: str | None
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("Animatic 关键帧图片大小不合法。")
        if not self.content.startswith(_IMAGE_SIGNATURES):
            raise ValueError("Animatic 关键帧图片必须是 PNG 或 JPEG。")
        if self.transition_from_previous not in {None, "seam_blend"}:
            raise ValueError("Animatic 转场类型不受支持。")
        if not 0.05 <= self.duration_seconds <= 600:
            raise ValueError("Animatic 片段目标时长不合法。")


@dataclass(frozen=True, slots=True)
class AnimaticNarrationInput:
    content: bytes
    start_clip_index: int

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("Animatic 旁白音频大小不合法。")
        if len(self.content) < 12 or self.content[:4] != b"RIFF" or self.content[8:12] != b"WAVE":
            raise ValueError("Animatic 旁白音频必须是真实 WAV。")
        if isinstance(self.start_clip_index, bool) or not 0 <= self.start_clip_index < 500:
            raise ValueError("Animatic 旁白起始片段索引不合法。")


@dataclass(frozen=True, slots=True)
class AnimaticRequest:
    clips: tuple[AnimaticClipInput, ...]
    narrations: tuple[AnimaticNarrationInput, ...]
    aspect_ratio: str
    transition_seconds: float = 0.1

    def __post_init__(self) -> None:
        if not 1 <= len(self.clips) <= 500:
            raise ValueError("Animatic 必须包含 1 到 500 个片段。")
        if len(self.narrations) > 200:
            raise ValueError("Animatic 旁白数量过多。")
        if any(item.start_clip_index >= len(self.clips) for item in self.narrations):
            raise ValueError("Animatic 旁白起始片段不存在。")
        if self.aspect_ratio not in {"16:9", "9:16", "2:1"}:
            raise ValueError("Animatic 画幅只允许 16:9、9:16 或 2:1。")
        if not 0.1 <= self.transition_seconds <= 1.0:
            raise ValueError("Animatic 转场时长不合法。")


def to_request(contract: AnimaticContract) -> AnimaticRequest:
    return AnimaticRequest(
        tuple(
            AnimaticClipInput(item.content, item.transition_from_previous, item.duration_seconds)
            for item in contract.clips
        ),
        tuple(
            AnimaticNarrationInput(item.content, item.start_clip_index)
            for item in contract.narrations
        ),
        contract.aspect_ratio,
        contract.transition_seconds,
    )


class FFmpegAnimaticProvider:
    plugin_id = "ffmpeg.animatic"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: AnimaticContract | AnimaticRequest) -> ProviderHandle:
        if not isinstance(request, AnimaticRequest):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/ffmpeg/animatics",
                json_body={
                    "aspect_ratio": request.aspect_ratio,
                    "transition_seconds": request.transition_seconds,
                    "clips": [
                        {
                            "mime": "image/png"
                            if item.content.startswith(b"\x89PNG")
                            else "image/jpeg",
                            "base64": base64.b64encode(item.content).decode("ascii"),
                            "transition_from_previous": item.transition_from_previous,
                            "duration_seconds": item.duration_seconds,
                        }
                        for item in request.clips
                    ],
                    "narrations": [
                        {
                            "mime": "audio/wav",
                            "base64": base64.b64encode(item.content).decode("ascii"),
                            "start_clip_index": item.start_clip_index,
                        }
                        for item in request.narrations
                    ],
                },
            ),
            {202},
        )
        require_keys(data, required={"animatic_id"})
        animatic_id = data["animatic_id"]
        if not isinstance(animatic_id, str) or not animatic_id:
            raise ModelProviderError("invalid_response", "FFmpeg animatic_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, animatic_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        animatic_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/ffmpeg/animatics/{quote(animatic_id)}"),
            {200},
        )
        require_keys(
            data,
            required={"stage", "progress", "message"},
            optional={"movie", "error_code", "retryable"},
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "assembling": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "FFmpeg stage 不合法。")
        artifact = _movie(data.get("movie")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "ffmpeg_animatic_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        animatic_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT",
                f"{self._endpoint}/ffmpeg/animatics/{quote(animatic_id)}/abort",
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        animatic_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/ffmpeg/animatics/{quote(animatic_id)}/movie/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "Animatic 预览不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 FFmpeg Animatic 插件。")
        return handle.external_id


def _movie(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "FFmpeg 完成响应缺少 movie。")
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
