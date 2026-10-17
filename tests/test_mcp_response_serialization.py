"""MCP 结果的 text 始终携带完整 JSON：只读 text 的客户端也能拿到数据。"""

from __future__ import annotations

import asyncio
import json

from mcp import Client

from integrations.storyrail_mcp.app import create_server

PROJECT_ID = "a" * 32
RUN_ID = "b" * 32
LARGE_TEXT = "x" * 10000


class _LargeBridge:
    async def call(self, project_id, name, revision, key, arguments):
        del project_id, name, revision, key, arguments
        return 200, {"data": {"blob": LARGE_TEXT}}


def test_large_mcp_response_text_carries_full_data() -> None:
    async def run() -> None:
        async with Client(create_server(_LargeBridge())) as client:
            result = await client.call_tool(
                "read_run", {"project_id": PROJECT_ID, "run_id": RUN_ID}
            )
        assert len(result.content) == 1
        text = json.loads(result.content[0].text)
        assert text["data"]["blob"] == LARGE_TEXT
        assert text == result.structured_content

    asyncio.run(run())
