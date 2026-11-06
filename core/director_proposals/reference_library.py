from __future__ import annotations

from dataclasses import dataclass

MAX_LOOKS = 8


@dataclass(frozen=True, slots=True)
class CharacterLookProposal:
    """一套造型：外观写服装、发型、配饰与状态；usage 写这套造型用在故事的什么时期或场合。"""

    name: str
    appearance: str
    usage: str

    def __post_init__(self) -> None:
        _require_text(self.name, "look.name")
        _require_text(self.appearance, "look.appearance")
        _require_text(self.usage, "look.usage")


@dataclass(frozen=True, slots=True)
class CharacterCardProposal:
    name: str
    visual_description: str | None
    voice_description: str
    looks: tuple[CharacterLookProposal, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, "character.name")
        if self.visual_description is None:
            _require_text(self.voice_description, "voice_identity.voice_description")
            if self.looks:
                raise ValueError("非出镜声音身份不能有造型。")
        else:
            _require_text(self.visual_description, "character.visual_description")
            if len(self.looks) > MAX_LOOKS:
                raise ValueError(f"单一角色最多 {MAX_LOOKS} 套造型。")
            if len({item.name.casefold() for item in self.looks}) != len(self.looks):
                raise ValueError("同一角色的造型名称不能重复。")


@dataclass(frozen=True, slots=True)
class NarratorProfileProposal:
    """旁白身份；中英旁白分别设计音色，所以两种语言各给一段音色描述。"""

    name: str
    zh_voice_description: str | None
    en_voice_description: str | None

    def __post_init__(self) -> None:
        _require_text(self.name, "narrator.name")
        if self.zh_voice_description is None and self.en_voice_description is None:
            raise ValueError("旁白身份至少需要一种语言的音色。")
        if self.zh_voice_description is not None:
            _require_text(self.zh_voice_description, "narrator.zh_voice_description")
        if self.en_voice_description is not None:
            _require_text(self.en_voice_description, "narrator.en_voice_description")


@dataclass(frozen=True, slots=True)
class ReferenceLibraryProposal:
    characters: tuple[CharacterCardProposal, ...]
    narrator: NarratorProfileProposal | None = None

    def __post_init__(self) -> None:
        if len({item.name.casefold() for item in self.characters}) != len(self.characters):
            raise ValueError("角色卡名称不能重复。")


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} 不能为空。")
