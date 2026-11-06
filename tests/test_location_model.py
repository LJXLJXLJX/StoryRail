"""地点语义、独立图片和去绑定后的 Shot/Keyframe 模型约束。"""

from dataclasses import fields, replace

import pytest

from core.structured_director.models import (
    Keyframe,
    Location,
    LocationFixture,
    LocationImage,
    LocationImageKind,
    LocationKeyLight,
    LocationLibrary,
    LocationState,
    PanoramaCaptureRequest,
    PanoramaCaptureSource,
    Shot,
)


def uid(char: str) -> str:
    return char * 32


def image(**overrides) -> LocationImage:
    values = {
        "id": uid("a"),
        "name": "壁炉正面",
        "kind": LocationImageKind.IMAGE,
        "description": "壁炉、木地板和白墙的正面中景。",
        "prompt_text": "温暖客厅的壁炉正面。",
    }
    values.update(overrides)
    return LocationImage(**values)


def test_location_needs_no_panorama_or_master_image():
    location = Location(uid("1"), "客厅", "跨 Scene 使用的固定空间。")
    assert location.images == ()
    assert {item.name for item in fields(Location)} == {
        "id",
        "name",
        "description",
        "fixtures",
        "key_light",
        "states",
        "images",
    }


def test_each_image_requires_human_readable_description():
    with pytest.raises(ValueError, match="location.image.description"):
        image(description="")
    with pytest.raises(ValueError, match="location.image.name"):
        image(name="")
    assert image(description="实际画面说明。 ").description == "实际画面说明。 "


def test_image_references_are_unique_valid_and_capped():
    refs = tuple(f"{number:032x}" for number in range(1, 7))
    assert image(reference_asset_ids=refs[:5]).reference_asset_ids == refs[:5]
    with pytest.raises(ValueError, match="最多使用 5 张"):
        image(reference_asset_ids=refs)
    with pytest.raises(ValueError, match="不能重复"):
        image(reference_asset_ids=(refs[0], refs[0]))
    with pytest.raises(ValueError, match="不合法"):
        image(reference_asset_ids=("bad",))


def test_panorama_is_only_an_image_kind():
    panorama = image(kind=LocationImageKind.PANORAMA, name="空间全景")
    assert panorama.kind is LocationImageKind.PANORAMA
    assert panorama.source is None
    with pytest.raises(ValueError, match="image 或 panorama"):
        image(kind="panorama")


def test_panorama_capture_source_only_belongs_to_plain_image():
    source = PanoramaCaptureSource(uid("b"), 180.0, -20.0, 70.0)
    child = image(source=source)
    assert child.source == source
    with pytest.raises(ValueError, match="只有普通地点图片"):
        replace(child, kind=LocationImageKind.PANORAMA)
    with pytest.raises(ValueError, match="yaw"):
        PanoramaCaptureSource(uid("b"), 361.0, 0.0, 60.0)


def test_capture_request_freezes_asset_camera_and_project_aspect():
    request = PanoramaCaptureRequest(uid("c"), 30.0, 5.0, 75.0, "16:9")
    assert request.panorama_asset_id == uid("c")
    assert request.master_asset_id == uid("c")
    assert request.aspect_ratio == "16:9"
    with pytest.raises(ValueError, match="水平视场角"):
        PanoramaCaptureRequest(uid("c"), 30.0, 5.0, 181.0, "16:9")


def test_location_semantics_and_ids_are_validated():
    fixture = LocationFixture(uid("d"), "壁炉", "石砌壁炉")
    state = LocationState(uid("e"), "夜晚", "仅有壁炉火光。")
    location = Location(
        uid("1"),
        "客厅",
        "固定空间。",
        (fixture,),
        LocationKeyLight("壁炉火光。"),
        (state,),
        (image(),),
    )
    library = LocationLibrary((location,))
    assert library.image_owner(uid("a")) == (location, location.images[0])
    assert library.selected_image_asset(uid("a")) is None
    with pytest.raises(ValueError, match="不能重复"):
        LocationLibrary((location, replace(location, id=uid("2"), images=(image(),))))


def test_shot_and_keyframe_have_no_location_binding_fields():
    shot = Shot(uid("2"), (), "中景", "固定", "人物停下。", "环境声", None)
    keyframe = Keyframe(uid("3"), uid("4"), None, "人物停下。", ())
    shot_fields = {item.name for item in fields(shot)}
    keyframe_fields = {item.name for item in fields(keyframe)}
    assert "view_id" not in shot_fields
    assert (
        not {
            "environment_mode",
            "environment_view_id",
            "environment_none_reason",
        }
        & keyframe_fields
    )
