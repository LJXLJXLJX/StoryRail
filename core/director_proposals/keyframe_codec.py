from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, replace

from core.director_commands import (
    KeyframeCharacterReferenceSelection,
    KeyframeOperation,
    SetKeyframeActivation,
    ShareKeyframeBoundary,
    SplitKeyframeBoundary,
    UpdateKeyframeFields,
)
from core.director_proposals.keyframe import (
    KeyframeCharacterReferenceProposal,
    KeyframePlanProposal,
    KeyframeSceneInput,
    KeyframeSegmentProposal,
)
from core.director_proposals.schema_gen import ProposalError, generate_schema, parse_proposal

_CHARACTER_REFERENCES_SCHEMA = {
    "__required__": True,
    "items": {
        "type": "object",
        "properties": {
            "character_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "look_id": {
                "anyOf": [{"type": "string", "pattern": "^[0-9a-f]{32}$"}, {"type": "null"}]
            },
        },
        "required": ["character_id", "look_id"],
        "additionalProperties": False,
    },
}
_KEYFRAME_OVERRIDES = {
    "segments[].segment_id": {"pattern": "^[0-9a-f]{32}$"},
    "segments[].frame_strategy": {"enum": ["none", "start", "end", "both"]},
    # 承接上一 Segment 时首帧必须为空；非承接时由 dataclass 校验非空。
    "segments[].start_prompt_text": {"maxLength": 18_000},
    "segments[].start_visible_character_ids": {
        "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"}
    },
    "segments[].start_character_references": _CHARACTER_REFERENCES_SCHEMA,
    "segments[].end_prompt_text": {"maxLength": 18_000},
    "segments[].end_visible_character_ids": {
        "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"}
    },
    "segments[].end_character_references": _CHARACTER_REFERENCES_SCHEMA,
    "segments[].reference_images": {"maxItems": 4},
    "segments[].reference_images[].slot_index": {"minimum": 0, "maximum": 3},
    "segments[].reference_images[].prompt_text": {"minLength": 1, "maxLength": 18000},
    "segments[].reference_images[].description": {"minLength": 1, "maxLength": 2000},
    "segments[].reference_images[].character_references": _CHARACTER_REFERENCES_SCHEMA,
    "segments[].continues_from_previous": {"__required__": True},
}
_STATIC_OUTPUT_SCHEMA = generate_schema(KeyframePlanProposal, _KEYFRAME_OVERRIDES)


_ASPECT_PREFIX = re.compile(
    r"^\s*(?:9\s*:\s*16|16\s*:\s*9)\s*(?:竖幅|横幅|竖屏|横屏)?\s*[，,。；;：:]?\s*",
    re.IGNORECASE,
)


def parse_keyframe_plan(raw_response: str) -> KeyframePlanProposal:
    try:
        proposal = parse_proposal(
            raw_response,
            _STATIC_OUTPUT_SCHEMA,
            KeyframePlanProposal,
            domain="keyframe",
        )
        return replace(
            proposal,
            segments=tuple(
                replace(
                    segment,
                    start_prompt_text=(
                        normalize_keyframe_prompt_text(segment.start_prompt_text)
                        if segment.start_prompt_text.strip()
                        else ""
                    ),
                    end_prompt_text=(
                        normalize_keyframe_prompt_text(segment.end_prompt_text)
                        if segment.end_prompt_text.strip()
                        else ""
                    ),
                )
                for segment in proposal.segments
            ),
        )
    except ProposalError as exc:
        raise ProposalError("keyframe", exc.code, exc.message) from exc
    except ValueError as exc:
        raise ProposalError("keyframe", "invalid_value", str(exc)) from exc


def normalize_keyframe_prompt_text(value: str) -> str:
    normalized = _ASPECT_PREFIX.sub("", value.strip()).strip()
    if not normalized:
        raise ValueError("关键帧画面正文不能只包含画幅标签。")
    return normalized


@dataclass(frozen=True, slots=True)
class KeyframePlanSlot:
    """编译 proposal 所需的当前 Keyframe 槽位事实（与输入/文档解耦）。"""

    segment_id: str
    start_keyframe_id: str
    end_keyframe_id: str
    planning_enabled: bool
    locked: bool
    continues_previous_shot: bool = False


def _scene_slots(
    scenes: tuple[KeyframeSceneInput, ...],
) -> tuple[tuple[KeyframePlanSlot, ...], ...]:
    return tuple(
        tuple(
            KeyframePlanSlot(
                segment.id,
                segment.start_keyframe_id,
                segment.end_keyframe_id,
                segment.planning_enabled,
                segment.start_locked or segment.end_locked,
                segment.continues_from_previous,
            )
            for segment in scene.segments
        )
        for scene in scenes
    )


def compile_plan_operations(
    proposal: KeyframePlanProposal,
    scene_slots: tuple[tuple[KeyframePlanSlot, ...], ...],
) -> tuple[KeyframeOperation, ...] | None:
    """把 Segment 计划编译为槽位、激活与边界操作；缺少槽位上下文时返回 None。"""
    all_slots = [slot for scene in scene_slots for slot in scene]
    if any(slot.start_keyframe_id is None or slot.end_keyframe_id is None for slot in all_slots):
        return None
    proposal_by_segment = {item.segment_id: item for item in proposal.segments}
    operations: list[KeyframeOperation] = []
    for scene in scene_slots:
        for index, slot in enumerate(scene):
            if not slot.planning_enabled:
                continue
            planned = proposal_by_segment[slot.segment_id]
            previous = scene[index - 1] if index > 0 else None
            if previous is not None:
                currently_shared = previous.end_keyframe_id == slot.start_keyframe_id
                boundary_mutable = (
                    previous.planning_enabled and not previous.locked and not slot.locked
                )
                if planned.continues_from_previous:
                    if not currently_shared:
                        if not boundary_mutable:
                            raise ProposalError(
                                "keyframe",
                                "invalid_proposal",
                                "与上下文 Segment 新建共享边界会越出授权；"
                                f"请至少扩大到相邻 Segment：{previous.segment_id}。",
                            )
                        operations.append(
                            ShareKeyframeBoundary(
                                left_segment_id=previous.segment_id,
                                right_segment_id=slot.segment_id,
                                source_keyframe_id=previous.end_keyframe_id,
                                expected_adjacency=(
                                    "intra_shot" if slot.continues_previous_shot else "cross_shot"
                                ),
                            )
                        )
                elif currently_shared:
                    if not boundary_mutable:
                        raise ProposalError(
                            "keyframe",
                            "invalid_proposal",
                            "解除与上下文 Segment 的共享边界会越出授权；"
                            f"请至少扩大到相邻 Segment：{previous.segment_id}。",
                        )
                    # 原共享 Keyframe 留给后段作为独立首帧：先把左段复制为新尾帧，
                    # 再把原 ID 改写成右段首帧。
                    operations.append(
                        SplitKeyframeBoundary(
                            left_segment_id=previous.segment_id,
                            right_segment_id=slot.segment_id,
                            clone_side="left_end",
                            copy_selection=False,
                        )
                    )
            if slot.locked:
                continue
            if not planned.continues_from_previous and planned.frame_strategy in {"start", "both"}:
                operations.append(
                    UpdateKeyframeFields(
                        keyframe_id=slot.start_keyframe_id,
                        prompt_text=planned.start_prompt_text,
                        visible_character_ids=planned.start_visible_character_ids,
                        character_references=_selections(planned.start_character_references),
                    )
                )
            if planned.frame_strategy in {"end", "both"}:
                operations.append(
                    UpdateKeyframeFields(
                        keyframe_id=slot.end_keyframe_id,
                        prompt_text=planned.end_prompt_text,
                        visible_character_ids=planned.end_visible_character_ids,
                        character_references=_selections(planned.end_character_references),
                    )
                )
            operations.append(
                SetKeyframeActivation(
                    segment_id=slot.segment_id,
                    start_enabled=planned.frame_strategy in {"start", "both"},
                    end_enabled=planned.frame_strategy in {"end", "both"},
                )
            )
    return tuple(operations)


def _selections(
    references: tuple[KeyframeCharacterReferenceProposal, ...],
) -> tuple[KeyframeCharacterReferenceSelection, ...]:
    return tuple(
        KeyframeCharacterReferenceSelection(item.character_id, item.look_id) for item in references
    )


def _validate_scope(
    proposal: KeyframePlanProposal,
    scenes: tuple[KeyframeSceneInput, ...],
) -> None:
    expected_segments = [
        segment for scene in scenes for segment in scene.segments if segment.planning_enabled
    ]
    if [item.segment_id for item in proposal.segments] != [item.id for item in expected_segments]:
        raise ProposalError(
            "keyframe", "invalid_proposal", "Agent 必须按生产基线顺序仅返回授权 Segment。"
        )
    proposal_by_id = {item.segment_id: item for item in proposal.segments}
    for scene in scenes:
        planned_ids = {
            segment.id
            for segment in scene.segments
            if segment.planning_enabled and segment.id in proposal_by_id
        }
        looks = {
            item.id: {look.look_id for look in item.looks}
            for segment in scene.segments
            for item in segment.visible_characters
        }
        for index, segment in enumerate(scene.segments):
            if segment.id not in planned_ids:
                continue
            actual = proposal_by_id[segment.id]
            previous = scene.segments[index - 1] if index > 0 else None
            if actual.continues_from_previous:
                if previous is None:
                    raise ProposalError(
                        "keyframe",
                        "invalid_proposal",
                        "每个 Scene 的第一个 Segment 不能承接上一 Segment。",
                    )
                if (
                    previous.id not in planned_ids
                    and previous.end_keyframe_id != segment.start_keyframe_id
                ):
                    raise ProposalError(
                        "keyframe",
                        "invalid_proposal",
                        "与上下文 Segment 新建共享边界会越出授权；"
                        f"请至少扩大到相邻 Segment：{previous.id}。",
                    )
            allowed = {item.id for item in segment.visible_characters}
            if (
                not actual.continues_from_previous
                and not set(actual.start_visible_character_ids) <= allowed
            ):
                raise ProposalError(
                    "keyframe",
                    "invalid_proposal",
                    "Agent 返回了不属于该 Segment 的可见角色 ID。",
                )
            next_segment = scene.segments[index + 1] if index + 1 < len(scene.segments) else None
            next_planned = None if next_segment is None else proposal_by_id.get(next_segment.id)
            boundary_allowed = set(allowed)
            if next_segment is not None and (
                (next_planned is not None and next_planned.continues_from_previous)
                or (
                    next_planned is None
                    and next_segment.start_keyframe_id == segment.end_keyframe_id
                )
            ):
                boundary_allowed.update(item.id for item in next_segment.visible_characters)
            if not set(actual.end_visible_character_ids) <= boundary_allowed:
                raise ProposalError(
                    "keyframe",
                    "invalid_proposal",
                    "Agent 返回了不属于相邻 Segment 角色并集的可见角色 ID。",
                )
            for reference in (
                *actual.start_character_references,
                *actual.end_character_references,
            ):
                if reference.look_id is not None and reference.look_id not in looks.get(
                    reference.character_id, set()
                ):
                    raise ProposalError(
                        "keyframe",
                        "invalid_proposal",
                        "角色造型选择必须来自工作集中该角色的 looks。",
                    )


def _enforce_required_shared_boundaries(
    proposal: KeyframePlanProposal,
    scene: KeyframeSceneInput,
    required_shared_boundaries: tuple[tuple[str, str], ...],
) -> KeyframePlanProposal:
    if not required_shared_boundaries:
        return proposal
    proposal_by_id = {item.segment_id: item for item in proposal.segments}
    segments = list(proposal.segments)
    index_by_id = {item.segment_id: index for index, item in enumerate(segments)}
    order = [segment.id for segment in scene.segments]
    for left_segment_id, right_segment_id in required_shared_boundaries:
        adjacent = any(
            order[index] == left_segment_id and order[index + 1] == right_segment_id
            for index in range(len(order) - 1)
        )
        if not adjacent:
            raise ProposalError(
                "keyframe",
                "invalid_proposal",
                "Core 指定的共享边界不是当前 Scene 的相邻 Segment。",
            )
        left = proposal_by_id.get(left_segment_id)
        right = proposal_by_id.get(right_segment_id)
        if left is None or right is None:
            missing = left_segment_id if left is None else right_segment_id
            raise ProposalError(
                "keyframe",
                "invalid_proposal",
                f"Core 指定的共享边界越出授权；请至少扩大到相邻 Segment：{missing}。",
            )
        if left.frame_strategy == "none" or right.frame_strategy == "none":
            raise ProposalError(
                "keyframe",
                "invalid_proposal",
                "共享边界必须启用前段尾帧和后段首帧，不能选择 none。",
            )
        if left.frame_strategy == "start":
            left = replace(left, frame_strategy="both")
        if right.frame_strategy == "end":
            right = replace(right, frame_strategy="both")
        right = replace(
            right,
            continues_from_previous=True,
            start_prompt_text="",
            start_visible_character_ids=(),
            start_character_references=(),
        )
        segments[index_by_id[left_segment_id]] = left
        segments[index_by_id[right_segment_id]] = right
        proposal_by_id[left_segment_id] = left
        proposal_by_id[right_segment_id] = right
    return replace(proposal, segments=tuple(segments))


def _output_schema(scenes: tuple[KeyframeSceneInput, ...], video_inputs=()) -> dict[str, object]:
    segments = [
        segment for scene in scenes for segment in scene.segments if segment.planning_enabled
    ]
    schema = deepcopy(_STATIC_OUTPUT_SCHEMA)
    by_id = {item["segment_id"]: item for item in video_inputs}
    segments_schema = schema["properties"]["segments"]
    segments_schema.update(
        minItems=len(segments),
        maxItems=len(segments),
        prefixItems=[
            _segment_schema(scene, index, by_id.get(segment.id))
            for scene in scenes
            for index, segment in enumerate(scene.segments)
            if segment.planning_enabled
        ],
        items=False,
    )
    return schema


def _segment_schema(scene: KeyframeSceneInput, index: int, video_input=None) -> dict[str, object]:
    segment = scene.segments[index]
    character_ids = [item.id for item in segment.visible_characters]
    boundary_character_ids = list(character_ids)
    next_segment = scene.segments[index + 1] if index + 1 < len(scene.segments) else None
    if next_segment is not None and (
        next_segment.continues_from_previous
        or next_segment.start_keyframe_id == segment.end_keyframe_id
    ):
        boundary_character_ids.extend(
            item.id
            for item in next_segment.visible_characters
            if item.id not in boundary_character_ids
        )
    segment_schema = deepcopy(_STATIC_OUTPUT_SCHEMA["properties"]["segments"]["items"])
    properties = segment_schema["properties"]
    properties["segment_id"] = {"type": "string", "const": segment.id}
    if video_input is not None and video_input["available"]:
        properties["frame_strategy"] = {"type": "string", "enum": video_input["frame_strategies"]}
    if index == 0:
        properties["continues_from_previous"] = {"type": "boolean", "const": False}
        properties["start_prompt_text"] = {
            "type": "string",
            "maxLength": 18_000,
        }
    else:
        properties["start_prompt_text"] = {
            "type": "string",
            "maxLength": 18_000,
        }
    properties["start_visible_character_ids"] = _id_array_schema(character_ids)
    properties["end_visible_character_ids"] = _id_array_schema(boundary_character_ids)
    _restrict_reference_characters(properties["start_character_references"], character_ids)
    _restrict_reference_characters(properties["end_character_references"], boundary_character_ids)
    return segment_schema


def _restrict_reference_characters(schema: dict, ids: list[str]) -> None:
    if not ids:
        schema["maxItems"] = 0
        return
    schema["items"]["properties"]["character_id"] = {"type": "string", "enum": ids}


def _id_array_schema(ids: list[str]) -> dict[str, object]:
    if not ids:
        return {
            "type": "array",
            "maxItems": 0,
            "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        }
    return {
        "type": "array",
        "items": {"type": "string", "enum": ids},
    }


def compile_keyframe_proposal(proposal, scenes, required_shared_boundaries=()):
    """校验并编译专业计划；模型执行不在此边界内。"""
    _validate_scope(proposal, scenes)
    proposal_by_id = {item.segment_id: item for item in proposal.segments}
    normalized: list[KeyframeSegmentProposal] = []
    for scene in scenes:
        planned_ids = {segment.id for segment in scene.segments if segment.planning_enabled}
        partial = replace(
            proposal,
            segments=tuple(item for item in proposal.segments if item.segment_id in planned_ids),
        )
        declared = tuple(
            (left.id, right.id)
            for left, right in zip(scene.segments, scene.segments[1:], strict=False)
            if left.id in planned_ids
            and right.id in planned_ids
            and proposal_by_id[right.id].continues_from_previous
        )
        required = tuple(
            boundary
            for boundary in required_shared_boundaries
            if boundary[0] in planned_ids and boundary[1] in planned_ids
        )
        partial = _enforce_required_shared_boundaries(partial, scene, required + declared)
        normalized.extend(partial.segments)
    proposal = replace(proposal, segments=tuple(normalized))
    _validate_scope(proposal, scenes)
    operations = compile_plan_operations(proposal, _scene_slots(scenes))
    return proposal, operations
