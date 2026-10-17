"""旁白合成机制参数（Breeze 表演指示）的写入路径：按 recipe 保存、200 字上限与选择失效。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from provider_factory import provider_registry
from structured_director_fixtures import RecordingProvider
from test_narration_mutations import (
    ID_B,
    ID_C,
    ID_D,
    _cue,
    _document,
    _narration_generation,
    _voice_asset,
    _wav_asset,
)

from core.director_commands import parse_narration_cue_update
from core.director_proposals import NarrationCueProposal, NarrationTrackProposal
from core.director_proposals.narration_codec import parse_narration_review_proposal
from core.director_proposals.schema_gen import ProposalError
from core.model_providers.manifest import Capability
from core.model_providers.recipe import RecipeParams
from core.structured_director.http_requests import _parse_editable_narration_cues
from core.structured_director.models import NarrationLanguage
from core.structured_director.mutations import narration as narration_mutations
from core.structured_director.store import _check_changed_recipe_params

LIMIT = 200
CLONE = "breeze_tts2.clone"


def _params(instruction: str | None) -> dict:
    return {CLONE: {"performance_instruction": instruction}}


def _review(**update) -> str:
    return json.dumps(
        {
            "reply_markdown": "已调整。",
            "cue_updates": [
                {"cue_id": ID_C, "language": "zh", "seed": 42, "regenerate": True, **update}
            ],
        },
        ensure_ascii=False,
    )


def _catalog():
    return provider_registry(
        speech_provider=RecordingProvider(media_type="audio/wav", content=b"RIFF")
    )


def test_breeze_manifest_limits_instruction_to_200_characters():
    registry = _catalog()
    validate = registry.validate_recipe_params
    assert validate(Capability.SPEECH_SYNTHESIZE, CLONE, {"performance_instruction": "慢" * LIMIT})
    assert validate(Capability.SPEECH_SYNTHESIZE, CLONE, {"performance_instruction": None}) == {
        "performance_instruction": None
    }
    for invalid in ("慢" * (LIMIT + 1), ""):
        with pytest.raises(ValueError, match="表演指示"):
            validate(Capability.SPEECH_SYNTHESIZE, CLONE, {"performance_instruction": invalid})
    with pytest.raises(ValueError, match="多出"):
        validate(Capability.SPEECH_SYNTHESIZE, CLONE, {"performance_instruction": None, "x": 1})
    with pytest.raises(ValueError, match="不属于已安装"):
        validate(Capability.SPEECH_SYNTHESIZE, "other.clone", {})


def test_review_proposal_carries_recipe_params():
    proposal = parse_narration_review_proposal(
        _review(recipe_params=_params("低沉克制，语速放慢，句尾停顿半拍。"))
    )
    assert proposal.cue_updates[0].recipe_params == _params("低沉克制，语速放慢，句尾停顿半拍。")
    cleared = parse_narration_review_proposal(_review(recipe_params=_params(None)))
    assert cleared.cue_updates[0].recipe_params == _params(None)
    for raw in (_review(recipe_params={CLONE: "慢"}), _review()):
        with pytest.raises(ProposalError):
            parse_narration_review_proposal(raw)


def test_update_cue_command_sets_and_clears_instruction():
    command = parse_narration_cue_update(
        {
            "scope": {"scene_ids": [ID_B]},
            "cue_id": ID_C,
            "fields": {"zh": {"recipe_params": _params("  更轻柔，像在耳边低语。 ")}},
        }
    )
    assert command.track_fields == {
        "zh": {"recipe_params": RecipeParams.from_json(_params("更轻柔，像在耳边低语。"))}
    }
    document = _document(
        cue=_cue(selected=ID_D),
        assets=(_voice_asset(), _wav_asset()),
        generations=(_narration_generation(),),
    )
    result = narration_mutations.update_narration_cue(document, command, "set-instruction")
    cue = result.document.director_script.scenes[0].narration_cues[0]
    assert cue.zh.recipe_params.get(CLONE) == {"performance_instruction": "更轻柔，像在耳边低语。"}
    assert cue.zh.selected_audio_asset_id is None

    repeated = narration_mutations.update_narration_cue(result.document, command, "noop")
    assert repeated.receipt.status == "noop"

    cleared = parse_narration_cue_update(
        {
            "scope": {"scene_ids": [ID_B]},
            "cue_id": ID_C,
            "fields": {"en": {"recipe_params": _params(None)}},
        }
    )
    assert cleared.track_fields == {"en": {"recipe_params": RecipeParams.from_json(_params(None))}}
    with pytest.raises(ValueError, match="recipe_params"):
        parse_narration_cue_update(
            {
                "scope": {"scene_ids": [ID_B]},
                "cue_id": ID_C,
                "fields": {"zh": {"recipe_params": {CLONE: ["慢"]}}},
            }
        )


def test_store_validates_only_changed_recipe_params_against_installed_manifest():
    registry = _catalog()
    document = _document(cue=_cue())
    cue = document.director_script.scenes[0].narration_cues[0]

    def with_zh(params: dict):
        updated = cue.with_track(
            NarrationLanguage.ZH, replace(cue.zh, recipe_params=RecipeParams.from_json(params))
        )
        scene = replace(document.director_script.scenes[0], narration_cues=(updated,))
        return replace(
            document,
            director_script=replace(document.director_script, scenes=(scene,)),
        )

    _check_changed_recipe_params(registry, document, with_zh(_params("沉稳。")))
    with pytest.raises(ValueError, match="表演指示"):
        _check_changed_recipe_params(registry, document, with_zh(_params("慢" * (LIMIT + 1))))
    with pytest.raises(ValueError, match="不属于已安装"):
        _check_changed_recipe_params(registry, document, with_zh({"retired.tts": {"x": 1}}))
    # 未改动的旧值即使与当前 manifest 不符也原样保留。
    stale = with_zh({"retired.tts": {"x": 1}})
    _check_changed_recipe_params(registry, stale, stale)


def test_review_proposal_writes_instruction_and_invalidates_selection():
    document, resumed = narration_mutations.begin_narration_edit(
        _document(
            cue=_cue(selected=ID_D),
            assets=(_voice_asset(), _wav_asset()),
            generations=(_narration_generation(),),
        ),
        "更沉稳一些",
    )
    assert resumed is False
    proposal = parse_narration_review_proposal(_review(recipe_params=_params("沉稳、语速稍慢。")))
    updated = narration_mutations.apply_narration_review_proposal(document, proposal)
    cue = updated.director_script.scenes[0].narration_cues[0]
    assert cue.zh.recipe_params.get(CLONE) == {"performance_instruction": "沉稳、语速稍慢。"}
    assert cue.zh.seed == 42
    assert cue.zh.selected_audio_asset_id is None
    # 只更新了中文轨道，英文保持原样。
    assert cue.en.seed == 1 and cue.en.recipe_params == RecipeParams()


def test_script_contracts_accept_optional_recipe_params():
    track = NarrationTrackProposal("旁白", 1, _params("平静叙述。"))
    assert track.recipe_params == _params("平静叙述。")
    assert NarrationTrackProposal("旁白", 1).recipe_params == {}
    with pytest.raises(ValueError, match="recipe_params"):
        NarrationTrackProposal("旁白", 1, {CLONE: "平静叙述。"})
    cue = NarrationCueProposal(None, None, track, NarrationTrackProposal("Narration.", 1))
    assert cue.en.text == "Narration."

    parsed = _parse_editable_narration_cues(
        [
            {
                "id": ID_C,
                "start_shot_id": None,
                "end_shot_id": None,
                "zh": {
                    "text": "旁白",
                    "seed": 1,
                    "selected_audio_asset_id": None,
                    "recipe_params": _params("平静叙述。"),
                },
                "en": {
                    "text": "Narration.",
                    "seed": 1,
                    "selected_audio_asset_id": None,
                    "recipe_params": {},
                },
            }
        ],
        (),
    )
    assert parsed[0].zh.recipe_params == _params("平静叙述。")
    assert parsed[0].en.recipe_params == {}
