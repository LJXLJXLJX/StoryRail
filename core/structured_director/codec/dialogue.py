"""对白 TTS 计划的严格编解码。"""

from __future__ import annotations

from typing import Any

from core.model_providers.recipe import RecipeParams

from ..models import DialogueAudio, DialoguePlan
from ._shared import _exact_object, _integer, _number, _object_list, _optional_string, _string


def _serialize_dialogue_plan(plan: DialoguePlan) -> dict[str, Any]:
    return {
        "source_script_revision": plan.source_script_revision,
        "items": [
            {
                "dialogue_line_id": item.dialogue_line_id,
                "seed": item.seed,
                "recipe_params": item.recipe_params.to_json(),
                "selected_audio_asset_id": item.selected_audio_asset_id,
                "start_seconds": item.start_seconds,
            }
            for item in plan.items
        ],
    }


def _parse_dialogue_plan(value: object) -> DialoguePlan:
    fields = _exact_object(value, {"source_script_revision", "items"})
    return DialoguePlan(
        source_script_revision=_integer(
            fields["source_script_revision"], "dialogue_plan.source_script_revision"
        ),
        items=_object_list(fields["items"], _parse_dialogue_audio),
    )


def _parse_dialogue_audio(value: object) -> DialogueAudio:
    fields = _exact_object(
        value,
        {
            "dialogue_line_id",
            "seed",
            "recipe_params",
            "selected_audio_asset_id",
            "start_seconds",
        },
    )
    return DialogueAudio(
        dialogue_line_id=_string(fields["dialogue_line_id"], "dialogue_audio.dialogue_line_id"),
        seed=_integer(fields["seed"], "dialogue_audio.seed"),
        recipe_params=RecipeParams.from_json(
            fields["recipe_params"], "dialogue_audio.recipe_params"
        ),
        selected_audio_asset_id=_optional_string(
            fields["selected_audio_asset_id"], "dialogue_audio.selected_audio_asset_id"
        ),
        start_seconds=(
            None
            if fields["start_seconds"] is None
            else _number(fields["start_seconds"], "dialogue_audio.start_seconds")
        ),
    )
