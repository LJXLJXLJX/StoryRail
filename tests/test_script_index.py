from __future__ import annotations

from core.structured_director.models import (
    DirectorScript,
    Scene,
    SegmentBoundary,
    SegmentBoundaryReason,
    Shot,
    ShotSegment,
)
from core.structured_director.script_index import (
    find_segment,
    scene_segments,
    script_segments,
    segment_continues_previous,
    segment_shots,
    segment_view_ids,
    segment_visible_character_ids,
    shot_segments,
)


def _id(label: str) -> str:
    return label.encode().hex().ljust(32, "0")[:32]


def _segment(label: str, *, continues: bool = False) -> ShotSegment:
    return ShotSegment(
        _id(label),
        4.0,
        f"{label} 动作",
        (),
        SegmentBoundary(SegmentBoundaryReason.MODEL_CONSTRAINT, "延续上一段姿态")
        if continues
        else None,
    )


def _shot(label: str, segments: tuple[ShotSegment, ...], characters=(), view=None) -> Shot:
    return Shot(
        _id(label),
        tuple(_id(item) for item in characters),
        f"{label} 构图",
        "固定机位",
        f"{label} 动作",
        "",
        None,
        segments,
        view_id=None if view is None else _id(view),
    )


def _scene(label: str, shots: tuple[Shot, ...]) -> Scene:
    return Scene(_id(label), label, "摘要", "场景", shots, location_id=_id("loc"))


# s1 一个 Segment；s2 长镜头拆成三段；s3 一个 Segment。
G1, G2A, G2B, G2C, G3 = (
    _segment("g1"),
    _segment("g2a"),
    _segment("g2b", continues=True),
    _segment("g2c", continues=True),
    _segment("g3"),
)
S1 = _shot("s1", (G1,), characters=("alice",), view="v1")
S2 = _shot("s2", (G2A, G2B, G2C), characters=("bob", "alice"), view="v2")
S3 = _shot("s3", (G3,))
SCENE_A = _scene("a", (S1, S2))
SCENE_B = _scene("b", (S3,))
SCRIPT = DirectorScript(1, 1, None, None, (SCENE_A, SCENE_B))


def test_segments_follow_script_order_across_shots_and_scenes() -> None:
    assert scene_segments(SCENE_A) == (G1, G2A, G2B, G2C)
    assert script_segments(SCRIPT) == (G1, G2A, G2B, G2C, G3)
    assert script_segments(SCRIPT.scenes) == script_segments(SCRIPT)


def test_shot_and_segment_coverage_lookup() -> None:
    assert shot_segments(SCENE_A, S2.id) == (G2A, G2B, G2C)
    assert shot_segments(SCENE_A, S3.id) == ()
    assert segment_shots(SCENE_A, G2B.id) == (S2,)
    assert segment_shots(SCENE_A, G3.id) == ()


def test_segment_visible_characters_and_views_come_from_covering_shots() -> None:
    assert segment_visible_character_ids(SCENE_A, G2A.id) == (_id("bob"), _id("alice"))
    assert segment_visible_character_ids(SCENE_B, G3.id) == ()
    assert segment_view_ids(SCENE_A, G1.id) == (_id("v1"), _id("v1"))
    assert segment_view_ids(SCENE_B, G3.id) == (None, None)
    assert segment_view_ids(SCENE_B, G1.id) == (None, None)


def test_find_segment_locates_owning_scene() -> None:
    assert find_segment(SCRIPT, G3.id) == (SCENE_B, G3)
    assert find_segment(SCRIPT.scenes, G2C.id) == (SCENE_A, G2C)
    assert find_segment(SCRIPT, _id("missing")) is None


def test_continuation_only_within_the_same_shot() -> None:
    assert not segment_continues_previous(SCENE_A, G1.id)
    assert not segment_continues_previous(SCENE_A, G2A.id)
    assert segment_continues_previous(SCENE_A, G2B.id)
    assert segment_continues_previous(SCENE_A, G2C.id)
    assert not segment_continues_previous(SCENE_B, G3.id)
    assert not segment_continues_previous(SCENE_A, G3.id)
