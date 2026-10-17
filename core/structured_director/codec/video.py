"""视频计划的严格 recipe 状态编解码。"""

from __future__ import annotations

from typing import Any

from core.model_providers.recipe import RecipeBook

from ..models.video import SegmentVideo, VideoPlan
from ._shared import _exact_object, _integer, _object_list, _optional_string, _string

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
    fields = _exact_object(value, _SEGMENT_VIDEO_FIELDS)
    return SegmentVideo(
        segment_id=_string(fields["segment_id"], "segment_video.segment_id"),
        prompt_text=_string(fields["prompt_text"], "segment_video.prompt_text"),
        active_recipe=_optional_string(fields["active_recipe"], "segment_video.active_recipe"),
        recipes=RecipeBook.from_json(fields["recipes"]),
        selected_asset_id=_optional_string(
            fields["selected_asset_id"], "segment_video.selected_asset_id"
        ),
        upscaled_asset_id=_optional_string(
            fields["upscaled_asset_id"], "segment_video.upscaled_asset_id"
        ),
    )
