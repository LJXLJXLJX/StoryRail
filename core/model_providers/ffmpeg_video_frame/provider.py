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
from core.model_providers.contracts import VideoFrameRequest as VideoFrameContract
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success

_IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
)


@dataclass(frozen=True, slots=True)
class VideoFrameRequest:
    content: bytes
    frame_index: int

    def __post_init__(self):
        if (
            len(self.content) < 12
            or self.content[4:8] != b"ftyp"
            or len(self.content) > 512 * 1024 * 1024
        ):
            raise ValueError("抽帧输入必须是受限 MP4 字节。")
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError("抽帧帧号必须是非负整数。")


def to_request(contract: VideoFrameContract) -> VideoFrameRequest:
    return VideoFrameRequest(contract.content, contract.frame_index)


class FFmpegVideoFrameProvider:
    plugin_id = "ffmpeg.video_frame"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: VideoFrameContract | VideoFrameRequest) -> ProviderHandle:
        if not isinstance(request, VideoFrameRequest):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/ffmpeg/video-frames",
                json_body={
                    "mime": "video/mp4",
                    "base64": base64.b64encode(request.content).decode("ascii"),
                    "frame_index": request.frame_index,
                },
            ),
            {202},
        )
        require_keys(data, required={"frame_id"})
        frame_id = data["frame_id"]
        if not isinstance(frame_id, str) or not frame_id:
            raise ModelProviderError("invalid_response", "FFmpeg frame_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, frame_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        frame_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/ffmpeg/video-frames/{quote(frame_id)}"),
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
            str(data.get("error_code") or "ffmpeg_video_frame_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        frame_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT",
                f"{self._endpoint}/ffmpeg/video-frames/{quote(frame_id)}/abort",
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        frame_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/ffmpeg/video-frames/{quote(frame_id)}/movie/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "抽帧图片不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 FFmpeg Video Frame 插件。")
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
