"""地点修改的精确失效（docs/data-model.md「失效规则」）：表格每一行至少一个用例。

夹具在 `_visual_project` 的真实脚本与关键帧计划上，用 `replace` 建立已选主图、标定、四个视图、
已选 Keyframe、Segment 视频/超分和最终装配，再直接调用与写入、影响预览共用的纯函数 mutation。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from uuid import uuid4

import pytest
from test_director_commands import _visual_project

from core.director_commands import (
    LocationMasterSelection,
    LocationViewSelection,
    parse_location_operations_patch,
)
from core.structured_director import Asset
from core.structured_director.location_mutations import (
    apply_location_operations,
    select_location_master,
    select_location_view,
)
from core.structured_director.models import (
    FinalAssemblyClip,
    FinalAssemblyPlan,
    GenerationOperation,
    KeyframeEnvironmentMode,
    Location,
    LocationFixture,
    LocationKeyLight,
    LocationKind,
    LocationLibrary,
    LocationMaster,
    LocationState,
    LocationView,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from core.structured_director.repair_mutations import _repair_invalidated_items

LOCATION = "10" * 16
STREET = "11" * 16
F_FIREPLACE = "12" * 16
F_WINDOW = "13" * 16
S_NIGHT = "14" * 16
VA = "15" * 16  # 绝对方位，有裁切
VB = "16" * 16  # 朝向壁炉，有裁切
VC = "17" * 16  # 夜晚状态，参考 VA
VD = "18" * 16  # 无人使用
VX = "19" * 16  # 另一地点
MASTER = "20" * 16
MASTER_NEW = "21" * 16
STREET_MASTER = "22" * 16
CROP = "23" * 16
IMG_A, IMG_B, IMG_C, IMG_D, IMG_X, IMG_NEW = (
    "24" * 16,
    "25" * 16,
    "26" * 16,
    "27" * 16,
    "28" * 16,
    "29" * 16,
)
KEY_IMG = "2a" * 16
VIDEO = "2b" * 16
UPSCALE = "2c" * 16
SCENE_ZH = "2d" * 16
SCENE_EN = "2e" * 16


@dataclass(frozen=True)
class Rig:
    document: StructuredDirectorDocument
    scene_id: str
    shot_ids: tuple[str, str]
    segment_ids: tuple[str, str]
    # (seg1 首, seg1 尾, seg2 首, seg2 尾)
    frame_ids: tuple[str, str, str, str]


def _image(asset_id: str) -> Asset:
    return Asset(asset_id, "image/png", 12, asset_id * 2, f"assets/images/library/{asset_id}.png")


def _candidate(kind: ReferenceGenerationKind, target_id: str, asset_id: str):
    """目标的成功候选：候选选择只接受这样的 Generation 产物。"""
    return ReferenceGeneration(
        id=uuid4().hex,
        kind=kind,
        operation=GenerationOperation.GENERATE,
        target_id=target_id,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        message="完成",
        prompt_text="候选",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id="test.image",
        plugin_version=1,
        external_id=asset_id,
        output_asset_id=asset_id,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
    )


def _video(asset_id: str) -> Asset:
    return Asset(
        asset_id, "video/mp4", 24, asset_id * 2, f"assets/videos/segments/{asset_id}.mp4", 4.0
    )


@pytest.fixture
def rig(tmp_path) -> Rig:
    _store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    script = document.director_script
    scene = script.scenes[0]
    shot1, shot2 = scene.shots
    plan = document.keyframe_plan
    b1, b2 = plan.segments
    frames = (b1.start_keyframe_id, b1.end_keyframe_id, b2.start_keyframe_id, b2.end_keyframe_id)
    views_by_frame = {frames[0]: VA, frames[2]: VB, frames[3]: VX}
    living = Location(
        LOCATION,
        "客厅",
        LocationKind.INTERIOR,
        description="木地板、白墙。",
        fixtures=(
            LocationFixture(F_FIREPLACE, "壁炉", "石砌壁炉", 10.0),
            LocationFixture(F_WINDOW, "窗", "落地窗", 200.0),
        ),
        key_light=LocationKeyLight("左侧窗光", 270.0),
        master=LocationMaster("客厅全景。", (), MASTER),
        calibrated_master_asset_id=MASTER,
        states=(LocationState(S_NIGHT, "夜晚", "只有壁炉火光。"),),
        views=(
            LocationView(
                VA,
                "正打",
                "人眼高中景",
                azimuth_deg=0.0,
                crop_asset_id=CROP,
                selected_asset_id=IMG_A,
            ),
            LocationView(
                VB,
                "壁炉",
                "朝壁炉中景",
                look_at_fixture_id=F_FIREPLACE,
                yaw_offset_deg=0.0,
                crop_asset_id=CROP,
                selected_asset_id=IMG_B,
            ),
            LocationView(
                VC,
                "夜景",
                "夜晚侧向",
                azimuth_deg=90.0,
                state_id=S_NIGHT,
                reference_view_ids=(VA,),
                selected_asset_id=IMG_C,
            ),
            LocationView(VD, "反打", "背面", azimuth_deg=180.0, selected_asset_id=IMG_D),
        ),
    )
    street = Location(
        STREET,
        "街道",
        LocationKind.EXTERIOR,
        master=LocationMaster("街道。", (), STREET_MASTER),
        views=(LocationView(VX, "街口", "远景", azimuth_deg=0.0, selected_asset_id=IMG_X),),
    )
    bound = replace(
        scene,
        location_id=LOCATION,
        shots=(replace(shot1, view_id=VA), replace(shot2, view_id=VD)),
    )
    document = replace(
        document,
        revision=document.revision + 1,
        assets=(
            *document.assets,
            *map(
                _image,
                (MASTER, MASTER_NEW, STREET_MASTER, CROP, IMG_A, IMG_B, IMG_C, IMG_D, IMG_X)
                + (IMG_NEW, KEY_IMG),
            ),
            *map(_video, (VIDEO, UPSCALE, SCENE_ZH, SCENE_EN)),
        ),
        location_library=LocationLibrary((living, street)),
        generations=(
            *document.generations,
            _candidate(ReferenceGenerationKind.LOCATION_MASTER_IMAGE, LOCATION, MASTER_NEW),
            _candidate(ReferenceGenerationKind.LOCATION_VIEW_IMAGE, VA, IMG_NEW),
        ),
        director_script=replace(
            script,
            scenes=(bound,),
            production_baseline_scenes=(bound,),
        ),
        keyframe_plan=replace(
            plan,
            segments=tuple(
                replace(item, start_enabled=True, end_enabled=True) for item in plan.segments
            ),
            keyframes=tuple(
                replace(
                    frame,
                    selected_asset_id=KEY_IMG,
                    environment_mode=KeyframeEnvironmentMode.EDIT,
                    environment_view_id=views_by_frame[frame.id],
                    environment_none_reason=None,
                )
                if frame.id in views_by_frame
                else replace(frame, selected_asset_id=KEY_IMG)
                for frame in plan.keyframes
            ),
        ),
        video_plan=replace(
            document.video_plan,
            segments=tuple(
                replace(item, selected_asset_id=VIDEO, upscaled_asset_id=UPSCALE)
                for item in document.video_plan.segments
            ),
        ),
        workspace_layers=replace(document.workspace_layers, final_assembly_unlocked=True),
        final_assembly=FinalAssemblyPlan(
            script.revision, (FinalAssemblyClip(scene.id, SCENE_ZH, SCENE_EN, None),)
        ),
    )
    return Rig(
        document,
        scene.id,
        (shot1.id, shot2.id),
        (b1.segment_id, b2.segment_id),
        frames,
    )


def _ops(rig: Rig, *operations, locations=(LOCATION,), scenes=(), shots=()):
    return apply_location_operations(
        rig.document,
        parse_location_operations_patch(
            {
                "scope": {
                    "location_ids": list(locations),
                    "scene_ids": list(scenes),
                    "shot_ids": list(shots),
                },
                "operations": list(operations),
            }
        ),
    ).document


def _view(document, view_id) -> LocationView:
    return document.location_library.view_owner(view_id)[1]


def _location(document, location_id) -> Location:
    return document.location_library.location(location_id)


def _frame_selection(document, frame_id):
    return next(f for f in document.keyframe_plan.keyframes if f.id == frame_id).selected_asset_id


def _video_selection(document, segment_id):
    item = next(i for i in document.video_plan.segments if i.segment_id == segment_id)
    return item.selected_asset_id, item.upscaled_asset_id


def _assert_history_kept(before, after):
    assert after.assets == before.assets
    assert after.generations == before.generations


def test_rename_purpose_and_text_fields_invalidate_nothing(rig):
    after = _ops(
        rig,
        {
            "op": "update_location",
            "location_id": LOCATION,
            "fields": {
                "name": "大客厅",
                "description": "木地板、白墙、壁画。",
                "master_prompt_text": "新的客厅全景计划。",
                "key_light": {"description": "左侧大窗光", "azimuth_deg": 270.0},
            },
        },
        {"op": "update_view", "view_id": VA, "fields": {"name": "正打A", "purpose": "近景"}},
        {
            "op": "upsert_fixture",
            "location_id": LOCATION,
            "fixture": F_FIREPLACE,
            "name": "大壁炉",
            "description": "新描述",
            "azimuth_deg": 10.0,
        },
        {
            "op": "upsert_state",
            "location_id": LOCATION,
            "state": S_NIGHT,
            "name": "深夜",
            "description": "只有壁炉火光。",
        },
    )
    assert after.revision == rig.document.revision + 1
    assert _location(after, LOCATION).name == "大客厅"
    assert _view(after, VA).name == "正打A"
    assert _repair_invalidated_items(rig.document, after) == ()
    assert after.keyframe_plan == rig.document.keyframe_plan
    assert after.video_plan == rig.document.video_plan
    assert after.final_assembly == rig.document.final_assembly
    assert _location(after, LOCATION).calibrated


def test_master_reselect_clears_calibration_all_views_and_downstream(rig):
    after = select_location_master(
        rig.document, LocationMasterSelection(LOCATION, MASTER_NEW)
    ).document
    living = _location(after, LOCATION)
    assert living.master.selected_asset_id == MASTER_NEW
    assert living.calibrated_master_asset_id is None
    assert all(
        view.crop_asset_id is None and view.selected_asset_id is None for view in living.views
    )
    # 另一地点不受影响。
    assert _location(after, STREET) == _location(rig.document, STREET)
    for frame_id in rig.frame_ids:
        assert _frame_selection(after, frame_id) is None
    for segment_id in rig.segment_ids:
        assert _video_selection(after, segment_id) == (None, None)
    assert after.final_assembly is None
    invalidated = set(_repair_invalidated_items(rig.document, after))
    assert {
        f"location_master_selection:{LOCATION}",
        f"location_calibration:{LOCATION}",
        f"location_view_crop:{VA}",
        f"location_view_selection:{VD}",
        "final_assembly",
    } <= invalidated
    _assert_history_kept(rig.document, after)


def test_master_clear_selection_is_a_master_change(rig):
    after = _ops(rig, {"op": "clear_master_selection", "location_id": LOCATION})
    assert _location(after, LOCATION).master.selected_asset_id is None
    assert _location(after, LOCATION).calibrated_master_asset_id is None
    assert _view(after, VD).selected_asset_id is None
    assert _frame_selection(after, rig.frame_ids[0]) is None


def test_kind_change_is_a_master_change(rig):
    after = _ops(
        rig, {"op": "update_location", "location_id": LOCATION, "fields": {"kind": "exterior"}}
    )
    living = _location(after, LOCATION)
    assert living.kind is LocationKind.EXTERIOR
    assert living.calibrated_master_asset_id is None
    assert all(
        view.crop_asset_id is None and view.selected_asset_id is None for view in living.views
    )


def test_calibration_change_invalidates_only_views_looking_at_moved_fixture(rig):
    after = _ops(
        rig,
        {
            "op": "calibrate",
            "location_id": LOCATION,
            "fixture_azimuths": {F_FIREPLACE: 30.0, F_WINDOW: 200.0},
            "key_light_azimuth_deg": 260.0,
        },
    )
    assert _view(after, VB).crop_asset_id is None
    assert _view(after, VB).selected_asset_id is None
    for view_id in (VA, VC, VD):
        assert _view(after, view_id) == _view(rig.document, view_id)
    seg1, seg2 = rig.segment_ids
    k1s, k1e, k2s, k2e = rig.frame_ids
    assert _frame_selection(after, k1s) == _frame_selection(after, k1e) == KEY_IMG
    # 首帧使用 VB，尾帧依赖首帧。
    assert _frame_selection(after, k2s) is None and _frame_selection(after, k2e) is None
    assert _video_selection(after, seg1) == (VIDEO, UPSCALE)
    assert _video_selection(after, seg2) == (None, None)
    assert after.final_assembly is None
    assert _location(after, LOCATION).calibrated


def test_key_light_azimuth_only_calibration_invalidates_nothing(rig):
    after = _ops(
        rig,
        {
            "op": "calibrate",
            "location_id": LOCATION,
            "fixture_azimuths": {},
            "key_light_azimuth_deg": 250.0,
        },
    )
    assert _location(after, LOCATION).key_light.azimuth_deg == 250.0
    assert _repair_invalidated_items(rig.document, after) == ()


def test_view_geometry_change_clears_crop_dependents_and_downstream(rig):
    after = _ops(rig, {"op": "update_view", "view_id": VA, "fields": {"pitch_deg": 10.0}})
    assert _view(after, VA).crop_asset_id is None and _view(after, VA).selected_asset_id is None
    # VC 参考 VA：只清选择。
    assert _view(after, VC).selected_asset_id is None
    assert _view(after, VB) == _view(rig.document, VB)
    k1s, k1e, k2s, _k2e = rig.frame_ids
    assert _frame_selection(after, k1s) is None and _frame_selection(after, k1e) is None
    assert _frame_selection(after, k2s) == KEY_IMG
    seg1, seg2 = rig.segment_ids
    assert _video_selection(after, seg1) == (None, None)
    assert _video_selection(after, seg2) == (VIDEO, UPSCALE)
    _assert_history_kept(rig.document, after)


def test_refine_plan_change_keeps_crop_and_clears_selection(rig):
    after = _ops(
        rig, {"op": "update_view", "view_id": VA, "fields": {"refine_prompt_text": "补足细节。"}}
    )
    assert _view(after, VA).crop_asset_id == CROP
    assert _view(after, VA).selected_asset_id is None
    assert _view(after, VC).selected_asset_id is None
    assert _frame_selection(after, rig.frame_ids[0]) is None


def test_state_description_change_invalidates_views_in_that_state(rig):
    after = _ops(
        rig,
        {
            "op": "upsert_state",
            "location_id": LOCATION,
            "state": S_NIGHT,
            "name": "夜晚",
            "description": "壁炉熄灭，只剩月光。",
        },
    )
    assert _view(after, VC).selected_asset_id is None
    assert _view(after, VA) == _view(rig.document, VA)
    assert after.keyframe_plan == rig.document.keyframe_plan


def test_view_reselect_propagates_to_reference_dependents_and_keyframes(rig):
    after = select_location_view(rig.document, LocationViewSelection(VA, IMG_NEW)).document
    assert _view(after, VA).selected_asset_id == IMG_NEW
    assert _view(after, VA).crop_asset_id == CROP
    assert _view(after, VC).selected_asset_id is None
    assert _frame_selection(after, rig.frame_ids[0]) is None
    assert _frame_selection(after, rig.frame_ids[2]) == KEY_IMG


def test_clear_unused_view_selection_touches_no_keyframe(rig):
    after = _ops(rig, {"op": "clear_view_selection", "view_id": VD})
    assert _view(after, VD).selected_asset_id is None
    assert after.keyframe_plan == rig.document.keyframe_plan
    assert after.final_assembly == rig.document.final_assembly


def test_shot_and_scene_rebinding_never_rewrites_keyframes(rig):
    shot1, shot2 = rig.shot_ids
    rebound = _ops(
        rig,
        {"op": "bind_shot", "shot_id": shot2, "view_id": VB},
        locations=(),
        shots=(shot2,),
    )
    assert rebound.director_script.scenes[0].shots[1].view_id == VB
    assert rebound.director_script.production_baseline_scenes[0].shots[1].view_id == VB
    assert rebound.keyframe_plan == rig.document.keyframe_plan
    assert _repair_invalidated_items(rig.document, rebound) == ()

    relocated = _ops(
        rig,
        {"op": "bind_scene", "scene_id": rig.scene_id, "location_id": STREET, "state_id": None},
        locations=(),
        scenes=(rig.scene_id,),
    )
    scene = relocated.director_script.scenes[0]
    assert scene.location_id == STREET
    assert all(shot.view_id is None for shot in scene.shots)
    baseline = relocated.director_script.production_baseline_scenes[0]
    assert baseline.location_id == STREET and all(shot.view_id is None for shot in baseline.shots)
    # D4：已规划 Keyframe 仍指向原视图，选择保留。
    assert relocated.keyframe_plan == rig.document.keyframe_plan
    assert relocated.video_plan == rig.document.video_plan


def test_delete_view_rejects_hard_references_and_clears_soft_shot(rig):
    # 被 Keyframe 与参考视图硬引用：拒绝；只被 Shot 软引用不再进入引用者列表。
    with pytest.raises(ValueError, match="不能删除视图「正打」") as caught:
        _ops(rig, {"op": "delete_view", "view_id": VA})
    message = str(caught.value)
    assert rig.frame_ids[0] in message and VC in message
    assert rig.shot_ids[0] not in message
    # 反打只被 Shot 软引用：允许删除，并清空当前脚本与生产基线的绑定。
    after = _ops(rig, {"op": "delete_view", "view_id": VD})
    assert _location(after, LOCATION).view(VD) is None
    scene = after.director_script.scenes[0]
    assert scene.shots[0].view_id == VA and scene.shots[1].view_id is None
    baseline = after.director_script.production_baseline_scenes[0]
    assert baseline.shots[0].view_id == VA and baseline.shots[1].view_id is None
    assert after.keyframe_plan == rig.document.keyframe_plan
    # 只删除视图本身并清空 Shot 建议，不产生 Keyframe / 视频 / 装配级联。
    assert all(
        not item.startswith(("keyframe", "video", "final"))
        for item in _repair_invalidated_items(rig.document, after)
    )


def test_delete_location_rejects_scene_binding(rig):
    with pytest.raises(ValueError, match="不能删除地点「客厅」") as caught:
        _ops(rig, {"op": "delete_location", "location_id": LOCATION})
    assert rig.scene_id in str(caught.value)


def test_delete_location_clears_soft_shot_references_in_script_and_baseline(rig):
    # Scene 不再绑定该地点时地点才可删除；基线中同 ID 的 Shot 软引用也必须清空。
    script = rig.document.director_script
    scene = script.scenes[0]
    unbound = replace(
        scene,
        location_id=None,
        state_id=None,
        shots=tuple(replace(shot, view_id=None) for shot in scene.shots),
    )
    plan = replace(
        rig.document.keyframe_plan,
        keyframes=tuple(
            replace(
                frame,
                environment_mode=KeyframeEnvironmentMode.NONE,
                environment_view_id=None,
                environment_none_reason=None,
            )
            if frame.environment_view_id in {VA, VB}
            else frame
            for frame in rig.document.keyframe_plan.keyframes
        ),
    )
    document = replace(
        rig.document,
        director_script=replace(script, scenes=(unbound,)),
        keyframe_plan=plan,
    )
    after = apply_location_operations(
        document,
        parse_location_operations_patch(
            {
                "scope": {"location_ids": [LOCATION], "scene_ids": [], "shot_ids": []},
                "operations": [{"op": "delete_location", "location_id": LOCATION}],
            }
        ),
    ).document
    assert _location(after, LOCATION) is None
    baseline = after.director_script.production_baseline_scenes[0]
    assert baseline.location_id is None
    assert all(shot.view_id is None for shot in baseline.shots)
    assert all(shot.view_id is None for shot in after.director_script.scenes[0].shots)


def _running(target_id: str) -> ReferenceGeneration:
    return ReferenceGeneration(
        id="3f" * 16,
        kind=ReferenceGenerationKind.KEYFRAME_IMAGE,
        operation=GenerationOperation.EDIT,
        target_id=target_id,
        phase=ReferenceGenerationPhase.RUNNING,
        progress=0.5,
        message="生成中",
        prompt_text="首帧。",
        input_asset_ids=(IMG_A,),
        sample_text=None,
        seed=1,
        plugin_id="test.image",
        plugin_version=1,
        external_id="provider-1",
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
    )


@pytest.mark.parametrize(
    "phase", [ReferenceGenerationPhase.RUNNING, ReferenceGenerationPhase.SUBMISSION_UNCERTAIN]
)
def test_active_or_uncertain_user_task_rejects_conflicting_change(rig, phase):
    generation = _running(rig.frame_ids[0])
    if phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN:
        # 提交结果不确定：还没有 Provider handle。
        generation = replace(
            generation, phase=phase, external_id=None, plugin_id=None, plugin_version=None
        )
    busy = replace(rig, document=replace(rig.document, generations=(generation,)))
    with pytest.raises(ValueError, match="进行中或结果不确定"):
        _ops(busy, {"op": "update_view", "view_id": VA, "fields": {"hfov_deg": 70.0}})
    # 不影响该 Keyframe 的修改仍可执行。
    renamed = _ops(busy, {"op": "update_view", "view_id": VA, "fields": {"name": "新名"}})
    assert _view(renamed, VA).name == "新名"
    unrelated = _ops(busy, {"op": "update_view", "view_id": VD, "fields": {"hfov_deg": 70.0}})
    assert _view(unrelated, VD).hfov_deg == 70.0


def test_view_generation_in_progress_blocks_its_own_invalidation(rig):
    generation = replace(_running(VC), kind=ReferenceGenerationKind.LOCATION_VIEW_IMAGE)
    busy = replace(rig, document=replace(rig.document, generations=(generation,)))
    # VA 失效会传给参考它的 VC。
    with pytest.raises(ValueError, match="进行中或结果不确定"):
        _ops(busy, {"op": "update_view", "view_id": VA, "fields": {"refine_prompt_text": "x"}})
