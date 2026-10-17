"""外部 Pi 原生工具调用的 MCP CLI；没有 Core 文件、人类 token 或厂商 adapter。"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
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
    async with Client(params) as client:
        if sys.argv[1] == "list":
            listed = await client.list_tools()
            if len(sys.argv) > 2:
                listed.tools = [tool for tool in listed.tools if tool.name == sys.argv[2]]
            print(listed.model_dump_json())
            return
        value = json.loads(Path(sys.argv[1]).read_text())
        result = await client.call_tool(value["tool"], value["arguments"])
        if "--drop-response" in sys.argv[2:]:
            os._exit(86)  # 验收故障：Core已提交，外部进程在交付结果前突然退出。
        data = {"request": value, "result": result.structured_content, "error": result.is_error}
        for block in result.content:
            if block.type in ("image", "audio"):
                extension = {
                    "image/png": "png",
                    "image/jpeg": "jpg",
                    "image/webp": "webp",
                    "audio/wav": "wav",
                    "audio/mpeg": "mp3",
                }[block.mime_type]
                path = Path("/workspace") / (uuid4().hex + "." + extension)
                path.write_bytes(base64.b64decode(block.data))
                data.setdefault("media_files", []).append(str(path))
        trace = Path("/workspace/tool-events.jsonl")
        with trace.open("a") as target:
            target.write(json.dumps(data, ensure_ascii=False) + "\n")
        print(json.dumps(data, ensure_ascii=False))
        if result.is_error:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
