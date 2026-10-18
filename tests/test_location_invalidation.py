"""地点语义与独立图片编辑的失效边界。"""

import pytest
from test_location_generation import KIND, Rig

from core.structured_director.models import ReferenceGenerationPhase


@pytest.fixture(name="rig")
def _rig_fixture(tmp_path) -> Rig:
    return Rig(tmp_path)


def apply(rig: Rig, location_id: str, operation: dict):
    return rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [location_id], "scene_ids": []},
            "operations": [operation],
        },
    ).document


def test_description_edit_preserves_selected_asset_and_production(rig: Rig):
    ids = rig.build()
    selected = rig.generate_finish_select(ids["front"])
    before = rig.document
    after = apply(
        rig,
        ids["room"],
        {
            "op": "update_image",
            "image_id": ids["front"],
            "fields": {"description": "用户核对后补写的实际画面说明。"},
        },
    )
    assert after.location_library.image_owner(ids["front"])[1].selected_asset_id == selected
    assert after.generations == before.generations
    assert after.keyframe_plan == before.keyframe_plan
    assert after.video_plan == before.video_plan


def test_prompt_or_reference_edit_does_not_invalidate_existing_candidate(rig: Rig):
    ids = rig.build(
        {
            "key": "a",
            "name": "A",
            "kind": "image",
            "description": "A 图。",
            "prompt_text": "A。",
        },
        {
            "key": "b",
            "name": "B",
            "kind": "image",
            "description": "B 图。",
            "prompt_text": "B。",
        },
    )
    reference = rig.generate_finish_select(ids["a"])
    candidate = rig.generate_finish_select(ids["b"])
    apply(
        rig,
        ids["room"],
        {
            "op": "update_image",
            "image_id": ids["b"],
            "fields": {
                "prompt_text": "更新后的 B。",
                "reference_asset_ids": [reference],
            },
        },
    )
    assert rig.image_row(ids["b"]).selected_asset_id == candidate
    generation = rig.last(KIND.LOCATION_IMAGE, ids["b"])
    assert generation.phase is ReferenceGenerationPhase.SUCCEEDED
    assert not generation.dismissed


def test_panorama_child_is_provenance_not_live_dependency(rig: Rig):
    ids = rig.build(
        {
            "key": "pano",
            "name": "全景",
            "kind": "panorama",
            "description": "完整空间。",
            "prompt_text": "完整空间全景。",
        },
        {
            "key": "child",
            "name": "沙发方向",
            "kind": "image",
            "description": "沙发方向取景。",
            "prompt_text": "",
            "source": {
                "panorama_image_id": "pano",
                "yaw_deg": 20,
                "pitch_deg": 0,
                "hfov_deg": 60,
            },
        },
    )
    rig.image.size = (2048, 1024)
    rig.generate_finish_select(ids["pano"])
    rig.capture(ids["child"])
    capture = rig.last(KIND.PANORAMA_CAPTURE, ids["child"])
    rig.finish(capture.id)
    child_asset = rig.image_row(ids["child"]).selected_asset_id
    assert child_asset is not None
    apply(rig, ids["room"], {"op": "delete_image", "image_id": ids["pano"]})
    child = rig.image_row(ids["child"])
    assert child.selected_asset_id == child_asset
    assert child.source.panorama_image_id == ids["pano"]


def test_image_delete_preserves_asset_and_generation_history(rig: Rig):
    ids = rig.build()
    selected = rig.generate_finish_select(ids["front"])
    generations = rig.document.generations
    assets = rig.document.assets
    apply(rig, ids["room"], {"op": "delete_image", "image_id": ids["front"]})
    assert rig.document.location_library.image_owner(ids["front"]) is None
    assert rig.document.generations == generations
    assert rig.document.assets == assets
    assert selected in {asset.id for asset in rig.document.assets}


def test_active_task_freezes_submission_but_only_blocks_delete(rig: Rig):
    ids = rig.build()
    rig.generate_image(ids["front"])
    generation = rig.last(KIND.LOCATION_IMAGE, ids["front"])
    frozen_prompt = generation.prompt_text
    apply(
        rig,
        ids["room"],
        {
            "op": "update_image",
            "image_id": ids["front"],
            "fields": {"prompt_text": "下一次生成使用的新提示词。"},
        },
    )
    assert rig.last(KIND.LOCATION_IMAGE, ids["front"]).prompt_text == frozen_prompt
    assert rig.image_row(ids["front"]).prompt_text == "下一次生成使用的新提示词。"
    with pytest.raises(ValueError, match="进行中"):
        apply(rig, ids["room"], {"op": "delete_image", "image_id": ids["front"]})


def test_location_rename_and_scene_binding_do_not_modify_shots(rig: Rig):
    ids = rig.build()
    scene = rig.document.director_script.scenes[0]
    original_shots = scene.shots
    apply(
        rig,
        ids["room"],
        {"op": "update_location", "location_id": ids["room"], "fields": {"name": "新客厅"}},
    )
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [], "scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "bind_scene",
                    "scene_id": scene.id,
                    "location_id": ids["room"],
                    "state_id": None,
                }
            ],
        },
    )
    current = rig.document.director_script.scenes[0]
    assert current.shots == original_shots
    assert all(not hasattr(shot, "view_id") for shot in current.shots)


def test_location_change_does_not_rewrite_keyframes(rig: Rig):
    ids = rig.build()
    before = rig.document.keyframe_plan
    apply(
        rig,
        ids["room"],
        {"op": "update_location", "location_id": ids["room"], "fields": {"description": "新说明"}},
    )
    assert rig.document.keyframe_plan == before
    if before is not None:
        assert all(not hasattr(frame, "environment_view_id") for frame in before.keyframes)
