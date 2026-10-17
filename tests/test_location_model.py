"""Location 领域模型约束（docs/data-model.md「地点库」）：每条约束至少一个用例。

模型级约束直接构造 dataclass 断言 ``__post_init__``；跨实体归属
（Scene state、Shot view、Keyframe view 必须落在正确的 Location 内）
经 ``store_factory`` 的真实文档 + ``replace`` 触发完整 validate_document 锁定。
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from core.structured_director.codec.location import (
    _parse_location_library,
    serialize_location_library,
)
from core.structured_director.models import (
    MAX_IMAGE_INPUTS,
    DirectorScript,
    Keyframe,
    KeyframeEnvironmentMode,
    KeyframePlan,
    Location,
    LocationFixture,
    LocationKeyLight,
    LocationKind,
    LocationLibrary,
    LocationMaster,
    LocationState,
    LocationView,
    Scene,
    SegmentKeyframes,
    Shot,
    ShotSegment,
    StructuredDirectorStatus,
    WorkspaceLayers,
)
from core.structured_director.models.location import (
    LOCATION_YAW_OFFSET_RANGE,
    MAX_LOCATION_FIXTURES,
    MAX_LOCATION_STATES,
    MAX_LOCATION_VIEWS,
    MAX_LOCATIONS,
)

LOCATION_ID = "1" * 32
FIXTURE_ID = "2" * 32
STATE_ID = "3" * 32
VIEW_ID = "4" * 32
SCENE_ID = "5" * 32
SHOT_ID = "6" * 32
SEGMENT_ID = "7" * 32
KEYFRAME_START_ID = "8" * 32
KEYFRAME_END_ID = "9" * 32
ASSET_ID = "a" * 32


def _ids(prefix: int, count: int) -> tuple[str, ...]:
    return tuple(f"{prefix:02x}{index:030x}" for index in range(count))


def _view(view_id: str = VIEW_ID, **overrides) -> LocationView:
    fields = dict(id=view_id, name="主机位", purpose="人眼高中景", azimuth_deg=0.0)
    fields.update(overrides)
    return LocationView(**fields)


def _location(location_id: str = LOCATION_ID, **overrides) -> Location:
    fields = dict(id=location_id, name="共享客厅", kind=LocationKind.INTERIOR)
    fields.update(overrides)
    return Location(**fields)


def _raises(message: str, build) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        build()


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def test_location_id_must_be_32_hex():
    assert _location().id == LOCATION_ID
    for invalid in ("not-an-id", "1" * 31, "1" * 33, "A" * 32, ""):
        _raises("location.id 不合法。", lambda invalid=invalid: _location(invalid))


def test_location_name_length_1_to_200():
    _location(name="地")
    _location(name="地" * 200)
    for invalid in ("", "   ", "地" * 201):
        _raises(
            "location.name 不能为空或超过 200 字符。",
            lambda invalid=invalid: _location(name=invalid),
        )


def test_location_kind_must_be_enum():
    _raises("location.kind 必须是 interior 或 exterior。", lambda: _location(kind="indoor"))


def test_location_description_at_most_4000():
    _location(description="空" * 4000)
    _raises(
        "location.description 不能超过 4000 字符。",
        lambda: _location(description="空" * 4001),
    )


def test_location_collection_limits():
    fixtures = tuple(
        LocationFixture(item_id, f"陈设{index}")
        for index, item_id in enumerate(_ids(2, MAX_LOCATION_FIXTURES + 1))
    )
    _location(fixtures=fixtures[:-1])
    _raises(
        f"单个地点最多 {MAX_LOCATION_FIXTURES} 项固定陈设。",
        lambda: _location(fixtures=fixtures),
    )
    states = tuple(
        LocationState(item_id, f"状态{index}", "可见差异。")
        for index, item_id in enumerate(_ids(3, MAX_LOCATION_STATES + 1))
    )
    _location(states=states[:-1])
    _raises(f"单个地点最多 {MAX_LOCATION_STATES} 个状态。", lambda: _location(states=states))
    views = tuple(_view(item_id) for item_id in _ids(4, MAX_LOCATION_VIEWS + 1))
    _location(views=views[:-1])
    _raises(f"单个地点最多 {MAX_LOCATION_VIEWS} 个视图。", lambda: _location(views=views))


def test_project_allows_at_most_200_locations():
    locations = tuple(_location(item_id) for item_id in _ids(1, MAX_LOCATIONS + 1))
    LocationLibrary(locations[:-1])
    _raises(f"项目最多 {MAX_LOCATIONS} 个地点。", lambda: LocationLibrary(locations))


def test_location_item_ids_must_be_unique_within_location():
    _raises(
        "同一地点的陈设、状态和视图 ID 不能重复。",
        lambda: _location(
            fixtures=(LocationFixture(FIXTURE_ID, "壁炉"), LocationFixture(FIXTURE_ID, "书架"))
        ),
    )
    _raises(
        "同一地点的陈设、状态和视图 ID 不能重复。",
        lambda: _location(
            states=(
                LocationState(STATE_ID, "白天", "日光。"),
                LocationState(STATE_ID, "夜晚", "灯光。"),
            )
        ),
    )
    _raises(
        "同一地点的陈设、状态和视图 ID 不能重复。",
        lambda: _location(views=(_view(), _view())),
    )


def test_location_ids_must_be_unique_across_project():
    first = _location(fixtures=(LocationFixture(FIXTURE_ID, "壁炉"),))
    second = _location("b" * 32, name="阳台", fixtures=(LocationFixture(FIXTURE_ID, "壁炉"),))
    _raises(
        "地点、陈设、状态和视图 ID 在项目内不能重复。",
        lambda: LocationLibrary((first, second)),
    )


# ---------------------------------------------------------------------------
# Fixture 与 key_light
# ---------------------------------------------------------------------------


def test_fixture_azimuth_in_0_to_360_exclusive():
    LocationFixture(FIXTURE_ID, "壁炉")
    LocationFixture(FIXTURE_ID, "壁炉", azimuth_deg=0.0)
    LocationFixture(FIXTURE_ID, "壁炉", azimuth_deg=359.5)
    message = "location.fixture.azimuth_deg 必须在 [0, 360) 度内。"
    for invalid in (360.0, -0.5, float("nan"), float("inf"), True):
        _raises(
            message,
            lambda invalid=invalid: LocationFixture(FIXTURE_ID, "壁炉", azimuth_deg=invalid),
        )


def test_key_light_structure():
    assert LocationKeyLight("窗外自然光。").azimuth_deg is None
    LocationKeyLight("窗外自然光。", azimuth_deg=90.0)
    _raises(
        "location.key_light.description 不能为空或超过 1000 字符。",
        lambda: LocationKeyLight(""),
    )
    _raises(
        "location.key_light.azimuth_deg 必须在 [0, 360) 度内。",
        lambda: LocationKeyLight("窗外自然光。", azimuth_deg=360.0),
    )


def test_master_reference_images_unique_and_capped():
    asset_ids = _ids(10, MAX_IMAGE_INPUTS + 1)
    LocationMaster(reference_asset_ids=asset_ids[:-1])
    _raises(
        f"地点主图最多使用 {MAX_IMAGE_INPUTS} 张参考图。",
        lambda: LocationMaster(reference_asset_ids=asset_ids),
    )
    _raises(
        "location.master.reference_asset_ids 不能重复。",
        lambda: LocationMaster(reference_asset_ids=(ASSET_ID, ASSET_ID)),
    )
    _raises(
        "location.master.selected_asset_id 不合法。",
        lambda: LocationMaster(selected_asset_id="not-an-id"),
    )


def test_calibration_tracks_selected_master():
    location = _location(master=LocationMaster(selected_asset_id=ASSET_ID))
    assert location.calibrated is False
    calibrated = replace(location, calibrated_master_asset_id=ASSET_ID)
    assert calibrated.calibrated is True
    _raises(
        "location.calibrated_master_asset_id 不合法。",
        lambda: replace(location, calibrated_master_asset_id="not-an-id"),
    )


# ---------------------------------------------------------------------------
# LocationView
# ---------------------------------------------------------------------------


def test_view_orientation_requires_exactly_one_form():
    # 方位与相对陈设同时给出或同时缺失都拒绝。
    _raises(
        "视图朝向必须二选一：azimuth_deg，或 look_at_fixture_id 与 yaw_offset_deg。",
        lambda: _view(azimuth_deg=None),
    )
    _raises(
        "视图朝向必须二选一：azimuth_deg，或 look_at_fixture_id 与 yaw_offset_deg。",
        lambda: _view(look_at_fixture_id=FIXTURE_ID, yaw_offset_deg=10.0),
    )


def test_view_relative_orientation_requires_fixture_and_offset_together():
    _raises(
        "相对陈设的视图必须同时给出 look_at_fixture_id 与 yaw_offset_deg。",
        lambda: _view(azimuth_deg=None, look_at_fixture_id=FIXTURE_ID),
    )
    _raises(
        "相对陈设的视图必须同时给出 look_at_fixture_id 与 yaw_offset_deg。",
        lambda: _view(azimuth_deg=None, yaw_offset_deg=0.0),
    )
    view = _view(azimuth_deg=None, look_at_fixture_id=FIXTURE_ID, yaw_offset_deg=0.0)
    location = _location(fixtures=(LocationFixture(FIXTURE_ID, "壁炉"),), views=(view,))
    assert location.views[0] is view


def test_view_yaw_offset_range():
    minimum, maximum = LOCATION_YAW_OFFSET_RANGE
    _view(azimuth_deg=None, look_at_fixture_id=FIXTURE_ID, yaw_offset_deg=minimum)
    _view(azimuth_deg=None, look_at_fixture_id=FIXTURE_ID, yaw_offset_deg=maximum)
    message = "location.view.yaw_offset_deg 必须在 [-180, 180] 度内。"
    for invalid in (minimum - 0.5, maximum + 0.5, float("nan")):
        _raises(
            message,
            lambda invalid=invalid: _view(
                azimuth_deg=None, look_at_fixture_id=FIXTURE_ID, yaw_offset_deg=invalid
            ),
        )


def test_view_azimuth_range():
    _view(azimuth_deg=0.0)
    _view(azimuth_deg=359.5)
    message = "location.view.azimuth_deg 必须在 [0, 360) 度内。"
    for invalid in (360.0, -0.5, float("nan"), True):
        _raises(message, lambda invalid=invalid: _view(azimuth_deg=invalid))


def test_view_pitch_range():
    _view(pitch_deg=-60.0)
    _view(pitch_deg=60.0)
    message = "location.view.pitch_deg 必须在 [-60, 60] 度内。"
    for invalid in (-60.5, 60.5, float("nan")):
        _raises(message, lambda invalid=invalid: _view(pitch_deg=invalid))


def test_view_hfov_range():
    _view(hfov_deg=20.0)
    _view(hfov_deg=120.0)
    message = "location.view.hfov_deg 必须在 [20, 120] 度内。"
    for invalid in (19.5, 120.5, float("nan")):
        _raises(message, lambda invalid=invalid: _view(hfov_deg=invalid))


def test_view_state_must_belong_to_same_location():
    view = _view(state_id=STATE_ID)
    _location(states=(LocationState(STATE_ID, "夜晚", "灯光。"),), views=(view,))
    _raises(
        f"视图「{view.name}」的状态不属于该地点。",
        lambda: _location(views=(view,)),
    )


def test_view_look_at_fixture_must_belong_to_same_location():
    view = _view(azimuth_deg=None, look_at_fixture_id=FIXTURE_ID, yaw_offset_deg=0.0)
    _raises(
        f"视图「{view.name}」朝向的陈设不属于该地点。",
        lambda: _location(views=(view,)),
    )


def test_view_reference_views_must_be_same_location_without_duplicates():
    other = _view("b" * 32)
    _location(views=(_view(reference_view_ids=(other.id,)), other))
    _raises(
        "location.view.reference_view_ids 不能重复。",
        lambda: _view(reference_view_ids=(other.id, other.id)),
    )
    _raises(
        "地点视图不能参考自身。",
        lambda: _view(reference_view_ids=(VIEW_ID,)),
    )
    _raises(
        "视图「主机位」只能参考同一地点的其它视图。",
        lambda: _location(views=(_view(reference_view_ids=(other.id,)),)),
    )


def test_view_reference_graph_must_be_acyclic():
    first = _view("b" * 32, reference_view_ids=(VIEW_ID,))
    second = _view(reference_view_ids=(first.id,))
    _raises(
        "地点视图的参考依赖不能形成环。",
        lambda: _location(views=(first, second)),
    )
    # 无环的链式依赖合法。
    leaf = _view("c" * 32)
    middle = _view("b" * 32, reference_view_ids=(leaf.id,))
    top = _view(reference_view_ids=(middle.id, leaf.id))
    _location(views=(leaf, middle, top))


def test_view_reference_images_share_single_call_input_cap():
    references = _ids(11, MAX_IMAGE_INPUTS - 2)
    views = tuple(_view(item_id) for item_id in references)
    _location(views=(*views, _view(reference_view_ids=references)))
    _raises(
        f"地点视图的底图、主图与参考视图合计不能超过 {MAX_IMAGE_INPUTS} 张输入。",
        lambda: _view(reference_view_ids=(*references, "c" * 32)),
    )


def test_view_crop_only_for_interior_locations():
    _location(views=(_view(crop_asset_id=ASSET_ID),))
    _raises(
        "只有室内地点的视图保存全景裁切图。",
        lambda: _location(kind=LocationKind.EXTERIOR, views=(_view(crop_asset_id=ASSET_ID),)),
    )


def test_view_name_and_purpose_required():
    _raises("location.view.name 不能为空或超过 200 字符。", lambda: _view(name=""))
    _raises("location.view.purpose 不能为空或超过 1000 字符。", lambda: _view(purpose=""))


# ---------------------------------------------------------------------------
# Scene / Shot 与地点的绑定（模型级 + 文档级）
# ---------------------------------------------------------------------------


def _shot(view_id: str | None = None) -> Shot:
    return Shot(
        SHOT_ID,
        (),
        "中景，固定机位。",
        "固定。",
        "角色等待。",
        "环境声。",
        None,
        (ShotSegment(SEGMENT_ID, 2.0, "角色抬头。", (), None),),
        view_id,
    )


def _scene(**overrides) -> Scene:
    fields = dict(
        id=SCENE_ID,
        title="末班车",
        summary="摘要。",
        setting="环境。",
        shots=(_shot(),),
        driver="drama",
    )
    fields.update(overrides)
    return Scene(**fields)


def test_scene_state_requires_location():
    _raises(
        "Scene 未绑定地点时不能指定地点状态。",
        lambda: _scene(state_id=STATE_ID),
    )


def test_shot_view_requires_scene_location():
    _raises(
        "Scene 未绑定地点时 Shot 不能绑定地点视图。",
        lambda: _scene(shots=(_shot(VIEW_ID),)),
    )


def _document_with_scene(store, location: Location, scene: Scene):
    document = store.read()
    return replace(
        document,
        status=StructuredDirectorStatus.REVIEWING_SCRIPT,
        director_script=DirectorScript(1, document.revision, None, None, (scene,)),
        location_library=LocationLibrary((location,)),
    )


def test_scene_state_must_belong_to_its_location(store_factory):
    store = store_factory()
    location = _location(states=(LocationState(STATE_ID, "夜晚", "灯光。"),))
    _document_with_scene(store, location, _scene(location_id=location.id, state_id=STATE_ID))
    with pytest.raises(ValueError, match=re.escape("Scene 的地点状态必须属于该 Scene 的地点。")):
        _document_with_scene(store, location, _scene(location_id=location.id, state_id="b" * 32))


def test_scene_must_reference_existing_location(store_factory):
    store = store_factory()
    with pytest.raises(ValueError, match=re.escape("Scene 引用的地点不存在。")):
        _document_with_scene(store, _location(), _scene(location_id="b" * 32))


def test_shot_view_must_belong_to_scene_location(store_factory):
    store = store_factory()
    location = _location(views=(_view(),))
    _document_with_scene(store, location, _scene(location_id=location.id, shots=(_shot(VIEW_ID),)))
    with pytest.raises(ValueError, match=re.escape("Shot 的地点视图必须属于所在 Scene 的地点。")):
        _document_with_scene(
            store, location, _scene(location_id=location.id, shots=(_shot("b" * 32),))
        )


# ---------------------------------------------------------------------------
# Keyframe 的地点视图规则
# ---------------------------------------------------------------------------


def _keyframe(keyframe_id: str = KEYFRAME_START_ID, **overrides) -> Keyframe:
    fields = dict(
        id=keyframe_id,
        owner_segment_id=SEGMENT_ID,
        predecessor_keyframe_id=None,
        prompt_text="静态首帧。",
        visible_character_ids=(),
    )
    fields.update(overrides)
    return Keyframe(**fields)


def test_keyframe_none_requires_reason_and_no_view():
    assert _keyframe().environment_mode is KeyframeEnvironmentMode.NONE
    _raises(
        "Keyframe 不使用地点视图时必须说明理由。",
        lambda: _keyframe(environment_none_reason=None),
    )
    _raises(
        "keyframe.environment_none_reason 不能为空或超过 500 字符。",
        lambda: _keyframe(environment_none_reason=""),
    )
    _raises(
        "keyframe.environment_none_reason 不能为空或超过 500 字符。",
        lambda: _keyframe(environment_none_reason="理" * 501),
    )
    _keyframe(environment_none_reason="理" * 500)


def test_keyframe_none_and_view_are_mutually_exclusive():
    _raises(
        "Keyframe none 必须不指定地点视图；edit/reference 必须显式指定视图。",
        lambda: _keyframe(environment_view_id=VIEW_ID),
    )
    for mode in (KeyframeEnvironmentMode.EDIT, KeyframeEnvironmentMode.REFERENCE):
        _raises(
            "Keyframe none 必须不指定地点视图；edit/reference 必须显式指定视图。",
            lambda mode=mode: _keyframe(environment_mode=mode),
        )


def test_keyframe_using_view_must_not_keep_none_reason():
    for mode in (KeyframeEnvironmentMode.EDIT, KeyframeEnvironmentMode.REFERENCE):
        _raises(
            "Keyframe 使用地点视图时不能保存 none 理由。",
            lambda mode=mode: _keyframe(
                environment_mode=mode,
                environment_view_id=VIEW_ID,
                environment_none_reason=" Shot 未绑定地点视图",
            ),
        )


def _document_with_keyframe_plan(store, location: Location, keyframe: Keyframe):
    document = store.read()
    shot_view_id = location.views[0].id if location.views else None
    scene = _scene(location_id=location.id, shots=(_shot(shot_view_id),))
    end = _keyframe(
        KEYFRAME_END_ID,
        predecessor_keyframe_id=keyframe.id,
        prompt_text="静态尾帧。",
    )
    plan = KeyframePlan(
        1,
        (keyframe, end),
        (SegmentKeyframes(SEGMENT_ID, keyframe.id, end.id),),
    )
    script = DirectorScript(1, document.revision, 1, (scene,), (scene,))
    return replace(
        document,
        status=StructuredDirectorStatus.REVIEWING_KEYFRAMES,
        workspace_layers=WorkspaceLayers(narration_unlocked=True, keyframes_unlocked=True),
        director_script=script,
        location_library=LocationLibrary((location,)),
        keyframe_plan=plan,
    )


def test_keyframe_environment_view_must_exist_in_library(store_factory):
    store = store_factory()
    location = _location(views=(_view(),))
    keyframe = _keyframe(
        environment_mode=KeyframeEnvironmentMode.EDIT,
        environment_view_id=VIEW_ID,
        environment_none_reason=None,
    )
    _document_with_keyframe_plan(store, location, keyframe)
    with pytest.raises(ValueError, match=re.escape("Keyframe 引用的地点视图不存在。")):
        _document_with_keyframe_plan(store, _location(), keyframe)


# ---------------------------------------------------------------------------
# 编解码
# ---------------------------------------------------------------------------


def _full_library() -> LocationLibrary:
    fixture = LocationFixture(FIXTURE_ID, "壁炉", "砖砌，位于客厅东墙。", azimuth_deg=90.0)
    state = LocationState(STATE_ID, "夜晚", "只开壁灯。")
    relative = _view(
        "b" * 32,
        name="朝壁炉",
        purpose="A/B 对话反打背景。",
        azimuth_deg=None,
        look_at_fixture_id=FIXTURE_ID,
        yaw_offset_deg=-15.0,
        pitch_deg=-5.0,
        hfov_deg=45.0,
        state_id=STATE_ID,
        refine_prompt_text="保持布局，只提高清晰度。",
        selected_asset_id=ASSET_ID,
    )
    absolute = _view(
        reference_view_ids=(relative.id,),
        crop_asset_id="c" * 32,
    )
    location = Location(
        LOCATION_ID,
        "共享客厅",
        LocationKind.INTERIOR,
        description="结构、材质、固定陈设与风格。",
        fixtures=(fixture,),
        key_light=LocationKeyLight("窗外自然光。", azimuth_deg=270.0),
        master=LocationMaster(
            prompt_text="等距柱状全景，无人物。",
            reference_asset_ids=("d" * 32,),
            selected_asset_id=ASSET_ID,
        ),
        calibrated_master_asset_id=ASSET_ID,
        states=(state,),
        views=(relative, absolute),
    )
    return LocationLibrary((location,))


def test_location_codec_roundtrip_is_strict_and_lossless():
    library = _full_library()
    assert _parse_location_library(serialize_location_library(library)) == library


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"untrusted": True}),
        lambda value: value["locations"][0].update({"untrusted": True}),
        lambda value: value["locations"][0]["fixtures"][0].update({"untrusted": True}),
        lambda value: value["locations"][0]["key_light"].update({"untrusted": True}),
        lambda value: value["locations"][0]["master"].update({"untrusted": True}),
        lambda value: value["locations"][0]["states"][0].update({"untrusted": True}),
        lambda value: value["locations"][0]["views"][0].update({"untrusted": True}),
    ],
    ids=["library", "location", "fixture", "key_light", "master", "state", "view"],
)
def test_location_codec_rejects_undeclared_fields(mutate):
    value = serialize_location_library(_full_library())
    mutate(value)
    with pytest.raises(ValueError, match=re.escape("project.json 包含缺失或未声明的字段。")):
        _parse_location_library(value)
