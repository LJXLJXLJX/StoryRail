from __future__ import annotations

import argparse
import asyncio
import signal
import threading
from pathlib import Path

from core.media_tools import install_local_media_tools
from core.model_providers.registry import ProviderRegistry
from core.model_providers.settings import ProviderSettingsStore
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService

from .access import load_access_policy
from .agent_timing import AgentTimingLog
from .api import SlatehandApi
from .http import SlatehandHttpServer
from .provider_bundles import (
    close_services,
    install_bundles,
    read_provider_directories,
    start_services,
)
from .writer import SingleWriterLease


def main() -> None:
    parser = argparse.ArgumentParser(description="Slatehand 本地 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stories-directory", type=Path, default=Path(".stories"))
    parser.add_argument("--local-connection-directory", type=Path)
    parser.add_argument(
        "--access-policy-file", type=Path, help="启用受信 caller 与精确授权的外部应用边界"
    )
    parser.add_argument(
        "--provider-dir",
        type=Path,
        action="append",
        default=[],
        help="Provider 目录（根部含 slatehand-provider.toml）；可重复，按出现顺序安装",
    )
    arguments = parser.parse_args()
    if arguments.local_connection_directory and arguments.access_policy_file:
        parser.error("本机连接与自定义访问策略不能同时启用。")

    if arguments.host not in {"127.0.0.1", "localhost"}:
        parser.error("当前版本只允许监听本机回环地址。")
    if not 0 <= arguments.port <= 65535:
        parser.error("port 必须在 0 到 65535 之间。")

    if arguments.access_policy_file is not None:
        try:
            load_access_policy(arguments.access_policy_file)
        except (ValueError, OSError):
            parser.error("访问策略不可用，未启动服务。")
    try:
        provider_manifests = read_provider_directories(arguments.provider_dir)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        with SingleWriterLease(arguments.stories_directory):
            _serve(arguments, provider_manifests)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))


def _serve(arguments: argparse.Namespace, provider_manifests: list) -> None:
    workspaces = ProjectWorkspaceStore(arguments.stories_directory)
    registry = ProviderRegistry(
        ProviderSettingsStore(workspaces.root_directory / ".runtime" / "providers.json")
    )
    bundle_services = install_bundles(
        registry, provider_manifests, workspaces.root_directory / ".runtime" / "providers"
    )
    media_tools = install_local_media_tools(
        registry, workspaces.root_directory / ".runtime" / "media-tools"
    )
    if media_tools is None:
        print("未找到 ffmpeg/ffprobe：成片装配、Animatic、抽帧、全景取景与音轨重混不可用。")

    def create_structured_director_service(project_id: str) -> StructuredDirectorService:
        return StructuredDirectorService(
            workspaces.structured_director_store(project_id),
            registry,
        )

    from core.playground.service import PlaygroundService
    from core.playground.store import PlaygroundStore

    playground_service = PlaygroundService(
        PlaygroundStore(workspaces.root_directory / ".playground"),
        registry,
    )

    event_loop = asyncio.new_event_loop()
    event_loop_thread = threading.Thread(
        target=event_loop.run_forever,
        name="slatehand-api-event-loop",
        daemon=True,
    )
    event_loop_thread.start()
    api = SlatehandApi(
        workspaces,
        create_structured_director_service,
        provider_registry=registry,
        playground_service=playground_service,
    )
    server = SlatehandHttpServer(
        (arguments.host, arguments.port),
        api,
        event_loop,
        **(
            {"access_policy_file": arguments.access_policy_file}
            if arguments.access_policy_file is not None
            else {}
        ),
    )
    server.agent_timing = AgentTimingLog(
        workspaces.root_directory / ".runtime" / "agent-timing.jsonl"
    )
    local_connection = None
    if arguments.local_connection_directory:
        from .local_connection import LocalConnection

        local_connection = LocalConnection(
            arguments.local_connection_directory,
            api,
            event_loop,
            lambda: [project.id for project in workspaces.list()],
        )
        api.set_local_connection(local_connection)
        server.local_connection = local_connection
        server.access_policy_file = local_connection.policy_path
    server_address = getattr(server, "server_address", None)
    if server_address is not None:
        api.set_core_port(server_address[1])

    def interrupt(_signum: int, _frame: object) -> None:
        # 启动阶段 Provider 服务可能阻塞等待远端就绪；中断它并回滚已启动的服务。
        raise KeyboardInterrupt

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    def handle_signals(handler) -> None:
        signal.signal(signal.SIGINT, handler)
        for name in ("SIGTERM", "SIGHUP"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), handler)

    services_started = False
    handle_signals(interrupt)
    try:
        start_services(bundle_services)
        services_started = True
        handle_signals(stop)
        actual_port = server_address[1] if server_address is not None else arguments.port
        print(f"Slatehand 已启动：http://{arguments.host}:{actual_port}（外部 Agent 应用入口）")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if local_connection:
            local_connection.close()
        if services_started:
            close_services(bundle_services)
        if media_tools is not None:
            media_tools.close()
        server.server_close()
        event_loop.call_soon_threadsafe(event_loop.stop)
        event_loop_thread.join()
        event_loop.close()


if __name__ == "__main__":
    main()
