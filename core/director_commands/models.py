from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

if TYPE_CHECKING:
    from core.structured_director.models import StructuredDirectorDocument

_ID = re.compile(r"[0-9a-f]{32}")
_COMMAND_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


class InvalidArgumentsError(ValueError):
    """The command shape is invalid before domain state is consulted."""


@dataclass(frozen=True, slots=True)
class DirectorCommand:
    name: str
    expected_revision: int
    idempotency_key: str
    arguments: dict[str, object]

    def __post_init__(self) -> None:
        if _COMMAND_NAME.fullmatch(self.name) is None:
            raise ValueError("Director command name 不合法。")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 1:
            raise ValueError("Director command expected_revision 不合法。")
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 200:
            raise ValueError("Director command idempotency_key 不合法。")
        if not isinstance(self.arguments, dict):
            raise ValueError("Director command arguments 必须是 object。")


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    command_id: str
    status: Literal["succeeded", "noop"]
    old_revision: int
    new_revision: int
    changed_ids: tuple[str, ...] = ()
    invalidated: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()
    decision_summary: str | None = None
    applied_summary: dict[str, int] | None = None
    assumptions: tuple[str, ...] = ()
    next_allowed_actions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    # 请求 revision 已落后、但期间变化与本次请求不相交而按当前文档执行时，记录原 revision。
    rebased_from_revision: int | None = None


class CommandNeedsUserInput(ValueError):
    def __init__(self, message: str, *, impact: dict[str, object]) -> None:
        super().__init__(message)
        self.impact = impact


@dataclass(frozen=True, slots=True)
class RepairOperation:
    entity_type: Literal["scene", "shot", "segment"]
    entity_id: str
    fields: dict[str, str | float | None]


@dataclass(frozen=True, slots=True)
class RepairPatch:
    run_id: str
    missing_command: str
    raw_user_request: str
    scope_scene_ids: tuple[str, ...]
    operations: tuple[RepairOperation, ...]


@dataclass(frozen=True, slots=True)
class RepairReceipt:
    gap_id: str
    missing_command: str
    normalized_operations: tuple[RepairOperation, ...]
    reverse_operations: tuple[RepairOperation, ...]


@dataclass(frozen=True, slots=True)
class SetKeyframeActivation:
    segment_id: str
    start_enabled: bool
    end_enabled: bool


@dataclass(frozen=True, slots=True)
class KeyframeCharacterReferenceSelection:
    """本帧为某个可见角色选择的造型；look_id 为 None 表示不提交该角色的图。"""

    character_id: str
    look_id: str | None


@dataclass(frozen=True, slots=True)
class UpdateKeyframeFields:
    keyframe_id: str
    prompt_text: str | None
    visible_character_ids: tuple[str, ...] | None
    # None 表示不修改；提交时整体替换本帧的角色参考图选择。
    character_references: tuple[KeyframeCharacterReferenceSelection, ...] | None = None
    # None 表示不修改；提交时整体替换本帧参考的其它 Keyframe（必须已有选中图）。
    reference_keyframe_ids: tuple[str, ...] | None = None
    # None 表示不修改；提交时整体替换本帧参考的地点库普通图片条目（必须已有选中图）。
    reference_location_image_ids: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SetKeyframeAuxReferences:
    segment_id: str
    asset_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BindKeyframeSlot:
    segment_id: str
    slot: Literal["start", "end"]
    keyframe_id: str


@dataclass(frozen=True, slots=True)
class ShareKeyframeBoundary:
    left_segment_id: str
    right_segment_id: str
    source_keyframe_id: str | None
    expected_adjacency: Literal["cross_shot", "intra_shot"] | None


@dataclass(frozen=True, slots=True)
class SplitKeyframeBoundary:
    left_segment_id: str
    right_segment_id: str
    clone_side: Literal["left_end", "right_start"]
    copy_selection: bool


@dataclass(frozen=True, slots=True)
class ClearKeyframeSelection:
    keyframe_id: str


@dataclass(frozen=True, slots=True)
class KeyframeCandidateSelection:
    """采用某个 Keyframe 的一条成功候选；Agent 与人类都可改选。"""

    keyframe_id: str
    generation_id: str


KeyframeOperation: TypeAlias = (
    SetKeyframeActivation
    | UpdateKeyframeFields
    | SetKeyframeAuxReferences
    | BindKeyframeSlot
    | ShareKeyframeBoundary
    | SplitKeyframeBoundary
    | ClearKeyframeSelection
)


def parse_director_command(value: object) -> DirectorCommand:
    item = _exact_object(
        value,
        {"name", "expected_revision", "idempotency_key", "arguments"},
        "command",
    )
    arguments = item["arguments"]
    if not isinstance(arguments, dict):
        raise ValueError("command.arguments 必须是 object。")
    return DirectorCommand(
        name=_string(item["name"], "command.name"),
        expected_revision=_integer(item["expected_revision"], "command.expected_revision"),
        idempotency_key=_string(item["idempotency_key"], "command.idempotency_key"),
        arguments=dict(arguments),
    )


def parse_keyframe_candidate_selection(value: object) -> KeyframeCandidateSelection:
    item = _exact_object(value, {"keyframe_id", "generation_id"}, "keyframe.select_candidate")
    return KeyframeCandidateSelection(
        _id(item["keyframe_id"], "keyframe_id"), _id(item["generation_id"], "generation_id")
    )


def parse_keyframe_operations(value: object) -> tuple[KeyframeOperation, ...]:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ValueError("keyframe operations 必须是包含 1 到 100 项的数组。")
    return tuple(_parse_keyframe_operation(item) for item in value)


def parse_repair_patch(value: object) -> RepairPatch:
    item = _exact_object(
        value,
        {
            "run_id",
            "reason_code",
            "missing_command",
            "raw_user_request",
            "scope",
            "operations",
        },
        "project.apply_repair_patch.arguments",
    )
    if _string(item["reason_code"], "reason_code") != "CAPABILITY_GAP":
        raise ValueError("repair reason_code 只允许 CAPABILITY_GAP。")
    run_id = _plain_string(item["run_id"], "run_id")
    if not run_id.strip() or len(run_id) > 200:
        raise ValueError("repair run_id 不合法。")
    missing_command = _string(item["missing_command"], "missing_command")
    if _COMMAND_NAME.fullmatch(missing_command) is None:
        raise ValueError("repair missing_command 不合法。")
    raw_user_request = _plain_string(item["raw_user_request"], "raw_user_request")
    if not raw_user_request.strip() or len(raw_user_request) > 20_000:
        raise ValueError("repair raw_user_request 不合法。")
    scope = _exact_object(item["scope"], {"scene_ids"}, "repair scope")
    scope_scene_ids = _id_list(scope["scene_ids"], "scope.scene_ids")
    if not scope_scene_ids:
        raise ValueError("repair scope 必须至少包含一个 Scene。")
    raw_operations = item["operations"]
    if not isinstance(raw_operations, list) or not 1 <= len(raw_operations) <= 50:
        raise ValueError("repair operations 必须包含 1 到 50 项。")
    operations = tuple(_parse_repair_operation(operation) for operation in raw_operations)
    if len({(operation.entity_type, operation.entity_id) for operation in operations}) != len(
        operations
    ):
        raise ValueError("repair operations 不能重复修改同一实体。")
    return RepairPatch(
        run_id,
        missing_command,
        raw_user_request,
        scope_scene_ids,
        operations,
    )


def _parse_repair_operation(value: object) -> RepairOperation:
    item = _exact_object(
        value,
        {"entity_type", "entity_id", "op", "fields"},
        "repair operation",
    )
    entity_type = _string(item["entity_type"], "entity_type")
    if entity_type not in {"scene", "shot", "segment"}:
        raise ValueError("repair entity_type 只允许 scene、shot 或 segment。")
    if _string(item["op"], "op") != "set_fields":
        raise ValueError("repair operation 只允许 set_fields。")
    fields = item["fields"]
    if not isinstance(fields, dict) or not fields:
        raise ValueError("repair fields 必须是非空 object。")
    allowed = {
        "scene": {"title", "summary", "setting"},
        "shot": {
            "composition",
            "camera_movement",
            "action",
            "audio_direction",
            "transition_in",
        },
        "segment": {"duration_estimate_seconds", "action"},
    }[entity_type]
    if not set(fields) <= allowed:
        raise ValueError(f"repair {entity_type} fields 包含未声明字段。")
    normalized: dict[str, str | float | None] = {}
    for name, field_value in fields.items():
        if name == "duration_estimate_seconds":
            if isinstance(field_value, bool) or not isinstance(field_value, (int, float)):
                raise ValueError("duration_estimate_seconds 必须是数字。")
            normalized[name] = float(field_value)
        elif name == "transition_in" and field_value is None:
            normalized[name] = None
        else:
            normalized[name] = _plain_string(field_value, name)
    return RepairOperation(
        entity_type,
        _id(item["entity_id"], "entity_id"),
        normalized,
    )


def _parse_character_reference_selections(
    value: object,
) -> tuple[KeyframeCharacterReferenceSelection, ...]:
    if not isinstance(value, list):
        raise ValueError("character_references 必须是数组。")
    selections = []
    for raw in value:
        item = _exact_object(raw, {"character_id", "look_id"}, "character_references")
        selections.append(
            KeyframeCharacterReferenceSelection(
                _id(item["character_id"], "character_references.character_id"),
                None
                if item["look_id"] is None
                else _id(item["look_id"], "character_references.look_id"),
            )
        )
    return tuple(selections)


def _parse_keyframe_operation(value: object) -> KeyframeOperation:
    if not isinstance(value, dict) or not isinstance(value.get("op"), str):
        raise ValueError("keyframe operation 必须包含字符串 op。")
    op = value["op"]
    if op == "set_activation":
        item = _exact_object(value, {"op", "segment_id", "start_enabled", "end_enabled"}, op)
        return SetKeyframeActivation(
            _id(item["segment_id"], "segment_id"),
            _boolean(item["start_enabled"], "start_enabled"),
            _boolean(item["end_enabled"], "end_enabled"),
        )
    if op == "update_frame_fields":
        item = _exact_object(value, {"op", "keyframe_id", "fields"}, op)
        fields = item["fields"]
        if not isinstance(fields, dict) or not fields:
            raise ValueError("update_frame_fields.fields 必须是非空 object。")
        allowed = {
            "prompt_text",
            "visible_character_ids",
            "character_references",
            "reference_keyframe_ids",
            "reference_location_image_ids",
        }
        if not set(fields) <= allowed:
            raise ValueError("update_frame_fields.fields 包含未声明字段。")
        prompt = fields.get("prompt_text")
        characters = fields.get("visible_character_ids")
        return UpdateKeyframeFields(
            keyframe_id=_id(item["keyframe_id"], "keyframe_id"),
            prompt_text=(
                None if "prompt_text" not in fields else _plain_string(prompt, "prompt_text")
            ),
            visible_character_ids=(
                None
                if "visible_character_ids" not in fields
                else _id_list(characters, "visible_character_ids")
            ),
            character_references=(
                None
                if "character_references" not in fields
                else _parse_character_reference_selections(fields["character_references"])
            ),
            reference_keyframe_ids=(
                None
                if "reference_keyframe_ids" not in fields
                else _id_list(fields["reference_keyframe_ids"], "reference_keyframe_ids")
            ),
            reference_location_image_ids=(
                None
                if "reference_location_image_ids" not in fields
                else _id_list(
                    fields["reference_location_image_ids"], "reference_location_image_ids"
                )
            ),
        )
    if op == "set_aux_references":
        item = _exact_object(value, {"op", "segment_id", "asset_ids"}, op)
        return SetKeyframeAuxReferences(
            _id(item["segment_id"], "segment_id"),
            _id_list(item["asset_ids"], "asset_ids"),
        )
    if op == "bind_slot":
        item = _exact_object(value, {"op", "segment_id", "slot", "keyframe_id"}, op)
        slot = _string(item["slot"], "slot")
        if slot not in {"start", "end"}:
            raise ValueError("bind_slot.slot 只允许 start 或 end。")
        return BindKeyframeSlot(
            _id(item["segment_id"], "segment_id"),
            slot,
            _id(item["keyframe_id"], "keyframe_id"),
        )
    if op == "share_boundary":
        required = {"op", "left_segment_id", "right_segment_id"}
        item = _exact_object(
            value,
            required,
            op,
            optional={"source_keyframe_id", "expected_adjacency"},
        )
        adjacency = item.get("expected_adjacency")
        if adjacency is not None and adjacency not in {"cross_shot", "intra_shot"}:
            raise ValueError("share_boundary.expected_adjacency 不合法。")
        source = item.get("source_keyframe_id")
        return ShareKeyframeBoundary(
            _id(item["left_segment_id"], "left_segment_id"),
            _id(item["right_segment_id"], "right_segment_id"),
            None if source is None else _id(source, "source_keyframe_id"),
            adjacency,
        )
    if op == "split_boundary":
        required = {"op", "left_segment_id", "right_segment_id", "clone_side"}
        item = _exact_object(value, required, op, optional={"copy_selection"})
        side = _string(item["clone_side"], "clone_side")
        if side not in {"left_end", "right_start"}:
            raise ValueError("split_boundary.clone_side 不合法。")
        copy_selection = item.get("copy_selection", False)
        return SplitKeyframeBoundary(
            _id(item["left_segment_id"], "left_segment_id"),
            _id(item["right_segment_id"], "right_segment_id"),
            side,
            _boolean(copy_selection, "copy_selection"),
        )
    if op == "clear_selection":
        item = _exact_object(value, {"op", "keyframe_id"}, op)
        return ClearKeyframeSelection(_id(item["keyframe_id"], "keyframe_id"))
    raise ValueError(f"未知的 keyframe operation：{op}。")


def _exact_object(
    value: object,
    required: set[str],
    label: str,
    *,
    optional: set[str] = frozenset(),
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or not set(value) <= (required | optional)
    ):
        raise ValueError(f"{label} 包含缺失或未声明字段。")
    return value


def _id(value: object, label: str) -> str:
    value = _string(value, label)
    if _ID.fullmatch(value) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value


def _id_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组。")
    result = tuple(_id(item, label) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} 不能重复。")
    return result


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()


def _plain_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串。")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} 必须是整数。")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} 必须是布尔值。")
    return value


@dataclass(frozen=True, slots=True)
class CommandExecution:
    document: StructuredDirectorDocument
    receipt: CommandReceipt
    data: dict[str, object] | None = None
    repair_receipt: RepairReceipt | None = None
    application_request_id: str | None = None
    replay: bool = False


def director_command_id(command: DirectorCommand) -> str:
    canonical = json.dumps(
        {
            "name": command.name,
            "idempotency_key": command.idempotency_key,
            "arguments": command.arguments,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
