"""IndexTTS2.5 插件：参考音色克隆、语速与八维情感。"""

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
    seed_field,
)

MANIFEST = PluginManifest(
    plugin_id="indextts2",
    plugin_version=1,
    label="IndexTTS2.5",
    recipes=(
        Recipe(
            "indextts2.synthesize",
            Capability.SPEECH_SYNTHESIZE,
            "IndexTTS2.5 声音克隆",
            slots=(
                Slot(
                    "voice", Role.VOICE_REFERENCE, "参考音色", minimum=1, media_types=("audio/wav",)
                ),
            ),
            params=(
                Field(
                    "text",
                    Widget.PROMPT,
                    "朗读文本",
                    min_length=1,
                    max_length=20_000,
                    role=Role.SPEECH_TEXT,
                ),
                seed_field(),
                Field(
                    "language",
                    Widget.ENUM,
                    "语言",
                    default="auto",
                    options=(
                        Option("auto", "中英自动"),
                        Option("zh", "中文"),
                        Option("en", "英文"),
                    ),
                    role=Role.LANGUAGE,
                ),
                Field(
                    "duration_factor",
                    Widget.SLIDER,
                    "语速因子",
                    default=1.0,
                    minimum=0.5,
                    maximum=2.0,
                ),
                Field(
                    "emotion_vector",
                    Widget.VECTOR,
                    "情感向量",
                    default=[0.0] * 8,
                    dimension=8,
                    minimum=-1.0,
                    maximum=1.0,
                    component_labels=(
                        "高兴",
                        "愤怒",
                        "悲伤",
                        "害怕",
                        "厌恶",
                        "低落",
                        "惊讶",
                        "平静",
                    ),
                ),
            ),
        ),
    ),
)
