"""地点 Planner 的独立图片 proposal 与增补语义。"""

import json

import pytest

from core.director_proposals import (
    ExistingLocationInput,
    LocationImageProposal,
    LocationPlanProposal,
    LocationProposal,
    LocationSceneInput,
    PanoramaCaptureSourceProposal,
    SceneLocationBindingProposal,
)
from core.director_proposals.location_codec import compile_location_proposal, parse_location_plan


def uid(char: str) -> str:
    return char * 32


def image(key: str, *, kind: str = "image", source=None) -> LocationImageProposal:
    return LocationImageProposal(
        name=key,
        kind=kind,
        description=f"{key} 的实际画面说明。",
        prompt_text=f"生成 {key}。",
        reference_asset_ids=(),
        source=source,
        key=key,
    )


def location(images) -> LocationProposal:
    return LocationProposal(
        name="客厅",
        description="跨 Scene 共享的固定客厅。",
        key_light=None,
        fixtures=(),
        states=(),
        images=tuple(images),
        key="room",
    )


def test_proposal_allows_location_without_panorama():
    proposal = LocationPlanProposal((location((image("front"),)),), ())
    assert proposal.locations[0].images[0].kind == "image"
    assert not any(item.kind == "panorama" for item in proposal.locations[0].images)


def test_panorama_and_capture_child_are_explicit_siblings():
    source = PanoramaCaptureSourceProposal("pano", 90.0, 0.0, 60.0)
    proposal = LocationPlanProposal(
        (location((image("pano", kind="panorama"), image("front", source=source))),), ()
    )
    assert [item.kind for item in proposal.locations[0].images] == ["panorama", "image"]
    assert proposal.locations[0].images[1].source.panorama_image_id == "pano"


def test_capture_source_key_must_exist_in_same_location():
    with pytest.raises(ValueError, match="同一地点"):
        location(
            (
                image(
                    "front",
                    source=PanoramaCaptureSourceProposal("missing", 0.0, 0.0, 60.0),
                ),
            )
        )


def test_image_description_is_mandatory_in_agent_output():
    with pytest.raises(ValueError, match="实际内容说明"):
        LocationImageProposal(
            name="无说明图片",
            kind="image",
            description=" ",
            prompt_text="画面。",
            reference_asset_ids=(),
            source=None,
            key="still",
        )


def test_compiler_emits_create_image_and_scene_semantic_binding():
    scene_id = uid("1")
    proposal = LocationPlanProposal(
        (location((image("front"),)),),
        (SceneLocationBindingProposal(scene_id, "room", None),),
    )
    compiled = compile_location_proposal(
        proposal,
        (LocationSceneInput(scene_id, "Scene", "摘要", "地点", ()),),
        (),
    )
    operation_names = [type(item).__name__ for item in compiled.operations]
    assert operation_names == ["CreateLocation", "CreateLocationImage", "BindScene"]
    assert compiled.scope_scene_ids == (scene_id,)
    assert compiled.scope_location_ids == ()


def test_compiler_updates_existing_image_without_deleting_unspecified_items():
    location_id, image_id = uid("2"), uid("3")
    proposal = LocationPlanProposal(
        (
            LocationProposal(
                name="客厅",
                description="更新说明。",
                key_light=None,
                fixtures=(),
                states=(),
                images=(
                    LocationImageProposal(
                        name="正打",
                        kind="image",
                        description="更新后的正打画面说明。",
                        prompt_text="更新正打。",
                        reference_asset_ids=(),
                        source=None,
                        id=image_id,
                    ),
                ),
                id=location_id,
            ),
        ),
        (),
    )
    existing = (ExistingLocationInput(location_id, (), (), (image_id, uid("4"))),)
    compiled = compile_location_proposal(proposal, (), existing)
    names = [type(item).__name__ for item in compiled.operations]
    assert names == ["UpdateLocation", "UpdateLocationImage"]
    assert all("Delete" not in name for name in names)


def test_json_parser_rejects_old_master_and_views_shape():
    raw = json.dumps(
        {
            "locations": [
                {
                    "key": "room",
                    "id": None,
                    "name": "客厅",
                    "description": "固定空间。",
                    "key_light": None,
                    "fixtures": [],
                    "states": [],
                    "images": [],
                    "master_prompt_text": "旧字段",
                }
            ],
            "scene_bindings": [],
        },
        ensure_ascii=False,
    )
    with pytest.raises(ValueError, match="未声明字段"):
        parse_location_plan(raw)


def test_json_parser_preserves_arbitrary_reference_assets():
    asset_a, asset_b = uid("a"), uid("b")
    raw = json.dumps(
        {
            "locations": [
                {
                    "id": None,
                    "key": "room",
                    "name": "客厅",
                    "description": "固定空间。",
                    "key_light": None,
                    "fixtures": [],
                    "states": [],
                    "images": [
                        {
                            "id": None,
                            "key": "still",
                            "name": "静帧",
                            "kind": "image",
                            "description": "静帧实际内容。",
                            "prompt_text": "生成静帧。",
                            "reference_asset_ids": [asset_a, asset_b],
                            "source": None,
                        }
                    ],
                }
            ],
            "scene_bindings": [],
        },
        ensure_ascii=False,
    )
    parsed = parse_location_plan(raw)
    assert parsed.locations[0].images[0].reference_asset_ids == (asset_a, asset_b)
