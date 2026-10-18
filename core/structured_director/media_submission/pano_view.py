"""全景地点图片的确定性取景；产物直接成为目标普通图片的已选 Asset。"""

from __future__ import annotations

from uuid import uuid4

from core.model_providers.contracts import PanoViewRequest

from ..location_requests import capture_prompt_text, panorama_capture_request
from ..models import (
    GenerationOperation,
    PanoramaCaptureRequest,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from .support import _commit_submission


class PanoViewSubmission:
    async def generate_location_capture(
        self,
        *,
        image_id: str,
        expected_revision: int,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        async with self._lock:
            document = self._store.read()
            if document.revision != expected_revision:
                raise ValueError("项目已被更新，请重新读取后再截取全景视角。")
            capture = panorama_capture_request(document, image_id)
            return await self._submit_location_capture(
                document, image_id, capture, retry_of=_retry_of
            )

    async def _submit_location_capture(
        self,
        document: StructuredDirectorDocument,
        image_id: str,
        capture: PanoramaCaptureRequest,
        *,
        retry_of: ReferenceGeneration | None,
    ) -> StructuredDirectorDocument:
        """在服务锁内调用；Generation 冻结全景 Asset 与相机几何。"""
        provider = self._pano_view_provider
        if provider is None:
            raise RuntimeError("全景裁切服务尚未配置。")
        _asset, content = self._store.read_asset(capture.panorama_asset_id)
        request = PanoViewRequest(
            content,
            capture.yaw_deg,
            capture.pitch_deg,
            capture.hfov_deg,
            capture.aspect_ratio,
        )
        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.PANORAMA_CAPTURE,
            operation=GenerationOperation.PROCESS,
            target_id=image_id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message="正在提交全景裁切任务。",
            prompt_text=capture_prompt_text(capture),
            input_asset_ids=(capture.panorama_asset_id,),
            sample_text=None,
            seed=None,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            panorama_capture_request=capture,
        )
        return await _commit_submission(
            self,
            document,
            generation,
            expected_revision=document.revision,
            submit=lambda: provider.submit(request),
            capability="全景裁切",
            queued_message="全景取景进行中；完成后结果直接成为独立地点图片。",
            retry_of=retry_of,
        )
