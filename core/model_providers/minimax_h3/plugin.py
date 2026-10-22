"""把 MiniMax H3 安装为全局可绑定的插件实例：FL2VA 与 Ref2VA 两个 recipe 各有实现。"""

from __future__ import annotations

from core.model_providers.http import HttpTransport
from core.model_providers.minimax_h3.fl2va import MiniMaxH3FL2VAProvider
from core.model_providers.minimax_h3.ref2va import MiniMaxH3Ref2VAProvider
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .prompt_context import format_prompt_workset, prompt_skills


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    return PluginInstance(
        MANIFEST,
        endpoint=endpoint,
        prompt_formatter=format_prompt_workset,
        prompt_skills=prompt_skills,
        recipes={
            "minimax_h3.fl2va": MiniMaxH3FL2VAProvider(endpoint, transport),
            "minimax_h3.ref2va": MiniMaxH3Ref2VAProvider(endpoint, transport),
        },
    )
