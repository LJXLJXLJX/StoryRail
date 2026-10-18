from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from core.director_commands import (
    BindKeyframeSlot,
    ClearKeyframeSelection,
    CommandNeedsUserInput,
    KeyframeOperation,
    SetKeyframeActivation,
    SetKeyframeAuxReferences,
    ShareKeyframeBoundary,
    SplitKeyframeBoundary,
    UpdateKeyframeFields,
)

from .models import (
    Keyframe,
    KeyframeCharacterReference,
    KeyframePlan,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    SegmentKeyframes,
    StructuredDirectorDocument,
)
from .script_index import (
    scene_segments,
    segment_continues_previous,
    segment_visible_character_ids,
    shot_segments,
)


def _validate_planned_shared_boundaries(
    plan: KeyframePlan,
    boundaries: tuple[tuple[str, str], ...],
) -> None:
    """Check the merged result, not merely the presence of a Share operation."""
    bindings = {item.segment_id: item for item in plan.segments}
    for left_id, right_id in boundaries:
        left, right = bindings.get(left_id), bindings.get(right_id)
        if (
            left is None
            or right is None
            or not left.end_enabled
            or not right.start_enabled
            or left.end_keyframe_id != right.start_keyframe_id
        ):
            raise ValueError("Keyframe Planner 最终计划未落实必须共享且启用的连续边界。")


def _segments_using_keyframes(plan: KeyframePlan, keyframe_ids: set[str]) -> set[str]:
    if not keyframe_ids:
        return set()
    return {
        item.segment_id
        for item in plan.segments
        if item.start_keyframe_id in keyframe_ids or item.end_keyframe_id in keyframe_ids
    }


@dataclass(frozen=True, slots=True)
class _KeyframeMutation:
    document: StructuredDirectorDocument
    changed_ids: frozenset[str]
    invalidated: frozenset[str]
    preserved: frozenset[str]
    decision_summary: str | None
    applied_summary: dict[str, int]


_KeyframeMutationOperation = KeyframeOperation


def _apply_keyframe_operations(
    document: StructuredDirectorDocument,
    operations: tuple[_KeyframeMutationOperation, ...],
) -> _KeyframeMutation:
    plan = document.keyframe_plan
    script = document.director_script
    if plan is None or script is None:
        raise ValueError("关键帧计划尚未建立。")
    keyframes = {item.id: item for item in plan.keyframes}
    keyframe_order = [item.id for item in plan.keyframes]
    bindings = {item.segment_id: item for item in plan.segments}
    binding_order = [item.segment_id for item in plan.segments]
    segment_context = {
        segment.id: (scene, shot, index, segment)
        for scene in script.scenes
        for shot in scene.shots
        for index, segment in enumerate(shot_segments(scene, shot.id))
    }
    timeline = [(scene, segment.id) for scene in script.scenes for segment in scene_segments(scene)]
    timeline_index = {segment_id: index for index, (_, segment_id) in enumerate(timeline)}
    original_bindings = dict(bindings)
    changed_ids: set[str] = set()
    generation_sensitive_keyframes: set[str] = set()
    directly_affected_segments: set[str] = set()
    preserved: set[str] = set()
    shared_boundaries = 0
    split_boundaries = 0
    decision_parts: list[str] = []

    def require_segment(segment_id: str) -> SegmentKeyframes:
        binding = bindings.get(segment_id)
        if binding is None or segment_id not in segment_context:
            raise ValueError(f"Segment {segment_id} 的关键帧绑定不存在。")
        return binding

    def require_keyframe(keyframe_id: str) -> Keyframe:
        keyframe = keyframes.get(keyframe_id)
        if keyframe is None:
            raise ValueError(f"Keyframe {keyframe_id} 不存在。")
        return keyframe

    def adjacency(left_id: str, right_id: str) -> str:
        require_segment(left_id)
        require_segment(right_id)
        left_index = timeline_index[left_id]
        right_index = timeline_index[right_id]
        if right_index != left_index + 1:
            raise ValueError("共享或拆分边界要求两个 Segment 在项目时间线上相邻。")
        right_scene = timeline[right_index][0]
        return "intra_shot" if segment_continues_previous(right_scene, right_id) else "cross_shot"

    def remove_orphans() -> None:
        referenced = {
            keyframe_id
            for binding in bindings.values()
            for keyframe_id in (binding.start_keyframe_id, binding.end_keyframe_id)
        }
        for keyframe_id in tuple(keyframes):
            if keyframe_id not in referenced:
                orphan = keyframes[keyframe_id]
                if orphan.selected_asset_id is not None:
                    preserved.add(f"asset:{orphan.selected_asset_id}")
                preserved.update(
                    f"generation:{item.id}"
                    for item in document.generations
                    if item.target_id == keyframe_id
                )
                del keyframes[keyframe_id]
                changed_ids.add(keyframe_id)

    def successful_outputs(keyframe_id: str) -> tuple[str, ...]:
        return tuple(
            item.output_asset_id
            for item in document.generations
            if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
            and item.target_id == keyframe_id
            and item.phase is ReferenceGenerationPhase.SUCCEEDED
            and item.output_asset_id is not None
            and not item.dismissed
        )

    def resolve_boundary_source(
        operation: ShareKeyframeBoundary,
        left: SegmentKeyframes,
        right: SegmentKeyframes,
    ) -> str:
        candidates = (left.end_keyframe_id, right.start_keyframe_id)
        if operation.source_keyframe_id is not None:
            if operation.source_keyframe_id not in candidates:
                raise ValueError("source_keyframe_id 必须属于待共享边界的两侧之一。")
            return operation.source_keyframe_id
        if candidates[0] == candidates[1]:
            return candidates[0]
        left_frame, right_frame = (require_keyframe(item) for item in candidates)
        left_asset = left_frame.selected_asset_id
        right_asset = right_frame.selected_asset_id
        if left_asset is not None and right_asset is not None and left_asset != right_asset:
            raise CommandNeedsUserInput(
                "共享边界两侧各有不同的已选图片，请明确指定保留哪一侧。",
                impact={
                    "left_segment_id": operation.left_segment_id,
                    "right_segment_id": operation.right_segment_id,
                    "left_keyframe_id": candidates[0],
                    "right_keyframe_id": candidates[1],
                    "left_asset_id": left_asset,
                    "right_asset_id": right_asset,
                },
            )
        if left_asset is not None or right_asset is not None:
            return candidates[0] if left_asset is not None else candidates[1]
        left_outputs = successful_outputs(candidates[0])
        right_outputs = successful_outputs(candidates[1])
        if bool(left_outputs) != bool(right_outputs):
            return candidates[0] if left_outputs else candidates[1]
        if left_outputs and right_outputs and set(left_outputs) != set(right_outputs):
            raise CommandNeedsUserInput(
                "共享边界两侧都有不同的成功候选，请明确指定保留哪一侧。",
                impact={
                    "left_segment_id": operation.left_segment_id,
                    "right_segment_id": operation.right_segment_id,
                    "left_keyframe_id": candidates[0],
                    "right_keyframe_id": candidates[1],
                    "left_candidate_asset_ids": left_outputs,
                    "right_candidate_asset_ids": right_outputs,
                },
            )
        return candidates[0]

    for operation in operations:
        if isinstance(operation, SetKeyframeActivation):
            binding = require_segment(operation.segment_id)
            replacement = replace(
                binding,
                start_enabled=operation.start_enabled,
                end_enabled=operation.end_enabled,
            )
            if replacement != binding:
                bindings[operation.segment_id] = replacement
                changed_ids.add(operation.segment_id)
                directly_affected_segments.add(operation.segment_id)
            continue

        if isinstance(operation, UpdateKeyframeFields):
            keyframe = require_keyframe(operation.keyframe_id)
            prompt_text = (
                keyframe.prompt_text
                if operation.prompt_text is None
                else operation.prompt_text.strip()
            )
            visible_character_ids = (
                keyframe.visible_character_ids
                if operation.visible_character_ids is None
                else operation.visible_character_ids
            )
            character_references = (
                tuple(
                    item
                    for item in keyframe.character_references
                    if item.character_id in visible_character_ids
                )
                if operation.character_references is None
                else tuple(
                    KeyframeCharacterReference(item.character_id, item.look_id)
                    for item in operation.character_references
                )
            )
            generation_changed = (
                prompt_text != keyframe.prompt_text
                or character_references != keyframe.character_references
            )
            replacement = replace(
                keyframe,
                prompt_text=prompt_text,
                visible_character_ids=visible_character_ids,
                character_references=character_references,
                selected_asset_id=None if generation_changed else keyframe.selected_asset_id,
            )
            if replacement != keyframe:
                keyframes[keyframe.id] = replacement
                changed_ids.add(keyframe.id)
                if generation_changed:
                    generation_sensitive_keyframes.add(keyframe.id)
            continue

        if isinstance(operation, SetKeyframeAuxReferences):
            binding = require_segment(operation.segment_id)
            if len(operation.asset_ids) > 4:
                raise ValueError("单个 Segment 最多添加 4 张辅助参考图。")
            assets = {item.id: item for item in document.assets}
            if any(
                asset_id not in assets or not assets[asset_id].media_type.startswith("image/")
                for asset_id in operation.asset_ids
            ):
                raise ValueError("Segment 辅助参考必须选择项目图片 Asset。")
            replacement = replace(binding, reference_asset_ids=operation.asset_ids)
            if replacement != binding:
                bindings[operation.segment_id] = replacement
                changed_ids.add(operation.segment_id)
                generation_sensitive_keyframes.update(
                    (binding.start_keyframe_id, binding.end_keyframe_id)
                )
            continue

        if isinstance(operation, BindKeyframeSlot):
            binding = require_segment(operation.segment_id)
            source = require_keyframe(operation.keyframe_id)
            if operation.slot == "start":
                if source.id == binding.end_keyframe_id:
                    raise ValueError("Segment 首尾关键帧不能相同。")
                for other in bindings.values():
                    if (
                        other.segment_id != operation.segment_id
                        and other.end_keyframe_id == source.id
                    ):
                        adjacency(other.segment_id, operation.segment_id)
                bindings[operation.segment_id] = replace(binding, start_keyframe_id=source.id)
                end = require_keyframe(binding.end_keyframe_id)
                replacement_end = replace(end, predecessor_keyframe_id=source.id)
                keyframes[end.id] = replacement_end
                if replacement_end != end:
                    generation_sensitive_keyframes.add(end.id)
                    changed_ids.add(end.id)
            else:
                if source.id == binding.start_keyframe_id:
                    raise ValueError("Segment 首尾关键帧不能相同。")
                for other in bindings.values():
                    if (
                        other.segment_id != operation.segment_id
                        and other.start_keyframe_id == source.id
                    ):
                        adjacency(operation.segment_id, other.segment_id)
                keyframes[source.id] = replace(
                    source,
                    owner_segment_id=operation.segment_id,
                    predecessor_keyframe_id=binding.start_keyframe_id,
                )
                bindings[operation.segment_id] = replace(binding, end_keyframe_id=source.id)
            changed_ids.update((operation.segment_id, source.id))
            directly_affected_segments.add(operation.segment_id)
            remove_orphans()
            continue

        if isinstance(operation, ShareKeyframeBoundary):
            actual_adjacency = adjacency(operation.left_segment_id, operation.right_segment_id)
            if (
                operation.expected_adjacency is not None
                and operation.expected_adjacency != actual_adjacency
            ):
                raise ValueError("共享边界的实际邻接类型与 expected_adjacency 不一致。")
            left = require_segment(operation.left_segment_id)
            right = require_segment(operation.right_segment_id)
            source_id = resolve_boundary_source(operation, left, right)
            source = require_keyframe(source_id)
            already_shared = left.end_keyframe_id == right.start_keyframe_id == source_id
            source = replace(
                source,
                owner_segment_id=operation.left_segment_id,
                predecessor_keyframe_id=left.start_keyframe_id,
            )
            keyframes[source_id] = source
            right_end = require_keyframe(right.end_keyframe_id)
            replacement_right_end = replace(right_end, predecessor_keyframe_id=source_id)
            keyframes[right_end.id] = replacement_right_end
            if replacement_right_end != right_end:
                generation_sensitive_keyframes.add(right_end.id)
                changed_ids.add(right_end.id)
            bindings[operation.left_segment_id] = replace(
                left, end_keyframe_id=source_id, end_enabled=True
            )
            bindings[operation.right_segment_id] = replace(
                right, start_keyframe_id=source_id, start_enabled=True
            )
            if (
                not already_shared
                or bindings[operation.left_segment_id] != left
                or bindings[operation.right_segment_id] != right
            ):
                shared_boundaries += 1
                changed_ids.update(
                    (operation.left_segment_id, operation.right_segment_id, source_id)
                )
                directly_affected_segments.update(
                    (operation.left_segment_id, operation.right_segment_id)
                )
                decision_parts.append(
                    f"{operation.left_segment_id} 尾帧与 {operation.right_segment_id} 首帧"
                    f"已共享 Keyframe {source_id}。"
                )
            if source.selected_asset_id is not None:
                preserved.add(f"asset:{source.selected_asset_id}")
            preserved.add(f"keyframe:{source_id}")
            preserved.update(
                f"generation:{item.id}"
                for item in document.generations
                if item.target_id == source_id
            )
            remove_orphans()
            continue

        if isinstance(operation, SplitKeyframeBoundary):
            adjacency(operation.left_segment_id, operation.right_segment_id)
            left = require_segment(operation.left_segment_id)
            right = require_segment(operation.right_segment_id)
            if left.end_keyframe_id != right.start_keyframe_id:
                continue
            shared = require_keyframe(left.end_keyframe_id)
            clone_id = uuid4().hex
            if operation.clone_side == "left_end":
                # 原共享 Keyframe 留给右段首帧，左段尾帧得到独立副本。
                clone = replace(
                    shared,
                    id=clone_id,
                    owner_segment_id=operation.left_segment_id,
                    predecessor_keyframe_id=left.start_keyframe_id,
                    selected_asset_id=(
                        shared.selected_asset_id if operation.copy_selection else None
                    ),
                )
                keyframes[clone_id] = clone
                keyframe_order.append(clone_id)
                keyframes[shared.id] = replace(
                    shared,
                    owner_segment_id=operation.right_segment_id,
                    predecessor_keyframe_id=None,
                )
                bindings[operation.left_segment_id] = replace(left, end_keyframe_id=clone_id)
                directly_affected_segments.add(operation.left_segment_id)
                directly_affected_segments.add(operation.right_segment_id)
            else:
                clone = replace(
                    shared,
                    id=clone_id,
                    owner_segment_id=operation.right_segment_id,
                    predecessor_keyframe_id=None,
                    selected_asset_id=(
                        shared.selected_asset_id if operation.copy_selection else None
                    ),
                )
                keyframes[clone_id] = clone
                keyframe_order.append(clone_id)
                bindings[operation.right_segment_id] = replace(right, start_keyframe_id=clone_id)
                right_end = require_keyframe(right.end_keyframe_id)
                keyframes[right_end.id] = replace(right_end, predecessor_keyframe_id=clone_id)
                generation_sensitive_keyframes.add(right_end.id)
                changed_ids.add(right_end.id)
                directly_affected_segments.add(operation.right_segment_id)
            changed_ids.update((operation.left_segment_id, operation.right_segment_id, clone_id))
            split_boundaries += 1
            continue

        if isinstance(operation, ClearKeyframeSelection):
            keyframe = require_keyframe(operation.keyframe_id)
            if keyframe.selected_asset_id is not None:
                keyframes[keyframe.id] = replace(keyframe, selected_asset_id=None)
                changed_ids.add(keyframe.id)
                generation_sensitive_keyframes.add(keyframe.id)
            continue

        raise TypeError("未支持的 Keyframe operation。")

    for keyframe_id in generation_sensitive_keyframes:
        keyframe = keyframes.get(keyframe_id)
        if keyframe is not None and keyframe.selected_asset_id is not None:
            keyframes[keyframe_id] = replace(keyframe, selected_asset_id=None)
    remove_orphans()
    final_plan = KeyframePlan(
        source_script_revision=plan.source_script_revision,
        keyframes=tuple(keyframes[item] for item in keyframe_order if item in keyframes),
        segments=tuple(bindings[item] for item in binding_order),
    )
    _validate_keyframe_operation_context(document, final_plan)

    affected_segments = set(directly_affected_segments)
    affected_segments.update(_segments_using_keyframes(plan, generation_sensitive_keyframes))
    affected_segments.update(
        segment_id
        for segment_id in binding_order
        if original_bindings[segment_id] != bindings[segment_id]
    )
    invalidated: set[str] = set()
    video_plan = document.video_plan
    if video_plan is not None and affected_segments:
        updated_videos = []
        for item in video_plan.segments:
            if item.segment_id in affected_segments and (
                item.selected_asset_id is not None or item.upscaled_asset_id is not None
            ):
                if item.selected_asset_id is not None:
                    invalidated.add(f"segment_video_selection:{item.segment_id}")
                if item.upscaled_asset_id is not None:
                    invalidated.add(f"video_upscale_selection:{item.segment_id}")
                item = replace(item, selected_asset_id=None, upscaled_asset_id=None)
            updated_videos.append(item)
        video_plan = replace(video_plan, segments=tuple(updated_videos))
    final_assembly = document.final_assembly
    if affected_segments and final_assembly is not None:
        invalidated.add("final_assembly")
        final_assembly = None

    changed = (
        final_plan != plan
        or video_plan != document.video_plan
        or final_assembly != document.final_assembly
    )
    updated = (
        document
        if not changed
        else replace(
            document,
            revision=document.revision + 1,
            keyframe_plan=final_plan,
            video_plan=video_plan,
            final_assembly=final_assembly,
        )
    )
    activated_start = sum(
        bindings[item].start_enabled and not original_bindings[item].start_enabled
        for item in binding_order
    )
    activated_end = sum(
        bindings[item].end_enabled and not original_bindings[item].end_enabled
        for item in binding_order
    )
    if not decision_parts and not changed:
        decision_parts.append("目标 Keyframe 绑定已处于请求状态，没有重复写入。")
    return _KeyframeMutation(
        document=updated,
        changed_ids=frozenset(changed_ids if changed else ()),
        invalidated=frozenset(invalidated),
        preserved=frozenset(preserved),
        decision_summary=" ".join(decision_parts) or None,
        applied_summary={
            "activated_start": activated_start,
            "activated_end": activated_end,
            "shared_boundaries": shared_boundaries,
            "split_boundaries": split_boundaries,
        },
    )


def _validate_keyframe_operation_context(
    document: StructuredDirectorDocument, plan: KeyframePlan
) -> None:
    script = document.director_script
    assert script is not None
    bindings = {item.segment_id: item for item in plan.segments}
    characters_by_segment = {
        segment.id: (scene.id, segment_visible_character_ids(scene, segment.id))
        for scene in script.scenes
        for segment in scene_segments(scene)
    }
    slots_by_keyframe: dict[str, list[tuple[str, str]]] = {}
    for binding in bindings.values():
        slots_by_keyframe.setdefault(binding.start_keyframe_id, []).append(
            (binding.segment_id, "start")
        )
        slots_by_keyframe.setdefault(binding.end_keyframe_id, []).append(
            (binding.segment_id, "end")
        )
    known_characters = {item.id for item in document.reference_library.characters}
    for keyframe in plan.keyframes:
        if not set(keyframe.visible_character_ids) <= known_characters:
            raise ValueError("Keyframe 引用了不存在的角色卡。")
        slots = slots_by_keyframe[keyframe.id]
        allowed_characters: set[str] = set()
        scene_ids: set[str] = set()
        for segment_id, _slot in slots:
            scene_id, visible_character_ids = characters_by_segment[segment_id]
            scene_ids.add(scene_id)
            allowed_characters.update(visible_character_ids)
        if not set(keyframe.visible_character_ids) <= allowed_characters:
            raise ValueError("Keyframe 可见角色必须属于使用该边界的相邻 Segment 角色并集。")
