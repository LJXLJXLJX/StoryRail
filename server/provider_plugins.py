"""装配本机已安装的 recipe 插件；连接信息来自用户启动配置。"""

from __future__ import annotations

import re
from importlib import import_module
from urllib.parse import urlsplit

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

_PACKAGE = re.compile(r"[a-z][a-z0-9_]*")


def load_plugin(specification: str, *, transport: HttpTransport | None = None) -> PluginInstance:
    package, separator, endpoint = specification.partition("=")
    if not separator or not _PACKAGE.fullmatch(package):
        raise ValueError("Provider 插件配置必须是包名=HTTP endpoint。")
    url = urlsplit(endpoint)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Provider endpoint 必须是不含凭据、查询或片段的 HTTP 地址。")
    try:
        module = import_module(f"core.model_providers.{package}.plugin")
    except ModuleNotFoundError as exc:
        raise ValueError(f"Provider 插件包 {package} 未安装或缺少依赖。") from exc
    factory = getattr(module, "plugin_instance", None)
    if not callable(factory):
        raise ValueError(f"Provider 插件包 {package} 没有 plugin_instance 工厂。")
    plugin = factory(endpoint) if transport is None else factory(endpoint, transport=transport)
    if not isinstance(plugin, PluginInstance) or plugin.plugin_id != package:
        raise ValueError("Provider 插件实例身份必须等于包名。")
    return plugin
