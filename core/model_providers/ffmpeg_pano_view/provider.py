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
from core.model_providers.contracts import PanoViewRequest as PanoViewContract
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success

_MEDIA_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
_ASPECT_RATIOS = frozenset({"16:9", "9:16", "2:1"})


@dataclass(frozen=True, slots=True)
class PanoViewRequest:
    content: bytes
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float
    aspect_ratio: str

    def __post_init__(self):
        if _media_type(self.content) is None or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("全景输入必须是受限 PNG 或 JPEG 字节。")
        for value, minimum, maximum in (
            (self.yaw_deg, 0, 360),
            (self.pitch_deg, -60, 60),
            (self.hfov_deg, 20, 120),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError("全景裁切机位参数不合法。")
        if self.yaw_deg == 360 or self.aspect_ratio not in _ASPECT_RATIOS:
            raise ValueError("全景裁切机位参数不合法。")


def to_request(contract: PanoViewContract) -> PanoViewRequest:
    return PanoViewRequest(
        contract.content,
        contract.yaw_deg,
        contract.pitch_deg,
        contract.hfov_deg,
        contract.aspect_ratio,
    )


class FFmpegPanoViewProvider:
    plugin_id = "ffmpeg.pano_view"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: PanoViewContract | PanoViewRequest) -> ProviderHandle:
        if not isinstance(request, PanoViewRequest):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/ffmpeg/pano-views",
                json_body={
                    "mime": _media_type(request.content),
                    "base64": base64.b64encode(request.content).decode("ascii"),
                    "yaw_deg": float(request.yaw_deg),
                    "pitch_deg": float(request.pitch_deg),
                    "hfov_deg": float(request.hfov_deg),
                    "aspect_ratio": request.aspect_ratio,
                },
            ),
            {202},
        )
        require_keys(data, required={"view_id"})
        view_id = data["view_id"]
        if not isinstance(view_id, str) or not view_id:
            raise ModelProviderError("invalid_response", "FFmpeg view_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, view_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        view_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/ffmpeg/pano-views/{quote(view_id)}"),
            {200},
        )
        require_keys(
            data,
            required={"stage", "progress", "message"},
            optional={"image", "error_code", "retryable"},
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "rendering": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "FFmpeg stage 不合法。")
        artifact = _image(data.get("image")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "ffmpeg_pano_view_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        view_id = self._id(handle)
        require_success(
            self._http.request(
                "PUT",
                f"{self._endpoint}/ffmpeg/pano-views/{quote(view_id)}/abort",
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        view_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/ffmpeg/pano-views/{quote(view_id)}/image/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "全景裁切图片不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 FFmpeg Pano View 插件。")
        return handle.external_id


def _media_type(content: bytes) -> str | None:
    for signature, media_type in _MEDIA_TYPES:
        if content.startswith(signature):
            return media_type
    return None


def _image(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "FFmpeg 完成响应缺少 image。")
    require_keys(value, required={"id", "mime", "bytes", "sha256"})
    if value["mime"] != "image/png":
        raise ModelProviderError("invalid_response", "全景裁切产物必须是 PNG。")
    return ArtifactDescriptor(
        str(value["id"]),
        str(value["mime"]),
        int(value["bytes"]),
        str(value["sha256"]),
        None,
    )
