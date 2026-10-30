"""MCP 参数校验失败逐项点名字段与原因；不触达 Core，也不回显参数值。"""

from __future__ import annotations

import asyncio

from mcp import Client

from integrations.storyrail_mcp.app import create_playground_server, create_server

ID = "a" * 32
BASE = {"project_id": ID, "expected_revision": 3, "idempotency_key": "k"}
SECRET = "私密创作正文-不得回显"


class RecordingBridge:
    def __init__(self):
        self.calls = []

    async def call(self, project_id, name, revision, key, arguments):
        self.calls.append(name)
        return 200, {"data": {}}

    async def call_playground(self, name, key, arguments):
        self.calls.append(name)
        return 200, {"data": {}}


def call(tool, arguments, *, playground=False):
    bridge = RecordingBridge()

    async def run():
        server = create_playground_server(bridge) if playground else create_server(bridge)
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)

    result = asyncio.run(run())
    return result, bridge


def error_of(result):
    assert result.is_error
    error = result.structured_content["error"]
    assert error["code"] == "invalid_arguments"
    assert error["origin"] == "mcp_schema"
    assert error["state_changed"] is False
    assert error["retry_policy"] == "fix_arguments_and_retry"
    assert SECRET not in result.content[0].text
    return error


def test_missing_required_field_is_named_in_message_and_issues():
    """实测场景：save_video_prompt 漏了 project_id。"""
    arguments = {
        **BASE,
        "scene_ids": [ID],
        "segment_id": ID,
        "prompt_text": SECRET,
    }
    del arguments["project_id"]
    result, bridge = call("save_video_prompt", arguments)
    error = error_of(result)
    assert bridge.calls == []
    assert error["message"] == "参数错误：缺少必填字段 project_id。"
    assert error["issues"] == [
        {"path": "project_id", "reason": "missing", "message": "缺少必填字段 project_id。"}
    ]


def test_wrong_names_types_and_ids_are_all_listed():
    result, bridge = call(
        "save_video_prompt",
        {
            **BASE,
            "project_id": "not-an-id",
            "expected_revision": "3",
            "scene_id": ID,
            "segment_ids": [ID],
            "prompt_text": SECRET,
        },
    )
    error = error_of(result)
    assert bridge.calls == []
    issues = {(item["path"], item["reason"]) for item in error["issues"]}
    assert issues == {
        ("project_id", "invalid_id"),
        ("expected_revision", "wrong_type"),
        ("scene_ids", "missing"),
        ("segment_id", "missing"),
        ("scene_id", "unknown_field"),
        ("segment_ids", "unknown_field"),
    }
    assert "另有 5 处问题" in error["message"]


def test_operation_errors_land_only_on_the_branch_named_by_op():
    shot = {
        "visible_character_ids": [],
        "composition": "c",
        "camera_movement": "m",
        "action": SECRET,
        "audio_direction": "a",
        "transition_in": None,
    }
    result, _ = call(
        "edit_script",
        {
            **BASE,
            "scene_ids": [ID],
            "operations": [
                {
                    "op": "insert_shot",
                    "scene_id": ID,
                    "after_shot_id": None,
                    "shot": shot,
                    "new_segment": {"duration_estimate_seconds": 3},
                }
            ],
        },
    )
    error = error_of(result)
    paths = [item["path"] for item in error["issues"]]
    assert "operations[0].new_segment.shot_indexes" in paths
    # 判别式联合：不出现其它 operation 分支的噪声。
    assert all(path.startswith("operations[0].new_segment") for path in paths)

    unknown, _ = call(
        "edit_script", {**BASE, "scene_ids": [ID], "operations": [{"op": "insert_shott"}]}
    )
    (issue,) = error_of(unknown)["issues"]
    assert issue["path"] == "operations[0].op" and issue["reason"] == "invalid_value"
    assert "insert_shot" in issue["expected"]


def test_custom_rule_reasons_are_passed_through():
    result, _ = call(
        "edit_script",
        {
            **BASE,
            "scene_ids": [ID],
            "operations": [
                {
                    "op": "insert_shot",
                    "scene_id": ID,
                    "after_shot_id": None,
                    "shot": {
                        "visible_character_ids": [],
                        "composition": "c",
                        "camera_movement": "m",
                        "action": "a",
                        "audio_direction": "a",
                        "transition_in": None,
                    },
                }
            ],
        },
    )
    (issue,) = error_of(result)["issues"]
    assert issue["reason"] == "invalid_combination"
    assert "attach_to_segment_id 或 new_segment" in issue["message"]

    outline, _ = call("read_story", {"project_id": ID, "level": "outline", "scene_ids": [ID]})
    assert any("outline" in item["message"] for item in error_of(outline)["issues"])


def test_playground_tools_report_issues_the_same_way():
    result, bridge = call("playground_runs", {"action": "get"}, playground=True)
    error = error_of(result)
    assert bridge.calls == []
    assert error["issues"]
    assert "run_ids" in error["message"]
