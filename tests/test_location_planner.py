"""地点规划能力：项目级工作集、增补式 proposal 的编解码与拒绝、局部键一次落库，
以及复用地点失效规则。"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest
from test_director_commands import _visual_project
from test_external_script_proposals import agent, http, ready
from test_location_invalidation import (
    LOCATION,
    STREET,
    VA,
    VC,
    VD,
    VX,
    _frame_selection,
    _view,
    rig,  # noqa: F401 - pytest fixture
)

from core.director_commands import DirectorCommand
from core.director_proposals.location_codec import (
    compile_location_proposal,
    output_schema,
    parse_location_plan,
)
from core.director_proposals.schema_gen import ProposalError
from core.structured_director.location_mutations import apply_location_operations
from core.structured_director.models import DirectorRunKind, DirectorRunStatus
from core.structured_director.planning_inputs import location_inputs
from core.structured_director.reads.professional_worksets import workset_read


def _view_item(key: str, name: str, azimuth: float, **fields) -> dict:
    return {
        "key": key,
        "name": name,
        "purpose": f"{name}背景",
        "azimuth_deg": azimuth,
        "look_at_fixture_id": None,
        "yaw_offset_deg": None,
        "pitch_deg": 0,
        "hfov_deg": 65,
        "state_id": None,
        "refine_prompt_text": "",
        "reference_view_ids": [],
        **fields,
    }


def _plan(document) -> dict:
    """新建一个室内地点（陈设、状态、互相参考的视图），并把第一个 Scene 与两个 Shot 绑上。"""
    scene = document.director_script.scenes[0]
    first, second = scene.shots
    return {
        "locations": [
            {
                "key": "living",
                "name": "林家客厅",
                "kind": "interior",
                "description": "木地板、白墙、低矮吊顶。",
                "key_light": {"description": "西侧落地窗的暖色夕照", "azimuth_deg": 270},
                "master_prompt_text": "温暖克制的旧式客厅。",
                "fixtures": [
                    {"key": "fireplace", "name": "壁炉", "description": "石砌", "azimuth_deg": 0},
                    {"key": "door", "name": "门", "description": "木门", "azimuth_deg": 180},
                ],
                "states": [{"key": "night", "name": "夜晚", "description": "只有壁炉火光。"}],
                # 反打参考正打且写在前面：Core 必须先落库被参考的视图。
                "views": [
                    _view_item("reverse", "反打", 180, reference_view_ids=["front"]),
                    _view_item("front", "正打", 0),
                    _view_item("front-night", "夜晚正打", 0, state_id="night"),
                ],
            }
        ],
        "scene_bindings": [{"scene_id": scene.id, "location_id": "living", "state_id": "night"}],
        "shot_bindings": [
            {"shot_id": first.id, "view_id": "front"},
            {"shot_id": second.id, "view_id": "reverse"},
        ],
    }


def _parse(value: dict):
    return parse_location_plan(json.dumps(value, ensure_ascii=False))


def _compile(document, value: dict):
    scenes, existing = location_inputs(document)
    return compile_location_proposal(_parse(value), scenes, existing)


@pytest.fixture
def project(tmp_path):
    store, service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    return store, service, document


# --- 工作集 ---


def test_workset_has_full_script_library_status_and_project_scope(project):
    _store, _service, document = project
    scope = {"project_id": document.project_id}
    result = workset_read(document, {"capability": "location", "scope": scope})
    facts = result["core_facts"]
    assert facts["director_plan_markdown"] == document.director_plan_markdown
    assert facts["aspect_ratio"] == document.aspect_ratio.value
    assert set(facts["image_prompt"]) == {"recipes", "plugin_skills"}
    assert facts["location_library"] == []
    assert result["output_schema"] == output_schema()
    script_scene = document.director_script.scenes[0]
    scene = facts["scenes"][0]
    assert (scene["id"], scene["location_id"], scene["state_id"]) == (script_scene.id, None, None)
    for shot, source in zip(scene["shots"], script_scene.shots, strict=True):
        assert shot["composition"] == source.composition
        assert shot["camera_movement"] == source.camera_movement
        assert shot["action"] == source.action
        names = {item.id: item.name for item in document.reference_library.characters}
        assert shot["visible_characters"] == [
            {"id": item, "name": names[item]} for item in source.visible_character_ids
        ]
    for bad in (
        {"capability": "location", "scope": {"scene_ids": [script_scene.id]}},
        {"capability": "location", "scope": scope, "target_ids": [script_scene.id]},
    ):
        with pytest.raises(ValueError):
            workset_read(document, bad)


def test_request_before_script_is_rejected_without_writes(tmp_path):
    async def run():
        store, service = await ready(tmp_path)
        document = store.read()
        scope = {"capability": "location", "scope": {"project_id": document.project_id}}
        with pytest.raises(ValueError, match="导演脚本尚未建立"):
            workset_read(document, scope)
        request = DirectorCommand(
            "location.request_proposal",
            document.revision,
            "early",
            {"raw_user_instruction": "规划地点"},
        )
        before = store.path.read_bytes()
        response = await http(service, agent(document, request), request)
        assert response.status == 409
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_workset_reports_selection_and_calibration_state(rig):  # noqa: F811
    result = workset_read(
        rig.document,
        {"capability": "location", "scope": {"project_id": rig.document.project_id}},
    )
    living, street = result["core_facts"]["location_library"]
    assert (living["id"], living["master_selected"], living["calibrated"]) == (
        LOCATION,
        True,
        True,
    )
    assert {item["id"]: (item["has_crop"], item["has_selected_image"]) for item in living["views"]}[
        VC
    ] == (False, True)
    assert (street["id"], street["calibrated"]) == (STREET, False)


# --- 编解码与拒绝 ---


def test_schema_is_strict_and_codec_rejects_structural_errors(project):
    _store, _service, document = project
    good = _plan(document)
    assert _parse(good).locations[0].key == "living"

    def mutated(change) -> dict:
        value = copy.deepcopy(good)
        change(value)
        return value

    cases = [
        (mutated(lambda v: v.update(extra=True)), "extra"),
        (mutated(lambda v: v["locations"][0].pop("key")), "id 或 key"),
        (mutated(lambda v: v["locations"][0].update(id="a" * 32)), "id 或 key"),
        (mutated(lambda v: v["locations"][0].update(key="a" * 32)), "不能是 32 位 ID"),
        (mutated(lambda v: v["locations"][0]["views"][2].update(key="night")), "唯一"),
        (
            mutated(lambda v: v["locations"][0]["views"][0].update(reference_view_ids=["ghost"])),
            "不是同一地点",
        ),
        (
            mutated(lambda v: v["locations"][0]["views"][0].update(look_at_fixture_id="ghost")),
            "不是同一地点",
        ),
        (mutated(lambda v: v["scene_bindings"][0].update(location_id="ghost")), "未新建的地点"),
        (mutated(lambda v: v["scene_bindings"][0].update(state_id="ghost")), "不属于所绑定"),
        (mutated(lambda v: v["shot_bindings"][0].update(view_id="ghost")), "未新建的视图"),
        (
            mutated(lambda v: v["scene_bindings"][0].update(location_id=None)),
            "没有绑定地点时不能指定",
        ),
        (mutated(lambda v: v["shot_bindings"].append(dict(v["shot_bindings"][0]))), "只能绑定一次"),
        ({"locations": [], "scene_bindings": [], "shot_bindings": []}, "不能为空"),
    ]
    for value, message in cases:
        with pytest.raises(ProposalError, match=message) as raised:
            _parse(value)
        assert raised.value.domain == "location"


def test_compile_rejects_targets_outside_current_facts(project):
    _store, _service, document = project
    good = _plan(document)
    with_location = apply_location_operations(document, _compile(document, good)).document
    living = with_location.location_library.locations[0]
    front = next(view for view in living.views if view.name == "正打")
    second = with_location.director_script.scenes[0].shots[1]

    def other_location(value):
        value["locations"][0]["key"] = "other"
        value["scene_bindings"] = []
        value["shot_bindings"] = []

    cases = [
        (
            {**good, "scene_bindings": [{**good["scene_bindings"][0], "scene_id": "f" * 32}]},
            "Scene 不存在",
        ),
        ({**good, "shot_bindings": [{"shot_id": "f" * 32, "view_id": None}]}, "Shot 不存在"),
    ]
    for value, message in cases:
        with pytest.raises(ProposalError, match=message):
            _compile(document, value)
    # 已有视图属于另一个地点：Scene 绑定的是新地点，Shot 却指向旧地点的视图。
    second_plan = copy.deepcopy(good)
    other_location(second_plan)
    second_plan["locations"][0]["views"] = [_view_item("lobby", "大堂", 0)]
    second_plan["scene_bindings"] = [
        {
            "scene_id": with_location.director_script.scenes[0].id,
            "location_id": "other",
            "state_id": None,
        }
    ]
    second_plan["shot_bindings"] = [{"shot_id": second.id, "view_id": front.id}]
    with pytest.raises(ProposalError, match="必须属于所在 Scene 绑定的地点"):
        _compile(with_location, second_plan)
    unknown = {"locations": [{**good["locations"][0], "key": None, "id": "f" * 32}]}
    unknown["locations"][0].pop("key")
    with pytest.raises(ProposalError, match="地点不存在"):
        _compile(with_location, {**unknown, "scene_bindings": [], "shot_bindings": []})
    cycle = copy.deepcopy(good)
    cycle["locations"][0]["views"][1]["reference_view_ids"] = ["reverse"]
    with pytest.raises(ProposalError, match="形成环"):
        _compile(document, cycle)


def test_selected_master_keeps_calibrated_azimuths(rig):  # noqa: F811
    living = rig.document.location_library.location(LOCATION)
    fireplace, window = living.fixtures
    item = {
        "id": LOCATION,
        "name": living.name,
        "kind": "interior",
        "description": living.description,
        "key_light": {"description": living.key_light.description, "azimuth_deg": None},
        "master_prompt_text": living.master.prompt_text,
        "fixtures": [
            {"id": fireplace.id, "name": "壁炉", "description": "石砌", "azimuth_deg": None},
        ],
        "states": [],
        "views": [],
    }
    patch = _compile(rig.document, {"locations": [item], "scene_bindings": [], "shot_bindings": []})
    updated = apply_location_operations(rig.document, patch).document.location_library.location(
        LOCATION
    )
    assert updated.fixture(fireplace.id).azimuth_deg == fireplace.azimuth_deg
    assert updated.key_light.azimuth_deg == living.key_light.azimuth_deg
    assert updated.fixture(window.id) == window  # 未列出的陈设不删除、不改动
    moved = copy.deepcopy(item)
    moved["fixtures"][0]["azimuth_deg"] = 40
    with pytest.raises(ProposalError, match="以标定为准"):
        _compile(rig.document, {"locations": [moved], "scene_bindings": [], "shot_bindings": []})
    added = copy.deepcopy(item)
    added["fixtures"] = [{"key": "lamp", "name": "落地灯", "description": "", "azimuth_deg": 90}]
    with pytest.raises(ProposalError, match="以标定为准"):
        _compile(rig.document, {"locations": [added], "scene_bindings": [], "shot_bindings": []})


# --- 失效复用 ---


def test_proposal_changing_existing_view_geometry_invalidates_per_design(rig):  # noqa: F811
    view = _view(rig.document, VA)
    living = rig.document.location_library.location(LOCATION)
    item = {
        "id": LOCATION,
        "name": living.name,
        "kind": "interior",
        "description": living.description,
        "key_light": {"description": living.key_light.description, "azimuth_deg": None},
        "master_prompt_text": living.master.prompt_text,
        "fixtures": [],
        "states": [],
        "views": [
            {
                "id": VA,
                "name": view.name,
                "purpose": view.purpose,
                "azimuth_deg": 30,
                "look_at_fixture_id": None,
                "yaw_offset_deg": None,
                "pitch_deg": view.pitch_deg,
                "hfov_deg": view.hfov_deg,
                "state_id": None,
                "refine_prompt_text": view.refine_prompt_text,
                "reference_view_ids": [],
            }
        ],
    }
    patch = _compile(rig.document, {"locations": [item], "scene_bindings": [], "shot_bindings": []})
    document = apply_location_operations(rig.document, patch).document
    changed = _view(document, VA)
    assert (changed.azimuth_deg, changed.crop_asset_id, changed.selected_asset_id) == (
        30,
        None,
        None,
    )
    assert _view(document, VC).selected_asset_id is None  # 参考 VA 的视图随之失效
    assert _view(document, VD).selected_asset_id is not None  # 无关视图保留
    assert _view(document, VX).selected_asset_id is not None
    assert _frame_selection(document, rig.frame_ids[0]) is None  # 使用 VA 的 Keyframe 失效
    assert len(document.generations) == len(rig.document.generations)  # 历史保留


# --- 生命周期 ---


def test_request_submit_maps_local_keys_and_binds_in_one_write(project):
    store, service, document = project

    async def run():
        request = DirectorCommand(
            "location.request_proposal",
            document.revision,
            "location-request",
            {"raw_user_instruction": "按完整脚本规划地点"},
        )
        caller = agent(document, request)
        started = await http(service, caller, request)
        assert started.status == 200, started.body
        data = started.body["data"]
        assert data["capability"] == "location"
        assert "image_prompt" not in data["core_facts"]
        assert data["proposal_observation"]["phase"] == "awaiting_agent_submission"
        current = store.read()
        assert current.active_director_run.kind is DirectorRunKind.LOCATION_PLAN
        locked = DirectorCommand(
            "location.apply_operations",
            current.revision,
            "locked",
            {
                "scope": {"location_ids": [], "scene_ids": [], "shot_ids": []},
                "operations": [
                    {
                        "op": "create_location",
                        "key": "x",
                        "name": "x",
                        "kind": "interior",
                        "description": "",
                    }
                ],
            },
        )
        assert (await http(service, agent(current, locked), locked)).status != 200
        bad = copy.deepcopy(_plan(current))
        bad["shot_bindings"][0]["view_id"] = "ghost"
        rejected = DirectorCommand(
            "location.submit_proposal",
            current.revision,
            "location-bad",
            {"request_id": data["request_id"], "proposal": bad},
        )
        assert (await http(service, caller, rejected)).status == 400
        assert store.read().revision == current.revision
        submit = DirectorCommand(
            "location.submit_proposal",
            current.revision,
            "location-submit",
            {"request_id": data["request_id"], "proposal": _plan(current)},
        )
        submitted = await http(service, caller, submit)
        assert submitted.status == 200, submitted.body
        return store.read()

    saved = asyncio.run(run())
    assert saved.revision == document.revision + 2
    run_record = next(
        item for item in saved.director_runs if item.kind is DirectorRunKind.LOCATION_PLAN
    )
    assert run_record.status is DirectorRunStatus.COMPLETED
    (living,) = saved.location_library.locations
    assert len(living.id) == 32 and living.name == "林家客厅"
    views = {view.name: view for view in living.views}
    night = living.states[0]
    assert views["反打"].reference_view_ids == (views["正打"].id,)
    assert views["夜晚正打"].state_id == night.id
    assert {item.name: item.azimuth_deg for item in living.fixtures} == {"壁炉": 0, "门": 180}
    assert living.key_light.azimuth_deg == 270
    scene = saved.director_script.scenes[0]
    assert (scene.location_id, scene.state_id) == (living.id, night.id)
    assert [shot.view_id for shot in scene.shots] == [views["正打"].id, views["反打"].id]
    baseline = saved.director_script.production_baseline_scenes[0]
    assert baseline.location_id == living.id


def test_second_proposal_supplements_without_deleting(project):
    store, _service, document = project
    first = apply_location_operations(document, _compile(document, _plan(document))).document
    living = first.location_library.locations[0]
    front = next(view for view in living.views if view.name == "正打")
    supplement = {
        "locations": [
            {
                "id": living.id,
                "name": living.name,
                "kind": "interior",
                "description": living.description,
                "key_light": {"description": living.key_light.description, "azimuth_deg": None},
                "master_prompt_text": living.master.prompt_text,
                "fixtures": [],
                "states": [],
                "views": [_view_item("window", "窗边", 90, reference_view_ids=[front.id])],
            }
        ],
        "scene_bindings": [],
        "shot_bindings": [],
    }
    second = apply_location_operations(first, _compile(first, supplement)).document
    updated = second.location_library.locations[0]
    assert [view.name for view in updated.views] == ["正打", "反打", "夜晚正打", "窗边"]
    assert updated.fixtures == living.fixtures and updated.states == living.states
    assert updated.views[-1].reference_view_ids == (front.id,)
    assert second.director_script.scenes == first.director_script.scenes
