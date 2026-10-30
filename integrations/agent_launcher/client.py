"""外部工作区的固定 MCP 客户端，不拥有 Core 文件或管理身份。"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


def _render_tool_listing(listed, tool_name=None):
    if tool_name is None:
        return json.dumps({"tools": [tool.name for tool in listed.tools]}, ensure_ascii=False)
    matches = [tool for tool in listed.tools if tool.name == tool_name]
    if not matches:
        raise ValueError(f"未知工具：{tool_name}")
    return listed.model_copy(update={"tools": matches}).model_dump_json()


def connection_scope(config):
    """连接配置没有 scope 键时视为项目连接；只接受两种已知范围。"""
    scope = config.get("scope", "project")
    if scope not in ("project", "playground"):
        raise ValueError("连接范围不受支持。")
    return scope


DEBUG_PROMPT = "/app/integrations/storyrail_mcp/debug_prompt.md"


def debug_mode():
    """调试模式由本次 start 写入 startup.json；原生 Agent 随后启动的 MCP 据此注入同一提示词。"""
    startup = Path("/workspace/startup.json")
    return startup.exists() and json.loads(startup.read_text()).get("debug") is True


def agents_prompt(source, debug):
    prompt = Path(source).read_text()
    return Path(DEBUG_PROMPT).read_text() + "\n\n" + prompt if debug else prompt


def mcp_arguments(config, token, scope, debug=False):
    """原生 MCP 启动参数；playground 追加 --scope playground，调试模式追加 --debug。"""
    arguments = [
        "-m",
        "integrations.storyrail_mcp",
        "--core-origin",
        config["origin"],
        "--token-file",
        str(token),
    ]
    if scope == "playground":
        arguments += ["--scope", "playground"]
    if debug:
        arguments.append("--debug")
    return arguments


def codex_command():
    # MCP 启动参数只有固定客户端路径；不含 Token、模型或初始任务。
    return [
        "codex",
        "--cd",
        "/workspace",
        "-c",
        'cli_auth_credentials_store="file"',
        "-c",
        'mcp_servers.storyrail.command="' + sys.executable + '"',
        "-c",
        'mcp_servers.storyrail.args=["/app/client.py","mcp"]',
        "-c",
        'mcp_servers.storyrail.cwd="/app"',
        "-c",
        "mcp_servers.storyrail.required=true",
    ]


def agy_command():
    # AGY 的独立 HOME 只保存容器内登录态；MCP 配置由固定参数合并，不导入宿主配置。
    os.environ["HOME"] = "/agy"
    subprocess.run(
        ["agy", "mcp", "add", "storyrail", sys.executable, "/app/client.py", "mcp"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return ["agy", "--dangerously-skip-permissions"]


def kimi_command():
    """Write only the fixed StoryRail MCP and start Kimi Code without approvals."""
    kimi_home = Path(os.environ.get("KIMI_CODE_HOME", "/kimi-code"))
    kimi_home.mkdir(parents=True, exist_ok=True)
    (kimi_home / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "storyrail": {
                        "command": sys.executable,
                        "args": ["/app/client.py", "mcp"],
                    }
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.environ["KIMI_CODE_HOME"] = str(kimi_home)
    return ["kimi", "--auto"]


def grok_command():
    """Register only the fixed StoryRail MCP in Grok's isolated profile."""
    grok_home = Path(os.environ.get("GROK_HOME", "/grok"))
    grok_home.mkdir(parents=True, exist_ok=True)
    os.environ["GROK_HOME"] = str(grok_home)
    # The profile volume survives reconnects. Replace only our fixed server so
    # reconnects stay idempotent without touching unrelated Grok settings.
    subprocess.run(
        ["grok", "mcp", "remove", "storyrail"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    subprocess.run(
        ["grok", "mcp", "add", "storyrail", "--", sys.executable, "/app/client.py", "mcp"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return ["grok"]


def dsh_command():
    """Expose the loopback-only Web UI through Docker and use the fixed MCP patch."""
    # Load the native addon from the image; Docker's /tmp tmpfs is noexec.
    os.environ["NARB_DISABLE_NATIVE_CACHE"] = "1"
    dsh_home = Path(os.environ.get("DSH_HOME", "/dsh"))
    dsh_home.mkdir(parents=True, exist_ok=True)
    (dsh_home / "cordis.patch.yml").write_text(
        Path("/app/dsh-storyrail.cordis.yml").read_text(), encoding="utf-8"
    )
    host_port = os.environ["STORYRAIL_DSH_HOST_PORT"]
    subprocess.Popen(
        [
            "socat",
            "TCP-LISTEN:3081,fork,reuseaddr,bind=0.0.0.0",
            "TCP:127.0.0.1:3080",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return [
        "node",
        "--expose-internals",
        "/usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js",
        "--profile",
        "web",
        "--port",
        "3080",
        "--trusted-host",
        f"127.0.0.1:{host_port}",
        "--no-open",
    ]


def run_dsh_web():
    process = subprocess.Popen(
        dsh_command(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    host_port = os.environ["STORYRAIL_DSH_HOST_PORT"]
    for line in process.stdout:
        # dsh 打印的是容器内回环端口；改写成宿主发布端口，终端里的链接才能直接打开。
        line = re.sub(r"(dsh web: http://127\.0\.0\.1:)\d+/", rf"\g<1>{host_port}/", line)
        print(line, end="", flush=True)
        match = re.search(r"dsh web: http://127\.0\.0\.1:\d+/\?token=([A-Za-z0-9_-]+)", line)
        if match:
            Path("/workspace/dsh-browser-token").write_text(match.group(1), encoding="utf-8")
    return process.wait()


async def main():
    config = json.loads(Path("/workspace/connection.json").read_text())
    scope = connection_scope(config)
    if sys.argv[1] == "dsh-web":
        raise SystemExit(run_dsh_web())
    if sys.argv[1] == "start":
        os.environ["DISPLAY"] = ":99"
        display = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1x1x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            if Path("/tmp/.X11-unix/X99").exists():
                break
            if display.poll() is not None:
                raise ValueError("图片粘贴服务启动失败。")
            time.sleep(0.02)
        else:
            raise ValueError("图片粘贴服务启动超时。")
        debug = "--debug" in sys.argv[3:]
        if scope == "playground":
            startup = {"scope": "playground"}
            prompt = "/app/PLAYGROUND_PROMPT.md"
        else:
            startup = {"project_id": config["project_id"], "revision": config["revision"]}
            prompt = "/app/PROMPT.md"
        if debug:
            startup["debug"] = True
        Path("/workspace/startup.json").write_text(json.dumps(startup, ensure_ascii=False))
        Path("/workspace/AGENTS.md").write_text(agents_prompt(prompt, debug))
        agent = sys.argv[2] if len(sys.argv) > 2 else "pi"
        if agent == "codex":
            os.execvp("codex", codex_command())
        if agent == "agy":
            os.execvp("agy", agy_command())
        if agent == "kimi":
            os.execvp("kimi", kimi_command())
        if agent == "grok":
            os.execvp("grok", grok_command())
        if agent == "dsh":
            os.execvp(sys.executable, [sys.executable, "/app/client.py", "dsh-web"])
        if agent != "pi":
            raise ValueError("不支持的 Agent。")
        os.execvp("pi", ["pi", "--session-dir", "/workspace/sessions"])
    token = Path("/workspace/core-token")
    token.write_text(config["token"])
    token.chmod(0o600)
    arguments = mcp_arguments(config, token, scope, debug_mode())
    if sys.argv[1] == "mcp":
        os.execv(sys.executable, [sys.executable, *arguments])
    params = StdioServerParameters(
        command=sys.executable,
        cwd="/app",
        args=arguments,
    )
    async with Client(params) as client:
        if sys.argv[1] == "list":
            listed = await client.list_tools()
            tool_name = sys.argv[2] if len(sys.argv) > 2 else None
            print(_render_tool_listing(listed, tool_name))
            return
        request = json.loads(Path(sys.argv[1]).read_text())
        if scope == "playground":
            if "project_id" in request["arguments"]:
                raise ValueError("请求超出 Playground 范围。")
        elif request["arguments"].get("project_id") != config["project_id"]:
            raise ValueError("请求超出当前项目。")
        result = await client.call_tool(request["tool"], request["arguments"])
        print(result.model_dump_json())
        if result.is_error:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
