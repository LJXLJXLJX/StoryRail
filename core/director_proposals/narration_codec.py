from __future__ import annotations

from core.director_proposals.narration import NarrationReviewProposal
from core.director_proposals.schema_gen import (
    RECIPE_PARAMS_SCHEMA,
    ProposalError,
    generate_schema,
    parse_proposal,
)

_OUTPUT_SCHEMA = generate_schema(
    NarrationReviewProposal,
    overrides={
        "reply_markdown": {"minLength": 1, "maxLength": 10_000},
        "cue_updates[].cue_id": {"pattern": "^[0-9a-f]{32}$"},
        "cue_updates[].language": {"enum": ["zh", "en"]},
        "cue_updates[].recipe_params": {"__required__": True, **RECIPE_PARAMS_SCHEMA},
        "cue_updates[].seed": {"minimum": 0, "maximum": 2**63 - 1},
    },
)


def parse_narration_review_proposal(raw_response: str) -> NarrationReviewProposal:
    try:
        return parse_proposal(
            raw_response, _OUTPUT_SCHEMA, NarrationReviewProposal, domain="narration"
        )
    except ProposalError as exc:
        raise ProposalError("narration", exc.code, exc.message) from exc
