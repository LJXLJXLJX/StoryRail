"""Stable Audio 3 Medium 插件 manifest：文生音频。"""

from __future__ import annotations

from core.model_providers.manifest import (
    Capability,
    Field,
    PluginManifest,
    Recipe,
    Role,
    Widget,
    prompt_field,
    seed_field,
)

MANIFEST = PluginManifest(
    plugin_id="stable_audio_3",
    plugin_version=1,
    label="Stable Audio 3 Medium",
    recipes=(
        Recipe(
            "stable_audio_3.generate",
            Capability.AUDIO_GENERATE,
            "文生音频",
            params=(
                prompt_field(1_000, "音乐或音效描述"),
                Field(
                    "duration_seconds",
                    Widget.NUMBER,
                    "时长（秒）",
                    default=10,
                    minimum=1,
                    maximum=380,
                    role=Role.DURATION,
                ),
                seed_field(),
            ),
        ),
    ),
)
