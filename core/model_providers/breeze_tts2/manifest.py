"""Breeze-TTS-2 插件 manifest：音色设计与声音克隆两个 recipe。"""

from __future__ import annotations

from core.model_providers.manifest import (
    Capability,
    Field,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
    seed_field,
)

_TEXT = Field(
    "text", Widget.PROMPT, "朗读文本", max_length=20_000, min_length=1, role=Role.SPEECH_TEXT
)

MANIFEST = PluginManifest(
    plugin_id="breeze_tts2",
    plugin_version=1,
    label="Breeze-TTS-2",
    recipes=(
        Recipe(
            "breeze_tts2.voice_design",
            Capability.VOICE_DESIGN,
            "音色设计",
            params=(
                _TEXT,
                Field(
                    "voice_description",
                    Widget.TEXT,
                    "音色描述",
                    max_length=4_000,
                    min_length=1,
                    role=Role.PROMPT,
                    help="用自然语言描述音色，不提供参考音频。",
                ),
                seed_field(),
            ),
        ),
        Recipe(
            "breeze_tts2.clone",
            Capability.SPEECH_SYNTHESIZE,
            "声音克隆",
            slots=(
                Slot(
                    "voice",
                    Role.VOICE_REFERENCE,
                    "参考音色",
                    minimum=1,
                    media_types=("audio/wav",),
                ),
            ),
            params=(
                _TEXT,
                Field(
                    "reference_transcript",
                    Widget.TEXT,
                    "参考音频文字稿",
                    max_length=20_000,
                    min_length=1,
                    role=Role.VOICE_TRANSCRIPT,
                ),
                Field(
                    "performance_instruction",
                    Widget.TEXT,
                    "表演指示",
                    nullable=True,
                    max_length=200,
                    min_length=1,
                    help="自然语言表演方式（语气、情绪、语速、停顿），可留空。",
                ),
                seed_field(),
            ),
        ),
    ),
)
