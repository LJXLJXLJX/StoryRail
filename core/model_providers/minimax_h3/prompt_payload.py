"""H3 专业输入的格式转换；引用标签只由 Core 的 recipe 编号器产生。"""

from core.director_proposals.compiler_intent import context_value
from core.model_providers.recipe import SlotBinding, binding_labels

from .manifest import MANIFEST
from .prompt_contract import H3PromptContext, H3PromptMode


def _context_labels(context):
    recipe = MANIFEST.recipe(
        "minimax_h3.ref2va" if context.mode is H3PromptMode.REF2VA else "minimax_h3.fl2va"
    )
    bindings = {}
    values = {
        "first_frame": ()
        if context.start_frame_description is None
        else (context.start_frame_description,),
        "last_frame": ()
        if context.end_frame_description is None
        else (context.end_frame_description,),
        "additional_images": context.additional_image_descriptions,
        "reference_audios": context.audio_reference_descriptions,
        "reference_videos": context.video_reference_descriptions,
    }
    for slot in recipe.slots:
        bindings[slot.key] = tuple(
            SlotBinding(f"{index:032x}", description)
            for index, description in enumerate(values[slot.key])
        )
    return binding_labels(recipe, bindings)


def h3_prompt_payload(context: H3PromptContext, input_labels=None) -> dict[str, object]:
    labels = _context_labels(context) if input_labels is None else input_labels

    def described(role):
        return [
            {"label": item["label"], "description": item["description"]}
            for item in labels
            if item["role"] == role
        ]

    return {
        "mode": context.mode.value,
        "duration_seconds": context.duration_seconds,
        "aspect_ratio": context.aspect_ratio,
        "scene": {"title": context.scene_title, "setting": context.scene_setting},
        "shot": {
            "composition": context.shot_composition,
            "camera_movement": context.camera_movement,
            "action": context.shot_action,
            "audio_direction": context.audio_direction,
        },
        "segment": {
            "action": context.segment_action,
            "historical_prompt": context.historical_prompt,
            "user_direction": context_value(context.user_direction),
            "start_frame_description": context.start_frame_description,
            "end_frame_description": context.end_frame_description,
            "additional_image_references": described("reference_image"),
            "audio_references": described("reference_audio"),
            "video_references": described("reference_video"),
            "dialogue": [
                {
                    "character_name": item.character_name,
                    "text": item.text,
                    "delivery": item.delivery,
                    "on_screen": item.on_screen,
                }
                for item in context.dialogue
            ],
        },
        "actual_provider_inputs": _actual_provider_inputs(context, labels),
    }


def _actual_provider_inputs(context: H3PromptContext, input_labels=None) -> dict[str, object]:
    labels = _context_labels(context) if input_labels is None else input_labels
    result = {
        "pictures": [],
        "audios": [],
        "videos": [],
        "allowed_asset_reference_labels": [item["label"] for item in labels],
    }
    for item in labels:
        role, index = item["role"], item["index"] + 1
        value = {"label": item["label"]}
        if role in {"first_frame", "last_frame"}:
            value.update(
                provider_input=role,
                role="exact_first_frame" if role == "first_frame" else "exact_last_frame",
                time_seconds=0.0 if role == "first_frame" else context.duration_seconds,
            )
            result["pictures"].append(value)
        elif role == "reference_image":
            value.update(
                provider_input=f"additional_reference_{index}",
                role="described_reference",
                description=item["description"],
                time_seconds=None,
            )
            result["pictures"].append(value)
        else:
            value.update(
                provider_input=f"{role}_{index}",
                role="described_visual_reference"
                if role == "reference_video"
                else "described_reference",
                description=item["description"],
            )
            result["videos" if role == "reference_video" else "audios"].append(value)
    return result
