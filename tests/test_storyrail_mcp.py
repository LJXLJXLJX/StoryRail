"""官方 MCP Client → stdio 子进程 → 真实受信 HTTP → 唯一 Core。"""

import asyncio
import hashlib
import json
import sys
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from test_director_commands import _visual_project
from test_external_script_proposals import agent, command, mixed_proposal, ready

from core.application.caller import command_digest
from core.director_commands import DirectorCommand
from core.structured_director import StructuredDirectorHttpApi
from integrations.storyrail_mcp.app import create_server
from integrations.storyrail_mcp.bridge import CoreBridge
from integrations.storyrail_mcp.production_tools import MODELS
from server.http import StoryRailHttpServer, StoryRailRequestHandler

TOKEN = "mcp_fixture_" + "a" * 40


@contextmanager
def endpoint(tmp_path, store, service, caller, *, full_api=False):
    token = tmp_path / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "version": 2,
                "external_mutations": True,
                "callers": [
                    {
                        "id": caller.id,
                        "role": caller.role,
                        "project_ids": list(caller.project_ids),
                        "capabilities": list(caller.capabilities),
                        "expires_at": caller.expires_at,
                        "grants": [asdict(g) for g in caller.grants],
                        "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                    }
                ],
            }
        )
    )
    policy.chmod(0o600)
    loop = asyncio.new_event_loop()
    worker = threading.Thread(target=loop.run_forever, daemon=True)
    worker.start()
    api = StructuredDirectorHttpApi(
        service, resource_path=f"/api/projects/{store.read().project_id}/structured-director"
    )
    if full_api:
        from core.project_workspaces import ProjectWorkspaceStore
        from server.api import StoryRailApi

        api = StoryRailApi(ProjectWorkspaceStore(store.path.parent.parent), lambda _pid: service)
    server = StoryRailHttpServer(("127.0.0.1", 0), api, loop, access_policy_file=policy)
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "integrations.storyrail_mcp",
            "--core-origin",
            origin,
            "--token-file",
            str(token),
        ],
        cwd=Path(__file__).resolve().parents[1],
    )
    try:
        yield params, CoreBridge(origin, token)
    finally:
        server.shutdown()
        server.server_close()
        listener.join()
        loop.call_soon_threadsafe(loop.stop)
        worker.join()
        loop.close()


def test_stdio_disconnect_retry_proposal_cancel_and_scope(tmp_path):
    store, service = asyncio.run(ready(tmp_path))
    document = store.read()
    request = command(
        "request", document.revision, "lost-response", raw_user_instruction="按方案生成"
    )
    caller = agent(document, request)
    original_sender = StoryRailRequestHandler._send_json
    dropped = []

    def drop_once(handler, status, value):
        if status == 200 and "application_request_id" in value and not dropped:
            dropped.append(True)
            handler.close_connection = True
            handler.connection.shutdown(2)  # Core 已提交，但客户端未得到响应。
            return
        original_sender(handler, status, value)

    async def run(params):
        args = {
            "project_id": document.project_id,
            "expected_revision": document.revision,
            "idempotency_key": "lost-response",
            "action": "request",
            "raw_user_instruction": "按方案生成",
        }
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            assert {t.name for t in tools} == (
                set(MODELS) - {"read_human_handoff", "read_workflow_state"}
            ) | {
                "read_story",
                "locate_story",
                "read_media_input",
                "read_professional_contract",
                "read_professional_workset",
                "read_workflow",
                "submit_proposal",
                "save_video_prompt",
                "save_keyframe_prompt",
            }
            assert all(t.input_schema["additionalProperties"] is False for t in tools)
            assert client.protocol_version == "2026-07-28"
            with patch.object(StoryRailRequestHandler, "_send_json", drop_once):
                lost = await client.call_tool("script_proposal", args)
            assert lost.is_error and lost.structured_content["error"]["code"] == "response_unknown"
            assert lost.structured_content["error"] == {
                "code": "response_unknown",
                "message": "响应未确认，请用原参数、revision 和幂等键重试。",
                "recoverable": True,
                "origin": "connector_transport",
                "state_changed": "unknown",
                "retry_policy": "replay_same_request",
                "automatic_retry_allowed": False,
                "preserve_revision": True,
                "preserve_idempotency_key": True,
            }
        # 完全关闭 adapter 子进程再重连；无 adapter 本地账本可供恢复。
        async with Client(params) as client:
            replay = await client.call_tool("script_proposal", args)
            assert not replay.is_error and replay.structured_content["replay"]
            assert store.read().revision == document.revision + 1
            rid = replay.structured_content["data"]["request_id"]
            current = store.read().revision
            target = {
                "project_id": document.project_id,
                "expected_revision": current,
                "idempotency_key": "get",
                "request_id": rid,
                "action": "get",
            }
            assert not (await client.call_tool("script_proposal", target)).is_error
            bad = await client.call_tool("script_proposal", {**target, "project_id": "e" * 32})
            assert bad.is_error and bad.structured_content["http_status"] == 403
            extra = await client.call_tool("script_proposal", {**target, "shell": "forbidden"})
            assert extra.is_error and extra.structured_content["http_status"] == 400
            cancelled = await client.call_tool(
                "script_proposal", {**target, "action": "cancel", "idempotency_key": "cancel"}
            )
            assert not cancelled.is_error
            assert store.read().active_director_run is None
            again = await client.call_tool(
                "script_proposal", {**target, "action": "cancel", "idempotency_key": "cancel"}
            )
            assert again.structured_content["receipt"] == cancelled.structured_content["receipt"]
            late = await client.call_tool(
                "script_proposal",
                {
                    **target,
                    "action": "submit",
                    "idempotency_key": "late",
                    "expected_revision": store.read().revision,
                    "proposal": mixed_proposal(document.reference_library.characters[0].id),
                },
            )
            assert late.is_error and late.structured_content["http_status"] == 409
            assert late.structured_content["error"]["code"] == "business_rule_rejected"

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))
    assert len(dropped) == 1 and len(store.read().application_requests) == 3


def test_prompt_scope_and_no_generation(tmp_path):
    from core.application.caller import Caller, MutationGrant

    store, service, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    scene = document.director_script.scenes[0]
    segment = scene.shots[0].segments[0]
    args = {
        "scope": {"scene_ids": [scene.id]},
        "segment_id": segment.id,
        "prompt_text": "一段手工正文",
    }
    digest = command_digest(
        {"name": "video.set_prompt", "arguments": args, "expected_revision": document.revision}
    )
    caller = Caller(
        "prompt",
        "agent",
        frozenset({document.project_id}),
        frozenset({"project.read", "project.mutate"}),
        4102444800,
        (MutationGrant("prompt", document.project_id, digest, 4102444800),),
        True,
    )

    async def run(bridge):
        async with Client(create_server(bridge)) as client:
            base = {
                "project_id": document.project_id,
                "expected_revision": document.revision,
                "idempotency_key": "prompt",
            }
            read = await client.call_tool(
                "read_story",
                {
                    **base,
                    "level": "segment",
                    "scene_ids": [scene.id],
                    "ids": [segment.id],
                    "parent_id": scene.shots[0].id,
                    "extensions": ["text", "selection", "dependencies"],
                },
            )
            assert not read.is_error
            from core.structured_director.reads.semantic_projection import build_semantic_projection

            assert read.structured_content["data"] == build_semantic_projection(
                document,
                {
                    "level": "segment",
                    "scope": {"scene_ids": [scene.id]},
                    "ids": [segment.id],
                    "parent_id": scene.shots[0].id,
                    "extensions": ["text", "selection", "dependencies"],
                    "limit": 20,
                },
                provider_recipes=service.provider_recipe_views(),
                provider_catalog=service.provider_catalog,
            )

            before = store.path.read_bytes()
            denied = await client.call_tool(
                "save_video_prompt",
                {
                    **base,
                    "scene_ids": [scene.id],
                    "segment_id": "e" * 32,
                    "prompt_text": "一段手工正文",
                },
            )
            assert denied.is_error and store.path.read_bytes() == before
            request = {
                **base,
                "scene_ids": [scene.id],
                "segment_id": segment.id,
                "prompt_text": "一段手工正文",
            }
            saved = await client.call_tool("save_video_prompt", request)
            assert not saved.is_error
            replay = await client.call_tool("save_video_prompt", request)
            assert replay.structured_content["replay"]
            assert not store.read().generations

    with endpoint(tmp_path, store, service, caller) as (_, bridge):
        asyncio.run(run(bridge))


def test_mcp_locate_story_resolves_readable_path(tmp_path):
    from core.application.caller import Caller

    store, service, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    caller = Caller(
        "locate",
        "agent",
        frozenset({document.project_id}),
        frozenset({"project.read"}),
        4102444800,
        (),
        False,
    )

    async def run(params):
        async with Client(params) as client:
            located = await client.call_tool(
                "locate_story",
                {
                    "project_id": document.project_id,
                    "expected_revision": document.revision,
                    "idempotency_key": "locate",
                    "location": "场景 1－镜头 1－片段 1",
                },
            )
            assert not located.is_error
            data = located.structured_content["data"]
            segment = document.director_script.scenes[0].shots[0].segments[0]
            assert data["target_type"] == "segment"
            assert data["target_id"] == segment.id
            assert data["location"] == "场景 1－镜头 1－片段 1"
            assert store.read().revision == document.revision

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))


def test_no_core_import_or_arbitrary_resource_mapping():
    import ast

    root = Path(__file__).resolve().parents[1] / "integrations/storyrail_mcp"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("core", "server"))
    for origin in (
        "http://user:secret@localhost",
        "http://localhost/path",
        "http://localhost?target=other",
    ):
        try:
            CoreBridge(origin, Path("unused"))
        except ValueError:
            pass
        else:
            raise AssertionError("非 origin 配置未拒绝")


def test_reference_stdio_submit_lost_response_keeps_core_ids(tmp_path):
    from test_external_reference_proposals import (
        PROPOSAL,
        empty_project,
    )
    from test_external_reference_proposals import (
        command as reference_command,
    )

    store, service = asyncio.run(empty_project(tmp_path))
    doc = store.read()
    request = reference_command(
        "request", doc.revision, "reference", raw_user_instruction="按原方案整理"
    )
    caller = agent(doc, request)
    original_sender = StoryRailRequestHandler._send_json
    dropped = []

    def drop_submit(handler, status, value):
        if (
            status == 200
            and value.get("data", {}).get("outcome") == "submit_proposal"
            and not dropped
        ):
            dropped.append(True)
            handler.close_connection = True
            handler.connection.shutdown(2)
            return
        original_sender(handler, status, value)

    async def run(params):
        base = {
            "project_id": doc.project_id,
            "expected_revision": doc.revision,
            "idempotency_key": "reference",
            "action": "request",
            "raw_user_instruction": "按原方案整理",
        }
        async with Client(params) as client:
            started = await client.call_tool("reference_proposal", base)
            assert not started.is_error, started
            rid = started.structured_content["data"]["request_id"]
            submitted = {
                "project_id": doc.project_id,
                "expected_revision": store.read().revision,
                "idempotency_key": "reference-submit",
                "action": "submit",
                "request_id": rid,
                "proposal": PROPOSAL,
            }
            with patch.object(StoryRailRequestHandler, "_send_json", drop_submit):
                lost = await client.call_tool("reference_proposal", submitted)
            assert lost.is_error and lost.structured_content["error"]["code"] == "response_unknown"
        ids = [c.id for c in store.read().reference_library.characters]
        revision = store.read().revision
        async with Client(params) as client:
            replay = await client.call_tool("reference_proposal", submitted)
            assert not replay.is_error and replay.structured_content["replay"]
            assert store.read().revision == revision
            assert [c.id for c in store.read().reference_library.characters] == ids
            get = await client.call_tool(
                "reference_proposal",
                {
                    "project_id": doc.project_id,
                    "expected_revision": revision,
                    "idempotency_key": "reference-get",
                    "action": "get",
                    "request_id": rid,
                },
            )
            assert not get.is_error and get.structured_content["data"]["status"] == "completed"
            assert store.read().director_script is None and not store.read().generations

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))


def test_script_stdio_request_get_submit_reaches_real_core(tmp_path):
    store, service = asyncio.run(ready(tmp_path))
    document = store.read()
    request = command(
        "request",
        document.revision,
        "stdio-script-request",
        raw_user_instruction="按已审核引用库生成脚本",
    )
    caller = agent(document, request)

    async def run(params):
        async with Client(params) as client:
            started = await client.call_tool(
                "script_proposal",
                {
                    "project_id": document.project_id,
                    "expected_revision": document.revision,
                    "idempotency_key": request.idempotency_key,
                    "action": "request",
                    "raw_user_instruction": request.arguments["raw_user_instruction"],
                },
            )
            assert not started.is_error, started
            request_id = started.structured_content["data"]["request_id"]
            observed = await client.call_tool(
                "script_proposal",
                {
                    "project_id": document.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "stdio-script-get",
                    "action": "get",
                    "request_id": request_id,
                },
            )
            assert not observed.is_error
            assert observed.structured_content["data"]["status"] == "running"
            submitted = await client.call_tool(
                "script_proposal",
                {
                    "project_id": document.project_id,
                    "expected_revision": store.read().revision,
                    "idempotency_key": "stdio-script-submit",
                    "action": "submit",
                    "request_id": request_id,
                    "proposal": mixed_proposal(document.reference_library.characters[0].id),
                },
            )
            assert not submitted.is_error, submitted
        assert store.read().director_script is not None
        assert store.read().active_director_run is None
        assert not store.read().generations

    with endpoint(tmp_path, store, service, caller) as (params, _):
        asyncio.run(run(params))


def test_mcp_generation_wait_only_persists_real_generation_changes(tmp_path, monkeypatch):
    from test_external_production import call as external_call
    from test_external_production import service as production_service
    from test_external_production import setup

    from core.model_providers.boundary import GenerationPhase

    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", "0.05")
    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_POLL_SECONDS", "0.01")

    async def prepare():
        store, provider, doc = await setup(tmp_path)
        await external_call(
            store,
            provider,
            "keyframe.generate_batch",
            "wait-batch",
            {"target_ids": [doc.director_script.scenes[0].id]},
        )
        return store, provider

    store, provider = asyncio.run(prepare())
    current = store.read()
    generation_id = current.generations[0].id
    wait_command = DirectorCommand(
        "generation.wait",
        current.revision,
        "wait-observe",
        {"generation_ids": [generation_id]},
    )
    caller = replace(
        agent(current, wait_command),
        capabilities=frozenset({"project.read", "project.mutate", "project.execute"}),
        grants=(),
    )
    core = production_service(store, provider)
    provider.observations = [GenerationPhase.RUNNING] * 100

    async def run(params):
        async with Client(params) as client:
            batch = await client.call_tool(
                "read_request",
                {
                    "project_id": current.project_id,
                    "expected_revision": current.revision,
                    "idempotency_key": "read-batch",
                    "request_key": "wait-batch",
                },
            )
            assert not batch.is_error
            batch_observation = batch.structured_content["data"]["result"]["batch_observation"]
            assert batch_observation["batch_id"]
            assert batch_observation["phase"] == "awaiting_generations"
            first = await client.call_tool(
                "manage_generation",
                {
                    "project_id": current.project_id,
                    "expected_revision": current.revision,
                    "idempotency_key": "wait-running",
                    "action": "wait",
                    "generation_ids": [generation_id],
                },
            )
            assert not first.is_error and "replay" not in first.structured_content
            assert first.structured_content["data"]["wait_again"] is True
            running = store.read()
            assert running.generations[0].phase.value == "running"
            before = store.path.read_bytes()
            request_count = len(running.application_requests)
            for index in range(3):
                observed = await client.call_tool(
                    "manage_generation",
                    {
                        "project_id": current.project_id,
                        "expected_revision": running.revision,
                        "idempotency_key": f"wait-same-{index}",
                        "action": "wait",
                        "generation_ids": [generation_id],
                    },
                )
                assert not observed.is_error and "replay" not in observed.structured_content
                assert observed.structured_content["receipt"]["status"] == "noop"
                assert observed.structured_content["data"]["generations"][0]["progress"] == 0.5
                assert store.path.read_bytes() == before
                assert len(store.read().application_requests) == request_count

            provider.observations = [GenerationPhase.SUCCEEDED]
            succeeded = await client.call_tool(
                "manage_generation",
                {
                    "project_id": current.project_id,
                    "expected_revision": running.revision,
                    "idempotency_key": "wait-success",
                    "action": "wait",
                    "generation_ids": [generation_id],
                },
            )
            assert not succeeded.is_error
            assert succeeded.structured_content["data"]["wait_again"] is False
            completed = store.read()
            assert completed.generations[0].phase.value == "succeeded"
            assert completed.generations[0].output_asset_id is not None
            assert len(completed.application_requests) == request_count
            terminal_bytes = store.path.read_bytes()
            terminal = await client.call_tool(
                "manage_generation",
                {
                    "project_id": current.project_id,
                    "expected_revision": completed.revision,
                    "idempotency_key": "wait-terminal",
                    "action": "wait",
                    "generation_ids": [generation_id],
                },
            )
            assert (
                not terminal.is_error and terminal.structured_content["receipt"]["status"] == "noop"
            )
            assert store.path.read_bytes() == terminal_bytes
            # wait 只观察：省略 revision/幂等键或带过期 revision 都直接返回当前状态。
            assert completed.revision != current.revision
            for arguments in (
                {},
                {"expected_revision": current.revision, "idempotency_key": "wait-stale"},
            ):
                observed = await client.call_tool(
                    "manage_generation",
                    {
                        "project_id": current.project_id,
                        "action": "wait",
                        "generation_ids": [generation_id],
                        **arguments,
                    },
                )
                assert not observed.is_error, observed
                assert observed.structured_content["data"]["wait_again"] is False
            assert store.path.read_bytes() == terminal_bytes
            retry_without_revision = await client.call_tool(
                "manage_generation",
                {
                    "project_id": current.project_id,
                    "action": "retry",
                    "generation_ids": [generation_id],
                },
            )
            assert retry_without_revision.is_error
            assert retry_without_revision.structured_content["error"]["code"] == "invalid_arguments"

    with endpoint(tmp_path, store, core, caller) as (params, _):
        asyncio.run(run(params))
