"""Keyframe“建议复用”：同 Shot 延续帧或回切帧建议原样复用另一帧的已选图，批量生成不另行生图。"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_external_production import call, service
from test_keyframe_reference_keyframes import _frame, _generate, _project, _try

from core.director_proposals.keyframe import KeyframePlanProposal, KeyframeSegmentProposal
from core.director_proposals.keyframe_codec import KeyframePlanSlot, compile_plan_operations
from core.structured_director.codec.document import _parse_document, serialize_document
from core.structured_director.models import (
    Keyframe,
    KeyframePlan,
    SegmentKeyframes,
    prune_reference_keyframes,
    require_known_reference_keyframes,
)

ROOT = Path(__file__).resolve().parents[1]


def _reuse(keyframe_id, source_id):
    return {
        "operations": [
            {
                "op": "update_frame_fields",
                "keyframe_id": keyframe_id,
                "fields": {"reuse_keyframe_id": source_id},
            }
        ]
    }


def _target_status(body, target_id):
    text = json.dumps(body, ensure_ascii=False)
    observation = json.loads(text)
    stack = [observation]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("target_id") == target_id and "status" in item:
                return item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    raise AssertionError(f"批次观测中没有 {target_id}")


def test_reuse_hint_waits_for_source_and_never_generates_in_batches(tmp_path):
    """来源未选图也可建议复用；批量等待来源、选定后提示选入，不新增 Generation；单帧生成照常。"""

    async def run():
        store, provider, source_id, target_id, _waiting_id = await _project(tmp_path)
        assert _frame(store.read(), source_id).selected_asset_id is None
        await call(
            store, provider, "keyframe.apply_operations", "reuse-set", _reuse(target_id, source_id)
        )
        assert _frame(store.read(), target_id).reuse_keyframe_id == source_id
        on_disk = json.loads(store.path.read_text())
        assert any(
            item["id"] == target_id and item["reuse_keyframe_id"] == source_id
            for item in on_disk["structured_director"]["keyframe_plan"]["keyframes"]
        )

        self_reuse = await _try(
            store, provider, "keyframe.apply_operations", "reuse-self", _reuse(target_id, target_id)
        )
        assert self_reuse.status != 200
        both = await _try(
            store,
            provider,
            "keyframe.apply_operations",
            "reuse-and-extract",
            {
                "operations": [
                    {
                        "op": "update_frame_fields",
                        "keyframe_id": target_id,
                        "fields": {"extraction_suggested": True},
                    }
                ]
            },
        )
        assert both.status != 200
        assert "建议复用" in json.dumps(both.body, ensure_ascii=False)

        count = len(store.read().generations)
        waiting = await _try(
            store, provider, "keyframe.generate_batch", "reuse-wait", {"target_ids": [target_id]}
        )
        assert waiting.status == 200, waiting.body
        assert len(store.read().generations) == count
        status = _target_status(waiting.body, target_id)
        assert status["status"] == "dependency_blocked"
        assert status["dependency_kind"] == "reuse_keyframe"
        assert status["dependency_target_id"] == source_id

        first = await _generate(store, provider, source_id, "reuse-src", b"s")
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "reuse-select-src",
            {"keyframe_id": source_id, "generation_id": first.id},
        )
        count = len(store.read().generations)
        ready = await _try(
            store, provider, "keyframe.generate_batch", "reuse-ready", {"target_ids": [target_id]}
        )
        assert ready.status == 200, ready.body
        assert len(store.read().generations) == count
        assert _target_status(ready.body, target_id)["status"] == "reuse_ready"
        assert "建议复用" in json.dumps(ready.body, ensure_ascii=False)

        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "reuse-select-target",
            {"keyframe_id": target_id, "source_keyframe_id": source_id},
        )
        reused = _frame(store.read(), target_id)
        assert reused.selected_asset_id == first.output_asset_id
        assert reused.reuse_keyframe_id == source_id  # 提示不随选择变化

        await _generate(store, provider, target_id, "reuse-single", b"t")
        assert len(store.read().generations) == count + 1

        document = await service(store, provider).set_keyframe_reuse_suggestion(
            keyframe_id=target_id, reuse_keyframe_id=None, expected_revision=store.read().revision
        )
        assert _frame(document, target_id).reuse_keyframe_id is None

    asyncio.run(run())


def test_planner_proposal_sets_and_clears_reuse_per_enabled_frame():
    segment_id, start_id, end_id, source_id = "1" * 32, "2" * 32, "3" * 32, "4" * 32
    proposal = KeyframePlanProposal(
        (
            KeyframeSegmentProposal(
                segment_id=segment_id,
                continues_from_previous=False,
                frame_strategy="both",
                start_prompt_text="同机位延续",
                start_visible_character_ids=(),
                end_prompt_text="结束",
                end_visible_character_ids=(),
                start_reuse_keyframe_id=source_id,
            ),
        )
    )
    operations = compile_plan_operations(
        proposal, ((KeyframePlanSlot(segment_id, start_id, end_id, True, False, True),),)
    )
    by_frame = {item.keyframe_id: item for item in operations if hasattr(item, "reuse_keyframe_id")}
    assert by_frame[start_id].reuse_keyframe_id == source_id
    assert by_frame[end_id].reuse_keyframe_id == ""  # 规划写出的帧以 proposal 为准，未给出即取消

    base = {
        "segment_id": segment_id,
        "start_prompt_text": "",
        "start_visible_character_ids": (),
        "end_prompt_text": "结束",
        "end_visible_character_ids": (),
    }
    with pytest.raises(ValueError, match="建议复用"):
        KeyframeSegmentProposal(
            **base,
            continues_from_previous=True,
            frame_strategy="both",
            start_reuse_keyframe_id=source_id,
        )
    with pytest.raises(ValueError, match="建议复用"):
        KeyframeSegmentProposal(
            **base,
            continues_from_previous=False,
            frame_strategy="start",
            end_reuse_keyframe_id=source_id,
        )
    with pytest.raises(ValueError, match="二选一|只保留一种"):
        KeyframeSegmentProposal(
            **{**base, "start_prompt_text": "x"},
            continues_from_previous=False,
            frame_strategy="start",
            start_reuse_keyframe_id=source_id,
            start_extraction_suggested=True,
        )


def test_reuse_hint_is_pruned_when_source_keyframe_disappears():
    start, end, gone = "a" * 32, "b" * 32, "c" * 32
    plan = KeyframePlan(
        source_script_revision=1,
        keyframes=(
            Keyframe(start, "d" * 32, None, "", (), reuse_keyframe_id=gone),
            Keyframe(end, "d" * 32, start, "", (), reuse_keyframe_id=start),
        ),
        segments=(SegmentKeyframes("d" * 32, start, end, True, True),),
    )
    with pytest.raises(ValueError, match="复用的关键帧不存在"):
        require_known_reference_keyframes(plan)
    pruned = prune_reference_keyframes(plan)
    assert [item.reuse_keyframe_id for item in pruned.keyframes] == [None, start]
    with pytest.raises(ValueError, match="复用自身"):
        Keyframe(start, "d" * 32, None, "", (), reuse_keyframe_id=start)


def test_migration_script_upgrades_v37_keyframes(tmp_path):
    from test_director_commands import _visual_project

    async def run():
        store, _service, document, _ = await _visual_project(str(tmp_path))
        return document

    document = asyncio.run(run())
    raw = serialize_document(document)
    raw["schema_version"] = 37
    for keyframe in raw["structured_director"]["keyframe_plan"]["keyframes"]:
        del keyframe["reuse_keyframe_id"]
    project = tmp_path / "stories" / "demo"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/migrate_project_v37_to_v38.py"), str(project)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "v37 → v38" in result.stdout
    migrated = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 38
    parsed = _parse_document(migrated)
    assert all(item.reuse_keyframe_id is None for item in parsed.keyframe_plan.keyframes)
    assert list((tmp_path / "stories" / ".migration-backups").iterdir())
