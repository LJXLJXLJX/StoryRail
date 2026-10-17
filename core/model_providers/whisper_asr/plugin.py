"""把 whisper.cpp 安装为全局可绑定的插件实例。"""

from __future__ import annotations

from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .provider import WhisperASRProvider


def plugin_instance(endpoint: str) -> PluginInstance:
    provider = WhisperASRProvider(endpoint)
    return PluginInstance(
        MANIFEST, endpoint=endpoint, recipes={recipe.id: provider for recipe in MANIFEST.recipes}
    )
