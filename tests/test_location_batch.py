"""地点成套生成批次（location.generate_set）：范围固定、单轮可提交项、依赖顺序、显式继续与恢复。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_director_commands import _visual_project
from test_external_script_proposals import agent, http
from test_location_generation import FakeImage, FakePano

from core.application.caller import _AGENT_OPERATIONS
from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.model_providers.qwen_image import MANIFEST as QWEN_MANIFEST
from core.model_providers.qwen_image.plugin import format_prompt_workset
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.structured_director import StructuredDirectorService, StructuredDirectorStore
from core.structured_director.models import ReferenceGenerationKind

KIND = ReferenceGenerationKind


class Rig:
    """已解锁视觉生产的项目 + Qwen 图片替身与全景裁切替身；批次走正式应用命令入口。"""

    def __init__(self, tmp_path: Path) -> None:
        directory = tmp_path / uuid4().hex
        directory.mkdir()
        self.store, _service, _document, _route = asyncio.run(_visual_project(str(directory)))
        self.image = FakeImage(f"{QWEN_MANIFEST.recipes[0].id.split('.')[0]}.fake")
        self.pano = FakePano()

    def service(self) -> StructuredDirectorService:
        store = StructuredDirectorStore(self.store.path.parent, self.store.read().project_id)
        registry = ProviderRegistry()
        registry.install(
            PluginInstance(
                QWEN_MANIFEST,
                recipes={recipe.id: self.image for recipe in QWEN_MANIFEST.recipes},
                prompt_formatter=format_prompt_workset,
            )
        )
        registry.register("pano_view", self.pano)
        return StructuredDirectorService(store, registry=registry)

    @property
    def document(self):
        return self.store.read()

    def run(self, name: str, arguments: dict):
        return DirectorCommandRegistry(self.store).execute(
            DirectorCommand(name, self.document.revision, uuid4().hex, arguments)
        )

    def build_location(
        self,
        key: str,
        *,
        kind: str = "interior",
        name: str = "客厅",
        master_prompt: str = "空间全景，无人物。",
        fixtures: tuple[dict, ...] = (),
        views: tuple[dict, ...] = (
            {"key": "front", "name": "正打", "purpose": "中景", "azimuth_deg": 90.0},
        ),
    ) -> dict[str, str]:
        execution = self.run(
            "location.apply_operations",
            {
                "scope": {"location_ids": [], "scene_ids": [], "shot_ids": []},
                "operations": [
                    {
                        "op": "create_location",
                        "key": key,
                        "name": name,
                        "kind": kind,
                        "description": "固定空间、陈设与光线。",
                    },
                    {
                        "op": "update_location",
                        "location_id": key,
                        "fields": {"master_prompt_text": master_prompt},
                    },
                    *(
                        {
                            "op": "upsert_fixture",
                            "location_id": key,
                            "fixture": fixture["key"],
                            "name": fixture["name"],
                            "description": fixture.get("description", ""),
                            "azimuth_deg": fixture.get("azimuth_deg"),
                        }
                        for fixture in fixtures
                    ),
                    *(
                        {
                            "op": "create_view",
                            "location_id": key,
                            "key": view["key"],
                            "fields": {k: v for k, v in view.items() if k != "key"},
                        }
                        for view in views
                    ),
                ],
            },
        )
        return execution.data["created_ids"]

    async def call(self, name: str, key: str, arguments: dict, service=None):
        document = self.document
        command = DirectorCommand(name, document.revision, key, arguments)
        response = await http(service or self.service(), agent(document, command), command)
        return response, command

    async def generate_set(self, key: str, arguments: dict):
        response, _ = await self.call("location.generate_set", key, arguments)
        assert response.status == 200, response.body
        return response.body["data"]

    async def finish_pending(self):
        service = self.service()
        for generation in self.document.generations:
            if generation.phase.value in {"submitting", "queued", "running"}:
                await service._generation_observer.refresh_generation(generation.id)

    def select_master(self, location_id: str):
        generation = self.last(KIND.LOCATION_MASTER_IMAGE, location_id)
        self.run(
            "location.select_master",
            {"location_id": location_id, "asset_id": generation.output_asset_id},
        )

    def select_view(self, view_id: str):
        generation = self.last(KIND.LOCATION_VIEW_IMAGE, view_id)
        self.run(
            "location.select_view", {"view_id": view_id, "asset_id": generation.output_asset_id}
        )

    def last(self, kind: ReferenceGenerationKind, target_id: str):
        return next(
            item
            for item in reversed(self.document.generations)
            if item.kind is kind and item.target_id == target_id
        )

    def location(self, location_id: str):
        return self.document.location_library.location(location_id)


def _target(observation, location_id):
    return next(item for item in observation["targets"] if item["target_id"] == location_id)


def test_agent_whitelist_includes_set_but_not_selection():
    assert "location.generate_set" in _AGENT_OPERATIONS
    assert not {"location.select_master", "location.select_view"} & _AGENT_OPERATIONS


def test_full_set_flow_one_interior_one_exterior(tmp_path):
    """一室内一室外完整跑通：主图轮 → 等待选择 → 裁切/转向轮 → 细化轮 → 等待选择 → 完成。"""

    rig = Rig(tmp_path)

    async def run():
        interior = rig.build_location(
            "room",
            kind="interior",
            name="客厅",
            fixtures=({"key": "fireplace", "name": "壁炉", "azimuth_deg": 90.0},),
        )
        exterior = rig.build_location(
            "street",
            kind="exterior",
            name="街口",
            views=({"key": "front", "name": "街口", "purpose": "远景", "azimuth_deg": 300.0},),
        )
        interior_id, exterior_id = interior["room"], exterior["street"]
        interior_view, exterior_view = interior["front"], exterior["front"]

        # 第 1 轮：两个地点都只提交主图。
        data = await rig.generate_set("set-1", {"target_ids": [interior_id, exterior_id]})
        assert len(rig.image.requests) == 2 and not rig.pano.requests
        assert {g.kind for g in rig.document.generations} == {KIND.LOCATION_MASTER_IMAGE}
        batch_id = data["batch_id"]
        assert data["root_execution_run_id"] == data["execution_run_id"]
        assert data["previous_execution_run_id"] is None
        run = rig.document.active_director_run
        assert run is None  # 每轮结束自己的 run，不占用项目锁等待人选择
        scopes = next(
            item for item in rig.document.director_runs if item.id == data["execution_run_id"]
        ).authorization.generation_scopes
        assert scopes == (f"location:{interior_id}", f"location:{exterior_id}")
        observation = data["batch_observation"]
        assert observation["batch_kind"] == "location"
        assert observation["phase"] == "awaiting_generations"
        assert _target(observation, interior_id)["master"]["status"] == "in_progress"
        assert _target(observation, interior_id)["views"][0]["status"] == "awaiting_master"

        # 主图完成但未选择：继续不重复提交，报告等待选择。
        await rig.finish_pending()
        data = await rig.generate_set("set-2", {"run_id": batch_id})
        assert len(rig.image.requests) == 2
        observation = data["batch_observation"]
        assert observation["phase"] == "awaiting_selection"
        assert _target(observation, interior_id)["master"]["status"] == "awaiting_selection"
        assert any("等待选择" in message for message in data["messages"])

        # 选定主图后继续：室内视图提交裁切，室外视图直接提交转向。
        rig.select_master(interior_id)
        rig.select_master(exterior_id)
        data = await rig.generate_set("set-3", {"run_id": batch_id})
        assert len(rig.pano.requests) == 1
        crop = rig.last(KIND.LOCATION_VIEW_CROP, interior_view)
        turn = rig.last(KIND.LOCATION_VIEW_IMAGE, exterior_view)
        assert turn.operation.value == "edit"
        assert crop.provider_snapshot is None and crop.seed is None
        assert turn.provider_snapshot is not None and turn.seed is not None
        assert data["batch_observation"]["phase"] == "awaiting_generations"
        assert data["previous_execution_run_id"] != data["execution_run_id"]
        assert data["root_execution_run_id"] != data["execution_run_id"]

        # 裁切回调不续提交；显式继续才提交室内细化。
        await rig.finish_pending()
        assert rig.location(interior_id).views[0].crop_asset_id is not None
        assert not any(
            g.kind is KIND.LOCATION_VIEW_IMAGE and g.target_id == interior_view
            for g in rig.document.generations
        )
        data = await rig.generate_set("set-4", {"run_id": batch_id})
        refine = rig.last(KIND.LOCATION_VIEW_IMAGE, interior_view)
        assert refine.input_asset_ids[0] == rig.location(interior_id).views[0].crop_asset_id
        await rig.finish_pending()

        # 两个视图都有候选但未选择：等待选择，不重复提交。
        data = await rig.generate_set("set-5", {"run_id": batch_id})
        assert len(rig.image.requests) == 4  # 2 主图 + 1 转向 + 1 细化，无新增
        observation = data["batch_observation"]
        assert observation["phase"] == "awaiting_selection"
        assert _target(observation, interior_id)["views"][0]["status"] == "awaiting_selection"

        # 选择后完成。
        rig.select_view(interior_view)
        rig.select_view(exterior_view)
        data = await rig.generate_set("set-6", {"run_id": batch_id})
        observation = data["batch_observation"]
        assert observation["phase"] == "completed"
        assert observation["is_terminal"] and observation["all_succeeded"]
        assert len(observation["executions"]) == 6
        assert len(rig.image.requests) == 4 and len(rig.pano.requests) == 1

    asyncio.run(run())


def test_dependency_order_reference_view_and_calibration(tmp_path):
    """参考视图未选定前报告等待；相对陈设的视图未标定前报告等待标定。"""

    rig = Rig(tmp_path)

    async def run():
        created = rig.build_location(
            "room",
            fixtures=({"key": "fireplace", "name": "壁炉"},),
            views=(
                {"key": "front", "name": "正打", "purpose": "中景", "azimuth_deg": 0.0},
                {
                    "key": "back",
                    "name": "反打",
                    "purpose": "反打中景",
                    "azimuth_deg": 180.0,
                    "reference_view_ids": ["front"],
                },
                {
                    "key": "fire",
                    "name": "壁炉特写",
                    "purpose": "朝壁炉",
                    "look_at_fixture_id": "fireplace",
                    "yaw_offset_deg": 0.0,
                },
            ),
        )
        location_id = created["room"]
        front, back, fire = created["front"], created["back"], created["fire"]
        data = await rig.generate_set("set-1", {"target_ids": [location_id]})
        await rig.finish_pending()
        rig.select_master(location_id)

        data = await rig.generate_set("set-2", {"run_id": data["batch_id"]})
        # 正打提交裁切；反打等待参考视图选择；壁炉特写等待标定。
        assert rig.last(KIND.LOCATION_VIEW_CROP, front).phase.value == "queued"
        views = {
            item["view_id"]: item
            for item in _target(data["batch_observation"], location_id)["views"]
        }
        assert views[back]["status"] == "awaiting_reference_view"
        assert "正打" in views[back]["reason"]
        assert views[fire]["status"] == "awaiting_calibration"
        assert "标定" in views[fire]["reason"]

        await rig.finish_pending()
        data = await rig.generate_set("set-3", {"run_id": data["batch_id"]})
        rig.finish = rig.last(KIND.LOCATION_VIEW_IMAGE, front)
        assert rig.finish.phase.value == "queued"
        views = {
            item["view_id"]: item
            for item in _target(data["batch_observation"], location_id)["views"]
        }
        assert views[back]["status"] == "awaiting_reference_view"
        await rig.finish_pending()
        rig.select_view(front)

        # 参考视图选定后，反打进入裁切。
        data = await rig.generate_set("set-4", {"run_id": data["batch_id"]})
        assert rig.last(KIND.LOCATION_VIEW_CROP, back).phase.value == "queued"
        views = {
            item["view_id"]: item
            for item in _target(data["batch_observation"], location_id)["views"]
        }
        assert views[fire]["status"] == "awaiting_calibration"

    asyncio.run(run())


def test_scope_fixed_deleted_location_reported_missing(tmp_path):
    """范围在开始时固定：地点被删除后报告已不存在，不扩大也不拒绝。"""

    rig = Rig(tmp_path)

    async def run():
        keep = rig.build_location("keep", name="保留")
        dropped = rig.build_location("dropped", name="将删除", master_prompt="")
        keep_id, dropped_id = keep["keep"], dropped["dropped"]
        data = await rig.generate_set("set-1", {"target_ids": [keep_id, dropped_id]})
        batch_id = data["batch_id"]
        # 空主图提示词的地点被阻止并说明原因，不影响其它地点提交。
        blocked = _target(data["batch_observation"], dropped_id)
        assert blocked["master"]["status"] == "blocked"
        assert "主图提示词" in blocked["master"]["reason"]
        assert len(rig.image.requests) == 1

        rig.run(
            "location.apply_operations",
            {
                "scope": {"location_ids": [dropped_id], "scene_ids": [], "shot_ids": []},
                "operations": [{"op": "delete_location", "location_id": dropped_id}],
            },
        )
        data = await rig.generate_set("set-2", {"run_id": batch_id})
        assert _target(data["batch_observation"], dropped_id)["status"] == "target_missing"
        assert data["batch_observation"]["target_ids"] == [keep_id, dropped_id]

    asyncio.run(run())


def test_in_progress_single_entry_counts_as_waiting_not_error(tmp_path):
    """同一目标已有单项入口的进行中任务时，批次计为进行中，不重复提交也不报错。"""

    rig = Rig(tmp_path)

    async def run():
        created = rig.build_location("room")
        location_id = created["room"]
        service = rig.service()
        await service.generate_location_master(
            location_id=location_id, expected_revision=rig.document.revision
        )
        data = await rig.generate_set("set-1", {"target_ids": [location_id]})
        assert len(rig.image.requests) == 1  # 批次没有重复提交
        observation = data["batch_observation"]
        assert _target(observation, location_id)["master"]["status"] == "in_progress"
        assert _target(observation, location_id)["views"][0]["status"] == "awaiting_master"
        assert any("进行中" in message for message in data["messages"])

    asyncio.run(run())


def test_interruption_replay_cancel_and_continue(tmp_path):
    """中断保留已提交任务；重放不重复提交；取消中断 run 后按原范围继续。"""

    rig = Rig(tmp_path)

    async def run():
        first = rig.build_location("a", name="甲")
        second = rig.build_location("b", name="乙")
        target_ids = [first["a"], second["b"]]
        document = rig.document
        command = DirectorCommand(
            "location.generate_set", document.revision, "interrupted", {"target_ids": target_ids}
        )
        service = rig.service()
        original = service._store.set_director_run_cursor

        def interrupt(**kwargs):
            if kwargs["cursor"].step == 1:
                raise asyncio.CancelledError()
            return original(**kwargs)

        from unittest.mock import patch

        with (
            patch.object(service._store, "set_director_run_cursor", interrupt),
            pytest.raises(asyncio.CancelledError),
        ):
            await http(service, agent(document, command), command)
        assert len(rig.image.requests) == 1
        interrupted = rig.document
        run_id = interrupted.active_director_run.id
        batch_id = json.loads(interrupted.application_requests[-1].receipt_json)["data"]["batch_id"]

        replay = await http(rig.service(), agent(document, command), command)
        assert replay.body["replay"] and len(rig.image.requests) == 1

        cancel, _ = await rig.call("run.cancel", "cancel-run", {"run_id": run_id})
        assert cancel.status == 200, cancel.body
        data = await rig.generate_set("continue", {"run_id": batch_id})
        assert len(rig.image.requests) == 2
        assert data["batch_id"] == batch_id
        assert data["previous_execution_run_id"] == run_id
        assert len({g.id for g in rig.document.generations}) == 2

    asyncio.run(run())


def test_location_batch_is_not_confused_with_keyframe_batch(tmp_path):
    """地点批次活跃时，workflow 不把它当作 Keyframe 批次；推荐动作的工具都真实存在。"""

    rig = Rig(tmp_path)

    async def run():
        from test_external_production import assert_workflow_tools_exist

        created = rig.build_location("room")
        data = await rig.generate_set("set-1", {"target_ids": [created["room"]]})
        await rig.finish_pending()  # 主图完成，批次等待人类选择
        response, _ = await rig.call("project.get_handoff", "handoff", {})
        assert response.status == 200, response.body
        workflow = response.body["data"]["workflow"]
        assert_workflow_tools_exist(workflow)
        active = workflow["active_task"]
        assert not (isinstance(active, dict) and active.get("batch_id") == data["batch_id"])
        assert not any(
            action.get("batch_id") == data["batch_id"]
            for action in workflow["required_next_actions"]
        )
        # 等待人类选择时不推荐继续；视觉生产已解锁，规划/成套生成也不再推荐。
        assert workflow["recommended_next_actions"] == []

    asyncio.run(run())


def test_workflow_recommends_explicit_continue_and_hint_is_callable(tmp_path):
    """地点批次有待提交项时 workflow 推荐显式继续；推荐参数通过 media_batch 公开 schema。"""

    rig = Rig(tmp_path)

    async def run():
        from jsonschema import Draft202012Validator

        from integrations.storyrail_mcp.app import published_tool_schema
        from integrations.storyrail_mcp.production_tools import Batch

        created = rig.build_location("room")
        location_id = created["room"]
        data = await rig.generate_set("set-1", {"target_ids": [location_id]})
        batch_id = data["batch_id"]
        await rig.finish_pending()
        rig.select_master(location_id)
        # 主图已选、室内视图等待裁切：批次处于 awaiting_explicit_continue。
        response, _ = await rig.call("project.get_handoff", "handoff", {})
        assert response.status == 200, response.body
        workflow = response.body["data"]["workflow"]
        # 继续提示只是推荐，永不进入 required；视觉生产已解锁，规划/成套生成被抑制，
        # 只留下在途批次的显式继续。
        assert not any(
            action["action"] == "location.continue_set"
            for action in workflow["required_next_actions"]
        )
        continuation = next(
            action
            for action in workflow["recommended_next_actions"]
            if action["action"] == "location.continue_set"
        )
        assert [action["action"] for action in workflow["recommended_next_actions"]] == [
            "location.continue_set"
        ]
        assert continuation["tool"] == "media_batch"
        assert continuation["tool_action"] == "continue"
        assert continuation["kind"] == "location"
        assert continuation["batch_id"] == batch_id
        assert continuation["target_ids"] == [location_id]
        assert continuation["requires_explicit_user_request"]
        hinted = {
            "project_id": rig.document.project_id,
            "expected_revision": rig.document.revision,
            "idempotency_key": "hinted-continue",
            "kind": continuation["kind"],
            "action": continuation["tool_action"],
            "run_id": continuation["batch_id"],
            "target_ids": None,
        }
        Batch.model_validate(hinted)
        assert Draft202012Validator(published_tool_schema("media_batch", Batch)).is_valid(hinted)
        # 照推荐执行：提交室内视图的裁切。
        await rig.generate_set("set-2", {"run_id": continuation["batch_id"]})
        assert rig.last(KIND.LOCATION_VIEW_CROP, created["front"]).phase.value == "queued"

    asyncio.run(run())


def test_continue_requires_owned_batch_and_rejects_argument_mix(tmp_path):
    """continue 只能带 run_id；其它 caller 的批次不能继续；run.get_status 能看到批次观察。"""

    rig = Rig(tmp_path)

    async def run():
        created = rig.build_location("room")
        location_id = created["room"]
        data = await rig.generate_set("set-1", {"target_ids": [location_id]})
        batch_id = data["batch_id"]

        mixed, _ = await rig.call(
            "location.generate_set",
            "mixed",
            {"run_id": batch_id, "target_ids": [location_id]},
        )
        assert mixed.status == 400

        document = rig.document
        foreign = DirectorCommand(
            "location.generate_set", document.revision, "foreign", {"run_id": batch_id}
        )
        from dataclasses import replace as _replace

        denied = await http(
            rig.service(),
            _replace(
                agent(document, foreign),
                id="other-agent",
                capabilities=frozenset({"project.read", "project.mutate", "project.execute"}),
                grants=(),
            ),
            foreign,
        )
        assert denied.status == 409
        assert len(rig.image.requests) == 1

        read, _ = await rig.call("run.get_status", "read-run", {"run_id": data["execution_run_id"]})
        observation = read.body["data"]["batch_observation"]
        assert observation["batch_id"] == batch_id
        assert observation["phase"] == "awaiting_generations"
        assert _target(observation, location_id)["master"]["status"] == "in_progress"

    asyncio.run(run())
