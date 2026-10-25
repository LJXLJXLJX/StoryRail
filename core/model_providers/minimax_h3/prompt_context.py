"""H3 专业工作集的格式适配；编号由 Core 提供。"""

from pathlib import Path

from .prompt_contract import H3DialogueInput, H3PromptContext, H3PromptMode, H3ShotInput
from .prompt_payload import h3_prompt_payload


def context_from_workset(value):
    ctx = value["context"]
    scene, segment = ctx["scene"], ctx["segment"]
    shots = tuple(
        H3ShotInput(
            composition=item["composition"],
            camera_movement=item["camera_movement"],
            action=item["action"],
            audio_direction=item["audio_direction"],
            visible_character_names=tuple(item["visible_character_names"]),
        )
        for item in ctx["shots"]
    )
    first, last = segment["start_frame_description"], segment["end_frame_description"]
    mode = (
        H3PromptMode.REF2VA
        if ctx["recipe_id"] == "minimax_h3.ref2va"
        else H3PromptMode.FL2VA
        if first is not None and last is not None
        else H3PromptMode.I2VA
        if first is not None
        else H3PromptMode.L2VA
        if last is not None
        else H3PromptMode.T2VA
    )

    def descriptions(role):
        return tuple(item["description"] for item in ctx["bindings"] if item["role"] == role)

    context = H3PromptContext(
        mode=mode,
        duration_seconds=ctx["duration_seconds"],
        aspect_ratio=ctx["aspect_ratio"],
        scene_title=scene["title"],
        scene_setting=scene["setting"],
        shots=shots,
        segment_action=segment["action"],
        historical_prompt=segment["historical_prompt"],
        user_direction="",
        start_frame_description=first,
        end_frame_description=last,
        dialogue=tuple(
            H3DialogueInput(
                character_name=item["character_name"],
                text=item["text"],
                delivery=item["delivery"],
                on_screen=item["on_screen"],
            )
            for item in segment["dialogue"]
        ),
        continues_from_previous_segment=segment["continues_from_previous_segment"],
        continues_into_next_segment=segment["continues_into_next_segment"],
        additional_image_descriptions=descriptions("reference_image"),
        audio_reference_descriptions=descriptions("reference_audio"),
        video_reference_descriptions=descriptions("reference_video"),
        scene_driver=scene["driver"],
    )
    return context


def format_prompt_workset(value):
    ctx = value["context"]
    context = context_from_workset(value)
    payload = h3_prompt_payload(context, ctx["bindings"])
    return {**value, "context": payload}


def prompt_skills():
    return [{"name": "h3-prompt-writing", "resources": skill_resources()}]


def skill_resources():
    directory = Path(__file__).parent / "skills/h3-prompt-writing"
    resources = [
        {"name": str(path.relative_to(directory)), "text": path.read_text(encoding="utf-8")}
        for path in [directory / "SKILL.md", *sorted((directory / "references").iterdir())]
        if path.is_file()
    ]
    return resources
