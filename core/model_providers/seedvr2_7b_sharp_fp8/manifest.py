"""SeedVR2 7B Sharp FP8 插件 manifest：视频超分。"""

from __future__ import annotations

from core.model_providers.manifest import (
    Capability,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    seed_field,
)

MANIFEST = PluginManifest(
    plugin_id="seedvr2_7b_sharp_fp8",
    plugin_version=1,
    label="SeedVR2 7B Sharp FP8",
    recipes=(
        Recipe(
            "seedvr2_7b_sharp_fp8.upscale",
            Capability.VIDEO_UPSCALE,
            "720p 超分",
            slots=(
                Slot("video", Role.SOURCE_VIDEO, "来源视频", minimum=1, media_types=("video/mp4",)),
            ),
            params=(seed_field(),),
        ),
    ),
)
