"""无内置 runtime 的正式引用库入口、审核衔接、原子回放与恢复。"""

import asyncio
import json
from dataclasses import asdict, replace

import pytest
from test_application_requests import human
from test_external_script_proposals import agent, confirm_references, http, mixed_proposal
from test_external_script_proposals import command as script_command

from core.application.caller import current_caller
from core.director_commands import DirectorCommand
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import (
    StructuredDirectorHttpApi,
    StructuredDirectorService,
    StructuredDirectorStore,
)
from server.api import StoryRailApi

PROPOSAL = {
    "characters": [
        {
            "name": "小满",
            "visual_description": "蓝色外套，短发。",
            "voice_description": "自然",
            "looks": [{"name": "日常", "appearance": "蓝色外套", "usage": "全片"}],
        }
    ],
    "narrator": {
        "name": "旁白",
        "zh_voice_description": "低沉平静",
        "en_voice_description": "Low, calm narrator.",
    },
}


def command(action, revision, key, **arguments):
    return DirectorCommand(f"reference.{action}_proposal", revision, key, arguments)


async def empty_project(tmp_path):
    workspaces = ProjectWorkspaceStore(tmp_path)
    api = StoryRailApi(
        workspaces, lambda pid: StructuredDirectorService(workspaces.structured_director_store(pid))
    )
    created = await api.handle(
        "POST",
        "/api/projects",
        json.dumps(
            {
                "title": "外部冷启动",
                "aspect_ratio": "16:9",
                "director_plan_markdown": "# 末班车\n小满等车，画外旁白描述告别。",
                "narration_languages": ["zh", "en"],
            }
        ).encode(),
    )
    assert created.status == 201, created.body
    project_id = created.body["project"]["id"]
    store = workspaces.structured_director_store(project_id)
    assert not store.read().director_runs
    return store, StructuredDirectorService(store)


def restart(store):
    return StructuredDirectorService(
        StructuredDirectorStore(store.path.parent, store.read().project_id)
    )


def test_empty_project_reference_restart_human_review_then_script(tmp_path):
    async def run():
        store, service = await empty_project(tmp_path)
        original = store.read()
        request = command(
            "request", original.revision, "initial", raw_user_instruction="严格按原方案整理"
        )
        caller = agent(original, request)
        first = await http(service, caller, request)
        assert first.status == 200, first.body
        rid = first.body["data"]["request_id"]
        observation = first.body["data"]["proposal_observation"]
        assert observation["phase"] == "awaiting_agent_submission"
        assert observation["execution_responsibility"] == "external_agent"
        assert observation["actions"][0] == {
            "action": "reference.submit_proposal",
            "tool": "reference_proposal",
            "tool_action": "submit",
            "request_id": rid,
            "target_ids": [],
            "human_only": False,
            "requires_explicit_user_request": False,
        }
        assert "后台模型" in observation["instruction"]
        assert first.body["workflow"]["active_task"] == observation
        assert first.body["workflow"]["required_next_actions"] == [observation["actions"][0]]
        assert first.body["data"]["core_facts"] == {
            "director_plan_markdown": original.director_plan_markdown,
            "narration_languages": ["zh", "en"],
        }
        assert first.body["data"]["output_schema"]["additionalProperties"] is False
        assert store.read().director_directives[-1].raw_user_request == "严格按原方案整理"
        replay = await http(restart(store), caller, request)
        assert replay.body["replay"] and replay.body["data"] == first.body["data"]
        get = command("get", store.read().revision, "read", request_id=rid)
        before = store.path.read_bytes()
        recovered = await http(restart(store), caller, get)
        assert recovered.body["data"]["status"] == "running"
        assert recovered.body["data"]["proposal_observation"]["phase"] == (
            "awaiting_agent_submission"
        )
        run_read = DirectorCommand("run.get_status", store.read().revision, "run", {"run_id": rid})
        run_result = await http(restart(store), caller, run_read)
        assert (
            run_result.body["data"]["proposal_observation"]
            == recovered.body["data"]["proposal_observation"]
        )
        request_read = DirectorCommand(
            "project.get_request", store.read().revision, "request-read", {"request_key": "initial"}
        )
        request_result = await http(restart(store), caller, request_read)
        assert (
            request_result.body["data"]["result"]["proposal_observation"]
            == recovered.body["data"]["proposal_observation"]
        )
        assert store.path.read_bytes() == before
        assert (await http(service, replace(caller, id="other"), get)).status == 403
        submit = command("submit", store.read().revision, "save", request_id=rid, proposal=PROPOSAL)
        for corrupt in [
            {**PROPOSAL, "id": "f" * 32},
            {**PROPOSAL, "characters": [{**PROPOSAL["characters"][0], "id": "f" * 32}]},
            {
                **PROPOSAL,
                "narrator": {
                    "name": 1,
                    "zh_voice_description": "平静",
                    "en_voice_description": "Calm",
                },
            },
            {**PROPOSAL, "characters": PROPOSAL["characters"] * 2},
        ]:
            result = await http(
                service,
                caller,
                replace(submit, arguments={**submit.arguments, "proposal": corrupt}),
            )
            assert result.status == 400, result.body
            assert store.path.read_bytes() == before
        assert (await http(service, replace(caller, grants=()), submit)).status == 403
        saved = await http(restart(store), caller, submit)
        assert saved.status == 200, saved.body
        doc = store.read()
        completed = await http(
            restart(store),
            caller,
            command("get", doc.revision, "get-completed", request_id=rid),
        )
        assert completed.body["data"]["proposal_observation"]["phase"] == "completed"
        assert doc.status.value == "reviewing_references" and doc.director_script is None
        assert doc.active_director_run is None and not doc.generations
        ids = [c.id for c in doc.reference_library.characters]
        assert len(ids[0]) == 32
        assert (await http(restart(store), caller, submit)).body["receipt"] == saved.body["receipt"]
        # A reference grant does not authorize the next creative operation or overwrite cards.
        script = script_command(
            "request", doc.revision, "script", raw_user_instruction="按已审核引用库生成脚本"
        )
        assert (await http(service, caller, script)).status == 403
        overwrite = command(
            "request", doc.revision, "overwrite", raw_user_instruction="重新全部整理"
        )
        overwrite_response = await http(service, human(doc.project_id), overwrite)
        assert overwrite_response.status == 409
        assert overwrite_response.body["error"]["code"] == "business_rule_rejected"
        # Human edits the reviewed card through the same HTTP endpoint as the UI.
        card = asdict(doc.reference_library.characters[0])
        card["visual_description"] = "审核后的蓝色外套，短发。"
        # 整卡保存只回传造型文字；造型图只经人类选择入口改变。
        card["looks"] = [
            {key: value for key, value in look.items() if key != "selected_asset_id"}
            for look in card["looks"]
        ]
        token = current_caller.set(human(doc.project_id))
        try:
            reviewed = await StructuredDirectorHttpApi(
                service, resource_path="/structured-director"
            ).handle(
                "PUT",
                f"/structured-director/characters/{card.pop('id')}",
                json.dumps({"expected_revision": doc.revision, **card}).encode(),
            )
        finally:
            current_caller.reset(token)
        assert reviewed.status == 200, reviewed.body
        await confirm_references(store, service)
        doc = store.read()
        script = replace(script, expected_revision=doc.revision)
        script_caller = agent(doc, script)  # Human explicitly grants this reviewed revision.
        scripted_request = await http(restart(store), script_caller, script)
        assert scripted_request.status == 200, scripted_request.body
        assert (
            scripted_request.body["data"]["core_facts"]["reference_library"]["characters"][0][
                "visual_description"
            ]
            == card["visual_description"]
        )
        scripted = await http(
            restart(store),
            script_caller,
            script_command(
                "submit",
                store.read().revision,
                "script-save",
                request_id=scripted_request.body["data"]["request_id"],
                proposal=mixed_proposal(ids[0]),
            ),
        )
        assert scripted.status == 200, scripted.body
        assert store.read().status.value == "reviewing_script"
        assert [c.id for c in store.read().reference_library.characters] == ids
        assert not store.read().generations

    asyncio.run(run())


@pytest.mark.parametrize("action", ["cancel", "reject"])
def test_reference_cancel_reject_stale_and_new_request(tmp_path, action):
    async def run():
        store, service = await empty_project(tmp_path)
        req = command("request", store.read().revision, "first", raw_user_instruction="整理")
        caller = agent(store.read(), req)
        started = await http(service, caller, req)
        rid = started.body["data"]["request_id"]
        end = command(
            action,
            store.read().revision,
            "end",
            request_id=rid,
            **({"reason": "用户要求重做"} if action == "reject" else {}),
        )
        assert (
            await http(service, caller, replace(end, expected_revision=end.expected_revision - 1))
        ).status == 409
        ended = await http(restart(store), caller, end)
        assert ended.status == 200, ended.body
        assert (await http(restart(store), caller, end)).body["replay"]
        assert store.read().active_director_run is None
        late = command("submit", store.read().revision, "late", request_id=rid, proposal=PROPOSAL)
        late_response = await http(service, caller, late)
        assert late_response.status == 409
        assert late_response.body["error"]["code"] == "business_rule_rejected"
        again = command("request", store.read().revision, "again", raw_user_instruction="重做")
        new = await http(restart(store), agent(store.read(), again), again)
        assert new.status == 200 and new.body["data"]["request_id"] != rid

    asyncio.run(run())
