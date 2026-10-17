"""脚本回改后的关键帧重建：独立槽位、共享边界只在仍紧邻时保留。"""

from types import SimpleNamespace

from core.structured_director.models import Keyframe, KeyframePlan, SegmentKeyframes
from core.structured_director.script_mutations import _rebase_keyframe_plan

A, B, C, D = ("a" * 32, "b" * 32, "c" * 32, "d" * 32)


def _scenes(*segment_ids):
    shot = SimpleNamespace(id="e" * 32, view_id=None)
    segments = tuple(SimpleNamespace(id=item, shot_ids=(shot.id,)) for item in segment_ids)
    return (SimpleNamespace(shots=(shot,), segments=segments),)


def _frame(frame_id, owner, predecessor=None, prompt="", selected=None):
    return Keyframe(frame_id, owner, predecessor, prompt, (), selected)


def _plan():
    # A 与 B 显式共享边界 "2"，C 使用独立首帧。
    return KeyframePlan(
        1,
        (
            _frame("1" * 32, A),
            _frame("2" * 32, A, "1" * 32, "交接", "9" * 32),
            _frame("3" * 32, B, "2" * 32),
            _frame("4" * 32, C),
            _frame("5" * 32, C, "4" * 32),
        ),
        (
            SegmentKeyframes(A, "1" * 32, "2" * 32, True, True),
            SegmentKeyframes(B, "2" * 32, "3" * 32, True, False),
            SegmentKeyframes(C, "4" * 32, "5" * 32, True, False),
        ),
    )


def _bindings(plan):
    return {item.segment_id: item for item in plan.segments}


def test_new_segment_gets_independent_empty_slots_and_adjacent_share_survives():
    plan = _rebase_keyframe_plan(_plan(), source_script_revision=2, scenes=_scenes(A, B, D, C))
    bindings = _bindings(plan)
    assert bindings[B].start_keyframe_id == bindings[A].end_keyframe_id == "2" * 32
    new = bindings[D]
    assert new.start_keyframe_id != bindings[B].end_keyframe_id
    assert (new.start_enabled, new.end_enabled) == (False, False)
    frames = {item.id: item for item in plan.keyframes}
    assert frames[new.start_keyframe_id].owner_segment_id == D
    assert frames[new.start_keyframe_id].predecessor_keyframe_id is None
    assert frames[new.end_keyframe_id].predecessor_keyframe_id == new.start_keyframe_id
    assert bindings[C].start_keyframe_id == "4" * 32


def test_share_no_longer_adjacent_is_cloned_with_content_and_selection():
    plan = _rebase_keyframe_plan(_plan(), source_script_revision=2, scenes=_scenes(B, C, A))
    bindings = _bindings(plan)
    frames = {item.id: item for item in plan.keyframes}
    clone = frames[bindings[B].start_keyframe_id]
    assert clone.id != "2" * 32
    assert (clone.owner_segment_id, clone.predecessor_keyframe_id) == (B, None)
    assert (clone.prompt_text, clone.selected_asset_id) == ("交接", "9" * 32)
    assert bindings[A].end_keyframe_id == "2" * 32
    assert frames["2" * 32].owner_segment_id == A
    assert frames[bindings[B].end_keyframe_id].predecessor_keyframe_id == clone.id


def test_share_partner_deleted_keeps_original_keyframe_identity():
    plan = _rebase_keyframe_plan(_plan(), source_script_revision=2, scenes=_scenes(B, C))
    bindings = _bindings(plan)
    frames = {item.id: item for item in plan.keyframes}
    assert bindings[B].start_keyframe_id == "2" * 32
    assert (frames["2" * 32].owner_segment_id, frames["2" * 32].predecessor_keyframe_id) == (
        B,
        None,
    )
    assert "1" * 32 not in frames


def test_new_segment_defaults_follow_first_and_last_covered_shot_views():
    from core.structured_director.models import KeyframeEnvironmentMode

    first = SimpleNamespace(id="e" * 32, view_id="6" * 32)
    second = SimpleNamespace(id="f" * 32, view_id="7" * 32)
    segment = SimpleNamespace(id=D, shot_ids=(first.id, second.id))
    scenes = (SimpleNamespace(shots=(first, second), segments=(segment,)),)
    plan = _rebase_keyframe_plan(_plan(), source_script_revision=2, scenes=scenes)
    binding = _bindings(plan)[D]
    frames = {item.id: item for item in plan.keyframes}
    start = frames[binding.start_keyframe_id]
    end = frames[binding.end_keyframe_id]
    assert (
        start.environment_mode,
        start.environment_view_id,
        start.environment_none_reason,
    ) == (KeyframeEnvironmentMode.REFERENCE, first.view_id, None)
    assert (
        end.environment_mode,
        end.environment_view_id,
        end.environment_none_reason,
    ) == (KeyframeEnvironmentMode.REFERENCE, second.view_id, None)
