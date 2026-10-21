"""外部工作区来源、媒体实际字节及人类视图契约。"""

import asyncio
import base64
from dataclasses import replace

from mcp import Client
from test_external_reference_proposals import command, empty_project, restart
from test_external_script_proposals import agent, http
from test_prompt_worksets import fixture
from test_storyrail_mcp import endpoint

from core.structured_director.reads.read_tools import execute_project_read
from core.structured_director.reads.snapshot_view import serialize_snapshot


def test_external_run_source_disables_builtin_recovery_even_if_configured(tmp_path):
    async def run():
        store, service = await empty_project(tmp_path)
        doc = store.read()
        assert (
            "unlock_visual_production"
            not in execute_project_read(doc, "project.get_handoff", {})["allowed_actions"]
        )
        req = command("request", doc.revision, "request", raw_user_instruction="整理引用库")
        started = await http(service, agent(doc, req), req)
        assert started.status == 200
        configured = restart(store)
        snapshot = serialize_snapshot(store.read(), configured, "/structured-director")
        assert "assistant_mode" not in snapshot
        assert "recover_reference_proposal" not in snapshot["allowed_actions"]
        handoff = execute_project_read(store.read(), "project.get_handoff", {})
        assert handoff["allowed_actions"] == snapshot["allowed_actions"] == []

    asyncio.run(run())


def test_mcp_image_audio_read_uses_controlled_assets_and_no_writes(tmp_path):
    store, service, doc, _ = asyncio.run(fixture(tmp_path))
    req = command("get", doc.revision, "unused", request_id="f" * 32)
    caller = replace(
        agent(doc, req),
        grants=(),
        capabilities=frozenset({"project.read"}),
        mutations_enabled=False,
    )
    before = store.path.read_bytes()
    assets = [
        next(a for a in doc.assets if a.media_type.startswith(kind))
        for kind in ["image/", "audio/"]
    ]

    async def run(params):
        async with Client(params) as client:
            base = {
                "project_id": doc.project_id,
                "expected_revision": doc.revision,
                "idempotency_key": "media",
            }
            for asset in assets:
                result = await client.call_tool("read_media_input", {**base, "asset_id": asset.id})
                assert not result.is_error, result
                assert result.content[0].type == "text"
                media = result.content[1]
                assert media.type == ("image" if asset.media_type.startswith("image/") else "audio")
                assert media.mime_type == asset.media_type
                assert base64.b64decode(media.data) == store.read_asset(asset.id)[1]
                content_url = result.structured_content["content_url"]
                assert content_url.endswith(f"/assets/{asset.id}/content")
                assert result.structured_content["sha256"] == asset.sha256
            for extra in (
                {"asset_id": "f" * 32},
                {"project_id": "f" * 32},
                {"expected_revision": 1},
                {"path": "../../secret"},
            ):
                result = await client.call_tool(
                    "read_media_input", {**base, "asset_id": assets[0].id, **extra}
                )
                assert result.is_error

    with endpoint(tmp_path, store, service, caller, full_api=True) as (params, _):
        asyncio.run(run(params))
    assert store.path.read_bytes() == before


def test_latest_read_recovers_tasks_and_exact_cursor_is_revision_bound(tmp_path):
    from test_external_production import call, service, setup

    from core.director_commands import DirectorCommand
    from core.model_providers.boundary import GenerationPhase

    async def run():
        store, provider, original = await setup(tmp_path)
        started, _ = await call(
            store,
            provider,
            "keyframe.generate_batch",
            "discover-batch",
            {"target_ids": [original.director_script.scenes[0].id]},
        )
        current = store.read()
        read_command = DirectorCommand("project.get_handoff", current.revision, "read", {})
        caller = replace(
            agent(current, read_command),
            grants=(),
            capabilities=frozenset({"project.read"}),
            mutations_enabled=False,
        )
        core = service(store, provider)
        before = store.path.read_bytes()
        with endpoint(tmp_path, store, core, caller) as (params, _):
            async with Client(params) as client:
                latest = await client.call_tool(
                    "read_human_handoff",
                    {"project_id": current.project_id, "limit": 1},
                )
                assert not latest.is_error, latest
                discovery = latest.structured_content["data"]["task_discovery"]
                assert discovery["observation_revision"] == current.revision
                assert discovery["active_count"] >= 3
                assert discovery["next_cursor"] is not None
                task = (discovery["active"] + discovery["recent"])[0]
                assert task["id"] and task["kind"] and task["status"]

                stale = await client.call_tool(
                    "read_human_handoff",
                    {
                        "project_id": current.project_id,
                        "expected_revision": original.revision,
                    },
                )
                assert stale.is_error
                assert stale.structured_content["error"] == {
                    "code": "revision_conflict",
                    "message": "项目已被更新，请重新读取后再查询。",
                    "recoverable": True,
                    "origin": "core_revision",
                    "state_changed": False,
                    "retry_policy": "reread_then_reissue_if_still_intended",
                    "automatic_retry_allowed": False,
                    "expected_revision": original.revision,
                    "current_revision": current.revision,
                }

                same_snapshot = await client.call_tool(
                    "read_human_handoff",
                    {
                        "project_id": current.project_id,
                        "expected_revision": current.revision,
                        "cursor": discovery["next_cursor"],
                        "limit": 1,
                    },
                )
                assert not same_snapshot.is_error

                provider.observations = [GenerationPhase.RUNNING]
                await core._generation_observer.refresh_generation(current.generations[-1].id)
                expired_cursor = await client.call_tool(
                    "read_human_handoff",
                    {
                        "project_id": current.project_id,
                        "cursor": discovery["next_cursor"],
                        "limit": 1,
                    },
                )
                assert expired_cursor.is_error
                assert expired_cursor.structured_content["error"]["code"] == "invalid_request"
        assert before != store.path.read_bytes()  # 仅显式 Provider 推进改变业务状态。
        assert len(store.read().application_requests) == len(current.application_requests)

    asyncio.run(run())
