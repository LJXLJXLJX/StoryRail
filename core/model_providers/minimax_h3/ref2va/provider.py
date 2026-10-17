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
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success
from core.model_providers.minimax_h3.contracts import Ref2VARequest, ReferenceImage
from core.model_providers.minimax_h3.requests import to_request as recipe_to_request


@dataclass(frozen=True, slots=True)
class H3ReferenceFrame:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("参考图片类型不受支持。")
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("参考图片大小不合法。")


@dataclass(frozen=True, slots=True)
class H3ReferenceAudio:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type != "audio/wav":
            raise ValueError("H3 参考音频只接受 WAV。")
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("H3 参考音频大小不合法。")


@dataclass(frozen=True, slots=True)
class H3ReferenceVideo:
    media_type: str
    content: bytes
    duration_seconds: float

    def __post_init__(self) -> None:
        if self.media_type != "video/mp4":
            raise ValueError("H3 参考视频只接受 MP4。")
        if (
            len(self.content) < 12
            or len(self.content) > 512 * 1024 * 1024
            or self.content[4:8] != b"ftyp"
        ):
            raise ValueError("H3 参考视频必须是真实 MP4。")
        if not 2.0 <= self.duration_seconds <= 15.0:
            raise ValueError("H3 参考视频时长必须在 2 到 15 秒之间。")


@dataclass(frozen=True, slots=True)
class MiniMaxH3Ref2VARequest:
    prompt: str
    reference_audios: tuple[H3ReferenceAudio, ...]
    first_frame: H3ReferenceFrame | None = None
    last_frame: H3ReferenceFrame | None = None
    additional_frames: tuple[H3ReferenceFrame, ...] = ()
    width: int = 832
    height: int = 480
    duration_seconds: float = 3.0
    seed: int = 42
    steps: int = 20
    cfg: float = 1.0
    save_audio: bool = False
    reference_videos: tuple[H3ReferenceVideo, ...] = ()
    sage_attention: bool = True
    selflift: bool = True

    def __post_init__(self) -> None:
        if not any(
            (
                self.first_frame,
                self.last_frame,
                self.additional_frames,
                self.reference_audios,
                self.reference_videos,
            )
        ):
            raise ValueError("Ref2VA 至少需要一个媒体参考。")
        if (
            not isinstance(self.additional_frames, tuple)
            or len(self.additional_frames) > 4
            or any(not isinstance(item, H3ReferenceFrame) for item in self.additional_frames)
        ):
            raise ValueError("Ref2VA 附加参考图必须是最多 4 项的图片元组。")
        if (
            not isinstance(self.reference_audios, tuple)
            or len(self.reference_audios) > 8
            or any(not isinstance(item, H3ReferenceAudio) for item in self.reference_audios)
        ):
            raise ValueError("Ref2VA 参考音频必须是最多 8 项的元组。")
        if (
            not isinstance(self.reference_videos, tuple)
            or len(self.reference_videos) > 3
            or any(not isinstance(item, H3ReferenceVideo) for item in self.reference_videos)
        ):
            raise ValueError("Ref2VA 参考视频必须是最多 3 项的元组。")
        if not self.prompt or len(self.prompt) > 20_000:
            raise ValueError("prompt 必须是 1 到 20000 字符。")
        if (
            self.width % 32
            or self.height % 32
            or not 256 <= self.width <= 1920
            or not 256 <= self.height <= 1920
        ):
            raise ValueError("画布边长必须是 32 的倍数且在 256 到 1920 之间。")
        if self.width * self.height > 2_100_000:
            raise ValueError("画布像素过大。")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0.2:
            raise ValueError("duration_seconds 必须是不短于 0.2 秒的有限数值。")
        if isinstance(self.steps, bool) or self.steps not in {20, 8}:
            raise ValueError("H3 步数只允许 20 或 8。")
        if not 0 <= self.seed <= 2**63 - 1 or not 0 <= self.cfg <= 30:
            raise ValueError("采样参数不合法。")
        if not isinstance(self.sage_attention, bool) or not isinstance(self.selflift, bool):
            raise ValueError("H3 sage_attention 与 selflift 必须是布尔值。")


def _frame(image: ReferenceImage | None) -> H3ReferenceFrame | None:
    if image is None:
        return None
    return H3ReferenceFrame(image.media_type, image.content)


def to_request(contract: Ref2VARequest) -> MiniMaxH3Ref2VARequest:
    return MiniMaxH3Ref2VARequest(
        contract.prompt,
        tuple(
            H3ReferenceAudio(audio.media_type, audio.content) for audio in contract.reference_audios
        ),
        _frame(contract.first_frame),
        _frame(contract.last_frame),
        tuple(
            H3ReferenceFrame(image.media_type, image.content)
            for image in contract.additional_frames
        ),
        contract.width,
        contract.height,
        contract.duration_seconds,
        contract.seed,
        contract.steps,
        contract.cfg,
        contract.save_audio,
        tuple(
            H3ReferenceVideo(video.media_type, video.content, video.duration_seconds)
            for video in contract.reference_videos
        ),
        contract.sage_attention,
        contract.selflift,
    )


class MiniMaxH3Ref2VAProvider:
    plugin_id = "minimax.h3.ref2va"
    plugin_version = 4

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request):
        return self.submit(recipe_to_request(request))

    def submit(self, request: Ref2VARequest | MiniMaxH3Ref2VARequest) -> ProviderHandle:
        if not isinstance(request, MiniMaxH3Ref2VARequest):
            request = to_request(request)
        payload = {
            "direction": request.prompt,
            "first_reference": _encode(request.first_frame),
            "last_reference": _encode(request.last_frame),
            "additional_references": [_encode(frame) for frame in request.additional_frames],
            "width_px": request.width,
            "height_px": request.height,
            "duration_s": request.duration_seconds,
            "random_seed": request.seed,
            "step_count": request.steps,
            "guidance": request.cfg,
            "sage_attention": request.sage_attention,
            "selflift": request.selflift,
            "audio": request.save_audio,
            "audio_references": [_encode_audio(audio) for audio in request.reference_audios],
            "video_references": [_encode_video(video) for video in request.reference_videos],
        }
        data = require_success(
            self._http.request(
                "POST", f"{self._endpoint}/minimax-h3/ref2va/renders", json_body=payload
            ),
            {202},
        )
        require_keys(data, required={"render_id", "status_uri"})
        render_id = data["render_id"]
        if not isinstance(render_id, str) or not render_id:
            raise ModelProviderError("invalid_response", "Ref2VA render_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, render_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        render_id = self._id(handle)
        data = require_success(
            self._http.request(
                "GET", f"{self._endpoint}/minimax-h3/ref2va/renders/{quote(render_id)}"
            ),
            {200},
        )
        require_keys(
            data,
            required={"status", "progress_0_100", "message"},
            optional={"result", "error", "retry_suggested"},
        )
        phase = {
            "pending": GenerationPhase.QUEUED,
            "processing": GenerationPhase.RUNNING,
            "rendered": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["status"])
        if phase is None:
            raise ModelProviderError("invalid_response", "Ref2VA status 不合法。")
        artifact = _result(data.get("result")) if phase is GenerationPhase.SUCCEEDED else None
        error_code = (
            str(data.get("error") or "h3_ref2va_failed")
            if phase is GenerationPhase.FAILED
            else None
        )
        return GenerationObservation(
            phase,
            float(data["progress_0_100"]) / 100,
            str(data["message"]),
            artifact,
            error_code,
            bool(data.get("retry_suggested", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        render_id = self._id(handle)
        require_success(
            self._http.request(
                "DELETE", f"{self._endpoint}/minimax-h3/ref2va/renders/{quote(render_id)}"
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        render_id = self._id(handle)
        escaped_artifact = quote(artifact_id, safe="")
        response = self._http.request(
            "GET",
            f"{self._endpoint}/minimax-h3/ref2va/renders/{quote(render_id)}/video/"
            f"{escaped_artifact}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "Ref2VA 视频不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 H3 Ref2VA 插件。")
        return handle.external_id


def _encode(image: H3ReferenceFrame | None) -> dict[str, str] | None:
    if image is None:
        return None
    return {
        "media_type": image.media_type,
        "content": base64.b64encode(image.content).decode("ascii"),
    }


def _encode_audio(audio: H3ReferenceAudio) -> dict[str, str]:
    return {
        "media_type": audio.media_type,
        "content": base64.b64encode(audio.content).decode("ascii"),
    }


def _encode_video(video: H3ReferenceVideo) -> dict[str, str]:
    return {
        "media_type": video.media_type,
        "content": base64.b64encode(video.content).decode("ascii"),
    }


def _result(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "Ref2VA 完成响应缺少 result。")
    require_keys(
        value,
        required={"artifact_id", "media_type", "byte_count", "sha256"},
        optional={"duration_seconds"},
    )
    return ArtifactDescriptor(
        str(value["artifact_id"]),
        str(value["media_type"]),
        int(value["byte_count"]),
        str(value["sha256"]),
        None if value.get("duration_seconds") is None else float(value["duration_seconds"]),
    )
