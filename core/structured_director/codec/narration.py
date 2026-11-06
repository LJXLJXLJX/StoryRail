"""文档编解码：narration 域的 parse/serialize 函数对。"""

from __future__ import annotations

from typing import Any

from core.model_providers.recipe import RecipeParams

from ..models import NarrationCue, NarrationTrack
from ._shared import _exact_object, _integer, _optional_string, _string

_NARRATION_CUE_FIELDS = {"id", "zh", "en"}
_NARRATION_TRACK_FIELDS = {"text", "seed", "selected_audio_asset_id", "recipe_params"}


def _serialize_narration_track(track: NarrationTrack | None) -> dict[str, Any] | None:
    if track is None:
        return None
    return {
        "text": track.text,
        "seed": track.seed,
        "selected_audio_asset_id": track.selected_audio_asset_id,
        "recipe_params": track.recipe_params.to_json(),
    }


def _serialize_narration_cue(cue: NarrationCue) -> dict[str, Any]:
    return {
        "id": cue.id,
        "zh": _serialize_narration_track(cue.zh),
        "en": _serialize_narration_track(cue.en),
    }


def _parse_narration_track(value: object, label: str) -> NarrationTrack | None:
    if value is None:
        return None
    fields = _exact_object(value, _NARRATION_TRACK_FIELDS)
    return NarrationTrack(
        text=_string(fields["text"], f"{label}.text"),
        seed=_integer(fields["seed"], f"{label}.seed"),
        selected_audio_asset_id=_optional_string(
            fields["selected_audio_asset_id"], f"{label}.selected_audio_asset_id"
        ),
        recipe_params=RecipeParams.from_json(fields["recipe_params"], f"{label}.recipe_params"),
    )


def _parse_narration_cue(value: object) -> NarrationCue:
    fields = _exact_object(value, _NARRATION_CUE_FIELDS)
    return NarrationCue(
        id=_string(fields["id"], "narration_cue.id"),
        zh=_parse_narration_track(fields["zh"], "narration_cue.zh"),
        en=_parse_narration_track(fields["en"], "narration_cue.en"),
    )
