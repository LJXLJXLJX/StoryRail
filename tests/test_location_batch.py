"""独立地点图片的固定范围批次分类与显式继续。"""

import asyncio
from uuid import uuid4

from test_external_script_proposals import agent, http
from test_location_generation import KIND, Rig

from core.director_commands import DirectorCommand
from core.structured_director.location_requests import location_set_items


def rows(rig: Rig, location_ids):
    return location_set_items(rig.document, tuple(location_ids))


def test_batch_has_one_item_per_explicit_image_not_implicit_master(tmp_path):
    rig = Rig(tmp_path)
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
    items = rows(rig, (ids["room"],))
    assert [item.image_id for item in items] == [ids["a"], ids["b"]]
    assert all(item.step == "image" for item in items)
    assert all(item.status == "ready" for item in items)


def test_batch_does_not_create_or_derive_images(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    before = tuple(rig.document.location_library.location(ids["room"]).images)
    location_set_items(rig.document, (ids["room"],))
    after = tuple(rig.document.location_library.location(ids["room"]).images)
    assert after == before
    assert len(after) == 1


def test_selected_image_is_terminal_for_batch(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    rig.generate_finish_select(ids["front"])
    item = rows(rig, (ids["room"],))[0]
    assert item.status == "already_selected"
    assert item.reason is None


def test_capture_waits_for_selected_panorama_then_becomes_ready(tmp_path):
    rig = Rig(tmp_path)
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
            "name": "子图",
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
    by_id = {item.image_id: item for item in rows(rig, (ids["room"],))}
    assert by_id[ids["pano"]].status == "ready"
    assert by_id[ids["child"]].status == "blocked"
    rig.image.size = (2048, 1024)
    rig.generate_finish_select(ids["pano"])
    child = {item.image_id: item for item in rows(rig, (ids["room"],))}[ids["child"]]
    assert child.status == "ready"
    assert child.step == "capture"


def test_missing_location_is_reported_without_expanding_scope(tmp_path):
    rig = Rig(tmp_path)
    rig.build()
    missing = "f" * 32
    items = rows(rig, (missing,))
    assert len(items) == 1
    assert items[0].location_id == missing
    assert items[0].image_id is None
    assert items[0].status == "target_missing"


def test_generate_set_submits_only_current_ready_wave(tmp_path):
    rig = Rig(tmp_path)
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
            "name": "子图",
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
    command = DirectorCommand(
        "location.generate_set",
        rig.document.revision,
        uuid4().hex,
        {"target_ids": [ids["room"]]},
    )
    response = asyncio.run(http(rig.service, agent(rig.document, command), command))
    assert response.status == 200
    assert len(rig.document.generations) >= 1
    submitted = [
        generation
        for generation in rig.document.generations
        if generation.target_id in {ids["pano"], ids["child"]}
    ]
    assert [item.target_id for item in submitted] == [ids["pano"]]
    assert submitted[0].kind is KIND.LOCATION_IMAGE
