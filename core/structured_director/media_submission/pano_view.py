"""地点视图的全景裁切提交：Core 确定性工具，产物由回调直接写入视图 `crop_asset_id`。"""

from __future__ import annotations

from uuid import uuid4

from core.model_providers.contracts import PanoViewRequest

from ..location_requests import crop_prompt_text
from ..models import (
    GenerationOperation,
    LocationCropRequest,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from .support import _commit_submission


class PanoViewSubmission:
    async def _submit_location_crop(
        self,
        document: StructuredDirectorDocument,
        view_id: str,
        crop: LocationCropRequest,
        *,
        retry_of: ReferenceGeneration | None,
    ) -> StructuredDirectorDocument:
        """在服务锁内调用；Generation 冻结主图与绝对几何，回调据此判断是否过期。"""
        provider = self._pano_view_provider
        if provider is None:
            raise RuntimeError("全景裁切服务尚未配置。")
        _asset, content = self._store.read_asset(crop.master_asset_id)
        request = PanoViewRequest(
            content, crop.yaw_deg, crop.pitch_deg, crop.hfov_deg, crop.aspect_ratio
        )
        generation = ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.LOCATION_VIEW_CROP,
            operation=GenerationOperation.PROCESS,
            target_id=view_id,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message="正在提交全景裁切任务。",
            prompt_text=crop_prompt_text(crop),
            input_asset_ids=(crop.master_asset_id,),
            sample_text=None,
            seed=None,
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
            location_crop_request=crop,
        )
        return await _commit_submission(
            self,
            document,
            generation,
            expected_revision=document.revision,
            submit=lambda: provider.submit(request),
            capability="全景裁切",
            queued_message="全景裁切进行中；完成后再次生成该视图才会提交细化。",
            retry_of=retry_of,
        )
