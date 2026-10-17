"""Qwen Image 2.1（NoctQ V4）HTTP 插件：把 recipe 请求翻译成固定图服务的 DTO。"""

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
from core.model_providers.manifest import IMAGE_ASPECT_RATIOS
from core.model_providers.recipe import RecipeRequest

from .manifest import RESOLUTION_LONG_EDGE

MAX_IMAGES = 5


@dataclass(frozen=True, slots=True)
class InputImage:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("输入图片类型不受支持。")
        if not self.content or len(self.content) > 32 * 1024 * 1024:
            raise ValueError("输入图片大小不合法。")


@dataclass(frozen=True, slots=True)
class QwenImageRequest:
    """images 按传入顺序对应 <image1>…；改图时第一张是底图。"""

    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    cfg: float
    seed: int
    images: tuple[InputImage, ...]

    def __post_init__(self) -> None:
        if not self.prompt.strip() or len(self.prompt) > 20_000:
            raise ValueError("提示词必须是 1 到 20000 字符。")
        if len(self.negative_prompt) > 4_000:
            raise ValueError("负向提示词不能超过 4000 字符。")
        for name, value in (("宽", self.width), ("高", self.height)):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value % 32
                or not 256 <= value <= 2048
            ):
                raise ValueError(f"{name}必须是 256 到 2048 之间 32 的倍数。")
        if isinstance(self.steps, bool) or not isinstance(self.steps, int):
            raise ValueError("采样步数必须是整数。")
        if not 4 <= self.steps <= 60:
            raise ValueError("采样步数必须在 4 到 60 之间。")
        if (
            isinstance(self.cfg, bool)
            or not isinstance(self.cfg, int | float)
            or not isfinite(self.cfg)
            or not 1 <= self.cfg <= 8
        ):
            raise ValueError("CFG 必须在 1 到 8 之间。")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数。")
        if not 0 <= self.seed <= 2**63 - 1:
            raise ValueError("seed 超出范围。")
        if len(self.images) > MAX_IMAGES or any(
            not isinstance(item, InputImage) for item in self.images
        ):
            raise ValueError(f"最多接受 {MAX_IMAGES} 张输入图。")


def canvas(width: object, height: object, aspect_ratio: str, long_edge: int) -> tuple[int, int]:
    """显式宽高优先；都留空时长边取分辨率档位，短边按画面比例取整到 32 像素网格。"""
    if width is None and height is None:
        if aspect_ratio not in IMAGE_ASPECT_RATIOS:
            raise ValueError("画面比例不在支持的图片比例中。")
        ratio_w, ratio_h = (int(item) for item in aspect_ratio.split(":"))
        short = max(256, round(long_edge * min(ratio_w, ratio_h) / max(ratio_w, ratio_h) / 32) * 32)
        return (long_edge, short) if ratio_w >= ratio_h else (short, long_edge)
    if width is None or height is None:
        raise ValueError("宽和高必须同时填写或同时留空。")
    if not float(width).is_integer() or not float(height).is_integer():
        raise ValueError("宽高必须是整数。")
    return int(width), int(height)


def to_request(contract: RecipeRequest) -> QwenImageRequest:
    width, height = canvas(
        contract.param("width"),
        contract.param("height"),
        str(contract.param("aspect_ratio")),
        RESOLUTION_LONG_EDGE[str(contract.setting("resolution"))],
    )
    steps = contract.setting("steps")
    if isinstance(steps, float) and steps.is_integer():
        steps = int(steps)
    slots = (
        ("source_image", "reference_image")
        if contract.recipe_id.endswith(".edit")
        else ("reference_image",)
    )
    return QwenImageRequest(
        prompt=str(contract.param("prompt")),
        negative_prompt=str(contract.setting("negative_prompt")),
        width=width,
        height=height,
        steps=steps,
        cfg=float(contract.setting("cfg")),
        seed=contract.param("seed"),
        images=tuple(
            InputImage(item.media_type, item.content)
            for slot in slots
            for item in contract.slot(slot)
        ),
    )


class QwenImageProvider:
    plugin_id = "qwen-image.noctq-v4"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        if request.recipe_id not in {"qwen_image.generate", "qwen_image.edit"}:
            raise ValueError("未知 Qwen 图片 recipe。")
        return self.submit(to_request(request))

    def submit(self, request: QwenImageRequest) -> ProviderHandle:
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/qwen-image/renders",
                json_body={
                    "prompt": request.prompt,
                    "negative_prompt": request.negative_prompt,
                    "width": request.width,
                    "height": request.height,
                    "steps": request.steps,
                    "cfg": request.cfg,
                    "seed": request.seed,
                    "images": [
                        {
                            "media_type": item.media_type,
                            "content_base64": base64.b64encode(item.content).decode("ascii"),
                        }
                        for item in request.images
                    ],
                },
            ),
            {202},
        )
        require_keys(data, required={"render_id"})
        render_id = data["render_id"]
        if not isinstance(render_id, str) or not render_id:
            raise ModelProviderError("invalid_response", "Qwen 图片 render_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, render_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        render_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/qwen-image/renders/{quote(render_id)}"),
            {200},
        )
        require_keys(
            data,
            required={"status", "progress", "message"},
            optional={"image", "error_code", "retryable"},
        )
        phase = {
            "queued": GenerationPhase.QUEUED,
            "running": GenerationPhase.RUNNING,
            "succeeded": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["status"])
        if phase is None or isinstance(data["progress"], bool):
            raise ModelProviderError("invalid_response", "Qwen 图片状态不合法。")
        artifact = _image(data.get("image")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "qwen_image_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        render_id = self._id(handle)
        require_success(
            self._http.request(
                "POST", f"{self._endpoint}/qwen-image/renders/{quote(render_id)}/cancel"
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        render_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/qwen-image/renders/{quote(render_id)}/image/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "Qwen 图片产物不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 Qwen 图片插件。")
        return handle.external_id


def _image(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "Qwen 图片完成响应缺少 image。")
    require_keys(value, required={"id", "media_type", "bytes", "sha256"})
    return ArtifactDescriptor(
        str(value["id"]), str(value["media_type"]), int(value["bytes"]), str(value["sha256"])
    )
