"""H3 专业工作集的格式适配；编号由 Core 提供。"""

from pathlib import Path

from .prompt_contract import H3DialogueInput, H3PromptContext, H3PromptMode
from .prompt_payload import h3_prompt_payload


def context_from_workset(value):
    ctx = value["context"]
    scene, shot, segment = ctx["scene"], ctx["shot"], ctx["segment"]
    first, last = segment["start_frame_description"], segment["end_frame_description"]
    mode = (
        H3PromptMode.REF2VA
        if ctx["recipe_id"] == "minimax_h3.ref2va"
        else H3PromptMode.FL2VA
        if first is not None and last is not None
        else H3PromptMode.I2VA
        if first is not None
        else H3PromptMode.L2VA
    )

    def descriptions(role):
        return tuple(item["description"] for item in ctx["bindings"] if item["role"] == role)

    context = H3PromptContext(
        mode,
        ctx["duration_seconds"],
        ctx["aspect_ratio"],
        scene["title"],
        scene["setting"],
        shot["composition"],
        shot["camera_movement"],
        shot["action"],
        segment["action"],
        segment["historical_prompt"],
        "",
        shot["audio_direction"],
        first,
        last,
        tuple(H3DialogueInput(**item) for item in segment["dialogue"]),
        descriptions("reference_image"),
        descriptions("reference_audio"),
        descriptions("reference_video"),
        scene["driver"],
    )
    return context


def format_prompt_workset(value):
    ctx = value["context"]
    context = context_from_workset(value)
    payload = h3_prompt_payload(context, ctx["bindings"])
    return {
        **value,
        "context": payload,
        "plugin_skills": [{"name": "h3-prompt-writing", "resources": skill_resources()}],
    }


def skill_resources():
    directory = Path(__file__).parent / "skills/h3-prompt-writing"
    resources = [
        {"name": str(path.relative_to(directory)), "text": path.read_text(encoding="utf-8")}
        for path in [directory / "SKILL.md", *sorted((directory / "references").iterdir())]
        if path.is_file()
    ]
    return resources
