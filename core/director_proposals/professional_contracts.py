"""固定专业能力清单；只读取随产品发布的契约，不接收文件路径。"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from core.model_providers.image_prompt_skill import image_prompt_skill
from core.model_providers.manifest import Capability

_SKILLS = Path(__file__).resolve().parent / "skills"


def consistency_instruction() -> str:
    """Agent、MCP 与 Web 校对任务共用的一致性说明。"""
    return (_SKILLS / "consistency_instruction.md").read_text(encoding="utf-8").strip()


CONTRACTS = {
    "reference_library": (
        "reference_library",
        "slatehand-reference-library",
        ("card-contract.md", "look-sheets.md"),
    ),
    "script": (
        "structured_director_script",
        "slatehand-structured-director-script",
        (
            "script-contract.md",
            "quality-gate.md",
            "cinematic-director-intent.md",
            "drama-scene-craft.md",
        ),
    ),
    "narration": ("narration_review", "slatehand-narration-review", ("parameter-contract.md",)),
    "keyframe": (
        "keyframe_planner",
        "slatehand-keyframe-planner",
        ("cinematic-keyframe-design.md", "cinematic-frame-prompting.md"),
    ),
    "location": (
        "location_planner",
        "slatehand-location-planner",
        ("location-bible.md", "view-coverage.md"),
    ),
    "video_prompt": (
        "video_prompt_writer",
        "slatehand-video-prompt",
        (),
    ),
    "song_prompt": (
        "song_prompt_writer",
        "slatehand-song-prompt",
        (),
    ),
}

# 只交付契约、没有工作集与 proposal 的专业能力：产出只出现在对话里，不写入项目。
CONTRACT_ONLY = frozenset({"song_prompt"})


# 专业能力 → 随契约附带的生产执行 Skill（资源名带 ``production/`` 前缀）。
PRODUCTION_SKILLS = {"keyframe": ("slatehand-keyframe-sequence",)}


# 专业能力 → 随当前绑定插件发布的提示词 Skill 所属媒体能力。
_PLUGIN_SKILL_CAPABILITIES = {
    "keyframe": (Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT),
    "location": (Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT),
    "video_prompt": (Capability.VIDEO_GENERATE,),
    "song_prompt": (Capability.AUDIO_GENERATE,),
}


def _plugin_skill_resources(capability, provider_catalog):
    if provider_catalog is None:
        return []
    skills = {}
    for media_capability in _PLUGIN_SKILL_CAPABILITIES.get(capability, ()):
        for skill in provider_catalog.prompt_skills(media_capability):
            skills.setdefault(skill["name"], skill)
    return [
        {
            "name": f"plugin/{skill['name']}/{resource['name']}",
            "text": resource["text"],
            "sha256": resource["sha256"],
        }
        for skill in skills.values()
        for resource in skill["resources"]
    ]


def read_contract(capability, *, include: tuple[str, ...] = (), provider_catalog=None):
    """Core 契约正文；给出 Provider 目录时追加当前绑定插件的提示词 Skill（``plugin/`` 前缀）。"""
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
    if capability in {"keyframe", "location"}:
        skill_resource = image_prompt_skill()
        resources.extend(
            {**resource, "name": f"global/{skill_resource['name']}/{resource['name']}"}
            for resource in skill_resource["resources"]
        )
    for production_skill in PRODUCTION_SKILLS.get(capability, ()):
        content = (_SKILLS / production_skill / "SKILL.md").read_text(encoding="utf-8")
        resources.append(
            {
                "name": f"production/{production_skill}/SKILL.md",
                "text": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
    resources.extend(_plugin_skill_resources(capability, provider_catalog))
    if "consistency-review" in include:
        content = (_SKILLS / "slatehand-consistency-review" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        resources.append(
            {
                "name": "shared/slatehand-consistency-review/SKILL.md",
                "text": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
    return {
        "contract_version": 1,
        "capability": capability,
        "skill_name": skill,
        "resources": resources,
        "output_schema_source": (
            None if capability in CONTRACT_ONLY else "project.get_workset.output_schema"
        ),
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
