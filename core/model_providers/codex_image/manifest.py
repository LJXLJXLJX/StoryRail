"""Codex 图片 插件 manifest：生图与改图两个 recipe。"""

from __future__ import annotations

from core.model_providers.manifest import (
    IMAGE_MEDIA_TYPES,
    Capability,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    image_aspect_ratio_field,
    prompt_field,
)

MANIFEST = PluginManifest(
    plugin_id="codex_image",
    plugin_version=1,
    label="Codex 图片",
    recipes=(
        Recipe(
            "codex_image.generate",
            Capability.IMAGE_GENERATE,
            "生图",
            slots=(
                Slot(
                    "reference_image",
                    Role.REFERENCE_IMAGE,
                    "参考图",
                    maximum=5,
                    media_types=IMAGE_MEDIA_TYPES,
                ),
            ),
            params=(prompt_field(20_000), image_aspect_ratio_field()),
        ),
        Recipe(
            "codex_image.edit",
            Capability.IMAGE_EDIT,
            "改图",
            slots=(
                Slot(
                    "source_image",
                    Role.EDIT_SOURCE,
                    "底图",
                    minimum=1,
                    media_types=IMAGE_MEDIA_TYPES,
                ),
                Slot(
                    "reference_image",
                    Role.REFERENCE_IMAGE,
                    "参考图",
                    maximum=4,
                    media_types=IMAGE_MEDIA_TYPES,
                ),
            ),
            params=(prompt_field(20_000), image_aspect_ratio_field()),
            distinct_slots=("source_image", "reference_image"),
        ),
    ),
)
