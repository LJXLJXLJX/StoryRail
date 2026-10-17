"""`location.apply_operations` 与人类候选选择：每个操作的成功与拒绝路径、scope、局部 key、
人类/Agent 入口差异、幂等与 HTTP/MCP 翻译。失效细节见 test_location_invalidation.py。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from structured_director_fixtures import add_image_asset
from test_director_commands import _visual_project

from core.application.caller import AccessDenied, Caller, authorize_command
from core.director_commands import (
    DirectorCommand,
    DirectorCommandRegistry,
    InvalidArgumentsError,
    parse_location_operations_patch,
)
from core.structured_director.application_requests import execute_atomic_request
from core.structured_director.errors import RevisionConflictError
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.models import LocationKind, ReferenceGenerationKind
from core.structured_director.reads.impact import preview_command_impact
from integrations.storyrail_mcp.production_tools import MODELS, translate
from scripts.harness.fixtures.candidates import register_image_candidate

UNKNOWN = "f0" * 16


def _view(key: str, location: str = "room", **fields) -> dict:
    view = {"name": "主机位", "purpose": "人眼高中景", "azimuth_deg": 0.0, **fields}
    return {"op": "create_view", "location_id": location, "key": key, "fields": view}


ROOM = {
    "op": "create_location",
    "key": "room",
    "name": "客厅",
    "kind": "interior",
    "description": "木地板、白墙。",
}


def _arguments(*operations, locations=(), scenes=(), shots=()) -> dict:
    return {
        "scope": {
            "location_ids": list(locations),
            "scene_ids": list(scenes),
            "shot_ids": list(shots),
        },
        "operations": list(operations),
    }


class Project:
    """真实 Store + 命令注册表；每次执行都走正式 registry 与 commit pipeline。"""

    def __init__(self, tmp_path) -> None:
        self.store, self.service, document, _ = asyncio.run(_visual_project(str(tmp_path)))
        self.registry = DirectorCommandRegistry(self.store)
        self.scene = document.director_script.scenes[0]

    @property
    def document(self):
        return self.store.read()

    def run(self, name: str, arguments: dict):
        return self.registry.execute(
            DirectorCommand(name, self.document.revision, uuid4().hex, arguments)
        )

    def ops(self, *operations, **scope):
        return self.run("location.apply_operations", _arguments(*operations, **scope))

    def image(self, **size) -> str:
        return add_image_asset(self.store, **size)

    def candidate(self, kind: ReferenceGenerationKind, target_id: str, **size) -> str:
        """一张图片，并登记为目标的成功候选（候选选择只接受这样的 Asset）。"""
        asset_id = self.image(**size)
        register_image_candidate(self.store, kind=kind, target_id=target_id, asset_id=asset_id)
        return asset_id

    def master(self, location_id: str, **size) -> str:
        return self.candidate(ReferenceGenerationKind.LOCATION_MASTER_IMAGE, location_id, **size)

    def view_image(self, view_id: str) -> str:
        return self.candidate(ReferenceGenerationKind.LOCATION_VIEW_IMAGE, view_id)

    def location(self, location_id: str):
        return self.document.location_library.location(location_id)


@pytest.fixture
def project(tmp_path) -> Project:
    return Project(tmp_path)


def _room(project: Project, *extra) -> tuple[str, dict[str, str]]:
    execution = project.ops(
        ROOM,
        {
            "op": "upsert_fixture",
            "location_id": "room",
            "fixture": "fireplace",
            "name": "壁炉",
            "description": "",
            "azimuth_deg": None,
        },
        {
            "op": "upsert_state",
            "location_id": "room",
            "state": "night",
            "name": "夜晚",
            "description": "只有火光。",
        },
        _view("main"),
        _view(
            "fire",
            look_at_fixture_id="fireplace",
            azimuth_deg=None,
            yaw_offset_deg=15.0,
            state_id="night",
            reference_view_ids=["main"],
        ),
        *extra,
    )
    created = execution.data["created_ids"]
    return created["room"], created


# --- 解析 ---


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"scope": {"location_ids": [], "scene_ids": []}, "operations": [ROOM]}, "location scope"),
        (_arguments(), "1 到 100"),
        (_arguments(*([ROOM] * 101)), "1 到 100"),
        (_arguments({**ROOM, "extra": 1}), "未声明字段"),
        (_arguments({"op": "teleport"}), "不支持的 location operation"),
        (_arguments({**ROOM, "key": "a" * 32}), "不能是 32 位 ID"),
        (_arguments({**ROOM, "kind": "cave"}), "interior 或 exterior"),
        (_arguments({"op": "delete_location", "location_id": "room"}), "32 位小写十六进制 ID"),
        (_arguments({"op": "update_location", "location_id": "room", "fields": {}}), "非空 object"),
        (
            _arguments({"op": "update_location", "location_id": "room", "fields": {"views": []}}),
            "未声明字段",
        ),
        (_arguments(_view("v", pitch_deg=float("inf"))), "有限数值角度"),
        (_arguments(_view("v", reference_view_ids=["a", "a"])), "不能重复"),
        (
            _arguments(
                {"op": "create_view", "location_id": "room", "key": "v", "fields": {"name": "n"}}
            ),
            "必须包含 name 与 purpose",
        ),
        (
            _arguments(
                {
                    "op": "calibrate",
                    "location_id": "room",
                    "fixture_azimuths": [],
                    "key_light_azimuth_deg": None,
                }
            ),
            "object",
        ),
        (
            {
                "scope": {"location_ids": ["a" * 32, "a" * 32], "scene_ids": [], "shot_ids": []},
                "operations": [ROOM],
            },
            "不能重复",
        ),
    ],
)
def test_parser_rejects_malformed_arguments(arguments, message):
    with pytest.raises(ValueError, match=message):
        parse_location_operations_patch(arguments)


# --- 地点库编辑：成功路径 ---


def test_create_with_local_keys_persists_and_returns_formal_ids(project):
    before = project.document.revision
    location_id, created = _room(project)
    document = project.document
    assert document.revision == before + 1
    location = document.location_library.location(location_id)
    assert set(created) == {"room", "fireplace", "night", "main", "fire"}
    fire = location.view(created["fire"])
    assert fire.look_at_fixture_id == created["fireplace"]
    assert fire.state_id == created["night"]
    assert fire.reference_view_ids == (created["main"],)
    assert location.kind is LocationKind.INTERIOR


def test_update_location_master_plan_key_light_and_kind(project):
    location_id, _ = _room(project)
    asset_id = project.image()
    project.ops(
        {
            "op": "update_location",
            "location_id": location_id,
            "fields": {
                "name": "大客厅",
                "description": "",
                "key_light": {"description": "左侧窗光", "azimuth_deg": 270.0},
                "master_prompt_text": "全景，无人物。",
                "master_reference_asset_ids": [asset_id],
                "kind": "exterior",
            },
        },
        locations=(location_id,),
    )
    location = project.location(location_id)
    assert (location.name, location.description, location.kind) == (
        "大客厅",
        "",
        LocationKind.EXTERIOR,
    )
    assert location.key_light.azimuth_deg == 270.0
    assert location.master.prompt_text == "全景，无人物。"
    assert location.master.reference_asset_ids == (asset_id,)


def test_upsert_by_id_replaces_and_deletes_unreferenced_items(project):
    location_id, created = _room(project, _view("spare"))
    project.ops(
        {
            "op": "upsert_fixture",
            "location_id": location_id,
            "fixture": created["fireplace"],
            "name": "大壁炉",
            "description": "石砌",
            "azimuth_deg": 12.0,
        },
        {"op": "delete_view", "view_id": created["spare"]},
        locations=(location_id,),
    )
    location = project.location(location_id)
    assert [(item.name, item.azimuth_deg) for item in location.fixtures] == [("大壁炉", 12.0)]
    assert location.view(created["spare"]) is None
    project.ops(
        {
            "op": "update_view",
            "view_id": created["fire"],
            "fields": {
                "look_at_fixture_id": None,
                "yaw_offset_deg": None,
                "azimuth_deg": 45.0,
                "state_id": None,
            },
        },
        {"op": "delete_fixture", "location_id": location_id, "fixture_id": created["fireplace"]},
        {"op": "delete_state", "location_id": location_id, "state_id": created["night"]},
        locations=(location_id,),
    )
    location = project.location(location_id)
    assert location.fixtures == () and location.states == ()
    assert location.view(created["fire"]).azimuth_deg == 45.0


def test_delete_unreferenced_location(project):
    location_id, _ = _room(project)
    project.ops({"op": "delete_location", "location_id": location_id}, locations=(location_id,))
    assert project.document.location_library.locations == ()


def test_calibrate_requires_selected_master_and_records_it(project):
    location_id, created = _room(project)
    calibrate = {
        "op": "calibrate",
        "location_id": location_id,
        "fixture_azimuths": {created["fireplace"]: 90.0},
        "key_light_azimuth_deg": None,
    }
    with pytest.raises(ValueError, match="尚未选择主图"):
        project.ops(calibrate, locations=(location_id,))
    master = project.master(location_id)
    project.run("location.select_master", {"location_id": location_id, "asset_id": master})
    with pytest.raises(ValueError, match="主光描述"):
        project.ops({**calibrate, "key_light_azimuth_deg": 10.0}, locations=(location_id,))
    project.ops(calibrate, locations=(location_id,))
    location = project.location(location_id)
    assert location.calibrated and location.calibrated_master_asset_id == master
    assert location.fixtures[0].azimuth_deg == 90.0


def test_bind_scene_and_shot(project):
    location_id, created = _room(project)
    shot_ids = [shot.id for shot in project.scene.shots]
    project.ops(
        {
            "op": "bind_scene",
            "scene_id": project.scene.id,
            "location_id": location_id,
            "state_id": created["night"],
        },
        {"op": "bind_shot", "shot_id": shot_ids[0], "view_id": created["main"]},
        scenes=(project.scene.id,),
        shots=(shot_ids[0],),
    )
    scene = project.document.director_script.scenes[0]
    assert (scene.location_id, scene.state_id) == (location_id, created["night"])
    assert scene.shots[0].view_id == created["main"] and scene.shots[1].view_id is None
    project.ops(
        {"op": "bind_scene", "scene_id": scene.id, "location_id": None, "state_id": None},
        scenes=(scene.id,),
    )
    scene = project.document.director_script.scenes[0]
    assert scene.location_id is None and all(shot.view_id is None for shot in scene.shots)


def test_create_bind_in_one_patch_with_keys(project):
    shot_id = project.scene.shots[0].id
    created = project.ops(
        ROOM,
        _view("main"),
        {"op": "bind_scene", "scene_id": project.scene.id, "location_id": "room", "state_id": None},
        {"op": "bind_shot", "shot_id": shot_id, "view_id": "main"},
        scenes=(project.scene.id,),
        shots=(shot_id,),
    ).data["created_ids"]
    scene = project.document.director_script.scenes[0]
    assert scene.location_id == created["room"]
    assert scene.shots[0].view_id == created["main"]
    baseline = project.document.director_script.production_baseline_scenes[0]
    assert baseline.shots[0].view_id == created["main"]


def test_clear_selections_and_noop(project):
    location_id, created = _room(project)
    master, view_image = project.master(location_id), project.view_image(created["main"])
    project.run("location.select_master", {"location_id": location_id, "asset_id": master})
    project.run("location.select_view", {"view_id": created["main"], "asset_id": view_image})
    assert project.location(location_id).view(created["main"]).selected_asset_id == view_image
    execution = project.ops(
        {"op": "clear_view_selection", "view_id": created["main"]}, locations=(location_id,)
    )
    assert execution.receipt.status == "succeeded"
    assert f"location_view_selection:{created['main']}" in execution.receipt.invalidated
    project.ops(
        {"op": "clear_master_selection", "location_id": location_id}, locations=(location_id,)
    )
    assert project.location(location_id).master.selected_asset_id is None
    revision = project.document.revision
    noop = project.ops(
        {"op": "clear_master_selection", "location_id": location_id}, locations=(location_id,)
    )
    assert noop.receipt.status == "noop" and project.document.revision == revision


# --- 拒绝路径 ---


def test_scope_must_cover_every_target(project):
    location_id, created = _room(project)
    shot_id = project.scene.shots[0].id
    rejected = [
        ({"op": "update_location", "location_id": location_id, "fields": {"name": "x"}}, {}),
        ({"op": "delete_view", "view_id": created["main"]}, {}),
        ({"op": "clear_view_selection", "view_id": created["main"]}, {}),
        (
            {
                "op": "bind_scene",
                "scene_id": project.scene.id,
                "location_id": location_id,
                "state_id": None,
            },
            {},
        ),
        ({"op": "bind_shot", "shot_id": shot_id, "view_id": None}, {}),
    ]
    for operation, scope in rejected:
        with pytest.raises(ValueError, match="超出 scope"):
            project.ops(operation, **scope)
    for scope, message in (
        ({"locations": (UNKNOWN,)}, "未知地点"),
        ({"scenes": (UNKNOWN,)}, "未知 Scene"),
        ({"shots": (UNKNOWN,)}, "未知 Shot"),
    ):
        with pytest.raises(ValueError, match=message):
            project.ops(ROOM, **scope)


def test_key_resolution_rejects_unknown_reused_and_mismatched_keys(project):
    with pytest.raises(ValueError, match="没有在本 patch 中先创建"):
        project.ops(_view("main", location="nowhere"))
    with pytest.raises(ValueError, match="重复创建"):
        project.ops(ROOM, {**ROOM, "name": "另一个"})
    with pytest.raises(ValueError, match="没有在本 patch 中先创建为陈设"):
        project.ops(
            ROOM, _view("main", look_at_fixture_id="room", azimuth_deg=None, yaw_offset_deg=0.0)
        )
    with pytest.raises(ValueError, match="地点不存在"):
        project.ops(
            {
                "op": "upsert_state",
                "location_id": UNKNOWN,
                "state": "s",
                "name": "n",
                "description": "d",
            },
            locations=(),
        )


def test_bindings_must_stay_inside_scene_location(project):
    location_id, created = _room(project)
    other_id, other = _other(project)
    scene, shot_id = project.scene, project.scene.shots[0].id
    with pytest.raises(ValueError, match="必须属于所绑定的地点"):
        project.ops(
            {
                "op": "bind_scene",
                "scene_id": scene.id,
                "location_id": other_id,
                "state_id": created["night"],
            },
            scenes=(scene.id,),
        )
    with pytest.raises(ValueError, match="所在 Scene 已绑定的地点"):
        project.ops(
            {"op": "bind_shot", "shot_id": shot_id, "view_id": created["main"]}, shots=(shot_id,)
        )
    project.ops(
        {"op": "bind_scene", "scene_id": scene.id, "location_id": location_id, "state_id": None},
        scenes=(scene.id,),
    )
    with pytest.raises(ValueError, match="所在 Scene 已绑定的地点"):
        project.ops(
            {"op": "bind_shot", "shot_id": shot_id, "view_id": other["street_view"]},
            shots=(shot_id,),
        )


def _other(project: Project):
    execution = project.ops(
        {
            "op": "create_location",
            "key": "street",
            "name": "街道",
            "kind": "exterior",
            "description": "",
        },
        _view("street_view", location="street"),
    )
    created = execution.data["created_ids"]
    return created["street"], created


def test_delete_referenced_items_lists_referrers(project):
    location_id, created = _room(project)
    scene = project.scene
    with pytest.raises(ValueError, match="不能删除陈设「壁炉」：仍被 视图「主机位」"):
        project.ops(
            {
                "op": "delete_fixture",
                "location_id": location_id,
                "fixture_id": created["fireplace"],
            },
            locations=(location_id,),
        )
    with pytest.raises(
        ValueError, match=f"不能删除视图「主机位」：仍被 视图「主机位」\\({created['fire']}\\)"
    ):
        project.ops({"op": "delete_view", "view_id": created["main"]}, locations=(location_id,))
    project.ops(
        {
            "op": "bind_scene",
            "scene_id": scene.id,
            "location_id": location_id,
            "state_id": created["night"],
        },
        scenes=(scene.id,),
    )
    with pytest.raises(ValueError, match=f"Scene「{scene.title}」\\({scene.id}\\)"):
        project.ops(
            {"op": "delete_state", "location_id": location_id, "state_id": created["night"]},
            locations=(location_id,),
        )
    with pytest.raises(ValueError, match="不能删除地点「客厅」"):
        project.ops({"op": "delete_location", "location_id": location_id}, locations=(location_id,))
    # 同一 patch 先解除引用再删除可以成功。
    project.ops(
        {"op": "bind_scene", "scene_id": scene.id, "location_id": None, "state_id": None},
        {"op": "delete_location", "location_id": location_id},
        locations=(location_id,),
        scenes=(scene.id,),
    )
    assert project.location(location_id) is None


def test_model_constraints_reject_invalid_plans(project):
    location_id, created = _room(project)
    other_id, other = _other(project)
    with pytest.raises(ValueError, match="pitch_deg"):
        project.ops(
            {"op": "update_view", "view_id": created["main"], "fields": {"pitch_deg": 80.0}},
            locations=(location_id,),
        )
    with pytest.raises(ValueError, match="二选一"):
        project.ops(
            {"op": "update_view", "view_id": created["main"], "fields": {"yaw_offset_deg": 5.0}},
            locations=(location_id,),
        )
    with pytest.raises(ValueError, match="只能参考同一地点"):
        project.ops(
            {
                "op": "update_view",
                "view_id": created["main"],
                "fields": {"reference_view_ids": [other["street_view"]]},
            },
            locations=(location_id,),
        )
    with pytest.raises(ValueError, match="形成环"):
        project.ops(
            {
                "op": "update_view",
                "view_id": created["main"],
                "fields": {"reference_view_ids": [created["fire"]]},
            },
            locations=(location_id,),
        )
    with pytest.raises(ValueError, match="最多 10 个状态"):
        project.ops(
            *(
                {
                    "op": "upsert_state",
                    "location_id": location_id,
                    "state": f"s{i}",
                    "name": "n",
                    "description": "d",
                }
                for i in range(10)
            ),
            locations=(location_id,),
        )
    del other_id


def test_select_rejects_non_image_assets_and_unknown_targets(project):
    location_id, created = _room(project)
    with pytest.raises(ValueError, match="主图候选"):
        project.run("location.select_master", {"location_id": location_id, "asset_id": UNKNOWN})
    with pytest.raises(ValueError, match="地点视图不存在"):
        project.run("location.select_view", {"view_id": UNKNOWN, "asset_id": project.image()})
    with pytest.raises(InvalidArgumentsError):
        project.run("location.select_view", {"view_id": created["main"]})


def test_writes_are_rejected_while_director_agent_works(project):
    location_id, _ = _room(project)
    project.store.begin_keyframe_plan(expected_revision=project.document.revision)
    with pytest.raises(ValueError, match="Director Agent 正在工作"):
        project.ops(
            {"op": "update_location", "location_id": location_id, "fields": {"name": "x"}},
            locations=(location_id,),
        )


# --- 人类与 Agent 入口 ---


def _caller(role: str, capabilities: set[str], project_id: str) -> Caller:
    return Caller(
        f"{role}-1",
        role,
        frozenset({project_id}),
        frozenset(capabilities),
        int(time.time()) + 3600,
        mutations_enabled=True,
    )


def test_agent_may_edit_but_never_select_candidates(project):
    project_id = project.document.project_id
    agent = _caller("agent", {"project.read", "project.mutate", "project.execute"}, project_id)
    human = _caller("human", {"project.read", "human.write"}, project_id)
    edit = {"name": "location.apply_operations", "arguments": _arguments(ROOM)}
    authorize_command(agent, project_id, edit)
    for name in ("location.select_master", "location.select_view"):
        command = {"name": name, "arguments": {}}
        with pytest.raises(AccessDenied):
            authorize_command(agent, project_id, command)
        authorize_command(human, project_id, command)
    assert "select" not in json.dumps(
        MODELS["edit_locations"].model_json_schema(), ensure_ascii=False
    ).replace("selection", "")


def test_idempotent_replay_checks_key_scope_and_request_digest(project):
    project_id = project.document.project_id
    agent = _caller("agent", {"project.read", "project.mutate", "project.execute"}, project_id)
    revision = project.document.revision
    command = DirectorCommand("location.apply_operations", revision, "agent-room", _arguments(ROOM))
    first = execute_atomic_request(project.store, command, agent)
    replay = execute_atomic_request(project.store, command, agent)
    assert replay.replay and replay.data == first.data
    assert len(project.document.location_library.locations) == 1
    different = DirectorCommand(
        "location.apply_operations", revision, "agent-room", _arguments({**ROOM, "name": "书房"})
    )
    with pytest.raises(RevisionConflictError, match="幂等键已用于不同请求"):
        execute_atomic_request(project.store, different, agent)
    other_caller = replace(agent, id="agent-2")
    with pytest.raises(RevisionConflictError):
        # 另一 caller 的同名键是不同作用域，按当前 revision 正常校验。
        execute_atomic_request(project.store, command, other_caller)


def test_impact_preview_matches_write(project):
    location_id, created = _room(project)
    first = project.master(location_id)
    project.run("location.select_master", {"location_id": location_id, "asset_id": first})
    document = project.document
    command = DirectorCommand(
        "location.select_master",
        document.revision,
        "preview",
        {"location_id": location_id, "asset_id": project.master(location_id)},
    )
    document = project.document
    command = replace(command, expected_revision=document.revision)
    preview = preview_command_impact(document, command)
    receipt = project.registry.execute(command).receipt
    assert preview["will_write"] and preview["high_impact"]
    assert preview["invalidated"] == sorted(receipt.invalidated)
    assert preview["changed_ids"] == sorted(receipt.changed_ids)
    assert f"location_master_selection:{location_id}" in preview["invalidated"]
    rename = DirectorCommand(
        "location.apply_operations",
        project.document.revision,
        "rename",
        _arguments(
            {"op": "update_view", "view_id": created["main"], "fields": {"name": "新名"}},
            locations=(location_id,),
        ),
    )
    preview = preview_command_impact(project.document, rename)
    assert preview["changed_ids"] == [created["main"]]
    assert preview["invalidated"] == [] and not preview["high_impact"]


def test_human_http_routes_edit_select_and_calibrate(project):
    api = StructuredDirectorHttpApi(project.service, resource_path="/r", store=project.store)

    def post(path, body):
        response = asyncio.run(api.handle("POST", f"/r{path}", json.dumps(body).encode()))
        assert response.status == 200, response.body
        return response

    post(
        "/locations/operations",
        {
            "expected_revision": project.document.revision,
            **_arguments(
                ROOM,
                _view("main"),
                {
                    "op": "upsert_fixture",
                    "location_id": "room",
                    "fixture": "door",
                    "name": "门",
                    "description": "",
                    "azimuth_deg": None,
                },
            ),
        },
    )
    location = project.document.location_library.locations[0]
    master = project.master(location.id)
    view_image = project.view_image(location.views[0].id)
    post(
        f"/locations/{location.id}/master/select",
        {"expected_revision": project.document.revision, "asset_id": master},
    )
    post(
        f"/location-views/{location.views[0].id}/select",
        {"expected_revision": project.document.revision, "asset_id": view_image},
    )
    post(
        f"/locations/{location.id}/calibrate",
        {
            "expected_revision": project.document.revision,
            "fixture_azimuths": {location.fixtures[0].id: 180.0},
            "key_light_azimuth_deg": None,
        },
    )
    location = project.location(location.id)
    assert location.calibrated and location.fixtures[0].azimuth_deg == 180.0
    assert location.views[0].selected_asset_id == view_image
    stale = asyncio.run(
        api.handle(
            "POST",
            f"/r/locations/{location.id}/master/select",
            json.dumps({"expected_revision": 1, "asset_id": master}).encode(),
        )
    )
    assert stale.status == 409


def test_mcp_edit_locations_translates_to_formal_command():
    model = MODELS["edit_locations"]
    request = model.model_validate(
        {
            "project_id": "a" * 32,
            "expected_revision": 3,
            "idempotency_key": "k",
            "location_ids": [],
            "scene_ids": ["b" * 32],
            "shot_ids": [],
            "operations": [
                ROOM,
                {"op": "bind_scene", "scene_id": "b" * 32, "location_id": "room", "state_id": None},
            ],
        }
    )
    name, arguments = translate("edit_locations", request)
    assert name == "location.apply_operations"
    assert arguments["scope"] == {"location_ids": [], "scene_ids": ["b" * 32], "shot_ids": []}
    parse_location_operations_patch(arguments)
    with pytest.raises(ValueError):
        model.model_validate(
            {
                "project_id": "a" * 32,
                "expected_revision": 3,
                "idempotency_key": "k",
                "location_ids": [],
                "scene_ids": [],
                "shot_ids": [],
                "operations": [
                    {"op": "select_master", "location_id": "a" * 32, "asset_id": "b" * 32}
                ],
            }
        )
