"""Keyframe“建议抽帧”标记与人类取消已选候选（关键帧、对白 TTS、造型图）。"""

import asyncio
import json

import pytest
from test_external_production import call, service
from test_keyframe_reference_keyframes import _frame, _generate, _project, _try

from core.director_proposals.keyframe import KeyframePlanProposal, KeyframeSegmentProposal
from core.director_proposals.keyframe_codec import KeyframePlanSlot, compile_plan_operations


def _flag(keyframe_id, suggested):
    return {
        "operations": [
            {
                "op": "update_frame_fields",
                "keyframe_id": keyframe_id,
                "fields": {"extraction_suggested": suggested},
            }
        ]
    }


def test_extraction_flag_is_shared_soft_hint_skipped_only_by_batches(tmp_path):
    """Agent 与人类写同一字段；标记不清除选择，批量跳过该帧，单帧生成照常提交。"""

    async def run():
        store, provider, source_id, target_id, _waiting_id = await _project(tmp_path)
        first = await _generate(store, provider, source_id, "src", b"s")
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-src",
            {"keyframe_id": source_id, "generation_id": first.id},
        )
        await call(store, provider, "keyframe.apply_operations", "flag-src", _flag(source_id, True))
        flagged = _frame(store.read(), source_id)
        assert flagged.extraction_suggested is True
        assert flagged.selected_asset_id == first.output_asset_id

        document = await service(store, provider).set_keyframe_extraction_suggested(
            keyframe_id=target_id, suggested=True, expected_revision=store.read().revision
        )
        assert _frame(document, target_id).extraction_suggested is True
        on_disk = json.loads(store.path.read_text())
        assert any(
            item["id"] == target_id and item["extraction_suggested"] is True
            for item in on_disk["structured_director"]["keyframe_plan"]["keyframes"]
        )

        count = len(store.read().generations)
        batch = await _try(
            store, provider, "keyframe.generate_batch", "flag-batch", {"target_ids": [target_id]}
        )
        assert batch.status == 200, batch.body
        assert len(store.read().generations) == count
        text = json.dumps(batch.body, ensure_ascii=False)
        assert "建议抽帧" in text
        assert '"extraction_suggested"' in text  # 批次观测把它视为已结束的跳过项

        await _generate(store, provider, target_id, "flag-single", b"t")
        assert len(store.read().generations) == count + 1

        await call(store, provider, "keyframe.apply_operations", "unflag", _flag(target_id, False))
        assert _frame(store.read(), target_id).extraction_suggested is False

    asyncio.run(run())


def test_planner_proposal_sets_start_extraction_flag_only_for_independent_start():
    segment_id, start_id, end_id = "1" * 32, "2" * 32, "3" * 32
    proposal = KeyframePlanProposal(
        (
            KeyframeSegmentProposal(
                segment_id=segment_id,
                continues_from_previous=False,
                frame_strategy="both",
                start_prompt_text="接上一段末帧",
                start_visible_character_ids=(),
                end_prompt_text="结束",
                end_visible_character_ids=(),
                start_extraction_suggested=True,
            ),
        )
    )
    operations = compile_plan_operations(
        proposal, ((KeyframePlanSlot(segment_id, start_id, end_id, True, False, False),),)
    )
    by_frame = {
        item.keyframe_id: item for item in operations if hasattr(item, "extraction_suggested")
    }
    assert by_frame[start_id].extraction_suggested is True
    # 尾帧不由规划设置，重规划时保留人类标记。
    assert by_frame[end_id].extraction_suggested is None
    for continues, strategy in ((True, "both"), (False, "end")):
        with pytest.raises(ValueError, match="建议抽帧"):
            KeyframeSegmentProposal(
                segment_id=segment_id,
                continues_from_previous=continues,
                frame_strategy=strategy,
                start_prompt_text="",
                start_visible_character_ids=(),
                end_prompt_text="结束",
                end_visible_character_ids=(),
                start_extraction_suggested=True,
            )


def test_human_clears_keyframe_selection_and_keeps_candidates(tmp_path):
    async def run():
        store, provider, source_id, _target_id, _waiting_id = await _project(tmp_path)
        first = await _generate(store, provider, source_id, "clear-src", b"c")
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-clear",
            {"keyframe_id": source_id, "generation_id": first.id},
        )
        document = await service(store, provider).clear_keyframe_selection(
            keyframe_id=source_id, expected_revision=store.read().revision
        )
        assert _frame(document, source_id).selected_asset_id is None
        assert any(item.id == first.id for item in document.generations)
        assert any(item.id == first.output_asset_id for item in document.assets)

    asyncio.run(run())


def test_human_clears_dialogue_audio_like_reselection(tmp_path):
    """取消一句对白 WAV：该句选择清空，本 Segment 全部时序清空并失效视频；无选择时不写入。"""
    from test_prompt_worksets import fixture

    async def run():
        store, service_, document, _ = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        first, *others = segment.dialogue_lines
        cleared = await service_.clear_dialogue_audio_selection(
            dialogue_line_id=first.id, expected_revision=document.revision
        )
        items = {item.dialogue_line_id: item for item in cleared.dialogue_plan.items}
        assert items[first.id].selected_audio_asset_id is None
        assert all(items[line.id].selected_audio_asset_id is not None for line in others)
        assert all(items[line.id].start_seconds is None for line in segment.dialogue_lines)
        video = next(item for item in cleared.video_plan.segments if item.segment_id == segment.id)
        assert video.selected_asset_id is None and cleared.final_assembly is None
        assert len(cleared.generations) == len(document.generations)
        again = await service_.clear_dialogue_audio_selection(
            dialogue_line_id=first.id, expected_revision=cleared.revision
        )
        assert again.revision == cleared.revision

    asyncio.run(run())


def test_human_clears_look_image_without_rewriting_keyframes(tmp_path):
    from test_keyframe_character_references import _project_with_costumes

    async def run():
        _store, service_, document, _keyframe_id = await _project_with_costumes(tmp_path)
        card, look = next(
            (card, look)
            for card in document.reference_library.characters
            for look in card.looks
            if look.selected_asset_id is not None
        )
        keyframes = document.keyframe_plan
        cleared = await service_.clear_look_asset(
            card_id=card.id, look_id=look.id, expected_revision=document.revision
        )
        current = next(item for item in cleared.reference_library.characters if item.id == card.id)
        assert current.look(look.id).selected_asset_id is None
        assert cleared.keyframe_plan == keyframes
        assert any(item.id == look.selected_asset_id for item in cleared.assets)
        again = await service_.clear_look_asset(
            card_id=card.id, look_id=look.id, expected_revision=cleared.revision
        )
        assert again.revision == cleared.revision

    asyncio.run(run())
