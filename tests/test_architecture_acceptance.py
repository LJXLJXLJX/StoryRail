"""混合生产的单路径受控验收；合成媒体只证明 Core 流程，不证明视觉质量。"""

import asyncio
from dataclasses import replace

import pytest
from conftest import make_service
from script_helpers import shot_segments_at
from structured_director_fixtures import RecordingProvider
from test_scene_driver_invariants import MixedProposer, insert_shot, narration_project, select_audio
from video_recipes import save_video_inputs

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.model_providers.boundary import GenerationPhase
from core.structured_director import StructuredDirectorService, StructuredDirectorStore


class SilentMixedProposer(MixedProposer):
    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        narration, drama = proposal.scenes
        drama = replace(
            drama,
            shots=tuple(replace(shot, visible_character_ids=()) for shot in drama.shots),
            segments=tuple(replace(segment, dialogue_lines=()) for segment in drama.segments),
        )
        return replace(proposal, scenes=(narration, drama))


def test_mixed_tts_to_approval_survives_restart_without_automatic_generation(tmp_path):
    asyncio.run(mixed_acceptance(tmp_path))


async def mixed_acceptance(
    path, service_transform=lambda service: service, project_factory=narration_project
):
    store, service, speech, document = await project_factory(path, SilentMixedProposer())
    language_count = len(document.narration_languages)
    service = service_transform(service)
    assert [s.driver for s in document.director_script.scenes] == ["narration", "drama"]
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="必须先选择项目所选语言的 TTS"):
        insert_shot(DirectorCommandRegistry(store), document)
    assert store.path.read_bytes() == before
    document = await select_audio(service, document)
    document = insert_shot(DirectorCommandRegistry(store), document).document
    assert (
        sum(
            s.duration_estimate_seconds
            for s in shot_segments_at(document.director_script.scenes[0], 0)
        )
        == 16
    )
    document = await service.unlock_visual_production(expected_revision=document.revision)
    left, right, drama = document.keyframe_plan.segments
    # Shot 内边界默认是两个独立 Keyframe，启用状态由用户或 Director 决定。
    assert left.end_keyframe_id != right.start_keyframe_id
    assert not (left.end_enabled or right.start_enabled)
    image = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nfixture")
    video = RecordingProvider(
        media_type="video/mp4", content=b"\x00\x00\x00\x18ftypmp42fixture", duration_seconds=8
    )
    final = RecordingProvider(
        media_type="video/mp4", content=b"\x00\x00\x00\x18ftypmp42final", duration_seconds=22
    )

    def restore():
        return service_transform(
            make_service(
                StructuredDirectorStore(path, document.project_id),
                image_provider=image,
                fl2va_provider=video,
                speech_provider=speech,
                final_assembly_provider=final,
            )
        )

    # No compilers configured: all remaining production operations are deterministic.
    service = restore()
    # 显式共享 Shot 内边界，覆盖同一 Keyframe identity 的 seam_blend 装配路径。
    document = (
        await service.execute_director_command(
            DirectorCommand(
                "keyframe.apply_operations",
                document.revision,
                "acceptance-share",
                {
                    "operations": [
                        {
                            "op": "share_boundary",
                            "left_segment_id": left.segment_id,
                            "right_segment_id": right.segment_id,
                            "expected_adjacency": "intra_shot",
                        }
                    ]
                },
            )
        )
    ).document
    operations = [
        {
            "op": "set_activation",
            "segment_id": binding.segment_id,
            "start_enabled": True,
            "end_enabled": True,
        }
        for binding in document.keyframe_plan.segments
    ]
    operations.extend(
        {
            "op": "update_frame_fields",
            "keyframe_id": frame.id,
            "fields": {
                "environment_view_id": None,
                "prompt_text": "静态空站台，固定机位。",
                "visible_character_ids": [],
                "environment_mode": "none",
                "environment_none_reason": "Shot 未绑定地点视图",
            },
        }
        for frame in document.keyframe_plan.keyframes
    )
    document = (
        await service.execute_director_command(
            DirectorCommand(
                "keyframe.apply_operations",
                document.revision,
                "acceptance-frames",
                {"operations": operations},
            )
        )
    ).document
    assert (
        len(document.generations) == language_count
    )  # 中英 TTS only; planning never submits media.
    for index, frame in enumerate(document.keyframe_plan.keyframes):
        image.content = b"\x89PNG\r\n\x1a\nfixture" + bytes([index])
        document = await service.generate_keyframe(
            keyframe_id=frame.id, expected_revision=document.revision
        )
        generation_id = document.generations[-1].id
        count = len(image.requests)
        # Restart after persisted submission, before success. Observe the same generation.
        service = restore()
        image.observations = [GenerationPhase.SUCCEEDED]
        document = await service._generation_observer.refresh_generation(generation_id)
        assert len(image.requests) == count
        assert (
            next(f for f in document.keyframe_plan.keyframes if f.id == frame.id).selected_asset_id
            is None
        )
        assert len(document.generations) == language_count + 1 + index
        document = await service.select_keyframe(
            keyframe_id=frame.id,
            asset_id=document.generations[-1].output_asset_id,
            expected_revision=document.revision,
        )
        assert len(image.requests) == count  # Selection does not continue generation.

    for index, binding in enumerate(document.keyframe_plan.segments):
        document = await save_video_inputs(
            service,
            segment_id=binding.segment_id,
            prompt_text="固定机位观察空站台，无对白。",
            expected_revision=document.revision,
        )
        video.duration_seconds = 8 if index < 2 else 6
        video.content = b"\x00\x00\x00\x18ftypmp42fixture" + bytes([index])
        document = await service._media.generate_segment_video(
            segment_id=binding.segment_id, expected_revision=document.revision
        )
        generation_id = document.generations[-1].id
        service = restore()
        video.observations = [GenerationPhase.SUCCEEDED]
        document = await service._generation_observer.refresh_generation(generation_id)
        assert len(video.requests) == index + 1
        assert (
            next(
                v for v in document.video_plan.segments if v.segment_id == binding.segment_id
            ).selected_asset_id
            is None
        )
        document = await service.select_segment_video(
            segment_id=binding.segment_id,
            asset_id=document.generations[-1].output_asset_id,
            expected_revision=document.revision,
        )
    # 最终成片只拼接 Scene 成片：先逐 Scene 渲染中英两版，再做项目级拼接。
    for index, scene in enumerate(document.director_script.scenes):
        final.content = b"\x00\x00\x00\x18ftypmp42scenefinal" + bytes([index])
        document = await service.generate_scene_final_video(
            scene_id=scene.id, expected_revision=document.revision
        )
        for generation_id in [item.id for item in document.generations[-language_count:]]:
            final.observations = [GenerationPhase.SUCCEEDED]
            document = await service._generation_observer.refresh_generation(generation_id)
    final.content = b"\x00\x00\x00\x18ftypmp42final"
    document = await service.generate_final_video(expected_revision=document.revision)
    narration_scene_request = final.requests[0]
    drama_scene_request = final.requests[language_count]
    request = final.requests[2 * language_count]
    # 所选语言的 Scene 成片画面时间轴一致，只换旁白音轨。
    for other in final.requests[:language_count]:
        assert [c.duration_seconds for c in narration_scene_request.clips] == [
            c.duration_seconds for c in other.clips
        ]
    for other in final.requests[2 * language_count :]:
        assert [c.duration_seconds for c in request.clips] == [
            c.duration_seconds for c in other.clips
        ]
    assert [c.transition_from_previous for c in narration_scene_request.clips] == [
        None,
        "seam_blend",
    ]
    assert sum(
        c.duration_seconds for c in narration_scene_request.clips[:2]
    ) - narration_scene_request.transition_seconds == pytest.approx(16)
    assert len(narration_scene_request.narrations) == 1
    assert narration_scene_request.narrations[0].start_clip_index == 0
    assert narration_scene_request.narrations[0].content == speech.content
    assert [c.transition_from_previous for c in drama_scene_request.clips] == [None]
    assert drama_scene_request.clips[0].duration_seconds == 6
    assert drama_scene_request.narrations == ()
    # 最终请求只按脚本顺序拼接 Scene 成片，不再传递原始 Segment 或旁白。
    assert [c.transition_from_previous for c in request.clips] == [None, None]
    assert request.narrations == ()
    assert request.clips[0].duration_seconds == 22
    service = restore()
    for generation_id in [item.id for item in document.generations[-language_count:]]:
        final.observations = [GenerationPhase.SUCCEEDED]
        document = await service._generation_observer.refresh_generation(generation_id)
    assert len(final.requests) == 3 * language_count
    for generation_id in [item.id for item in document.generations[-language_count:]]:
        document = await service.select_final_video(
            generation_id=generation_id, expected_revision=document.revision
        )
    assert document.final_approval is None
    document = await service.approve_final_video(expected_revision=document.revision)
    assert restore().snapshot() == document
    assert document.final_approval is not None
    return document


if __name__ == "__main__":
    # Regenerate the Web contract fixture only from an isolated current Core workflow.
    import json
    import sys
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from core.structured_director.reads.snapshot_view import serialize_snapshot

    # 无参数保持原行为（写回 web/src/test）；传路径时供 freshness 门禁写到临时目录比较。
    output = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("web/src/test/mixed_approval_fixture.json")
    )
    with TemporaryDirectory(prefix="storyrail-mixed-contract-") as directory:
        fixture_path = Path(directory)
        result = asyncio.run(mixed_acceptance(fixture_path))
        snapshot = serialize_snapshot(
            result,
            StructuredDirectorService(StructuredDirectorStore(fixture_path, result.project_id)),
            resource_path=f"/api/projects/{result.project_id}/structured-director",
        )
        output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
