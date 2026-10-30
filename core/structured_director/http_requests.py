from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl
from uuid import uuid4

from core.application.caller import PROPOSAL_KINDS, READ_OPERATIONS
from core.director_proposals import (
    DialogueLineProposal,
    EditableNarrationCueProposal,
    EditableSceneProposal,
    EditableShotProposal,
    EditableShotSegmentProposal,
    NarrationTrackProposal,
    SegmentBoundaryProposal,
)
from core.director_proposals.wire_fields import (
    CHARACTER_LOOK_EDITOR_FIELDS,
    NARRATION_CUE_EDITOR_FIELDS,
    NARRATION_TRACK_EDIT_FIELDS,
    NARRATION_TRACK_EDITOR_FIELDS,
    SCENE_EDITOR_FIELDS,
    SEGMENT_EDITOR_FIELDS,
    SHOT_EDITOR_FIELDS,
)
from core.model_providers.recipe import RecipeParams
from storyrail_contracts.errors import error_payload
from storyrail_contracts.fields import field_mismatch, require_fields

from .models import (
    CharacterLook,
    KeyframeCharacterReference,
)


@dataclass(frozen=True, slots=True)
class JsonResponse:
    status: int
    body: dict[str, Any]


_NARRATION_CUE_FIELDS = NARRATION_CUE_EDITOR_FIELDS
_SCENE_FIELDS = SCENE_EDITOR_FIELDS
_SHOT_FIELDS = SHOT_EDITOR_FIELDS
_SEGMENT_FIELDS = SEGMENT_EDITOR_FIELDS


def _parse_scenes(value: object) -> tuple[EditableSceneProposal, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("scenes 必须是非空数组。")
    return tuple(_parse_scene(item) for item in value)


def _parse_scene(value: object) -> EditableSceneProposal:
    if isinstance(value, dict) and ({"animatic", "scene_final"} & set(value)):
        value = {key: item for key, item in value.items() if key not in {"animatic", "scene_final"}}
    item = _exact_object(value, _SCENE_FIELDS, "scene")
    _optional_id(item["location_id"], "location_id")
    _optional_id(item["state_id"], "state_id")
    shots = item["shots"]
    segments = item["segments"]
    if not isinstance(shots, list):
        raise ValueError("scene.shots 必须是数组。")
    if not isinstance(segments, list):
        raise ValueError("scene.segments 必须是数组。")
    return EditableSceneProposal(
        id=_optional_id(item["id"], "scene.id"),
        title=_plain_string(item["title"], "scene.title").strip(),
        summary=_plain_string(item["summary"], "scene.summary").strip(),
        setting=_plain_string(item["setting"], "scene.setting").strip(),
        driver=_plain_string(item["driver"], "scene.driver"),
        shots=tuple(_parse_shot(shot) for shot in shots),
        segments=tuple(_parse_segment(segment) for segment in segments),
        narration_cues=_parse_editable_narration_cues(item["narration_cues"]),
    )


def _parse_editable_narration_cues(
    value: object,
) -> tuple[EditableNarrationCueProposal, ...]:
    if not isinstance(value, list):
        raise ValueError("scene.narration_cues 必须是数组。")
    return tuple(
        EditableNarrationCueProposal(
            id=_optional_id(item["id"], "narration_cue.id"),
            zh=_parse_narration_track(item["zh"], "narration_cue.zh", editor=True),
            en=_parse_narration_track(item["en"], "narration_cue.en", editor=True),
        )
        for item in (_exact_object(raw, _NARRATION_CUE_FIELDS, "narration_cue") for raw in value)
    )


def _parse_narration_track(
    value: object, label: str, *, editor: bool = False
) -> NarrationTrackProposal | None:
    """单一语言旁白轨道；编辑器整卡回传时允许携带只读的已选音频 ID（由 Core 决定是否保留）。"""
    if value is None:
        return None
    fields = NARRATION_TRACK_EDITOR_FIELDS if editor else NARRATION_TRACK_EDIT_FIELDS
    item = _exact_object(value, set(fields), label)
    return NarrationTrackProposal(
        text=_plain_string(item["text"], f"{label}.text").strip(),
        seed=_integer(item["seed"], f"{label}.seed"),
        recipe_params=RecipeParams.from_json(
            item["recipe_params"], f"{label}.recipe_params"
        ).to_json(),
    )


def _parse_shot(value: object) -> EditableShotProposal:
    item = _exact_object(value, _SHOT_FIELDS, "shot")
    character_ids = item["visible_character_ids"]
    if not isinstance(character_ids, list):
        raise ValueError("shot.visible_character_ids 必须是数组。")
    return EditableShotProposal(
        id=_optional_id(item["id"], "shot.id"),
        visible_character_ids=tuple(
            _id(character_id, "shot.visible_character_ids") for character_id in character_ids
        ),
        composition=_plain_string(item["composition"], "shot.composition").strip(),
        camera_movement=_plain_string(item["camera_movement"], "shot.camera_movement").strip(),
        action=_plain_string(item["action"], "shot.action").strip(),
        audio_direction=_plain_string(item["audio_direction"], "shot.audio_direction").strip(),
        transition_in=_optional_text(item["transition_in"], "shot.transition_in"),
    )


def _parse_segment(value: object) -> EditableShotSegmentProposal:
    item = _exact_object(value, _SEGMENT_FIELDS, "segment")
    dialogue = item["dialogue_lines"]
    shot_indexes = item["shot_indexes"]
    if not isinstance(dialogue, list):
        raise ValueError("segment.dialogue_lines 必须是数组。")
    if not isinstance(shot_indexes, list) or not shot_indexes:
        raise ValueError("segment.shot_indexes 必须是非空数组。")
    boundary = item["boundary_from_previous"]
    return EditableShotSegmentProposal(
        id=_optional_id(item["id"], "segment.id"),
        shot_indexes=tuple(_index(value, "segment.shot_indexes") for value in shot_indexes),
        duration_estimate_seconds=_number(
            item["duration_estimate_seconds"], "segment.duration_estimate_seconds"
        ),
        action=_plain_string(item["action"], "segment.action").strip(),
        dialogue_lines=tuple(_parse_dialogue_line(line) for line in dialogue),
        boundary_from_previous=(None if boundary is None else _parse_boundary(boundary)),
    )


def _parse_dialogue_line(value: object) -> DialogueLineProposal:
    if isinstance(value, dict):
        value = {
            "id": None,
            "speaker_label": None,
            "voice_description": None,
            **value,
        }
    item = _exact_object(
        value,
        {
            "id",
            "character_id",
            "speaker_label",
            "voice_description",
            "text",
            "delivery",
        },
        "dialogue_line",
    )
    label = item["speaker_label"]
    voice_description = item["voice_description"]
    return DialogueLineProposal(
        character_id=(
            None
            if item["character_id"] is None
            else _id(item["character_id"], "dialogue_line.character_id")
        ),
        text=_plain_string(item["text"], "dialogue_line.text").strip(),
        delivery=_plain_string(item["delivery"], "dialogue_line.delivery").strip(),
        speaker_label=(
            None if label is None else _plain_string(label, "dialogue_line.speaker_label").strip()
        ),
        id=_optional_id(item["id"], "dialogue_line.id"),
        voice_description=(
            None
            if voice_description is None
            else _plain_string(voice_description, "dialogue_line.voice_description").strip()
        ),
    )


def _parse_boundary(value: object) -> SegmentBoundaryProposal:
    item = _exact_object(
        value,
        {"reason", "continuity_instruction"},
        "boundary_from_previous",
    )
    return SegmentBoundaryProposal(
        reason=_plain_string(item["reason"], "boundary.reason"),
        continuity_instruction=_plain_string(
            item["continuity_instruction"], "boundary.continuity_instruction"
        ).strip(),
    )


def _exact_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    require_fields(label, value, fields)
    return value


def _parse_character_looks(value: object) -> tuple[tuple[CharacterLook, ...], frozenset[str]]:
    """解析人类整卡回传的造型；id 为 null 的新造型由 Core 分配 ID，并返回这些新 ID。"""
    if not isinstance(value, list):
        raise ValueError("looks 必须是数组。")
    looks: list[CharacterLook] = []
    created: set[str] = set()
    for raw in value:
        item = _exact_object(raw, set(CHARACTER_LOOK_EDITOR_FIELDS), "looks")
        look_id = _optional_id(item["id"], "looks.id")
        if look_id is None:
            look_id = uuid4().hex
            created.add(look_id)
        looks.append(
            CharacterLook(
                id=look_id,
                name=_plain_string(item["name"], "looks.name").strip(),
                appearance=_plain_string(item["appearance"], "looks.appearance").strip(),
                usage=_plain_string(item["usage"], "looks.usage").strip(),
            )
        )
    return tuple(looks), frozenset(created)


def _parse_keyframe_character_references(
    value: object,
) -> tuple[KeyframeCharacterReference, ...]:
    if not isinstance(value, list):
        raise ValueError("character_references 必须是数组。")
    result = []
    for raw in value:
        item = _exact_object(raw, {"character_id", "look_id"}, "character_references")
        result.append(
            KeyframeCharacterReference(
                _id(item["character_id"], "character_references.character_id"),
                _optional_id(item["look_id"], "character_references.look_id"),
            )
        )
    return tuple(result)


def _is_active_run_command(body: bytes) -> bool:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value.get("name") in READ_OPERATIONS | {
        "keyframe.generate_batch",
        "keyframe.continue_batch",
        "location.generate_set",
        "generation.cancel",
        "generation.wait",
        "run.cancel",
        "run.get_status",
        *(
            f"{kind}.{action}_proposal"
            for kind in PROPOSAL_KINDS
            for action in ("request", "get", "submit", "reject", "cancel")
        ),
        "run.resume",
    }


def _parse_request(
    body: bytes, *, required: set[str], optional: set[str] | None = None
) -> dict[str, Any] | JsonResponse:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "请求体必须是合法 JSON。")
    problem = field_mismatch("请求", value, required, optional or ())
    if problem is not None:
        return _error(400, "invalid_request", problem)
    return value


def _parse_query(
    query: str, *, required: set[str], optional: set[str] | None = None
) -> dict[str, str]:
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("上传查询字段不合法。") from exc
    fields = dict(pairs)
    allowed = required | (optional or set())
    if len(fields) != len(pairs) or not required <= set(fields) or not set(fields) <= allowed:
        raise ValueError("上传请求包含缺失、重复或未声明的查询字段。")
    return fields


def _query_revision(request: dict[str, str]) -> int:
    try:
        value = int(request["expected_revision"])
    except ValueError as exc:
        raise ValueError("expected_revision 必须是正整数。") from exc
    if value < 1 or str(value) != request["expected_revision"]:
        raise ValueError("expected_revision 必须是正整数。")
    return value


def _query_filename(request: dict[str, str]) -> str | None:
    value = request.get("filename")
    if value is None:
        return None
    if not value.strip() or len(value) > 255 or any(ord(character) < 32 for character in value):
        raise ValueError("filename 不合法。")
    return value


def _required_media_type(value: str | None) -> str:
    if value is None or not value:
        raise ValueError("媒体上传缺少 Content-Type。")
    return value


def _parse_revision(request: dict[str, Any]) -> int | JsonResponse:
    value = request["expected_revision"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return _error(400, "invalid_request", "expected_revision 必须是正整数。")
    return value


def _required_revision(request: dict[str, Any]) -> int:
    value = request["expected_revision"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected_revision 必须是正整数。")
    return value


def _string(request: dict[str, Any], field: str) -> str:
    return _plain_string(request[field], field).strip()


def _plain_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串。")
    return value


def _id(value: object, field: str) -> str:
    result = _plain_string(value, field)
    if not re.fullmatch(r"[0-9a-f]{32}", result):
        raise ValueError(f"{field} 不合法。")
    return result


def _optional_id(value: object, field: str) -> str | None:
    return None if value is None else _id(value, field)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _plain_string(value, field).strip()


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是数字。")
    return float(value)


def _index(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} 必须是非负整数序号。")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须是整数。")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} 必须是布尔值。")
    return value


def _id_list(value: object, field: str = "reference_asset_ids") -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} 必须是数组。")
    result = tuple(_id(item, field) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} 不能重复。")
    return result


def _error(
    status: int,
    code: str,
    message: str,
    *,
    recoverable: bool = False,
    details: dict[str, object] | None = None,
    origin: str | None = None,
    state_changed: bool | str = False,
    retry_policy: str | None = None,
    automatic_retry_allowed: bool = False,
) -> JsonResponse:
    return JsonResponse(
        status,
        error_payload(
            code,
            message,
            recoverable=recoverable,
            details=details,
            origin=origin,
            state_changed=state_changed,
            retry_policy=retry_policy,
            automatic_retry_allowed=automatic_retry_allowed,
        ),
    )


def _revision_error(
    exc: Exception,
    *,
    expected_revision: int | None = None,
    current_revision: int | None = None,
) -> JsonResponse:
    expected = getattr(exc, "expected_revision", None)
    current = getattr(exc, "current_revision", None)
    if expected is None:
        expected = expected_revision
    if current is None:
        current = current_revision
    details = (
        {"expected_revision": expected, "current_revision": current}
        if expected is not None and current is not None
        else None
    )
    reason = getattr(exc, "conflict_reason", None)
    if details is not None and reason is not None:
        details["conflict_reason"] = reason
        details["conflicts"] = list(getattr(exc, "conflicts", ()))
    return _error(
        409,
        "revision_conflict",
        str(exc),
        recoverable=details is not None,
        details=details,
        automatic_retry_allowed=False,
    )
