"""地点语义卡、独立图片生产状态与 snapshot schema。"""

from test_location_generation import KIND, Rig

from core.structured_director.reads.snapshot_view import serialize_snapshot
from core.web_contracts.snapshot_schema import snapshot_schemas


def library(rig: Rig):
    before = rig.store.path.read_bytes()
    result = serialize_snapshot(rig.document, rig.service, "/r")["location_library"]
    assert rig.store.path.read_bytes() == before
    return result


def test_location_projection_contains_only_semantics_and_images(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    row = library(rig)["locations"][0]
    assert row["id"] == ids["room"]
    assert row["images"][0]["id"] == ids["front"]
    assert row["images"][0]["description"]
    assert "master" not in row
    assert "views" not in row


def test_plain_image_moves_from_ready_to_selection_without_auto_select(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    production = library(rig)["locations"][0]["images"][0]["production"]
    assert production["status"] == "ready"
    assert production["generation_step"] == "image"
    assert "generate" in production["allowed_actions"]
    assert "select_asset" in production["allowed_actions"]
    rig.generate_image(ids["front"])
    active = library(rig)["locations"][0]["images"][0]["production"]
    assert active["status"] == "in_progress"
    assert active["active_generation_id"] == rig.last(KIND.LOCATION_IMAGE, ids["front"]).id
    rig.finish(active["active_generation_id"])
    ready = library(rig)["locations"][0]["images"][0]
    assert ready["selected_asset_id"] is None
    assert ready["production"]["status"] == "awaiting_selection"
    assert ready["production"]["selectable_generation_ids"]
    assert "select" in ready["production"]["allowed_actions"]


def test_selected_panorama_exposes_3d_preview_action(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build(
        {
            "key": "pano",
            "name": "全景",
            "kind": "panorama",
            "description": "空间全景。",
            "prompt_text": "空间全景。",
        }
    )
    rig.image.size = (2048, 1024)
    rig.generate_finish_select(ids["pano"])
    image = library(rig)["locations"][0]["images"][0]
    assert image["kind"] == "panorama"
    assert "preview_panorama" in image["production"]["allowed_actions"]
    assert "clear_selection" in image["production"]["allowed_actions"]


def test_capture_row_is_blocked_until_panorama_selected(tmp_path):
    rig = Rig(tmp_path)
    rig.build(
        {
            "key": "pano",
            "name": "全景",
            "kind": "panorama",
            "description": "空间全景。",
            "prompt_text": "空间全景。",
        },
        {
            "key": "child",
            "name": "取景",
            "kind": "image",
            "description": "沙发方向。",
            "prompt_text": "",
            "source": {
                "panorama_image_id": "pano",
                "yaw_deg": 0,
                "pitch_deg": 0,
                "hfov_deg": 60,
            },
        },
    )
    child = library(rig)["locations"][0]["images"][1]["production"]
    assert child["generation_step"] == "capture"
    assert child["status"] == "blocked"
    assert "尚未选择" in child["reason"]
    assert "generate" not in child["allowed_actions"]
    assert "select_asset" not in child["allowed_actions"]


def test_bound_scene_blocks_location_and_state_delete_but_not_image_delete(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    scene = rig.document.director_script.scenes[0]
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [], "scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "bind_scene",
                    "scene_id": scene.id,
                    "location_id": ids["room"],
                    "state_id": ids["night"],
                }
            ],
        },
    )
    row = library(rig)["locations"][0]
    assert "delete" not in row["allowed_actions"]
    assert "delete" not in row["states"][0]["allowed_actions"]
    assert "delete" in row["images"][0]["production"]["allowed_actions"]


def test_wire_schema_requires_image_description_and_production():
    schemas = snapshot_schemas()
    required = set(schemas["LocationImage"]["required"])
    assert {"id", "name", "kind", "description", "production"} <= required
    assert "images" in schemas["Location"]["required"]
    assert "allowed_actions" in schemas["LocationLibrary"]["required"]
    assert "LocationMaster" not in schemas
    assert "LocationView" not in schemas
