"""对白必须先 TTS：音色路由、真实时序和视频门禁。"""

import asyncio
from dataclasses import replace

import pytest
from provider_factory import make_service
from structured_director_fixtures import RecordingProvider, wav_bytes
from test_director_commands import _visual_project

from core.structured_director import StructuredDirectorStore
from core.structured_director.models import GenerationOperation


def test_character_dialogue_uses_voice_design_without_reference_and_clone_with_reference(
    tmp_path,
):
    async def run():
        (tmp_path / "design").mkdir()
        design_store, _old, design_doc, _ = await _visual_project(str(tmp_path / "design"))
        design_provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
        clone_provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
        design_service = make_service(
            StructuredDirectorStore(design_store.path.parent, design_doc.project_id),
            voice_provider=design_provider,
            speech_provider=clone_provider,
        )
        design_line = design_doc.director_script.scenes[0].segments[0].dialogue_lines[0]
        designed = await design_service.generate_dialogue(
            dialogue_line_id=design_line.id,
            expected_revision=design_doc.revision,
        )
        design_generation = designed.generations[-1]
        design_card = designed.reference_library.characters[0]
        assert design_generation.operation is GenerationOperation.VOICE_DESIGN
        assert design_generation.input_asset_ids == ()
        assert design_generation.sample_text == design_card.voice_description
        assert len(design_provider.requests) == 1
        assert clone_provider.requests == []

        (tmp_path / "clone").mkdir()
        clone_store, _old, clone_doc, _ = await _visual_project(str(tmp_path / "clone"))
        design_provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
        clone_provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
        clone_service = make_service(
            StructuredDirectorStore(clone_store.path.parent, clone_doc.project_id),
            voice_provider=design_provider,
            speech_provider=clone_provider,
        )
        clone_line = clone_doc.director_script.scenes[0].segments[0].dialogue_lines[0]
        card = next(
            item
            for item in clone_doc.reference_library.characters
            if item.id == clone_line.character_id
        )
        clone_doc = await clone_service.upload_reference_voice(
            card_id=card.id,
            media_type="audio/wav",
            content=wav_bytes(duration_seconds=2),
            expected_revision=clone_doc.revision,
        )
        card = next(item for item in clone_doc.reference_library.characters if item.id == card.id)
        transcript = "这是用于克隆的完整参考音频文字稿。"
        clone_doc = await clone_service.update_character(
            replace(card, voice_reference_transcript=transcript),
            expected_revision=clone_doc.revision,
        )
        cloned = await clone_service.generate_dialogue(
            dialogue_line_id=clone_line.id,
            expected_revision=clone_doc.revision,
        )
        clone_generation = cloned.generations[-1]
        assert clone_generation.operation is GenerationOperation.SYNTHESIZE
        assert clone_generation.input_asset_ids == (card.voice_reference_asset_id,)
        assert clone_generation.sample_text == transcript
        assert len(clone_provider.requests) == 1
        assert design_provider.requests == []

    asyncio.run(run())


def test_dialogue_timing_rejects_overlap_and_video_shorter_than_audio(tmp_path):
    from test_prompt_worksets import fixture

    async def run():
        _store, service, document, _ = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        line_ids = [line.id for line in segment.dialogue_lines]
        with pytest.raises(ValueError, match="不能重叠"):
            await service.set_dialogue_timing(
                segment_id=segment.id,
                starts={line_id: 0.0 for line_id in line_ids},
                duration_seconds=10.0,
                expected_revision=document.revision,
            )
        with pytest.raises(ValueError, match="不能短于最后一句对白结束时间"):
            await service.set_dialogue_timing(
                segment_id=segment.id,
                starts={line_id: index * 1.25 for index, line_id in enumerate(line_ids)},
                duration_seconds=3.0,
                expected_revision=document.revision,
            )

    asyncio.run(run())
