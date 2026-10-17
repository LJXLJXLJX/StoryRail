"""whisper.cpp 插件 manifest：WAV 转写。"""

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
    plugin_id="whisper_asr",
    plugin_version=1,
    label="whisper.cpp",
    recipes=(
        Recipe(
            "whisper_asr.transcribe",
            Capability.SPEECH_RECOGNIZE,
            "语音转写",
            slots=(
                Slot("audio", Role.SOURCE_AUDIO, "音频", minimum=1, media_types=("audio/wav",)),
            ),
            params=(
                Field(
                    "language",
                    Widget.ENUM,
                    "识别语言",
                    default="auto",
                    options=(Option("auto", "自动"), Option("zh", "中文"), Option("en", "英文")),
                    role=Role.LANGUAGE,
                ),
            ),
        ),
    ),
)
