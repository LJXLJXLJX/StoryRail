"""外部确定性生产的精确授权、持久批次和人类审核边界。"""

import asyncio
import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from conftest import make_service
from jsonschema import Draft202012Validator
from keyframe_wave_fixtures import FiveShotPlan, FiveShotScript
from structured_director_fixtures import RecordingProvider
from test_director_commands import _visual_project
from test_external_script_proposals import agent, http

from core.director_commands import DirectorCommand
from core.model_providers.boundary import (
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
)
from core.structured_director import StructuredDirectorStore
from integrations.storyrail_mcp.app import project_models, published_tool_schema
from integrations.storyrail_mcp.production_tools import Batch


def assert_workflow_tools_exist(workflow):
    """workflow 输出的任何工具（必需或推荐动作）都必须是真实可调用的 MCP 工具。"""
    tools = project_models()
    for action in (
        *workflow["required_next_actions"],
        *workflow.get("recommended_next_actions", []),
    ):
        for key in ("tool", "verification_tool"):
            name = action.get(key)
            if name is not None:
                assert name in tools, f"workflow 推荐了不存在的 MCP 工具：{name}"


async def setup(tmp_path):
    store, service, doc, _ = await _visual_project(
        str(tmp_path), script_proposer=FiveShotScript(), keyframe_planner=FiveShotPlan()
    )
    doc = await service.prepare_keyframes(expected_revision=doc.revision)
    provider = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nfixture")
    return store, provider, doc


def service(store, provider):
    return make_service(
        StructuredDirectorStore(store.path.parent, store.read().project_id), image_provider=provider
    )


async def call(store, provider, name, key, arguments):
    doc = store.read()
    command = DirectorCommand(name, doc.revision, key, arguments)
    result = await http(service(store, provider), agent(doc, command), command)
    assert result.status == 200, result.body
    return result, command


def test_external_batch_three_waves_replay_and_exact_scope(tmp_path):
    async def run():
        store, provider, doc = await setup(tmp_path)
        first, command = await call(
            store,
            provider,
            "keyframe.generate_batch",
            "batch",
            {"target_ids": [doc.director_script.scenes[0].id]},
        )
        assert len(provider.requests) == 3
        batch_id = first.body["data"]["batch_id"]
        rid = first.body["data"]["execution_run_id"]
        assert first.body["data"]["root_execution_run_id"] == rid
        assert first.body["data"]["previous_execution_run_id"] is None
        assert first.body["data"]["batch_observation"]["phase"] == "awaiting_generations"
        assert not first.body["data"]["batch_observation"]["is_terminal"]
        workflow = first.body["workflow"]
        assert workflow["active_task"]["task_type"] == "keyframe_batch"
        assert workflow["active_task"]["batch_id"] == batch_id
        assert workflow["stage_status"] == "awaiting_generations"
        assert any(
            item["action"] == "generation.wait" for item in workflow["required_next_actions"]
        )
        original_ids = tuple(g.id for g in store.read().generations)
        assert all(g.created_at and g.updated_at for g in store.read().generations)
        record = store.read().application_requests[-1]
        assert record.generation_ids == original_ids and record.phase == "committed"
        handoff = DirectorCommand(
            "project.get_handoff", store.read().revision, "batch-audit-handoff", {}
        )
        discovered = await http(service(store, provider), agent(store.read(), handoff), handoff)
        generation_tasks = {
            item["id"]: item
            for item in (
                *discovered.body["data"]["task_discovery"]["active"],
                *discovered.body["data"]["task_discovery"]["recent"],
            )
            if item["task_type"] == "generation" and item["id"] in original_ids
        }
        assert set(generation_tasks) == set(original_ids)
        assert {item["run_id"] for item in generation_tasks.values()} == {rid}
        assert {item["run_association"] for item in generation_tasks.values()} == {
            "linked_director_run"
        }
        assert {item["timestamp_status"] for item in generation_tasks.values()} == {"complete"}
        cross_caller = DirectorCommand(
            "keyframe.continue_batch",
            store.read().revision,
            "cross-caller",
            {"run_id": batch_id},
        )
        before = store.path.read_bytes()
        denied = await http(
            service(store, provider),
            replace(
                agent(store.read(), cross_caller),
                id="other-agent",
                capabilities=frozenset({"project.read", "project.mutate", "project.execute"}),
                grants=(),
            ),
            cross_caller,
        )
        assert denied.status == 409
        assert denied.body["error"]["code"] == "business_rule_rejected"
        assert store.path.read_bytes() == before and len(provider.requests) == 3
        replay = await http(service(store, provider), agent(doc, command), command)
        assert replay.body["replay"] and len(provider.requests) == 3
        assert replay.body["data"]["execution_run_id"] == rid
        previous_execution_run_id = rid
        for wave, count in [(2, 5), (3, 7)]:
            resumed = service(store, provider)
            for gen in store.read().generations:
                if gen.phase.value == "queued":
                    provider.observations = [GenerationPhase.SUCCEEDED]
                    await resumed._generation_observer.refresh_generation(gen.id)
            batch_read = DirectorCommand(
                "project.get_request",
                store.read().revision,
                f"before-wave-{wave}",
                {"request_key": "batch"},
            )
            observed = await http(
                service(store, provider), agent(store.read(), batch_read), batch_read
            )
            assert (
                observed.body["data"]["result"]["batch_observation"]["phase"]
                == "awaiting_explicit_continue"
            )
            # Agent 只读命令不附主流程；完整 workflow 由 handoff/read_workflow 返回。
            assert "workflow" not in observed.body
            wave_handoff = DirectorCommand(
                "project.get_handoff", store.read().revision, f"handoff-wave-{wave}", {}
            )
            handed = await http(
                service(store, provider), agent(store.read(), wave_handoff), wave_handoff
            )
            workflow = handed.body["data"]["workflow"]
            assert workflow["active_task"]["batch_id"] == batch_id
            assert workflow["active_task"]["batch_kind"] == "keyframe"
            assert workflow["stage_status"] == "awaiting_explicit_continue"
            assert_workflow_tools_exist(workflow)
            continuation = workflow["required_next_actions"][0]
            assert continuation["action"] == "keyframe.continue_batch"
            assert continuation["batch_id"] == batch_id
            # workflow 推荐的必须是真实存在的 MCP 工具，且参数（含 kind）通过该工具的公开 schema。
            assert continuation["tool"] == "media_batch"
            assert continuation["kind"] == "keyframe"
            hinted = {
                "project_id": store.read().project_id,
                "expected_revision": store.read().revision,
                "idempotency_key": f"hinted-wave-{wave}",
                "kind": continuation["kind"],
                "action": continuation["tool_action"],
                "run_id": continuation["batch_id"],
                "target_ids": None,
            }
            Batch.model_validate(hinted)
            assert Draft202012Validator(published_tool_schema("media_batch", Batch)).is_valid(
                hinted
            )
            next_result, _ = await call(
                store,
                provider,
                "keyframe.continue_batch",
                f"wave-{wave}",
                {"run_id": batch_id},
            )
            assert len(provider.requests) == count
            assert next_result.body["data"]["batch_id"] == batch_id
            assert next_result.body["data"]["root_execution_run_id"] == rid
            assert (
                next_result.body["data"]["previous_execution_run_id"] == previous_execution_run_id
            )
            previous_execution_run_id = next_result.body["data"]["execution_run_id"]
            assert previous_execution_run_id != rid
            assert next_result.body["data"]["batch_observation"]["phase"] == (
                "awaiting_generations"
            )
        scope = set(first.body["data"]["target_ids"])
        assert {g.target_id for g in store.read().generations} <= scope
        assert tuple(g.id for g in store.read().generations[:3]) == original_ids
        malicious = DirectorCommand(
            "keyframe.continue_batch",
            store.read().revision,
            "expand",
            {"run_id": batch_id, "target_ids": [doc.director_script.scenes[1].id]},
        )
        result = await http(service(store, provider), agent(store.read(), malicious), malicious)
        assert result.status == 400

        resumed = service(store, provider)
        for generation in store.read().generations:
            if generation.phase.value == "queued":
                provider.observations = [GenerationPhase.SUCCEEDED]
                await resumed._generation_observer.refresh_generation(generation.id)
        lookup = DirectorCommand(
            "project.get_request", store.read().revision, "batch-get", {"request_key": "batch"}
        )
        observed = await http(service(store, provider), agent(store.read(), lookup), lookup)
        batch = observed.body["data"]["result"]["batch_observation"]
        assert batch["batch_id"] == batch_id
        assert batch["phase"] == "completed"
        assert batch["is_terminal"] and batch["all_succeeded"]
        assert len(batch["executions"]) == 3
        assert {item["status"] for item in batch["targets"]} == {"succeeded"}

        independent, _ = await call(
            store,
            provider,
            "keyframe.generate_batch",
            "independent-batch",
            {"target_ids": [doc.director_script.scenes[0].id]},
        )
        assert independent.body["data"]["batch_id"] != batch_id
        assert not independent.body["data"]["generation_ids"]

    asyncio.run(run())


def test_single_generation_persists_own_timestamps_and_explains_missing_run(tmp_path):
    async def run():
        store, provider, doc = await setup(tmp_path)
        keyframe_id = doc.keyframe_plan.segments[0].start_keyframe_id
        started, command = await call(
            store,
            provider,
            "keyframe.generate",
            "single-generation-audit",
            {"keyframe_id": keyframe_id},
        )
        generation_id = started.body["data"]["generation_ids"][0]
        generation = next(item for item in store.read().generations if item.id == generation_id)
        assert generation.created_at is not None
        assert generation.updated_at is not None
        assert generation.updated_at >= generation.created_at

        handoff = DirectorCommand(
            "project.get_handoff", store.read().revision, "single-handoff", {}
        )
        response = await http(service(store, provider), agent(store.read(), handoff), handoff)
        tasks = response.body["data"]["task_discovery"]
        task = next(
            item
            for item in (*tasks["active"], *tasks["recent"])
            if item["task_type"] == "generation" and item["id"] == generation_id
        )
        assert task["created_at"] == generation.created_at
        assert task["updated_at"] == generation.updated_at
        assert task["timestamp_status"] == "complete"
        assert task["run_id"] is None
        assert task["run_association"] == "not_applicable_single_generation"
        assert task["request_association"] == "current_caller"
        assert task["application_request_id"] == started.body["application_request_id"]
        assert task["request_key"] == "single-generation-audit"
        assert task["origin_operation"] == "keyframe.generate"

        before_update = generation.updated_at
        provider.observations = [GenerationPhase.RUNNING]
        await service(store, provider)._generation_observer.refresh_generation(generation_id)
        running = next(item for item in store.read().generations if item.id == generation_id)
        assert running.created_at == generation.created_at
        assert running.updated_at is not None and running.updated_at > before_update
        running_revision = store.read().revision
        provider.observations = [GenerationPhase.RUNNING]
        await service(store, provider)._generation_observer.refresh_generation(generation_id)
        unchanged = next(item for item in store.read().generations if item.id == generation_id)
        assert unchanged.updated_at == running.updated_at
        assert store.read().revision == running_revision

        provider.observations = [GenerationPhase.SUCCEEDED]
        await service(store, provider)._generation_observer.refresh_generation(generation_id)
        succeeded = next(item for item in store.read().generations if item.id == generation_id)
        assert succeeded.phase.value == "succeeded"
        assert succeeded.created_at == generation.created_at
        assert succeeded.updated_at is not None and succeeded.updated_at > running.updated_at

        replay = await http(service(store, provider), agent(doc, command), command)
        assert replay.body["replay"]
        assert len(store.read().generations) == 1

        other_handoff = DirectorCommand(
            "project.get_handoff", store.read().revision, "other-handoff", {}
        )
        other = replace(
            agent(store.read(), other_handoff),
            id="other-agent",
            capabilities=frozenset({"project.read"}),
            grants=(),
            mutations_enabled=False,
        )
        redacted = await http(service(store, provider), other, other_handoff)
        redacted_tasks = redacted.body["data"]["task_discovery"]
        redacted_task = next(
            item
            for item in (*redacted_tasks["active"], *redacted_tasks["recent"])
            if item["task_type"] == "generation" and item["id"] == generation_id
        )
        assert redacted_task["request_association"] == "other_caller_redacted"
        assert redacted_task["application_request_id"] is None
        assert redacted_task["request_key"] is None

    asyncio.run(run())


def test_batch_interruption_persists_all_submitted_jobs_and_recovers_without_repeating(tmp_path):
    async def run():
        store, provider, doc = await setup(tmp_path)
        command = DirectorCommand(
            "keyframe.generate_batch",
            doc.revision,
            "interrupted",
            {"target_ids": [doc.director_script.scenes[0].id]},
        )
        running = service(store, provider)
        original = running._store.set_director_run_cursor

        def interrupt(**kwargs):
            if kwargs["cursor"].step == 2:
                raise asyncio.CancelledError()
            return original(**kwargs)

        with (
            patch.object(running._store, "set_director_run_cursor", interrupt),
            pytest.raises(asyncio.CancelledError),
        ):
            await http(running, agent(doc, command), command)
        assert len(provider.requests) == 2
        interrupted = store.read()
        assert len(interrupted.application_requests[-1].generation_ids) == 2
        run_id = interrupted.active_director_run.id
        batch_id = json.loads(interrupted.application_requests[-1].receipt_json)["data"]["batch_id"]
        replay = await http(service(store, provider), agent(doc, command), command)
        assert replay.body["replay"] and len(provider.requests) == 2
        lookup = DirectorCommand(
            "project.get_request", store.read().revision, "lookup", {"request_key": "interrupted"}
        )
        record = await http(service(store, provider), agent(store.read(), lookup), lookup)
        assert record.body["data"]["phase"] == "uncertain"
        assert record.body["data"]["result"]["batch_run_id"] == run_id
        await call(store, provider, "run.cancel", "cancel-run", {"run_id": run_id})
        continued, _ = await call(
            store, provider, "keyframe.continue_batch", "continue", {"run_id": batch_id}
        )
        assert continued.body["data"]["batch_id"] == batch_id
        assert continued.body["data"]["previous_execution_run_id"] == run_id
        assert len(provider.requests) == 3
        assert len({g.id for g in store.read().generations}) == 3

    asyncio.run(run())


def test_batch_observation_reports_failed_cancelled_and_uncertain_without_retry(tmp_path):
    class FailedObservationProvider(RecordingProvider):
        def observe(self, _handle):
            return GenerationObservation(
                GenerationPhase.FAILED,
                1.0,
                "生成失败",
                error_code="provider_failed",
            )

    class UncertainSubmitProvider(RecordingProvider):
        def submit_recipe(self, request):
            return self.submit_generate(request)

        def submit_generate(self, request):
            self.requests.append(request)
            raise ModelProviderError("transport_error", "提交响应丢失", retryable=True)

        def submit_edit(self, request):
            return self.submit_generate(request)

    async def single_batch(path, provider, key):
        path.mkdir()
        store, _, doc = await setup(path)
        target_id = doc.keyframe_plan.segments[0].start_keyframe_id
        result, _ = await call(
            store,
            provider,
            "keyframe.generate_batch",
            key,
            {"target_ids": [target_id]},
        )
        return store, provider, result, target_id

    async def run():
        failed_provider = FailedObservationProvider(
            media_type="image/png", content=b"\x89PNG\r\n\x1a\nfailed"
        )
        failed_store, _, failed, _ = await single_batch(
            tmp_path / "failed", failed_provider, "failed-batch"
        )
        await service(failed_store, failed_provider)._generation_observer.refresh_generation(
            failed_store.read().generations[0].id
        )
        failed_read = DirectorCommand(
            "project.get_request",
            failed_store.read().revision,
            "failed-read",
            {"request_key": "failed-batch"},
        )
        response = await http(
            service(failed_store, failed_provider),
            agent(failed_store.read(), failed_read),
            failed_read,
        )
        observation = response.body["data"]["result"]["batch_observation"]
        assert observation["phase"] == "completed_with_issues"
        assert observation["is_terminal"] and not observation["all_succeeded"]
        assert observation["targets"][0]["status"] == "failed"
        failed_handoff = DirectorCommand(
            "project.get_handoff", failed_store.read().revision, "failed-handoff", {}
        )
        failed_tasks = (
            await http(
                service(failed_store, failed_provider),
                agent(failed_store.read(), failed_handoff),
                failed_handoff,
            )
        ).body["data"]["task_discovery"]
        failed_task = next(
            item
            for item in (*failed_tasks["active"], *failed_tasks["recent"])
            if item["task_type"] == "generation"
        )
        assert failed_task["error_code"] == "provider_failed"
        assert failed_task["recovery"] == {
            "failure_origin": "provider_generation",
            "retry_policy": "explicit_generation_retry_if_inputs_unchanged",
            "automatic_retry_allowed": False,
        }

        cancelled_store, cancelled_provider, cancelled, _ = await single_batch(
            tmp_path / "cancelled",
            RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\ncancel"),
            "cancelled-batch",
        )
        generation_id = cancelled_store.read().generations[0].id
        await call(
            cancelled_store,
            cancelled_provider,
            "generation.cancel",
            "cancel-generation",
            {"generation_id": generation_id},
        )
        batch_id = cancelled.body["data"]["batch_id"]
        run_read = DirectorCommand(
            "run.get_status",
            cancelled_store.read().revision,
            "cancelled-read",
            {"run_id": cancelled.body["data"]["execution_run_id"]},
        )
        response = await http(
            service(cancelled_store, cancelled_provider),
            agent(cancelled_store.read(), run_read),
            run_read,
        )
        observation = response.body["data"]["batch_observation"]
        assert observation["batch_id"] == batch_id
        assert observation["phase"] == "completed_with_issues"
        assert observation["targets"][0]["status"] == "cancelled"

        uncertain_provider = UncertainSubmitProvider(
            media_type="image/png", content=b"\x89PNG\r\n\x1a\nuncertain"
        )
        uncertain_store, _, uncertain, _ = await single_batch(
            tmp_path / "uncertain", uncertain_provider, "uncertain-batch"
        )
        observation = uncertain.body["data"]["batch_observation"]
        assert observation["phase"] == "needs_attention"
        assert not observation["is_terminal"] and not observation["all_succeeded"]
        assert observation["targets"][0]["status"] == "submission_uncertain"
        assert len(uncertain_provider.requests) == 1
        uncertain_generation = uncertain_store.read().generations[0]
        assert uncertain_generation.created_at is not None
        assert uncertain_generation.updated_at is not None
        handoff = DirectorCommand(
            "project.get_handoff", uncertain_store.read().revision, "handoff", {}
        )
        response = await http(
            service(uncertain_store, uncertain_provider),
            agent(uncertain_store.read(), handoff),
            handoff,
        )
        tasks = response.body["data"]["task_discovery"]
        batch_tasks = [
            item
            for item in (*tasks["active"], *tasks["recent"])
            if item["batch_id"] == uncertain.body["data"]["batch_id"]
        ]
        assert batch_tasks
        uncertain_task = next(item for item in batch_tasks if item["task_type"] == "generation")
        assert uncertain_task["timestamp_status"] == "complete"
        assert uncertain_task["request_association"] == "current_caller"
        assert uncertain_task["application_request_id"] is not None
        assert uncertain_task["error_code"] == "transport_error"
        assert uncertain_task["cancellation_requested"] is False
        assert uncertain_task["retry_of"] is None
        assert uncertain_task["recovery"] == {
            "failure_origin": "provider_submission",
            "retry_policy": "inspect_then_explicit_generation_retry",
            "automatic_retry_allowed": False,
        }
        batch_observations = [
            item
            for item in tasks["batches"]
            if item["batch_id"] == uncertain.body["data"]["batch_id"]
        ]
        assert len(batch_observations) == 1
        assert batch_observations[0]["phase"] == "needs_attention"

    asyncio.run(run())


def test_agent_cannot_review_select_or_approve_even_with_exact_grant(tmp_path):
    async def run():
        store, provider, doc = await setup(tmp_path)
        before = store.path.read_bytes()
        for name, args in [
            ("script.confirm", {}),
            ("final.approve", {"asset_id": "f" * 32}),
            ("final.select_candidate", {"generation_id": "f" * 32}),
            ("final.reopen_production", {}),
        ]:
            cmd = DirectorCommand(name, doc.revision, name, args)
            result = await http(service(store, provider), agent(doc, cmd), cmd)
            assert result.status == 403
        read = DirectorCommand("project.get_handoff", doc.revision, "handoff", {})
        result = await http(service(store, provider), agent(doc, read), read)
        assert result.body["data"]["web_path"] == f"/?project={doc.project_id}"
        assert "candidate_selection" in result.body["data"]["human_only"]
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_mixed_tts_keyframe_video_final_use_external_application_commands(tmp_path):
    from test_architecture_acceptance import mixed_acceptance

    from core.application.caller import current_caller

    seen = []

    class External:
        def __init__(self, original):
            self.original = original

        class _MediaProxy:
            def __init__(self, outer):
                self._outer = outer

            def __getattr__(self, name):
                if name != "generate_segment_video":
                    return getattr(self._outer.original._media, name)
                return self._outer.__getattr__("generate_segment_video")

        def __getattr__(self, name):
            names = {
                "generate_narration": "narration.generate",
                "generate_keyframe": "keyframe.generate",
                "generate_segment_video": "video.generate",
                "generate_scene_final_video": "final.assemble_scene",
                "generate_final_video": "final.assemble",
            }
            if name == "_media":
                return External._MediaProxy(self)
            if name not in names:
                return getattr(self.original, name)

            async def invoke(**args):
                assert current_caller.get() is None
                revision = args.pop("expected_revision")
                command = DirectorCommand(names[name], revision, f"{name}:{revision}", args)
                document = self.original._store.read()
                result = await http(self.original, agent(document, command), command)
                assert result.status == 200, result.body
                before = self.original._store.path.read_bytes()
                replay = await http(self.original, agent(document, command), command)
                assert replay.body["replay"]
                assert self.original._store.path.read_bytes() == before
                seen.append(names[name])
                return self.original._store.read()

            return invoke

    result = asyncio.run(mixed_acceptance(tmp_path, External))
    assert result.final_approval is not None
    assert set(seen) == {
        "narration.generate",
        "keyframe.generate",
        "video.generate",
        "final.assemble_scene",
        "final.assemble",
    }


def test_external_upscale_animatic_scene_assembly_observation_cancel_retry(tmp_path, monkeypatch):
    from test_architecture_acceptance import mixed_acceptance

    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", "0")

    async def run():
        doc = await mixed_acceptance(tmp_path)
        store = StructuredDirectorStore(tmp_path, doc.project_id)
        media = RecordingProvider(
            media_type="video/mp4", content=b"\0\0\0\x18ftypmp42fixture", duration_seconds=8
        )
        core = make_service(
            store, upscale_provider=media, animatic_provider=media, final_assembly_provider=media
        )
        doc = await core.reopen_video_production(
            expected_revision=doc.revision
        )  # human fixture action

        async def command(name, args, key):
            before = store.read()
            cmd = DirectorCommand(name, before.revision, key, args)
            response = await http(core, agent(before, cmd), cmd)
            assert response.status == 200, response.body
            count = len(media.requests)
            replay = await http(core, agent(before, cmd), cmd)
            if name == "generation.wait":
                assert "replay" not in replay.body and len(media.requests) == count
            else:
                assert replay.body["replay"] and len(media.requests) == count
            return store.read()

        scene = doc.director_script.scenes[0]
        for name, args in [
            ("video.upscale", {"segment_id": scene.segments[0].id}),
            ("animatic.generate_scene", {"scene_id": scene.id}),
            ("final.assemble_scene", {"scene_id": scene.id}),
        ]:
            doc = await command(name, args, name)
            generation = doc.generations[-1]
            assert generation.external_id is not None
            doc = await command(
                "generation.cancel", {"generation_id": generation.id}, "cancel-" + name
            )
            assert (
                next(g for g in doc.generations if g.id == generation.id).phase.value == "cancelled"
            )
            doc = await command(
                "generation.retry", {"generation_id": generation.id}, "retry-" + name
            )
            retry = doc.generations[-1]
            assert retry.id != generation.id
            assert retry.retry_of == generation.id
            assert retry.created_at is not None and retry.updated_at is not None
            assert retry.created_at >= generation.created_at
            media.observations = [GenerationPhase.SUCCEEDED]
            await command(
                "generation.wait", {"generation_ids": [doc.generations[-1].id]}, "wait-" + name
            )

    asyncio.run(run())


def test_external_visual_unlock_is_repeatable_and_preserves_locations(tmp_path):
    from structured_director_fixtures import install_location
    from test_director_commands import _location_project

    async def run():
        store, _, doc, _ = await _location_project(str(tmp_path))
        provider = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nfixture")
        install_location(store, name="未绑定地点")
        await call(store, provider, "visual_production.unlock", "unlock", {})
        plan = store.read().keyframe_plan
        locations = store.read().location_library
        await call(store, provider, "visual_production.unlock", "unlock-again", {})
        assert store.read().keyframe_plan == plan and store.read().location_library == locations
        assert provider.requests == []

    asyncio.run(run())


def test_agent_edits_looks_and_generates_sheet_idempotently(tmp_path):
    from test_keyframe_character_references import _project_with_costumes

    async def run():
        store, _service, doc, _keyframe_id = await _project_with_costumes(tmp_path)
        provider = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nfixture")
        card = doc.reference_library.characters[0]
        added, _command = await call(
            store,
            provider,
            "reference.apply_look_operations",
            "add-look",
            {
                "operations": [
                    {
                        "op": "add_look",
                        "character_id": card.id,
                        "name": "雨衣",
                        "appearance": "黄色雨衣，湿透的头发",
                        "usage": "暴雨夜的追逐戏",
                    }
                ]
            },
        )
        look = store.read().reference_library.characters[0].looks[-1]
        assert look.name == "雨衣" and look.selected_asset_id is None
        arguments = {"look_id": look.id, "identity_asset_ids": [card.looks[0].selected_asset_id]}
        result, command = await call(
            store, provider, "reference.generate_look_sheet", "sheet", arguments
        )
        assert len(provider.requests) == 1 and provider.requests[0].param("aspect_ratio") == "2:1"
        generation = store.read().generations[-1]
        assert (generation.target_id, generation.aspect_ratio) == (look.id, "2:1")
        replay = await http(service(store, provider), agent(store.read(), command), command)
        assert replay.status == 200 and len(provider.requests) == 1
        bad = DirectorCommand(
            "reference.generate_look_sheet",
            store.read().revision,
            "bad",
            {**arguments, "identity_asset_ids": "not-a-list"},
        )
        rejected = await http(service(store, provider), agent(store.read(), bad), bad)
        assert rejected.status == 400 and len(provider.requests) == 1
        assert added is not None and result is not None

    asyncio.run(run())


def test_agent_selects_keyframe_candidate_and_human_can_reselect(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", "0")

    async def run():
        store, provider, doc = await setup(tmp_path)
        keyframe_id = doc.keyframe_plan.segments[0].start_keyframe_id
        generation_ids = []
        for key in ("kf-a", "kf-b"):
            started, _ = await call(
                store, provider, "keyframe.generate", key, {"keyframe_id": keyframe_id}
            )
            generation_ids.append(started.body["data"]["generation_ids"][0])
            provider.observations = [GenerationPhase.SUCCEEDED]
            await call(
                store,
                provider,
                "generation.wait",
                "wait-" + key,
                {"generation_ids": generation_ids[-1:]},
            )
        first, second = (
            next(g for g in store.read().generations if g.id == gid) for gid in generation_ids
        )
        assert first.output_asset_id and second.output_asset_id

        selected, command = await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-a",
            {"keyframe_id": keyframe_id, "generation_id": first.id},
        )
        assert selected.body["receipt"]["changed_ids"] == [keyframe_id]
        keyframe = next(k for k in store.read().keyframe_plan.keyframes if k.id == keyframe_id)
        assert keyframe.selected_asset_id == first.output_asset_id
        before = store.path.read_bytes()
        replay = await http(service(store, provider), agent(doc, command), command)
        assert replay.body["replay"] and store.path.read_bytes() == before

        # 别的 Keyframe 的候选不能借用。
        other_id = doc.keyframe_plan.segments[0].end_keyframe_id
        wrong = DirectorCommand(
            "keyframe.select_candidate",
            store.read().revision,
            "select-wrong",
            {"keyframe_id": other_id, "generation_id": second.id},
        )
        denied = await http(service(store, provider), agent(store.read(), wrong), wrong)
        assert denied.status != 200
        assert store.path.read_bytes() == before

        # 人类改选与 Agent 写同一字段，Agent 之后仍可再次改选。
        current = await service(store, provider).select_keyframe(
            keyframe_id=keyframe_id,
            asset_id=second.output_asset_id,
            expected_revision=store.read().revision,
        )
        assert (
            next(
                k for k in current.keyframe_plan.keyframes if k.id == keyframe_id
            ).selected_asset_id
            == second.output_asset_id
        )
        await call(
            store,
            provider,
            "keyframe.select_candidate",
            "select-a-again",
            {"keyframe_id": keyframe_id, "generation_id": first.id},
        )
        keyframe = next(k for k in store.read().keyframe_plan.keyframes if k.id == keyframe_id)
        assert keyframe.selected_asset_id == first.output_asset_id

    asyncio.run(run())
