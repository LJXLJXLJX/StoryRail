"""proposal 的公开 schema、MCP runtime 与下游 Core 参数保持同一 action 契约。"""

import asyncio
import itertools

import pytest
from jsonschema import Draft202012Validator
from mcp import Client

from integrations.storyrail_mcp.app import (
    PROPOSAL_ACTION_FIELDS,
    PlanningProposal,
    Proposal,
    create_server,
    proposal_fields,
    supplied_proposal_fields,
    tool_schema,
)

BASE = {"project_id": "a" * 32, "expected_revision": 1, "idempotency_key": "request"}
NAMES = {
    "script_proposal": (Proposal, "script"),
    "reference_proposal": (Proposal, "reference"),
    "location_proposal": (Proposal, "location"),
    "keyframe_proposal": (PlanningProposal, "keyframe"),
}
ACTIONS = ("request", "get", "submit", "reject", "cancel")


def valid_arguments(name, action):
    result = {**BASE, "action": action}
    if action == "request":
        result["raw_user_instruction"] = "按当前事实规划"
        if name == "keyframe_proposal":
            result.update(scene_ids=["b" * 32], target_ids=["c" * 32])
    else:
        result["request_id"] = "d" * 32
        if action == "submit":
            result["proposal"] = {}
        elif action == "reject":
            result["reason"] = "用户要求重做"
    return result


def expected_core_call(name, action, arguments):
    prefix = NAMES[name][1]
    core_arguments = {
        key: arguments[key] for key in proposal_fields(name, action) if key not in {"scene_ids"}
    }
    if action == "request" and name == "keyframe_proposal":
        core_arguments["scope"] = {"scene_ids": arguments["scene_ids"]}
    return (
        arguments["project_id"],
        f"{prefix}.{action}_proposal",
        arguments["expected_revision"],
        arguments["idempotency_key"],
        core_arguments,
    )


class RecordingBridge:
    def __init__(self):
        self.calls = []

    async def call(self, project_id, name, revision, key, arguments):
        self.calls.append((project_id, name, revision, key, arguments))
        return 200, {"data": {"accepted": True}}


@pytest.mark.parametrize("name,action", list(itertools.product(NAMES, ACTIONS)))
def test_action_matrix_schema_runtime_and_core_arguments(name, action):
    model = NAMES[name][0]
    schema = tool_schema(name, model)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    arguments = valid_arguments(name, action)
    assert validator.is_valid(arguments)

    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            for required in proposal_fields(name, action):
                invalid = {**arguments, required: None}
                assert not validator.is_valid(invalid)
                rejected = await client.call_tool(name, invalid)
                assert rejected.is_error
            forbidden = next(
                field
                for field in (
                    "raw_user_instruction",
                    "request_id",
                    "proposal",
                    "reason",
                    "scene_ids",
                    "target_ids",
                )
                if field not in proposal_fields(name, action)
            )
            explicit_null = {**arguments, forbidden: None}
            assert validator.is_valid(explicit_null)
            assert not (await client.call_tool(name, explicit_null)).is_error
            forbidden_value = {**arguments, forbidden: _forbidden_value(forbidden)}
            assert not validator.is_valid(forbidden_value)
            assert (await client.call_tool(name, forbidden_value)).is_error
        expected = expected_core_call(name, action, arguments)
        assert bridge.calls == [expected, expected]

    asyncio.run(run())


def _forbidden_value(field):
    if field in {"scene_ids", "target_ids"}:
        return ["e" * 32]
    if field == "proposal":
        return {}
    if field == "request_id":
        return "e" * 32
    return "不属于当前 action"


@pytest.mark.parametrize("name,action", list(itertools.product(NAMES, ACTIONS)))
def test_connector_inflated_nulls_are_omitted_but_required_nulls_are_rejected(name, action):
    model = NAMES[name][0]
    arguments = valid_arguments(name, action)
    inactive = {
        field: None
        for field in (
            "raw_user_instruction",
            "request_id",
            "proposal",
            "reason",
            "scene_ids",
            "target_ids",
        )
        if field in model.model_fields and field not in proposal_fields(name, action)
    }
    inflated = {**arguments, **inactive}
    validator = Draft202012Validator(tool_schema(name, model))
    assert validator.is_valid(inflated)
    parsed = model.model_validate(inflated)
    assert supplied_proposal_fields(parsed) == proposal_fields(name, action)

    required = next(iter(proposal_fields(name, action)))
    assert not validator.is_valid({**inflated, required: None})
    with pytest.raises(ValueError):
        model.model_validate({**inflated, required: None})

    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            result = await client.call_tool(name, inflated)
            assert not result.is_error, result
        assert bridge.calls == [expected_core_call(name, action, arguments)]

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,model",
    [
        ("script_proposal", Proposal),
        ("reference_proposal", Proposal),
        ("location_proposal", Proposal),
        ("keyframe_proposal", PlanningProposal),
    ],
)
def test_submit_schema_rejects_reason_without_exposing_business_content(name, model):
    validator = Draft202012Validator(tool_schema(name, model))
    good = {**BASE, "action": "submit", "request_id": "b" * 32, "proposal": {}}
    assert validator.is_valid(good)
    assert not validator.is_valid({**good, "reason": "只允许reject"})
    assert not validator.is_valid({**good, "raw_user_instruction": "不能覆盖原范围"})
    rejected = {**BASE, "action": "reject", "request_id": "b" * 32, "reason": "拒绝"}
    assert validator.is_valid(rejected)


def test_planning_schema_exposes_exact_request_scope_option():
    common = {**BASE, "action": "request", "raw_user_instruction": "规划", "scene_ids": ["b" * 32]}
    keyframe = Draft202012Validator(tool_schema("keyframe_proposal", PlanningProposal))
    assert keyframe.is_valid({**common, "target_ids": ["c" * 32]})
    assert not keyframe.is_valid(common)
    assert not keyframe.is_valid({**common, "target_ids": ["c" * 32], "replace_existing": True})


@pytest.mark.parametrize("name", NAMES)
def test_text_and_array_constraints_match_runtime(name):
    model = NAMES[name][0]
    validator = Draft202012Validator(tool_schema(name, model))
    invalid = valid_arguments(name, "request")
    invalid["raw_user_instruction"] = " \n\t "
    assert not validator.is_valid(invalid)
    if name == "keyframe_proposal":
        for field, value in (("scene_ids", []), ("scene_ids", "b" * 32), ("target_ids", [])):
            malformed = {**valid_arguments(name, "request"), field: value}
            assert not validator.is_valid(malformed)
        wrong_scope = valid_arguments(name, "request")
        wrong_scope.pop("scene_ids")
        wrong_scope.pop("target_ids")
        assert not validator.is_valid(wrong_scope)
    else:
        wrong_scope = None

    submit_with_reason = {**valid_arguments(name, "submit"), "reason": "只属于 reject"}
    assert not validator.is_valid(submit_with_reason)
    blank_reason = {**valid_arguments(name, "reject"), "reason": " \n "}
    assert not validator.is_valid(blank_reason)

    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            assert (await client.call_tool(name, invalid)).is_error
            if name == "keyframe_proposal":
                malformed = {**valid_arguments(name, "request"), "scene_ids": []}
                assert (await client.call_tool(name, malformed)).is_error
            if wrong_scope is not None:
                assert (await client.call_tool(name, wrong_scope)).is_error
            assert (await client.call_tool(name, submit_with_reason)).is_error
            assert (await client.call_tool(name, blank_reason)).is_error
        assert not bridge.calls

    asyncio.run(run())


def test_mcp_rejection_explains_action_fields_without_echoing_input(tmp_path):
    import asyncio

    from mcp import Client
    from test_external_reference_proposals import empty_project
    from test_external_script_proposals import agent
    from test_storyrail_mcp import endpoint

    from core.director_commands import DirectorCommand

    async def run():
        store, service = await empty_project(tmp_path)
        d = store.read()
        command = DirectorCommand(
            "reference.request_proposal", d.revision, "start", {"raw_user_instruction": "整理"}
        )
        caller = agent(d, command)
        before = store.path.read_bytes()
        with endpoint(tmp_path, store, service, caller) as (params, _):
            async with Client(params) as client:
                result = await client.call_tool(
                    "script_proposal",
                    {
                        **BASE,
                        "project_id": d.project_id,
                        "action": "submit",
                        "request_id": "b" * 32,
                        "proposal": {},
                        "reason": "private-customer-content",
                    },
                )
                message = result.structured_content["error"]["message"]
                assert result.is_error and "submit" in message and "request_id" in message
                assert "private-customer-content" not in message
        assert store.path.read_bytes() == before

    asyncio.run(run())


@pytest.mark.parametrize("name,action", list(itertools.product(NAMES, ACTIONS)))
def test_submit_proposal_publishes_exact_payload_per_action(name, action):
    """统一入口的 payload 按 action 给出完整字段，不依赖未发布的旧工具 schema。"""
    from integrations.storyrail_mcp.app import SubmitProposal, published_tool_schema

    capability = {"reference": "reference_library"}.get(NAMES[name][1], NAMES[name][1])
    schema = published_tool_schema("submit_proposal", SubmitProposal)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    arguments = valid_arguments(name, action)
    payload = {key: value for key, value in arguments.items() if key not in BASE}
    wrapped = {**BASE, "capability": capability, "payload": payload}
    assert validator.is_valid(wrapped)
    assert not validator.is_valid({**wrapped, "payload": {**payload, "unknown": 1}})
    missing = sorted(PROPOSAL_ACTION_FIELDS[action])[0]
    assert not validator.is_valid(
        {**wrapped, "payload": {k: v for k, v in payload.items() if k != missing}}
    )
    scope_missing = None
    if name == "keyframe_proposal" and action == "request":
        scope_missing = {
            **wrapped,
            "payload": {k: v for k, v in payload.items() if k != "scene_ids"},
        }
        assert not validator.is_valid(scope_missing)
    if name != "keyframe_proposal" and action == "request":
        # 项目级 capability 不接受 keyframe 的 scope 字段。
        assert not validator.is_valid({**wrapped, "payload": {**payload, "scene_ids": ["b" * 32]}})

    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            result = await client.call_tool("submit_proposal", wrapped)
            assert not result.is_error, result
            bad = await client.call_tool(
                "submit_proposal", {**wrapped, "payload": {**payload, "unknown": 1}}
            )
            assert bad.is_error
            assert "submit→request_id、proposal" in bad.structured_content["error"]["message"]
            if scope_missing is not None:
                assert (await client.call_tool("submit_proposal", scope_missing)).is_error
        assert bridge.calls == [expected_core_call(name, action, arguments)]

    asyncio.run(run())
