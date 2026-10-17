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
from core.model_providers.contracts import FinalAssemblyRequest as AssemblyContract
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success


@dataclass(frozen=True, slots=True)
class FinalAssemblyClipInput:
    content: bytes
    transition_from_previous: str | None
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > 512 * 1024 * 1024:
            raise ValueError("成片片段大小不合法。")
        if len(self.content) < 12 or self.content[4:8] != b"ftyp":
            raise ValueError("成片片段必须是真实 MP4。")
        if self.transition_from_previous not in {None, "seam_blend"}:
            raise ValueError("成片转场类型不受支持。")
        if not 0.05 <= self.duration_seconds <= 600:
            raise ValueError("成片片段目标时长不合法。")


@dataclass(frozen=True, slots=True)
class FinalAssemblyNarrationInput:
    content: bytes
    start_clip_index: int

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("旁白音频大小不合法。")
        if len(self.content) < 12 or self.content[:4] != b"RIFF" or self.content[8:12] != b"WAVE":
            raise ValueError("旁白音频必须是真实 WAV。")
        if isinstance(self.start_clip_index, bool) or self.start_clip_index < 0:
            raise ValueError("旁白起始片段索引不合法。")


@dataclass(frozen=True, slots=True)
class FinalAssemblyRequest:
    clips: tuple[FinalAssemblyClipInput, ...]
    narrations: tuple[FinalAssemblyNarrationInput, ...]
    aspect_ratio: str
    transition_seconds: float = 0.1
    video_audio_volume: float = 1.0
    narration_audio_volume: float = 1.0

    def __post_init__(self) -> None:
        if not 1 <= len(self.clips) <= 500:
            raise ValueError("成片必须包含 1 到 500 个片段。")
        if self.clips[0].transition_from_previous is not None:
            raise ValueError("首个片段不能包含入场转场。")
        if len(self.narrations) > 200:
            raise ValueError("成片旁白数量过多。")
        if any(item.start_clip_index >= len(self.clips) for item in self.narrations):
            raise ValueError("旁白起始片段不存在。")
        if self.aspect_ratio not in {"16:9", "9:16", "2:1"}:
            raise ValueError("成片画幅只允许 16:9、9:16 或 2:1。")
        if not 0.1 <= self.transition_seconds <= 1.0:
            raise ValueError("转场时长不合法。")
        for value, label in (
            (self.video_audio_volume, "视频自带音频音量"),
            (self.narration_audio_volume, "旁白音频音量"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= value <= 2.0
            ):
                raise ValueError(f"{label}必须在 0 到 2 之间。")


def to_request(contract: AssemblyContract) -> FinalAssemblyRequest:
    return FinalAssemblyRequest(
        tuple(
            FinalAssemblyClipInput(
                item.content, item.transition_from_previous, item.duration_seconds
            )
            for item in contract.clips
        ),
        tuple(
            FinalAssemblyNarrationInput(item.content, item.start_clip_index)
            for item in contract.narrations
        ),
        contract.aspect_ratio,
        contract.transition_seconds,
        contract.video_audio_volume,
        contract.narration_audio_volume,
    )


class FFmpegFinalAssemblyProvider:
    plugin_id = "ffmpeg.final-assembly"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: AssemblyContract | FinalAssemblyRequest) -> ProviderHandle:
        if not isinstance(request, FinalAssemblyRequest):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/ffmpeg/final-assemblies",
                json_body={
                    "aspect_ratio": request.aspect_ratio,
                    "transition_seconds": request.transition_seconds,
                    "video_audio_volume": request.video_audio_volume,
                    "narration_audio_volume": request.narration_audio_volume,
                    "clips": [
                        {
                            "mime": "video/mp4",
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
        require_keys(data, required={"assembly_id"})
        assembly_id = data["assembly_id"]
        if not isinstance(assembly_id, str) or not assembly_id:
            raise ModelProviderError("invalid_response", "FFmpeg assembly_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, assembly_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        assembly_id = self._id(handle)
        data = require_success(
            self._http.request(
                "GET", f"{self._endpoint}/ffmpeg/final-assemblies/{quote(assembly_id)}"
            ),
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
            str(data.get("error_code") or "ffmpeg_assembly_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        assembly_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT",
                f"{self._endpoint}/ffmpeg/final-assemblies/{quote(assembly_id)}/abort",
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        assembly_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/ffmpeg/final-assemblies/{quote(assembly_id)}/movie/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "最终成片不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 FFmpeg 成片插件。")
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
