"""专业工作集只给导演脚本与极简索引；索引之外的完整详情经 project.get_details 按 ID 读取。"""

import asyncio

import pytest
from structured_director_fixtures import install_location
from test_prompt_worksets import fixture

from core.application.caller import READ_OPERATIONS
from core.structured_director.reads.read_tools import execute_project_read


def _details(document, **arguments):
    return execute_project_read(document, "project.get_details", arguments)


def test_details_read_full_objects_by_id_and_report_missing(tmp_path):
    store, _, document, _ = asyncio.run(fixture(tmp_path))
    document = install_location(store, scene_ids=(document.director_script.scenes[0].id,))
    keyframe = next(item for item in document.keyframe_plan.keyframes if item.prompt_text)
    character = document.reference_library.characters[0]
    location = document.location_library.locations[-1]
    image = location.images[0]
    missing = "f" * 32

    result = _details(document, kind="keyframe", ids=[keyframe.id, missing])
    assert result["kind"] == "keyframe"
    assert [item["keyframe_id"] for item in result["items"]] == [keyframe.id]
    assert result["items"][0]["prompt_text"] == keyframe.prompt_text
    assert result["items"][0]["bindings"]
    assert result["missing_ids"] == [missing]

    character_item = _details(document, kind="character", ids=[character.id])["items"][0]
    assert character_item["id"] == character.id
    assert character_item["visual_description"] == character.visual_description
    location_item = _details(document, kind="location", ids=[location.id])["items"][0]
    assert location_item["images"][0]["prompt_text"] == image.prompt_text
    image_item = _details(document, kind="location_image", ids=[image.id])["items"][0]
    assert image_item["description"] == image.description
    assert image_item["location_id"] == location.id
    assert image_item["referenceable"] is False

    plan = _details(document, kind="director_plan")["items"]
    assert plan == [{"director_plan_markdown": document.director_plan_markdown}]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"kind": "director_plan", "ids": ["a" * 32]}, "不接受 ids"),
        ({"kind": "keyframe"}, "必须给出 ids"),
        ({"kind": "keyframe", "ids": [f"{index:032x}" for index in range(21)]}, "1 到 20"),
        ({"kind": "asset", "ids": ["a" * 32]}, "kind 只允许"),
        ({"kind": "keyframe", "ids": ["a" * 32], "extra": 1}, "未声明字段"),
    ],
)
def test_details_reject_invalid_arguments(tmp_path, arguments, message):
    _, _, document, _ = asyncio.run(fixture(tmp_path))
    with pytest.raises(ValueError, match=message):
        _details(document, **arguments)


def test_details_is_an_agent_read_operation():
    assert "project.get_details" in READ_OPERATIONS


def test_keyframe_workset_carries_indexes_not_full_text(tmp_path):
    store, _, document, _ = asyncio.run(fixture(tmp_path))
    scene = document.director_script.scenes[0]
    document = install_location(store, scene_ids=(scene.id,))
    workset = execute_project_read(
        document,
        "project.get_workset",
        {"capability": "keyframe", "scope": {"scene_ids": [scene.id]}},
    )
    facts = workset["core_facts"]
    assert facts["referenceable_keyframes"]
    for item in facts["referenceable_keyframes"]:
        assert set(item) == {"keyframe_id", "bindings", "visible_character_ids"}
    for item in facts["location_images"]:
        assert "description" not in item and "prompt_text" not in item
    # 本 Scene 绑定地点的图片强制说明仍随工作集交付，生成正文不交付。
    images = facts["location_library"][0]["images"]
    assert images[0]["description"] and "prompt_text" not in images[0]
    assert "prefixItems" not in workset["output_schema"]["properties"]["segments"]


def test_location_workset_reads_plan_and_image_text_on_demand(tmp_path):
    store, _, document, _ = asyncio.run(fixture(tmp_path))
    document = install_location(store)
    workset = execute_project_read(
        document,
        "project.get_workset",
        {"capability": "location", "scope": {"project_id": document.project_id}},
    )
    facts = workset["core_facts"]
    assert "director_plan_markdown" not in facts
    image = facts["location_library"][-1]["images"][0]
    assert set(image) == {"id", "name", "kind", "has_selected_image"}
