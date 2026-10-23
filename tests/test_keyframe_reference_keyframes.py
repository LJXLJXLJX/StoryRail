"""Keyframe 参考其它已选 Keyframe：写入校验、实际输入映射、未选阻塞、改选软提示与悬空剪除。"""

import asyncio
import json
from dataclasses import replace

import pytest
from test_external_production import call, service, setup

from core.director_commands import DirectorCommand
from core.director_proposals.keyframe import KeyframePlanProposal, KeyframeSegmentProposal
from core.director_proposals.keyframe_codec import compile_plan_operations
from core.model_providers.boundary import GenerationPhase
from core.structured_director.candidate_eligibility import keyframe_references_unchanged
from core.structured_director.codec.document import _parse_document, serialize_document
from core.structured_director.keyframe_requests import _active_keyframe_ids
from core.structured_director.models import prune_reference_keyframes


async def _generate(store, provider, keyframe_id, key, content):
    provider.content = b"\x89PNG\r\n\x1a\n" + content
    started, _ = await call(store, provider, "keyframe.generate", key, {"keyframe_id": keyframe_id})
    generation_id = started.body["data"]["generation_ids"][0]
    provider.observations = [GenerationPhase.SUCCEEDED]
    await call(
        store, provider, "generation.wait", "wait-" + key, {"generation_ids": [generation_id]}
    )
    return next(item for item in store.read().generations if item.id == generation_id)


def _frame(document, keyframe_id):
    return next(item for item in document.keyframe_plan.keyframes if item.id == keyframe_id)


def _edit(keyframe_id, references):
    return {
        "operations": [
            {
                "op": "update_frame_fields",
                "keyframe_id": keyframe_id,
                "fields": {"reference_keyframe_ids": references},
            }
        ]
    }


async def _try(store, provider, name, key, arguments):
    from test_external_script_proposals import agent, http

    document = store.read()
    command = DirectorCommand(name, document.revision, key, arguments)
    return await http(service(store, provider), agent(document, command), command)


async def _project(tmp_path):
    store, provider, doc = await setup(tmp_path)
    active = _active_keyframe_ids(doc.keyframe_plan)
    source_id = doc.keyframe_plan.segments[0].start_keyframe_id
    target_id, waiting_id, *_ = (
        item.id
        for item in doc.keyframe_plan.keyframes
        if item.id in active
        and item.id != source_id
        and item.predecessor_keyframe_id is None
        and item.prompt_text.strip()
    )
    return store, provider, source_id, target_id, waiting_id


def test_frame_references_only_selected_keyframes_and_submits_their_current_image(tmp_path):
    async def run():
        store, provider, source_id, target_id, waiting_id = await _project(tmp_path)
        before = store.path.read_bytes()
        unselected = await _try(
            store,
            provider,
            "keyframe.apply_operations",
            "ref-unselected",
            _edit(target_id, [source_id]),
        )
        assert unselected.status != 200
        selfref = await _try(
            store, provider, "keyframe.apply_operations", "ref-self", _edit(target_id, [target_id])
        )
        assert selfref.status != 200
        assert store.path.read_bytes() == before

        first = await _generate(store, provider, source_id, "source-a", b"a")
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-a",
            {"keyframe_id": source_id, "generation_id": first.id},
        )
        await call(
            store, provider, "keyframe.apply_operations", "ref-ok", _edit(target_id, [source_id])
        )
        assert _frame(store.read(), target_id).reference_keyframe_ids == (source_id,)
        on_disk = json.loads(store.path.read_text())
        assert any(
            item["reference_keyframe_ids"] == [source_id]
            for item in on_disk["structured_director"]["keyframe_plan"]["keyframes"]
        )

        candidate = await _generate(store, provider, target_id, "target-1", b"t1")
        assert first.output_asset_id in candidate.input_asset_ids
        assert keyframe_references_unchanged(store.read(), candidate)

        # 改选参考帧：旧候选只获得软提示，仍属于可审核候选。
        second = await _generate(store, provider, source_id, "source-b", b"b")
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-b",
            {"keyframe_id": source_id, "generation_id": second.id},
        )
        assert not keyframe_references_unchanged(store.read(), candidate)
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-target",
            {"keyframe_id": target_id, "generation_id": candidate.id},
        )
        regenerated = await _generate(store, provider, target_id, "target-2", b"t2")
        assert second.output_asset_id in regenerated.input_asset_ids
        assert first.output_asset_id not in regenerated.input_asset_ids
        await call(
            store, provider, "keyframe.apply_operations", "ref-wait", _edit(waiting_id, [source_id])
        )

        # 参考帧撤销选择后，本帧单独生成被拒绝，批次则等待而不是失败。
        await call(
            store,
            provider,
            "keyframe.apply_operations",
            "clear-source",
            {"operations": [{"op": "clear_selection", "keyframe_id": source_id}]},
        )
        blocked = await _try(
            store, provider, "keyframe.generate", "target-blocked", {"keyframe_id": target_id}
        )
        assert blocked.status != 200
        assert "参考关键帧" in json.dumps(blocked.body, ensure_ascii=False)
        count = len(store.read().generations)
        batch = await _try(
            store, provider, "keyframe.generate_batch", "target-batch", {"target_ids": [waiting_id]}
        )
        assert batch.status == 200, batch.body
        assert len(store.read().generations) == count
        assert "选定图片" in json.dumps(batch.body, ensure_ascii=False)

    asyncio.run(run())


def test_dangling_references_are_pruned_on_write_and_rejected_on_read(tmp_path):
    async def run():
        store, provider, source_id, target_id, waiting_id = await _project(tmp_path)
        document = store.read()
        plan = document.keyframe_plan
        dangling = replace(
            plan,
            keyframes=tuple(
                replace(item, reference_keyframe_ids=("f" * 32,)) if item.id == target_id else item
                for item in plan.keyframes
            ),
        )
        assert _frame(replace(document, keyframe_plan=dangling), target_id).reference_keyframe_ids
        pruned = prune_reference_keyframes(dangling)
        assert (
            _frame(replace(document, keyframe_plan=pruned), target_id).reference_keyframe_ids == ()
        )
        assert prune_reference_keyframes(plan) is plan

        raw = serialize_document(replace(document, keyframe_plan=dangling))
        with pytest.raises(ValueError, match="不存在的关键帧"):
            _parse_document(raw)

        store._atomic_write(
            replace(document, keyframe_plan=dangling, revision=document.revision + 1)
        )
        assert _frame(store.read(), target_id).reference_keyframe_ids == ()

    asyncio.run(run())


def test_planner_proposal_compiles_frame_references():
    from core.director_proposals.keyframe_codec import KeyframePlanSlot

    segment_id, start_id, end_id, source_id = "1" * 32, "2" * 32, "3" * 32, "4" * 32
    proposal = KeyframePlanProposal(
        (
            KeyframeSegmentProposal(
                segment_id=segment_id,
                continues_from_previous=False,
                frame_strategy="both",
                start_prompt_text="开始",
                start_visible_character_ids=(),
                end_prompt_text="结束",
                end_visible_character_ids=(),
                end_reference_keyframe_ids=(source_id,),
            ),
        )
    )
    operations = compile_plan_operations(
        proposal, ((KeyframePlanSlot(segment_id, start_id, end_id, True, False, False),),)
    )
    by_frame = {
        item.keyframe_id: item for item in operations if hasattr(item, "reference_keyframe_ids")
    }
    assert by_frame[start_id].reference_keyframe_ids == ()
    assert by_frame[end_id].reference_keyframe_ids == (source_id,)
    with pytest.raises(ValueError, match="start_reference_keyframe_ids"):
        KeyframeSegmentProposal(
            segment_id=segment_id,
            continues_from_previous=True,
            frame_strategy="both",
            start_prompt_text="",
            start_visible_character_ids=(),
            end_prompt_text="结束",
            end_visible_character_ids=(),
            start_reference_keyframe_ids=(source_id,),
        )
