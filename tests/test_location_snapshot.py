"""地点卡权限、生成步骤与只读 snapshot 的契约测试。"""

from dataclasses import replace

from test_location_generation import KIND, Rig

from core.structured_director.models import ReferenceGenerationPhase as Phase
from core.structured_director.reads.snapshot_view import serialize_snapshot
from core.web_contracts.snapshot_schema import snapshot_schemas


def library(rig, document=None):
    before = rig.store._path.read_bytes()
    result = serialize_snapshot(document or rig.document, rig.service, "/r")["location_library"]
    assert rig.store._path.read_bytes() == before
    return result


def test_interior_two_explicit_steps_and_crop_is_not_candidate(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    room, view = ids["room"], ids["front"]
    row = library(rig)["locations"][0]
    assert "generate" in row["master"]["production"]["allowed_actions"]
    assert row["views"][0]["production"]["status"] == "awaiting_master"
    assert "generate" not in row["views"][0]["production"]["allowed_actions"]
    rig.master_ready(room)
    assert library(rig)["locations"][0]["views"][0]["production"]["generation_step"] == "crop"
    rig.generate_view(view)
    active = library(rig)["locations"][0]["views"][0]["production"]
    assert active["status"] == "in_progress"
    assert active["active_generation_id"] == rig.last(KIND.LOCATION_VIEW_CROP, view).id
    assert "generate" not in active["allowed_actions"]
    rig.finish(active["active_generation_id"])
    row = library(rig)["locations"][0]["views"][0]
    assert row["has_valid_crop"]
    assert row["production"]["generation_step"] == "refine"
    assert row["production"]["candidate_generation_ids"] == []
    assert "select" not in row["production"]["allowed_actions"]
    assert not any(g.kind is KIND.LOCATION_VIEW_IMAGE for g in rig.document.generations)
    rig.generate_view(view)
    rig.finish(rig.last(KIND.LOCATION_VIEW_IMAGE, view).id)
    production = library(rig)["locations"][0]["views"][0]["production"]
    assert production["status"] == "awaiting_selection"
    assert production["selectable_generation_ids"] == [rig.last(KIND.LOCATION_VIEW_IMAGE, view).id]


def test_exterior_one_step_and_regeneration_shows_active_even_when_selected(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build("exterior")
    rig.master_ready(ids["room"])
    production = library(rig)["locations"][0]["views"][0]["production"]
    assert production["generation_step"] == "turn" and "generate" in production["allowed_actions"]
    rig.generate_master(ids["room"])
    production = library(rig)["locations"][0]["master"]["production"]
    assert production["status"] == "in_progress" and production["active_generation_id"]
    assert "generate" not in production["allowed_actions"]


def test_missing_provider_and_reference_or_calibration_dependencies(tmp_path):
    rig = Rig(tmp_path, pano=False)
    ids = rig.build()
    rig.master_ready(ids["room"])
    production = library(rig)["locations"][0]["views"][0]["production"]
    assert "generate" not in production["allowed_actions"]
    assert production["status"] == "blocked" and "裁切服务" in production["reason"]
    other = Rig(tmp_path)
    ids = other.build(
        "interior",
        {
            "key": "relative",
            "name": "朝壁炉",
            "purpose": "中景",
            "look_at_fixture_id": "fireplace",
            "yaw_offset_deg": 0,
        },
    )
    other.master_ready(ids["room"])
    row = library(other)["locations"][0]["views"][0]
    assert row["production"]["status"] == "awaiting_calibration"
    assert "generate" not in row["production"]["allowed_actions"]


def test_permissions_delete_reference_and_project_locks(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    scene = rig.document.director_script.scenes[0]
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [], "scene_ids": [scene.id], "shot_ids": [scene.shots[0].id]},
            "operations": [
                {
                    "op": "bind_scene",
                    "scene_id": scene.id,
                    "location_id": ids["room"],
                    "state_id": ids["night"],
                },
                {"op": "bind_shot", "shot_id": scene.shots[0].id, "view_id": ids["front"]},
            ],
        },
    )
    row = library(rig)["locations"][0]
    assert "delete" not in row["allowed_actions"]
    # 只被 Shot 软引用的视图允许删除；状态仍被 Scene 引用，仍不开放。
    assert "delete" in row["views"][0]["production"]["allowed_actions"]
    assert "delete" not in row["states"][0]["allowed_actions"]
    rig.store.begin_location_plan(expected_revision=rig.document.revision, user_message="规划地点")
    locked = library(rig)
    assert locked["allowed_actions"] == []
    assert locked["locations"][0]["allowed_actions"] == []
    assert locked["locations"][0]["master"]["production"]["allowed_actions"] == []


def test_wire_schema_requires_projection_fields():
    schemas = snapshot_schemas()
    assert "production" in schemas["LocationMaster"]["required"]
    assert {"production", "has_valid_crop"} <= set(schemas["LocationView"]["required"])
    assert "allowed_actions" in schemas["LocationLibrary"]["required"]


def test_invalid_panorama_visible_but_not_selectable(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    rig.image.size = (1024, 576)
    rig.generate_master(ids["room"])
    generation = rig.last(KIND.LOCATION_MASTER_IMAGE, ids["room"])
    rig.finish(generation.id)
    production = library(rig)["locations"][0]["master"]["production"]
    assert production["candidate_generation_ids"] == [generation.id]
    assert production["selectable_generation_ids"] == []
    assert "select" not in production["allowed_actions"]


def test_reference_view_wait_and_uncertain_submission_block_generate(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build(
        "exterior",
        {"key": "front", "name": "正打", "purpose": "正打", "azimuth_deg": 0},
        {
            "key": "reverse",
            "name": "反打",
            "purpose": "反打",
            "azimuth_deg": 180,
            "reference_view_ids": ["front"],
        },
    )
    rig.master_ready(ids["room"])
    reverse = library(rig)["locations"][0]["views"][1]["production"]
    assert reverse["status"] == "awaiting_reference_view"
    assert "generate" not in reverse["allowed_actions"]
    rig.generate_view(ids["front"])
    current = rig.document
    active = rig.last(KIND.LOCATION_VIEW_IMAGE, ids["front"])
    uncertain = replace(
        current,
        generations=tuple(
            replace(
                g,
                phase=Phase.SUBMISSION_UNCERTAIN,
                plugin_id=None,
                plugin_version=None,
                external_id=None,
            )
            if g.id == active.id
            else g
            for g in current.generations
        ),
    )
    front = library(rig, uncertain)["locations"][0]["views"][0]["production"]
    assert front["status"] == "submission_uncertain"
    assert front["active_generation_id"] == active.id
    assert "generate" not in front["allowed_actions"]


def test_pano_cache_survives_store_instances_but_formal_selection_still_reads(
    tmp_path, monkeypatch
):
    from unittest.mock import patch

    import pytest

    import core.structured_director.store as store_module
    from core.structured_director.store import StructuredDirectorStore

    rig = Rig(tmp_path)
    ids = rig.build()
    asset_id = rig.master_ready(ids["room"])
    asset = next(a for a in rig.document.assets if a.id == asset_id)
    monkeypatch.setattr(store_module, "_LOCATION_PANO_SOURCES", {})
    with patch.object(rig.store, "read_asset", wraps=rig.store.read_asset) as reader:
        assert rig.service.location_master_candidate_valid(asset)
        assert rig.service.location_master_candidate_valid(asset)
        assert reader.call_count == 1
    reopened = StructuredDirectorStore(rig.store._project_directory, rig.document.project_id)
    with patch.object(reopened, "read_asset", side_effect=AssertionError("cache missed")):
        assert reopened.is_location_pano_source(asset)
    # 同一候选再次选择也走正式 Store 字节验证；快照缓存不成为写入授权。
    with patch.object(
        StructuredDirectorStore, "read_asset", side_effect=ValueError("Asset 内容校验失败。")
    ) as reader:
        with pytest.raises(ValueError, match="Asset 内容校验失败"):
            rig.select_master(ids["room"], asset_id)
        assert reader.call_count == 1


def test_invalid_pano_result_cached_and_io_failure_is_retryable(tmp_path, monkeypatch):
    from unittest.mock import patch

    import core.structured_director.store as store_module

    rig = Rig(tmp_path)
    ids = rig.build()
    rig.image.size = (1024, 576)
    rig.generate_master(ids["room"])
    rig.finish(rig.last(KIND.LOCATION_MASTER_IMAGE, ids["room"]).id)
    asset = rig.document.assets[-1]
    monkeypatch.setattr(store_module, "_LOCATION_PANO_SOURCES", {})
    with patch.object(rig.store, "read_asset", side_effect=OSError("暂时不可读")):
        assert not rig.service.location_master_candidate_valid(asset)
    assert asset.sha256 not in store_module._LOCATION_PANO_SOURCES
    with patch.object(rig.store, "read_asset", wraps=rig.store.read_asset) as reader:
        assert not rig.service.location_master_candidate_valid(asset)
        assert not rig.service.location_master_candidate_valid(asset)
        assert reader.call_count == 1
