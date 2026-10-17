"""外部客户端的冷启动/恢复/提交闭环，以及无内置 runtime 装配。"""

import asyncio
import copy
import json
from dataclasses import asdict, replace
from unittest.mock import patch

import pytest
from proposal_fixture_service import ProposalFixtureService
from structured_director_fixtures import RecordingProposer, create_project
from test_application_requests import execute, human
from test_structured_director_script import proposal_json

from core.application.caller import (
    AccessDenied,
    Caller,
    MutationGrant,
    command_digest,
    current_caller,
)
from core.director_commands import DirectorCommand
from core.structured_director import StructuredDirectorService, StructuredDirectorStore
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.models import NarrationLanguage, StructuredDirectorStatus


def command(name, revision, key, **arguments):
    return DirectorCommand("script." + name + "_proposal", revision, key, arguments)


async def ready(tmp_path):
    project = tmp_path / ("a" * 32)
    project.mkdir()
    store = StructuredDirectorStore(project, project.name)
    create_project(store)
    await ProposalFixtureService(store, RecordingProposer()).prepare_references()
    service = StructuredDirectorService(store)
    await confirm_references(store, service)
    return store, service


def agent(document, request):
    return Caller(
        "external",
        "agent",
        frozenset({document.project_id}),
        frozenset({"project.read", "project.mutate", "project.propose"}),
        4102444800,
        (
            MutationGrant(
                "cold-start", document.project_id, command_digest(asdict(request)), 4102444800
            ),
        ),
        True,
    )


async def http(service, caller, request):
    context = current_caller.set(caller)
    try:
        return await StructuredDirectorHttpApi(
            service, resource_path="/structured-director"
        ).handle(
            "POST",
            "/structured-director/application/commands",
            json.dumps(asdict(request), ensure_ascii=False).encode(),
        )
    finally:
        current_caller.reset(context)


def mixed_proposal(character_id):
    body = json.loads(proposal_json())
    body["scenes"][0]["shots"][0]["visible_character_ids"] = [character_id]
    narration = copy.deepcopy(body["scenes"][0])
    narration.update(
        driver="narration",
        shots=[],
        segments=[],
        narration_cues=[
            {
                "zh": {"text": "车站见证了最后一次告别。", "seed": 42},
                "en": {"text": "The station witnessed the last farewell.", "seed": 42},
            }
        ],
    )
    body["scenes"].append(narration)
    return body


def test_external_cold_start_restart_submit_review_and_no_overwrite(tmp_path):
    async def run():
        store, service = await ready(tmp_path)
        original = store.read()
        request = command(
            "request", original.revision, "request", raw_user_instruction="保持原方案"
        )
        caller = agent(original, request)
        first = await http(service, caller, request)
        assert first.status == 200, first.body
        request_id = first.body["data"]["request_id"]
        observation = first.body["data"]["proposal_observation"]
        assert observation["phase"] == "awaiting_agent_submission"
        assert observation["actions"][0]["action"] == "script.submit_proposal"
        assert first.body["workflow"]["required_next_actions"] == [observation["actions"][0]]
        facts = first.body["data"]["core_facts"]
        assert facts["director_plan_markdown"] == original.director_plan_markdown
        assert first.body["data"]["raw_user_instruction"] == "保持原方案"
        restarted = StructuredDirectorService(
            StructuredDirectorStore(store.path.parent, original.project_id)
        )
        replay = await http(restarted, caller, request)
        assert replay.status == 200 and replay.body["replay"]
        assert first.body["data"] == replay.body["data"]
        get = command("get", store.read().revision, "get", request_id=request_id)
        recovered = await http(restarted, caller, get)
        assert recovered.status == 200 and recovered.body["data"]["request_id"] == request_id
        assert recovered.body["data"]["proposal_observation"]["execution_responsibility"] == (
            "external_agent"
        )
        assert store.read().revision == get.expected_revision  # 读取不创建回执写入
        other = replace(caller, id="other")
        assert (await http(restarted, other, get)).status == 403
        body = mixed_proposal(original.reference_library.characters[0].id)
        submit = command(
            "submit", store.read().revision, "submit", request_id=request_id, proposal=body
        )
        before = store.path.read_bytes()
        bad = copy.deepcopy(body)
        bad["scenes"][0]["id"] = "f" * 32
        assert (
            await http(
                restarted, caller, replace(submit, arguments={**submit.arguments, "proposal": bad})
            )
        ).status == 400
        assert store.path.read_bytes() == before
        foreign = copy.deepcopy(body)
        foreign["scenes"][0]["shots"][0]["visible_character_ids"] = ["f" * 32]
        foreign_response = await http(
            restarted,
            caller,
            replace(submit, arguments={**submit.arguments, "proposal": foreign}),
        )
        assert foreign_response.status == 409
        assert foreign_response.body["error"]["code"] == "business_rule_rejected"
        result = await http(restarted, caller, submit)
        assert result.status == 200, result.body
        completed = await http(
            restarted,
            caller,
            command("get", store.read().revision, "get-completed", request_id=request_id),
        )
        assert completed.body["data"]["proposal_observation"]["phase"] == "completed"
        replay = await http(restarted, caller, submit)
        assert replay.status == 200 and replay.body["receipt"] == result.body["receipt"]
        assert (await http(restarted, replace(caller, grants=()), submit)).status == 403
        scripted = store.read()
        assert scripted.status is StructuredDirectorStatus.REVIEWING_SCRIPT
        assert scripted.director_script.scenes[0].shots
        assert not scripted.director_script.scenes[1].shots
        assert len(scripted.director_script.scenes[1].narration_cues) == 1
        assert not scripted.generations
        ids = [scene.id for scene in scripted.director_script.scenes]
        # 人类独立审核；不会由 Agent submit 自动批准。
        reviewed = store.confirm_director_script(expected_revision=scripted.revision)
        assert [scene.id for scene in reviewed.director_script.scenes] == ids
        after_review = await http(StructuredDirectorService(store), caller, submit)
        assert after_review.status == 200 and after_review.body["replay"]
        assert after_review.body["receipt"] == result.body["receipt"]
        expired = replace(caller, grants=(replace(caller.grants[0], expires_at=0),))
        assert (await http(restarted, expired, submit)).status == 403
        request2 = command(
            "request", reviewed.revision, "overwrite", raw_user_instruction="覆盖全部"
        )
        overwrite = await http(restarted, human(original.project_id), request2)
        assert overwrite.status == 409
        assert overwrite.body["error"]["code"] == "business_rule_rejected"

    asyncio.run(run())


def test_cancel_reject_conflict_and_new_request(tmp_path):
    async def run():
        store, service = await ready(tmp_path)
        caller = human(store.read().project_id)
        for operation in ("cancel", "reject"):
            req = command(
                "request",
                store.read().revision,
                "request-" + operation,
                raw_user_instruction="生成",
            )
            started = await execute(service, caller, req)
            rid = started.data["request_id"]
            args = {
                "request_id": rid,
                **({"reason": "重新整理输入"} if operation == "reject" else {}),
            }
            end = command(operation, store.read().revision, operation, **args)
            first = await execute(service, caller, end)
            replay = await execute(StructuredDirectorService(store), caller, end)
            assert first.receipt == replay.receipt and replay.replay
            assert store.read().active_director_run is None
            stale_submit = command(
                "submit",
                store.read().revision,
                "late-" + operation,
                request_id=rid,
                proposal=mixed_proposal(store.read().reference_library.characters[0].id),
            )
            late_response = await http(service, caller, stale_submit)
            assert late_response.status == 409
            assert late_response.body["error"]["code"] == "business_rule_rejected"
        req = command("request", store.read().revision, "fresh", raw_user_instruction="新请求")
        started = await execute(service, caller, req)
        wrong = command(
            "cancel", store.read().revision - 1, "stale", request_id=started.data["request_id"]
        )
        assert (await http(service, caller, wrong)).status == 409
        with pytest.raises(AccessDenied):
            await execute(service, replace(caller, project_ids=frozenset()), req)

    asyncio.run(run())


def test_server_without_builtin_assistant_never_constructs_backend(tmp_path):
    from server.__main__ import main

    services = []

    class FakeServer:
        def __init__(self, address, api, loop):
            from core.project_settings import ProjectAspectRatio

            workspace = api._workspaces.create(
                "独立 Core",
                "# 完整方案",
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            services.append(api._structured_director_service(workspace.id))

        def serve_forever(self):
            pass

        def server_close(self):
            pass

    with (
        patch(
            "sys.argv",
            [
                "server",
                "--stories-directory",
                str(tmp_path.resolve()),
            ],
        ),
        patch("server.__main__.StoryRailHttpServer", FakeServer),
        patch("server.__main__.signal.signal"),
    ):
        main()
    assert not hasattr(services[0], "_script_proposer")
    assert not hasattr(services[0], "_director_session")
    assert services[0].image_generation_available
    from core.structured_director.reads.snapshot_view import serialize_snapshot

    snapshot = serialize_snapshot(services[0].snapshot_required(), services[0], "/fixture")
    assert "prepare_references" not in snapshot["allowed_actions"]
    assert snapshot["provider_availability"]["image_generation"]


async def confirm_references(store, service):
    result = await http(
        service,
        human(store.read().project_id),
        DirectorCommand(
            "reference.confirm_review",
            store.read().revision,
            "human-reference-review-" + str(store.read().revision),
            {},
        ),
    )
    assert result.status == 200, result.body
