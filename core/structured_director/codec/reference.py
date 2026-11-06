"""文档编解码：reference 域的 parse/serialize 函数对。"""

from __future__ import annotations

from typing import Any

from ..models import (
    CharacterCard,
    CharacterLook,
    NarratorProfile,
    NarratorVoice,
)
from ._shared import _exact_object, _object_list, _optional_string, _string

_CHARACTER_FIELDS = {
    "id",
    "name",
    "visual_description",
    "voice_description",
    "voice_reference_asset_id",
    "voice_reference_transcript",
    "looks",
}


def _serialize_character(card: CharacterCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "visual_description": card.visual_description,
        "voice_description": card.voice_description,
        "voice_reference_asset_id": card.voice_reference_asset_id,
        "voice_reference_transcript": card.voice_reference_transcript,
        "looks": [_serialize_look(item) for item in card.looks],
    }


def _serialize_look(look: CharacterLook) -> dict[str, str | None]:
    return {
        "id": look.id,
        "name": look.name,
        "appearance": look.appearance,
        "usage": look.usage,
        "selected_asset_id": look.selected_asset_id,
    }


def _serialize_narrator(profile: NarratorProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "zh": _serialize_narrator_voice(profile.zh),
        "en": _serialize_narrator_voice(profile.en),
    }


def _serialize_narrator_voice(voice: NarratorVoice | None) -> dict[str, Any] | None:
    if voice is None:
        return None
    return {
        "voice_description": voice.voice_description,
        "voice_reference_asset_id": voice.voice_reference_asset_id,
        "voice_reference_transcript": voice.voice_reference_transcript,
    }


def _parse_character(value: object) -> CharacterCard:
    if not isinstance(value, dict) or set(value) not in (
        _CHARACTER_FIELDS,
        _CHARACTER_FIELDS - {"voice_reference_transcript"},
    ):
        raise ValueError("character 字段不完整或包含未知字段。")
    fields = value
    return CharacterCard(
        id=_string(fields["id"], "character.id"),
        name=_string(fields["name"], "character.name"),
        visual_description=_optional_string(
            fields["visual_description"], "character.visual_description"
        ),
        voice_description=_string(fields["voice_description"], "character.voice_description"),
        voice_reference_asset_id=_optional_string(
            fields["voice_reference_asset_id"], "character.voice_reference_asset_id"
        ),
        voice_reference_transcript=_optional_string(
            fields.get("voice_reference_transcript"), "character.voice_reference_transcript"
        ),
        looks=_object_list(fields["looks"], _parse_look),
    )


def _parse_look(value: object) -> CharacterLook:
    fields = _exact_object(value, {"id", "name", "appearance", "usage", "selected_asset_id"})
    return CharacterLook(
        id=_string(fields["id"], "look.id"),
        name=_string(fields["name"], "look.name"),
        appearance=_string(fields["appearance"], "look.appearance"),
        usage=_string(fields["usage"], "look.usage"),
        selected_asset_id=_optional_string(fields["selected_asset_id"], "look.selected_asset_id"),
    )


def _parse_narrator(value: object) -> NarratorProfile:
    fields = _exact_object(value, {"id", "name", "zh", "en"})
    return NarratorProfile(
        id=_string(fields["id"], "narrator.id"),
        name=_string(fields["name"], "narrator.name"),
        zh=_parse_narrator_voice(fields["zh"], "narrator.zh"),
        en=_parse_narrator_voice(fields["en"], "narrator.en"),
    )


def _parse_narrator_voice(value: object, label: str) -> NarratorVoice | None:
    if value is None:
        return None
    fields = _exact_object(
        value, {"voice_description", "voice_reference_asset_id", "voice_reference_transcript"}
    )
    return NarratorVoice(
        voice_description=_string(fields["voice_description"], f"{label}.voice_description"),
        voice_reference_asset_id=_optional_string(
            fields["voice_reference_asset_id"], f"{label}.voice_reference_asset_id"
        ),
        voice_reference_transcript=_optional_string(
            fields["voice_reference_transcript"], f"{label}.voice_reference_transcript"
        ),
    )
