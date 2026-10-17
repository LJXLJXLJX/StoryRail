"""Agent-visible failures identify their layer, mutation certainty and safe recovery."""

import asyncio
import json

from mcp import Client
from test_external_production import service as production_service
from test_external_production import setup as production_setup
from test_external_reference_proposals import empty_project
from test_external_script_proposals import agent, command, http

from core.director_commands import DirectorCommand
from core.model_providers.boundary import GenerationPhase
from core.structured_director import StructuredDirectorService, StructuredDirectorStore
from core.structured_director.http_api import StructuredDirectorHttpApi
from integrations.storyrail_mcp.app import create_server
from integrations.storyrail_mcp.bridge import CoreBridge


class RecordingBridge:
    def __init__(self):
        self.calls = []

    async def call(self, project_id, name, revision, key, arguments):
        self.calls.append((project_id, name, revision, key, arguments))
        return 200, {"data": {"accepted": True}}


def _assert_error_contract(error, *, origin, retry_policy, state_changed=False):
    assert set(
        (
            "code",
            "message",
            "recoverable",
            "origin",
            "state_changed",
            "retry_policy",
            "automatic_retry_allowed",
        )
    ) <= set(error)
    assert error["origin"] == origin
    assert error["state_changed"] is state_changed
    assert error["retry_policy"] == retry_policy
    assert isinstance(error["recoverable"], bool)
    assert isinstance(error["message"], str) and error["message"]
    assert error["automatic_retry_allowed"] is False


def test_mcp_schema_error_is_local_and_does_not_reach_core():
    async def run():
        bridge = RecordingBridge()
        async with Client(create_server(bridge)) as client:
            result = await client.call_tool(
                "read_story",
                {
                    "project_id": "a" * 32,
                    "level": "outline",
                    "extensions": ["keyframe"],
                },
            )
        assert result.is_error
        assert result.structured_content["http_status"] == 400
        error = result.structured_content["error"]
        assert error["code"] == "invalid_arguments"
        _assert_error_contract(
            error,
            origin="mcp_schema",
            retry_policy="fix_arguments_and_retry",
        )
        assert bridge.calls == []

    asyncio.run(run())


def test_connector_serialization_error_is_not_reported_as_core_rejection(tmp_path):
    token = tmp_path / "token"
    token.write_text("a" * 32)
    token.chmod(0o600)
    status, value = CoreBridge("http://127.0.0.1:1", token)._send(
        "a" * 32,
        "project.get_handoff",
        None,
        "read",
        {"not_finite": float("nan")},
    )
    assert status == 400
    error = value["error"]
    assert error["code"] == "connector_serialization_error"
    _assert_error_contract(
        error,
        origin="connector_serialization",
        retry_policy="fix_arguments_and_retry",
    )


def test_core_parser_business_revision_and_workflow_errors_are_distinct(tmp_path):
    async def run():
        (tmp_path / "production").mkdir()
        store, provider, document = await production_setup(tmp_path / "production")
        service = production_service(store, provider)

        malformed = {
            "name": "generation.retry",
            "expected_revision": document.revision,
            "idempotency_key": "malformed",
            "arguments": [],
        }
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        parsed = await api.handle(
            "POST",
            "/structured-director/application/commands",
            json.dumps(malformed).encode(),
        )
        assert parsed.status == 400
        assert parsed.body["error"]["code"] == "invalid_request"
        _assert_error_contract(
            parsed.body["error"],
            origin="core_parser",
            retry_policy="fix_arguments_and_retry",
        )

        missing = DirectorCommand(
            "generation.retry",
            store.read().revision,
            "missing-generation",
            {"generation_id": "f" * 32},
        )
        rejected = await http(service, agent(store.read(), missing), missing)
        assert rejected.status == 409
        assert rejected.body["error"]["code"] == "business_rule_rejected"
        _assert_error_contract(
            rejected.body["error"],
            origin="core_domain",
            retry_policy="change_business_state_or_request",
        )

        stale = DirectorCommand(
            "generation.retry",
            store.read().revision - 1,
            "stale-generation",
            {"generation_id": "f" * 32},
        )
        conflict = await http(service, agent(store.read(), stale), stale)
        assert conflict.status == 409
        error = conflict.body["error"]
        assert error["code"] == "revision_conflict"
        assert error["expected_revision"] == stale.expected_revision
        assert error["current_revision"] == store.read().revision
        assert error["automatic_retry_allowed"] is False
        _assert_error_contract(
            error,
            origin="core_revision",
            retry_policy="reread_then_reissue_if_still_intended",
        )

        (tmp_path / "initial").mkdir()
        initial_store, initial_service = await empty_project(tmp_path / "initial")
        initial = initial_store.read()
        early = command(
            "request",
            initial.revision,
            "early-script",
            raw_user_instruction="提前生成脚本",
        )
        blocked = await http(initial_service, agent(initial, early), early)
        assert blocked.status == 409
        error = blocked.body["error"]
        assert error["code"] == "stage_prerequisite_not_met"
        assert error["current_stage"] == "reference_library"
        assert error["required_next_actions"]
        _assert_error_contract(
            error,
            origin="workflow_prerequisite",
            retry_policy="follow_required_next_actions",
        )

    asyncio.run(run())


def test_artifact_import_failure_is_persisted_and_retries_same_generation(tmp_path):
    async def run():
        (tmp_path / "artifact").mkdir()
        store, provider, document = await production_setup(tmp_path / "artifact")
        target_id = document.keyframe_plan.segments[0].start_keyframe_id
        generate = DirectorCommand(
            "keyframe.generate_batch",
            document.revision,
            "artifact-import",
            {"target_ids": [target_id]},
        )
        service = production_service(store, provider)
        submitted = await http(service, agent(document, generate), generate)
        assert submitted.status == 200
        generation_id = store.read().generations[0].id
        provider.observations = [GenerationPhase.SUCCEEDED]
        provider.read_artifact = lambda _handle, _artifact_id: b"corrupt"
        await service._generation_observer.refresh_generation(generation_id)
        generation = store.read().generations[0]
        assert generation.id == generation_id
        assert generation.phase.value == "queued"
        assert generation.error_code == "artifact_import_failed"

        handoff = DirectorCommand(
            "project.get_handoff", store.read().revision, "artifact-handoff", {}
        )
        response = await http(service, agent(store.read(), handoff), handoff)
        tasks = response.body["data"]["task_discovery"]
        task = next(
            item for item in (*tasks["active"], *tasks["recent"]) if item["id"] == generation_id
        )
        assert task["error_code"] == "artifact_import_failed"
        assert task["recovery"] == {
            "failure_origin": "artifact_import",
            "retry_policy": "wait_same_generation",
            "automatic_retry_allowed": False,
        }

    asyncio.run(run())


def test_provider_dependency_failure_is_not_a_revision_or_business_error(tmp_path):
    async def run():
        (tmp_path / "provider").mkdir()
        store, _, document = await production_setup(tmp_path / "provider")
        without_provider = StructuredDirectorService(
            StructuredDirectorStore(store.path.parent, document.project_id)
        )
        target_id = document.keyframe_plan.segments[0].start_keyframe_id
        generate = DirectorCommand(
            "keyframe.generate",
            document.revision,
            "provider-unavailable",
            {"keyframe_id": target_id},
        )
        before = store.path.read_bytes()
        response = await http(without_provider, agent(document, generate), generate)
        assert response.status == 409
        error = response.body["error"]
        assert error["code"] == "provider_unavailable"
        assert error["current_revision"] == document.revision
        _assert_error_contract(
            error,
            origin="provider_boundary",
            retry_policy="restore_dependency_then_replay_same_request",
        )
        assert store.path.read_bytes() == before

        (tmp_path / "provider-batch").mkdir()
        batch_store, _, batch_document = await production_setup(tmp_path / "provider-batch")
        batch_service = StructuredDirectorService(
            StructuredDirectorStore(batch_store.path.parent, batch_document.project_id)
        )
        batch = DirectorCommand(
            "keyframe.generate_batch",
            batch_document.revision,
            "provider-batch-unavailable",
            {"target_ids": [batch_document.keyframe_plan.segments[0].start_keyframe_id]},
        )
        partial = await http(batch_service, agent(batch_document, batch), batch)
        assert partial.status == 200
        assert partial.body["data"]["issues"] == [
            {
                "code": "provider_unavailable",
                "origin": "provider_boundary",
                "state_changed": True,
                "retry_policy": "restore_dependency_then_explicit_batch_continue",
                "automatic_retry_allowed": False,
            }
        ]

    asyncio.run(run())
