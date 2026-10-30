"""Keyframe 与地点图片解耦后的契约回归。"""

import asyncio
from dataclasses import fields
from pathlib import Path

import pytest
from test_director_commands import _visual_project

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.structured_director.models import Keyframe


def test_keyframe_model_has_no_location_or_environment_binding():
    names = {item.name for item in fields(Keyframe)}
    assert "environment_mode" not in names
    assert "environment_view_id" not in names
    assert "environment_none_reason" not in names
    assert names == {
        "id",
        "owner_segment_id",
        "predecessor_keyframe_id",
        "prompt_text",
        "visible_character_ids",
        "selected_asset_id",
        "character_references",
        "reference_keyframe_ids",
        # 显式参考的地点图片条目只是生图输入，不是 Keyframe 的地点或视图绑定。
        "reference_location_image_ids",
    }


def test_visual_unlock_creates_blank_keyframes_without_location_defaults(tmp_path: Path):
    store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    assert document.keyframe_plan is not None
    for frame in document.keyframe_plan.keyframes:
        assert frame.prompt_text == ""
        assert not hasattr(frame, "environment_view_id")


def test_keyframe_update_wire_rejects_removed_environment_fields(tmp_path: Path):
    store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    binding = document.keyframe_plan.segments[0]
    registry = DirectorCommandRegistry(store)
    with pytest.raises(ValueError, match="缺少字段|不接受字段|未声明字段"):
        registry.execute(
            DirectorCommand(
                "keyframe.apply_operations",
                document.revision,
                "1" * 32,
                {
                    "operations": [
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": binding.start_keyframe_id,
                            "fields": {
                                "prompt_text": "空镜。",
                                "visible_character_ids": [],
                                "character_references": [],
                                "environment_mode": "none",
                            },
                        }
                    ],
                },
            )
        )


def test_keyframe_prompt_can_describe_location_without_core_binding(tmp_path: Path):
    store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    binding = document.keyframe_plan.segments[0]
    registry = DirectorCommandRegistry(store)
    result = registry.execute(
        DirectorCommand(
            "keyframe.apply_operations",
            document.revision,
            "2" * 32,
            {
                "operations": [
                    {
                        "op": "update_frame_fields",
                        "keyframe_id": binding.start_keyframe_id,
                        "fields": {
                            "prompt_text": "客厅壁炉前的暖色中景。",
                            "visible_character_ids": [],
                            "character_references": [],
                        },
                    }
                ],
            },
        )
    )
    frame = next(
        item
        for item in result.document.keyframe_plan.keyframes
        if item.id == binding.start_keyframe_id
    )
    assert frame.prompt_text == "客厅壁炉前的暖色中景。"
    assert not hasattr(frame, "environment_mode")


def test_script_shot_wire_rejects_view_id(tmp_path: Path):
    store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    scene = document.director_script.scenes[0]
    shot = scene.shots[0]
    registry = DirectorCommandRegistry(store)
    with pytest.raises(ValueError, match="缺少字段|不接受字段|未声明字段"):
        registry.execute(
            DirectorCommand(
                "script.apply_operations",
                document.revision,
                "3" * 32,
                {
                    "scope": {"scene_ids": [scene.id]},
                    "operations": [
                        {
                            "op": "update_shot_fields",
                            "shot_id": shot.id,
                            "fields": {
                                "view_id": None,
                            },
                        }
                    ],
                },
            )
        )


def test_location_image_delete_never_rewrites_keyframe_plan(tmp_path: Path):
    store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    registry = DirectorCommandRegistry(store)
    created = registry.execute(
        DirectorCommand(
            "location.apply_operations",
            document.revision,
            "4" * 32,
            {
                "scope": {"location_ids": [], "scene_ids": []},
                "operations": [
                    {
                        "op": "create_location",
                        "key": "room",
                        "name": "客厅",
                        "description": "固定空间。",
                    },
                    {
                        "op": "create_image",
                        "location_id": "room",
                        "key": "still",
                        "fields": {
                            "name": "壁炉",
                            "kind": "image",
                            "description": "壁炉中景。",
                            "prompt_text": "壁炉中景。",
                        },
                    },
                ],
            },
        )
    )
    before = created.document.keyframe_plan
    ids = created.data["created_ids"]
    deleted = registry.execute(
        DirectorCommand(
            "location.apply_operations",
            created.document.revision,
            "5" * 32,
            {
                "scope": {"location_ids": [ids["room"]], "scene_ids": []},
                "operations": [{"op": "delete_image", "image_id": ids["still"]}],
            },
        )
    )
    assert deleted.document.keyframe_plan == before
