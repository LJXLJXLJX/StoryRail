"""各域生成式 proposal codec 的统一错误与畸形 fixture 回归。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.director_proposals.keyframe_codec import parse_keyframe_plan
from core.director_proposals.location_codec import parse_location_plan
from core.director_proposals.narration_codec import parse_narration_review_proposal
from core.director_proposals.reference_library_codec import parse_reference_library_proposal
from core.director_proposals.schema_gen import ProposalError
from core.director_proposals.script_codec import parse_structured_director_script_proposal
from core.director_proposals.video_prompt import parse_video_prompt_proposal

_FIXTURES = Path(__file__).parent / "fixtures/proposal_malformed"
_PARSERS = {
    "narration": parse_narration_review_proposal,
    "video_prompt": parse_video_prompt_proposal,
    "reference_library": parse_reference_library_proposal,
    "script": parse_structured_director_script_proposal,
    "keyframe": parse_keyframe_plan,
    "location": parse_location_plan,
}


@pytest.mark.parametrize("domain", tuple(_PARSERS))
@pytest.mark.parametrize("case", ("fence", "extra", "missing", "type"))
def test_each_codec_rejects_malformed_fixtures_as_proposal_error(domain: str, case: str):
    fixtures = json.loads((_FIXTURES / f"{domain}.json").read_text())
    with pytest.raises(ProposalError) as raised:
        _PARSERS[domain](fixtures[case])
    assert raised.value.domain == domain
    assert raised.value.code in {"invalid_fence", "schema_violation"}


def test_wire_required_overrides_preserve_narrator_and_scene_driver():
    with pytest.raises(ProposalError, match="narrator"):
        parse_reference_library_proposal('{"characters":[]}')
    scene_without_driver = {
        "title": "场景",
        "summary": "摘要",
        "setting": "地点",
        "shots": [],
        "narration_cues": [],
    }
    with pytest.raises(ProposalError, match="driver"):
        parse_structured_director_script_proposal(
            json.dumps({"scenes": [scene_without_driver]}, ensure_ascii=False)
        )


def test_legacy_error_names_are_proposal_error_subclasses():
    for parser in _PARSERS.values():
        with pytest.raises(ProposalError):
            parser("{}")
