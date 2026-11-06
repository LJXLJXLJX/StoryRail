"""Director command 数据表与 repair 显式翻译回归。"""

from core.director_commands.models import RepairOperation, RepairPatch
from core.director_commands.registry import (
    _COMMAND_SPECS,
    translate_repair_to_script_operations,
)


def test_repair_shot_and_segment_translate_to_formal_script_operations():
    scene_id = "1" * 32
    shot_id = "2" * 32
    segment_id = "3" * 32
    patch = RepairPatch(
        "run-1",
        "missing.command",
        "修正镜头与片段",
        (scene_id,),
        (
            RepairOperation("shot", shot_id, {"action": "新镜头动作"}),
            RepairOperation("segment", segment_id, {"action": "新片段动作"}),
        ),
    )
    assert translate_repair_to_script_operations(patch) == {
        "scope": {"scene_ids": [scene_id]},
        "operations": [
            {
                "op": "update_shot_fields",
                "shot_id": shot_id,
                "fields": {"action": "新镜头动作"},
            },
            {
                "op": "update_segment_fields",
                "segment_id": segment_id,
                "fields": {"action": "新片段动作"},
            },
        ],
    }


def test_scene_repair_stays_on_repair_path():
    patch = RepairPatch(
        "run-1",
        "missing.command",
        "修正场景",
        ("1" * 32,),
        (RepairOperation("scene", "1" * 32, {"summary": "新摘要"}),),
    )
    assert translate_repair_to_script_operations(patch) is None


def test_external_and_domain_commands_share_one_registry_table():
    for name in (
        "reference.request_proposal",
        "script.submit_proposal",
        "keyframe.cancel_proposal",
        "reference.confirm_review",
        "script.confirm",
        "project.apply_repair_patch",
        "keyframe.apply_operations",
        "location.apply_operations",
        "location.select_image",
    ):
        assert name in _COMMAND_SPECS
        assert _COMMAND_SPECS[name].scope_rule


def test_location_candidate_selection_is_human_only():
    from core.application.caller import _AGENT_OPERATIONS

    assert "location.apply_operations" in _AGENT_OPERATIONS
    assert "location.select_image" not in _AGENT_OPERATIONS
