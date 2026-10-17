"""实验外部Pi的原生shell客户端；只使用T09 MCP工具，不是新业务adapter。"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from core.director_proposals.script_codec import _OUTPUT_SCHEMA


async def main():
    config = json.loads(Path("/workspace/config.json").read_text())
    params = StdioServerParameters(
        command=sys.executable,
        cwd="/app",
        args=[
            "-m",
            "integrations.storyrail_mcp",
            "--core-origin",
            "http://core:8765",
            "--token-file",
            "/workspace/core-token",
        ],
    )
    action = sys.argv[1]
    if action == "request":
        command = config["initial_request"]
        arguments = {
            "project_id": config["project_id"],
            "action": "request",
            "expected_revision": command["expected_revision"],
            "idempotency_key": command["idempotency_key"],
            **command["arguments"],
        }
    elif action == "submit":
        state = json.loads(Path("/workspace/request-result.json").read_text())
        arguments = {
            "project_id": config["project_id"],
            "action": "submit",
            "expected_revision": state["receipt"]["new_revision"],
            "idempotency_key": "initial-submit",
            "request_id": state["data"]["request_id"],
            "proposal": json.loads(Path("/workspace/proposal.json").read_text()),
        }
    else:
        raise ValueError("只支持request和submit")
    async with Client(params) as client:
        response = await client.call_tool("script_proposal", arguments)
        result = response.structured_content
        print(
            json.dumps(
                {**result, **({"output_schema": _OUTPUT_SCHEMA} if action == "request" else {})},
                ensure_ascii=False,
            )
        )
        if response.is_error:
            raise SystemExit(1)
        Path(f"/workspace/{action}-result.json").write_text(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
