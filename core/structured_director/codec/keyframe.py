"""文档编解码：keyframe 域的 parse/serialize 函数对（纯移动，语义/JSON key/错误消息不变）。"""

from __future__ import annotations

from typing import Any

from ..models import (
    Keyframe,
    KeyframeCharacterReference,
    KeyframeEnvironmentMode,
    KeyframePlan,
    SegmentKeyframes,
)
from ._shared import (
    _boolean,
    _exact_object,
    _integer,
    _object_list,
    _optional_string,
    _string,
    _string_list,
)

_KEYFRAME_FIELDS = {
    "id",
    "owner_segment_id",
    "predecessor_keyframe_id",
    "prompt_text",
    "visible_character_ids",
    "selected_asset_id",
    "environment_mode",
    "environment_view_id",
    "environment_none_reason",
    "character_references",
}

_CHARACTER_REFERENCE_FIELDS = {"character_id", "look_id"}

_SEGMENT_KEYFRAMES_FIELDS = {
    "segment_id",
    "start_keyframe_id",
    "end_keyframe_id",
    "start_enabled",
    "end_enabled",
    "reference_asset_ids",
}

_KEYFRAME_PLAN_FIELDS = {"source_script_revision", "keyframes", "segments"}


def serialize_character_references(keyframe: Keyframe) -> list[dict[str, Any]]:
    return [
        {"character_id": item.character_id, "look_id": item.look_id}
        for item in keyframe.character_references
    ]


def _serialize_keyframe_plan(plan: KeyframePlan) -> dict[str, Any]:
    return {
        "source_script_revision": plan.source_script_revision,
        "keyframes": [
            {
                "id": item.id,
                "owner_segment_id": item.owner_segment_id,
                "predecessor_keyframe_id": item.predecessor_keyframe_id,
                "prompt_text": item.prompt_text,
                "visible_character_ids": list(item.visible_character_ids),
                "selected_asset_id": item.selected_asset_id,
                "environment_mode": item.environment_mode.value,
                "environment_view_id": item.environment_view_id,
                "environment_none_reason": item.environment_none_reason,
                "character_references": serialize_character_references(item),
            }
            for item in plan.keyframes
        ],
        "segments": [
            {
                "segment_id": item.segment_id,
                "start_keyframe_id": item.start_keyframe_id,
                "end_keyframe_id": item.end_keyframe_id,
                "start_enabled": item.start_enabled,
                "end_enabled": item.end_enabled,
                "reference_asset_ids": list(item.reference_asset_ids),
            }
            for item in plan.segments
        ],
    }


def _parse_keyframe_plan(value: object) -> KeyframePlan:
    fields = _exact_object(value, _KEYFRAME_PLAN_FIELDS)
    return KeyframePlan(
        source_script_revision=_integer(
            fields["source_script_revision"], "keyframe_plan.source_script_revision"
        ),
        keyframes=_object_list(fields["keyframes"], _parse_keyframe),
        segments=_object_list(fields["segments"], _parse_segment_keyframes),
    )


def _parse_keyframe(value: object) -> Keyframe:
    fields = _exact_object(value, _KEYFRAME_FIELDS)
    return Keyframe(
        id=_string(fields["id"], "keyframe.id"),
        owner_segment_id=_string(fields["owner_segment_id"], "keyframe.owner_segment_id"),
        predecessor_keyframe_id=_optional_string(
            fields["predecessor_keyframe_id"], "keyframe.predecessor_keyframe_id"
        ),
        prompt_text=_string(fields["prompt_text"], "keyframe.prompt_text"),
        visible_character_ids=_string_list(
            fields["visible_character_ids"], "keyframe.visible_character_ids"
        ),
        selected_asset_id=_optional_string(
            fields["selected_asset_id"], "keyframe.selected_asset_id"
        ),
        environment_view_id=_optional_string(
            fields["environment_view_id"], "keyframe.environment_view_id"
        ),
        environment_mode=KeyframeEnvironmentMode(
            _string(fields["environment_mode"], "keyframe.environment_mode")
        ),
        environment_none_reason=_optional_string(
            fields["environment_none_reason"], "keyframe.environment_none_reason"
        ),
        character_references=_object_list(
            fields["character_references"], _parse_character_reference
        ),
    )


def _parse_character_reference(value: object) -> KeyframeCharacterReference:
    fields = _exact_object(value, _CHARACTER_REFERENCE_FIELDS)
    return KeyframeCharacterReference(
        character_id=_string(fields["character_id"], "keyframe.character_references.character_id"),
        look_id=_optional_string(fields["look_id"], "keyframe.character_references.look_id"),
    )


def _parse_segment_keyframes(value: object) -> SegmentKeyframes:
    fields = _exact_object(value, _SEGMENT_KEYFRAMES_FIELDS)
    return SegmentKeyframes(
        segment_id=_string(fields["segment_id"], "segment_keyframes.segment_id"),
        start_keyframe_id=_string(
            fields["start_keyframe_id"], "segment_keyframes.start_keyframe_id"
        ),
        end_keyframe_id=_string(fields["end_keyframe_id"], "segment_keyframes.end_keyframe_id"),
        start_enabled=_boolean(fields["start_enabled"], "segment_keyframes.start_enabled"),
        end_enabled=_boolean(fields["end_enabled"], "segment_keyframes.end_enabled"),
        reference_asset_ids=_string_list(
            fields["reference_asset_ids"], "segment_keyframes.reference_asset_ids"
        ),
    )
