import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest
from test_director_commands import _visual_project

from core.director_commands import parse_keyframe_operations
from core.structured_director.keyframe_mutations import _apply_keyframe_operations
from core.structured_director.store import RevisionConflictError


def visual_project(tmp_path):
    store, service, document, router = asyncio.run(_visual_project(str(tmp_path)))
    document = asyncio.run(
        service.save_segment_keyframe_activation(
            segment_id=document.keyframe_plan.segments[0].segment_id,
            start_enabled=True,
            end_enabled=False,
            expected_revision=document.revision,
        )
    )
    return store, service, document, router


def test_manual_keyframe_edit_matches_registry_result_and_preserves_lineage(tmp_path):
    store, service, before, _ = visual_project(tmp_path)
    frame = before.keyframe_plan.keyframes[0]
    changed = replace(frame, prompt_text="单帧：站台人物抬头看向远处。")
    expected = _apply_keyframe_operations(
        before,
        parse_keyframe_operations(
            [
                {
                    "op": "update_frame_fields",
                    "keyframe_id": frame.id,
                    "fields": {
                        "prompt_text": changed.prompt_text,
                        "visible_character_ids": list(changed.visible_character_ids),
                        "environment_mode": changed.environment_mode.value,
                        "environment_view_id": changed.environment_view_id,
                        "environment_none_reason": changed.environment_none_reason,
                    },
                }
            ]
        ),
    ).document
    # Preview is read-only even when the subsequent manual mutation changes state.
    assert store.read() == before
    assert expected is not None
    after = asyncio.run(service.save_keyframe(changed, expected_revision=before.revision))
    assert after == expected
    assert after.revision == before.revision + 1
    assert after.generations == before.generations
    assert after.assets == before.assets
    assert after.keyframe_plan.segments == before.keyframe_plan.segments
    assert next(x for x in after.keyframe_plan.keyframes if x.id == frame.id) == changed


def test_manual_keyframe_edit_rejects_binding_tampering_without_write(tmp_path):
    store, service, before, _ = visual_project(tmp_path)
    frame = before.keyframe_plan.keyframes[0]
    with pytest.raises(ValueError, match="绑定"):
        asyncio.run(
            service.save_keyframe(
                replace(frame, owner_segment_id="f" * 32),
                expected_revision=before.revision,
            )
        )
    assert store.read() == before


def test_manual_keyframe_save_is_one_registry_transaction_and_identical_save_is_noop(tmp_path):
    store, service, before, _ = visual_project(tmp_path)
    binding = before.keyframe_plan.segments[0]
    frame = before.keyframe_plan.keyframes[0]
    changed = replace(frame, prompt_text="站台的静态构图。")
    with patch.object(
        service._command_registry, "execute", wraps=service._command_registry.execute
    ) as execute:
        after = asyncio.run(
            service.save_keyframe(
                changed,
                expected_revision=before.revision,
                segment_id=binding.segment_id,
                reference_asset_ids=(),
            )
        )
        assert execute.call_count == 1
        command = execute.call_args.args[0]
        assert command.name == "keyframe.apply_operations"
        assert len(command.arguments["operations"]) == 2
    assert after.revision == before.revision + 1
    replay = asyncio.run(service.save_keyframe(changed, expected_revision=after.revision))
    assert replay == after
    with pytest.raises(RevisionConflictError):
        asyncio.run(service.save_keyframe(changed, expected_revision=before.revision))
    assert store.read() == after
