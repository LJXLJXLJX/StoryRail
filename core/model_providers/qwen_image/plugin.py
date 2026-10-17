"""把 QwenImageProvider 安装为全局可绑定的插件实例。"""

from __future__ import annotations

from pathlib import Path

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST, SKILL
from .provider import QwenImageProvider


def skill_resources() -> list[dict[str, str]]:
    directory = Path(__file__).parent / "skills" / SKILL
    return [
        {"name": str(path.relative_to(directory)), "text": path.read_text(encoding="utf-8")}
        for path in [directory / "SKILL.md", *sorted((directory / "references").iterdir())]
        if path.is_file()
    ]


def format_prompt_workset(value: dict) -> dict:
    """图片提示词工作集附带随插件发布的 Skill 正文与官方参考。"""
    return {**value, "plugin_skills": [{"name": SKILL, "resources": skill_resources()}]}


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    provider = QwenImageProvider(endpoint, transport)
    return PluginInstance(
        MANIFEST,
        endpoint=endpoint,
        recipes={recipe.id: provider for recipe in MANIFEST.recipes},
        prompt_formatter=format_prompt_workset,
    )
