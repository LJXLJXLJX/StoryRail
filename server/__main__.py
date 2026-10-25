from __future__ import annotations

import argparse
import asyncio
import signal
import threading
from pathlib import Path

from core.model_providers.agy_image.plugin import plugin_instance as agy_image_plugin
from core.model_providers.breeze_tts2.plugin import plugin_instance as breeze_tts2_plugin
from core.model_providers.codex_image.plugin import plugin_instance as codex_image_plugin
from core.model_providers.demucs_audio.plugin import plugin_instance as demucs_audio_plugin
from core.model_providers.ffmpeg_animatic import FFmpegAnimaticProvider
from core.model_providers.ffmpeg_audio_remix import FFmpegAudioRemixProvider
from core.model_providers.ffmpeg_final_assembly import FFmpegFinalAssemblyProvider
from core.model_providers.ffmpeg_pano_view import FFmpegPanoViewProvider
from core.model_providers.ffmpeg_video_frame import FFmpegVideoFrameProvider
from core.model_providers.http import UrllibTransport
from core.model_providers.minimax_h3.plugin import plugin_instance as minimax_h3_plugin
from core.model_providers.qwen_image.plugin import plugin_instance as qwen_image_plugin
from core.model_providers.registry import ProviderRegistry
from core.model_providers.seedvr2_7b_sharp_fp8.plugin import plugin_instance as seedvr2_plugin
from core.model_providers.settings import ProviderSettingsStore
from core.model_providers.stable_audio_3.plugin import plugin_instance as stable_audio_3_plugin
from core.model_providers.whisper_asr.plugin import plugin_instance as whisper_asr_plugin
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService

from .access import load_access_policy
from .agent_timing import AgentTimingLog
from .api import StoryRailApi
from .http import StoryRailHttpServer
from .provider_plugins import load_plugin
from .windows_runtime_lease import WindowsRuntimeLease
from .writer import SingleWriterLease


def main() -> None:
    parser = argparse.ArgumentParser(description="StoryRail 本地 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stories-directory", type=Path, default=Path(".stories"))
    parser.add_argument("--local-connection-directory", type=Path)
    parser.add_argument(
        "--access-policy-file", type=Path, help="启用受信 caller 与精确授权的外部应用边界"
    )
    parser.add_argument("--codex-image-endpoint", default="http://127.0.0.1:8792")
    parser.add_argument(
        "--breeze-endpoint", help="已部署 Breeze-TTS-2 API，例如 http://<windows-lan-ip>:7860"
    )
    parser.add_argument(
        "--whisper-endpoint", help="本机 whisper.cpp server，例如 http://127.0.0.1:8793"
    )
    parser.add_argument("--windows-runtime-endpoint")
    parser.add_argument("--windows-runtime-token-file", type=Path)
    parser.add_argument(
        "--provider-plugin",
        action="append",
        default=[],
        help="附加已安装插件：包名=HTTP endpoint；可重复",
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
        with SingleWriterLease(arguments.stories_directory):
            _serve(arguments, parser)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))


def _serve(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    workspaces = ProjectWorkspaceStore(arguments.stories_directory)
    registry = ProviderRegistry(
        ProviderSettingsStore(workspaces.root_directory / ".runtime" / "providers.json")
    )
    registry.install(codex_image_plugin(arguments.codex_image_endpoint))
    registry.install(agy_image_plugin(arguments.codex_image_endpoint))
    registry.install(demucs_audio_plugin(arguments.codex_image_endpoint))
    if arguments.whisper_endpoint is not None:
        registry.install(whisper_asr_plugin(arguments.whisper_endpoint))
    for tool, provider in (
        ("final_assembly", FFmpegFinalAssemblyProvider(arguments.codex_image_endpoint)),
        ("animatic", FFmpegAnimaticProvider(arguments.codex_image_endpoint)),
        ("video_frame", FFmpegVideoFrameProvider(arguments.codex_image_endpoint)),
        ("pano_view", FFmpegPanoViewProvider(arguments.codex_image_endpoint)),
        ("audio_remix", FFmpegAudioRemixProvider(arguments.codex_image_endpoint)),
    ):
        registry.register(tool, provider)
    windows_runtime_lease = None
    if arguments.breeze_endpoint is not None:
        breeze_transport = None
        if arguments.windows_runtime_token_file is not None:
            try:
                breeze_token = arguments.windows_runtime_token_file.read_text(
                    encoding="ascii"
                ).strip()
            except OSError as exc:
                parser.error(f"无法读取 Breeze/Windows Provider token file：{exc}")
            if not 32 <= len(breeze_token) <= 512:
                parser.error("Breeze/Windows Provider token 长度不合法。")
            breeze_transport = UrllibTransport({"Authorization": "Bearer " + breeze_token})
        registry.install(
            breeze_tts2_plugin(
                arguments.breeze_endpoint,
                workspaces.root_directory / ".runtime" / "breeze-tts2",
                breeze_transport,
            )
        )
    if arguments.windows_runtime_endpoint is not None:
        if arguments.windows_runtime_token_file is None:
            parser.error("配置 Windows runtime endpoint 时必须同时提供 token file。")
        try:
            token = arguments.windows_runtime_token_file.read_text(encoding="ascii").strip()
        except OSError as exc:
            parser.error(f"无法读取 Windows runtime token file：{exc}")
        if not 32 <= len(token) <= 512:
            parser.error("Windows runtime token 长度不合法。")
        try:
            windows_runtime_lease = WindowsRuntimeLease(
                arguments.windows_runtime_endpoint,
                token,
            )
        except ValueError as exc:
            parser.error(str(exc))
        transport = UrllibTransport({"Authorization": "Bearer " + token})
        registry.install(minimax_h3_plugin(arguments.windows_runtime_endpoint, transport))
        registry.install(seedvr2_plugin(arguments.windows_runtime_endpoint, transport))
        registry.install(stable_audio_3_plugin(arguments.windows_runtime_endpoint, transport))
        # 备选图片插件：Codex 先安装，未显式绑定时仍是生图/改图默认实现。
        registry.install(qwen_image_plugin(arguments.windows_runtime_endpoint, transport))

    for specification in arguments.provider_plugin:
        endpoint = specification.partition("=")[2]
        shared_transport = (
            transport
            if arguments.windows_runtime_endpoint is not None
            and endpoint.rstrip("/") == arguments.windows_runtime_endpoint.rstrip("/")
            else None
        )
        registry.install(load_plugin(specification, transport=shared_transport))

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
        name="storyrail-api-event-loop",
        daemon=True,
    )
    event_loop_thread.start()
    api = StoryRailApi(
        workspaces,
        create_structured_director_service,
        provider_registry=registry,
        playground_service=playground_service,
    )
    server = StoryRailHttpServer(
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
    if windows_runtime_lease is not None:
        windows_runtime_lease.start()

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, stop)
    actual_port = server_address[1] if server_address is not None else arguments.port
    print(f"StoryRail 已启动：http://{arguments.host}:{actual_port}（外部 Agent 应用入口）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if local_connection:
            local_connection.close()
        if windows_runtime_lease is not None:
            windows_runtime_lease.close()
        server.server_close()
        event_loop.call_soon_threadsafe(event_loop.stop)
        event_loop_thread.join()
        event_loop.close()


if __name__ == "__main__":
    main()
