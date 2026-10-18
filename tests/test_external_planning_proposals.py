"""规划生命周期复用 Core，断连/取消/范围/已生成锁定由持久事实决定。"""

import asyncio
import copy
from dataclasses import replace

import pytest
from mcp import Client
from test_director_commands import _visual_project
from test_external_reference_proposals import restart
from test_external_script_proposals import agent, http
from test_prompt_worksets import fixture
from test_storyrail_mcp import endpoint

from core.director_commands import DirectorCommand


def request(document, kind, target_ids=None):
    scenes = document.director_script.scenes
    args = {
        "raw_user_instruction": "按当前完整上下文规划指定范围",
        "scope": {"scene_ids": [s.id for s in scenes]},
    }
    args["target_ids"] = target_ids or [scenes[0].segments[0].id]
    return DirectorCommand(f"{kind}.request_proposal", document.revision, "request", args)


def proposal_for(document, kind, target_ids=None):
    scenes = document.director_script.production_baseline_scenes
    writable = set(target_ids or [scenes[0].segments[0].id])
    return {
        "segments": [
            {
                "segment_id": segment.id,
                "continues_from_previous": False,
                "frame_strategy": "both",
                "start_prompt_text": "完整静态场景。",
                "start_visible_character_ids": [],
                "start_character_references": [],
                "end_prompt_text": "静态终点。",
                "end_visible_character_ids": [],
                "end_character_references": [],
            }
            for scene in scenes
            for segment in scene.segments
            if segment.id in writable
        ]
    }


def test_planning_restart_scope_atomic_submit_and_no_builtin(tmp_path):
    kind = "keyframe"

    async def run():
        store, _, doc, _ = await _visual_project(str(tmp_path))
        req = request(doc, kind)
        caller = agent(doc, req)
        before = store.path.read_bytes()
        for args in ({**req.arguments, "scope": {}}, {**req.arguments, "extra": True}):
            malformed = replace(req, arguments=args)
            assert (await http(restart(store), agent(doc, malformed), malformed)).status == 400
            assert store.path.read_bytes() == before
        start = await http(restart(store), caller, req)
        assert start.status == 200, start.body
        rid = start.body["data"]["request_id"]
        observation = start.body["data"]["proposal_observation"]
        assert observation["phase"] == "awaiting_agent_submission"
        assert observation["actions"][0]["action"] == f"{kind}.submit_proposal"
        assert start.body["workflow"]["required_next_actions"] == [observation["actions"][0]]
        assert start.body["data"]["request_arguments"] == req.arguments
        assert (await http(restart(store), caller, req)).body["replay"]
        doc = store.read()
        get = DirectorCommand(f"{kind}.get_proposal", doc.revision, "get", {"request_id": rid})
        before = store.path.read_bytes()
        observed = await http(restart(store), caller, get)
        assert observed.body["data"]["status"] == "running"
        assert observed.body["data"]["proposal_observation"]["phase"] == (
            "awaiting_agent_submission"
        )
        assert store.path.read_bytes() == before
        assert (await http(restart(store), replace(caller, id="another"), get)).status == 403
        assert (await http(restart(store), replace(caller, grants=()), get)).status == 403
        good = proposal_for(doc, kind)
        bads = [{**good, "extra": True}, {"segments": []}, {"segments": good["segments"] * 2}]
        wrong = copy.deepcopy(good)
        wrong["segments"][0]["segment_id"] = "f" * 32
        bads.append(wrong)
        missing_segment = copy.deepcopy(good)
        missing_segment["segments"][0]["frame_strategy"] = "invalid"
        bads.append(missing_segment)
        extra_segment = proposal_for(
            doc,
            kind,
            [
                doc.director_script.scenes[0].segments[0].id,
                doc.director_script.scenes[0].segments[1].id,
            ],
        )
        bads.append(extra_segment)
        for index, bad in enumerate(bads):
            submit = DirectorCommand(
                f"{kind}.submit_proposal",
                doc.revision,
                f"bad-{index}",
                {"request_id": rid, "proposal": bad},
            )
            result = await http(restart(store), caller, submit)
            assert result.status == 400, result.body
            assert store.path.read_bytes() == before
        submit = DirectorCommand(
            f"{kind}.submit_proposal", doc.revision, "submit", {"request_id": rid, "proposal": good}
        )
        assert (
            await http(restart(store), caller, replace(submit, expected_revision=1))
        ).status == 409
        result = await http(restart(store), caller, submit)
        assert result.status == 200, result.body
        finished = store.read()
        assert finished.active_director_run is None
        completed_get = DirectorCommand(
            f"{kind}.get_proposal",
            finished.revision,
            "get-completed",
            {"request_id": rid},
        )
        completed = await http(restart(store), caller, completed_get)
        assert completed.body["data"]["proposal_observation"]["phase"] == "completed"
        # Same-Scene context Shot is not writable; original slots and empty fields stay intact.
        untouched = doc.director_script.scenes[0].segments[1].id
        before_binding = next(b for b in doc.keyframe_plan.segments if b.segment_id == untouched)
        assert before_binding in finished.keyframe_plan.segments
        ids = {before_binding.start_keyframe_id, before_binding.end_keyframe_id}
        assert [f for f in finished.keyframe_plan.keyframes if f.id in ids] == [
            f for f in doc.keyframe_plan.keyframes if f.id in ids
        ]
        saved = store.path.read_bytes()
        assert (await http(restart(store), caller, submit)).body["replay"]
        assert store.path.read_bytes() == saved
        assert not finished.generations

    asyncio.run(run())


def test_keyframe_partial_scope_schema_and_second_shot_submit(tmp_path):
    async def run():
        store, _, doc, _ = await _visual_project(str(tmp_path))
        scene = doc.director_script.scenes[0]
        target = scene.segments[1].id
        req = request(doc, "keyframe", [target])
        caller = agent(doc, req)
        started = await http(restart(store), caller, req)
        assert started.status == 200, started.body
        data = started.body["data"]
        facts = data["core_facts"]
        assert facts["context_segment_ids"] == [segment.id for segment in scene.segments]
        assert facts["writable_segment_ids"] == [target]
        segment_schema = data["output_schema"]["properties"]["segments"]
        assert segment_schema["minItems"] == segment_schema["maxItems"] == 1
        assert [
            schema["properties"]["segment_id"]["const"] for schema in segment_schema["prefixItems"]
        ] == [target]

        before = store.read()
        untouched_segment = scene.segments[0].id
        before_binding = next(
            item for item in before.keyframe_plan.segments if item.segment_id == untouched_segment
        )
        before_frames = {
            item.id: item
            for item in before.keyframe_plan.keyframes
            if item.id in {before_binding.start_keyframe_id, before_binding.end_keyframe_id}
        }
        submit = DirectorCommand(
            "keyframe.submit_proposal",
            before.revision,
            "submit-second",
            {
                "request_id": data["request_id"],
                "proposal": proposal_for(before, "keyframe", [target]),
            },
        )
        result = await http(restart(store), caller, submit)
        assert result.status == 200, result.body
        finished = store.read()
        assert (
            next(
                item
                for item in finished.keyframe_plan.segments
                if item.segment_id == untouched_segment
            )
            == before_binding
        )
        assert {
            item.id: item for item in finished.keyframe_plan.keyframes if item.id in before_frames
        } == before_frames
        assert not finished.generations

    asyncio.run(run())


def test_keyframe_non_contiguous_targets_keep_context_shots_unchanged(tmp_path):
    from keyframe_wave_fixtures import FiveShotScript

    async def run():
        store, _, doc, _ = await _visual_project(str(tmp_path), script_proposer=FiveShotScript())
        scene = doc.director_script.scenes[0]
        target_ids = [scene.segments[0].id, scene.segments[2].id]
        req = request(doc, "keyframe", target_ids)
        caller = agent(doc, req)
        started = await http(restart(store), caller, req)
        assert started.status == 200, started.body
        assert started.body["data"]["core_facts"]["writable_segment_ids"] == target_ids
        before = store.read()
        submit = DirectorCommand(
            "keyframe.submit_proposal",
            before.revision,
            "submit-non-contiguous",
            {
                "request_id": started.body["data"]["request_id"],
                "proposal": proposal_for(before, "keyframe", target_ids),
            },
        )
        result = await http(restart(store), caller, submit)
        assert result.status == 200, result.body
        finished = store.read()
        untouched_segments = {
            segment.id for segment in scene.segments if segment.id not in target_ids
        }
        assert [
            item
            for item in finished.keyframe_plan.segments
            if item.segment_id in untouched_segments
        ] == [
            item for item in before.keyframe_plan.segments if item.segment_id in untouched_segments
        ]
        untouched_frame_ids = {
            frame_id
            for item in before.keyframe_plan.segments
            if item.segment_id in untouched_segments
            for frame_id in (item.start_keyframe_id, item.end_keyframe_id)
        }
        assert [
            item for item in finished.keyframe_plan.keyframes if item.id in untouched_frame_ids
        ] == [item for item in before.keyframe_plan.keyframes if item.id in untouched_frame_ids]

    asyncio.run(run())


@pytest.mark.parametrize("action", ["cancel", "reject"])
def test_cancel_reject_cannot_accept_late_proposal(tmp_path, action):
    kind = "keyframe"

    async def run():
        store, _, doc, _ = await _visual_project(str(tmp_path))
        req = request(doc, kind)
        caller = agent(doc, req)
        start = await http(restart(store), caller, req)
        rid = start.body["data"]["request_id"]
        args = {"request_id": rid, **({"reason": "需要重新定义范围"} if action == "reject" else {})}
        end = DirectorCommand(f"{kind}.{action}_proposal", store.read().revision, "end", args)
        assert (await http(restart(store), caller, end)).status == 200
        assert (await http(restart(store), caller, end)).body["replay"]
        terminal = await http(
            restart(store),
            caller,
            DirectorCommand(
                f"{kind}.get_proposal",
                store.read().revision,
                "get-terminal",
                {"request_id": rid},
            ),
        )
        assert terminal.body["data"]["proposal_observation"]["phase"] == (
            "rejected" if action == "reject" else "cancelled"
        )
        late = DirectorCommand(
            f"{kind}.submit_proposal",
            store.read().revision,
            "late",
            {"request_id": rid, "proposal": proposal_for(store.read(), kind)},
        )
        before = store.path.read_bytes()
        late_response = await http(restart(store), caller, late)
        assert late_response.status == 409
        assert late_response.body["error"]["code"] == "business_rule_rejected"
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_generated_keyframe_nodes_and_aux_are_preserved(tmp_path):
    async def run():
        store, _, doc, _ = await fixture(tmp_path)
        plan, generations = doc.keyframe_plan, doc.generations
        req = request(doc, "keyframe")
        caller = agent(doc, req)
        start = await http(restart(store), caller, req)
        rid = start.body["data"]["request_id"]
        submit = DirectorCommand(
            "keyframe.submit_proposal",
            store.read().revision,
            "submit",
            {"request_id": rid, "proposal": proposal_for(store.read(), "keyframe")},
        )
        result = await http(restart(store), caller, submit)
        assert result.status == 200, result.body
        assert store.read().keyframe_plan == plan
        assert store.read().generations == generations

    asyncio.run(run())


def test_mcp_planning_request_get_submit_reaches_real_core(tmp_path):
    kind = "keyframe"

    async def prepare():
        store, _, document, _ = await _visual_project(str(tmp_path))
        request_command = request(document, kind)
        return store, document, request_command, agent(document, request_command)

    store, document, request_command, caller = asyncio.run(prepare())

    async def run(params):
        arguments = {
            "project_id": document.project_id,
            "expected_revision": document.revision,
            "idempotency_key": request_command.idempotency_key,
            "action": "request",
            "raw_user_instruction": request_command.arguments["raw_user_instruction"],
        }
        arguments["scene_ids"] = request_command.arguments["scope"]["scene_ids"]
        arguments["target_ids"] = request_command.arguments["target_ids"]
        tool = f"{kind}_proposal"
        async with Client(params) as client:
            started = await client.call_tool(tool, arguments)
            assert not started.is_error, started
            request_id = started.structured_content["data"]["request_id"]
            observed = await client.call_tool(
                tool,
                {
                    "project_id": document.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "stdio-get",
                    "action": "get",
                    "request_id": request_id,
                },
            )
            assert not observed.is_error
            assert observed.structured_content["data"]["status"] == "running"
            submitted = await client.call_tool(
                tool,
                {
                    "project_id": document.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "stdio-submit",
                    "action": "submit",
                    "request_id": request_id,
                    "proposal": proposal_for(store.read(), kind),
                },
            )
            assert not submitted.is_error, submitted
        assert store.read().active_director_run is None
        assert not store.read().generations

    with endpoint(tmp_path, store, restart(store), caller) as (params, _):
        asyncio.run(run(params))


def test_missing_persisted_scope_and_changed_workset_cannot_resume(tmp_path):
    from core.structured_director.errors import RevisionConflictError
    from core.structured_director.planning_proposals import PlanningProposalHandler

    async def run():
        store, _, doc, _ = await _visual_project(str(tmp_path))
        req = request(doc, "keyframe")
        caller = agent(doc, req)
        start = await http(restart(store), caller, req)
        data = start.body["data"]
        handler = PlanningProposalHandler("keyframe")
        import json

        parsed = handler.parse_proposal(json.dumps(proposal_for(doc, "keyframe")))
        before = store.path.read_bytes()
        missing = {k: v for k, v in data.items() if k != "request_arguments"}
        for saved, error in (
            (missing, ValueError),
            ({**data, "source_revision": 1}, RevisionConflictError),
        ):
            with pytest.raises(error):
                handler.submit(
                    store,
                    parsed,
                    request_id=data["request_id"],
                    expected_revision=store.read().revision,
                    request_data=saved,
                )
            assert store.path.read_bytes() == before

    asyncio.run(run())
