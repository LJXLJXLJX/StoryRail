"""提交结果未知的 Generation：隐藏或显式重试即视为已处理，不再计入活动任务或占用目标。"""

from __future__ import annotations

from test_generation_mutations import ID_D, _document, _png_asset
from test_models_validation import make_generation

from core.structured_director.models import (
    AssetUsageReason,
    GenerationOperation,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    asset_usage_reasons,
    unresolved_uncertain_ids,
)
from core.structured_director.reads.execution_reads import _task_discovery
from core.structured_director.reads.workflow_state import workflow_state

ASSET = "f" * 32
RETRY = "9" * 32


def _uncertain(**kw):
    fields = dict(
        id=ID_D,
        target_id="e" * 32,
        phase=ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        error_code="core_restarted_during_submit",
        plugin_id=None,
        plugin_version=None,
        external_id=None,
        input_asset_ids=(ASSET,),
    )
    fields.update(kw)
    return make_generation(
        ReferenceGenerationKind.KEYFRAME_IMAGE, GenerationOperation.GENERATE, **fields
    )


def _retry_of(generation):
    return make_generation(
        ReferenceGenerationKind.KEYFRAME_IMAGE,
        GenerationOperation.GENERATE,
        id=RETRY,
        target_id=generation.target_id,
        phase=ReferenceGenerationPhase.FAILED,
        error_code="provider_failed",
        retry_of=generation.id,
        input_asset_ids=(ASSET,),
    )


def _activity(document):
    return workflow_state(document)["activity_summary"]


def _discovery(document):
    data = _task_discovery(document, {})
    return {item["id"] for item in data["active"]}, data["active_count"]


def test_unresolved_uncertain_until_dismissed_or_retried():
    pending = _uncertain()
    dismissed = _uncertain(dismissed=True)
    assert unresolved_uncertain_ids((pending,)) == {ID_D}
    assert unresolved_uncertain_ids((dismissed,)) == frozenset()
    assert unresolved_uncertain_ids((pending, _retry_of(pending))) == frozenset()


def test_pending_uncertain_counts_as_active_and_blocks_input_deletion():
    document = _document(assets=(_png_asset(ASSET),), generations=(_uncertain(),))
    assert _activity(document)["active_generation_count"] == 1
    assert _discovery(document) == ({ID_D}, 1)
    assert AssetUsageReason.UNFINISHED_GENERATION_INPUT in asset_usage_reasons(document, ASSET)


def test_dismissed_uncertain_leaves_activity_and_releases_inputs():
    document = _document(assets=(_png_asset(ASSET),), generations=(_uncertain(dismissed=True),))
    assert _activity(document)["active_generation_count"] == 0
    assert _discovery(document) == (set(), 0)
    assert AssetUsageReason.UNFINISHED_GENERATION_INPUT not in asset_usage_reasons(document, ASSET)


def test_retried_uncertain_is_superseded_by_its_retry():
    original = _uncertain()
    document = _document(assets=(_png_asset(ASSET),), generations=(original, _retry_of(original)))
    assert _activity(document)["active_generation_count"] == 0
    assert _discovery(document) == (set(), 0)
