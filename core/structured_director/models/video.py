"""视频计划：领域提示词、按 recipe 保存的显式输入与人类选择。"""

from __future__ import annotations

from dataclasses import dataclass

from core.model_providers.recipe import RecipeBook, RecipeInputs

from ._shared import _require_id
from .keyframe import Keyframe, KeyframeCharacterReference


@dataclass(frozen=True, slots=True)
class VideoReferenceImagePlan:
    """当前 recipe 的一个无时间位置图片槽位；选图唯一保存于 recipes.bindings。"""

    id: str
    recipe_id: str
    slot_index: int
    prompt_text: str
    description: str
    visible_character_ids: tuple[str, ...] = ()
    character_references: tuple[KeyframeCharacterReference, ...] = ()
    reference_asset_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _require_id(self.id, "reference_image.id")
        if not isinstance(self.recipe_id, str) or not 0 < len(self.recipe_id) <= 128:
            raise ValueError("参考图片 recipe ID 不合法。")
        if type(self.slot_index) is not int or not 0 <= self.slot_index < 4:
            raise ValueError("参考图片槽位必须在 0–3 之间。")
        if (
            not isinstance(self.description, str)
            or not self.description.strip()
            or len(self.description) > 2000
        ):
            raise ValueError("参考图片说明不能为空或超过 2000 字。")
        Keyframe(
            self.id,
            self.id,
            None,
            self.prompt_text,
            self.visible_character_ids,
            character_references=self.character_references,
        )
        if len(self.reference_asset_ids) > 5 or len(set(self.reference_asset_ids)) != len(
            self.reference_asset_ids
        ):
            raise ValueError("参考图片的生图输入最多 5 张且不得重复。")
        for asset_id in self.reference_asset_ids:
            _require_id(asset_id, "reference_image.reference_asset_ids")


@dataclass(frozen=True, slots=True)
class SegmentVideo:
    segment_id: str
    prompt_text: str
    active_recipe: str | None = None
    recipes: RecipeBook = RecipeBook()
    selected_asset_id: str | None = None
    upscaled_asset_id: str | None = None
    reference_images: tuple[VideoReferenceImagePlan, ...] = ()

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
        positions = [(item.recipe_id, item.slot_index) for item in self.reference_images]
        if len(positions) != len(set(positions)) or len(
            {item.id for item in self.reference_images}
        ) != len(positions):
            raise ValueError("参考图片 ID 与同 recipe 槽位不得重复。")
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
