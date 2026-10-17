from __future__ import annotations

import base64
from urllib.parse import quote

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.codex_image import (
    CodexImageEditRequest,
    CodexImageGenerateRequest,
    InputImage,
)
from core.model_providers.codex_image.provider import to_edit_request, to_generate_request
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success
from core.model_providers.recipe import RecipeRequest


class AgyImageProvider:
    """AGY 图片能力的独立 HTTP 插件；Core 不执行 CLI。"""

    generate_plugin_id = "agy.image.generate"
    edit_plugin_id = "agy.image.edit"
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
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/agy/{path}",
                json_body={
                    "instruction": prompt,
                    # 保留统一请求形状；AGY 使用用户在原生 CLI 中保存的模型选择。
                    "model": model,
                    "aspect_ratio": aspect_ratio,
                    "source_image": _image_payload(source_image),
                    "reference_images": [_image_payload(item) for item in reference_images],
                },
            ),
            {202},
        )
        require_keys(data, required={"request_id", "accepted_at"})
        request_id = data["request_id"]
        if not isinstance(request_id, str) or not request_id:
            raise ModelProviderError("invalid_response", "AGY request_id 不合法。")
        return ProviderHandle(plugin_id, self.plugin_version, request_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        request_id = self._id(handle)
        route = self._route(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/agy/{route}/{quote(request_id)}"),
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
            raise ModelProviderError("invalid_response", "AGY 状态不合法。")
        artifact = None
        error_code = None
        if phase is GenerationPhase.SUCCEEDED:
            image = data.get("image")
            if not isinstance(image, dict):
                raise ModelProviderError("invalid_response", "AGY 完成响应缺少 image。")
            require_keys(image, required={"id", "content_type", "size", "sha256"})
            artifact = ArtifactDescriptor(
                str(image["id"]),
                str(image["content_type"]),
                int(image["size"]),
                str(image["sha256"]),
            )
        elif phase is GenerationPhase.FAILED:
            error_code = str(data.get("failure") or "agy_failed")
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
            self._http.request("POST", f"{self._endpoint}/agy/{route}/{quote(request_id)}/stop"),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        request_id = self._id(handle)
        route = self._route(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/agy/{route}/{quote(request_id)}/content/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "AGY 图片不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if handle.plugin_id not in self.plugin_ids or handle.plugin_version != self.plugin_version:
            raise ModelProviderError("invalid_handle", "调用句柄不属于 AGY 图片插件。")
        return handle.external_id

    def _route(self, handle: ProviderHandle) -> str:
        self._id(handle)
        return "image-generations" if handle.plugin_id == self.generate_plugin_id else "image-edits"


def _image_payload(image: InputImage | None) -> dict[str, str] | None:
    if image is None:
        return None
    return {
        "content_type": image.media_type,
        "data_base64": base64.b64encode(image.content).decode("ascii"),
    }
