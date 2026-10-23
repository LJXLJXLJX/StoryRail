from __future__ import annotations

import json
from dataclasses import dataclass, replace

from core.director_proposals.keyframe_codec import normalize_keyframe_prompt_text

from .image_inputs import ImageInput, ImageInputs, ordered_image_inputs
from .image_prompt_style import DEFAULT_IMAGE_PROMPT_STYLE, ImagePromptStyle
from .models import (
    Asset,
    CharacterCard,
    CharacterLook,
    GenerationOperation,
    Keyframe,
    KeyframeCharacterReference,
    KeyframePlan,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from .script_index import find_segment, segment_shots


@dataclass(frozen=True, slots=True)
class KeyframeSubmissionPreview:
    reference_prompt: str
    instruction: str | None
    ready: bool
    operation: GenerationOperation
    input_assets: tuple[Asset, ...]
    # 与 input_assets 同序：每张图的角色名（例如“角色参考”“前置帧”）与用途说明，取自实际输入编译。
    input_roles: tuple[tuple[str, ...], ...] = ()
    input_purposes: tuple[str, ...] = ()


def keyframe_character_look(keyframe: Keyframe, character: CharacterCard) -> CharacterLook | None:
    """本帧该角色使用的造型；None 表示不提交该角色的图。

    显式选择优先（look_id 为 null 表示不提交）；未选择时只有一套造型默认使用它，
    多套造型必须显式选择，避免不同时期、服装的造型图被混用。所选造型必须已选定造型图。
    """
    selection = next(
        (item for item in keyframe.character_references if item.character_id == character.id),
        None,
    )
    if selection is not None:
        look = None if selection.look_id is None else character.look(selection.look_id)
    elif len(character.looks) > 1:
        raise ValueError(
            f"角色「{character.name}」有 {len(character.looks)} 套造型，"
            "请为该 Keyframe 显式选择本帧使用的造型（可以选择不提交）。"
        )
    else:
        look = character.looks[0] if character.looks else None
    if look is not None and look.selected_asset_id is None:
        raise ValueError(f"角色「{character.name}」的造型「{look.name}」尚未选定造型图。")
    return look


def _find_keyframe(document: StructuredDirectorDocument, keyframe_id: str):
    plan = document.keyframe_plan
    if plan is None:
        raise ValueError("Segment Keyframe 计划尚未建立。")
    keyframe = next((item for item in plan.keyframes if item.id == keyframe_id), None)
    if keyframe is None:
        raise ValueError("Keyframe 不存在。")
    return keyframe


def _keyframe_label(document: StructuredDirectorDocument, keyframe_id: str | None) -> str:
    if keyframe_id is None or document.director_script is None or document.keyframe_plan is None:
        return "未知 Keyframe"
    labels: list[str] = []
    binding_by_segment = {item.segment_id: item for item in document.keyframe_plan.segments}
    for scene_index, scene in enumerate(document.director_script.scenes, start=1):
        for segment_index, segment in enumerate(scene.segments, start=1):
            binding = binding_by_segment[segment.id]
            for side, enabled, candidate_id in (
                ("首帧", binding.start_enabled, binding.start_keyframe_id),
                ("尾帧", binding.end_enabled, binding.end_keyframe_id),
            ):
                if enabled and candidate_id == keyframe_id:
                    labels.append(f"Scene {scene_index} Segment {segment_index} {side}")
    if not labels:
        return f"Keyframe {keyframe_id[:8]}"
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]}（同时是 {labels[1]}）"


def _active_keyframe_ids(plan: KeyframePlan | None) -> set[str]:
    if plan is None:
        return set()
    return {
        keyframe_id
        for item in plan.segments
        for keyframe_id in (
            item.start_keyframe_id if item.start_enabled else None,
            item.end_keyframe_id if item.end_enabled else None,
        )
        if keyframe_id is not None
    }


def _keyframe_batch_ids(document: StructuredDirectorDocument) -> tuple[str, ...] | None:
    """Recover the latest explicitly bound batch, never infer it from dialogue."""
    for run in reversed(document.director_runs):
        scopes = run.authorization.generation_scopes
        if scopes and all(
            item.startswith("keyframe:")
            and len(item) == 41
            and all(char in "0123456789abcdef" for char in item[9:])
            for item in scopes
        ):
            return tuple(item[9:] for item in scopes)
    return None


def _keyframe_existing_result(document: StructuredDirectorDocument, keyframe_id: str) -> str | None:
    keyframe = _find_keyframe(document, keyframe_id)
    if keyframe.selected_asset_id is not None:
        return "已有已选图片"
    if any(
        item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
        and item.target_id == keyframe_id
        and not item.dismissed
        and item.phase is ReferenceGenerationPhase.SUCCEEDED
        and item.output_asset_id is not None
        for item in document.generations
    ):
        return "已有成功候选"
    return None


def _resolve_keyframe_generation_targets(
    document: StructuredDirectorDocument, target_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Expand an explicit Scene/Segment scope to active slots, once."""
    script, plan = document.director_script, document.keyframe_plan
    if script is None or plan is None or not target_ids:
        raise ValueError("生成 Keyframe 必须指定已建立计划的目标。")
    active = _active_keyframe_ids(plan)
    bindings = {item.segment_id: item for item in plan.segments}
    scopes: dict[str, tuple[str, ...]] = {}
    for scene in script.scenes:
        scene_frames: list[str] = []
        for segment in scene.segments:
            binding = bindings[segment.id]
            frames = tuple(
                frame_id
                for enabled, frame_id in (
                    (binding.start_enabled, binding.start_keyframe_id),
                    (binding.end_enabled, binding.end_keyframe_id),
                )
                if enabled
            )
            scopes[segment.id] = frames
            scene_frames.extend(frames)
        scopes[scene.id] = tuple(scene_frames)
    resolved: list[str] = []
    for target_id in target_ids:
        if target_id in active:
            resolved.append(target_id)
        elif target_id in scopes:
            if not scopes[target_id]:
                raise ValueError("目标范围尚无已启用 Keyframe，请先规划或启用关键帧。")
            resolved.extend(scopes[target_id])
        else:
            raise ValueError("Keyframe 生成目标不存在或未激活，Core 未提交任何图片任务。")
    return tuple(dict.fromkeys(resolved))


def unselected_reference_keyframes(
    document: StructuredDirectorDocument, keyframe: Keyframe
) -> tuple[str, ...]:
    """本帧参考、但当前没有选中图的 Keyframe；它们被采用候选之前本帧不能生成。"""
    plan = document.keyframe_plan
    by_id = {} if plan is None else {item.id: item for item in plan.keyframes}
    return tuple(
        reference_id
        for reference_id in keyframe.reference_keyframe_ids
        if reference_id in by_id and by_id[reference_id].selected_asset_id is None
    )


def _keyframe_generation_inputs(
    document: StructuredDirectorDocument, keyframe_id: str
) -> ImageInputs | None:
    """Return an optional edit source followed by ordered visual references.

    None means the temporal predecessor is not ready yet.  The ordering is part of
    StoryRail's adapter contract and is persisted in Generation.input_asset_ids.
    超过输入上限时按名额优先级列出会被挤掉的输入并拒绝，不静默丢弃。
    """
    plan = document.keyframe_plan
    script = document.director_script
    if plan is None or script is None:
        raise ValueError("关键帧生成缺少导演脚本。")
    keyframe = _find_keyframe(document, keyframe_id)
    if keyframe_id not in _active_keyframe_ids(plan):
        raise ValueError("该 Keyframe 未激活，不能用于生成。")
    binding = next(
        (item for item in plan.segments if item.segment_id == keyframe.owner_segment_id),
        None,
    )
    if binding is None:
        raise ValueError("Keyframe owner Segment 没有输入绑定。")
    if find_segment(script.scenes, keyframe.owner_segment_id) is None:
        raise ValueError("Keyframe owner Segment 不在当前脚本中。")
    # 名额优先级：可见角色参考 → 前置帧 → 参考关键帧 → 本次显式辅助图。
    source_asset_id: str | None = None
    predecessor_input: ImageInput | None = None
    if keyframe.predecessor_keyframe_id is not None and binding.start_enabled:
        predecessor = _find_keyframe(document, keyframe.predecessor_keyframe_id)
        predecessor_asset = predecessor.selected_asset_id
        if predecessor_asset is None:
            predecessor_asset = next(
                (
                    item.output_asset_id
                    for item in reversed(document.generations)
                    if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                    and item.target_id == predecessor.id
                    and item.phase is ReferenceGenerationPhase.SUCCEEDED
                    and not item.dismissed
                    and item.output_asset_id is not None
                ),
                None,
            )
        if predecessor_asset is None:
            return None
        predecessor_input = ImageInput(
            predecessor_asset,
            "前置帧",
            "前一时间边界 Keyframe 的图片。",
        )
        if source_asset_id is None:
            source_asset_id = predecessor_asset
    unselected = unselected_reference_keyframes(document, keyframe)
    if unselected:
        raise ValueError(
            f"参考关键帧 {_keyframe_label(document, unselected[0])} 还没有选中图片，"
            "请先采用它的候选。"
        )
    frames_by_id = {item.id: item for item in plan.keyframes}
    reference_inputs = [
        ImageInput(
            frames_by_id[reference_id].selected_asset_id,
            "参考关键帧",
            f"{_keyframe_label(document, reference_id)}的当前选中图。",
        )
        for reference_id in keyframe.reference_keyframe_ids
        if reference_id in frames_by_id
    ]
    character_by_id = {item.id: item for item in document.reference_library.characters}
    character_inputs: list[ImageInput] = []
    for character_id in keyframe.visible_character_ids:
        character = character_by_id.get(character_id)
        if character is None:
            raise ValueError("Keyframe 引用了不存在的可见角色卡。")
        look = keyframe_character_look(keyframe, character)
        if look is not None:
            assert look.selected_asset_id is not None
            character_inputs.append(
                ImageInput(
                    look.selected_asset_id,
                    f"角色「{character.name}」造型「{look.name}」",
                    f"角色「{character.name}」造型「{look.name}」的已选图。",
                )
            )
    related_bindings = (
        item
        for item in plan.segments
        if keyframe_id in {item.start_keyframe_id, item.end_keyframe_id}
    )
    described_assets = {
        image.selected_asset_id: (location.name, image.name, image.description)
        for location in document.location_library.locations
        for image in location.images
        if image.selected_asset_id is not None
    }
    auxiliary_inputs = [
        ImageInput(
            asset_id,
            "地点参考" if asset_id in described_assets else "辅助参考",
            (
                f"地点「{described_assets[asset_id][0]}」的图片"
                f"「{described_assets[asset_id][1]}」：{described_assets[asset_id][2]}"
                if asset_id in described_assets
                else "用户为本 Segment 显式选择的图片。"
            ),
        )
        for related in related_bindings
        for asset_id in related.reference_asset_ids
    ]
    return ordered_image_inputs(
        document,
        [
            *character_inputs,
            *([predecessor_input] if predecessor_input is not None else []),
            *reference_inputs,
            *auxiliary_inputs,
        ],
        operation=(
            GenerationOperation.EDIT
            if source_asset_id is not None
            else GenerationOperation.GENERATE
        ),
        label=f"{_keyframe_label(document, keyframe_id)}的角色参考、前置帧、参考关键帧与显式参考图",
        source_asset_id=source_asset_id,
    )


def _keyframe_preview_document(
    document: StructuredDirectorDocument,
    *,
    keyframe_id: str,
    segment_id: str,
    prompt_text: str,
    visible_character_ids: tuple[str, ...],
    character_references: tuple[KeyframeCharacterReference, ...],
    reference_asset_ids: tuple[str, ...],
) -> StructuredDirectorDocument:
    plan = document.keyframe_plan
    if plan is None:
        raise ValueError("关键帧计划尚未建立。")
    if len(reference_asset_ids) != len(set(reference_asset_ids)) or len(reference_asset_ids) > 4:
        raise ValueError("关键帧辅助参考不能重复且最多 4 张。")
    assets = {item.id: item for item in document.assets}
    if any(
        asset_id not in assets or not assets[asset_id].media_type.startswith("image/")
        for asset_id in reference_asset_ids
    ):
        raise ValueError("关键帧辅助参考必须选择项目图片 Asset。")
    card_looks = {
        card.id: {look.id for look in card.looks} for card in document.reference_library.characters
    }
    if any(
        item.character_id not in card_looks
        or (item.look_id is not None and item.look_id not in card_looks[item.character_id])
        for item in character_references
    ):
        raise ValueError("Keyframe 角色造型必须选自该角色当前的造型。")
    binding = next((item for item in plan.segments if item.segment_id == segment_id), None)
    if binding is None or keyframe_id not in {
        binding.start_keyframe_id,
        binding.end_keyframe_id,
    }:
        raise ValueError("Keyframe 不属于指定 Segment。")
    keyframes = tuple(
        replace(
            item,
            prompt_text=prompt_text.strip(),
            visible_character_ids=visible_character_ids,
            character_references=character_references,
        )
        if item.id == keyframe_id
        else item
        for item in plan.keyframes
    )
    bindings = tuple(
        replace(item, reference_asset_ids=reference_asset_ids)
        if item.segment_id == segment_id
        else item
        for item in plan.segments
    )
    return replace(document, keyframe_plan=replace(plan, keyframes=keyframes, segments=bindings))


def _keyframe_reference_prompt(
    inputs: ImageInputs, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE
) -> str:
    lines = inputs.lines(style)
    return "实际图片输入：\n" + "\n".join(lines) if lines else "本次未选择引用图片。"


def _keyframe_effective_prompt(
    document: StructuredDirectorDocument,
    keyframe: Keyframe,
    inputs: ImageInputs,
    style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE,
) -> str:
    prompt_text = normalize_keyframe_prompt_text(keyframe.prompt_text)
    prompt_text = inputs.validate_prompt(prompt_text, style)
    # 画幅由插件画布保证时不写画幅句，避免提示词与画布形成两个来源。
    aspect = style.aspect_ratio_in_prompt
    return (
        prompt_text
        + "\n\n"
        + (f"项目固定画幅：{document.aspect_ratio.value}。" if aspect else "")
        + "关键帧硬约束：只生成一张单一静态画面，不得生成分镜拼图、文字或水印；"
        "准确表现这一时刻的可见状态。"
        + ("输出必须保持项目画幅比例与横竖方向，不得在连续关键帧之间改变画幅。" if aspect else "")
    )


def _keyframe_prompt_context_json(document: StructuredDirectorDocument, keyframe_id: str) -> str:
    script = document.director_script
    keyframe = _find_keyframe(document, keyframe_id)
    if script is None:
        raise ValueError("关键帧提示词缺少导演脚本。")
    found = find_segment(script.scenes, keyframe.owner_segment_id)
    if found is None:
        raise ValueError("Segment 不存在。")
    scene, segment = found
    return json.dumps(
        {
            "scene": {
                "id": scene.id,
                "title": scene.title,
                "summary": scene.summary,
                "setting": scene.setting,
            },
            "shots": [
                {
                    "id": shot.id,
                    "composition": shot.composition,
                    "camera_movement": shot.camera_movement,
                    "action": shot.action,
                }
                for shot in segment_shots(scene, segment.id)
            ],
            "segment": {
                "id": segment.id,
                "shot_ids": list(segment.shot_ids),
                "action": segment.action,
                "dialogue_lines": [line.text for line in segment.dialogue_lines],
            },
            "keyframe": {
                "id": keyframe.id,
                "prompt_text": keyframe.prompt_text,
            },
        },
        ensure_ascii=False,
        indent=2,
    )
