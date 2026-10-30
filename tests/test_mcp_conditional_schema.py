"""MCP 公开 schema 与 runtime 共用同一条件参数契约。"""

import asyncio

import pytest
from jsonschema import Draft202012Validator
from mcp import Client
from pydantic import ValidationError

from integrations.storyrail_mcp.app import (
    DetailsRead,
    Read,
    WorksetRead,
    create_server,
    tool_schema,
)
from integrations.storyrail_mcp.production_tools import MODELS, Assemble, Batch, GenerationAction

READ_BASE = {"project_id": "a" * 32, "level": "outline"}
WRITE_BASE = {
    "project_id": "a" * 32,
    "expected_revision": 1,
    "idempotency_key": "conditional-schema",
}
SCENE_ID = "b" * 32
SHOT_ID = "c" * 32
SEGMENT_ID = "d" * 32


class RecordingBridge:
    def __init__(self):
        self.calls = []

    async def call(self, project_id, name, revision, key, arguments):
        self.calls.append((project_id, name, revision, key, arguments))
        return 200, {"data": {"accepted": True}}


def test_every_public_tool_schema_is_draft_2020_12_valid_and_conditionals_are_explicit():
    async def run():
        async with Client(create_server(RecordingBridge())) as client:
            tools = (await client.list_tools()).tools
        schemas = {tool.name: tool.input_schema for tool in tools}
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        for name in {
            "read_story",
            "read_details",
            "read_professional_workset",
            "manage_generation",
            "media_batch",
            "assemble_media",
        }:
            assert schemas[name]["oneOf"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "arguments",
    [
        READ_BASE,
        {
            **READ_BASE,
            "scene_ids": [],
            "ids": [],
            "parent_id": None,
            "extensions": ["text", "dependencies"],
        },
        {**READ_BASE, "level": "scene", "scene_ids": [SCENE_ID]},
        {
            **READ_BASE,
            "level": "shot",
            "scene_ids": [SCENE_ID],
            "ids": [SHOT_ID],
            "extensions": ["selection"],
        },
        {
            **READ_BASE,
            "level": "segment",
            "scene_ids": [SCENE_ID],
            "ids": [SEGMENT_ID],
            "parent_id": SCENE_ID,
            "extensions": ["text", "selection", "dependencies", "video_prompt", "keyframe"],
        },
    ],
)
def test_read_story_legal_combinations_match_schema_and_runtime(arguments):
    validator = Draft202012Validator(tool_schema("read_story", Read))
    assert validator.is_valid(arguments)
    assert Read.model_validate(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {**READ_BASE, "scene_ids": [SCENE_ID]},
        {**READ_BASE, "ids": [SHOT_ID]},
        {**READ_BASE, "parent_id": SHOT_ID},
        {**READ_BASE, "extensions": ["keyframe"]},
        {**READ_BASE, "level": "scene"},
        {**READ_BASE, "level": "scene", "scene_ids": [SCENE_ID], "ids": [SCENE_ID]},
        {**READ_BASE, "level": "shot", "scene_ids": [SCENE_ID], "parent_id": SCENE_ID},
        {**READ_BASE, "level": "shot", "scene_ids": [SCENE_ID], "extensions": ["video_prompt"]},
        {
            **READ_BASE,
            "level": "segment",
            "scene_ids": [SCENE_ID, SCENE_ID],
        },
        {
            **READ_BASE,
            "level": "segment",
            "scene_ids": [SCENE_ID],
            "extensions": ["text", "text"],
        },
    ],
)
def test_read_story_illegal_combinations_fail_schema_and_runtime(arguments):
    validator = Draft202012Validator(tool_schema("read_story", Read))
    assert not validator.is_valid(arguments)
    with pytest.raises(ValidationError):
        Read.model_validate(arguments)


def test_read_story_schema_documents_parent_identity_and_professional_level():
    schema = tool_schema("read_story", Read)
    assert "Scene ID" in schema["properties"]["parent_id"]["description"]
    assert "segment" in schema["properties"]["extensions"]["description"]
    Draft202012Validator.check_schema(schema)


def test_read_story_known_invalid_combinations_stop_at_mcp_before_core():
    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            outline_keyframe = await client.call_tool(
                "read_story", {**READ_BASE, "extensions": ["keyframe"]}
            )
            shot_with_parent = await client.call_tool(
                "read_story",
                {
                    **READ_BASE,
                    "level": "shot",
                    "scene_ids": [SCENE_ID],
                    "parent_id": SCENE_ID,
                },
            )
            assert outline_keyframe.is_error
            assert shot_with_parent.is_error
            assert not bridge.calls

            segment = await client.call_tool(
                "read_story",
                {
                    **READ_BASE,
                    "level": "segment",
                    "scene_ids": [SCENE_ID],
                    "parent_id": SCENE_ID,
                    "extensions": ["keyframe"],
                },
            )
            assert not segment.is_error
            assert bridge.calls[0][1:] == (
                "project.get_projection",
                None,
                "read",
                {
                    "level": "segment",
                    "scope": {"scene_ids": [SCENE_ID]},
                    "extensions": ["keyframe"],
                    "limit": 20,
                    "parent_id": SCENE_ID,
                },
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "arguments",
    [
        {"project_id": "a" * 32, "capability": "reference_library"},
        {
            "project_id": "a" * 32,
            "capability": "script",
            "scene_ids": [],
            "target_ids": None,
        },
        {"project_id": "a" * 32, "capability": "narration", "scene_ids": [SCENE_ID]},
        {
            "project_id": "a" * 32,
            "capability": "keyframe",
            "scene_ids": [SCENE_ID],
            "target_ids": [SHOT_ID],
        },
        {
            "project_id": "a" * 32,
            "capability": "video_prompt",
            "scene_ids": [SCENE_ID],
            "target_ids": [SEGMENT_ID],
        },
    ],
)
def test_workset_legal_capability_scopes_match_schema_and_runtime(arguments):
    validator = Draft202012Validator(tool_schema("read_professional_workset", WorksetRead))
    assert validator.is_valid(arguments)
    assert WorksetRead.model_validate(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "project_id": "a" * 32,
            "capability": "reference_library",
            "scene_ids": [SCENE_ID],
        },
        {
            "project_id": "a" * 32,
            "capability": "script",
            "target_ids": [SEGMENT_ID],
        },
        {"project_id": "a" * 32, "capability": "narration"},
        {"project_id": "a" * 32, "capability": "video_prompt", "scene_ids": [SCENE_ID]},
        {
            "project_id": "a" * 32,
            "capability": "video_prompt",
            "scene_ids": [SCENE_ID],
            "target_ids": [SEGMENT_ID, "e" * 32],
        },
    ],
)
def test_workset_illegal_capability_scopes_fail_schema_and_runtime(arguments):
    validator = Draft202012Validator(tool_schema("read_professional_workset", WorksetRead))
    assert not validator.is_valid(arguments)
    with pytest.raises(ValidationError):
        WorksetRead.model_validate(arguments)


@pytest.mark.parametrize(
    "name,model,valid,invalid",
    [
        (
            "manage_generation",
            GenerationAction,
            {**WRITE_BASE, "action": "wait", "generation_ids": [SEGMENT_ID, "e" * 32]},
            {**WRITE_BASE, "action": "cancel", "generation_ids": [SEGMENT_ID, "e" * 32]},
        ),
        (
            "media_batch",
            Batch,
            {
                **WRITE_BASE,
                "kind": "location",
                "action": "start",
                "target_ids": [SHOT_ID],
                "run_id": None,
            },
            {
                **WRITE_BASE,
                "kind": "keyframe",
                "action": "start",
                "target_ids": [SHOT_ID],
                "run_id": SEGMENT_ID,
            },
        ),
        (
            "media_batch",
            Batch,
            {
                **WRITE_BASE,
                "kind": "location",
                "action": "continue",
                "run_id": SEGMENT_ID,
                "target_ids": None,
            },
            {**WRITE_BASE, "kind": "keyframe", "action": "continue", "target_ids": [SHOT_ID]},
        ),
        (
            "assemble_media",
            Assemble,
            {**WRITE_BASE, "kind": "scene", "scene_id": SCENE_ID},
            {**WRITE_BASE, "kind": "scene", "scene_id": None},
        ),
        (
            "assemble_media",
            Assemble,
            {**WRITE_BASE, "kind": "final", "scene_id": None},
            {**WRITE_BASE, "kind": "final", "scene_id": SCENE_ID},
        ),
    ],
)
def test_action_conditionals_match_schema_and_runtime(name, model, valid, invalid):
    validator = Draft202012Validator(tool_schema(name, model))
    Draft202012Validator.check_schema(validator.schema)
    assert validator.is_valid(valid)
    assert model.model_validate(valid)
    assert not validator.is_valid(invalid)
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


@pytest.mark.parametrize("name", ["edit_script", "edit_keyframes", "edit_locations"])
def test_typed_operation_unions_are_already_exact_discriminated_branches(name):
    schema = tool_schema(name, MODELS[name])
    Draft202012Validator.check_schema(schema)
    items = schema["properties"]["operations"]["items"]
    # 按 op 判别：一个字段错只落在对应分支，不对每个分支各报一遍。
    assert items["discriminator"]["propertyName"] == "op"
    alternatives = items["oneOf"]
    assert alternatives
    for alternative in alternatives:
        definition = schema["$defs"][alternative["$ref"].removeprefix("#/$defs/")]
        assert definition["additionalProperties"] is False
        assert "const" in definition["properties"]["op"]


DETAILS_BASE = {"project_id": "a" * 32}


@pytest.mark.parametrize(
    "arguments",
    [
        {"kind": "director_plan"},
        {"kind": "keyframe", "ids": [SEGMENT_ID]},
        {"kind": "location_image", "ids": [SCENE_ID, SHOT_ID]},
    ],
)
def test_read_details_legal_combinations_match_schema_and_runtime(arguments):
    value = {**DETAILS_BASE, **arguments}
    Draft202012Validator(tool_schema("read_details", DetailsRead)).validate(value)
    DetailsRead.model_validate(value)


@pytest.mark.parametrize(
    "arguments",
    [
        {"kind": "director_plan", "ids": [SCENE_ID]},
        {"kind": "keyframe"},
        {"kind": "character", "ids": [f"{index:032x}" for index in range(21)]},
    ],
)
def test_read_details_illegal_combinations_fail_schema_and_runtime(arguments):
    value = {**DETAILS_BASE, **arguments}
    assert list(Draft202012Validator(tool_schema("read_details", DetailsRead)).iter_errors(value))
    with pytest.raises(ValidationError):
        DetailsRead.model_validate(value)


def test_read_details_translates_to_core_get_details():
    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            result = await client.call_tool(
                "read_details", {**DETAILS_BASE, "kind": "keyframe", "ids": [SEGMENT_ID]}
            )
            plan = await client.call_tool("read_details", {**DETAILS_BASE, "kind": "director_plan"})
        assert not result.is_error and not plan.is_error
        assert [(name, arguments) for _, name, _, _, arguments in bridge.calls] == [
            ("project.get_details", {"kind": "keyframe", "ids": [SEGMENT_ID]}),
            ("project.get_details", {"kind": "director_plan"}),
        ]

    asyncio.run(run())
