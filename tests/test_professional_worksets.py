"""完整专业契约、共源规划输入及受信外部只读边界。"""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from mcp import Client
from script_helpers import shot_segments_at
from test_director_commands import _location_project, _visual_project
from test_external_script_proposals import agent, command, http
from test_prompt_worksets import fixture
from test_storyrail_mcp import endpoint

import core.director_proposals
from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals.professional_contracts import CONTRACTS, read_contract
from core.structured_director.models import (
    ImageAssetCategory,
    SegmentBoundary,
    SegmentBoundaryReason,
)
from core.structured_director.planning_inputs import keyframe_inputs
from core.structured_director.prompt_worksets import keyframe_workset, video_prompt_workset
from core.structured_director.reads.professional_worksets import workset_read
from core.structured_director.reads.read_tools import _json_value, execute_project_read


def test_all_contract_resources_are_the_published_sources():
    for capability, (_role, skill, references) in CONTRACTS.items():
        directory = Path(core.director_proposals.__file__).parent / "skills" / skill
        default = read_contract(capability)
        assert default["skill_name"] == skill
        global_names = (
            {"global/storyrail-image-prompt-writing/SKILL.md"}
            if capability in {"keyframe", "location"}
            else set()
        )
        assert len(default["resources"]) == len(references) + 1 + len(global_names)
        assert {r["name"] for r in default["resources"]} == {
            "SKILL.md",
            *("references/" + name for name in references),
            *global_names,
        }
        included = read_contract(capability, include=("consistency-review",))
        assert {r["name"] for r in included["resources"]} == {
            "SKILL.md",
            *("references/" + name for name in references),
            "shared/storyrail-consistency-review/SKILL.md",
            *global_names,
        }
        for resource in included["resources"]:
            name = resource["name"]
            source = (
                directory.parent / "storyrail-consistency-review" / "SKILL.md"
                if name == "shared/storyrail-consistency-review/SKILL.md"
                else directory / name
            )
            if name in global_names:
                source = (
                    directory.parents[2]
                    / "model_providers"
                    / "skills"
                    / name.removeprefix("global/")
                )
            text = source.read_text()
            assert resource["text"] == text
            assert resource["sha256"] == hashlib.sha256(text.encode()).hexdigest()


def test_worksets_current_facts_schema_scope_and_no_writes(tmp_path):
    store, service, document, aux = asyncio.run(fixture(tmp_path))
    scene = document.director_script.scenes[0]
    segment = scene.segments[0]
    before = store.path.read_bytes()
    for capability in CONTRACTS:
        project_scope = capability in {"reference_library", "script", "location"}
        request = {
            "capability": capability,
            "scope": {"project_id": document.project_id}
            if project_scope
            else {"scene_ids": [scene.id]},
        }
        if capability == "video_prompt":
            request["target_ids"] = [segment.id]
        result = workset_read(
            document,
            request,
            provider_recipes=service.provider_recipe_views(),
            provider_catalog=service._registry,
        )
        assert result["source_revision"] == document.revision
        assert result["provenance"]["authority"] == "project.json"
        assert result["output_schema"]["additionalProperties"] is False
        if capability == "video_prompt":
            assert result["core_facts"] == video_prompt_workset(
                document,
                segment.id,
                provider_recipes=service.provider_recipe_views(),
                provider_catalog=service._registry,
            )
            assert aux not in [x["asset_id"] for x in result["core_facts"]["asset_inputs"]]
        elif capability in {"reference_library", "script"}:
            assert result["core_facts"]["director_plan_markdown"] == document.director_plan_markdown
        elif capability == "location":
            # 地点规划以导演脚本为核心；原始方案经 get_details 按需读取。
            assert "director_plan_markdown" not in result["core_facts"]
        assert execute_project_read(document, "project.get_contract", {"capability": capability})[
            "resources"
        ]
    scoped = {
        "capability": "keyframe",
        "scope": {"scene_ids": [scene.id]},
        "target_ids": [segment.id],
    }
    result = execute_project_read(document, "project.get_workset", scoped)
    scenes, targets, _ = keyframe_inputs(document, (segment.id,))
    assert result["core_facts"]["scenes"] == _json_value(scenes)
    assert result["core_facts"]["target_segment_ids"] == list(targets)
    assert scenes[0].segments[0].planning_enabled and not scenes[0].segments[1].planning_enabled
    assert scenes[0].segments[0].start_locked
    for extra in (
        {"path": "../../secret"},
        {"scope": {}},
        {"target_ids": []},
        {"target_ids": ["f" * 32]},
        {"scope": {"scene_ids": ["f" * 32]}},
        {"capability": "shell"},
    ):
        with pytest.raises(ValueError):
            execute_project_read(document, "project.get_workset", {**scoped, **extra})
    with pytest.raises(ValueError):
        execute_project_read(
            document,
            "project.get_contract",
            {"capability": "video_prompt", "path": "references/base-en.txt"},
        )
    caller = replace(
        agent(document, command("get", document.revision, "unused", request_id="f" * 32)),
        grants=(),
        capabilities=frozenset({"project.read"}),
        mutations_enabled=False,
    )
    read = DirectorCommand("project.get_workset", document.revision, "read", scoped)
    assert asyncio.run(http(service, caller, read)).status == 200
    assert asyncio.run(http(service, caller, replace(read, expected_revision=1))).status == 409
    assert asyncio.run(http(service, replace(caller, project_ids=frozenset()), read)).status == 403
    assert store.path.read_bytes() == before


def test_narration_before_shot_planning_and_result_size(tmp_path):
    from test_scene_driver_invariants import MixedProposer, narration_project

    store, _, _, doc = asyncio.run(narration_project(tmp_path, MixedProposer()))
    scene = doc.director_script.scenes[0]
    request = {"capability": "narration", "scope": {"scene_ids": [scene.id]}}
    result = execute_project_read(doc, "project.get_workset", request)
    assert "尚未规划" in result["core_facts"]["cues"][0]["coverage"]
    huge = replace(doc, director_plan_markdown="文" * 50000)
    query = {"capability": "script", "scope": {"project_id": doc.project_id}}
    chunks = []
    cursor = None
    first_cursor = None
    while True:
        page = execute_project_read(
            huge,
            "project.get_workset",
            {**query, **({} if cursor is None else {"cursor": cursor})},
        )
        assert page["project_id"] == doc.project_id
        assert page["observation_revision"] == huge.revision
        assert len(json.dumps(page, ensure_ascii=False).encode()) < 64 * 1024
        chunks.append(page["content_chunk"])
        cursor = page["pagination"]["next_cursor"]
        if first_cursor is None:
            first_cursor = cursor
        if cursor is None:
            digest = page["pagination"]["content_sha256"]
            break
    encoded = "".join(chunks).encode()
    assert hashlib.sha256(encoded).hexdigest() == digest
    assert json.loads(encoded) == workset_read(huge, query)

    with pytest.raises(ValueError, match="cursor"):
        execute_project_read(
            huge,
            "project.get_workset",
            {**query, "cursor": "0" * 64 + ":1"},
        )
    with pytest.raises(ValueError, match="cursor"):
        execute_project_read(
            replace(huge, revision=huge.revision + 1),
            "project.get_workset",
            {**query, "cursor": first_cursor},
        )


def test_large_contract_resource_bundle_uses_same_complete_paging(tmp_path, monkeypatch):
    import core.structured_director.reads.professional_worksets as module

    _, _, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    oversized = "contract-section\n" + "契约" * 40000

    def fake_contract(capability, *, include=(), provider_catalog=None):
        del include, provider_catalog
        return {
            "contract_version": 1,
            "capability": capability,
            "skill_name": "fixture",
            "resources": [
                {
                    "name": "SKILL.md",
                    "text": oversized,
                    "sha256": hashlib.sha256(oversized.encode()).hexdigest(),
                }
            ],
            "output_schema_source": "project.get_workset.output_schema",
        }

    monkeypatch.setattr(module, "read_contract", fake_contract)
    query = {"capability": "video_prompt"}
    chunks = []
    cursor = None
    first_cursor = None
    while True:
        page = execute_project_read(
            document,
            "project.get_contract",
            {**query, **({} if cursor is None else {"cursor": cursor})},
        )
        assert page["observation_revision"] is None
        chunks.append(page["content_chunk"])
        cursor = page["pagination"]["next_cursor"]
        if first_cursor is None:
            first_cursor = cursor
        if cursor is None:
            break
    restored = json.loads("".join(chunks))
    assert restored["resources"][0]["text"] == oversized
    bumped = replace(document, revision=document.revision + 1)
    next_page = execute_project_read(
        bumped,
        "project.get_contract",
        {**query, "cursor": first_cursor},
    )
    assert next_page["pagination"]["offset"] > 0


def test_saved_keyframe_plan_is_complete_scoped_and_independent_of_executable_inputs(tmp_path):
    async def run():
        store, service, doc, _ = await _location_project(str(tmp_path))
        doc = await service.unlock_visual_production(expected_revision=doc.revision)
        scene = doc.director_script.scenes[0]
        first_segment = scene.segments[0]
        second_segment = shot_segments_at(scene, 1)[0]
        bindings = {item.segment_id: item for item in doc.keyframe_plan.segments}
        registry = DirectorCommandRegistry(store)
        doc = registry.execute(
            DirectorCommand(
                "keyframe.apply_operations",
                doc.revision,
                "share-context-boundary",
                {
                    "operations": [
                        {
                            "op": "share_boundary",
                            "left_segment_id": first_segment.id,
                            "right_segment_id": second_segment.id,
                            "source_keyframe_id": bindings[first_segment.id].end_keyframe_id,
                            "expected_adjacency": "cross_shot",
                        }
                    ]
                },
            )
        ).document
        bindings = {item.segment_id: item for item in doc.keyframe_plan.segments}
        first_start = bindings[first_segment.id].start_keyframe_id
        shared = bindings[first_segment.id].end_keyframe_id
        second_end = bindings[second_segment.id].end_keyframe_id
        doc = await service.import_image_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\nsaved-plan",
            category=ImageAssetCategory.KEYFRAME,
            expected_revision=doc.revision,
        )
        aux = doc.assets[-1].id
        doc = registry.execute(
            DirectorCommand(
                "keyframe.apply_operations",
                doc.revision,
                "saved-plan-fields",
                {
                    "operations": [
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": first_start,
                            "fields": {
                                "prompt_text": "已保存首帧正文。",
                                "visible_character_ids": [scene.shots[0].visible_character_ids[0]],
                            },
                        },
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": shared,
                            "fields": {
                                "prompt_text": "已保存共享边界正文。",
                                "visible_character_ids": [],
                            },
                        },
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": second_end,
                            "fields": {
                                "prompt_text": "已保存尾帧正文。",
                                "visible_character_ids": [],
                            },
                        },
                        {
                            "op": "set_activation",
                            "segment_id": first_segment.id,
                            "start_enabled": True,
                            "end_enabled": True,
                        },
                        {
                            "op": "set_activation",
                            "segment_id": second_segment.id,
                            "start_enabled": True,
                            "end_enabled": True,
                        },
                        {
                            "op": "set_aux_references",
                            "segment_id": first_segment.id,
                            "asset_ids": [aux],
                        },
                    ]
                },
            )
        ).document
        doc = await service.select_keyframe(
            keyframe_id=first_start,
            asset_id=aux,
            expected_revision=doc.revision,
        )
        request = {
            "capability": "keyframe",
            "scope": {"scene_ids": [scene.id]},
            "target_ids": [second_segment.id],
        }
        before = store.path.read_bytes()
        result = execute_project_read(doc, "project.get_workset", request)
        location_facts = result["core_facts"]["location_library"]
        assert [item["id"] for item in location_facts] == [scene.location_id]
        assert result["core_facts"]["scenes"][0]["state_id"] == scene.state_id
        saved = result["core_facts"]["saved_keyframe_plan"]
        assert saved["status"] == "established"
        assert saved["source_script_revision"] == doc.keyframe_plan.source_script_revision
        assert [item["segment_id"] for item in saved["segments"]] == [
            first_segment.id,
            second_segment.id,
        ]
        first_saved = next(
            item for item in saved["segments"] if item["segment_id"] == first_segment.id
        )
        assert first_saved["reference_asset_ids"] == [aux]
        frames = {item["id"]: item for item in saved["keyframes"]}
        assert frames[first_start]["prompt_text"] == "已保存首帧正文。"
        assert frames[first_start]["selected_asset_id"] == aux
        assert "environment_mode" not in frames[first_start]
        assert "environment_view_id" not in frames[first_start]
        assert "environment_none_reason" not in frames[second_end]
        assert frames[second_end]["predecessor_keyframe_id"] == shared
        assert frames[shared]["bindings"] == [
            {"segment_id": first_segment.id, "slot": "end"},
            {"segment_id": second_segment.id, "slot": "start"},
        ]
        assert len(saved["keyframes"]) == len({item["id"] for item in saved["keyframes"]})
        with pytest.raises(ValueError, match="前置Keyframe候选"):
            keyframe_workset(doc, second_segment.id)
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_keyframe_workset_reports_plan_not_established_before_unlock(tmp_path):
    store, _, doc, _ = asyncio.run(_location_project(str(tmp_path)))
    scene = doc.director_script.scenes[0]
    before = store.path.read_bytes()
    result = execute_project_read(
        doc,
        "project.get_workset",
        {
            "capability": "keyframe",
            "scope": {"scene_ids": [scene.id]},
            "target_ids": [scene.segments[0].id],
        },
    )
    saved = result["core_facts"]["saved_keyframe_plan"]
    assert saved == {
        "status": "not_established",
        "source_script_revision": None,
        "segments": [],
        "keyframes": [],
    }
    assert store.path.read_bytes() == before


def test_mcp_professional_reads_need_no_mutation_grant(tmp_path):
    store, service, doc, _ = asyncio.run(_visual_project(str(tmp_path)))
    caller = replace(
        agent(doc, command("get", doc.revision, "unused", request_id="f" * 32)),
        grants=(),
        capabilities=frozenset({"project.read"}),
        mutations_enabled=False,
    )
    before = store.path.read_bytes()

    async def run(params):
        scene = doc.director_script.scenes[0]
        base = {
            "project_id": doc.project_id,
            "expected_revision": doc.revision,
            "idempotency_key": "read-only",
        }
        async with Client(params) as client:
            for cap in CONTRACTS:
                read = await client.call_tool(
                    "read_professional_contract", {**base, "capability": cap}
                )
                assert not read.is_error
            result = await client.call_tool(
                "read_professional_workset", {**base, "capability": "script"}
            )
            assert not result.is_error
            keyframes = await client.call_tool(
                "read_professional_workset",
                {
                    **base,
                    "capability": "keyframe",
                    "scene_ids": [scene.id],
                    "target_ids": [scene.segments[0].id],
                },
            )
            assert not keyframes.is_error
            assert (
                keyframes.structured_content["data"]["core_facts"]["saved_keyframe_plan"]["status"]
                == "established"
            )
            for extra in (
                {"path": "../secret"},
                {"capability": "../secret"},
                {"scene_ids": ["f" * 32]},
                {"expected_revision": 1},
                {"project_id": "f" * 32},
            ):
                result = await client.call_tool(
                    "read_professional_workset", {**base, "capability": "script", **extra}
                )
                assert result.is_error

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))
    assert store.path.read_bytes() == before


def test_keyframe_inputs_multi_shot_segment_union_without_location_image_defaults(tmp_path):
    _store, _service, document, _route = asyncio.run(_location_project(str(tmp_path)))
    scene = document.director_script.scenes[0]
    first, second = scene.shots[:2]
    updated_scene = replace(
        scene,
        segments=(
            scene.segments[0],
            replace(
                scene.segments[1],
                shot_ids=(first.id, second.id),
                boundary_from_previous=SegmentBoundary(
                    SegmentBoundaryReason.CONTINUITY_ANCHOR, "延续同一镜头"
                ),
            ),
        ),
    )
    baseline = document.director_script.production_baseline_scenes
    document = replace(
        document,
        director_script=replace(
            document.director_script,
            scenes=(updated_scene, *document.director_script.scenes[1:]),
            production_baseline_scenes=(
                None if baseline is None else (updated_scene, *baseline[1:])
            ),
        ),
    )
    scenes, targets, _boundaries = keyframe_inputs(document, (scene.segments[1].id,))
    segment = scenes[0].segments[1]
    assert [item.id for item in segment.visible_characters] == [
        first.visible_character_ids[0],
        second.visible_character_ids[0],
    ]
    assert not hasattr(segment, "start_view_id")
    assert not hasattr(segment, "end_view_id")
    assert segment.continues_from_previous is True
    assert scenes[0].segments[0].planning_enabled is False
    assert segment.planning_enabled is True
    assert targets == (scene.segments[1].id,)


def test_required_shared_boundary_outside_target_segments_reports_expansion(tmp_path):
    _store, _service, document, _route = asyncio.run(_location_project(str(tmp_path)))
    scene = document.director_script.scenes[0]
    left, right = scene.segments[0], scene.segments[1]
    message = json.dumps(
        {
            "scope_guard": {
                "required_shared_boundaries": [
                    {"left_segment_id": left.id, "right_segment_id": right.id}
                ]
            }
        }
    )
    with pytest.raises(ValueError, match="至少扩大目标范围到") as error:
        keyframe_inputs(document, (left.id,), message)
    assert right.id in str(error.value)
