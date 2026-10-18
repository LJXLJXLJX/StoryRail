"""启动 stdio adapter；启动配置不成为模型工具参数。"""

import argparse
import asyncio
from pathlib import Path

from mcp.server.stdio import stdio_server

from .app import create_playground_server, create_server
from .bridge import CoreBridge


def main():
    parser = argparse.ArgumentParser(description="StoryRail 受限 MCP stdio adapter")
    parser.add_argument("--core-origin", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--scope", choices=["project", "playground"], default="project")
    parser.add_argument(
        "--proposal-directory",
        type=Path,
        default=Path("/workspace/proposals"),
        help="项目 Agent 大型 proposal 的固定工作区目录。",
    )
    args = parser.parse_args()
    try:
        bridge = CoreBridge(args.core_origin, args.token_file)
    except ValueError as exc:
        parser.error(str(exc))
    server = (
        create_playground_server(bridge)
        if args.scope == "playground"
        else create_server(bridge, proposal_directory=args.proposal_directory)
    )

    async def serve():
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    asyncio.run(serve())


if __name__ == "__main__":
    main()
