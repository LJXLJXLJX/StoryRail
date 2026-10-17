#!/usr/bin/env python3
"""不调用模型的 Pi RPC 测试进程，覆盖 session 和异步事件合约。"""

import json
import sys
import time
from pathlib import Path
from uuid import uuid4


def option(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    if "--version" in sys.argv:
        print("0.85.0")
        return
    session_id = option("--session-id")
    sessions = Path(option("--session-dir"))
    sessions.mkdir(exist_ok=True)
    filename = sessions / (session_id + ".jsonl")
    count = len(filename.read_text().splitlines()) if filename.exists() else 0
    filename.touch()
    with Path("rpc-log.jsonl").open("a") as log:
        log.write(json.dumps({"argv": sys.argv[1:]}) + "\n")
    for line in sys.stdin:
        request = json.loads(line)
        kind = request["type"]
        with Path("rpc-log.jsonl").open("a") as log:
            log.write(json.dumps(request, ensure_ascii=False) + "\n")
        response = {"type": "response", "id": request["id"], "command": kind, "success": True}
        if kind == "get_state":
            response["data"] = {
                "sessionId": session_id,
                "sessionFile": str(filename),
                "model": {"id": option("--model")},
                "messageCount": count,
            }
        elif kind == "new_session":
            session_id = str(uuid4())
            filename = sessions / (session_id + ".jsonl")
            filename.touch()
            count = 0
            response["data"] = {"cancelled": False}
        elif kind == "compact":
            if option("--model") == "compact_fail":
                response.update(success=False, error="Nothing to compact")
            else:
                response["data"] = {"summary": "压缩摘要", "tokensBefore": 123}
        elif kind == "prompt":
            message = request["message"]
            if message == "eof":
                return
            if message == "malformed":
                print("not json", flush=True)
                return
            if message == "hang":
                time.sleep(60)
            if message == "stderr":
                sys.stderr.write("x" * 131072)
                sys.stderr.flush()
            if message != "late_ack":
                emit(response)
            emit({"type": "agent_start"})
            if message == "provider_error":
                emit(
                    {
                        "type": "message_end",
                        "message": {"role": "assistant", "errorMessage": "model unavailable"},
                    }
                )
                emit({"type": "agent_settled"})
                continue
            if message == "retry":
                emit(
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "errorMessage": "temporary failure",
                            "usage": {"input": 90, "cacheRead": 10, "output": 12},
                        },
                    }
                )
                emit({"type": "agent_end", "willRetry": True})
                emit({"type": "agent_start"})
            contract = json.loads(Path("output-contract.json").read_text())
            schema = contract["schema"]
            result = {
                key: item.get("const", "ok") for key, item in schema.get("properties", {}).items()
            }
            if message == "unicode":
                result = {"value": "before\u2028middle\u2029after"}
            emit(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "usage": {"input": 100, "cacheRead": 25, "output": 15},
                    },
                }
            )
            event = {
                "type": "tool_execution_end",
                "toolName": "submit_storyrail_result",
                "isError": False,
                "result": {
                    "details": {
                        "turn_id": "wrong" if message == "wrong_turn" else contract["turn_id"],
                        "result": result,
                    }
                },
            }
            if message in {"tool_retry", "tool_retry_twice"}:
                emit({**event, "isError": True})
            if message == "tool_retry_twice":
                emit({**event, "isError": True})
            if message != "missing":
                emit(event)
            if message == "duplicate":
                emit(event)
            emit({"type": "agent_end", "willRetry": False})
            with filename.open("a") as session:
                session.write(json.dumps({"type": "message", "message": {"role": "user"}}) + "\n")
            count += 1
            emit({"type": "agent_settled"})
            if message == "late_ack":
                emit(response)
            continue
        emit(response)


if __name__ == "__main__":
    main()
