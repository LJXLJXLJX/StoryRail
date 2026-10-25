"""外部 Agent 命令计时：只记元数据，区分 Core 耗时与 Agent 两次调用之间的自身耗时。"""

import asyncio
import hashlib
import json

from core.structured_director import JsonResponse
from server.agent_timing import AgentTimingLog
from server.http import StoryRailHttpServer

PROJECT = "a" * 32
COMMANDS = f"/api/projects/{PROJECT}/structured-director/application/commands"
AGENT_TOKEN = "agent_timing_" + "b" * 40
HUMAN_TOKEN = "human_timing_" + "c" * 40


def _body(name, **arguments):
    return json.dumps(
        {"name": name, "idempotency_key": "k", "arguments": arguments}, ensure_ascii=False
    ).encode()


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_records_metadata_and_agent_time_between_calls(tmp_path):
    log = AgentTimingLog(tmp_path / "agent-timing.jsonl")
    secret = "不应写入日志的画面正文"
    log.record(
        caller_id="agent-1",
        path=COMMANDS,
        body=_body("project.get_workset", capability="keyframe", note=secret),
        status=200,
        response_body={"data": {"text": secret}},
        started=10.0,
        finished=10.25,
    )
    log.record(
        caller_id="agent-1",
        path=COMMANDS,
        body=_body("keyframe.submit_proposal"),
        status=409,
        response_body={"error": {}},
        started=14.25,
        finished=14.5,
    )
    first, second = _lines(tmp_path / "agent-timing.jsonl")
    assert first["command"] == "project.get_workset" and first["detail"] == "keyframe"
    assert first["project_id"] == PROJECT and first["core_ms"] == 250
    assert first["agent_ms"] is None
    assert first["response_bytes"] == len(
        json.dumps({"data": {"text": secret}}, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert second["agent_ms"] == 4000 and second["status"] == 409
    assert secret not in (tmp_path / "agent-timing.jsonl").read_text(encoding="utf-8")


def test_only_agent_command_requests_are_timed(tmp_path):
    class Api:
        async def handle(self, method, path, body, *, media_type=None):
            return JsonResponse(200, {"ok": True})

    def caller(caller_id, role, token, capabilities):
        return {
            "id": caller_id,
            "role": role,
            "project_ids": [PROJECT],
            "capabilities": capabilities,
            "expires_at": 4_102_444_800,
            "grants": [],
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        }

    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "version": 2,
                "external_mutations": True,
                "callers": [
                    caller("agent-1", "agent", AGENT_TOKEN, ["project.read", "project.execute"]),
                    caller("human-1", "human", HUMAN_TOKEN, ["project.read", "human.write"]),
                ],
            }
        )
    )
    policy.chmod(0o600)
    loop = asyncio.new_event_loop()
    server = StoryRailHttpServer(("127.0.0.1", 0), Api(), loop, access_policy_file=policy)
    server.agent_timing = AgentTimingLog(tmp_path / "agent-timing.jsonl")
    try:
        read = _body("project.get_details", kind="director_plan")
        for token in (AGENT_TOKEN, HUMAN_TOKEN):
            loop.run_until_complete(
                server.handle_request("POST", COMMANDS, read, "application/json", f"Bearer {token}")
            )
        loop.run_until_complete(
            server.handle_request(
                "GET",
                f"/api/projects/{PROJECT}/structured-director",
                b"",
                None,
                f"Bearer {AGENT_TOKEN}",
            )
        )
    finally:
        server.server_close()
        loop.close()
    (entry,) = _lines(tmp_path / "agent-timing.jsonl")
    assert entry["caller_id"] == "agent-1"
    assert entry["command"] == "project.get_details" and entry["detail"] == "director_plan"
