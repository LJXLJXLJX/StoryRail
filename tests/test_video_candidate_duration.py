"""资产库视频候选的时长规则：只要求可挂接的真实时长，不限制上限。"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace

import pytest
from test_director_commands import _visual_project

from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)


def _attach_generation(*, duration_seconds: float) -> ReferenceGeneration:
    return ReferenceGeneration(
        id="9" * 32,
        kind=ReferenceGenerationKind.SEGMENT_VIDEO,
        operation=GenerationOperation.ATTACH,
        target_id="7" * 32,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        message="已从项目资产库增加为视频候选。",
        prompt_text="从项目资产库增加视频候选。",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id="storyrail.asset_library",
        plugin_version=1,
        external_id="9" * 32,
        output_asset_id="5" * 32,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=duration_seconds,
    )


class AttachDurationRuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_asset_library_candidate_keeps_duration_beyond_segment_budget(self) -> None:
        """10.125 秒这类直出视频必须能挂接、能被选中，且仍占用真实时长。"""
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.video_plan is not None
            segment_id = document.video_plan.segments[0].segment_id
            document, asset = store._ingest_asset(
                document,
                "video/mp4",
                b"\x00\x00\x00\x18ftypmp42long-candidate",
                duration_seconds=10.125,
                directory="videos/imported",
                label="前作长片段",
            )
            document = replace(document, revision=document.revision + 1)
            store._atomic_write(document)

            attached = store.attach_segment_video_candidate(
                segment_id=segment_id,
                asset_id=asset.id,
                expected_revision=document.revision,
            )

            candidates = [
                item
                for item in attached.generations
                if item.kind is ReferenceGenerationKind.SEGMENT_VIDEO
                and item.operation is GenerationOperation.ATTACH
                and item.output_asset_id == asset.id
            ]
            assert len(candidates) == 1
            assert candidates[0].duration_seconds == 10.125
            selected = store.select_segment_video(
                segment_id=segment_id,
                asset_id=asset.id,
                expected_revision=attached.revision,
            )
            assert (
                next(
                    item for item in selected.video_plan.segments if item.segment_id == segment_id
                ).selected_asset_id
                == asset.id
            )

    async def test_http_attach_route_accepts_over_budget_candidate(self) -> None:
        """走真实 HTTP 路由：挂接 10.125 秒候选后快照展示为普通成功候选。"""
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.video_plan is not None
            segment_id = document.video_plan.segments[0].segment_id
            document, asset = store._ingest_asset(
                document,
                "video/mp4",
                b"\x00\x00\x00\x18ftypmp42http-candidate",
                duration_seconds=10.125,
                directory="videos/imported",
                label="HTTP 长候选",
            )
            document = replace(document, revision=document.revision + 1)
            store._atomic_write(document)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            response = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/attach-candidate",
                json.dumps({"expected_revision": document.revision, "asset_id": asset.id}).encode(),
            )

            assert response.status == 200
            candidate = next(
                item for item in response.body["generations"] if item["output_asset_id"] == asset.id
            )
            assert candidate["duration_seconds"] == 10.125
            assert candidate["operation"] == "attach"
            assert "select_segment_video" in candidate["allowed_actions"]

    async def test_asset_library_candidate_requires_real_positive_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.video_plan is not None
            segment_id = document.video_plan.segments[0].segment_id
            document, asset = store._ingest_asset(
                document,
                "video/mp4",
                b"\x00\x00\x00\x18ftypmp42shorter-candidate",
                duration_seconds=0.05,
                directory="videos/imported",
                label="过短片段",
            )
            document = replace(document, revision=document.revision + 1)
            store._atomic_write(document)

            with pytest.raises(ValueError, match="不短于 0.2 秒"):
                store.attach_segment_video_candidate(
                    segment_id=segment_id,
                    asset_id=asset.id,
                    expected_revision=document.revision,
                )


class GenerationDurationRuleTests(unittest.TestCase):
    def test_attach_generation_accepts_duration_over_budget(self) -> None:
        assert _attach_generation(duration_seconds=10.125).duration_seconds == 10.125
        assert _attach_generation(duration_seconds=22.0).duration_seconds == 22.0

    def test_attach_generation_still_rejects_missing_duration(self) -> None:
        with pytest.raises(ValueError, match="不短于 0.2 秒"):
            _attach_generation(duration_seconds=0.0)

    def test_generated_segment_video_has_no_duration_upper_limit(self) -> None:
        # 15 秒只是可能 OOM 的软约束，渲染产物时长不设上限，只拒绝短于 0.2 秒。
        rendered = replace(
            _attach_generation(duration_seconds=20.125),
            operation=GenerationOperation.RENDER,
            input_asset_ids=("5" * 32,),
            seed=7,
        )
        assert rendered.duration_seconds == 20.125
        with pytest.raises(ValueError, match="不短于 0.2 秒"):
            replace(rendered, duration_seconds=0.1)
