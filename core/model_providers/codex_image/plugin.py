"""把 CodexImageProvider 安装为全局可绑定的插件实例。"""

from __future__ import annotations

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .provider import CodexImageProvider


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    provider = CodexImageProvider(endpoint, transport)
    return PluginInstance(
        MANIFEST, endpoint=endpoint, recipes={recipe.id: provider for recipe in MANIFEST.recipes}
    )
