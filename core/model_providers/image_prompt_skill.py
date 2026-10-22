"""项目与 Playground 共用的全局生图 Skill 与插件 Skill 目录；不依赖任何具体图片插件。"""

import hashlib
from pathlib import Path

from .manifest import Capability

IMAGE_PROMPT_SKILL = "storyrail-image-prompt-writing"


def image_prompt_skill() -> dict:
    directory = Path(__file__).parent / "skills" / IMAGE_PROMPT_SKILL
    text = (directory / "SKILL.md").read_text(encoding="utf-8")
    return {
        "name": IMAGE_PROMPT_SKILL,
        "resources": [
            {"name": "SKILL.md", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        ],
    }


def prompt_skill_index(skills: list[dict]) -> list[dict]:
    """工作集只给 Skill 资源目录；全文经专业契约读取，可用 if_hash 缓存。"""
    return [
        {
            "name": skill["name"],
            "resources": [
                {key: resource[key] for key in ("name", "sha256", "bytes")}
                for resource in skill["resources"]
            ],
        }
        for skill in skills
    ]


def image_prompt_guide(provider_catalog, *, skill_text: bool = True) -> dict[str, object]:
    """当前绑定的生图/改图 recipe 的输入图指代约定与随插件发布的 Skill。

    Agent 编写项目或 Playground 图片提示词时据此选择写法；Core 不自动补写参考用途或引用说明。
    同名 Skill 只附带一次；``skill_text=False`` 时插件 Skill 只给目录，全文经专业契约读取。
    """
    recipes: list[dict[str, object]] = []
    skills: dict[str, object] = {}
    for capability in (Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT):
        found = None if provider_catalog is None else provider_catalog.recipe_for(capability)
        if found is None:
            continue
        plugin, recipe = found
        convention = plugin.manifest.image_prompt
        value = provider_catalog.format_prompt_workset(
            capability,
            recipe.id,
            {
                "capability": capability.value,
                "plugin_id": plugin.plugin_id,
                "recipe_id": recipe.id,
                "image_prompt": None if convention is None else convention.to_json(),
                "label_namespaces": dict(recipe.label_namespaces),
            },
        )
        for skill in provider_catalog.prompt_skills(capability):
            skills.setdefault(skill["name"], skill)
        value.pop("global_skills", None)
        recipes.append(value)
    return {
        "recipes": recipes,
        "global_skills": [image_prompt_skill()],
        "plugin_skills": (
            list(skills.values()) if skill_text else prompt_skill_index(list(skills.values()))
        ),
        "default_input_label_template": "<Picture{n}>",
        "reference_prompt_format": (
            "有输入图：逐行写标签与用途，空行后正文逐张明确引用标签；不写文件名。"
            "无输入图：只写画面正文。"
        ),
    }
