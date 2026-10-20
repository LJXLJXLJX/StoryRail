"""MCP生产schema逐项固定翻译；Core仍执行领域/权限校验。"""

import asyncio
from dataclasses import replace

import pytest
from mcp import Client
from structured_director_fixtures import synthesize_and_select_narration
from test_director_commands import _visual_project
from test_external_script_proposals import agent
from test_scene_driver_invariants import narration_project
from test_storyrail_mcp import endpoint

from core.application.caller import Caller
from core.director_commands import DirectorCommand
from integrations.storyrail_mcp.production_tools import MODELS, translate

BASE = {"project_id": "a" * 32, "expected_revision": 1, "idempotency_key": "test"}
TARGET = "b" * 32
CASES = [
    (
        "edit_script",
        {
            "scene_ids": [TARGET],
            "operations": [
                {"op": "update_shot_fields", "shot_id": TARGET, "fields": {"action": "起身"}}
            ],
        },
        "script.apply_operations",
    ),
    (
        "edit_script",
        {
            "scene_ids": [TARGET],
            "operations": [
                {"op": "update_scene_fields", "scene_id": TARGET, "fields": {"title": "甲板"}},
                {
                    "op": "insert_scene",
                    "after_scene_id": TARGET,
                    "scene": {
                        "title": "甲板",
                        "summary": "转场。",
                        "setting": "夜间甲板。",
                        "shots": [
                            {
                                "visible_character_ids": [],
                                "composition": "全景。",
                                "camera_movement": "固定。",
                                "action": "甲板空镜。",
                                "audio_direction": "",
                                "transition_in": None,
                            }
                        ],
                        "segments": [
                            {
                                "shot_indexes": [0],
                                "duration_estimate_seconds": 3,
                                "action": "甲板空镜。",
                                "dialogue_lines": [],
                                "boundary_from_previous": None,
                            }
                        ],
                    },
                },
                {"op": "move_scene", "scene_id": TARGET, "after_scene_id": None},
                {"op": "delete_scene", "scene_id": TARGET},
            ],
        },
        "script.apply_operations",
    ),
    (
        "edit_narration",
        {
            "scene_ids": [TARGET],
            "cue_id": TARGET,
            "fields": {"zh": {"seed": 7}},
        },
        "narration.update_cue",
    ),
    (
        "edit_keyframes",
        {"operations": [{"op": "set_aux_references", "segment_id": TARGET, "asset_ids": []}]},
        "keyframe.apply_operations",
    ),
    (
        "generate_media",
        {"kind": "narration", "target_id": TARGET, "language": "en"},
        "narration.generate",
    ),
    (
        "generate_media",
        {"kind": "look_sheet", "target_id": TARGET, "identity_asset_ids": []},
        "reference.generate_look_sheet",
    ),
    *[
        ("generate_media", {"kind": kind, "target_id": TARGET}, command)
        for kind, command in [
            ("keyframe", "keyframe.generate"),
            ("video", "video.generate"),
            ("upscale", "video.upscale"),
        ]
    ],
    *[
        (
            "manage_generation",
            {"action": action, "generation_ids": [TARGET]},
            "generation." + action,
        )
        for action in ["wait", "cancel", "retry", "dismiss"]
    ],
    (
        "media_batch",
        {"kind": "keyframe", "action": "start", "target_ids": [TARGET]},
        "keyframe.generate_batch",
    ),
    (
        "media_batch",
        {"kind": "keyframe", "action": "continue", "run_id": TARGET},
        "keyframe.continue_batch",
    ),
    (
        "media_batch",
        {"kind": "location", "action": "start", "target_ids": [TARGET]},
        "location.generate_set",
    ),
    (
        "media_batch",
        {"kind": "location", "action": "continue", "run_id": TARGET},
        "location.generate_set",
    ),
    ("unlock_production", {"action": "unlock_visual_production"}, "visual_production.unlock"),
    ("assemble_media", {"kind": "animatic", "scene_id": TARGET}, "animatic.generate_scene"),
    ("assemble_media", {"kind": "scene", "scene_id": TARGET}, "final.assemble_scene"),
    ("assemble_media", {"kind": "final"}, "final.assemble"),
    ("read_run", {"run_id": TARGET}, "run.get_status"),
    ("cancel_run", {"run_id": TARGET}, "run.cancel"),
    ("read_request", {"request_key": "first"}, "project.get_request"),
    ("read_human_handoff", {}, "project.get_handoff"),
    (
        "list_candidates",
        {"kind": "keyframe_image", "target_ids": [TARGET]},
        "project.list_candidates",
    ),
    (
        "set_video_recipe",
        {"scene_ids": [TARGET], "segment_id": TARGET, "recipe_id": "minimax_h3.fl2va"},
        "video.set_recipe",
    ),
]


@pytest.mark.parametrize("name,args,command", CASES)
def test_production_tool_schema_and_fixed_mapping(name, args, command):
    parsed = MODELS[name].model_validate({**BASE, **args})
    actual, values = translate(name, parsed)
    assert actual == command
    if name == "edit_narration":
        assert values["fields"] == {"zh": {"seed": 7}}
    with pytest.raises(ValueError):
        MODELS[name].model_validate({**BASE, **args, "command": "final.approve"})
    schema = MODELS[name].model_json_schema()
    assert schema["additionalProperties"] is False
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False


def test_edit_script_segment_duration_has_no_mcp_upper_limit():
    # 15 秒只是 Agent 侧软约束；MCP 适配层与 Core 一样不设上限，只拒绝短于 0.2 秒或非有限值。
    def data(duration):
        return {
            **BASE,
            "scene_ids": [TARGET],
            "operations": [
                {
                    "op": "update_segment_fields",
                    "segment_id": TARGET,
                    "fields": {"duration_estimate_seconds": duration},
                }
            ],
        }

    model = MODELS["edit_script"]
    _, values = translate("edit_script", model.model_validate(data(20.0)))
    assert values["operations"][0]["fields"]["duration_estimate_seconds"] == 20.0
    for invalid in (0.1, float("inf")):
        with pytest.raises(ValueError):
            model.model_validate(data(invalid))

    def duration_schemas(node):
        if isinstance(node, dict):
            if "duration_estimate_seconds" in node.get("properties", {}):
                yield node["properties"]["duration_estimate_seconds"]
            for value in node.values():
                yield from duration_schemas(value)
        elif isinstance(node, list):
            for value in node:
                yield from duration_schemas(value)

    schemas = list(duration_schemas(model.model_json_schema()))
    assert schemas and all("maximum" not in item for item in schemas)
    assert all(item["minimum"] == 0.2 for item in schemas)


def test_published_split_segment_schema_exposes_nested_fields_and_boundary_reason_enum():
    from jsonschema import Draft202012Validator

    from core.director_commands.script_operations import parse_script_operations_patch
    from integrations.storyrail_mcp.app import published_tool_schema

    schema = published_tool_schema("edit_script", MODELS["edit_script"])
    split = schema["$defs"]["split_segment"]
    assert split["properties"]["first"] == {"$ref": "#/$defs/Segment"}
    assert split["properties"]["second"] == {"$ref": "#/$defs/Segment"}
    assert set(schema["$defs"]["Boundary"]["properties"]["reason"]["enum"]) == {
        "model_constraint",
        "continuity_anchor",
        "control_boundary",
        "failure_cost",
    }
    segment = {
        "shot_ids": [TARGET],
        "duration_estimate_seconds": 9.0,
        "action": "延续同一镜头。",
        "dialogue_lines": [],
        "boundary_from_previous": None,
    }
    request = {
        **BASE,
        "scene_ids": [TARGET],
        "operations": [
            {
                "op": "split_segment",
                "segment_id": TARGET,
                "preserve_id": "first",
                "first": segment,
                "second": {
                    **segment,
                    "boundary_from_previous": {
                        "reason": "model_constraint",
                        "continuity_instruction": "保持机位、动作与光线状态继续。",
                    },
                },
            }
        ],
    }
    validator = Draft202012Validator(schema)
    assert validator.is_valid(request)
    invalid = {
        **request,
        "operations": [
            {
                **request["operations"][0],
                "second": {
                    **request["operations"][0]["second"],
                    "boundary_from_previous": {
                        "reason": "long_take",
                        "continuity_instruction": "保持连续。",
                    },
                },
            }
        ],
    }
    assert not validator.is_valid(invalid)
    with pytest.raises(ValueError, match="model_constraint.*continuity_anchor"):
        parse_script_operations_patch(
            {"scope": {"scene_ids": [TARGET]}, "operations": invalid["operations"]}
        )


def test_edit_narration_clear_selected_audio_has_strict_schema_and_translation():
    data = {
        **BASE,
        "scene_ids": [TARGET],
        "cue_id": TARGET,
        "fields": {"clear_selected_audio": "zh"},
    }
    model = MODELS["edit_narration"]
    parsed = model.model_validate(data)
    assert translate("edit_narration", parsed) == (
        "narration.clear_selection",
        {"scope": {"scene_ids": [TARGET]}, "cue_id": TARGET, "language": "zh"},
    )
    schema = model.model_json_schema()
    clear_schema = schema["$defs"]["NarrationFields"]["properties"]["clear_selected_audio"]
    assert clear_schema["description"].startswith("指定 zh 或 en")
    for fields in (
        {},
        {"clear_selected_audio": None},
        {"clear_selected_audio": True},
        {"clear_selected_audio": "zh", "zh": {"text": "不能混合修改"}},
        {"zh": {}},
        {"text": "旧的单语字段"},
    ):
        with pytest.raises(ValueError):
            model.model_validate({**data, "fields": fields})
    nullable = model.model_validate(
        {**data, "fields": {"clear_selected_audio": None, "en": {"text": "Connector null."}}}
    )
    assert translate("edit_narration", nullable) == (
        "narration.update_cue",
        {
            "scope": {"scene_ids": [TARGET]},
            "cue_id": TARGET,
            "fields": {"en": {"text": "Connector null."}},
        },
    )
    generate = MODELS["generate_media"]
    with pytest.raises(ValueError):
        generate.model_validate({**BASE, "kind": "narration", "target_id": TARGET})
    with pytest.raises(ValueError):
        generate.model_validate({**BASE, "kind": "keyframe", "target_id": TARGET, "language": "zh"})


def test_mcp_edit_and_human_handoff(tmp_path):
    store, service, doc, _ = asyncio.run(_visual_project(str(tmp_path)))
    scene = doc.director_script.scenes[0]
    args = {
        "scene_ids": [scene.id],
        "operations": [
            {
                "op": "update_shot_fields",
                "shot_id": scene.shots[0].id,
                "fields": {"action": "人物走向门口。"},
            }
        ],
    }
    data = {
        "project_id": doc.project_id,
        "expected_revision": doc.revision,
        "idempotency_key": "edit",
        **args,
    }
    name, values = translate("edit_script", MODELS["edit_script"].model_validate(data))
    command = DirectorCommand(name, doc.revision, "edit", values)
    caller = agent(doc, command)

    async def run(params):
        async with Client(params) as client:
            result = await client.call_tool("edit_script", data)
            assert not result.is_error, result
            saved = store.path.read_bytes()
            replay = await client.call_tool("edit_script", data)
            assert replay.structured_content["replay"]
            assert store.path.read_bytes() == saved
            result = await client.call_tool(
                "read_human_handoff",
                {
                    "project_id": doc.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "human",
                },
            )
            assert not result.is_error
            assert "candidate_selection" in result.structured_content["data"]["human_only"]
            malformed = {**data, "operations": [{**args["operations"][0], "shell": "bad"}]}
            assert (await client.call_tool("edit_script", malformed)).is_error

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))


def test_mcp_agent_clears_selected_narration_then_dismisses_generation(tmp_path):
    async def setup():
        store, service, _provider, document = await narration_project(tmp_path)
        # 测试 Provider 中英返回相同字节会共用 Asset；这里只合成并选择中文。
        selected, _ = await synthesize_and_select_narration(
            service,
            document.director_script.scenes[0].narration_cues[0].id,
            document.revision,
            ("zh",),
        )
        scene = selected.director_script.scenes[0]
        cue = scene.narration_cues[0]
        generation = selected.generations[-1]
        clear_data = {
            "project_id": selected.project_id,
            "expected_revision": selected.revision,
            "idempotency_key": "clear-selected-narration",
            "scene_ids": [scene.id],
            "cue_id": cue.id,
            "fields": {"clear_selected_audio": "zh"},
        }
        command_name, arguments = translate(
            "edit_narration", MODELS["edit_narration"].model_validate(clear_data)
        )
        command = DirectorCommand(
            command_name,
            selected.revision,
            clear_data["idempotency_key"],
            arguments,
        )
        caller = replace(
            agent(selected, command),
            capabilities=frozenset({"project.read", "project.mutate", "project.execute"}),
            grants=(),
        )
        return store, service, selected, scene, cue, generation, clear_data, caller

    store, service, selected, scene, cue, generation, clear_data, caller = asyncio.run(setup())

    async def run(params):
        async with Client(params) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            fields = tools["edit_narration"].input_schema["$defs"]["NarrationFields"]["properties"]
            assert "clear_selected_audio" in fields

            blocked = await client.call_tool(
                "manage_generation",
                {
                    "project_id": selected.project_id,
                    "expected_revision": selected.revision,
                    "idempotency_key": "dismiss-selected-narration",
                    "action": "dismiss",
                    "generation_ids": [generation.id],
                },
            )
            assert blocked.is_error
            assert blocked.structured_content["http_status"] == 409

            cleared = await client.call_tool("edit_narration", clear_data)
            assert not cleared.is_error, cleared
            assert cleared.structured_content["http_status"] == 200
            cleared_cue = store.read().director_script.scenes[0].narration_cues[0]
            assert cleared_cue.zh.selected_audio_asset_id is None

            projection = await client.call_tool(
                "read_story",
                {
                    "project_id": selected.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "read-cleared-narration",
                    "level": "outline",
                },
            )
            assert not projection.is_error, projection
            projected_cue = projection.structured_content["data"]["items"][0]["narration"][0]
            assert projected_cue["id"] == cue.id
            assert projected_cue["zh"]["selected_audio_asset_id"] is None

            dismissed = await client.call_tool(
                "manage_generation",
                {
                    "project_id": selected.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "dismiss-unselected-narration",
                    "action": "dismiss",
                    "generation_ids": [generation.id],
                },
            )
            assert not dismissed.is_error, dismissed
            assert dismissed.structured_content["http_status"] == 200
            assert next(
                item for item in store.read().generations if item.id == generation.id
            ).dismissed

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))


def test_mcp_delegated_agent_edits_and_splits_scene(tmp_path):
    store, service, doc, _ = asyncio.run(_visual_project(str(tmp_path)))
    scene = doc.director_script.scenes[0]
    caller = Caller(
        "local-agent",
        "agent",
        frozenset({doc.project_id}),
        frozenset({"project.read", "project.mutate", "project.propose", "project.execute"}),
        4102444800,
        (),
        True,
    )
    base = {"project_id": doc.project_id, "scene_ids": [scene.id]}

    async def run(params):
        async with Client(params) as client:
            renamed = await client.call_tool(
                "edit_script",
                {
                    **base,
                    "expected_revision": doc.revision,
                    "idempotency_key": "rename-scene",
                    "operations": [
                        {
                            "op": "update_scene_fields",
                            "scene_id": scene.id,
                            "fields": {"title": "拐角通道·时空重叠交错"},
                        }
                    ],
                },
            )
            assert not renamed.is_error, renamed
            revision = store.read().revision
            assert revision == doc.revision + 1
            split = await client.call_tool(
                "edit_script",
                {
                    **base,
                    "expected_revision": revision,
                    "idempotency_key": "split-scene",
                    "operations": [
                        {
                            "op": "insert_scene",
                            "after_scene_id": scene.id,
                            "scene": {
                                "title": "母船甲板",
                                "summary": "转移到母船甲板。",
                                "setting": "夜间母船甲板。",
                                "shots": [
                                    {
                                        "visible_character_ids": [],
                                        "composition": "全景。",
                                        "camera_movement": "固定。",
                                        "action": "母船甲板空镜。",
                                        "audio_direction": "海风。",
                                        "transition_in": None,
                                    }
                                ],
                                "segments": [
                                    {
                                        "shot_indexes": [0],
                                        "duration_estimate_seconds": 3,
                                        "action": "母船甲板空镜。",
                                        "dialogue_lines": [],
                                        "boundary_from_previous": None,
                                    }
                                ],
                            },
                        }
                    ],
                },
            )
            assert not split.is_error, split

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))
    scenes = store.read().director_script.scenes
    assert scenes[0].title == "拐角通道·时空重叠交错"
    assert [shot.id for shot in scenes[0].shots] == [item.id for item in scene.shots]
    assert scenes[1].title == "母船甲板"
    (new_shot,) = scenes[1].shots
    assert new_shot.id not in {item.id for item in scene.shots}
    (new_segment,) = scenes[1].segments
    assert new_segment.shot_ids == (new_shot.id,)
