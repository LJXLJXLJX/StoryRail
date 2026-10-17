"""对白说话者二选一：引用库角色 character_id，或引用库外说话者 speaker_label。"""

import json

import pytest
from pydantic import ValidationError

from core.director_commands.script_operations import _dialogues
from core.director_proposals.schema_gen import ProposalError
from core.director_proposals.script_codec import parse_structured_director_script_proposal
from core.structured_director import DialogueLine
from core.structured_director.codec.script import _parse_dialogue_line, _serialize_segment
from core.structured_director.models import ShotSegment
from integrations.storyrail_mcp.production_tools import Dialogue

ID = "a" * 32


@pytest.mark.parametrize(
    ("character_id", "speaker_label"),
    [(None, None), (ID, "研究员"), (None, " "), (None, "长" * 61)],
)
def test_model_requires_exactly_one_valid_speaker(character_id, speaker_label):
    with pytest.raises(ValueError):
        DialogueLine(character_id, "台词。", "", speaker_label=speaker_label)


def test_persistence_round_trips_speaker_label_and_accepts_omitted_key():
    line = DialogueLine(None, "开始宣读。", "平板", speaker_label="研究员")
    segment = ShotSegment(ID, 3.0, "研究员对着麦克风。", (line,), None)
    (serialized,) = _serialize_segment(segment)["dialogue_lines"]
    assert serialized == {
        "character_id": None,
        "speaker_label": "研究员",
        "text": "开始宣读。",
        "delivery": "平板",
    }
    assert _parse_dialogue_line(serialized) == line
    legacy = {"character_id": ID, "text": "好。", "delivery": ""}
    assert _parse_dialogue_line(legacy) == DialogueLine(ID, "好。", "")


def _proposal(dialogue: dict) -> str:
    segment = {
        "duration_estimate_seconds": 3.0,
        "action": "研究员对着麦克风宣读。",
        "dialogue_lines": [dialogue],
        "boundary_from_previous": None,
    }
    shot = {
        "visible_character_ids": [],
        "composition": "中景。",
        "camera_movement": "固定。",
        "action": "宣读。",
        "audio_direction": "扬声器底噪。",
        "transition_in": None,
        "segments": [segment],
    }
    scene = {
        "driver": "drama",
        "title": "序幕",
        "summary": "宣读协议。",
        "setting": "实验室。",
        "shots": [shot],
        "narration_cues": [],
    }
    return json.dumps({"scenes": [scene]}, ensure_ascii=False)


def test_script_proposal_accepts_external_speaker():
    proposal = parse_structured_director_script_proposal(
        _proposal(
            {"character_id": None, "speaker_label": "研究员", "text": "开始。", "delivery": ""}
        )
    )
    (line,) = proposal.scenes[0].shots[0].segments[0].dialogue_lines
    assert (line.character_id, line.speaker_label) == (None, "研究员")


@pytest.mark.parametrize(
    "speaker",
    [
        {"character_id": None},
        {"character_id": None, "speaker_label": None},
        {"character_id": ID, "speaker_label": "研究员"},
        {"character_id": None, "speaker_label": ""},
    ],
)
def test_script_proposal_rejects_missing_or_double_speaker(speaker):
    with pytest.raises(ProposalError):
        parse_structured_director_script_proposal(
            _proposal({**speaker, "text": "开始。", "delivery": ""})
        )


def test_edit_script_operations_and_mcp_accept_external_speaker():
    value = {"character_id": None, "speaker_label": "广播", "text": "新闻。", "delivery": ""}
    (line,) = _dialogues([value])
    assert (line.character_id, line.speaker_label) == (None, "广播")
    with pytest.raises(ValueError):
        _dialogues([{**value, "speaker_label": None}])
    assert Dialogue.model_validate(value).speaker_label == "广播"
    assert Dialogue.model_validate({"character_id": ID, "text": "好。", "delivery": ""})
    with pytest.raises(ValidationError):
        Dialogue.model_validate({**value, "speaker_label": ""})
