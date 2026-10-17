"""视频 recipe 的可用性、切换守护和输入编号；Web 只消费这个只读投影。"""

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import SlotBinding, binding_labels, validate_required_slots

from ..video_inputs import binding_for, resolve_video_inputs, segment_context


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
