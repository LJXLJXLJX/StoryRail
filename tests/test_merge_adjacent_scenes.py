"""merge_adjacent_scenes：合并相邻 Scene 只改变归属，Segment 的关键帧、视频与候选原样保留。"""

from __future__ import annotations

import pytest
from conftest import Journey, JourneyStepError

from core.director_commands.script_operations import parse_script_operations_patch
from core.structured_director.script_mutations import _apply_script_operations


@pytest.fixture
def produced_journey(journey: Journey):
    journey.create_project(title="合并 Scene")
    journey.propose_references()
    character_id = journey.snapshot()["reference_library"]["characters"][0]["id"]
    journey.approve_references()
    journey.apply_script(
        scenes=[
            journey.drama_scene(character_id),
            journey.drama_scene(character_id, title="第二场", setting="夜里，车厢内，暖黄灯光。"),
        ]
    )
    journey.unlock_visual_production()
    journey.generate_keyframes()
    journey.generate_videos()
    return journey


def _merge(journey: Journey, scope, left, right):
    return journey._command(
        "script.apply_operations",
        {
            "scope": {"scene_ids": scope},
            "operations": [
                {"op": "merge_adjacent_scenes", "left_scene_id": left, "right_scene_id": right}
            ],
        },
        role="agent",
    )


def test_merge_keeps_segment_ids_keyframes_and_selected_videos(produced_journey: Journey):
    journey = produced_journey
    before = journey.snapshot()
    first, second = before["director_script"]["scenes"]
    segment_ids = [segment["id"] for scene in (first, second) for segment in scene["segments"]]
    videos = {item["segment_id"]: item for item in before["video_plan"]["segments"]}
    keyframes = {
        item["id"]: item["selected_asset_id"] for item in before["keyframe_plan"]["keyframes"]
    }
    assert all(videos[segment_id]["selected_asset_id"] for segment_id in segment_ids)

    _merge(journey, [first["id"], second["id"]], first["id"], second["id"])

    after = journey.snapshot()
    (merged,) = after["director_script"]["scenes"]
    assert merged["id"] == first["id"]
    assert merged["title"] == first["title"] and merged["setting"] == first["setting"]
    assert [segment["id"] for segment in merged["segments"]] == segment_ids
    assert [shot["id"] for shot in merged["shots"]] == [
        shot["id"] for scene in (first, second) for shot in scene["shots"]
    ]
    merged_videos = {item["segment_id"]: item for item in after["video_plan"]["segments"]}
    for segment_id in segment_ids:
        assert (
            merged_videos[segment_id]["selected_asset_id"]
            == videos[segment_id]["selected_asset_id"]
        )
        assert merged_videos[segment_id]["prompt_text"] == videos[segment_id]["prompt_text"]
    assert {
        item["id"]: item["selected_asset_id"] for item in after["keyframe_plan"]["keyframes"]
    } == keyframes
    assert after["final_assembly"] is None


def test_merge_rejects_non_adjacent_order_and_out_of_scope(produced_journey: Journey):
    journey = produced_journey
    first, second = journey.snapshot()["director_script"]["scenes"]
    before = journey.document()
    for scope, left, right, message in (
        ([first["id"], second["id"]], second["id"], first["id"], "不相邻"),
        ([first["id"]], first["id"], second["id"], "超出已授权 Scene scope"),
    ):
        with pytest.raises(JourneyStepError) as raised:
            _merge(journey, scope, left, right)
        assert message in raised.value.body["error"]["message"]
        assert journey.document() == before


def test_merge_rejects_mixed_driver_and_narration_pairs(produced_journey: Journey):
    journey = produced_journey
    from core.structured_director.codec.document import _parse_document

    document = _parse_document(journey.document())
    first, second = document.director_script.scenes
    patch = parse_script_operations_patch(
        {
            "scope": {"scene_ids": [first.id, second.id]},
            "operations": [
                {
                    "op": "merge_adjacent_scenes",
                    "left_scene_id": first.id,
                    "right_scene_id": second.id,
                }
            ],
        }
    )
    # 绕过 Scene 构造校验，只为让草稿里出现指定 driver 的相邻 Scene。
    object.__setattr__(second, "driver", "narration")
    with pytest.raises(ValueError, match="driver 相同"):
        _apply_script_operations((first, second), patch, command_id="mixed")
    # Narration Scene 恰好一条旁白 Cue，两场旁白也不能合并。
    object.__setattr__(first, "driver", "narration")
    with pytest.raises(ValueError, match="两个 Narration Scene 不能合并"):
        _apply_script_operations((first, second), patch, command_id="narration")
