"""内置与外部引用库共用的严格专业输出契约；无 Agent runtime 依赖。"""

from .reference_library import (
    ReferenceLibraryProposal,
)
from .schema_gen import ProposalError, generate_schema, parse_proposal

REFERENCE_LIBRARY_OUTPUT_SCHEMA = generate_schema(
    ReferenceLibraryProposal,
    overrides={
        "characters[].name": {"minLength": 1},
        "characters[].visual_description": {
            "anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}],
            "description": "非出镜声音用 null，且声音描述非空；旁白使用 narrator。",
        },
        "characters[].looks": {
            "__required__": True,
            "maxItems": 8,
            "description": "出镜角色至少 1 套、最多 8 套造型；非出镜声音为空数组。",
        },
        "characters[].looks[].name": {"minLength": 1},
        "characters[].looks[].appearance": {
            "minLength": 1,
            "description": "本套造型的服装、发型、配饰与身体状态；不重复角色固有外形。",
        },
        "characters[].looks[].usage": {
            "minLength": 1,
            "description": "本套造型用于故事的哪个时期、场合或剧情状态。",
        },
        "narrator": {"__required__": True},
        "narrator.name": {"minLength": 1},
        "narrator.zh_voice_description": {
            "minLength": 1,
            "description": "中文旁白音色描述，用于设计中文参考音色。",
        },
        "narrator.en_voice_description": {
            "minLength": 1,
            "description": "英文旁白音色描述，用于设计英文参考音色。",
        },
    },
)


def parse_reference_library_proposal(raw_response: str) -> ReferenceLibraryProposal:
    try:
        return parse_proposal(
            raw_response,
            REFERENCE_LIBRARY_OUTPUT_SCHEMA,
            ReferenceLibraryProposal,
            domain="reference_library",
        )
    except ProposalError as exc:
        raise ProposalError("reference_library", exc.code, exc.message) from exc
