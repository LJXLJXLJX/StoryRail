"""Opt-in native Codex CLI discovery/wire check against a controlled Core fixture."""

import asyncio
import json
import os
import shutil
import subprocess

import pytest
from test_director_commands import _visual_project
from test_external_script_proposals import agent
from test_storyrail_mcp import stdio_endpoint

from core.director_commands import DirectorCommand


@pytest.mark.skipif(
    os.environ.get("STORYRAIL_NATIVE_CODEX_TESTS") != "1" or shutil.which("codex") is None,
    reason="set STORYRAIL_NATIVE_CODEX_TESTS=1 to run the installed Codex CLI MCP check",
)
def test_native_codex_discovers_and_sends_keyframe_proposal_request(tmp_path):
    store, service, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    scene = document.director_script.scenes[0]
    shot = scene.shots[0]
    core_command = DirectorCommand(
        "keyframe.request_proposal",
        document.revision,
        "native-codex-keyframe-request",
        {
            "raw_user_instruction": "为受控测试镜头规划关键帧，只规划，不生成图片。",
            "scope": {"scene_ids": [scene.id]},
            "target_ids": [shot.id],
        },
    )
    caller = agent(document, core_command)
    with stdio_endpoint(tmp_path, store, service, caller) as (params, _bridge):
        tool_arguments = {
            "project_id": document.project_id,
            "expected_revision": document.revision,
            "idempotency_key": core_command.idempotency_key,
            "action": "request",
            "raw_user_instruction": core_command.arguments["raw_user_instruction"],
            "scene_ids": [scene.id],
            "target_ids": [shot.id],
        }
        prompt = (
            "这是 StoryRail 受控 fixture 的协议复验。必须调用 storyrail MCP 的 "
            "keyframe_proposal 工具恰好一次，参数严格使用下面 JSON，不增删字段；调用后只输出 "
            "request_id 和 phase，不执行 submit 或任何其它工具：\n"
            + json.dumps(tool_arguments, ensure_ascii=False)
        )
        completed = subprocess.run(
            [
                "codex",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--approve-for-me",
                "-c",
                "mcp_servers.storyrail.command=" + json.dumps(params.command),
                "-c",
                "mcp_servers.storyrail.args=" + json.dumps([str(item) for item in params.args]),
                prompt,
            ],
            cwd=params.cwd,
            text=True,
            capture_output=True,
            timeout=240,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr[-4_000:]
    current = store.read()
    assert current.revision == document.revision + 1, (
        completed.stdout[-4_000:] + "\n" + completed.stderr[-4_000:]
    )
    assert current.active_director_run is not None
    record = current.application_requests[-1]
    assert record.operation == "keyframe.request_proposal"
    receipt = json.loads(record.receipt_json)
    assert receipt["data"]["request_arguments"] == core_command.arguments
    assert receipt["data"]["proposal_observation"]["phase"] == "awaiting_agent_submission"
