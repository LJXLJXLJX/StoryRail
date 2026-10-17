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
    segment_continues_next,
    segment_continues_previous,
    segment_shots,
    segment_view_ids,
    segment_visible_character_ids,
    shot_segments,
)


def _id(label: str) -> str:
    return label.encode().hex().ljust(32, "0")[:32]


def _segment(label: str, *shots: str, continues: bool = False) -> ShotSegment:
    return ShotSegment(
        _id(label),
        tuple(_id(item) for item in shots),
        4.0,
        f"{label} 动作",
        (),
        SegmentBoundary(SegmentBoundaryReason.MODEL_CONSTRAINT, "延续上一段姿态")
        if continues
        else None,
    )


def _shot(label: str, characters=(), view=None) -> Shot:
    return Shot(
        _id(label),
        tuple(_id(item) for item in characters),
        f"{label} 构图",
        "固定机位",
        f"{label} 动作",
        "",
        None,
        view_id=None if view is None else _id(view),
    )


def _scene(label: str, shots: tuple[Shot, ...], segments: tuple[ShotSegment, ...]) -> Scene:
    return Scene(_id(label), label, "摘要", "场景", shots, segments, location_id=_id("loc"))


# g1 段内切镜覆盖 s1–s2；s3 长镜头拆成 g2、g3、g4；g4 延续 s3 后段内切到 s4；s5 独立。
S1 = _shot("s1", characters=("alice",), view="v1")
S2 = _shot("s2", characters=("bob", "alice"), view="v2")
S3 = _shot("s3", characters=("carol",))
S4 = _shot("s4", view="v4")
S5 = _shot("s5")
G1 = _segment("g1", "s1", "s2")
G2 = _segment("g2", "s3")
G3 = _segment("g3", "s3", continues=True)
G4 = _segment("g4", "s3", "s4", continues=True)
G5 = _segment("g5", "s5")
SCENE_A = _scene("a", (S1, S2, S3, S4), (G1, G2, G3, G4))
SCENE_B = _scene("b", (S5,), (G5,))
SCRIPT = DirectorScript(1, 1, None, None, (SCENE_A, SCENE_B))


def test_segments_follow_script_order_across_scenes() -> None:
    assert scene_segments(SCENE_A) == (G1, G2, G3, G4)
    assert script_segments(SCRIPT) == (G1, G2, G3, G4, G5)
    assert script_segments(SCRIPT.scenes) == script_segments(SCRIPT)


def test_shot_and_segment_coverage_lookup() -> None:
    assert shot_segments(SCENE_A, S2.id) == (G1,)
    assert shot_segments(SCENE_A, S3.id) == (G2, G3, G4)
    assert shot_segments(SCENE_A, S5.id) == ()
    assert segment_shots(SCENE_A, G1.id) == (S1, S2)
    assert segment_shots(SCENE_A, G4.id) == (S3, S4)
    assert segment_shots(SCENE_A, G5.id) == ()


def test_segment_visible_characters_and_views_come_from_covering_shots() -> None:
    assert segment_visible_character_ids(SCENE_A, G1.id) == (_id("alice"), _id("bob"))
    assert segment_visible_character_ids(SCENE_B, G5.id) == ()
    assert segment_view_ids(SCENE_A, G1.id) == (_id("v1"), _id("v2"))
    assert segment_view_ids(SCENE_A, G4.id) == (None, _id("v4"))
    assert segment_view_ids(SCENE_B, G1.id) == (None, None)


def test_find_segment_locates_owning_scene() -> None:
    assert find_segment(SCRIPT, G5.id) == (SCENE_B, G5)
    assert find_segment(SCRIPT.scenes, G3.id) == (SCENE_A, G3)
    assert find_segment(SCRIPT, _id("missing")) is None


def test_continuation_means_sharing_the_boundary_shot() -> None:
    assert not segment_continues_previous(SCENE_A, G1.id)
    assert not segment_continues_previous(SCENE_A, G2.id)
    assert segment_continues_previous(SCENE_A, G3.id)
    assert segment_continues_previous(SCENE_A, G4.id)
    assert not segment_continues_previous(SCENE_B, G5.id)
    assert not segment_continues_previous(SCENE_A, G5.id)


def test_next_continuation_means_sharing_the_boundary_shot() -> None:
    assert not segment_continues_next(SCENE_A, G1.id)
    assert segment_continues_next(SCENE_A, G2.id)
    assert segment_continues_next(SCENE_A, G3.id)
    assert not segment_continues_next(SCENE_A, G4.id)
    assert not segment_continues_next(SCENE_B, G5.id)
    assert not segment_continues_next(SCENE_A, G5.id)
