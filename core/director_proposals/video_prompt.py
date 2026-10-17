"""视频提示词 proposal；正文约束与语言偏好来自当前 recipe Skill。"""

from dataclasses import dataclass

from core.director_proposals.schema_gen import ProposalError, generate_schema, parse_proposal


@dataclass(frozen=True, slots=True)
class VideoPromptProposal:
    prompt_text: str


OUTPUT_SCHEMA = generate_schema(
    VideoPromptProposal, overrides={"prompt_text": {"minLength": 1, "maxLength": 20_000}}
)


def parse_video_prompt_proposal(raw):
    try:
        return parse_proposal(raw, OUTPUT_SCHEMA, VideoPromptProposal, domain="video_prompt")
    except ProposalError as exc:
        raise ProposalError("video_prompt", exc.code, exc.message) from exc
