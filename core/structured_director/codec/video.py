"""视频计划的严格 recipe 状态编解码。"""

from __future__ import annotations

from typing import Any

from core.model_providers.recipe import RecipeBook

from ..models.video import SegmentVideo, VideoPlan, VideoReferenceImagePlan
from ._shared import _exact_object, _integer, _object_list, _optional_string, _string, _string_list
from .keyframe import _parse_character_reference, serialize_character_references

_SEGMENT_VIDEO_FIELDS = {
    "segment_id",
    "prompt_text",
    "active_recipe",
    "recipes",
    "selected_asset_id",
    "upscaled_asset_id",
}
_VIDEO_PLAN_FIELDS = {"source_script_revision", "segments"}


def _serialize_video_plan(plan: VideoPlan) -> dict[str, Any]:
    return {
        "source_script_revision": plan.source_script_revision,
        "segments": [
            {
                "segment_id": item.segment_id,
                "prompt_text": item.prompt_text,
                "active_recipe": item.active_recipe,
                "recipes": item.recipes.to_json(),
                "selected_asset_id": item.selected_asset_id,
                "upscaled_asset_id": item.upscaled_asset_id,
                **(
                    {
                        "reference_images": [
                            _serialize_reference_image(plan) for plan in item.reference_images
                        ]
                    }
                    if item.reference_images
                    else {}
                ),
            }
            for item in plan.segments
        ],
    }


def _parse_video_plan(value: object) -> VideoPlan:
    fields = _exact_object(value, _VIDEO_PLAN_FIELDS)
    return VideoPlan(
        source_script_revision=_integer(
            fields["source_script_revision"], "video_plan.source_script_revision"
        ),
        segments=_object_list(fields["segments"], _parse_segment_video),
    )


def _parse_segment_video(value: object) -> SegmentVideo:
    fields = _exact_object(
        value,
        _SEGMENT_VIDEO_FIELDS
        | (
            {"reference_images"}
            if isinstance(value, dict) and "reference_images" in value
            else set()
        ),
    )
    return SegmentVideo(
        segment_id=_string(fields["segment_id"], "segment_video.segment_id"),
        prompt_text=_string(fields["prompt_text"], "segment_video.prompt_text"),
        reference_images=_object_list(fields.get("reference_images", []), _parse_reference_image),
        active_recipe=_optional_string(fields["active_recipe"], "segment_video.active_recipe"),
        recipes=RecipeBook.from_json(fields["recipes"]),
        selected_asset_id=_optional_string(
            fields["selected_asset_id"], "segment_video.selected_asset_id"
        ),
        upscaled_asset_id=_optional_string(
            fields["upscaled_asset_id"], "segment_video.upscaled_asset_id"
        ),
    )


def _serialize_reference_image(plan):
    return {
        "id": plan.id,
        "recipe_id": plan.recipe_id,
        "slot_index": plan.slot_index,
        "prompt_text": plan.prompt_text,
        "description": plan.description,
        "visible_character_ids": list(plan.visible_character_ids),
        "character_references": serialize_character_references(plan),
        "reference_asset_ids": list(plan.reference_asset_ids),
    }


def _parse_reference_image(value):
    fields = _exact_object(
        value,
        {
            "id",
            "recipe_id",
            "slot_index",
            "prompt_text",
            "description",
            "visible_character_ids",
            "character_references",
            "reference_asset_ids",
        },
    )
    return VideoReferenceImagePlan(
        _string(fields["id"], "reference_image.id"),
        _string(fields["recipe_id"], "reference_image.recipe_id"),
        _integer(fields["slot_index"], "reference_image.slot_index"),
        _string(fields["prompt_text"], "reference_image.prompt_text"),
        _string(fields["description"], "reference_image.description"),
        _string_list(fields["visible_character_ids"], "reference_image.visible_character_ids"),
        _object_list(fields["character_references"], _parse_character_reference),
        _string_list(fields["reference_asset_ids"], "reference_image.reference_asset_ids"),
    )
