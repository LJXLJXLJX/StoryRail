"""固定专业能力清单；只读取随产品发布的契约，不接收文件路径。"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent / "skills"


def consistency_instruction() -> str:
    """Agent、MCP 与 Web 校对任务共用的一致性说明。"""
    return (_SKILLS / "consistency_instruction.md").read_text(encoding="utf-8").strip()


CONTRACTS = {
    "reference_library": (
        "reference_library",
        "storyrail-reference-library",
        ("card-contract.md", "look-sheets.md"),
    ),
    "script": (
        "structured_director_script",
        "storyrail-structured-director-script",
        (
            "script-contract.md",
            "quality-gate.md",
            "cinematic-director-intent.md",
            "drama-scene-craft.md",
        ),
    ),
    "narration": ("narration_review", "storyrail-narration-review", ("parameter-contract.md",)),
    "keyframe": (
        "keyframe_planner",
        "storyrail-keyframe-planner",
        ("cinematic-keyframe-design.md", "cinematic-frame-prompting.md"),
    ),
    "location": (
        "location_planner",
        "storyrail-location-planner",
        ("location-bible.md", "view-coverage.md"),
    ),
    "video_prompt": (
        "video_prompt_writer",
        "storyrail-video-prompt",
        (),
    ),
}


def read_contract(capability, *, include: tuple[str, ...] = ()):
    if not isinstance(capability, str) or capability not in CONTRACTS:
        raise ValueError("未知专业能力。")
    if any(item != "consistency-review" for item in include):
        raise ValueError("include 只接受 consistency-review。")
    role, skill, references = CONTRACTS[capability]
    directory = _SKILLS / skill
    resources = []
    for name in ("SKILL.md", *("references/" + item for item in references)):
        content = (directory / name).read_text(encoding="utf-8")
        resources.append(
            {"name": name, "text": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}
        )
    if "consistency-review" in include:
        content = (_SKILLS / "storyrail-consistency-review" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        resources.append(
            {
                "name": "shared/storyrail-consistency-review/SKILL.md",
                "text": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
    return {
        "contract_version": 1,
        "capability": capability,
        "skill_name": skill,
        "resources": resources,
        "output_schema_source": "project.get_workset.output_schema",
    }


def contract_hash(capability: str) -> str:
    """返回契约正文的稳定内容 hash；不绑定 project revision。"""
    return hashlib.sha256(
        json.dumps(
            read_contract(capability),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=1)
def contract_hashes() -> dict[str, str]:
    return {capability: contract_hash(capability) for capability in CONTRACTS}
