"""真实 FFmpeg 按帧号抽帧 + Core 临时项目闭环，不调用视频模型。"""

import asyncio
import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from uuid import uuid4

import pytest
from conftest import make_service
from script_helpers import shot_segments_at
from test_director_commands import _ScriptCompiler, _visual_project

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals import SegmentBoundaryProposal
from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.structured_director import StructuredDirectorHttpApi, StructuredDirectorStore
from core.structured_director.models import (
    AssetUsageReason,
    ImageAssetCategory,
    ReferenceGenerationKind,
    asset_deletion_closure,
    asset_project_usage_reasons,
    asset_usage_reasons,
)
from core.structured_director.video_inputs import (
    resolve_video_inputs,
    start_frame_extraction_source,
)
from default_model_providers_implement.ffmpeg_video_frame_worker import extract


class ContinuousScript(_ScriptCompiler):
    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        scene = proposal.scenes[0]
        shot = scene.shots[0]
        first = replace(shot.segments[0], dialogue_lines=())
        second = replace(
            first,
            boundary_from_previous=SegmentBoundaryProposal("continuity_anchor", "延续同一动作。"),
        )
        return replace(
            proposal, scenes=(replace(scene, shots=(replace(shot, segments=(first, second)),)),)
        )


class FrameProvider:
    plugin_id = "ffmpeg.video_frame"
    plugin_version = 1

    def __init__(self, root):
        self.root = root
        self.requests = []

    def submit(self, request):
        self.requests.append(request)
        task_id = uuid4().hex
        directory = self.root / task_id
        directory.mkdir()
        (directory / "source.mp4").write_bytes(request.content)
        (directory / "request.json").write_text(
            json.dumps({"schema": "video_frame_v2", "frame_index": request.frame_index})
        )
        extract(directory / "request.json")
        return ProviderHandle(self.plugin_id, 1, task_id)

    def read_artifact(self, handle, artifact_id):
        return (self.root / handle.external_id / "output.png").read_bytes()

    def observe(self, handle):
        content = self.read_artifact(handle, handle.external_id)
        return GenerationObservation(
            GenerationPhase.SUCCEEDED,
            1.0,
            "已完成",
            ArtifactDescriptor(
                handle.external_id, "image/png", len(content), hashlib.sha256(content).hexdigest()
            ),
        )


class FlakyFrameProvider(FrameProvider):
    def __init__(self, root):
        super().__init__(root)
        self.fail_next = True

    def submit(self, request):
        if self.fail_next:
            self.fail_next = False
            raise ModelProviderError("transport_error", "测试传输失败")
        return super().submit(request)


def make_video(path, color, tail_color=None):
    """5 帧 64x64 视频；给出 tail_color 时第 3-4 帧换成该颜色。"""
    source = (
        ["-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=5:d=1"]
        if tail_color is None
        else [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=64x64:r=5:d=0.6",
            "-f",
            "lavfi",
            "-i",
            f"color=c={tail_color}:s=64x64:r=5:d=0.4",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1[v]",
            "-map",
            "[v]",
        ]
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *source, "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        + [str(path)],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


def first_pixel(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return raw[0], raw[1], raw[2]


def _needs_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("需要 FFmpeg")


def _set_activation(store, doc, segment_id, start, end):
    return (
        DirectorCommandRegistry(store)
        .execute(
            DirectorCommand(
                "keyframe.apply_operations",
                doc.revision,
                f"activation-{segment_id}-{start}-{end}",
                {
                    "operations": [
                        {
                            "op": "set_activation",
                            "segment_id": segment_id,
                            "start_enabled": start,
                            "end_enabled": end,
                        }
                    ]
                },
            )
        )
        .document
    )


def _binding(doc, segment_id):
    return next(item for item in doc.keyframe_plan.segments if item.segment_id == segment_id)


def test_start_frame_extracted_from_previous_segment_is_candidate_not_guarantee(tmp_path):
    """上一段只用首帧生成，下一段首帧从其视频任意帧抽取；程序不强制两侧一致。"""

    _needs_ffmpeg()

    async def scenario():
        store, _, doc, _ = await _visual_project(str(tmp_path), script_proposer=ContinuousScript())
        provider = FrameProvider(tmp_path)
        service = make_service(store, video_frame_provider=provider)
        scene = doc.director_script.scenes[0]
        source, target = shot_segments_at(scene, 0)
        # Shot 内边界是两个独立 Keyframe，默认都不启用。
        assert (
            _binding(doc, source.id).end_keyframe_id != _binding(doc, target.id).start_keyframe_id
        )
        start_keyframe = _binding(doc, target.id).start_keyframe_id
        # 上一段关闭尾帧、下一段启用首帧：不再报“共享边界必须在两侧启用”。
        doc = _set_activation(store, doc, source.id, True, False)
        doc = _set_activation(store, doc, target.id, True, False)
        assert start_frame_extraction_source(doc, start_keyframe)["state"] == (
            "waiting_source_video"
        )
        doc = await service.import_media_asset(
            media_type="video/mp4",
            content=make_video(tmp_path / "red-blue.mp4", "red", "blue"),
            expected_revision=doc.revision,
        )
        source_video = doc.assets[-1].id
        doc = store.attach_segment_video_candidate(
            segment_id=source.id, asset_id=source_video, expected_revision=doc.revision
        )
        doc = store.select_segment_video(
            segment_id=source.id, asset_id=source_video, expected_revision=doc.revision
        )
        extraction = start_frame_extraction_source(doc, start_keyframe)
        assert extraction["state"] == "ready"
        assert extraction["source_segment_id"] == source.id
        assert extraction["source_video_asset_id"] == source_video
        assert service.video_frame_info(source_video).frame_count == 5
        with pytest.raises(ValueError, match="上一段视频已变化"):
            await service._media.extract_keyframe_video_frame(
                keyframe_id=start_keyframe,
                frame_index=4,
                expected_source_video_asset_id="f" * 32,
                expected_revision=doc.revision,
            )
        with pytest.raises(ValueError, match="0-4"):
            await service._media.extract_keyframe_video_frame(
                keyframe_id=start_keyframe,
                frame_index=5,
                expected_source_video_asset_id=source_video,
                expected_revision=doc.revision,
            )
        doc = await service._media.extract_keyframe_video_frame(
            keyframe_id=start_keyframe,
            frame_index=1,
            expected_source_video_asset_id=source_video,
            expected_revision=doc.revision,
        )
        generation = doc.generations[-1]
        assert generation.kind is ReferenceGenerationKind.VIDEO_FRAME
        assert generation.target_id == start_keyframe
        request = generation.video_frame_request
        assert (request.frame_index, request.frame_count) == (1, 5)
        assert request.source_segment_id == source.id
        assert provider.requests[-1].frame_index == 1
        with pytest.raises(ValueError, match="进行中的抽帧"):
            await service._media.extract_keyframe_video_frame(
                keyframe_id=start_keyframe,
                frame_index=4,
                expected_source_video_asset_id=source_video,
                expected_revision=doc.revision,
            )
        # 服务重启后仍可观察；完成后登记为首帧候选但不自动选择。
        service = make_service(store, video_frame_provider=provider)
        doc = await service._generation_observer.refresh_generation(generation.id)
        frame_asset = next(x for x in doc.generations if x.id == generation.id).output_asset_id
        candidate = doc.generations[-1]
        assert candidate.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
        assert candidate.operation.value == "attach"
        assert candidate.target_id == start_keyframe
        assert candidate.output_asset_id == frame_asset
        assert "第 1 帧" in candidate.prompt_text
        frame_name = next(x for x in doc.assets if x.id == frame_asset).display_name
        assert frame_name.endswith("-首帧-抽帧-第1帧.png"), frame_name
        keyframe = next(x for x in doc.keyframe_plan.keyframes if x.id == start_keyframe)
        assert keyframe.selected_asset_id is None
        assert AssetUsageReason.VISIBLE_CANDIDATE in asset_usage_reasons(doc, frame_asset)
        assert first_pixel(tmp_path / generation.external_id / "output.png")[0] > 240
        metadata = json.loads(
            (tmp_path / generation.external_id / "frame-metadata.json").read_text()
        )
        assert (metadata["frame_index"], metadata["frame_count"]) == (1, 5)

        doc = store.select_keyframe_asset(
            keyframe_id=start_keyframe, asset_id=frame_asset, expected_revision=doc.revision
        )
        inputs = resolve_video_inputs(doc, target.id)
        assert inputs.start_asset_id == frame_asset
        assert inputs.end_asset_id is None

        # 默认最后一帧：抽到蓝色尾段。
        doc = await service._media.extract_keyframe_video_frame(
            keyframe_id=start_keyframe,
            frame_index=4,
            expected_source_video_asset_id=source_video,
            expected_revision=doc.revision,
        )
        last = doc.generations[-1]
        doc = await service._generation_observer.refresh_generation(last.id)
        assert first_pixel(tmp_path / last.external_id / "output.png")[2] > 240

        # 上一段换版不会改写或失效下一段已选首帧：一致性由用户手动维护。
        doc = await service.import_media_asset(
            media_type="video/mp4",
            content=make_video(tmp_path / "green.mp4", "green"),
            expected_revision=doc.revision,
        )
        replacement = doc.assets[-1].id
        doc = store.attach_segment_video_candidate(
            segment_id=source.id, asset_id=replacement, expected_revision=doc.revision
        )
        doc = store.select_segment_video(
            segment_id=source.id, asset_id=replacement, expected_revision=doc.revision
        )
        keyframe = next(x for x in doc.keyframe_plan.keyframes if x.id == start_keyframe)
        assert keyframe.selected_asset_id == frame_asset
        assert start_frame_extraction_source(doc, start_keyframe)["source_video_asset_id"] == (
            replacement
        )

    asyncio.run(scenario())


def test_shared_boundary_start_frame_cannot_extract_from_previous_segment(tmp_path):
    async def scenario():
        store, _, doc, _ = await _visual_project(str(tmp_path), script_proposer=ContinuousScript())
        source, target = shot_segments_at(doc.director_script.scenes[0], 0)
        doc = (
            DirectorCommandRegistry(store)
            .execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    doc.revision,
                    "share-intra-shot",
                    {
                        "operations": [
                            {
                                "op": "share_boundary",
                                "left_segment_id": source.id,
                                "right_segment_id": target.id,
                                "expected_adjacency": "intra_shot",
                            }
                        ]
                    },
                )
            )
            .document
        )
        shared = _binding(doc, target.id).start_keyframe_id
        assert shared == _binding(doc, source.id).end_keyframe_id
        assert start_frame_extraction_source(doc, shared)["state"] == "shared_boundary"
        # 显式共享的边界仍可单侧关闭，不再强制两侧启用。
        doc = _set_activation(store, doc, source.id, True, False)
        assert _binding(doc, source.id).end_enabled is False
        first_start = _binding(doc, source.id).start_keyframe_id
        assert start_frame_extraction_source(doc, first_start)["state"] == "unavailable"

    asyncio.run(scenario())


def test_asset_center_frame_output_is_unbound_and_purgeable(tmp_path):
    """资产中心任意 MP4 按帧号抽帧产出的 PNG 默认未绑定，删除语义与源视频分开。"""

    _needs_ffmpeg()

    async def scenario():
        store, _, doc, _ = await _visual_project(str(tmp_path))
        provider = FrameProvider(tmp_path)
        service = make_service(store, video_frame_provider=provider)
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        doc = await service.import_media_asset(
            media_type="video/mp4",
            content=make_video(tmp_path / "asset-center.mp4", "red"),
            expected_revision=doc.revision,
        )
        source_video = doc.assets[-1].id
        info = await api.handle(
            "GET", f"/structured-director/assets/{source_video}/video-frame-info"
        )
        assert info.status == 200
        assert info.body["frame_count"] == 5
        assert info.body["duration_seconds"] == pytest.approx(1.0)
        response = await api.handle(
            "POST",
            f"/structured-director/assets/{source_video}/video-frame",
            json.dumps({"expected_revision": doc.revision, "frame_index": 2}).encode(),
        )
        assert response.status == 200, response.body
        doc = store.read()
        generation_id = doc.generations[-1].id
        assert provider.requests[-1].frame_index == 2
        assert doc.generations[-1].video_frame_request.source_segment_id is None
        doc = await service._generation_observer.refresh_generation(generation_id)
        frame_asset = doc.generations[-1].output_asset_id
        assert frame_asset is not None
        assert doc.generations[-1].kind is ReferenceGenerationKind.VIDEO_FRAME
        assert next(x for x in doc.assets if x.id == frame_asset).display_name.endswith(
            "-抽帧-第2帧.png"
        )

        # 只有 VIDEO_FRAME 的输出关系，没有正式项目绑定。
        assert asset_project_usage_reasons(doc, frame_asset) == ()
        assert asset_usage_reasons(doc, frame_asset) == ()
        closure = asset_deletion_closure(doc, frame_asset)
        assert closure is not None
        assert closure.asset_ids == frozenset({frame_asset})
        assert closure.generation_ids == frozenset({generation_id})
        assert closure.retains_derived_assets is False

        snapshot = await api.handle("GET", "/structured-director")
        projected = {item["id"]: item for item in snapshot.body["assets"]}
        assert projected[frame_asset]["is_in_use"] is False
        assert projected[frame_asset]["usage_reasons"] == []
        assert projected[frame_asset]["allowed_actions"] == ["delete"]
        assert projected[source_video]["is_in_use"] is False
        # 抽帧图是独立的图片分类，供资产中心单独页签浏览。
        assert projected[frame_asset]["image_category"] == "video_frame"
        assert (
            next(item for item in doc.assets if item.id == frame_asset).image_category
            is ImageAssetCategory.VIDEO_FRAME
        )
        _, frame_bytes = store.read_asset(frame_asset)
        with pytest.raises(ValueError, match="已经归入抽帧图"):
            await service.import_image_asset(
                media_type="image/png",
                content=frame_bytes,
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=doc.revision,
            )

        # 删除源 MP4 只清理失去可复现性的 Generation，PNG 保留且不被伪造为使用中。
        assert asset_usage_reasons(doc, source_video) == ()
        source_closure = asset_deletion_closure(doc, source_video)
        assert source_closure is not None
        assert source_closure.asset_ids == frozenset({source_video})
        assert source_closure.generation_ids == frozenset({generation_id})
        assert source_closure.retains_derived_assets is True

        # 服务重启后判断完全一致。
        restarted = StructuredDirectorStore(store.path.parent, "a" * 32)
        restarted_document = restarted.read()
        assert asset_usage_reasons(restarted_document, frame_asset) == ()
        purged = restarted.delete_asset(frame_asset, expected_revision=restarted_document.revision)
        assert frame_asset not in {item.id for item in purged.assets}
        assert source_video in {item.id for item in purged.assets}
        assert generation_id not in {item.id for item in purged.generations}

    asyncio.run(scenario())


def test_asset_frame_submission_uncertain_retry_keeps_frame_index(tmp_path):
    _needs_ffmpeg()

    async def scenario():
        store, _, doc, _ = await _visual_project(str(tmp_path))
        provider = FlakyFrameProvider(tmp_path)
        service = make_service(store, video_frame_provider=provider)
        doc = await service.import_media_asset(
            media_type="video/mp4",
            content=make_video(tmp_path / "retry.mp4", "blue"),
            expected_revision=doc.revision,
        )
        source_asset = doc.assets[-1].id
        doc = await service._media.extract_asset_video_frame(
            asset_id=source_asset, frame_index=3, expected_revision=doc.revision
        )
        uncertain = doc.generations[-1]
        assert uncertain.phase.value == "submission_uncertain"
        # 结果未知的任务仍保护其输入，但不会伪造输出 PNG 的使用状态。
        assert asset_usage_reasons(doc, source_asset) == (
            AssetUsageReason.UNFINISHED_GENERATION_INPUT,
        )
        doc = await service.retry_generation(uncertain.id, expected_revision=doc.revision)
        retry = doc.generations[-1]
        assert retry.retry_of == uncertain.id
        assert retry.phase.value == "queued"
        assert retry.video_frame_request.frame_index == 3
        assert provider.requests[-1].frame_index == 3
        doc = await service._generation_observer.refresh_generation(retry.id)
        assert doc.generations[-1].phase.value == "succeeded"
        frame_asset = doc.generations[-1].output_asset_id
        assert frame_asset is not None
        assert asset_usage_reasons(doc, frame_asset) == ()

    asyncio.run(scenario())


def test_start_frame_card_toggles_boundary_sharing_with_previous_segment(tmp_path):
    async def scenario():
        store, service, doc, _ = await _visual_project(
            str(tmp_path), script_proposer=ContinuousScript()
        )
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        source, target = shot_segments_at(doc.director_script.scenes[0], 0)
        previous_end = _binding(doc, source.id).end_keyframe_id

        async def toggle(shared):
            response = await api.handle(
                "PUT",
                f"/structured-director/segments/{target.id}/keyframe-boundary",
                json.dumps({"expected_revision": store.read().revision, "shared": shared}).encode(),
            )
            assert response.status == 200, response.body
            return store.read()

        doc = await toggle(True)
        assert _binding(doc, target.id).start_keyframe_id == previous_end
        assert _binding(doc, source.id).end_enabled and _binding(doc, target.id).start_enabled
        doc = await toggle(False)
        start = _binding(doc, target.id).start_keyframe_id
        assert start != previous_end
        frame = next(item for item in doc.keyframe_plan.keyframes if item.id == start)
        assert (frame.owner_segment_id, frame.predecessor_keyframe_id) == (target.id, None)
        with pytest.raises(ValueError, match="第一个 Segment"):
            await service.save_segment_boundary_sharing(
                segment_id=source.id, shared=True, expected_revision=doc.revision
            )

    asyncio.run(scenario())
