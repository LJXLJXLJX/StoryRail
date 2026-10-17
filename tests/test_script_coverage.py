"""Scene 的 Segment 覆盖校验（Shot 与 Segment 并列后 Core 唯一的结构校验）。"""

from __future__ import annotations

import pytest

from core.structured_director.models import (
    DialogueLine,
    NarrationCue,
    NarrationTrack,
    Scene,
    SegmentBoundary,
    SegmentBoundaryReason,
    Shot,
    ShotSegment,
)

BOUNDARY = SegmentBoundary(SegmentBoundaryReason.CONTINUITY_ANCHOR, "延续上一段的姿态。")
CUE = NarrationCue("c" * 32, NarrationTrack("旁白。", 1), None)


def _id(index: int) -> str:
    return f"{index:032x}"


def _shots(count: int) -> tuple[Shot, ...]:
    return tuple(
        Shot(_id(100 + index), (), "构图", "固定", "动作", "", None) for index in range(count)
    )


def _segment(index: int, *shot_numbers: int, continues=False, dialogue=()) -> ShotSegment:
    return ShotSegment(
        _id(200 + index),
        tuple(_id(100 + number) for number in shot_numbers),
        4.0,
        "动作",
        dialogue,
        BOUNDARY if continues else None,
    )


def _scene(shot_count: int, *segments: ShotSegment, driver="drama", cues=()) -> Scene:
    return Scene(_id(1), "站台", "摘要", "环境", _shots(shot_count), segments, cues, driver, None)


def test_one_segment_may_cover_several_shots_and_long_shots_span_segments() -> None:
    # g0 段内切镜 s0–s1；s2 长镜头跨 g1、g2、g3，g3 再段内切到 s3。
    scene = _scene(
        4,
        _segment(0, 0, 1),
        _segment(1, 2),
        _segment(2, 2, continues=True),
        _segment(3, 2, 3, continues=True),
    )
    assert [segment.shot_ids for segment in scene.segments][0] == (_id(100), _id(101))


def test_rule1_shot_ids_must_be_non_empty_unique_and_contiguous() -> None:
    with pytest.raises(ValueError, match="至少一个 Shot"):
        _segment(0)
    with pytest.raises(ValueError, match="不能重复"):
        _segment(0, 0, 0)
    with pytest.raises(ValueError, match="必须按 Shot 顺序连续覆盖"):
        _scene(3, _segment(0, 0, 2), _segment(1, 1))
    with pytest.raises(ValueError, match="必须按 Shot 顺序连续覆盖"):
        _scene(2, _segment(0, 1, 0))
    with pytest.raises(ValueError, match="不属于本 Scene"):
        _scene(1, _segment(0, 0, 5))


@pytest.mark.parametrize(
    "segments",
    [
        (_segment(0, 1), _segment(1, 0)),  # 倒序
        (_segment(0, 0), _segment(1, 2)),  # 跳过 s1
        (_segment(0, 0, 1), _segment(1, 0, 1, continues=True)),  # 重复覆盖非边界 Shot
        (_segment(0, 1), _segment(1, 2)),  # 首段不从 s0 开始
    ],
)
def test_rule2_segments_cover_every_shot_in_order_once(segments) -> None:
    with pytest.raises(
        ValueError,
        match="必须从本 Scene 的第一个 Shot 开始|跳过了第|重复覆盖了前面的 Shot",
    ):
        _scene(3, *segments)


def test_rule2_trailing_shots_must_be_covered() -> None:
    with pytest.raises(ValueError, match="没有覆盖到最后一个 Shot"):
        _scene(3, _segment(0, 0), _segment(1, 1))


def test_rule3_sharing_the_boundary_shot_iff_boundary_from_previous() -> None:
    assert _scene(1, _segment(0, 0), _segment(1, 0, continues=True))
    assert _scene(2, _segment(0, 0), _segment(1, 1))
    with pytest.raises(ValueError, match="必须填写 boundary_from_previous"):
        _scene(1, _segment(0, 0), _segment(1, 0))
    with pytest.raises(ValueError, match="boundary_from_previous 必须为 null"):
        _scene(2, _segment(0, 0), _segment(1, 1, continues=True))
    with pytest.raises(ValueError, match="boundary_from_previous 必须为 null"):
        _scene(1, _segment(0, 0, continues=True))


def test_rule4_middle_segment_of_a_three_segment_shot_covers_only_that_shot() -> None:
    assert _scene(
        3, _segment(0, 0, 1), _segment(1, 1, continues=True), _segment(2, 1, 2, continues=True)
    )
    # 中间段多覆盖了 s2，第三段就无法再从共享的 s1 继续。
    with pytest.raises(ValueError, match="重复覆盖了前面的 Shot"):
        _scene(
            3,
            _segment(0, 0, 1),
            _segment(1, 1, 2, continues=True),
            _segment(2, 1, continues=True),
        )


def test_rule5_shots_and_segments_are_both_present_or_both_empty() -> None:
    with pytest.raises(ValueError, match="Drama Scene 至少需要一个 Shot"):
        _scene(0)
    with pytest.raises(ValueError, match="同时为空或同时非空"):
        _scene(1)
    assert _scene(0, driver="narration", cues=(CUE,)).segments == ()
    assert _scene(1, _segment(0, 0), driver="narration", cues=(CUE,))
    with pytest.raises(ValueError, match="同时为空或同时非空"):
        _scene(1, driver="narration", cues=(CUE,))


def test_rule6_narration_has_no_dialogue_and_drama_has_no_narration() -> None:
    line = DialogueLine(None, "还会来吗？", "轻声", speaker_label="路人")
    with pytest.raises(ValueError, match="Narration Scene 不能包含对白"):
        _scene(1, _segment(0, 0, dialogue=(line,)), driver="narration", cues=(CUE,))
    with pytest.raises(ValueError, match="Drama Scene 不能包含旁白"):
        _scene(1, _segment(0, 0), cues=(CUE,))
