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
from core.model_providers.minimax_h3.contracts import FL2VARequest
from core.model_providers.minimax_h3.requests import to_request as recipe_to_request


@dataclass(frozen=True, slots=True)
class H3KeyframeImage:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("关键帧图片类型不受支持。")
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("关键帧图片大小不合法。")


@dataclass(frozen=True, slots=True)
class MiniMaxH3FL2VARequest:
    prompt: str
    first_frame: H3KeyframeImage | None = None
    last_frame: H3KeyframeImage | None = None
    width: int = 832
    height: int = 480
    duration_seconds: float = 3.0
    seed: int = 42
    steps: int = 20
    cfg: float = 1.0
    save_audio: bool = False
    sage_attention: bool = True
    selflift: bool = True

    def __post_init__(self) -> None:
        if self.first_frame is None and self.last_frame is None:
            raise ValueError("H3 FL2VA 至少需要首帧或尾帧之一。")
        _validate_h3_fields(self)


def to_request(contract: FL2VARequest) -> MiniMaxH3FL2VARequest:
    return MiniMaxH3FL2VARequest(
        contract.prompt,
        None
        if contract.first_frame is None
        else H3KeyframeImage(contract.first_frame.media_type, contract.first_frame.content),
        None
        if contract.last_frame is None
        else H3KeyframeImage(contract.last_frame.media_type, contract.last_frame.content),
        contract.width,
        contract.height,
        contract.duration_seconds,
        contract.seed,
        contract.steps,
        contract.cfg,
        contract.save_audio,
        contract.sage_attention,
        contract.selflift,
    )


class MiniMaxH3FL2VAProvider:
    plugin_id = "minimax.h3.fl2va"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request):
        return self.submit(recipe_to_request(request))

    def submit(self, request: FL2VARequest | MiniMaxH3FL2VARequest) -> ProviderHandle:
        if not isinstance(request, MiniMaxH3FL2VARequest):
            request = to_request(request)
        payload = {
            "prompt": request.prompt,
            "canvas": {"width": request.width, "height": request.height},
            "seconds": request.duration_seconds,
            "seed": request.seed,
            "sampling": {
                "steps": request.steps,
                "cfg": request.cfg,
                "sage_attention": request.sage_attention,
                "selflift": request.selflift,
            },
            "include_audio": request.save_audio,
            "opening_frame": _encode_image(request.first_frame),
            "closing_frame": _encode_image(request.last_frame),
        }
        data = require_success(
            self._http.request(
                "POST", f"{self._endpoint}/minimax-h3/fl2va/clips", json_body=payload
            ),
            {202},
        )
        require_keys(data, required={"job_token", "queue_position"})
        token = data["job_token"]
        if not isinstance(token, str) or not token:
            raise ModelProviderError("invalid_response", "H3 FL2VA job_token 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, token)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        token = self._token(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/minimax-h3/fl2va/clips/{quote(token)}"),
            {200},
        )
        require_keys(
            data,
            required={"stage", "ratio", "description"},
            optional={"movie", "error_tag", "can_retry"},
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "generating": GenerationPhase.RUNNING,
            "done": GenerationPhase.SUCCEEDED,
            "error": GenerationPhase.FAILED,
            "stopped": GenerationPhase.CANCELLED,
        }.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "H3 FL2VA stage 不合法。")
        artifact = (
            _movie_artifact(data.get("movie")) if phase is GenerationPhase.SUCCEEDED else None
        )
        error_code = (
            str(data.get("error_tag") or "h3_fl2va_failed")
            if phase is GenerationPhase.FAILED
            else None
        )
        return GenerationObservation(
            phase,
            float(data["ratio"]),
            str(data["description"]),
            artifact,
            error_code,
            bool(data.get("can_retry", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        token = self._token(handle)
        require_success(
            self._http.request(
                "PUT", f"{self._endpoint}/minimax-h3/fl2va/clips/{quote(token)}/abort"
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        token = self._token(handle)
        escaped_artifact = quote(artifact_id, safe="")
        response = self._http.request(
            "GET",
            f"{self._endpoint}/minimax-h3/fl2va/clips/{quote(token)}/movie/{escaped_artifact}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "H3 FL2VA 视频不可用。")
        return response.body

    def _token(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 H3 FL2VA 插件。")
        return handle.external_id


def _validate_h3_fields(request: MiniMaxH3FL2VARequest) -> None:
    if not request.prompt or len(request.prompt) > 20_000:
        raise ValueError("prompt 必须是 1 到 20000 字符。")
    if (
        request.width % 32
        or request.height % 32
        or not 256 <= request.width <= 1920
        or not 256 <= request.height <= 1920
    ):
        raise ValueError("画布边长必须是 32 的倍数且在 256 到 1920 之间。")
    if request.width * request.height > 2_100_000:
        raise ValueError("画布像素过大。")
    if not isfinite(request.duration_seconds) or request.duration_seconds < 0.2:
        raise ValueError("duration_seconds 必须是不短于 0.2 秒的有限数值。")
    if isinstance(request.steps, bool) or request.steps not in {20, 8}:
        raise ValueError("H3 步数只允许 20 或 8。")
    if not 0 <= request.seed <= 2**63 - 1 or not 0 <= request.cfg <= 30:
        raise ValueError("采样参数不合法。")
    if not isinstance(request.sage_attention, bool) or not isinstance(request.selflift, bool):
        raise ValueError("H3 sage_attention 与 selflift 必须是布尔值。")


def _encode_image(image: H3KeyframeImage | None) -> dict[str, str] | None:
    if image is None:
        return None
    return {"mime": image.media_type, "base64": base64.b64encode(image.content).decode("ascii")}


def _movie_artifact(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "H3 FL2VA 完成响应缺少 movie。")
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
