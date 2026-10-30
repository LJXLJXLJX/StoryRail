"""由用户粘贴执行；准备独立 Agent 容器，不读取或写入项目业务文件。"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from .clipboard import run_interactive

# 构建上下文与镜像摘要共用一份列表；新增提示词文件时同时触发镜像重建。
BUILD_CONTEXT_FILES = (
    "Dockerfile",
    "client.py",
    "gateway.py",
    "clipboard_input.py",
    "PROMPT.md",
    "PLAYGROUND_PROMPT.md",
    "dsh-storyrail.cordis.yml",
)
# MCP adapter 引用的 Core 单一事实源文本；只复制这些纯文本，不带 Core 代码或作品。
CORE_TEXT_FILES = ("core/director_proposals/skills/consistency_instruction.md",)
AGENT_IMAGE = "storyrail-external-agents:latest-v1"


def host_proxy_port(environment):
    """仅读取宿主本机无认证 HTTP 代理地址；不把原始环境或凭据交给容器。"""
    value = next(
        (
            environment[key]
            for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
            if environment.get(key)
        ),
        None,
    )
    if value is None:
        return None
    try:
        proxy = urlsplit(value)
        port = 80 if proxy.port is None else proxy.port
        valid = (
            proxy.scheme == "http"
            and proxy.hostname in {"localhost", "127.0.0.1", "::1"}
            and proxy.username is None
            and proxy.password is None
            and proxy.path in {"", "/"}
            and not proxy.query
            and not proxy.fragment
            and 1 <= port <= 65535
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Agent 宿主代理须为无认证的本机 HTTP 代理；请检查 HTTPS_PROXY。")
    return str(port)


def effective_host_proxy_port(environment):
    """环境变量优先；macOS 新终端未继承变量时读取当前系统 HTTP 代理。"""
    port = host_proxy_port(environment)
    if port is not None or sys.platform != "darwin":
        return port
    try:
        result = subprocess.run(
            ["scutil", "--proxy"], capture_output=True, text=True, check=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("无法读取 macOS 系统代理，请检查系统代理或设置 HTTPS_PROXY。") from None
    # 只读取顶层生效配置，不把 __SCOPED__ 内其它接口的代理当作全局代理。
    settings = dict(re.findall(r"^  (\w+) : ([^\r\n]+)$", result.stdout, re.MULTILINE))
    for scheme in ("HTTPS", "HTTP"):
        if settings.get(scheme + "Enable") != "1":
            continue
        host = settings.get(scheme + "Proxy", "")
        port = settings.get(scheme + "Port", "")
        if not host or not port:
            raise ValueError("macOS 系统 HTTP 代理缺少地址或端口，请检查系统代理。")
        if ":" in host:
            host = "[" + host + "]"
        return host_proxy_port({"HTTPS_PROXY": f"http://{host}:{port}"})
    return None


def control(path, request):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(20)
        client.connect(str(path))
        client.sendall(json.dumps(request).encode() + b"\n")
        with client.makefile("rb") as source:
            value = json.loads(source.readline(65537))
    if "error" in value:
        raise ValueError(value["error"])
    return value


def browser(path, project=None):
    login = control(path, {"action": "browser"})
    webbrowser.open(
        "http://127.0.0.1:5173/"
        + ("?project=" + project if project else "")
        + "#storyrail-login="
        + login["login"]
    )


def checked(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        # 子进程输出可能含模型凭据，不回显。
        if args[:3] == ["docker", "network", "create"] and (
            b"all predefined address pools have been fully subnetted" in result.stderr
        ):
            raise ValueError("Docker 网络地址池已耗尽，请清理未使用的临时网络后重试。")
        raise ValueError("启动准备失败，请确认 Docker 已运行、所选 Agent 已安装，再重试此命令。")
    return result.stdout


def prepare_build_context(root, context):
    """镜像内 /app 的完整布局；MCP adapter 启动所需的每个文件都必须从这里进入。"""
    shutil.copytree(
        root / "integrations" / "storyrail_mcp",
        context / "integrations" / "storyrail_mcp",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copyfile(root / "integrations" / "__init__.py", context / "integrations" / "__init__.py")
    shutil.copytree(
        root / "storyrail_contracts",
        context / "storyrail_contracts",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in CORE_TEXT_FILES:
        target = context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    for name in BUILD_CONTEXT_FILES:
        source = Path(__file__).parent / name
        if source.is_file():
            shutil.copyfile(source, context / name)


def agent_build_digest(root):
    digest = hashlib.sha256()
    paths = [Path(__file__).with_name(name) for name in BUILD_CONTEXT_FILES]
    paths.extend((root / "integrations" / "storyrail_mcp").rglob("*"))
    paths.extend((root / "storyrail_contracts").rglob("*"))
    paths.append(root / "integrations" / "__init__.py")
    paths.extend(root / name for name in CORE_TEXT_FILES)
    for path in sorted(
        path for path in paths if path.is_file() and "__pycache__" not in path.parts
    ):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare_agent_image(root, state_directory, *, update=False):
    """所有 Agent 共用同一镜像；构建锁跨项目、跨 Agent，等待后重新检查摘要。"""
    descriptor = os.open(
        state_directory / "agents-image.build.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "w") as build_lock:
        fcntl.flock(build_lock, fcntl.LOCK_EX)
        source_digest = agent_build_digest(root)
        try:
            installed_digest = (
                checked(
                    [
                        "docker",
                        "image",
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "storyrail.agent.source"}}',
                        AGENT_IMAGE,
                    ]
                )
                .decode()
                .strip()
            )
        except ValueError:
            installed_digest = ""
        if not update and installed_digest == source_digest:
            print("正在复用通用 Agent 镜像……", flush=True)
            return AGENT_IMAGE
        print("正在构建通用 Agent 镜像（Pi、Codex、AGY、Kimi、DeepSeek、Grok）……", flush=True)
        # 依赖安装层先于源码 COPY；普通源码变化复用依赖，显式更新才重新下载 latest。
        with tempfile.TemporaryDirectory(prefix="storyrail-agents-build-") as temporary:
            context = Path(temporary)
            prepare_build_context(root, context)
            checked(
                [
                    "docker",
                    "build",
                    *(["--no-cache"] if update else []),
                    "--label",
                    f"storyrail.agent.source={source_digest}",
                    "-t",
                    AGENT_IMAGE,
                    str(context),
                ]
            )
    return AGENT_IMAGE


def main():
    parser = argparse.ArgumentParser(description="连接 StoryRail 外部 Agent")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--core-port", type=int, default=8765)
    parser.add_argument("--project")
    parser.add_argument("--playground", action="store_true")
    parser.add_argument(
        "--agent", choices=["pi", "codex", "agy", "kimi", "dsh", "grok"], default="pi"
    )
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument(
        "--update-agents", action="store_true", help="更新通用镜像中的全部 Agent 至 latest"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="调试模式：要求 Agent 以第一优先级主动汇报 Core 的错误与不合理设计",
    )
    args = parser.parse_args()
    label = {
        "pi": "Pi",
        "codex": "Codex CLI",
        "agy": "Antigravity CLI",
        "kimi": "Kimi Code",
        "dsh": "DeepSeek Harness",
        "grok": "Grok Build",
    }[args.agent]
    try:
        if args.open_browser:
            browser(args.socket)
            return
        if bool(args.project) == bool(args.playground) or (
            args.project is not None and not re.fullmatch(r"[0-9a-f]{32}", args.project)
        ):
            raise ValueError("请从项目页面或 Playground 页面重新复制启动命令。")
        scope_key = args.project if not args.playground else "playground"
        if not 1 <= args.core_port <= 65535:
            raise ValueError("服务端口不合法。")
        if not shutil.which("docker"):
            raise ValueError("请先安装并打开 Docker Desktop，再粘贴同一条命令。")
        proxy_port = effective_host_proxy_port(os.environ)
        checked(["docker", "info"])
        root = Path(__file__).resolve().parents[2]
        image = prepare_agent_image(root, args.socket.parent, update=args.update_agents)
        connection = control(
            args.socket,
            {"action": "connect_playground"}
            if args.playground
            else {"action": "connect", "project_id": args.project},
        )
        connection["origin"] = "http://gateway:8080"
        volume = "storyrail-" + args.agent + "-" + scope_key
        checked(["docker", "volume", "create", volume])
        # 受信 provisioning 进程仅写 Agent volume，没有业务 volume 或宿主 home。
        checked(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--user",
                "0:0",
                "--mount",
                f"type=volume,source={volume},target=/workspace",
                image,
                "python",
                "-c",
                # 同一范围可同时运行多个 Agent；原子替换，正在运行的实例不会读到半截连接。
                "import os,sys; from pathlib import Path; "
                "p=Path('/workspace/connection.json'); "
                "t=p.with_name(p.name+'.'+os.urandom(6).hex()); "
                "t.write_bytes(sys.stdin.buffer.read()); "
                "os.chmod(t,0o600); os.chown(t,10002,10002); "
                "os.replace(t,p); os.chown('/workspace',10002,10002)",
            ],
            input=json.dumps(connection).encode(),
        )
        # 独立原生配置只在首次初始化时导入；后续由所选 Agent 自己切换模型、登录和刷新。
        profile_volume = "storyrail-native-" + args.agent + "-profile"
        profile_target = {
            "pi": "/pi",
            "codex": "/codex",
            "agy": "/agy",
            "kimi": "/kimi-code",
            "dsh": "/dsh",
            "grok": "/grok",
        }[args.agent]
        checked(["docker", "volume", "create", profile_volume])
        profile_root = Path(
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
            if args.agent == "codex"
            else os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent"))
            if args.agent == "pi"
            else profile_target
        ).expanduser()
        profile = {}
        for name in (
            ("auth.json",)
            if args.agent == "codex"
            else ("auth.json", "models.json", "settings.json")
            if args.agent == "pi"
            else ()
        ):
            source = profile_root / name
            if source.is_file():
                value = json.loads(source.read_text())
                if not isinstance(value, dict):
                    raise ValueError(f"{label} 配置格式不正确，请检查配置后重试。")
                profile[name] = value
        checked(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--user",
                "0:0",
                "--mount",
                f"type=volume,source={profile_volume},target={profile_target}",
                image,
                "python",
                "-c",
                "import json,os,sys;from pathlib import Path;"
                f"root=Path({profile_target!r}); data=json.load(sys.stdin);"
                "[((root/n).write_text(json.dumps(v)),os.chmod(root/n,0o600),"
                "os.chown(root/n,10002,10002)) "
                "for n,v in data.items() if not (root/'.initialized').exists()];"
                "(root/'.initialized').touch();os.chmod(root,0o700);os.chown(root,10002,10002)",
            ],
            input=json.dumps(profile).encode(),
        )
        print(
            "已连接 Playground。你可以描述想做的实验。"
            if args.playground
            else "已连接当前项目。你可以询问当前应该做什么。",
            flush=True,
        )
        if sys.platform == "darwin":
            print("粘贴图片：复制图片后按 Ctrl+V。图片只传入当前隔离 Agent。", flush=True)
        network = "storyrail-" + args.agent + "-" + secrets.token_hex(8)
        gateway = network + "-gateway"
        agent_container = network + "-agent"
        web_proxy = network + "-web" if args.agent == "dsh" else None
        environment = {
            **os.environ,
            "CORE_PORT": str(args.core_port),
            "GATEWAY_TOKEN": secrets.token_urlsafe(32),
        }
        # 不接受同名宿主环境覆盖；唯一来源是上面校验的本机代理地址。
        environment.pop("STORYRAIL_HOST_PROXY_PORT", None)
        if proxy_port is not None:
            environment["STORYRAIL_HOST_PROXY_PORT"] = proxy_port
        if args.playground:
            environment["STORYRAIL_SCOPE"] = "playground"
        else:
            environment["PROJECT_ID"] = args.project
        dsh_port = None
        if args.agent == "dsh":
            with socket.socket() as port_socket:
                port_socket.bind(("127.0.0.1", 0))
                dsh_port = port_socket.getsockname()[1]
            environment["STORYRAIL_DSH_HOST_PORT"] = str(dsh_port)
        environment["HTTPS_PROXY"] = "http://pi:" + environment["GATEWAY_TOKEN"] + "@gateway:8080"
        checked(["docker", "network", "create", "--internal", network])
        try:
            checked(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    gateway,
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--user",
                    "10002:10002",
                    "--env",
                    "CORE_PORT",
                    "--env",
                    "STORYRAIL_SCOPE" if args.playground else "PROJECT_ID",
                    "--env",
                    "GATEWAY_TOKEN",
                    *(["--env", "STORYRAIL_HOST_PROXY_PORT"] if proxy_port is not None else []),
                    image,
                    "python",
                    "/app/gateway.py",
                ],
                env=environment,
            )
            checked(["docker", "network", "connect", "--alias", "gateway", network, gateway])
            if dsh_port is not None:
                checked(
                    [
                        "docker",
                        "create",
                        "--name",
                        web_proxy,
                        "--read-only",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--user",
                        "10002:10002",
                        "--network",
                        "bridge",
                        "--publish",
                        f"127.0.0.1:{dsh_port}:3081",
                        image,
                        "socat",
                        "TCP-LISTEN:3081,fork,reuseaddr,bind=0.0.0.0",
                        f"TCP:{agent_container}:3081",
                    ],
                    env=environment,
                )
                checked(["docker", "network", "connect", network, web_proxy])
                checked(["docker", "start", web_proxy])
            agent_command = [
                "docker",
                "run",
                "--rm",
                "-it",
                "--name",
                agent_container,
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user",
                "10002:10002",
                "--network",
                network,
            ]
            if dsh_port is not None:
                agent_command.extend(["--env", "STORYRAIL_DSH_HOST_PORT"])
            agent_command.extend(
                [
                    "--tmpfs",
                    "/tmp:rw,mode=1777",
                    "--mount",
                    f"type=volume,source={volume},target=/workspace",
                    "--mount",
                    f"type=volume,source={profile_volume},target={profile_target}",
                    "--env",
                    "HTTPS_PROXY",
                    image,
                    "python",
                    "/app/client.py",
                    "start",
                    args.agent,
                    *(["--debug"] if args.debug else []),
                ]
            )
            if dsh_port is not None:
                print(f"DeepSeek Harness 将在浏览器打开：http://127.0.0.1:{dsh_port}", flush=True)
            result = run_interactive(
                agent_command,
                env=environment,
                container=agent_container,
                agent=args.agent,
                ready_url=f"http://127.0.0.1:{dsh_port}" if dsh_port is not None else None,
            )
            raise SystemExit(result)
        finally:
            subprocess.run(["docker", "rm", "-f", agent_container], capture_output=True)
            if web_proxy is not None:
                subprocess.run(["docker", "rm", "-f", web_proxy], capture_output=True)
            subprocess.run(["docker", "rm", "-f", gateway], capture_output=True)
            subprocess.run(["docker", "network", "rm", network], capture_output=True)
    except KeyboardInterrupt:
        print(f"已停止 {label}。项目进度保留，稍后可用同一条命令重新连接。")
        raise SystemExit(130) from None
    except (OSError, ValueError) as exc:
        print(str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
