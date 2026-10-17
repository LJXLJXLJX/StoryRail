"""视频计划：领域提示词、按 recipe 保存的显式输入与人类选择。"""

from __future__ import annotations

from dataclasses import dataclass

from core.model_providers.recipe import RecipeBook, RecipeInputs

from ._shared import _require_id


@dataclass(frozen=True, slots=True)
class SegmentVideo:
    segment_id: str
    prompt_text: str
    active_recipe: str | None = None
    recipes: RecipeBook = RecipeBook()
    selected_asset_id: str | None = None
    upscaled_asset_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.segment_id, "segment_video.segment_id")
        if not isinstance(self.prompt_text, str) or len(self.prompt_text) > 20_000:
            raise ValueError("segment_video.prompt_text 必须是至多 20000 字符的字符串。")
        if self.active_recipe is not None and (
            not isinstance(self.active_recipe, str) or not 0 < len(self.active_recipe) <= 128
        ):
            raise ValueError("segment_video.active_recipe 不合法。")
        if not isinstance(self.recipes, RecipeBook):
            raise ValueError("segment_video.recipes 不合法。")
        if self.selected_asset_id is not None:
            _require_id(self.selected_asset_id, "segment_video.selected_asset_id")
        if self.upscaled_asset_id is not None:
            _require_id(self.upscaled_asset_id, "segment_video.upscaled_asset_id")
            if self.selected_asset_id is None:
                raise ValueError("超分视频必须关联已选原视频。")

    @property
    def recipe_inputs(self) -> RecipeInputs:
        return self.recipes.get(self.active_recipe)


@dataclass(frozen=True, slots=True)
class VideoPlan:
    source_script_revision: int
    segments: tuple[SegmentVideo, ...]

    def __post_init__(self) -> None:
        if isinstance(self.source_script_revision, bool) or self.source_script_revision < 1:
            raise ValueError("video_plan.source_script_revision 不合法。")
        ids = [item.segment_id for item in self.segments]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("视频计划必须完整包含不重复的 Segment。")
