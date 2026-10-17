from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import replace

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
    KeyframeShotInput,
    KeyframeShotProposal,
)
from core.director_proposals.schema_gen import ProposalError, generate_schema, parse_proposal
from core.structured_director.models import DEFAULT_ENVIRONMENT_NONE_REASON

_OPTIONAL_ID_SCHEMA = {
    "anyOf": [
        {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        {"type": "null"},
    ]
}
# 三个环境字段 wire 必填但可为 null：使用方式为 null 表示未声明，由 Core 继承 Shot 视图；
# 声明 none 时必须写理由，使用视图时理由必须为 null（交叉约束由 proposal dataclass 校验）。
_ENVIRONMENT_MODE_SCHEMA = {
    "anyOf": [
        {"type": "string", "enum": ["edit", "reference", "none"]},
        {"type": "null"},
    ],
    "__required__": True,
}
_OPTIONAL_REASON_SCHEMA = {
    "anyOf": [
        {"type": "string", "minLength": 1, "maxLength": 500},
        {"type": "null"},
    ],
    "__required__": True,
}
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
    "shots[].shot_id": {"pattern": "^[0-9a-f]{32}$"},
    "shots[].start_prompt_text": {"minLength": 1, "maxLength": 18_000},
    "shots[].start_visible_character_ids": {
        "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"}
    },
    "shots[].start_environment_mode": _ENVIRONMENT_MODE_SCHEMA,
    "shots[].start_environment_view_id": {
        **_OPTIONAL_ID_SCHEMA,
        "__required__": True,
    },
    "shots[].start_environment_none_reason": _OPTIONAL_REASON_SCHEMA,
    "shots[].start_character_references": _CHARACTER_REFERENCES_SCHEMA,
    "shots[].segments": {"minItems": 1},
    "shots[].segments[].segment_id": {"pattern": "^[0-9a-f]{32}$"},
    "shots[].segments[].frame_strategy": {"enum": ["start", "end", "both"]},
    "shots[].segments[].end_prompt_text": {"minLength": 1, "maxLength": 18_000},
    "shots[].segments[].end_visible_character_ids": {
        "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"}
    },
    "shots[].segments[].end_environment_mode": _ENVIRONMENT_MODE_SCHEMA,
    "shots[].segments[].end_environment_view_id": {
        **_OPTIONAL_ID_SCHEMA,
        "__required__": True,
    },
    "shots[].segments[].end_environment_none_reason": _OPTIONAL_REASON_SCHEMA,
    "shots[].segments[].end_character_references": _CHARACTER_REFERENCES_SCHEMA,
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
            shots=tuple(
                replace(
                    shot,
                    start_prompt_text=normalize_keyframe_prompt_text(shot.start_prompt_text),
                    segments=tuple(
                        replace(
                            segment,
                            end_prompt_text=normalize_keyframe_prompt_text(segment.end_prompt_text),
                        )
                        for segment in shot.segments
                    ),
                )
                for shot in proposal.shots
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


def _compile_operations(
    proposal: KeyframePlanProposal,
    scenes: tuple[KeyframeSceneInput, ...],
) -> tuple[KeyframeOperation, ...] | None:
    """把创作结果绑定到当前槽位；缺少槽位上下文时保留旧 proposal 兼容路径。"""
    segments = [segment for scene in scenes for shot in scene.shots for segment in shot.segments]
    if any(
        segment.start_keyframe_id is None or segment.end_keyframe_id is None for segment in segments
    ):
        return None
    proposal_by_shot = {item.shot_id: item for item in proposal.shots}
    operations: list[KeyframeOperation] = []
    for scene in scenes:
        previous_shot: KeyframeShotInput | None = None
        previous_proposal: KeyframeShotProposal | None = None
        for shot in scene.shots:
            planned = proposal_by_shot.get(shot.id)
            if not shot.planning_enabled:
                previous_shot = shot
                previous_proposal = None
                continue
            if planned is None:
                raise ProposalError(
                    "keyframe", "invalid_proposal", "Agent 遗漏了授权范围内的 Shot。"
                )
            first_segment = shot.segments[0]
            segment_locked = {
                item.id: item.start_locked or item.end_locked for item in shot.segments
            }
            if shot.planning_enabled and not segment_locked[first_segment.id]:
                assert first_segment.start_keyframe_id is not None
                currently_shared = (
                    previous_shot is not None
                    and previous_shot.segments[-1].end_keyframe_id
                    == first_segment.start_keyframe_id
                )
                if currently_shared and not planned.continues_from_previous_shot:
                    previous_segment = previous_shot.segments[-1]
                    if (
                        not previous_shot.planning_enabled
                        or previous_segment.start_locked
                        or previous_segment.end_locked
                    ):
                        raise ProposalError(
                            "keyframe",
                            "invalid_proposal",
                            "解除与上下文 Shot 的共享边界会越出授权；请至少扩大到相邻 Shot："
                            f"{previous_shot.id}。",
                        )
                    operations.append(
                        SplitKeyframeBoundary(
                            left_segment_id=previous_segment.id,
                            right_segment_id=first_segment.id,
                            clone_side="left_end",
                            copy_selection=True,
                        )
                    )
                if not planned.continues_from_previous_shot:
                    operations.append(
                        UpdateKeyframeFields(
                            keyframe_id=first_segment.start_keyframe_id,
                            prompt_text=planned.start_prompt_text,
                            visible_character_ids=planned.start_visible_character_ids,
                            **_environment_fields(
                                planned.start_environment_mode,
                                planned.start_environment_view_id,
                                planned.start_environment_none_reason,
                                shot.view_id,
                            ),
                            character_references=_selections(planned.start_character_references),
                        )
                    )
            previous_plan = None
            for index, (segment, segment_plan) in enumerate(
                zip(shot.segments, planned.segments, strict=True)
            ):
                boundary_plan, previous_plan = previous_plan, segment_plan
                if not shot.planning_enabled or segment_locked[segment.id]:
                    continue
                assert segment.start_keyframe_id is not None
                assert segment.end_keyframe_id is not None
                if (
                    index > 0
                    and boundary_plan is not None
                    and segment.start_keyframe_id != shot.segments[index - 1].end_keyframe_id
                ):
                    # Shot 内边界默认是独立 Keyframe：首帧沿用上一段尾帧的画面描述作为连续性
                    # 起点；用户之后可直接生成，或从上一段视频抽帧后另行处理。
                    operations.append(
                        UpdateKeyframeFields(
                            keyframe_id=segment.start_keyframe_id,
                            prompt_text=boundary_plan.end_prompt_text,
                            visible_character_ids=boundary_plan.end_visible_character_ids,
                            **_environment_fields(
                                boundary_plan.end_environment_mode,
                                boundary_plan.end_environment_view_id,
                                boundary_plan.end_environment_none_reason,
                                shot.view_id,
                            ),
                            character_references=_selections(
                                boundary_plan.end_character_references
                            ),
                        )
                    )
                operations.extend(
                    (
                        UpdateKeyframeFields(
                            keyframe_id=segment.end_keyframe_id,
                            prompt_text=segment_plan.end_prompt_text,
                            visible_character_ids=segment_plan.end_visible_character_ids,
                            **_environment_fields(
                                segment_plan.end_environment_mode,
                                segment_plan.end_environment_view_id,
                                segment_plan.end_environment_none_reason,
                                shot.view_id,
                            ),
                            character_references=_selections(segment_plan.end_character_references),
                        ),
                        SetKeyframeActivation(
                            segment_id=segment.id,
                            start_enabled=segment_plan.frame_strategy in {"start", "both"},
                            end_enabled=segment_plan.frame_strategy in {"end", "both"},
                        ),
                    )
                )
            if (
                planned.continues_from_previous_shot
                and previous_shot is not None
                and shot.planning_enabled
            ):
                left = previous_shot.segments[-1]
                right = first_segment
                if not previous_shot.planning_enabled:
                    if left.end_keyframe_id != right.start_keyframe_id:
                        raise ProposalError(
                            "keyframe",
                            "invalid_proposal",
                            "与上下文 Shot 新建共享边界会越出授权；请至少扩大到相邻 Shot："
                            f"{previous_shot.id}。",
                        )
                    previous_shot = shot
                    previous_proposal = planned
                    continue
                if previous_proposal is None:
                    raise RuntimeError("可写相邻 Shot 缺少已校验 proposal。")
                if not (
                    left.start_locked or left.end_locked or right.start_locked or right.end_locked
                ):
                    assert left.end_keyframe_id is not None
                    if left.end_keyframe_id != right.start_keyframe_id:
                        operations.append(
                            ShareKeyframeBoundary(
                                left_segment_id=left.id,
                                right_segment_id=right.id,
                                source_keyframe_id=left.end_keyframe_id,
                                expected_adjacency="cross_shot",
                            )
                        )
            previous_shot = shot
            previous_proposal = planned
    return tuple(operations)


def resolve_keyframe_environment(
    mode: str | None, view_id: str | None, none_reason: str | None, shot_view_id: str | None
) -> tuple[str, str | None, str | None]:
    """Planner 未声明（mode 为 null）时继承 Shot 视图：有视图 reference，否则 none + 默认理由。

    与 `blank_keyframe` 同一规则；视图只作空间参考，`edit` 只在显式声明时使用。
    显式 none 的理由已由 proposal 校验为必填。
    """
    if mode is not None:
        return mode, view_id, none_reason
    if shot_view_id is not None:
        return "reference", shot_view_id, None
    return "none", None, DEFAULT_ENVIRONMENT_NONE_REASON


def _environment_fields(
    mode: str | None, view_id: str | None, none_reason: str | None, shot_view_id: str | None
) -> dict[str, object]:
    mode, view_id, none_reason = resolve_keyframe_environment(
        mode, view_id, none_reason, shot_view_id
    )
    return {
        "environment_mode": mode,
        "environment_view_id": view_id,
        "environment_none_reason": none_reason,
        "environment_changed": True,
    }


def _selections(
    references: tuple[KeyframeCharacterReferenceProposal, ...],
) -> tuple[KeyframeCharacterReferenceSelection, ...]:
    return tuple(
        KeyframeCharacterReferenceSelection(item.character_id, item.look_id) for item in references
    )


def _reference_key(
    references: tuple[KeyframeCharacterReferenceProposal, ...],
) -> dict[str, str | None]:
    return {item.character_id: item.look_id for item in references}


def _validate_scope(
    proposal: KeyframePlanProposal,
    scenes: tuple[KeyframeSceneInput, ...],
) -> None:
    expected_shots = [shot for scene in scenes for shot in scene.shots if shot.planning_enabled]
    if [item.shot_id for item in proposal.shots] != [item.id for item in expected_shots]:
        raise ProposalError(
            "keyframe", "invalid_proposal", "Agent 必须按生产基线顺序仅返回授权 Shot。"
        )
    proposal_by_id = {item.shot_id: item for item in proposal.shots}
    for scene in scenes:
        for shot_index, shot in enumerate(scene.shots):
            if not shot.planning_enabled:
                continue
            actual = proposal_by_id[shot.id]
            if [item.segment_id for item in actual.segments] != [item.id for item in shot.segments]:
                raise ProposalError(
                    "keyframe", "invalid_proposal", "Agent 必须按顺序完整返回每个 Segment。"
                )
            allowed = {item.id for item in shot.visible_characters}
            if actual.continues_from_previous_shot:
                if shot_index == 0:
                    raise ProposalError(
                        "keyframe",
                        "invalid_proposal",
                        "每个 Scene 的第一个 Shot 不能承接上一 Shot。",
                    )
                previous_shot = scene.shots[shot_index - 1]
                previous = proposal_by_id.get(previous_shot.id)
                if previous is None:
                    if (
                        previous_shot.segments[-1].end_keyframe_id
                        != shot.segments[0].start_keyframe_id
                    ):
                        raise ProposalError(
                            "keyframe",
                            "invalid_proposal",
                            "与上下文 Shot 新建共享边界会越出授权；请至少扩大到相邻 Shot："
                            f"{previous_shot.id}。",
                        )
                else:
                    previous_end = previous.segments[-1]
                    if (
                        actual.start_prompt_text.strip() != previous_end.end_prompt_text.strip()
                        or set(actual.start_visible_character_ids)
                        != set(previous_end.end_visible_character_ids)
                        or actual.start_environment_mode != previous_end.end_environment_mode
                        or actual.start_environment_view_id != previous_end.end_environment_view_id
                        or actual.start_environment_none_reason
                        != previous_end.end_environment_none_reason
                        or _reference_key(actual.start_character_references)
                        != _reference_key(previous_end.end_character_references)
                    ):
                        raise ProposalError(
                            "keyframe",
                            "invalid_proposal",
                            "承接 Shot 的首帧必须与上一 Shot 尾帧完全一致。",
                        )
            elif not set(actual.start_visible_character_ids) <= allowed:
                raise ProposalError(
                    "keyframe", "invalid_proposal", "Agent 返回了不属于该 Shot 的可见角色 ID。"
                )
            view_ids = (
                actual.start_environment_view_id,
                *(item.end_environment_view_id for item in actual.segments),
            )
            if any(
                view_id is not None and view_id not in scene.available_view_ids
                for view_id in view_ids
            ):
                raise ProposalError(
                    "keyframe", "invalid_proposal", "关键帧引用了工作集之外的地点视图。"
                )
            looks = {
                item.id: {look.look_id for look in item.looks}
                for candidate in scene.shots
                for item in candidate.visible_characters
            }
            for reference in (
                *actual.start_character_references,
                *(ref for item in actual.segments for ref in item.end_character_references),
            ):
                if reference.look_id is not None and reference.look_id not in looks.get(
                    reference.character_id, set()
                ):
                    raise ProposalError(
                        "keyframe",
                        "invalid_proposal",
                        "角色造型选择必须来自工作集中该角色的 looks。",
                    )
            next_shot = scene.shots[shot_index + 1] if shot_index + 1 < len(scene.shots) else None
            next_continues = (
                next_shot is not None
                and next_shot.id in proposal_by_id
                and proposal_by_id[next_shot.id].continues_from_previous_shot
            )
            for segment_index, segment in enumerate(actual.segments):
                boundary_allowed = set(allowed)
                if segment_index == len(actual.segments) - 1 and next_continues:
                    assert next_shot is not None
                    boundary_allowed.update(item.id for item in next_shot.visible_characters)
                if not set(segment.end_visible_character_ids) <= boundary_allowed:
                    raise ProposalError(
                        "keyframe",
                        "invalid_proposal",
                        "Agent 返回了不属于相邻 Shot 角色并集的可见角色 ID。",
                    )


def _enforce_required_shared_boundaries(
    proposal: KeyframePlanProposal,
    scene: KeyframeSceneInput,
    required_shared_boundaries: tuple[tuple[str, str], ...],
) -> KeyframePlanProposal:
    if not required_shared_boundaries:
        return proposal
    proposal_by_shot = {item.shot_id: item for item in proposal.shots}
    shots = list(proposal.shots)
    shot_index_by_id = {item.shot_id: index for index, item in enumerate(shots)}
    for left_segment_id, right_segment_id in required_shared_boundaries:
        match = next(
            (
                (left_shot, right_shot)
                for left_shot, right_shot in zip(scene.shots, scene.shots[1:], strict=False)
                if left_shot.segments[-1].id == left_segment_id
                and right_shot.segments[0].id == right_segment_id
            ),
            None,
        )
        if match is None:
            raise ProposalError(
                "keyframe", "invalid_proposal", "Core 指定的共享边界不是当前 Scene 的相邻 Shot。"
            )
        left_shot, right_shot = match
        left = proposal_by_shot[left_shot.id]
        right = proposal_by_shot[right_shot.id]
        left_segments = list(left.segments)
        left_end = left_segments[-1]
        if left_end.frame_strategy == "start":
            left_end = replace(left_end, frame_strategy="both")
            left_segments[-1] = left_end
            left = replace(left, segments=tuple(left_segments))
            shots[shot_index_by_id[left.shot_id]] = left
            proposal_by_shot[left.shot_id] = left
        right_segments = list(right.segments)
        if right_segments[0].frame_strategy == "end":
            right_segments[0] = replace(right_segments[0], frame_strategy="both")
        right = replace(
            right,
            continues_from_previous_shot=True,
            start_prompt_text=left_end.end_prompt_text,
            start_visible_character_ids=left_end.end_visible_character_ids,
            start_environment_mode=left_end.end_environment_mode,
            start_environment_view_id=left_end.end_environment_view_id,
            start_environment_none_reason=left_end.end_environment_none_reason,
            start_character_references=left_end.end_character_references,
            segments=tuple(right_segments),
        )
        shots[shot_index_by_id[right.shot_id]] = right
        proposal_by_shot[right.shot_id] = right
    return KeyframePlanProposal(tuple(shots))


def _enforce_segment_anchors(proposal: KeyframePlanProposal) -> KeyframePlanProposal:
    """保住段内连续交接与已声明角色覆盖，不推测图片的实际视觉内容。"""
    shots = []
    for shot in proposal.shots:
        segments = []
        start_characters = set(shot.start_visible_character_ids)
        for segment in shot.segments:
            end_characters = set(segment.end_visible_character_ids)
            start_enabled = segment.frame_strategy in {"start", "both"}
            end_enabled = segment.frame_strategy in {"end", "both"}
            # 单帧不能漏掉另一端已明确出现的角色；不向空镜伪加角色。
            if start_characters - end_characters:
                start_enabled = True
            if end_characters - start_characters:
                end_enabled = True
            strategy = (
                "both" if start_enabled and end_enabled else ("start" if start_enabled else "end")
            )
            segments.append(replace(segment, frame_strategy=strategy))
            start_characters = end_characters
        shots.append(replace(shot, segments=tuple(segments)))
    return KeyframePlanProposal(tuple(shots))


def _output_schema(scenes: tuple[KeyframeSceneInput, ...]) -> dict[str, object]:
    shots = [shot for scene in scenes for shot in scene.shots if shot.planning_enabled]
    shot_schemas = [
        _shot_schema(shot, scene.shots[index - 1] if index > 0 else None)
        for scene in scenes
        for index, shot in enumerate(scene.shots)
        if shot.planning_enabled
    ]
    schema = deepcopy(_STATIC_OUTPUT_SCHEMA)
    shots_schema = schema["properties"]["shots"]
    shots_schema.update(
        minItems=len(shots),
        maxItems=len(shots),
        prefixItems=shot_schemas,
        items=False,
    )
    return schema


def _shot_schema(
    shot: KeyframeShotInput,
    previous_shot: KeyframeShotInput | None,
) -> dict[str, object]:
    character_ids = [item.id for item in shot.visible_characters]
    start_character_ids = list(character_ids)
    if previous_shot is not None:
        start_character_ids.extend(
            item.id
            for item in previous_shot.visible_characters
            if item.id not in start_character_ids
        )
    segment_ids = [item.id for item in shot.segments]
    shot_schema = deepcopy(_STATIC_OUTPUT_SCHEMA["properties"]["shots"]["items"])
    segment_template = shot_schema["properties"]["segments"]["items"]
    segment_schemas = []
    for segment_id in segment_ids:
        segment_schema = deepcopy(segment_template)
        segment_schema["properties"]["segment_id"] = {"type": "string", "const": segment_id}
        segment_schema["properties"]["end_visible_character_ids"] = _id_array_schema(character_ids)
        _restrict_reference_characters(
            segment_schema["properties"]["end_character_references"], character_ids
        )
        segment_schemas.append(segment_schema)
    properties = shot_schema["properties"]
    properties["shot_id"] = {"type": "string", "const": shot.id}
    properties["start_visible_character_ids"] = _id_array_schema(start_character_ids)
    _restrict_reference_characters(properties["start_character_references"], start_character_ids)
    properties["segments"].update(
        minItems=len(segment_ids),
        maxItems=len(segment_ids),
        prefixItems=segment_schemas,
        items=False,
    )
    return shot_schema


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
    normalized = []
    for scene in scenes:
        ids = {s.id for s in scene.shots}
        partial = replace(proposal, shots=tuple(s for s in proposal.shots if s.shot_id in ids))
        scene_segments = {s.id for shot in scene.shots for s in shot.segments}
        partial_by_id = {shot.shot_id: shot for shot in partial.shots}
        declared = tuple(
            (left.segments[-1].id, right.segments[0].id)
            for left, right in zip(scene.shots, scene.shots[1:], strict=False)
            if right.id in partial_by_id
            and left.id in partial_by_id
            and partial_by_id[right.id].continues_from_previous_shot
        )
        required = tuple(b for b in required_shared_boundaries if b[0] in scene_segments)
        partial = _enforce_required_shared_boundaries(partial, scene, required + declared)
        normalized.extend(_enforce_segment_anchors(partial).shots)
    proposal = replace(proposal, shots=tuple(normalized))
    _validate_scope(proposal, scenes)
    operations = _compile_operations(proposal, scenes)
    return proposal, operations
