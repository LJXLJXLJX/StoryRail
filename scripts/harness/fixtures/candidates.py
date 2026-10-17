"""把已有项目图片登记为成功候选：等同 Provider 产出同一字节，供需要“已选视图”的 fixture 使用。

候选选择只接受属于目标的成功 Generation；fixture 不调用图片模型，只走 Store 的正式
create → queued → complete 生命周期，产物按内容去重回到同一个 Asset。
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from core.structured_director.models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    transition_generation,
)


def register_image_candidate(
    store, *, kind: ReferenceGenerationKind, target_id: str, asset_id: str
) -> None:
    asset, content = store.read_asset(asset_id)
    generation = ReferenceGeneration(
        id=uuid4().hex,
        kind=kind,
        operation=GenerationOperation.GENERATE,
        target_id=target_id,
        phase=ReferenceGenerationPhase.SUBMITTING,
        progress=0.0,
        message="fixture 候选。",
        prompt_text="fixture 候选。",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id=None,
        plugin_version=None,
        external_id=None,
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
    )
    store.create_generation(generation, expected_revision=store.read().revision)
    queued = transition_generation(
        generation,
        ReferenceGenerationPhase.QUEUED,
        plugin_id="fixture.image",
        plugin_version=1,
        external_id=generation.id,
    )
    store.update_generation(queued)
    store.complete_generation(
        queued,
        media_type=asset.media_type,
        content=content,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_byte_count=len(content),
    )
