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
from core.model_providers.manifest import IMAGE_ASPECT_RATIOS
from core.model_providers.recipe import RecipeRequest


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
class CodexImageGenerateRequest:
    prompt: str
    aspect_ratio: str
    reference_images: tuple[InputImage, ...] = ()
    model: str = "gpt-5.6-terra"

    def __post_init__(self) -> None:
        if not self.prompt or len(self.prompt) > 20_000:
            raise ValueError("prompt 必须是 1 到 20000 字符。")
        if not self.model or len(self.model) > 128:
            raise ValueError("model 不合法。")
        if any(not isinstance(image, InputImage) for image in self.reference_images):
            raise ValueError("输入图片类型不受支持。")
        if len(self.reference_images) > 5:
            raise ValueError("最多接受 5 张参考图片。")
        if self.aspect_ratio not in IMAGE_ASPECT_RATIOS:
            raise ValueError("aspect_ratio 不在支持的图片比例中。")


@dataclass(frozen=True, slots=True)
class CodexImageEditRequest:
    prompt: str
    source_image: InputImage
    aspect_ratio: str
    reference_images: tuple[InputImage, ...] = ()
    model: str = "gpt-5.6-terra"

    def __post_init__(self) -> None:
        if not isinstance(self.source_image, InputImage):
            raise ValueError("输入图片类型不受支持。")
        if not self.prompt or len(self.prompt) > 20_000:
            raise ValueError("prompt 必须是 1 到 20000 字符。")
        if not self.model or len(self.model) > 128:
            raise ValueError("model 不合法。")
        if any(not isinstance(image, InputImage) for image in self.reference_images):
            raise ValueError("输入图片类型不受支持。")
        if len(self.reference_images) > 4:
            raise ValueError("图片编辑除底图外最多接受 4 张参考图片。")
        if self.aspect_ratio not in IMAGE_ASPECT_RATIOS:
            raise ValueError("aspect_ratio 不在支持的图片比例中。")


def to_generate_request(contract: RecipeRequest) -> CodexImageGenerateRequest:
    return CodexImageGenerateRequest(
        str(contract.param("prompt")),
        str(contract.param("aspect_ratio")),
        tuple(
            InputImage(item.media_type, item.content) for item in contract.slot("reference_image")
        ),
    )


def to_edit_request(contract: RecipeRequest) -> CodexImageEditRequest:
    source = contract.slot("source_image")[0]
    return CodexImageEditRequest(
        str(contract.param("prompt")),
        InputImage(source.media_type, source.content),
        str(contract.param("aspect_ratio")),
        tuple(
            InputImage(item.media_type, item.content) for item in contract.slot("reference_image")
        ),
    )


class CodexImageProvider:
    generate_plugin_id = "codex.image.generate"
    edit_plugin_id = "codex.image.edit"
    plugin_ids = frozenset({generate_plugin_id, edit_plugin_id})
    plugin_version = 1

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        if request.recipe_id.endswith(".generate"):
            return self.submit_generate(to_generate_request(request))
        if request.recipe_id.endswith(".edit"):
            return self.submit_edit(to_edit_request(request))
        raise ValueError("未知图片 recipe。")

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit_generate(self, request: RecipeRequest | CodexImageGenerateRequest) -> ProviderHandle:
        if not isinstance(request, CodexImageGenerateRequest):
            request = to_generate_request(request)
        return self._submit(
            path="image-generations",
            plugin_id=self.generate_plugin_id,
            prompt=request.prompt,
            model=request.model,
            aspect_ratio=request.aspect_ratio,
            source_image=None,
            reference_images=request.reference_images,
        )

    def submit_edit(self, request: RecipeRequest | CodexImageEditRequest) -> ProviderHandle:
        if not isinstance(request, CodexImageEditRequest):
            request = to_edit_request(request)
        return self._submit(
            path="image-edits",
            plugin_id=self.edit_plugin_id,
            prompt=request.prompt,
            model=request.model,
            aspect_ratio=request.aspect_ratio,
            source_image=request.source_image,
            reference_images=request.reference_images,
        )

    def _submit(
        self,
        *,
        path: str,
        plugin_id: str,
        prompt: str,
        model: str,
        aspect_ratio: str,
        source_image: InputImage | None,
        reference_images: tuple[InputImage, ...],
    ) -> ProviderHandle:
        images = [
            {
                "content_type": item.media_type,
                "data_base64": base64.b64encode(item.content).decode("ascii"),
            }
            for item in reference_images
        ]
        source = (
            None
            if source_image is None
            else {
                "content_type": source_image.media_type,
                "data_base64": base64.b64encode(source_image.content).decode("ascii"),
            }
        )
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/codex/{path}",
                json_body={
                    "instruction": prompt,
                    "model": model,
                    "aspect_ratio": aspect_ratio,
                    "source_image": source,
                    "reference_images": images,
                },
            ),
            {202},
        )
        require_keys(data, required={"request_id", "accepted_at"})
        request_id = data["request_id"]
        if not isinstance(request_id, str) or not request_id:
            raise ModelProviderError("invalid_response", "Codex request_id 不合法。")
        return ProviderHandle(plugin_id, self.plugin_version, request_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        request_id = self._id(handle)
        route = self._route(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/codex/{route}/{quote(request_id)}"),
            {200},
        )
        require_keys(
            data,
            required={"state", "completion", "detail"},
            optional={"image", "failure"},
        )
        phase = {
            "accepted": GenerationPhase.QUEUED,
            "working": GenerationPhase.RUNNING,
            "complete": GenerationPhase.SUCCEEDED,
            "failed": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["state"])
        if phase is None or isinstance(data["completion"], bool):
            raise ModelProviderError("invalid_response", "Codex 状态不合法。")
        artifact = None
        error_code = None
        if phase is GenerationPhase.SUCCEEDED:
            image = data.get("image")
            if not isinstance(image, dict):
                raise ModelProviderError("invalid_response", "Codex 完成响应缺少 image。")
            require_keys(image, required={"id", "content_type", "size", "sha256"})
            artifact = ArtifactDescriptor(
                str(image["id"]),
                str(image["content_type"]),
                int(image["size"]),
                str(image["sha256"]),
            )
        elif phase is GenerationPhase.FAILED:
            failure = data.get("failure")
            error_code = str(failure) if failure else "codex_failed"
        return GenerationObservation(
            phase,
            float(data["completion"]),
            str(data["detail"]),
            artifact,
            error_code,
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        request_id = self._id(handle)
        route = self._route(handle)
        require_success(
            self._http.request("POST", f"{self._endpoint}/codex/{route}/{quote(request_id)}/stop"),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        request_id = self._id(handle)
        route = self._route(handle)
        escaped_artifact = quote(artifact_id, safe="")
        response = self._http.request(
            "GET",
            f"{self._endpoint}/codex/{route}/{quote(request_id)}/content/{escaped_artifact}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "Codex 图片不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if handle.plugin_id not in self.plugin_ids or (
            handle.plugin_version != self.plugin_version
        ):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 Codex 图片插件。")
        return handle.external_id

    def _route(self, handle: ProviderHandle) -> str:
        self._id(handle)
        return "image-generations" if handle.plugin_id == self.generate_plugin_id else "image-edits"
