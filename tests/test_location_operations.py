"""location.apply_operations 的严格 wire、scope、CRUD 与场景语义绑定。"""

from uuid import uuid4

import pytest
from test_location_generation import KIND, Rig

from core.director_commands import parse_location_operations_patch


@pytest.fixture(name="rig")
def _rig_fixture(tmp_path) -> Rig:
    return Rig(tmp_path)


def patch(operations, *, locations=(), scenes=()):
    return {
        "scope": {"location_ids": list(locations), "scene_ids": list(scenes)},
        "operations": operations,
    }


def test_wire_rejects_unknown_fields_and_old_view_operations():
    with pytest.raises(ValueError, match="缺少字段|不接受字段"):
        parse_location_operations_patch(
            {**patch([{"op": "delete_location", "location_id": "1" * 32}]), "extra": 1}
        )
    with pytest.raises(ValueError, match="不支持的 location operation"):
        parse_location_operations_patch(patch([{"op": "create_view", "location_id": "1" * 32}]))
    with pytest.raises(ValueError, match="scope"):
        parse_location_operations_patch(
            {
                "scope": {"location_ids": [], "scene_ids": [], "shot_ids": []},
                "operations": [{"op": "delete_location", "location_id": "1" * 32}],
            }
        )


def test_create_location_image_requires_description_and_kind():
    with pytest.raises(ValueError, match="必须包含 name、kind 与 description"):
        parse_location_operations_patch(
            patch(
                [
                    {
                        "op": "create_image",
                        "location_id": "1" * 32,
                        "key": "still",
                        "fields": {"name": "图"},
                    }
                ]
            )
        )
    with pytest.raises(ValueError, match="kind"):
        parse_location_operations_patch(
            patch(
                [
                    {
                        "op": "create_image",
                        "location_id": "1" * 32,
                        "key": "still",
                        "fields": {
                            "name": "图",
                            "kind": "master",
                            "description": "实际画面。",
                        },
                    }
                ]
            )
        )


def test_same_patch_local_keys_create_complete_location(rig: Rig):
    result = rig.run(
        "location.apply_operations",
        patch(
            [
                {
                    "op": "create_location",
                    "key": "hall",
                    "name": "大厅",
                    "description": "高挑大厅。",
                },
                {
                    "op": "upsert_fixture",
                    "location_id": "hall",
                    "fixture": "desk",
                    "name": "前台",
                    "description": "木制前台。",
                },
                {
                    "op": "upsert_state",
                    "location_id": "hall",
                    "state": "night",
                    "name": "夜晚",
                    "description": "仅开壁灯。",
                },
                {
                    "op": "create_image",
                    "location_id": "hall",
                    "key": "pano",
                    "fields": {
                        "name": "大厅全景",
                        "kind": "panorama",
                        "description": "大厅四周完整空间。",
                        "prompt_text": "大厅 360 度全景。",
                        "reference_asset_ids": [],
                        "source": None,
                    },
                },
            ]
        ),
    )
    ids = result.data["created_ids"]
    location = rig.document.location_library.location(ids["hall"])
    assert location is not None
    assert location.fixtures[0].id == ids["desk"]
    assert location.states[0].id == ids["night"]
    assert location.images[0].id == ids["pano"]
    assert location.images[0].description == "大厅四周完整空间。"


def test_scope_prevents_cross_location_image_edit(rig: Rig):
    first = rig.build()
    second = rig.run(
        "location.apply_operations",
        patch(
            [
                {
                    "op": "create_location",
                    "key": "other",
                    "name": "街道",
                    "description": "室外街道。",
                }
            ]
        ),
    ).data["created_ids"]
    with pytest.raises(ValueError, match="超出 scope"):
        rig.run(
            "location.apply_operations",
            patch(
                [
                    {
                        "op": "update_image",
                        "image_id": first["front"],
                        "fields": {"name": "越权改名"},
                    }
                ],
                locations=(second["other"],),
            ),
        )


def test_update_and_clear_image_selection_preserve_other_images(rig: Rig):
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
    asset = rig.generate_finish_select(ids["a"])
    rig.run(
        "location.apply_operations",
        patch(
            [
                {
                    "op": "update_image",
                    "image_id": ids["a"],
                    "fields": {"name": "A2", "description": "更新后的 A 图。"},
                }
            ],
            locations=(ids["room"],),
        ),
    )
    assert rig.image_row(ids["a"]).selected_asset_id == asset
    assert rig.image_row(ids["a"]).name == "A2"
    assert rig.image_row(ids["b"]).name == "B"
    rig.run(
        "location.apply_operations",
        patch(
            [{"op": "clear_image_selection", "image_id": ids["a"]}],
            locations=(ids["room"],),
        ),
    )
    assert rig.image_row(ids["a"]).selected_asset_id is None


def test_scene_binds_only_semantic_location_and_state(rig: Rig):
    ids = rig.build()
    scene = rig.document.director_script.scenes[0]
    rig.run(
        "location.apply_operations",
        patch(
            [
                {
                    "op": "bind_scene",
                    "scene_id": scene.id,
                    "location_id": ids["room"],
                    "state_id": ids["night"],
                }
            ],
            scenes=(scene.id,),
        ),
    )
    bound = rig.document.director_script.scenes[0]
    assert bound.location_id == ids["room"]
    assert bound.state_id == ids["night"]
    assert all(not hasattr(shot, "view_id") for shot in bound.shots)


def test_deletion_checks_scene_semantics_but_images_have_no_live_dependents(rig: Rig):
    ids = rig.build()
    scene = rig.document.director_script.scenes[0]
    rig.run(
        "location.apply_operations",
        patch(
            [
                {
                    "op": "bind_scene",
                    "scene_id": scene.id,
                    "location_id": ids["room"],
                    "state_id": ids["night"],
                }
            ],
            scenes=(scene.id,),
        ),
    )
    with pytest.raises(ValueError, match="仍被 Scene"):
        rig.run(
            "location.apply_operations",
            patch(
                [{"op": "delete_location", "location_id": ids["room"]}],
                locations=(ids["room"],),
            ),
        )
    rig.run(
        "location.apply_operations",
        patch(
            [{"op": "delete_image", "image_id": ids["front"]}],
            locations=(ids["room"],),
        ),
    )
    assert rig.document.location_library.image_owner(ids["front"]) is None


def test_stale_retry_is_rejected_without_duplicate_location(rig: Rig):
    body = patch(
        [
            {
                "op": "create_location",
                "key": "yard",
                "name": "院子",
                "description": "石板院子。",
            }
        ]
    )
    command_id = uuid4().hex
    expected_revision = rig.document.revision
    first = rig.registry.execute(
        __import__("core.director_commands", fromlist=["DirectorCommand"]).DirectorCommand(
            "location.apply_operations", expected_revision, command_id, body
        )
    )
    with pytest.raises(ValueError, match="项目已更新"):
        rig.registry.execute(
            __import__("core.director_commands", fromlist=["DirectorCommand"]).DirectorCommand(
                "location.apply_operations", expected_revision, command_id, body
            )
        )
    assert first.data["created_ids"]["yard"]
    assert (
        len([item for item in rig.document.location_library.locations if item.name == "院子"]) == 1
    )


def test_selection_can_reuse_another_location_images_output_from_the_asset_library(rig: Rig):
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
    rig.generate_image(ids["a"])
    generation = rig.last(KIND.LOCATION_IMAGE, ids["a"])
    rig.finish(generation.id)
    asset_id = rig.last(KIND.LOCATION_IMAGE, ids["a"]).output_asset_id
    assert asset_id is not None
    rig.select_image(ids["b"], asset_id)
    assert rig.image_row(ids["b"]).selected_asset_id == asset_id
