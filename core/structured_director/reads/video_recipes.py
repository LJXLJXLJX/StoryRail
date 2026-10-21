"""视频 recipe 的可用性、切换守护和输入编号；Web 只消费这个只读投影。"""

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import SlotBinding, binding_labels, validate_required_slots

from ..codec.video import _serialize_reference_image
from ..image_prompt_style import image_prompt_style
from ..models import GenerationOperation
from ..reference_image_requests import reference_image_inputs
from ..video_inputs import binding_for, dialogue_audio_inputs, resolve_video_inputs, segment_context


def video_recipe_state(document, video, catalog, views):
    _scene, _shot, segment, _index = segment_context(document, video.segment_id)
    options = []
    for view in views:
        if view["capability"] != Capability.VIDEO_GENERATE.value:
            continue
        reason = None
        try:
            catalog.validate_recipe_switch(
                Capability.VIDEO_GENERATE, video, view["recipe"]["id"], document.assets
            )
        except (ValueError, RuntimeError) as exc:
            reason = str(exc)
        options.append(
            {
                "id": view["recipe"]["id"],
                "label": view["recipe"]["label"],
                "allowed": reason is None,
                "reason": reason,
            }
        )
    view = next((item for item in views if item["recipe"]["id"] == video.active_recipe), None)
    state = {
        "available": view is not None,
        "ready": False,
        "reason": None if view is not None else "当前视频 recipe 不可用，请选择可用 recipe。",
        "options": options,
        "duration_seconds": segment.duration_estimate_seconds,
        "soft_duration_limit_seconds": None
        if view is None
        else view["hints"].get("soft_duration_limit_seconds"),
        "bindings": [],
        "slot_labels": {},
    }
    if view is None:
        return state
    _plugin, recipe = catalog.recipe_definition(Capability.VIDEO_GENERATE, video.active_recipe)
    bindings = dict(video.recipe_inputs.bindings)
    boundary = binding_for(document, video.segment_id)
    frames = {item.id: item for item in document.keyframe_plan.keyframes}
    for slot in recipe.slots:
        if slot.role not in {Role.FIRST_FRAME, Role.LAST_FRAME}:
            continue
        enabled = boundary.start_enabled if slot.role is Role.FIRST_FRAME else boundary.end_enabled
        frame_id = (
            boundary.start_keyframe_id
            if slot.role is Role.FIRST_FRAME
            else boundary.end_keyframe_id
        )
        asset_id = frames[frame_id].selected_asset_id if enabled else None
        bindings[slot.key] = () if asset_id is None else (SlotBinding(asset_id),)
    try:
        resolve_video_inputs(document, video.segment_id)
        validate_required_slots(recipe, bindings)
        catalog.validate_recipe_inputs(
            Capability.VIDEO_GENERATE, video.active_recipe, video.recipe_inputs, document.assets
        )
        state["ready"] = True
    except (ValueError, RuntimeError) as exc:
        state["reason"] = str(exc)
    state["bindings"] = binding_labels(recipe, bindings)
    # 每个槽位的标签候选仍由 Core 的同一个编号器生成。
    for slot in recipe.slots:
        expanded = dict(bindings)
        expanded[slot.key] = tuple(SlotBinding(f"{index:032x}") for index in range(slot.maximum))
        state["slot_labels"][slot.key] = [
            item["label"] for item in binding_labels(recipe, expanded) if item["slot"] == slot.key
        ]
    return state


def keyframe_video_context(document, segment_id, views=(), catalog=None):
    """规划帧数需要的 recipe 约束与显式参考；不要求边界图已经生成。"""
    video = next(
        (
            item
            for item in (() if document.video_plan is None else document.video_plan.segments)
            if item.segment_id == segment_id
        ),
        None,
    )
    recipe_id = None if video is None else video.active_recipe
    view = next((item for item in views or () if item["recipe"]["id"] == recipe_id), None)
    recipe = None if view is None else view["recipe"]
    if recipe is None and catalog is not None and recipe_id is not None:
        try:
            _, definition = catalog.recipe_definition(Capability.VIDEO_GENERATE, recipe_id)
            recipe = definition.to_json()
        except (ValueError, RuntimeError):
            pass
    result = {
        "segment_id": segment_id,
        "active_recipe": recipe_id,
        "available": recipe is not None,
        "frame_strategies": [],
        "slots": [],
        "require_any": [],
        "reference_inputs": [],
        "reference_image_plans": [],
    }
    if video is not None:
        result["reference_image_plans"] = [
            _serialize_reference_image(image)
            for image in video.reference_images
            if image.recipe_id == recipe_id
        ]
        for plan in result["reference_image_plans"]:
            image = next(item for item in video.reference_images if item.id == plan["id"])
            try:
                inputs = reference_image_inputs(document, video, image)
                plan["image_inputs"] = inputs.describe(
                    image_prompt_style(catalog, GenerationOperation.GENERATE)
                )
                plan["image_inputs_error"] = None
            except ValueError as exc:
                plan["image_inputs"] = []
                plan["image_inputs_error"] = str(exc)
    if recipe is None:
        return result
    slots = recipe["slots"]
    reference_slot = next((slot for slot in slots if slot["role"] == "reference_image"), None)
    reference_bindings = (
        ()
        if reference_slot is None
        else dict(video.recipe_inputs.bindings).get(reference_slot["key"], ())
    )
    for plan in result["reference_image_plans"]:
        index = plan["slot_index"]
        plan["selected_asset_id"] = (
            reference_bindings[index].asset_id if index < len(reference_bindings) else None
        )
        plan["locked"] = plan["selected_asset_id"] is not None or any(
            generation.target_id == plan["id"]
            and generation.phase.value == "succeeded"
            and generation.output_asset_id is not None
            and not generation.dismissed
            for generation in document.generations
        )

    boundaries = {
        item["key"]: item for item in slots if item["role"] in {"first_frame", "last_frame"}
    }
    for strategy, roles in (
        ("none", set()),
        ("start", {"first_frame"}),
        ("end", {"last_frame"}),
        ("both", {"first_frame", "last_frame"}),
    ):
        enabled = {
            key for key, slot in boundaries.items() if slot["role"] in roles and slot["maximum"] > 0
        }
        if any(
            not any(slot["role"] == role and slot["maximum"] > 0 for slot in slots)
            for role in roles
        ):
            continue
        if any(slot["minimum"] > 0 and key not in enabled for key, slot in boundaries.items()):
            continue
        required = set(recipe["require_any"])
        alternatives = {
            item["key"] for item in slots if item["key"] not in boundaries and item["maximum"] > 0
        }
        if required and not required.intersection(enabled | alternatives):
            continue
        result["frame_strategies"].append(strategy)
    result["slots"] = slots
    result["require_any"] = recipe["require_any"]
    assets = {item.id: item for item in document.assets}
    for slot in slots:
        if slot["key"] in boundaries:
            continue
        bindings = dict(video.recipe_inputs.bindings).get(slot["key"], ())
        inputs = [(item.asset_id, item.description, "recipe") for item in bindings]
        if slot["role"] == "reference_audio":
            inputs.extend(
                (asset.id, line.text, "dialogue")
                for line, _, asset in dialogue_audio_inputs(
                    document, segment_id, require_ready=False
                )
            )
        for index, (asset_id, description, source) in enumerate(inputs):
            asset = assets.get(asset_id)
            result["reference_inputs"].append(
                {
                    "slot": slot["key"],
                    "role": slot["role"],
                    "asset_id": asset_id,
                    "description": description,
                    "source": source,
                    "slot_index": index,
                    "name": None if asset is None else asset.display_name,
                    "media_type": None if asset is None else asset.media_type,
                }
            )
    return result
