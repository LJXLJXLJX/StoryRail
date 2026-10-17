"""安装 IndexTTS2.5 recipe 实现；连接由宿主启动配置提供。"""

from __future__ import annotations

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .provider import IndexTTS2Provider


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    provider = IndexTTS2Provider(endpoint, transport)
    return PluginInstance(MANIFEST, endpoint=endpoint, recipes={"indextts2.synthesize": provider})
