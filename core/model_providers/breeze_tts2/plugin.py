"""把 Breeze-TTS-2 安装为全局可绑定的插件实例：同一实现承担音色设计与声音克隆。"""

from __future__ import annotations

from pathlib import Path

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .provider import BreezeTTS2Provider


def plugin_instance(
    endpoint: str, spool_dir: Path, transport: HttpTransport | None = None
) -> PluginInstance:
    provider = BreezeTTS2Provider(endpoint, spool_dir, transport)
    return PluginInstance(
        MANIFEST,
        recipes={"breeze_tts2.voice_design": provider, "breeze_tts2.clone": provider},
        endpoint=endpoint,
    )
