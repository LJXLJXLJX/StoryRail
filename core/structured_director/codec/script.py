"""文档编解码：script 域的 parse/serialize 函数对（纯移动，语义/JSON key/错误消息不变）。"""

from __future__ import annotations

from typing import Any

from ..models import (
    CapabilityGapAlert,
    CapabilityGapRepairOperation,
    CapabilityGapResult,
    CapabilityGapStatus,
    DialogueLine,
    DirectorScript,
    PendingNarrationEdit,
    PendingScriptEdit,
    Scene,
    SegmentBoundary,
    SegmentBoundaryReason,
    Shot,
    ShotSegment,
)
from ._shared import (
    _exact_object,
    _integer,
    _number,
    _object_list,
    _optional_integer,
    _optional_string,
    _string,
    _string_list,
)
from .narration import _parse_narration_cue, _serialize_narration_cue

_DIALOGUE_LINE_FIELDS = {
    "id",
    "character_id",
    "speaker_label",
    "voice_description",
    "text",
    "delivery",
}

_BOUNDARY_FIELDS = {"reason", "continuity_instruction"}

_SEGMENT_FIELDS = {
    "id",
    "shot_ids",
    "duration_estimate_seconds",
    "action",
    "dialogue_lines",
    "boundary_from_previous",
}

_SHOT_FIELDS = {
    "id",
    "visible_character_ids",
    "composition",
    "camera_movement",
    "action",
    "audio_direction",
    "transition_in",
    "view_id",
}

_SCENE_FIELDS = {
    "id",
    "title",
    "summary",
    "setting",
    "shots",
    "segments",
    "narration_cues",
    "driver",
    "location_id",
    "state_id",
}

_SCRIPT_FIELDS = {
    "revision",
    "source_reference_revision",
    "production_baseline_revision",
    "production_baseline_scenes",
    "scenes",
}

_PENDING_SCRIPT_EDIT_FIELDS = {"base_script_revision", "user_message"}

_PENDING_NARRATION_EDIT_FIELDS = {"base_script_revision", "user_message"}


def _serialize_capability_gap_alert(alert: CapabilityGapAlert) -> dict[str, Any]:
    def operation(item: CapabilityGapRepairOperation) -> dict[str, Any]:
        return {
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "fields": item.fields,
        }

    return {
        "gap_id": alert.gap_id,
        "command_id": alert.command_id,
        "command_ids": list(alert.command_ids),
        "run_id": alert.run_id,
        "missing_command": alert.missing_command,
        "raw_user_request_summary": alert.raw_user_request_summary,
        "target_ids": list(alert.target_ids),
        "scope_scene_ids": list(alert.scope_scene_ids),
        "operations": [operation(item) for item in alert.operations],
        "reverse_operations": [operation(item) for item in alert.reverse_operations],
        "operation_summary": alert.operation_summary,
        "old_revision": alert.old_revision,
        "new_revision": alert.new_revision,
        "result": alert.result.value,
        "first_occurred_at": alert.first_occurred_at,
        "last_occurred_at": alert.last_occurred_at,
        "occurrence_count": alert.occurrence_count,
        "closed_revision": alert.closed_revision,
        "closed_by_command": alert.closed_by_command,
        "status": alert.status.value,
    }


def _serialize_director_script(script: DirectorScript) -> dict[str, Any]:
    return {
        "revision": script.revision,
        "source_reference_revision": script.source_reference_revision,
        "production_baseline_revision": script.production_baseline_revision,
        "production_baseline_scenes": (
            None
            if script.production_baseline_scenes is None
            else [_serialize_scene(scene) for scene in script.production_baseline_scenes]
        ),
        "scenes": [_serialize_scene(scene) for scene in script.scenes],
    }


def _serialize_scene(scene: Scene) -> dict[str, Any]:
    return {
        "id": scene.id,
        "title": scene.title,
        "summary": scene.summary,
        "setting": scene.setting,
        "driver": scene.driver,
        "location_id": scene.location_id,
        "state_id": scene.state_id,
        "shots": [_serialize_shot(shot) for shot in scene.shots],
        "segments": [_serialize_segment(segment) for segment in scene.segments],
        "narration_cues": [_serialize_narration_cue(cue) for cue in scene.narration_cues],
    }


def _serialize_shot(shot: Shot) -> dict[str, Any]:
    return {
        "id": shot.id,
        "visible_character_ids": list(shot.visible_character_ids),
        "composition": shot.composition,
        "camera_movement": shot.camera_movement,
        "action": shot.action,
        "audio_direction": shot.audio_direction,
        "transition_in": shot.transition_in,
        "view_id": shot.view_id,
    }


def _serialize_segment(segment: ShotSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "shot_ids": list(segment.shot_ids),
        "duration_estimate_seconds": segment.duration_estimate_seconds,
        "action": segment.action,
        "dialogue_lines": [
            {
                "id": line.id,
                "character_id": line.character_id,
                "speaker_label": line.speaker_label,
                "voice_description": line.voice_description,
                "text": line.text,
                "delivery": line.delivery,
            }
            for line in segment.dialogue_lines
        ],
        "boundary_from_previous": (
            None
            if segment.boundary_from_previous is None
            else {
                "reason": segment.boundary_from_previous.reason.value,
                "continuity_instruction": (segment.boundary_from_previous.continuity_instruction),
            }
        ),
    }


def _parse_capability_gap_alert(value: object) -> CapabilityGapAlert:
    fields = _exact_object(
        value,
        {
            "gap_id",
            "command_id",
            "command_ids",
            "run_id",
            "missing_command",
            "raw_user_request_summary",
            "target_ids",
            "scope_scene_ids",
            "operations",
            "reverse_operations",
            "operation_summary",
            "old_revision",
            "new_revision",
            "result",
            "first_occurred_at",
            "last_occurred_at",
            "occurrence_count",
            "closed_revision",
            "closed_by_command",
            "status",
        },
    )
    return CapabilityGapAlert(
        gap_id=_string(fields["gap_id"], "capability_gap.gap_id"),
        command_id=_string(fields["command_id"], "capability_gap.command_id"),
        command_ids=_string_list(fields["command_ids"], "capability_gap.command_ids"),
        run_id=_string(fields["run_id"], "capability_gap.run_id"),
        missing_command=_string(fields["missing_command"], "capability_gap.missing_command"),
        raw_user_request_summary=_string(
            fields["raw_user_request_summary"],
            "capability_gap.raw_user_request_summary",
        ),
        target_ids=_string_list(fields["target_ids"], "capability_gap.target_ids"),
        scope_scene_ids=_string_list(fields["scope_scene_ids"], "capability_gap.scope_scene_ids"),
        operations=_object_list(fields["operations"], _parse_capability_gap_operation),
        reverse_operations=_object_list(
            fields["reverse_operations"], _parse_capability_gap_operation
        ),
        operation_summary=_string(fields["operation_summary"], "capability_gap.operation_summary"),
        old_revision=_integer(fields["old_revision"], "capability_gap.old_revision"),
        new_revision=_integer(fields["new_revision"], "capability_gap.new_revision"),
        result=CapabilityGapResult(_string(fields["result"], "capability_gap.result")),
        first_occurred_at=_string(fields["first_occurred_at"], "capability_gap.first_occurred_at"),
        last_occurred_at=_string(fields["last_occurred_at"], "capability_gap.last_occurred_at"),
        occurrence_count=_integer(fields["occurrence_count"], "capability_gap.occurrence_count"),
        closed_revision=_optional_integer(
            fields["closed_revision"], "capability_gap.closed_revision"
        ),
        closed_by_command=_optional_string(
            fields["closed_by_command"], "capability_gap.closed_by_command"
        ),
        status=CapabilityGapStatus(_string(fields["status"], "capability_gap.status")),
    )


def _parse_capability_gap_operation(value: object) -> CapabilityGapRepairOperation:
    fields = _exact_object(value, {"entity_type", "entity_id", "fields"})
    raw_fields = fields["fields"]
    if not isinstance(raw_fields, dict):
        raise ValueError("capability gap operation fields 必须是 object。")
    normalized: dict[str, str | float | None] = {}
    for name, item in raw_fields.items():
        if not isinstance(name, str):
            raise ValueError("capability gap operation field name 不合法。")
        if item is not None and not isinstance(item, (str, int, float)):
            raise ValueError("capability gap operation field value 不合法。")
        if isinstance(item, bool):
            raise ValueError("capability gap operation field value 不合法。")
        normalized[name] = float(item) if isinstance(item, (int, float)) else item
    return CapabilityGapRepairOperation(
        _string(fields["entity_type"], "capability_gap.operation.entity_type"),
        _string(fields["entity_id"], "capability_gap.operation.entity_id"),
        normalized,
    )


def _parse_director_script(value: object) -> DirectorScript:
    fields = _exact_object(value, _SCRIPT_FIELDS)
    return DirectorScript(
        revision=_integer(fields["revision"], "director_script.revision"),
        source_reference_revision=_integer(
            fields["source_reference_revision"],
            "director_script.source_reference_revision",
        ),
        production_baseline_revision=_optional_integer(
            fields["production_baseline_revision"],
            "director_script.production_baseline_revision",
        ),
        production_baseline_scenes=(
            None
            if fields["production_baseline_scenes"] is None
            else _object_list(fields["production_baseline_scenes"], _parse_scene)
        ),
        scenes=_object_list(fields["scenes"], _parse_scene),
    )


def _parse_pending_script_edit(value: object) -> PendingScriptEdit:
    fields = _exact_object(value, _PENDING_SCRIPT_EDIT_FIELDS)
    return PendingScriptEdit(
        base_script_revision=_integer(
            fields["base_script_revision"], "pending_script_edit.base_script_revision"
        ),
        user_message=_string(fields["user_message"], "pending_script_edit.user_message"),
    )


def _parse_pending_narration_edit(value: object) -> PendingNarrationEdit:
    fields = _exact_object(value, _PENDING_NARRATION_EDIT_FIELDS)
    return PendingNarrationEdit(
        base_script_revision=_integer(
            fields["base_script_revision"], "pending_narration_edit.base_script_revision"
        ),
        user_message=_string(fields["user_message"], "pending_narration_edit.user_message"),
    )


def _parse_scene(value: object) -> Scene:
    fields = _exact_object(value, _SCENE_FIELDS)
    return Scene(
        id=_string(fields["id"], "scene.id"),
        title=_string(fields["title"], "scene.title"),
        summary=_string(fields["summary"], "scene.summary"),
        setting=_string(fields["setting"], "scene.setting"),
        driver=_string(fields["driver"], "scene.driver"),
        location_id=_optional_string(fields["location_id"], "scene.location_id"),
        state_id=_optional_string(fields["state_id"], "scene.state_id"),
        shots=_object_list(fields["shots"], _parse_shot),
        segments=_object_list(fields["segments"], _parse_segment),
        narration_cues=_object_list(fields["narration_cues"], _parse_narration_cue),
    )


def _parse_shot(value: object) -> Shot:
    fields = _exact_object(value, _SHOT_FIELDS)
    return Shot(
        id=_string(fields["id"], "shot.id"),
        visible_character_ids=_string_list(
            fields["visible_character_ids"], "shot.visible_character_ids"
        ),
        composition=_string(fields["composition"], "shot.composition"),
        camera_movement=_string(fields["camera_movement"], "shot.camera_movement"),
        action=_string(fields["action"], "shot.action"),
        audio_direction=_string(fields["audio_direction"], "shot.audio_direction"),
        transition_in=_optional_string(fields["transition_in"], "shot.transition_in"),
        view_id=_optional_string(fields["view_id"], "shot.view_id"),
    )


def _parse_segment(value: object) -> ShotSegment:
    fields = _exact_object(value, _SEGMENT_FIELDS)
    boundary = fields["boundary_from_previous"]
    return ShotSegment(
        id=_string(fields["id"], "segment.id"),
        shot_ids=_string_list(fields["shot_ids"], "segment.shot_ids"),
        duration_estimate_seconds=_number(
            fields["duration_estimate_seconds"], "segment.duration_estimate_seconds"
        ),
        action=_string(fields["action"], "segment.action"),
        dialogue_lines=_object_list(fields["dialogue_lines"], _parse_dialogue_line),
        boundary_from_previous=(None if boundary is None else _parse_boundary(boundary)),
    )


def _parse_dialogue_line(value: object) -> DialogueLine:
    fields = _exact_object(value, _DIALOGUE_LINE_FIELDS)
    return DialogueLine(
        character_id=_optional_string(fields["character_id"], "dialogue_line.character_id"),
        text=_string(fields["text"], "dialogue_line.text"),
        delivery=_string(fields["delivery"], "dialogue_line.delivery"),
        speaker_label=_optional_string(fields["speaker_label"], "dialogue_line.speaker_label"),
        id=_string(fields["id"], "dialogue_line.id"),
        voice_description=_optional_string(
            fields["voice_description"], "dialogue_line.voice_description"
        ),
    )


def _parse_boundary(value: object) -> SegmentBoundary:
    fields = _exact_object(value, _BOUNDARY_FIELDS)
    return SegmentBoundary(
        reason=SegmentBoundaryReason(_string(fields["reason"], "boundary.reason")),
        continuity_instruction=_string(
            fields["continuity_instruction"], "boundary.continuity_instruction"
        ),
    )
