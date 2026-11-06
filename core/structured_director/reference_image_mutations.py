"""Segment 无时间位置参考图片的规划与显式选图；视频绑定只有 recipes 一个来源。"""

from dataclasses import replace
from uuid import uuid4

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import SlotBinding

from .models import (
    KeyframeCharacterReference,
    ReferenceGenerationPhase,
    unresolved_uncertain_ids,
)
from .models.video import VideoReferenceImagePlan
from .video_mutations import _reject_active_segment_video_generation, _require_video_command_target


def reference_image_slot(catalog, video):
    if catalog is None:
        raise ValueError("请先配置视频 Provider。")
    _, recipe = catalog.recipe_definition(Capability.VIDEO_GENERATE, video.active_recipe)
    slot = next((item for item in recipe.slots if item.role is Role.REFERENCE_IMAGE), None)
    if slot is None:
        raise ValueError("当前视频 recipe 不支持其他图片。")
    return slot


def save_reference_image_plan(document, update, slot, *, planning=False):
    plan, _, _, video = _require_video_command_target(
        document, update.scope_scene_ids, update.segment_id
    )
    if update.slot_index >= min(slot.maximum, 4):
        raise ValueError("参考图片超过当前 recipe 输入上限。")
    _reject_active_segment_video_generation(document, video.segment_id)
    current = next(
        (
            item
            for item in video.reference_images
            if item.recipe_id == video.active_recipe and item.slot_index == update.slot_index
        ),
        None,
    )
    if current is not None:
        unresolved = unresolved_uncertain_ids(document.generations)
        if any(
            item.target_id == current.id
            and (
                item.phase
                in {
                    ReferenceGenerationPhase.SUBMITTING,
                    ReferenceGenerationPhase.QUEUED,
                    ReferenceGenerationPhase.RUNNING,
                }
                or item.id in unresolved
            )
            for item in document.generations
        ):
            raise ValueError("该参考图片有进行中或提交不确定的 Generation。")
        if planning and (
            update.slot_index < len(dict(video.recipe_inputs.bindings).get(slot.key, ()))
            or any(
                item.target_id == current.id
                and item.output_asset_id is not None
                and item.phase is ReferenceGenerationPhase.SUCCEEDED
                and not item.dismissed
                for item in document.generations
            )
        ):
            return document
    image = VideoReferenceImagePlan(
        current.id if current else uuid4().hex,
        video.active_recipe,
        update.slot_index,
        update.prompt_text,
        update.description,
        update.visible_character_ids,
        tuple(
            KeyframeCharacterReference(item.character_id, item.look_id)
            for item in update.character_references
        ),
        update.reference_asset_ids,
    )
    assets = {item.id: item for item in document.assets}
    if any(
        value not in assets or not assets[value].media_type.startswith("image/")
        for value in image.reference_asset_ids
    ):
        raise ValueError("参考图片的生图输入必须是项目图片。")
    characters = {item.id: item for item in document.reference_library.characters}
    if not set(image.visible_character_ids) <= characters.keys():
        raise ValueError("参考图片包含未知角色。")
    for choice in image.character_references:
        if choice.look_id is not None and not any(
            look.id == choice.look_id for look in characters[choice.character_id].looks
        ):
            raise ValueError("参考图片造型不属于所选角色。")
    images = tuple(
        item for item in video.reference_images if current is None or item.id != current.id
    ) + (image,)
    replacement = replace(video, reference_images=images)
    return replace(
        document,
        video_plan=replace(
            plan,
            segments=tuple(
                replacement if item.segment_id == video.segment_id else item
                for item in plan.segments
            ),
        ),
    )


def _resolve_selected_asset_id(document, update):
    """把候选 Generation 或 Keyframe 已选图解析为 Asset ID；asset_id 来源原样返回。"""
    if update.generation_id is not None:
        generation = next(
            (item for item in document.generations if item.id == update.generation_id), None
        )
        if generation is None:
            raise ValueError("Generation 不存在。")
        if (
            generation.phase is not ReferenceGenerationPhase.SUCCEEDED
            or generation.dismissed
            or generation.output_asset_id is None
        ):
            raise ValueError("只能选用成功、未隐藏且有产物的 Generation。")
        return generation.output_asset_id
    if update.keyframe_id is not None:
        keyframes = () if document.keyframe_plan is None else document.keyframe_plan.keyframes
        keyframe = next((item for item in keyframes if item.id == update.keyframe_id), None)
        if keyframe is None:
            raise ValueError("Keyframe 不存在。")
        if keyframe.selected_asset_id is None:
            raise ValueError("该 Keyframe 尚未选定图片。")
        return keyframe.selected_asset_id
    return update.asset_id


def select_reference_image(document, update, slot):
    plan, _, _, video = _require_video_command_target(
        document, update.scope_scene_ids, update.segment_id
    )
    _reject_active_segment_video_generation(document, video.segment_id)
    update = replace(update, asset_id=_resolve_selected_asset_id(document, update))
    if update.slot_index >= min(slot.maximum, 4):
        raise ValueError("参考图片超过当前 recipe 上限。")
    bindings = dict(video.recipe_inputs.bindings)
    items = list(bindings.get(slot.key, ()))
    index = min(update.slot_index, len(items))
    images = list(video.reference_images)
    if update.asset_id is None:
        if update.slot_index >= len(items):
            return document
        items.pop(update.slot_index)
        # 移除后槽位与图片计划一起左移，被移除卡片的计划移到空白区。
        images = [
            replace(
                image,
                slot_index=(
                    len(items)
                    if image.slot_index == update.slot_index
                    else image.slot_index - 1
                    if update.slot_index < image.slot_index <= len(items)
                    else image.slot_index
                ),
            )
            if image.recipe_id == video.active_recipe
            else image
            for image in images
        ]
    else:
        asset = next((item for item in document.assets if item.id == update.asset_id), None)
        if asset is None or asset.media_type not in slot.media_types:
            raise ValueError("参考图片必须是当前项目受支持的图片 Asset。")
        # 未写说明时沿用该槽位已绑定说明，其次是该卡片图片规划的参考用途。
        description = (
            update.description.strip()
            or (
                (items[update.slot_index].description or "")
                if update.slot_index < len(items)
                else ""
            )
            or next(
                (
                    image.description
                    for image in images
                    if image.recipe_id == video.active_recipe
                    and image.slot_index == update.slot_index
                ),
                "",
            ).strip()
        )
        if not description:
            raise ValueError("请填写该图片实际内容与参考用途的说明。")
        boundary = next(
            item for item in document.keyframe_plan.segments if item.segment_id == video.segment_id
        )
        enabled_ids = {
            frame_id
            for enabled, frame_id in (
                (boundary.start_enabled, boundary.start_keyframe_id),
                (boundary.end_enabled, boundary.end_keyframe_id),
            )
            if enabled
        }
        if any(
            frame.id in enabled_ids and frame.selected_asset_id == update.asset_id
            for frame in document.keyframe_plan.keyframes
        ):
            raise ValueError("其他图片不能重复当前已启用的首尾帧。")
        binding = SlotBinding(update.asset_id, description)
        if update.slot_index < len(items):
            items[index] = binding
        else:
            items.append(binding)
            # 空槽不占 Provider 名额；先选后面的卡片时，把该计划移到实际提交位置。
            images = [
                replace(
                    image,
                    slot_index=(
                        index
                        if image.slot_index == update.slot_index
                        else update.slot_index
                        if image.slot_index == index
                        else image.slot_index
                    ),
                )
                if image.recipe_id == video.active_recipe
                else image
                for image in images
            ]
    bindings[slot.key] = tuple(items)
    inputs = replace(video.recipe_inputs, bindings=tuple(sorted(bindings.items())))
    replacement = replace(
        video,
        recipes=video.recipes.with_entry(video.active_recipe, inputs),
        reference_images=tuple(images),
        selected_asset_id=None,
        upscaled_asset_id=None,
    )
    return replace(
        document,
        video_plan=replace(
            plan,
            segments=tuple(
                replacement if item.segment_id == video.segment_id else item
                for item in plan.segments
            ),
        ),
        final_assembly=None,
    )
