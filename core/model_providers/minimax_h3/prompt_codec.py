from __future__ import annotations

from core.director_proposals.schema_gen import ProposalError, generate_schema, parse_proposal

from .prompt_contract import H3PromptProposal

_OUTPUT_SCHEMA = generate_schema(
    H3PromptProposal,
    overrides={"prompt_text": {"minLength": 1, "maxLength": 20_000}},
)


def parse_h3_prompt_proposal(raw_response: str) -> H3PromptProposal:
    try:
        return parse_proposal(raw_response, _OUTPUT_SCHEMA, H3PromptProposal, domain="h3")
    except ProposalError as exc:
        raise ProposalError("h3", exc.code, exc.message) from exc
