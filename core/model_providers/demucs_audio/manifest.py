"""Demucs 插件 manifest：从视频分离人声或背景声。"""

from __future__ import annotations

from core.model_providers.manifest import (
    Capability,
    Field,
    Option,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
)

MANIFEST = PluginManifest(
    plugin_id="demucs_audio",
    plugin_version=1,
    label="Demucs",
    recipes=(
        Recipe(
            "demucs_audio.separate",
            Capability.AUDIO_SEPARATE,
            "音轨分离",
            slots=(
                Slot("video", Role.SOURCE_VIDEO, "来源视频", minimum=1, media_types=("video/mp4",)),
            ),
            params=(
                Field(
                    "stem",
                    Widget.ENUM,
                    "音轨",
                    default="voice",
                    role=Role.AUDIO_STEM,
                    options=(Option("voice", "人声"), Option("background", "背景声")),
                ),
            ),
        ),
    ),
)
