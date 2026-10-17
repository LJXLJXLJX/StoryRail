"""通用 recipe 线上形状、媒体校验与 Web 声明保持一致。"""

import json
from pathlib import Path

import pytest

from core.model_providers.breeze_tts2.manifest import MANIFEST
from core.model_providers.recipe import MediaInput, build_recipe_request, parse_recipe_wire


def test_speech_web_fixture_matches_manifest():
    path = Path(__file__).parents[1] / "web/src/test/speech_recipes.json"
    assert json.loads(path.read_text()) == [recipe.to_json() for recipe in MANIFEST.recipes]


def test_clone_wire_and_request_require_voice_transcript_and_wav():
    recipe = MANIFEST.recipe("breeze_tts2.clone")
    values = {
        "text": "你好",
        "voice_asset_id": "a" * 32,
        "reference_transcript": "完整文字稿",
        "performance_instruction": None,
        "seed": 42,
    }
    bindings, params = parse_recipe_wire(recipe, values)
    assert bindings["voice"][0].asset_id == "a" * 32
    request = build_recipe_request(
        MANIFEST, recipe.id, inputs={"voice": [MediaInput("audio/wav", b"wav")]}, params=params
    )
    assert request.param("performance_instruction") is None
    for invalid in ("", "x" * 20_001):
        with pytest.raises(ValueError):
            parse_recipe_wire(recipe, {**values, "reference_transcript": invalid})
    with pytest.raises(ValueError, match="audio/wav"):
        build_recipe_request(
            MANIFEST, recipe.id, inputs={"voice": [MediaInput("audio/mp3", b"mp3")]}, params=params
        )
    with pytest.raises(ValueError):
        parse_recipe_wire(recipe, {**values, "extra": True})
