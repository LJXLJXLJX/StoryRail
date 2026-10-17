"""Translate UI value objects to the same deterministic command contract."""

from __future__ import annotations

from core.director_commands import DirectorCommand

from .errors import RevisionConflictError
from .models import Keyframe, StructuredDirectorDocument


def keyframe_edit_command(
    document: StructuredDirectorDocument,
    keyframe: Keyframe,
    *,
    expected_revision: int,
    segment_id: str | None = None,
    reference_asset_ids: tuple[str, ...] | None = None,
) -> DirectorCommand:
    if document.revision != expected_revision:
        raise RevisionConflictError("项目已更新，请刷新后重试。")
    plan = document.keyframe_plan
    if plan is None:
        raise ValueError("关键帧计划尚未建立。")
    existing = next((x for x in plan.keyframes if x.id == keyframe.id), None)
    if existing is None:
        raise ValueError("Keyframe 不存在。")
    if not any(
        (x.start_keyframe_id == keyframe.id and x.start_enabled)
        or (x.end_keyframe_id == keyframe.id and x.end_enabled)
        for x in plan.segments
    ):
        raise ValueError("该 Keyframe 未激活，不能修改。")
    if (
        keyframe.owner_segment_id,
        keyframe.predecessor_keyframe_id,
        keyframe.selected_asset_id,
    ) != (
        existing.owner_segment_id,
        existing.predecessor_keyframe_id,
        existing.selected_asset_id,
    ):
        raise ValueError("人工编辑不能改变 Keyframe 的绑定、依赖或候选选择。")
    if (segment_id is None) != (reference_asset_ids is None):
        raise ValueError("Keyframe 图片引用必须与 Segment 一起提交。")
    operations: list[dict[str, object]] = [
        {
            "op": "update_frame_fields",
            "keyframe_id": keyframe.id,
            "fields": {
                "prompt_text": keyframe.prompt_text,
                "visible_character_ids": list(keyframe.visible_character_ids),
                "character_references": [
                    {"character_id": item.character_id, "look_id": item.look_id}
                    for item in keyframe.character_references
                ],
                "environment_mode": keyframe.environment_mode.value,
                "environment_view_id": keyframe.environment_view_id,
                "environment_none_reason": keyframe.environment_none_reason,
            },
        }
    ]
    if segment_id is not None:
        binding = next((x for x in plan.segments if x.segment_id == segment_id), None)
        if binding is None or keyframe.id not in {
            binding.start_keyframe_id,
            binding.end_keyframe_id,
        }:
            raise ValueError("Keyframe 不属于指定 Segment。")
        operations.append(
            {
                "op": "set_aux_references",
                "segment_id": segment_id,
                "asset_ids": list(reference_asset_ids),
            }
        )
    return DirectorCommand(
        "keyframe.apply_operations",
        expected_revision,
        f"ui-keyframe-edit:{expected_revision}:{keyframe.id}",
        {"operations": operations},
    )


def keyframe_activation_command(
    *,
    segment_id: str,
    start_enabled: bool,
    end_enabled: bool,
    expected_revision: int,
) -> DirectorCommand:
    return DirectorCommand(
        "keyframe.apply_operations",
        expected_revision,
        f"ui-keyframe-activation:{expected_revision}:{segment_id}",
        {
            "operations": [
                {
                    "op": "set_activation",
                    "segment_id": segment_id,
                    "start_enabled": start_enabled,
                    "end_enabled": end_enabled,
                }
            ]
        },
    )


def keyframe_references_command(
    *,
    segment_id: str,
    asset_ids: tuple[str, ...],
    expected_revision: int,
) -> DirectorCommand:
    return DirectorCommand(
        "keyframe.apply_operations",
        expected_revision,
        f"ui-keyframe-references:{expected_revision}:{segment_id}",
        {
            "operations": [
                {
                    "op": "set_aux_references",
                    "segment_id": segment_id,
                    "asset_ids": list(asset_ids),
                }
            ]
        },
    )


def location_operations_command(
    *,
    scope: object,
    operations: object,
    expected_revision: int,
) -> DirectorCommand:
    """人类地点编辑与 Agent 走同一 `location.apply_operations` 契约。"""
    return DirectorCommand(
        "location.apply_operations",
        expected_revision,
        f"ui-location-operations:{expected_revision}",
        {"scope": scope, "operations": operations},
    )


def location_calibration_command(
    *,
    location_id: str,
    fixture_azimuths: object,
    key_light_azimuth_deg: object,
    expected_revision: int,
) -> DirectorCommand:
    return DirectorCommand(
        "location.apply_operations",
        expected_revision,
        f"ui-location-calibrate:{expected_revision}:{location_id}",
        {
            "scope": {"location_ids": [location_id], "scene_ids": [], "shot_ids": []},
            "operations": [
                {
                    "op": "calibrate",
                    "location_id": location_id,
                    "fixture_azimuths": fixture_azimuths,
                    "key_light_azimuth_deg": key_light_azimuth_deg,
                }
            ],
        },
    )


def location_selection_command(
    *,
    target: str,
    target_id: str,
    asset_id: str,
    expected_revision: int,
) -> DirectorCommand:
    """人类候选选择：`target` 为 master（地点 ID）或 view（视图 ID）。"""
    name, field = {
        "master": ("location.select_master", "location_id"),
        "view": ("location.select_view", "view_id"),
    }[target]
    return DirectorCommand(
        name,
        expected_revision,
        f"ui-{name}:{expected_revision}:{target_id}",
        {field: target_id, "asset_id": asset_id},
    )
