"""Agent 写回执与专业读取在大项目下仍保留完整关键字段。"""

import asyncio
import hashlib
import json
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from conftest import make_service
from mcp import Client
from structured_director_fixtures import RecordingProvider, RecordingScriptProposer
from test_director_commands import _visual_project
from test_external_planning_proposals import proposal_for, request
from test_external_script_proposals import agent, http
from test_prompt_worksets import fixture
from test_storyrail_mcp import endpoint

from core.director_commands import DirectorCommand
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.reads.read_tools import ReadResultTooLarge, _object_count

_APPLICATION_RESPONSE_BUDGET = 32 * 1024
_MCP_PAGE_RESPONSE_BUDGET = 64 * 1024


def _encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


class FifteenShotScript(RecordingScriptProposer):
    async def propose(self, **kwargs):
        base = await super().propose(**kwargs)
        scene = base.scenes[0]
        shot = replace(
            scene.shots[0],
            segments=(replace(scene.shots[0].segments[0], dialogue_lines=()),),
        )
        scene = replace(scene, shots=(shot,))
        return replace(
            base,
            scenes=tuple(replace(scene, title=f"大型项目场景 {index + 1}") for index in range(15)),
        )


def test_large_keyframe_proposal_submit_is_not_limited_by_read_envelope(tmp_path):
    async def run():
        store, service, document, _ = await _visual_project(
            str(tmp_path), script_proposer=FifteenShotScript()
        )
        target_ids = [shot.id for scene in document.director_script.scenes for shot in scene.shots]
        start_command = request(document, "keyframe", target_ids)
        caller = agent(document, start_command)

        started = await http(service, caller, start_command)
        assert started.status == 200, started.body
        assert _object_count(started.body["data"]) > 500
        request_id = started.body["data"]["request_id"]

        current = store.read()
        request_lookup = DirectorCommand(
            "project.get_request",
            current.revision,
            "lookup-large-keyframe-request",
            {"request_key": start_command.idempotency_key},
        )
        lookup = await http(service, caller, request_lookup)
        assert lookup.status == 200, lookup.body
        compact = lookup.body["data"]["result"]
        assert "core_facts" not in compact and "output_schema" not in compact
        assert compact["workset_recovery"] == {
            "included": False,
            "reason": "通用请求查询不内联大型专业工作集。",
            "tool": "keyframe_proposal",
            "action": "get",
            "request_id": request_id,
            "latest_workset_tool": "read_professional_workset",
            "capability": "keyframe",
            "scope": start_command.arguments["scope"],
            "target_ids": target_ids,
        }
        assert _encoded_size(lookup.body) < _APPLICATION_RESPONSE_BUDGET

        with endpoint(tmp_path, store, service, caller) as (params, _):
            async with Client(params) as client:
                recovered = await client.call_tool(
                    "keyframe_proposal",
                    {
                        "project_id": current.project_id,
                        "expected_revision": current.revision,
                        "idempotency_key": "get-large-keyframe-proposal",
                        "action": "get",
                        "request_id": request_id,
                    },
                )
                assert not recovered.is_error, recovered
                assert _object_count(recovered.structured_content["data"]) > 500
                submitted = await client.call_tool(
                    "keyframe_proposal",
                    {
                        "project_id": current.project_id,
                        "expected_revision": current.revision,
                        "idempotency_key": "submit-large-keyframe-proposal",
                        "action": "submit",
                        "request_id": request_id,
                        "proposal": proposal_for(current, "keyframe", target_ids),
                    },
                )
        assert not submitted.is_error, submitted
        payload = submitted.structured_content
        assert payload["http_status"] == 200
        assert payload["data"] == {
            "request_id": request_id,
            "outcome": "submit_proposal",
        }
        assert payload["receipt"]["new_revision"] == store.read().revision
        assert store.read().active_director_run is None
        assert _encoded_size(payload) < _APPLICATION_RESPONSE_BUDGET

    asyncio.run(run())


def test_large_project_application_writes_return_compact_receipts_and_stable_replay(tmp_path):
    async def run():
        store, _, document, _ = await fixture(tmp_path)
        document = replace(
            document,
            revision=document.revision + 1,
            director_plan_markdown="# 大项目\n" + "文" * 49000,
        )
        store._atomic_write(document)
        provider = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\ncompact")
        service = make_service(store, image_provider=provider)
        scene = document.director_script.scenes[0]
        segment = scene.segments[0]
        keyframe_id = document.keyframe_plan.segments[0].start_keyframe_id
        commands = [
            (
                "save_video_prompt",
                "video.set_prompt",
                {
                    "scope": {"scene_ids": [scene.id]},
                    "segment_id": segment.id,
                    "prompt_text": "仅保存当前 Segment 的 H3 正文。",
                },
                {
                    "scene_ids": [scene.id],
                    "segment_id": segment.id,
                    "prompt_text": "仅保存当前 Segment 的 H3 正文。",
                },
            ),
            (
                "save_keyframe_prompt",
                "keyframe.apply_operations",
                {
                    "operations": [
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": keyframe_id,
                            "fields": {"prompt_text": "只保存这一帧的静态提示词。"},
                        }
                    ]
                },
                {"keyframe_id": keyframe_id, "prompt_text": "只保存这一帧的静态提示词。"},
            ),
            (
                "edit_keyframes",
                "keyframe.apply_operations",
                {
                    "operations": [
                        {
                            "op": "set_aux_references",
                            "segment_id": segment.id,
                            "asset_ids": [],
                        }
                    ]
                },
                {
                    "operations": [
                        {
                            "op": "set_aux_references",
                            "segment_id": segment.id,
                            "asset_ids": [],
                        }
                    ]
                },
            ),
            (
                "generate_media",
                "keyframe.generate",
                {"keyframe_id": keyframe_id},
                {"kind": "keyframe", "target_id": keyframe_id},
            ),
        ]
        for index, (tool_name, name, arguments, tool_arguments) in enumerate(commands):
            before = store.read()
            command = DirectorCommand(name, before.revision, f"large-write-{index}", arguments)
            caller = agent(before, command)
            mcp_arguments = {
                "project_id": before.project_id,
                "expected_revision": before.revision,
                "idempotency_key": command.idempotency_key,
                **tool_arguments,
            }
            with endpoint(tmp_path, store, service, caller) as (params, _):
                async with Client(params) as client:
                    response = await client.call_tool(tool_name, mcp_arguments)
                    replay = await client.call_tool(tool_name, mcp_arguments)
            assert not response.is_error, response
            payload = response.structured_content
            assert "snapshot" not in payload
            assert _encoded_size(payload) < _APPLICATION_RESPONSE_BUDGET
            assert len(response.content[0].text.encode()) < _APPLICATION_RESPONSE_BUDGET
            assert payload["receipt"]["new_revision"] == store.read().revision
            assert "warnings" in payload["receipt"]
            assert payload["workflow"]["semantics"]["current_stage"]
            assert payload["data"] is not None

            replay_payload = replay.structured_content
            assert not replay.is_error
            assert replay_payload["replay"] is True
            assert replay_payload["receipt"] == payload["receipt"]
            assert replay_payload["data"] == payload["data"]
            assert "snapshot" not in replay_payload
            assert _encoded_size(replay_payload) < _APPLICATION_RESPONSE_BUDGET
        assert len(provider.requests) == 1

    asyncio.run(run())


def test_large_professional_workset_pages_are_revision_bound_complete_json(tmp_path):
    async def run(params, document):
        query = {
            "project_id": document.project_id,
            "expected_revision": document.revision,
            "idempotency_key": "large-workset-read",
            "capability": "script",
        }
        chunks = []
        cursor = None
        final_page = None
        async with Client(params) as client:
            while True:
                result = await client.call_tool(
                    "read_professional_workset",
                    {**query, **({} if cursor is None else {"cursor": cursor})},
                )
                assert not result.is_error, result
                page = result.structured_content["data"]
                assert page["observation_revision"] == document.revision
                assert _encoded_size(result.structured_content) < _MCP_PAGE_RESPONSE_BUDGET
                assert len(result.content[0].text.encode()) < _MCP_PAGE_RESPONSE_BUDGET
                chunks.append(page["content_chunk"])
                final_page = page
                cursor = page["pagination"]["next_cursor"]
                if cursor is None:
                    break
        encoded = "".join(chunks).encode()
        assert hashlib.sha256(encoded).hexdigest() == final_page["pagination"]["content_sha256"]
        full = json.loads(encoded)
        assert full["source_revision"] == document.revision
        assert full["scope"] == {"project_id": document.project_id}
        assert full["core_facts"]["director_plan_markdown"].endswith("文" * 100)

    async def setup():
        store, service, document, _ = await fixture(tmp_path)
        document = replace(
            document,
            revision=document.revision + 1,
            director_plan_markdown="# 大项目\n" + "文" * 49000,
        )
        store._atomic_write(document)
        command = DirectorCommand(
            "project.get_workset",
            document.revision,
            "large-workset-read",
            {"capability": "script", "scope": {"project_id": document.project_id}},
        )
        caller = replace(
            agent(document, command),
            grants=(),
            capabilities=frozenset({"project.read"}),
            mutations_enabled=False,
        )
        with endpoint(tmp_path, store, service, caller) as (params, _):
            await run(params, document)

    asyncio.run(setup())


def test_unpageable_read_overflow_is_structured_and_never_truncated(tmp_path):
    async def run():
        store, service, document, _ = await fixture(tmp_path)
        command = DirectorCommand(
            "project.get_scene",
            document.revision,
            "oversized-read",
            {"scene_id": document.director_script.scenes[0].id},
        )
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        with patch.object(
            service,
            "execute_director_command",
            AsyncMock(side_effect=ReadResultTooLarge("结果超过 128 KiB。")),
        ):
            response = await api.handle(
                "POST",
                "/structured-director/application/commands",
                json.dumps(
                    {
                        "name": command.name,
                        "expected_revision": command.expected_revision,
                        "idempotency_key": command.idempotency_key,
                        "arguments": command.arguments,
                    }
                ).encode(),
            )
        assert response.status == 413
        assert response.body == {
            "error": {
                "code": "result_too_large",
                "message": "结果超过 128 KiB。",
                "recoverable": True,
                "origin": "response_envelope",
                "state_changed": False,
                "retry_policy": "narrow_or_continue_read",
                "automatic_retry_allowed": False,
                "retry": "缩小 scope/limit/layers，或使用返回的 cursor 续读。",
            }
        }
        assert _encoded_size(response.body) < _APPLICATION_RESPONSE_BUDGET
        assert store.read().revision == document.revision

    asyncio.run(run())
