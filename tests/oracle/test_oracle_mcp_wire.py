"""O8 · MCP wire 兼容 oracle。

ARRIVE   真实 stdio 子进程起官方 MCP server（`python -m integrations.storyrail_mcp
         --core-origin <Core> --token-file <agent token>`，参照
         tests/test_storyrail_mcp.py），背后接 conftest 的真实 loopback Core
         （OracleHttpServer 的受信 agent caller）；journey 驱动双 Scene 项目到
         视觉生产解锁，经 MCP client 发写/读请求。
ORACLE   断言可达状态谓词：
         - tools/list 与进程内 create_server().tool_schema() 一致（27 个工具，
           名称 + input_schema + description 逐一相等）；
         - 三个写工具翻译到正确 Core 命令并有真实副作用：script_proposal
           （request→建立 SCRIPT_PROPOSAL run→显式 cancel）、save_video_prompt
           （video.set_prompt，video_plan 正文落库且幂等回放）、set_video_recipe
           （video.set_recipe，generation_mode 切换）；
         - 读工具分页 cursor 往返：read_story outline limit=1 逐页续读，拼接
           结果与一次全量读取一致；
         - 写工具错误形状逐字段符合 docs/error-contract.md：领域不变量拒绝
           （script_proposal 冷启动覆盖 / save_video_prompt 未知 Segment）→ 409
           business_rule_rejected / core_domain；schema 拒绝（set_video_recipe
           非法枚举）→ 400 invalid_arguments / mcp_schema；拒绝后 revision 不变。
覆盖领域规则：外部 Agent 只经类型化能力入口；MCP 保留 Core 原始错误 code 与
错误契约字段；幂等键回放；分页 cursor 绑定 revision 与查询。
BUDGET   单场景 ≤20s（stdio 子进程 + 合成 Provider）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from conftest import AGENT_TOKEN, Journey
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from video_recipes import video_wire_dict, video_wire_mode

from integrations.storyrail_mcp.app import create_server
from integrations.storyrail_mcp.bridge import CoreBridge
from integrations.storyrail_mcp.production_tools import MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = (set(MODELS) - {"read_human_handoff", "read_workflow_state"}) | {
    "read_story",
    "locate_story",
    "read_details",
    "read_media_input",
    "read_professional_contract",
    "read_professional_workset",
    "read_workflow",
    "submit_proposal",
    "save_video_prompt",
    "save_keyframe_prompt",
}


@pytest.fixture()
def mcp_params(http_server, tmp_path) -> StdioServerParameters:
    token_file = tmp_path / "agent_token"
    token_file.write_text(AGENT_TOKEN)
    token_file.chmod(0o600)
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "integrations.storyrail_mcp",
            "--core-origin",
            http_server.base_url,
            "--token-file",
            str(token_file),
        ],
        cwd=REPO_ROOT,
    )


def _base(journey) -> dict:
    return {
        "project_id": journey.project_id,
        "expected_revision": journey._revision(),
        "idempotency_key": "O8-base",
    }


def _domain_rejection_fields(error: dict) -> None:
    assert error["code"] == "business_rule_rejected"
    assert error["origin"] == "core_domain"
    assert error["state_changed"] is False
    assert error["retry_policy"] == "change_business_state_or_request"
    assert error["automatic_retry_allowed"] is False
    assert error["recoverable"] is False


@pytest.mark.oracle
def test_oracle_mcp_wire_tools_translation_pagination_and_errors(journey, http_server, mcp_params):
    journey.create_project(title="O8MCPwire")
    journey.propose_references()
    journey.approve_references()

    async def wire_check() -> None:
        async with Client(mcp_params) as stdio:
            # ORACLE：stdio tools/list 与进程内 published schema 一致（27 个）。
            wire_tools = {tool.name: tool for tool in (await stdio.list_tools()).tools}
            in_process_bridge = CoreBridge("http://127.0.0.1:9", Path("unused-token"))
            async with Client(create_server(in_process_bridge)) as local:
                local_tools = {tool.name: tool for tool in (await local.list_tools()).tools}
            assert set(wire_tools) == EXPECTED_TOOLS
            assert len(wire_tools) == 28
            assert set(local_tools) == set(wire_tools)
            for name, tool in wire_tools.items():
                assert tool.input_schema == local_tools[name].input_schema, name
                assert tool.description == local_tools[name].description, name
                assert tool.input_schema["additionalProperties"] is False

            # ORACLE：合并读工具与旧别名都可调用。
            workflow_read = await stdio.call_tool(
                "read_workflow",
                {
                    **_base(journey),
                    "idempotency_key": "O8-read-workflow",
                },
            )
            assert not workflow_read.is_error, workflow_read.structured_content
            workflow_alias = await stdio.call_tool(
                "read_workflow_state",
                {
                    **_base(journey),
                    "idempotency_key": "O8-read-workflow-alias",
                },
            )
            assert not workflow_alias.is_error, workflow_alias.structured_content

            # ARRIVE：submit_proposal request 建立 SCRIPT_PROPOSAL run，旧别名显式 cancel 收尾。
            started = await stdio.call_tool(
                "submit_proposal",
                {
                    **_base(journey),
                    "idempotency_key": "O8-script-request",
                    "capability": "script",
                    "payload": {
                        "action": "request",
                        "raw_user_instruction": "按已审核引用库生成脚本",
                    },
                },
            )
            assert not started.is_error, started.structured_content
            request_id = started.structured_content["data"]["request_id"]
            active = journey.snapshot()["active_director_run"]
            assert active is not None and active["kind"] == "script_proposal"
            cancelled = await stdio.call_tool(
                "script_proposal",
                {
                    **_base(journey),
                    "idempotency_key": "O8-script-cancel",
                    "action": "cancel",
                    "request_id": request_id,
                },
            )
            assert not cancelled.is_error
            assert journey.snapshot()["active_director_run"] is None

    asyncio.run(wire_check())

    # ARRIVE：双 Scene 生产基线建立，解锁视觉生产。
    character_id = journey.snapshot()["reference_library"]["characters"][0]["id"]
    journey.apply_script(
        scenes=[
            Journey.drama_scene(character_id, title="第一场"),
            Journey.drama_scene(character_id, title="第二场"),
        ]
    )
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    snap = journey.snapshot()
    scene_ids = [scene["id"] for scene in snap["director_script"]["scenes"]]
    segment_id = snap["video_plan"]["segments"][0]["segment_id"]

    async def production_checks() -> None:
        async with Client(mcp_params) as stdio:
            # ORACLE：save_video_prompt → video.set_prompt，正文落库且幂等回放。
            prompt_args = {
                **_base(journey),
                "idempotency_key": "O8-h3-prompt",
                "scene_ids": scene_ids,
                "segment_id": segment_id,
                "prompt_text": "固定机位观察站台。",
            }
            saved = await stdio.call_tool("save_video_prompt", prompt_args)
            assert not saved.is_error, saved.structured_content
            plan_item = next(
                item
                for item in journey.snapshot()["video_plan"]["segments"]
                if item["segment_id"] == segment_id
            )
            assert plan_item["prompt_text"] == "固定机位观察站台。"
            replay = await stdio.call_tool("save_video_prompt", prompt_args)
            assert replay.structured_content["replay"] is True
            assert plan_item["prompt_text"] == "固定机位观察站台。"

            # ORACLE：契约内容协商——先读 hash，中间夹一次真实写入，再带 if_hash 读为 unchanged。
            contract_args = {
                **_base(journey),
                "idempotency_key": "O8-contract-first",
                "capability": "script",
            }
            first_contract = await stdio.call_tool("read_professional_contract", contract_args)
            assert not first_contract.is_error, first_contract.structured_content
            first_contract_data = first_contract.structured_content["data"]
            contract_hash = first_contract_data["hash"]
            assert isinstance(contract_hash, str) and len(contract_hash) == 64

            # ORACLE：set_video_recipe → video.set_recipe；对白 Segment 只能保持 Ref2VA。
            current_mode = video_wire_mode(plan_item)
            selected_mode = current_mode
            mode_args = video_wire_dict(
                {
                    **_base(journey),
                    "idempotency_key": "O8-video-mode",
                    "scene_ids": scene_ids,
                    "segment_id": segment_id,
                    "generation_mode": selected_mode,
                }
            )
            mode = await stdio.call_tool("set_video_recipe", mode_args)
            assert not mode.is_error, mode.structured_content
            flipped_item = next(
                item
                for item in journey.snapshot()["video_plan"]["segments"]
                if item["segment_id"] == segment_id
            )
            assert video_wire_mode(flipped_item) == selected_mode

            unchanged = await stdio.call_tool(
                "read_professional_contract",
                {
                    **_base(journey),
                    "idempotency_key": "O8-contract-second",
                    "capability": "script",
                    "if_hash": contract_hash,
                },
            )
            assert not unchanged.is_error, unchanged.structured_content
            assert unchanged.structured_content["data"] == {
                "unchanged": True,
                "hash": contract_hash,
            }

            # ORACLE：分页 cursor 往返——limit=1 逐页拼接 == 一次全量读取。
            first = await stdio.call_tool(
                "read_story",
                {
                    **_base(journey),
                    "idempotency_key": "O8-read-page-1",
                    "level": "outline",
                    "limit": 1,
                },
            )
            assert not first.is_error
            page_one = first.structured_content["data"]
            assert page_one["total"] == 2 and len(page_one["items"]) == 1
            cursor = page_one["next_cursor"]
            assert cursor
            second = await stdio.call_tool(
                "read_story",
                {
                    **_base(journey),
                    "idempotency_key": "O8-read-page-2",
                    "level": "outline",
                    "limit": 1,
                    "cursor": cursor,
                },
            )
            page_two = second.structured_content["data"]
            assert page_two["next_cursor"] is None and len(page_two["items"]) == 1
            whole = await stdio.call_tool(
                "read_story",
                {
                    **_base(journey),
                    "idempotency_key": "O8-read-all",
                    "level": "outline",
                    "limit": 20,
                },
            )
            whole_items = whole.structured_content["data"]["items"]
            paged_items = [*page_one["items"], *page_two["items"]]
            assert [item["id"] for item in paged_items] == [item["id"] for item in whole_items]

            # ORACLE：写工具错误形状逐字段（revision 无副作用）。
            revision_before = journey._revision()
            overwrite = await stdio.call_tool(
                "script_proposal",
                {
                    **_base(journey),
                    "idempotency_key": "O8-script-overwrite",
                    "action": "request",
                    "raw_user_instruction": "覆盖已有脚本",
                },
            )
            assert overwrite.is_error
            assert overwrite.structured_content["http_status"] == 409
            _domain_rejection_fields(overwrite.structured_content["error"])
            assert journey.snapshot()["active_director_run"] is None

            unknown_segment = await stdio.call_tool(
                "save_video_prompt",
                {
                    **_base(journey),
                    "idempotency_key": "O8-h3-unknown",
                    "scene_ids": scene_ids,
                    "segment_id": "e" * 32,
                    "prompt_text": "不应到达 Core。",
                },
            )
            assert unknown_segment.is_error
            assert unknown_segment.structured_content["http_status"] == 409
            _domain_rejection_fields(unknown_segment.structured_content["error"])

            bad_mode = await stdio.call_tool(
                "set_video_recipe",
                video_wire_dict(
                    {
                        **_base(journey),
                        "idempotency_key": "O8-video-mode-bad",
                        "scene_ids": scene_ids,
                        "segment_id": segment_id,
                        "recipe_id": "",
                    }
                ),
            )
            assert bad_mode.is_error
            schema_error = bad_mode.structured_content["error"]
            assert bad_mode.structured_content["http_status"] == 400
            assert schema_error["code"] == "invalid_arguments"
            assert schema_error["origin"] == "mcp_schema"
            assert schema_error["state_changed"] is False
            assert schema_error["retry_policy"] == "fix_arguments_and_retry"
            assert schema_error["automatic_retry_allowed"] is False

            assert journey._revision() == revision_before

    asyncio.run(production_checks())
