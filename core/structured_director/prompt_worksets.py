"""从项目领域事实与 recipe 声明构造专业输入；不解释插件采样机制。"""

from core.model_providers.image_prompt_skill import image_prompt_guide as image_prompt_guide
from core.model_providers.manifest import Capability, Role, recipe_from_json
from core.model_providers.recipe import SlotBinding, binding_labels, explicit_slots

from .dialogue_timing import actual_dialogue_timing
from .image_prompt_style import image_prompt_style
from .keyframe_requests import (
    _keyframe_generation_inputs,
    _keyframe_prompt_context_json,
    _keyframe_reference_prompt,
)
from .models import StructuredDirectorDocument
from .reads.video_recipes import keyframe_video_context
from .script_index import (
    find_segment,
    scene_segments,
    segment_continues_next,
    segment_continues_previous,
    segment_shots,
    segment_visible_character_ids,
)
from .video_inputs import dialogue_audio_addition, dialogue_audio_inputs, resolve_video_inputs


def video_prompt_workset(
    document: StructuredDirectorDocument,
    segment_id: str,
    *,
    provider_recipes=None,
    provider_catalog=None,
) -> dict[str, object]:
    """视频提示词工作集；recipe 的标签、槽位、参数和软约束均由 Provider 声明。"""
    if (
        document.director_script is None
        or document.video_plan is None
        or document.keyframe_plan is None
    ):
        raise ValueError("视频生产上下文尚未建立。")
    found = find_segment(document.director_script.scenes, segment_id)
    if found is None:
        raise ValueError("Segment 不存在。")
    scene, segment = found
    shots = segment_shots(scene, segment.id)
    visible_character_ids = set(segment_visible_character_ids(scene, segment.id))
    video = next(item for item in document.video_plan.segments if item.segment_id == segment_id)
    view = next(
        (item for item in provider_recipes or [] if item["recipe"]["id"] == video.active_recipe),
        None,
    )
    if view is None:
        raise ValueError("当前视频 recipe 不可用，请先配置 Provider 或选择可用 recipe。")
    recipe = recipe_from_json(view["recipe"])
    actual = resolve_video_inputs(document, segment_id)
    bindings = dict(video.recipe_inputs.bindings)
    for slot in recipe.slots:
        asset_id = (
            actual.start_asset_id
            if slot.role is Role.FIRST_FRAME
            else actual.end_asset_id
            if slot.role is Role.LAST_FRAME
            else None
        )
        if slot.role in {Role.FIRST_FRAME, Role.LAST_FRAME}:
            bindings[slot.key] = () if asset_id is None else (SlotBinding(asset_id),)
    dialogue_inputs = dialogue_audio_inputs(document, segment_id, require_ready=False)
    audio_slot = next((slot for slot in recipe.slots if slot.role is Role.REFERENCE_AUDIO), None)
    if segment.dialogue_lines and audio_slot is None:
        raise ValueError("含对白的 Segment 必须使用支持参考音频的 Ref2VA recipe。")
    labels = binding_labels(recipe, bindings)
    assets = {asset.id: asset for asset in document.assets}
    if any(item["asset_id"] not in assets for item in labels):
        raise ValueError("已选视频输入 Asset 不存在。")
    characters = {item.id: item.name for item in document.reference_library.characters}
    frames = {item.id: item for item in document.keyframe_plan.keyframes}
    boundary = next(
        item for item in document.keyframe_plan.segments if item.segment_id == segment_id
    )

    def frame_description(enabled, frame_id):
        return (
            None
            if not enabled
            else frames[frame_id].prompt_text.strip() or "以已选关键帧图片的可见内容为准。"
        )

    soft = view["hints"].get("soft_duration_limit_seconds")
    result = {
        "workset_version": 7,
        "video_recipe": view,
        "context": {
            "recipe_id": recipe.id,
            "duration_seconds": segment.duration_estimate_seconds,
            "aspect_ratio": document.aspect_ratio.value,
            "scene": {
                "title": scene.title,
                "setting": scene.setting,
                "driver": scene.driver,
            },
            "shots": [
                {
                    "composition": shot.composition,
                    "camera_movement": shot.camera_movement,
                    "action": shot.action,
                    "audio_direction": shot.audio_direction,
                    "visible_character_names": [
                        characters.get(character_id, character_id)
                        for character_id in shot.visible_character_ids
                    ],
                }
                for shot in shots
            ],
            "segment": {
                "action": segment.action,
                "historical_prompt": video.prompt_text,
                "continues_from_previous_segment": segment_continues_previous(scene, segment.id),
                "continues_into_next_segment": segment_continues_next(scene, segment.id),
                "start_frame_description": frame_description(
                    boundary.start_enabled, boundary.start_keyframe_id
                ),
                "end_frame_description": frame_description(
                    boundary.end_enabled, boundary.end_keyframe_id
                ),
                "dialogue": [
                    {
                        "character_name": (
                            item.speaker_label
                            if item.character_id is None
                            else characters.get(item.character_id, item.character_id)
                        ),
                        "text": item.text,
                        "delivery": item.delivery,
                        "dialogue_line_id": item.id,
                        # 引用库外说话者没有可见性登记，是否入画以 Segment action 为准。
                        "on_screen": (
                            None
                            if item.character_id is None
                            else item.character_id in visible_character_ids
                        ),
                    }
                    for item in segment.dialogue_lines
                ],
            },
            "bindings": labels,
            "params": video.recipe_inputs.to_json()["params"],
            "actual_provider_inputs": {
                "inputs": labels,
                "allowed_asset_reference_labels": [
                    item["label"] for item in labels if item["label"] is not None
                ],
            },
        },
        "asset_inputs": [{"label": item["label"], "asset_id": item["asset_id"]} for item in labels],
        # video.update_recipe_inputs 的形状；按槽位合并，只需给出要改的槽位与参数。
        "recipe_inputs": video.recipe_inputs.to_json(),
        "bindable_assets": _bindable_assets(document, scene, recipe),
        "soft_duration_limit_seconds": soft,
        "exceeds_soft_duration_limit": isinstance(soft, int | float)
        and segment.duration_estimate_seconds > soft,
        "dialogue_timing": actual_dialogue_timing(document, segment),
        "dialogue_audio": dialogue_audio_addition(document, segment_id, recipe),
        # Core 提交时自动前置的对白约束，正文不要重复。
        "core_prepended_dialogue_prompt": dialogue_prompt_prefix(labels, dialogue_inputs),
        "video_inputs": [
            keyframe_video_context(document, segment_id, provider_recipes, provider_catalog)
        ],
    }

    return (
        result
        if provider_catalog is None
        else provider_catalog.format_prompt_workset(Capability.VIDEO_GENERATE, recipe.id, result)
    )


def dialogue_prompt_prefix(labels, dialogue_inputs):
    """按实际显式绑定的 Asset 找标签，不假定对白一定排在手工参考前面。"""
    audio_labels = {
        item["asset_id"]: item["label"] for item in labels if item["role"] == "reference_audio"
    }
    bound = [(line, asset) for line, _, asset in dialogue_inputs if asset.id in audio_labels]
    if not bound:
        return None
    instructions = ["严格让角色说出参考音频的原始内容，音频完全相等。"]
    instructions.extend(
        f"{audio_labels[asset.id]} 对应原始对白：{line.text}" for line, asset in bound
    )
    return "\n".join(instructions)


def _bindable_assets(document: StructuredDirectorDocument, scene, recipe) -> list[dict]:
    """当前 recipe 显式槽位可绑定的项目 Asset，按媒体类型与时长匹配槽位。

    只列导入素材、引用库与地点库的已选资源，以及本 Scene 已选的关键帧、旁白、视频与显式参考；
    未被选择的生成候选不列出。Core 校验仍接受任意本项目 Asset。
    """
    slots = explicit_slots(recipe)
    if not slots:
        return []
    library = document.reference_library
    produced = {item.output_asset_id for item in document.generations}
    used: set[str | None] = {asset.id for asset in document.assets if asset.id not in produced}
    for card in library.characters:
        used.add(card.voice_reference_asset_id)
        used.update(card.look_asset_ids)
    if library.narrator is not None:
        used.update(library.narrator.voice_reference_asset_ids)
    for location in document.location_library.locations:
        used.update(image.selected_asset_id for image in location.images)
    segment_ids = {segment.id for segment in scene_segments(scene)}
    dialogue_line_ids = {
        line.id for segment in scene_segments(scene) for line in segment.dialogue_lines
    }
    if document.dialogue_plan is not None:
        used.update(
            item.selected_audio_asset_id
            for item in document.dialogue_plan.items
            if item.dialogue_line_id in dialogue_line_ids
        )
    for cue in scene.narration_cues:
        used.update(cue.selected_audio_asset_ids)
    if document.keyframe_plan is not None:
        used.update(
            item.selected_asset_id
            for item in document.keyframe_plan.keyframes
            if item.owner_segment_id in segment_ids
        )
    if document.video_plan is not None:
        for item in document.video_plan.segments:
            if item.segment_id in segment_ids:
                used.update((item.selected_asset_id, item.upscaled_asset_id))
                used.update(
                    binding.asset_id
                    for _, bindings in item.recipe_inputs.bindings
                    for binding in bindings
                )
    result = []
    for asset in document.assets:
        accepted = [
            slot.key
            for slot in slots
            if asset.media_type in slot.media_types
            and (
                slot.duration_seconds is None
                or asset.duration_seconds is not None
                and slot.duration_seconds[0] <= asset.duration_seconds <= slot.duration_seconds[1]
            )
        ]
        if accepted and asset.id in used:
            result.append(
                {
                    "asset_id": asset.id,
                    "name": asset.display_name,
                    "media_type": asset.media_type,
                    "duration_seconds": asset.duration_seconds,
                    "slots": accepted,
                }
            )
    return result


def keyframe_workset(
    document: StructuredDirectorDocument, segment_id: str, *, provider_catalog=None
) -> list[dict]:
    import json

    plan = document.keyframe_plan
    if plan is None:
        raise ValueError("关键帧计划尚未建立。")
    binding = next((x for x in plan.segments if x.segment_id == segment_id), None)
    if binding is None:
        raise ValueError("Segment关键帧绑定不存在。")
    result = []
    for slot, enabled, frame_id in [
        ("start", binding.start_enabled, binding.start_keyframe_id),
        ("end", binding.end_enabled, binding.end_keyframe_id),
    ]:
        if not enabled:
            continue
        inputs = _keyframe_generation_inputs(document, frame_id)
        if inputs is None:
            raise ValueError("前置Keyframe候选尚未完成，不能提供可执行Prompt输入。")
        style = image_prompt_style(provider_catalog, inputs.operation)
        result.append(
            {
                "workset_version": 1,
                "slot": slot,
                "keyframe_id": frame_id,
                "context": json.loads(_keyframe_prompt_context_json(document, frame_id)),
                "aspect_ratio": document.aspect_ratio.value,
                "operation": inputs.operation.value,
                "reference_mapping": _keyframe_reference_prompt(inputs, style),
                "image_inputs": inputs.describe(style),
            }
        )
    return result
