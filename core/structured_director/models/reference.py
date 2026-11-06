"""领域模型：reference 域（角色卡、旁白身份与引用库）。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ._shared import NarrationLanguage, _require_id, _require_text

MAX_CHARACTER_LOOKS = 8


@dataclass(frozen=True, slots=True)
class CharacterLook:
    """角色的一套造型：外观、使用场合与人类选定的造型图（角色图的唯一单位）。"""

    id: str
    name: str
    appearance: str
    usage: str
    selected_asset_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "look.id")
        _require_text(self.name, "look.name", 100)
        _require_text(self.appearance, "look.appearance", 2_000)
        _require_text(self.usage, "look.usage", 1_000)
        if self.selected_asset_id is not None:
            _require_id(self.selected_asset_id, "look.selected_asset_id")


@dataclass(frozen=True, slots=True)
class CharacterCard:
    id: str
    name: str
    visual_description: str | None
    looks: tuple[CharacterLook, ...] = ()
    voice_description: str = ""
    voice_reference_asset_id: str | None = None
    voice_reference_transcript: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "character.id")
        _require_text(self.name, "character.name", 200)
        if self.visual_description is None:
            _require_text(self.voice_description, "voice_identity.voice_description", 500)
            if self.looks:
                raise ValueError("非出镜声音身份不能有造型。")
        else:
            _require_text(self.visual_description, "character.visual_description", 4_000)
        _validate_looks(self.looks)
        if len(self.voice_description) > 500:
            raise ValueError("character.voice_description 过长。")
        if self.voice_reference_asset_id is not None:
            _require_id(self.voice_reference_asset_id, "character.voice_reference_asset_id")
        if self.voice_reference_transcript is not None:
            _require_text(
                self.voice_reference_transcript, "character.voice_reference_transcript", 20_000
            )

    def look(self, look_id: str) -> CharacterLook | None:
        return next((item for item in self.looks if item.id == look_id), None)

    @property
    def look_asset_ids(self) -> tuple[str, ...]:
        return tuple(
            item.selected_asset_id for item in self.looks if item.selected_asset_id is not None
        )


@dataclass(frozen=True, slots=True)
class NarratorVoice:
    """旁白单一语言的音色描述、参考 WAV 与其完整文字稿。"""

    voice_description: str
    voice_reference_asset_id: str | None = None
    voice_reference_transcript: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.voice_description, "narrator_voice.voice_description", 500)
        if self.voice_reference_asset_id is not None:
            _require_id(self.voice_reference_asset_id, "narrator_voice.voice_reference_asset_id")
        if self.voice_reference_transcript is not None:
            _require_text(
                self.voice_reference_transcript, "narrator_voice.voice_reference_transcript", 20_000
            )


@dataclass(frozen=True, slots=True)
class NarratorProfile:
    """独立旁白身份；中英旁白各用一套参考音色，分别克隆。"""

    id: str
    name: str
    zh: NarratorVoice | None
    en: NarratorVoice | None

    def __post_init__(self) -> None:
        _require_id(self.id, "narrator.id")
        _require_text(self.name, "narrator.name", 200)
        if not self.voices or any(
            voice is not None and not isinstance(voice, NarratorVoice)
            for voice in (self.zh, self.en)
        ):
            raise ValueError("narrator 至少包含一种有效语言的音色。")

    def voice(self, language: NarrationLanguage) -> NarratorVoice:
        voice = self.zh if language is NarrationLanguage.ZH else self.en
        if voice is None:
            raise ValueError("项目未启用该旁白语言。")
        return voice

    def with_voice(self, language: NarrationLanguage, voice: NarratorVoice) -> NarratorProfile:
        self.voice(language)
        return replace(self, **{language.value: voice})

    @property
    def voices(self) -> tuple[tuple[NarrationLanguage, NarratorVoice], ...]:
        return tuple(
            (language, voice)
            for language, voice in (
                (NarrationLanguage.ZH, self.zh),
                (NarrationLanguage.EN, self.en),
            )
            if voice is not None
        )

    @property
    def voice_reference_asset_ids(self) -> tuple[str, ...]:
        return tuple(
            voice.voice_reference_asset_id
            for _, voice in self.voices
            if voice.voice_reference_asset_id is not None
        )


@dataclass(frozen=True, slots=True)
class ReferenceLibrary:
    characters: tuple[CharacterCard, ...] = ()
    narrator: NarratorProfile | None = None

    def __post_init__(self) -> None:
        ids = [item.id for item in self.characters]
        if len(ids) != len(set(ids)):
            raise ValueError("引用库卡片 ID 不能重复。")
        look_ids = [look.id for card in self.characters for look in card.looks]
        if len(look_ids) != len(set(look_ids)) or set(look_ids) & set(ids):
            raise ValueError("造型 ID 不能重复。")
        if len({item.name.casefold() for item in self.characters}) != len(self.characters):
            raise ValueError("角色卡名称不能重复。")
        if self.narrator is not None and self.narrator.id in ids:
            raise ValueError("旁白身份 ID 不能与角色卡重复。")

    def look_owner(self, look_id: str) -> tuple[CharacterCard, CharacterLook] | None:
        for card in self.characters:
            look = card.look(look_id)
            if look is not None:
                return card, look
        return None


def _validate_looks(looks: tuple[CharacterLook, ...]) -> None:
    if len(looks) > MAX_CHARACTER_LOOKS:
        raise ValueError(f"单一角色最多 {MAX_CHARACTER_LOOKS} 套造型。")
    if len({item.id for item in looks}) != len(looks):
        raise ValueError("同一角色的造型 ID 不能重复。")
    if len({item.name.casefold() for item in looks}) != len(looks):
        raise ValueError("同一角色的造型名称不能重复。")
