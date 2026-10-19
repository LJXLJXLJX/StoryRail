"""对白必须先 TTS：音色路由、真实时序和视频门禁。"""

import asyncio
import threading
from dataclasses import replace

import pytest
from provider_factory import make_service
from structured_director_fixtures import RecordingProvider, wav_bytes
from test_director_commands import _visual_project

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.model_providers.boundary import GenerationPhase
from core.model_providers.recipe import RecipeParams
from core.structured_director import StructuredDirectorStore
from core.structured_director.models import GenerationOperation
from core.structured_director.reads.snapshot_view import serialize_snapshot


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
        assert clone_provider.requests[0].param("performance_instruction") == clone_line.delivery
        assert clone_generation.recipe_params.get("breeze_tts2.clone") == {
            "performance_instruction": clone_line.delivery
        }
        cloned = await clone_service._generation_observer.refresh_generation(clone_generation.id)
        clone_doc = await clone_service._generation_observer.refresh_generation(clone_generation.id)

        performance_instruction = "压低声音，带一点迟疑，语速稍慢，问句后停顿。"
        clone_doc = await clone_service.update_dialogue_recipe_params(
            dialogue_line_id=clone_line.id,
            recipe_params=RecipeParams.from_json(
                {"breeze_tts2.clone": {"performance_instruction": performance_instruction}}
            ),
            expected_revision=clone_doc.revision,
        )
        clone_doc = await clone_service.select_dialogue_audio(
            dialogue_line_id=clone_line.id,
            generation_id=clone_generation.id,
            expected_revision=clone_doc.revision,
        )
        stale_projection = serialize_snapshot(clone_doc, clone_service, "/project")
        stale_generation = next(
            item for item in stale_projection["generations"] if item["id"] == clone_generation.id
        )
        assert stale_generation["inputs_outdated"] is True
        assert stale_generation["allowed_actions"] == []
        overridden = await clone_service.generate_dialogue(
            dialogue_line_id=clone_line.id,
            expected_revision=clone_doc.revision,
        )
        assert (
            clone_provider.requests[-1].param("performance_instruction") == performance_instruction
        )
        assert overridden.generations[-1].recipe_params.get("breeze_tts2.clone") == {
            "performance_instruction": performance_instruction
        }
        overridden_generation_id = overridden.generations[-1].id
        clone_provider.content = wav_bytes(duration_seconds=3)
        clone_provider.observations = [GenerationPhase.RUNNING, GenerationPhase.SUCCEEDED]
        await clone_service._generation_observer.refresh_generation(overridden_generation_id)
        clone_doc = await clone_service._generation_observer.refresh_generation(
            overridden_generation_id
        )
        clone_doc = await clone_service.select_dialogue_audio(
            dialogue_line_id=clone_line.id,
            generation_id=overridden_generation_id,
            expected_revision=clone_doc.revision,
        )
        projected = serialize_snapshot(clone_doc, clone_service, "/project")
        actions = {item["id"]: item["allowed_actions"] for item in projected["generations"]}
        assert actions[overridden_generation_id] == []
        assert actions[clone_generation.id] == ["select_dialogue_audio", "dismiss_history"]
        with pytest.raises(ValueError, match="已经成为参考素材"):
            await clone_service.dismiss_generation(
                overridden_generation_id,
                expected_revision=clone_doc.revision,
            )
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


def test_splitting_one_dialogue_preserves_other_selected_tts(tmp_path):
    from test_prompt_worksets import fixture

    async def run():
        store, _service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        segment = scene.segments[0]
        original = segment.dialogue_lines
        assert len(original) == 3
        assert document.dialogue_plan is not None
        selected_before = {
            item.dialogue_line_id: item.selected_audio_asset_id
            for item in document.dialogue_plan.items
        }
        assert all(selected_before[line.id] is not None for line in original)

        def payload(line, *, text=None):
            return {
                "character_id": line.character_id,
                "speaker_label": line.speaker_label,
                "voice_description": line.voice_description,
                "text": line.text if text is None else text,
                "delivery": line.delivery,
            }

        updated = (
            DirectorCommandRegistry(store)
            .execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "split-one-dialogue-line",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_segment_fields",
                                "segment_id": segment.id,
                                "fields": {
                                    "dialogue_lines": [
                                        payload(original[0], text="先听。"),
                                        payload(original[0], text="我说。"),
                                        payload(original[1]),
                                        payload(original[2]),
                                    ]
                                },
                            }
                        ],
                    },
                )
            )
            .document
        )

        changed = updated.director_script.scenes[0].segments[0].dialogue_lines
        assert len(changed) == 4
        assert changed[2:] == original[1:]
        assert changed[0].id not in selected_before
        assert changed[1].id not in selected_before
        assert updated.dialogue_plan is not None
        selected_after = {
            item.dialogue_line_id: item.selected_audio_asset_id
            for item in updated.dialogue_plan.items
        }
        assert selected_after[changed[0].id] is None
        assert selected_after[changed[1].id] is None
        assert selected_after[original[1].id] == selected_before[original[1].id]
        assert selected_after[original[2].id] == selected_before[original[2].id]

    asyncio.run(run())


def test_splitting_segment_preserves_unchanged_dialogue_tts_across_both_halves(tmp_path):
    from test_prompt_worksets import fixture

    async def run():
        store, _service, document, _ = await fixture(tmp_path)
        scene = document.director_script.scenes[0]
        segment = scene.segments[0]
        original = segment.dialogue_lines
        assert document.dialogue_plan is not None
        selected_before = {
            item.dialogue_line_id: item.selected_audio_asset_id
            for item in document.dialogue_plan.items
        }

        def payload(line, *, text=None):
            return {
                "character_id": line.character_id,
                "speaker_label": line.speaker_label,
                "voice_description": line.voice_description,
                "text": line.text if text is None else text,
                "delivery": line.delivery,
            }

        def half(action, dialogue_lines, boundary):
            return {
                "shot_ids": list(segment.shot_ids),
                "duration_estimate_seconds": segment.duration_estimate_seconds / 2,
                "action": action,
                "dialogue_lines": dialogue_lines,
                "boundary_from_previous": boundary,
            }

        updated = (
            DirectorCommandRegistry(store)
            .execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "split-segment-and-one-dialogue-line",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "split_segment",
                                "segment_id": segment.id,
                                "preserve_id": "first",
                                "first": half(
                                    "先说前半句。",
                                    [
                                        payload(original[0], text="先听。"),
                                        payload(original[1]),
                                    ],
                                    None,
                                ),
                                "second": half(
                                    "再说后半句。",
                                    [
                                        payload(original[0], text="我说。"),
                                        payload(original[2]),
                                    ],
                                    {
                                        "reason": "continuity_anchor",
                                        "continuity_instruction": "承接同一镜头与表演状态。",
                                    },
                                ),
                            }
                        ],
                    },
                )
            )
            .document
        )

        first, second = updated.director_script.scenes[0].segments[:2]
        assert first.dialogue_lines[1] == original[1]
        assert second.dialogue_lines[1] == original[2]
        assert updated.dialogue_plan is not None
        selected_after = {
            item.dialogue_line_id: item.selected_audio_asset_id
            for item in updated.dialogue_plan.items
        }
        assert selected_after[first.dialogue_lines[0].id] is None
        assert selected_after[second.dialogue_lines[0].id] is None
        assert selected_after[original[1].id] == selected_before[original[1].id]
        assert selected_after[original[2].id] == selected_before[original[2].id]

    asyncio.run(run())


def test_cancelled_http_request_still_finishes_durable_dialogue_submission(tmp_path):
    async def scenario(directory, *, should_fail: bool):
        directory.mkdir()
        store_path, _old, document, _ = await _visual_project(str(directory))
        started = threading.Event()
        release = threading.Event()
        provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
        original_submit = provider.submit_recipe

        def blocked_submit(request):
            started.set()
            assert release.wait(timeout=2)
            if should_fail:
                raise RuntimeError("模拟 Provider 拒绝提交")
            return original_submit(request)

        provider.submit_recipe = blocked_submit
        store = StructuredDirectorStore(store_path.path.parent, document.project_id)
        service = make_service(store, voice_provider=provider)
        line = document.director_script.scenes[0].segments[0].dialogue_lines[0]
        task = asyncio.create_task(
            service.generate_dialogue(
                dialogue_line_id=line.id,
                expected_revision=document.revision,
            )
        )
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        generation = store.read().generations[-1]
        assert generation.phase.value == ("submission_uncertain" if should_fail else "queued")
        assert generation.external_id == (None if should_fail else "external-1")

    async def run():
        await scenario(tmp_path / "accepted", should_fail=False)
        await scenario(tmp_path / "failed", should_fail=True)

    asyncio.run(run())
