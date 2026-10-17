from __future__ import annotations

import base64
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
from core.model_providers.contracts import AudioRemixRequest
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success


@dataclass(frozen=True, slots=True)
class FFmpegAudioRemixRequest:
    video: bytes
    voice: bytes
    background: bytes
    voice_gain_db: float
    background_gain_db: float
    voice_gain_start_seconds: float | None = None
    voice_gain_end_seconds: float | None = None
    background_gain_start_seconds: float | None = None
    background_gain_end_seconds: float | None = None

    def __post_init__(self) -> None:
        if not 12 <= len(self.video) <= 512 * 1024 * 1024 or self.video[4:8] != b"ftyp":
            raise ValueError("音轨混音输入必须是真实 MP4。")
        for content in (self.voice, self.background):
            if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
                raise ValueError("音轨混音输入必须是真实 WAV。")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or not -100 <= value <= 24
            for value in (self.voice_gain_db, self.background_gain_db)
        ):
            raise ValueError("音轨增益必须在 -100 到 24 dB 之间。")
        _validate_range(
            self.voice_gain_start_seconds,
            self.voice_gain_end_seconds,
            "人声音量",
        )
        _validate_range(
            self.background_gain_start_seconds,
            self.background_gain_end_seconds,
            "背景声音量",
        )


def to_request(contract: AudioRemixRequest) -> FFmpegAudioRemixRequest:
    return FFmpegAudioRemixRequest(
        contract.video,
        contract.voice,
        contract.background,
        contract.voice_gain_db,
        contract.background_gain_db,
        contract.voice_gain_start_seconds,
        contract.voice_gain_end_seconds,
        contract.background_gain_start_seconds,
        contract.background_gain_end_seconds,
    )


class FFmpegAudioRemixProvider:
    plugin_id = "ffmpeg.audio-remix"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: AudioRemixRequest | FFmpegAudioRemixRequest) -> ProviderHandle:
        if not isinstance(request, FFmpegAudioRemixRequest):
            request = to_request(request)

        def media(mime: str, content: bytes) -> dict[str, str]:
            return {"mime": mime, "base64": base64.b64encode(content).decode("ascii")}

        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/ffmpeg/audio-remixes",
                json_body={
                    "video": media("video/mp4", request.video),
                    "voice": media("audio/wav", request.voice),
                    "background": media("audio/wav", request.background),
                    "voice_gain_db": request.voice_gain_db,
                    "background_gain_db": request.background_gain_db,
                    "voice_gain_start_seconds": request.voice_gain_start_seconds,
                    "voice_gain_end_seconds": request.voice_gain_end_seconds,
                    "background_gain_start_seconds": request.background_gain_start_seconds,
                    "background_gain_end_seconds": request.background_gain_end_seconds,
                },
            ),
            {202},
        )
        require_keys(data, required={"remix_id"})
        task_id = data["remix_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ModelProviderError("invalid_response", "FFmpeg remix_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        task_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/ffmpeg/audio-remixes/{quote(task_id)}"),
            {200},
        )
        require_keys(
            data,
            required={"stage", "progress", "message"},
            optional={"movie", "error_code", "retryable"},
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "remixing": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "FFmpeg remix stage 不合法。")
        artifact = _movie(data.get("movie")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "audio_remix_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        task_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT", f"{self._endpoint}/ffmpeg/audio-remixes/{quote(task_id)}/abort"
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        task_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/ffmpeg/audio-remixes/{quote(task_id)}/movie/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "音轨混音视频不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 FFmpeg 音轨混音插件。")
        return handle.external_id


def _validate_range(start: float | None, end: float | None, label: str) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{label}开始和结束时间必须同时提供或同时省略。")
    if start is None or end is None:
        return
    if (
        any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in (start, end)
        )
        or start < 0
        or end <= start
    ):
        raise ValueError(f"{label}时间范围不合法。")


def _movie(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "FFmpeg 完成响应缺少 movie。")
    require_keys(value, required={"id", "mime", "bytes", "sha256"}, optional={"duration_seconds"})
    return ArtifactDescriptor(
        str(value["id"]),
        str(value["mime"]),
        int(value["bytes"]),
        str(value["sha256"]),
        None if value.get("duration_seconds") is None else float(value["duration_seconds"]),
    )
