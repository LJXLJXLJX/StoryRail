"""同源专业输入→内置Writer/MCP→Core；fake Provider只检查实际请求字节。"""

import asyncio
import json
import struct
from dataclasses import replace

from script_helpers import shot_segments_at
from structured_director_fixtures import install_location, wav_bytes
from test_director_commands import _ScriptCompiler, _visual_project
from video_recipes import (
    SegmentVideoAudioReference,
    SegmentVideoGenerationMode,
    SegmentVideoImageReference,
    SegmentVideoVideoReference,
    h3_dialogue_prompt,
    replace_video,
    replace_video_provider,
    save_video_inputs,
    set_video_settings,
    video_prompt_workset,
    video_slot,
    video_wire_dict,
    video_wire_slot,
)

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals import DialogueLineProposal
from core.structured_director import ImageAssetCategory
from core.structured_director.production_context import _production_state_json
from core.structured_director.reads.semantic_projection import build_semantic_projection
from core.structured_director.reads.snapshot_view import serialize_snapshot
from core.structured_director.script_index import shot_segments
from core.structured_director.video_inputs import dialogue_audio_bindings
from scripts.harness.fixtures.candidates import register_dialogue_audio_candidate


def _descriptions(workset, role):
    return tuple(
        item["description"] for item in workset["context"]["bindings"] if item["role"] == role
    )


def _mp4_bytes(*, duration_seconds: float) -> bytes:
    def box(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I4s", len(payload) + 8, kind) + payload

    mvhd = box(
        b"mvhd",
        b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1_000, int(duration_seconds * 1_000)),
    )
    return box(b"ftyp", b"isom\x00\x00\x02\x00isom") + box(b"moov", mvhd)


class PromptScript(_ScriptCompiler):
    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        scene = proposal.scenes[0]
        first, second = scene.shots
        a, b = kwargs["characters"]
        segments = tuple(
            replace(
                segment,
                dialogue_lines=(
                    (
                        DialogueLineProposal(b.id, "先听我说。", "平静。"),
                        DialogueLineProposal(a.id, "好的。", "低声。"),
                        DialogueLineProposal(b.id, "我们开始。", "平静。"),
                    )
                    if index == 0
                    else ()
                ),
            )
            for index, segment in enumerate(scene.segments)
        )
        return replace(
            proposal,
            scenes=(
                replace(
                    scene,
                    shots=(
                        replace(first, visible_character_ids=(a.id, b.id)),
                        second,
                    ),
                    segments=segments,
                ),
            ),
        )


async def fixture(tmp_path):
    store, service, doc, _ = await _visual_project(str(tmp_path), script_proposer=PromptScript())
    registry = DirectorCommandRegistry(store)
    operations = [
        {
            "op": "set_activation",
            "segment_id": b.segment_id,
            "start_enabled": True,
            "end_enabled": True,
        }
        for b in doc.keyframe_plan.segments
    ]
    operations += [
        {
            "op": "update_frame_fields",
            "keyframe_id": f.id,
            "fields": {
                "prompt_text": f"静态边界{index}",
            },
        }
        for index, f in enumerate(doc.keyframe_plan.keyframes)
    ]
    doc = registry.execute(
        DirectorCommand(
            "keyframe.apply_operations", doc.revision, "setup", {"operations": operations}
        )
    ).document
    for index, frame in enumerate(doc.keyframe_plan.keyframes):
        doc = await service.import_image_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\nfixture" + bytes([index]),
            category=ImageAssetCategory.KEYFRAME,
            expected_revision=doc.revision,
        )
        doc = await service.select_keyframe(
            keyframe_id=frame.id, asset_id=doc.assets[-1].id, expected_revision=doc.revision
        )
    for index, character in enumerate(doc.reference_library.characters):
        doc = await service.upload_reference_voice(
            card_id=character.id,
            media_type="audio/wav",
            content=wav_bytes(duration_seconds=2) + bytes([index]),
            expected_revision=doc.revision,
        )
        current = next(item for item in doc.reference_library.characters if item.id == character.id)
        doc = await service.update_character(
            replace(current, voice_reference_transcript=f"{character.name} 的音色参考文字稿。"),
            expected_revision=doc.revision,
        )
    cards = {item.id: item for item in doc.reference_library.characters}
    segment = doc.director_script.scenes[0].segments[0]
    starts = {}
    cursor = 0.25
    for index, line in enumerate(segment.dialogue_lines):
        card = cards[line.character_id]
        doc = await service.import_media_asset(
            media_type="audio/wav",
            content=wav_bytes(duration_seconds=1.0) + bytes([100 + index]),
            expected_revision=doc.revision,
        )
        dialogue_asset_id = doc.assets[-1].id
        generation_id = register_dialogue_audio_candidate(
            store,
            dialogue_line_id=line.id,
            source_asset_id=dialogue_asset_id,
            voice_reference_asset_id=card.voice_reference_asset_id,
            reference_transcript=card.voice_reference_transcript,
            text=line.text,
        )
        doc = await service.select_dialogue_audio(
            dialogue_line_id=line.id,
            generation_id=generation_id,
            expected_revision=store.read().revision,
        )
        starts[line.id] = cursor
        cursor += 1.25
    scene = doc.director_script.scenes[0]
    doc = registry.execute(
        DirectorCommand(
            "video.set_recipe",
            doc.revision,
            "mode",
            video_wire_dict(
                {
                    "scope": {"scene_ids": [scene.id]},
                    "segment_id": scene.segments[0].id,
                    "generation_mode": "ref2va",
                }
            ),
        )
    ).document
    doc = await save_video_inputs(
        service,
        segment_id=scene.segments[0].id,
        prompt_text="",
        additional_image_references=(),
        # 三句对白 TTS 已占满 H3 官方节点的 3 条参考音频上限，不再追加角色音色参考。
        audio_references=(),
        expected_revision=doc.revision,
    )
    current_video = doc.video_plan.segments[0]
    doc = await save_video_inputs(
        service,
        segment_id=segment.id,
        prompt_text=current_video.prompt_text,
        audio_references=(
            *video_slot(current_video, "reference_audios"),
            *dialogue_audio_bindings(doc, segment.id),
        ),
        expected_revision=doc.revision,
    )
    selected = {f.id: f.selected_asset_id for f in doc.keyframe_plan.keyframes}
    # 手工辅助图只供Keyframe；H3不得把它列作实际Picture。
    doc = await service.import_image_asset(
        media_type="image/png",
        content=b"\x89PNG\r\n\x1a\naux",
        category=ImageAssetCategory.KEYFRAME,
        expected_revision=doc.revision,
    )
    aux = doc.assets[-1].id
    doc = registry.execute(
        DirectorCommand(
            "keyframe.apply_operations",
            doc.revision,
            "aux",
            {
                "operations": [
                    {
                        "op": "set_aux_references",
                        "segment_id": scene.segments[0].id,
                        "asset_ids": [aux],
                    }
                ],
            },
        )
    ).document
    # 辅助图修改会使关联选择失效；由Core显式重新选择原测试图。
    for frame in doc.keyframe_plan.keyframes:
        if frame.selected_asset_id is None:
            asset_id = selected[frame.id]
            doc = await service.select_keyframe(
                keyframe_id=frame.id, asset_id=asset_id, expected_revision=doc.revision
            )
    # 任何会失效视频输入的准备动作都完成后，再建立最终对白时序。
    doc = await service.set_dialogue_timing(
        segment_id=segment.id,
        starts=starts,
        duration_seconds=cursor + 0.25,
        expected_revision=doc.revision,
    )
    return store, service, doc, aux


def test_manifest_matches_actual_fake_provider_request_and_language(tmp_path):
    from structured_director_fixtures import RecordingProvider

    async def run():
        store, service, document, additional_asset_id = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        segment = scene.segments[0]

        await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=document.revision,
            prompt_text="中文正文；无字幕、无水印。",
            additional_image_references=(
                SegmentVideoImageReference(
                    additional_asset_id, "保持图中红色行李箱的外观和材质一致。"
                ),
            ),
            audio_references=video_slot(document.video_plan.segments[0], "reference_audios"),
        )
        workset = video_prompt_workset(store.read(), segment.id)
        assert all(item.kind.value == "dialogue_audio" for item in store.read().generations)
        # 单 Shot Segment：工作集只列一个 Shot，且不延续相邻 Segment。
        single = workset["context"]
        assert [(item["action"], item["visible_character_names"]) for item in single["shots"]] == [
            (scene.shots[0].action, ["甲", "乙"])
        ]
        assert single["segment"]["continues_from_previous_segment"] is False
        assert single["segment"]["continues_into_next_segment"] is False
        prompt_text = h3_dialogue_prompt(workset, tail="\n无字幕、无水印。")
        await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=store.read().revision,
            prompt_text=prompt_text,
        )
        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        # 全局插件设置在提交时读取，随请求交给插件。
        set_video_settings(
            service, preset="turbo_v2", resolution="1080p", sage_attention=False, selflift=True
        )
        await service._media.generate_segment_video(
            segment_id=segment.id, expected_revision=store.read().revision
        )
        request = provider.requests[-1]
        assert dict(request.settings) == {
            "preset": "turbo_v2",
            "resolution": "1080p",
            "sage_attention": False,
            "selflift": True,
        }
        assert request.param("aspect_ratio") == document.aspect_ratio.value
        assets = {
            item["label"]: store.read_asset(item["asset_id"])[1] for item in workset["asset_inputs"]
        }
        assert request.single("first_frame").content == assets["<Picture 1>"]
        assert request.single("last_frame").content == assets["<Picture 2>"]
        assert request.slot("additional_images")[0].content == assets["<Picture 3>"]
        assert [audio.content for audio in request.slot("reference_audios")] == [
            assets[f"<Audio {index}>"] for index in range(1, 4)
        ]
        assert len(store.read().generations[-1].input_asset_ids) == 6
        inputs = workset["context"]["actual_provider_inputs"]["inputs"]
        picture = inputs[2]
        assert {key: picture[key] for key in ("slot", "role", "label", "description")} == {
            "slot": "additional_images",
            "role": "reference_image",
            "label": "<Picture 3>",
            "description": "保持图中红色行李箱的外观和材质一致。",
        }
        audios = [item for item in inputs if item["slot"] == "reference_audios"]
        assert [item["label"] for item in audios] == [f"<Audio {index}>" for index in range(1, 4)]
        assert [item["description"] for item in audios] == [
            item.description
            for item in video_slot(document.video_plan.segments[0], "reference_audios")
        ]
        import pytest

        generation = store.read().generations[-1]
        replace(generation, input_asset_ids=tuple(f"{i:032x}" for i in range(17)))
        with pytest.raises(ValueError, match="17"):
            replace(generation, input_asset_ids=tuple(f"{i:032x}" for i in range(18)))
        # 已保存正文原样提交；Core 不再在结构外前置对白映射。
        assert request.param("prompt") == prompt_text

    asyncio.run(run())


def test_ref2va_submits_reference_videos_with_lineage(tmp_path):
    import pytest
    from structured_director_fixtures import RecordingProvider

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)

        # 时长越界的参考视频在提交路径被同一规则拒绝，且不创建 Generation。
        document = await service.import_media_asset(
            media_type="video/mp4",
            content=_mp4_bytes(duration_seconds=20.0),
            expected_revision=document.revision,
        )
        rejected_video = document.assets[-1]
        with pytest.raises(ValueError, match="参考视频必须是 2 到 15 秒"):
            await save_video_inputs(
                service,
                segment_id=segment.id,
                expected_revision=document.revision,
                prompt_text="中文正文；无字幕、无水印。",
                additional_image_references=(),
                audio_references=video_slot(document.video_plan.segments[0], "reference_audios"),
                video_references=(SegmentVideoVideoReference(rejected_video.id, "超出时长上限。"),),
            )
        assert all(item.kind.value == "dialogue_audio" for item in store.read().generations)

        document = await service.import_media_asset(
            media_type="video/mp4",
            content=_mp4_bytes(duration_seconds=3.0),
            expected_revision=store.read().revision,
        )
        reference_video = document.assets[-1]
        document = await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=document.revision,
            prompt_text="中文正文；无字幕、无水印。",
            additional_image_references=(),
            audio_references=video_slot(document.video_plan.segments[0], "reference_audios"),
            video_references=(SegmentVideoVideoReference(reference_video.id, "参考运镜与节奏。"),),
        )
        generated = await service._media.generate_segment_video(
            segment_id=segment.id,
            expected_revision=document.revision,
        )
        request = provider.requests[-1]
        assert [item.content for item in request.slot("reference_videos")] == [
            store.read_asset(reference_video.id)[1]
        ]
        assert [item.duration_seconds for item in request.slot("reference_videos")] == [3.0]
        generation = generated.generations[-1]
        assert reference_video.id in generation.input_asset_ids
        assert len(generation.input_asset_ids) == 6

    asyncio.run(run())


def test_video_labels_number_independently_and_map_to_provider_order(tmp_path):
    import pytest
    from structured_director_fixtures import RecordingProvider

    async def run():
        store, service, document, additional_asset_id = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        video_ids = []
        for seconds in (2.0, 4.0):
            document = await service.import_media_asset(
                media_type="video/mp4",
                content=_mp4_bytes(duration_seconds=seconds),
                expected_revision=document.revision,
            )
            video_ids.append(document.assets[-1].id)
        audio_references = video_slot(document.video_plan.segments[0], "reference_audios")
        document = await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=document.revision,
            prompt_text="中文正文；无字幕、无水印。",
            additional_image_references=(
                SegmentVideoImageReference(additional_asset_id, "保持行李箱外观一致。"),
            ),
            audio_references=audio_references,
            video_references=(
                SegmentVideoVideoReference(video_ids[1], "参考整体运镜节奏。"),
                SegmentVideoVideoReference(video_ids[0], "参考人物转身动作。"),
            ),
        )
        workset = video_prompt_workset(document, segment.id)
        context = workset["context"]
        assert [
            {"label": item["label"], "description": item["description"]}
            for item in context["bindings"]
            if item["slot"] == "reference_videos"
        ] == [
            {"label": "<Video 1>", "description": "参考整体运镜节奏。"},
            {"label": "<Video 2>", "description": "参考人物转身动作。"},
        ]
        manifest = context["actual_provider_inputs"]
        assert [
            (item["label"], item["index"], item["description"])
            for item in manifest["inputs"]
            if item["slot"] == "reference_videos"
        ] == [
            ("<Video 1>", 0, "参考整体运镜节奏。"),
            ("<Video 2>", 1, "参考人物转身动作。"),
        ]
        # Picture / Audio / Video 各自从 1 起编号，按类型分组稳定排列。
        assert manifest["allowed_asset_reference_labels"] == [
            "<Picture 1>",
            "<Picture 2>",
            "<Picture 3>",
            "<Audio 1>",
            "<Audio 2>",
            "<Audio 3>",
            "<Video 1>",
            "<Video 2>",
        ]
        assert [item["label"] for item in workset["asset_inputs"]] == manifest[
            "allowed_asset_reference_labels"
        ]
        labeled = {item["label"]: item["asset_id"] for item in workset["asset_inputs"]}
        assert labeled["<Video 1>"] == video_ids[1]
        assert labeled["<Video 2>"] == video_ids[0]
        assert labeled["<Audio 1>"] == audio_references[0].asset_id

        # 引用的参考视频 Asset 缺失时，项目文档本身即不成立，工作集无从构建。
        with pytest.raises(ValueError, match="视频参考输入必须引用本项目 Asset"):
            replace(
                document,
                assets=tuple(item for item in document.assets if item.id != video_ids[0]),
            )

        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        await service._media.generate_segment_video(
            segment_id=segment.id, expected_revision=document.revision
        )
        request = provider.requests[-1]
        assert [item.content for item in request.slot("reference_videos")] == [
            store.read_asset(labeled["<Video 1>"])[1],
            store.read_asset(labeled["<Video 2>"])[1],
        ]
        assert [item.duration_seconds for item in request.slot("reference_videos")] == [4.0, 2.0]

        state = json.loads(_production_state_json(store.read()))
        video_state = next(
            item["video"]
            for scene in state["scenes"]
            for item in scene.get("segments", ())
            if item["id"] == segment.id
        )
        assert [item["asset_id"] for item in video_wire_slot(video_state, "reference_videos")] == [
            video_ids[1],
            video_ids[0],
        ]
        snapshot_plan = serialize_snapshot(store.read(), service, "/project")["video_plan"]
        assert video_wire_slot(snapshot_plan["segments"][0], "reference_videos") == [
            {"asset_id": video_ids[1], "description": "参考整体运镜节奏。"},
            {"asset_id": video_ids[0], "description": "参考人物转身动作。"},
        ]

    asyncio.run(run())


def test_ref2va_submits_additional_images_without_manual_reference_audio(tmp_path):
    from structured_director_fixtures import RecordingProvider

    async def run():
        store, service, document, additional_asset_id = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        document = await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=document.revision,
            prompt_text="仅使用图片参考保持仓库场景一致。",
            additional_image_references=(
                SegmentVideoImageReference(
                    additional_asset_id, "保持仓库墙面、货架和红色行李箱一致。"
                ),
            ),
            audio_references=dialogue_audio_bindings(document, segment.id),
        )
        workset = video_prompt_workset(document, segment.id)
        inputs = workset["context"]["actual_provider_inputs"]["inputs"]
        assert len([item for item in inputs if item["slot"] == "reference_audios"]) == 3
        assert [item["label"] for item in workset["asset_inputs"]] == [
            "<Picture 1>",
            "<Picture 2>",
            "<Picture 3>",
            "<Audio 1>",
            "<Audio 2>",
            "<Audio 3>",
        ]

        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        generated = await service._media.generate_segment_video(
            segment_id=segment.id,
            expected_revision=document.revision,
        )
        request = provider.requests[-1]
        assert len(request.slot("reference_audios")) == 3
        assert len(request.slot("additional_images")) == 1
        assert len(generated.generations[-1].input_asset_ids) == 6

    asyncio.run(run())


def test_invalid_input_and_specialized_scope_are_read_only(tmp_path):
    import pytest

    store, service, document, _ = asyncio.run(fixture(tmp_path))
    scene = document.director_script.scenes[0]
    segment = scene.segments[0]
    with pytest.raises(ValueError, match="必须填写说明"):
        SegmentVideoImageReference(document.assets[0].id, "   ")
    with pytest.raises(ValueError, match="必须填写说明"):
        SegmentVideoAudioReference(document.assets[0].id, "   ")
    with pytest.raises(ValueError, match="必须填写说明"):
        SegmentVideoVideoReference(document.assets[0].id, "   ")
    current_video = document.video_plan.segments[0]
    with pytest.raises(ValueError, match="0 到 3 项"):
        replace_video(
            current_video,
            audio_references=tuple(
                SegmentVideoAudioReference(f"{index + 1:032x}", "通用参考音频。")
                for index in range(4)
            ),
        )
    with pytest.raises(ValueError, match="不能重复"):
        replace_video(
            current_video,
            audio_references=(
                video_slot(current_video, "reference_audios")[0],
                video_slot(current_video, "reference_audios")[0],
            ),
        )
    with pytest.raises(ValueError, match="0 到 3 项"):
        replace_video(
            current_video,
            video_references=tuple(
                SegmentVideoVideoReference(f"{index + 1:032x}", "参考运镜。") for index in range(4)
            ),
        )
    with pytest.raises(ValueError, match="不能重复"):
        replace_video(
            current_video,
            video_references=(
                SegmentVideoVideoReference(document.assets[0].id, "参考运镜。"),
                SegmentVideoVideoReference(document.assets[0].id, "重复引用。"),
            ),
        )
    with pytest.raises(ValueError, match="不支持槽位"):
        replace_video(
            current_video,
            generation_mode=SegmentVideoGenerationMode.FL2VA,
            additional_image_references=(),
            audio_references=(),
            video_references=(SegmentVideoVideoReference(document.assets[0].id, "参考运镜。"),),
        )
    before = store.path.read_bytes()
    characters = document.reference_library.characters
    missing_voice = replace(
        document,
        reference_library=replace(
            document.reference_library,
            characters=(replace(characters[0], voice_reference_asset_id=None), characters[1]),
        ),
    )
    assert _descriptions(video_prompt_workset(missing_voice, segment.id), "reference_audio")
    quiet_segment = shot_segments_at(scene, 1)[0]
    generic_audio_video = replace_video(
        next(item for item in document.video_plan.segments if item.segment_id == quiet_segment.id),
        generation_mode=SegmentVideoGenerationMode.REF2VA,
        audio_references=(
            SegmentVideoAudioReference(
                characters[1].voice_reference_asset_id, "原样使用这段对白。"
            ),
        ),
    )
    generic_audio_document = replace(
        document,
        video_plan=replace(
            document.video_plan,
            segments=tuple(
                generic_audio_video if item.segment_id == quiet_segment.id else item
                for item in document.video_plan.segments
            ),
        ),
    )
    generic_audio_workset = video_prompt_workset(generic_audio_document, quiet_segment.id)
    assert not generic_audio_workset["context"]["segment"]["dialogue"]
    assert _descriptions(generic_audio_workset, "reference_audio") == ("原样使用这段对白。",)
    audio_only_document = replace(
        generic_audio_document,
        keyframe_plan=replace(
            generic_audio_document.keyframe_plan,
            segments=tuple(
                replace(item, start_enabled=False, end_enabled=False)
                if item.segment_id == quiet_segment.id
                else item
                for item in generic_audio_document.keyframe_plan.segments
            ),
        ),
    )
    audio_only_workset = video_prompt_workset(audio_only_document, quiet_segment.id)
    assert audio_only_workset["context"]["recipe_id"] == "sample_video.ref2va"
    assert audio_only_workset["context"]["segment"]["start_frame_description"] is None
    assert audio_only_workset["context"]["segment"]["end_frame_description"] is None
    assert _descriptions(audio_only_workset, "reference_audio") == ("原样使用这段对白。",)
    audio_only_inputs = audio_only_workset["context"]["actual_provider_inputs"]["inputs"]
    assert [item["slot"] for item in audio_only_inputs] == ["reference_audios"]
    missing_audio = replace(
        document,
        video_plan=replace(
            document.video_plan,
            segments=tuple(
                replace_video(item, audio_references=()) if item.segment_id == segment.id else item
                for item in document.video_plan.segments
            ),
        ),
    )
    image_only_workset = video_prompt_workset(missing_audio, segment.id)
    assert image_only_workset["context"]["recipe_id"] == "sample_video.ref2va"
    assert _descriptions(image_only_workset, "reference_audio") == ()
    missing_frame = replace(
        document,
        keyframe_plan=replace(
            document.keyframe_plan,
            keyframes=tuple(
                replace(f, selected_asset_id=None) for f in document.keyframe_plan.keyframes
            ),
        ),
    )
    with pytest.raises(ValueError, match="尚未选择"):
        video_prompt_workset(missing_frame, segment.id)
    with pytest.raises(ValueError, match="duration_estimate_seconds"):
        replace(segment, duration_estimate_seconds=0.1)
    with pytest.raises(ValueError, match="Segment层级"):
        build_semantic_projection(
            document,
            {"level": "scene", "scope": {"scene_ids": [scene.id]}, "extensions": ["video_prompt"]},
        )
    with pytest.raises(ValueError, match="越出"):
        build_semantic_projection(
            document,
            {
                "level": "segment",
                "scope": {"scene_ids": [scene.id]},
                "ids": ["e" * 32],
                "extensions": ["video_prompt"],
            },
        )
    assert store.path.read_bytes() == before


def test_mcp_prompt_commit_lost_response_replay_and_invalidated_boundary(tmp_path):
    from unittest.mock import patch

    from mcp import Client
    from test_slatehand_mcp import endpoint

    from core.application.caller import Caller, MutationGrant, command_digest
    from server.http import SlatehandRequestHandler

    store, service, document, _ = asyncio.run(fixture(tmp_path))
    scene = document.director_script.scenes[0]
    segment = scene.segments[0]
    target = document.keyframe_plan.segments[0].start_keyframe_id
    h3_args = {
        "scope": {"scene_ids": [scene.id]},
        "segment_id": segment.id,
        "prompt_text": "中文正文；无字幕。",
    }
    frame_args = {
        "operations": [
            {
                "op": "update_frame_fields",
                "keyframe_id": target,
                "fields": {"prompt_text": "单帧新正文。"},
            }
        ]
    }
    grants = tuple(
        MutationGrant(
            str(index),
            document.project_id,
            command_digest({"name": name, "arguments": args, "expected_revision": revision}),
            4102444800,
        )
        for index, (name, args, revision) in enumerate(
            [
                ("video.set_prompt", h3_args, document.revision),
                ("keyframe.apply_operations", frame_args, document.revision + 1),
            ]
        )
    )
    caller = Caller(
        "prompt",
        "agent",
        frozenset({document.project_id}),
        frozenset({"project.read", "project.mutate"}),
        4102444800,
        grants,
        True,
    )
    original = SlatehandRequestHandler._send_json
    dropped = []

    def drop_once(handler, status, value):
        if status == 200 and "application_request_id" in value and not dropped:
            dropped.append(True)
            handler.close_connection = True
            handler.connection.shutdown(2)
            handler.connection.close()
            return
        original(handler, status, value)

    async def run(params):
        base = {
            "project_id": document.project_id,
            "expected_revision": document.revision,
            "idempotency_key": "video_prompt",
        }
        request = {
            **base,
            "scene_ids": [scene.id],
            "segment_id": segment.id,
            "prompt_text": h3_args["prompt_text"],
        }
        async with Client(params) as client:
            read = await client.call_tool(
                "read_story",
                {
                    **base,
                    "level": "segment",
                    "scene_ids": [scene.id],
                    "ids": [segment.id],
                    "extensions": ["video_prompt", "keyframe"],
                },
            )
            assert not read.is_error
            with patch.object(SlatehandRequestHandler, "_send_json", drop_once):
                lost = await client.call_tool("save_video_prompt", request)
            assert lost.is_error and dropped
        committed = store.path.read_bytes()
        async with Client(params) as client:
            replay = await client.call_tool("save_video_prompt", request)
            assert replay.structured_content["replay"]
            assert store.path.read_bytes() == committed
            stale = await client.call_tool(
                "save_video_prompt", {**request, "idempotency_key": "stale"}
            )
            assert stale.is_error
            saved = await client.call_tool(
                "save_keyframe_prompt",
                {
                    **base,
                    "expected_revision": document.revision + 1,
                    "idempotency_key": "frame",
                    "keyframe_id": target,
                    "prompt_text": "单帧新正文。",
                },
            )
            assert not saved.is_error
            invalidated = await client.call_tool(
                "read_story",
                {
                    **base,
                    "expected_revision": store.read().revision,
                    "level": "segment",
                    "scene_ids": [scene.id],
                    "ids": [segment.id],
                    "extensions": ["video_prompt"],
                },
            )
            # 前置失效只让 video_prompt 扩展标记未就绪，读取本身仍成功。
            assert not invalidated.is_error
            projected = invalidated.structured_content["data"]["items"][0]
            assert projected["video_prompt"]["available"] is False
        current = store.read()
        assert current.assets == document.assets and current.generations == document.generations
        unrelated = {
            document.keyframe_plan.segments[1].start_keyframe_id,
            document.keyframe_plan.segments[1].end_keyframe_id,
        }
        assert [f for f in current.keyframe_plan.keyframes if f.id in unrelated] == [
            f for f in document.keyframe_plan.keyframes if f.id in unrelated
        ]

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))


def test_single_boundary_labels_follow_actual_enabled_slot(tmp_path):
    store, _, document, _ = asyncio.run(fixture(tmp_path))
    binding = document.keyframe_plan.segments[1]
    for start, end, slot in [(True, False, "first_frame"), (False, True, "last_frame")]:
        changed = replace(
            document,
            keyframe_plan=replace(
                document.keyframe_plan,
                segments=tuple(
                    replace(item, start_enabled=start, end_enabled=end)
                    if item.segment_id == binding.segment_id
                    else item
                    for item in document.keyframe_plan.segments
                ),
            ),
        )
        workset = video_prompt_workset(changed, binding.segment_id)
        inputs = workset["context"]["actual_provider_inputs"]["inputs"]
        assert [(item["slot"], item["label"]) for item in inputs] == [(slot, "<Picture 1>")]
        assert (workset["context"]["segment"]["start_frame_description"] is None) is not start
        assert (workset["context"]["segment"]["end_frame_description"] is None) is not end
        assert len(workset["asset_inputs"]) == 1


def test_fl2va_workset_without_boundary_frames_reads_as_t2va(tmp_path):
    store, _, document, _ = asyncio.run(fixture(tmp_path))
    binding = document.keyframe_plan.segments[1]
    changed = replace(
        document,
        keyframe_plan=replace(
            document.keyframe_plan,
            segments=tuple(
                replace(item, start_enabled=False, end_enabled=False)
                if item.segment_id == binding.segment_id
                else item
                for item in document.keyframe_plan.segments
            ),
        ),
    )
    workset = video_prompt_workset(changed, binding.segment_id)
    assert workset["context"]["recipe_id"] == "sample_video.fl2va"
    assert workset["context"]["duration_seconds"] == 3
    # 插件声明的帧网格让 3 秒请求实际输出 3.042 秒。
    assert workset["context"]["output_duration_seconds"] == 3.042
    assert workset["context"]["segment"]["start_frame_description"] is None
    assert workset["context"]["segment"]["end_frame_description"] is None
    assert workset["context"]["actual_provider_inputs"]["inputs"] == []
    assert workset["asset_inputs"] == []


def test_ref2va_reference_audio_has_no_duration_limit(tmp_path):
    from structured_director_fixtures import RecordingProvider

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        references = []
        for index, seconds in enumerate((0.5, 30.0)):
            document = await service.import_media_asset(
                media_type="audio/wav",
                content=wav_bytes(duration_seconds=seconds) + bytes([200 + index]),
                expected_revision=store.read().revision,
            )
            references.append(SegmentVideoAudioReference(document.assets[-1].id, "音色参考。"))
        document = await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=document.revision,
            prompt_text="中文正文；无字幕、无水印。",
            additional_image_references=(),
            audio_references=(*dialogue_audio_bindings(document, segment.id)[:1], *references),
            video_references=(),
        )
        await service._media.generate_segment_video(
            segment_id=segment.id,
            expected_revision=document.revision,
        )
        assert [audio.content for audio in provider.requests[-1].slot("reference_audios")][-2:] == [
            store.read_asset(reference.asset_id)[1] for reference in references
        ]

    asyncio.run(run())


def test_segment_over_soft_duration_limit_is_flagged_but_still_submitted(tmp_path):
    from structured_director_fixtures import RecordingProvider

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        segment = scene.segments[1]
        assert video_prompt_workset(document, segment.id)["exceeds_soft_duration_limit"] is False
        long_scene = replace(
            scene,
            segments=(scene.segments[0], replace(segment, duration_estimate_seconds=20.0)),
        )
        document = await service.save_script(
            (long_scene, *document.director_script.scenes[1:]),
            expected_revision=document.revision,
        )
        workset = video_prompt_workset(document, segment.id)
        assert workset["soft_duration_limit_seconds"] == 15
        assert workset["exceeds_soft_duration_limit"] is True
        document = await save_video_inputs(
            service,
            segment_id=segment.id,
            expected_revision=document.revision,
            prompt_text="中文正文；无字幕、无水印。",
        )
        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "fl2va", provider)
        replace_video_provider(service, "ref2va", provider)
        # 15 秒只是 Agent 侧软约束：用户坚持时 Core 原样提交，不截断也不拒绝。
        await service._media.generate_segment_video(
            segment_id=segment.id, expected_revision=store.read().revision
        )
        assert provider.requests[-1].param("duration_seconds") == 20.0

    asyncio.run(run())


def test_video_workset_marks_off_screen_dialogue_speakers(tmp_path):
    """倾听者镜头：说话者不在 Shot 可见角色中时，工作集把该句标为画外台词。"""

    async def run():
        _, service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        shot = scene.shots[0]
        segment = shot_segments(scene, shot.id)[0]
        speakers = [line.character_id for line in segment.dialogue_lines]
        dialogue = video_prompt_workset(document, segment.id)["context"]["segment"]["dialogue"]
        assert [item["on_screen"] for item in dialogue] == [True, True, True]

        listener = speakers[1]
        document = await service.save_script(
            (
                replace(
                    scene,
                    shots=(replace(shot, visible_character_ids=(listener,)), *scene.shots[1:]),
                ),
                *document.director_script.scenes[1:],
            ),
            expected_revision=document.revision,
        )
        dialogue = video_prompt_workset(document, segment.id)["context"]["segment"]["dialogue"]
        assert [item["on_screen"] for item in dialogue] == [
            speaker == listener for speaker in speakers
        ]

    asyncio.run(run())


def test_video_workset_carries_external_speakers_and_scene_driver(tmp_path):
    """引用库外说话者原样进入视频工作集；Scene driver 决定无对白时是否预留旁白通道。"""
    from core.structured_director import DialogueLine

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        shot = scene.shots[0]
        segment = shot_segments(scene, shot.id)[0]
        external = DialogueLine(
            None,
            "实验编号 0x04，开始宣读。",
            "平板",
            speaker_label="研究员",
            voice_description="冷静、克制的成年研究员声音。",
        )
        document = await service.save_script(
            (
                replace(
                    scene,
                    segments=(
                        replace(segment, dialogue_lines=(*segment.dialogue_lines, external)),
                        *scene.segments[1:],
                    ),
                ),
                *document.director_script.scenes[1:],
            ),
            expected_revision=document.revision,
        )
        # 持久化往返保留 speaker_label。
        stored = store.read().director_script.scenes[0].segments[0]
        assert stored.dialogue_lines[-1].id is not None
        assert replace(stored.dialogue_lines[-1], id=None) == external

        context = video_prompt_workset(document, segment.id)["context"]
        assert context["scene"]["driver"] == scene.driver
        line = dict(context["segment"]["dialogue"][-1])
        assert line.pop("dialogue_line_id") == stored.dialogue_lines[-1].id
        assert line == {
            "character_name": "研究员",
            "text": "实验编号 0x04，开始宣读。",
            "delivery": "平板",
            "on_screen": None,
        }

    asyncio.run(run())


def test_dialogue_runtime_does_not_estimate_seconds_before_tts(tmp_path):
    """无论文字多长，运行时都不换算秒数；视频工作集只报告真实 TTS 尚未选择。"""

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        shot = scene.shots[0]
        segment = shot_segments(scene, shot.id)[0]
        actual = video_prompt_workset(document, segment.id)["dialogue_timing"]
        assert actual["ready"] is True
        assets = {asset.id: asset for asset in document.assets}
        assert all(
            line["duration_seconds"] == assets[line["asset_id"]].duration_seconds
            for line in actual["lines"]
        )
        long_line = replace(segment.dialogue_lines[0], text="字" * 90)
        overloaded = replace(segment, duration_estimate_seconds=4.0, dialogue_lines=(long_line,))
        document = await service.save_script(
            (
                replace(scene, segments=(overloaded, *scene.segments[1:])),
                *document.director_script.scenes[1:],
            ),
            expected_revision=document.revision,
        )
        snapshot = serialize_snapshot(store.read(), service, "/project")
        assert "dialogue_timing_warnings" not in snapshot
        story = build_semantic_projection(
            document,
            {"level": "segment", "scope": {"scene_ids": [scene.id]}, "ids": [segment.id]},
        )
        assert "dialogue_timing" not in story["items"][0]
        assert video_prompt_workset(document, segment.id)["dialogue_timing"] == {
            "ready": False,
            "reason": "audio_not_selected",
        }

    asyncio.run(run())


def test_dialogue_breathing_room_is_soft_hint_against_actual_output_duration(tmp_path):
    """首句前、末句后各 0.5 秒余量只是软提示；段尾按插件实际输出时长计算，Core 照常接受时序。"""

    async def run():
        _store, service, document, _ = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        # 夹具首句 0.25 秒开口；请求 4.0 秒、插件实际输出 4.458 秒，段尾余量足够。
        timing = video_prompt_workset(document, segment.id)["dialogue_timing"]
        assert timing["breathing_seconds"] == 0.5
        assert timing["lead_seconds"] == 0.25
        assert timing["tail_seconds"] == 0.708
        assert len(timing["breathing_hints"]) == 1
        assert "段首" in timing["breathing_hints"][0]

        def shifted(offset):
            return {
                line["dialogue_line_id"]: line["start_seconds"] + offset for line in timing["lines"]
            }

        # 末句恰好在请求时长处结束：Core 不拒绝，实际输出尾部只剩 0.458 秒时给出段尾提示。
        document = await service.set_dialogue_timing(
            segment_id=segment.id,
            starts=shifted(0.25),
            duration_seconds=4.0,
            expected_revision=document.revision,
        )
        tight = video_prompt_workset(document, segment.id)["dialogue_timing"]
        assert tight["ready"] is True
        assert (tight["lead_seconds"], tight["tail_seconds"]) == (0.5, 0.458)
        assert len(tight["breathing_hints"]) == 1
        assert "段尾" in tight["breathing_hints"][0]

        document = await service.set_dialogue_timing(
            segment_id=segment.id,
            starts=shifted(0.25),
            duration_seconds=4.5,
            expected_revision=document.revision,
        )
        assert (
            video_prompt_workset(document, segment.id)["dialogue_timing"]["breathing_hints"] == []
        )

    asyncio.run(run())


def test_video_workset_lists_all_covering_shots_and_continuation_flags(tmp_path):
    """多 Shot Segment：按覆盖顺序列出 Shot，对白可见性取并集，并标出边界延续。"""
    from core.structured_director.models import SegmentBoundary, SegmentBoundaryReason

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        first, second = scene.shots
        segment, next_segment = scene.segments
        # 地点只作为 Scene 语义上下文；Shot 工作集不再带地点图片建议。
        document = install_location(store, scene_ids=(scene.id,))
        scene = document.director_script.scenes[0]
        characters = document.reference_library.characters
        first_visible, second_visible = characters[0].id, characters[1].id
        first = replace(scene.shots[0], visible_character_ids=(first_visible,))
        second = replace(scene.shots[1], visible_character_ids=(second_visible,))
        segments = (
            replace(segment, shot_ids=(first.id, second.id), duration_estimate_seconds=6.0),
            replace(
                next_segment,
                shot_ids=(second.id,),
                boundary_from_previous=SegmentBoundary(
                    SegmentBoundaryReason.CONTINUITY_ANCHOR, "延续第二镜的视线。"
                ),
            ),
        )
        document = await service.save_script(
            (
                replace(scene, shots=(first, second), segments=segments),
                *document.director_script.scenes[1:],
            ),
            expected_revision=document.revision,
        )

        context = video_prompt_workset(document, segment.id)["context"]
        assert [item["action"] for item in context["shots"]] == [first.action, second.action]
        assert [item["visible_character_names"] for item in context["shots"]] == [
            [characters[0].name],
            [characters[1].name],
        ]
        assert all("view_name" not in item for item in context["shots"])
        assert "shot" not in context
        # 对白说话者只要在任一覆盖 Shot 可见即为 on_screen；这里两句都属于并集。
        assert [item["on_screen"] for item in context["segment"]["dialogue"]] == [
            True,
            True,
            True,
        ]
        assert context["segment"]["continues_from_previous_segment"] is False
        assert context["segment"]["continues_into_next_segment"] is True

        next_context = video_prompt_workset(document, next_segment.id)["context"]
        assert [item["action"] for item in next_context["shots"]] == [second.action]
        assert next_context["segment"]["dialogue"] == []
        assert next_context["segment"]["continues_from_previous_segment"] is True
        assert next_context["segment"]["continues_into_next_segment"] is False

    asyncio.run(run())
