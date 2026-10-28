from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from core.director_proposals.wire_fields import (
    BOUNDARY_FIELDS,
    DIALOGUE_FIELDS,
    SEGMENT_FIELDS,
    SHOT_CONTENT_FIELDS,
    SHOT_FIELDS,
)
from core.model_providers.recipe import RecipeParams

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class ScriptDialogueInput:
    character_id: str | None
    text: str
    delivery: str
    speaker_label: str | None = None
    id: str | None = None
    voice_description: str | None = None


@dataclass(frozen=True, slots=True)
class ScriptBoundaryInput:
    reason: str
    continuity_instruction: str


@dataclass(frozen=True, slots=True)
class ScriptSegmentInput:
    """已有 Scene 内的 Segment：用已有 Shot 的 ID 表达覆盖。"""

    shot_ids: tuple[str, ...]
    duration_estimate_seconds: float
    action: str
    dialogue_lines: tuple[ScriptDialogueInput, ...]
    boundary_from_previous: ScriptBoundaryInput | None


@dataclass(frozen=True, slots=True)
class ScriptNewSegmentInput:
    """随新 Scene / 新 Shot 一起创建的 Segment：用本 Scene 新 shots 数组的序号表达覆盖。"""

    shot_indexes: tuple[int, ...]
    duration_estimate_seconds: float
    action: str
    dialogue_lines: tuple[ScriptDialogueInput, ...]
    boundary_from_previous: ScriptBoundaryInput | None


@dataclass(frozen=True, slots=True)
class ScriptShotInput:
    visible_character_ids: tuple[str, ...]
    composition: str
    camera_movement: str
    action: str
    audio_direction: str
    transition_in: str | None


@dataclass(frozen=True, slots=True)
class ScriptNarrationTrackInput:
    text: str
    seed: int
    recipe_params: RecipeParams


@dataclass(frozen=True, slots=True)
class ScriptNarrationCueInput:
    """新增 Scene 的双语旁白：zh 与 en 两条轨道。"""

    zh: ScriptNarrationTrackInput
    en: ScriptNarrationTrackInput


@dataclass(frozen=True, slots=True)
class ScriptSceneInput:
    title: str
    summary: str
    setting: str
    driver: Literal["drama", "narration"]
    shots: tuple[ScriptShotInput, ...]
    segments: tuple[ScriptNewSegmentInput, ...]
    narration_cue: ScriptNarrationCueInput | None


@dataclass(frozen=True, slots=True)
class ScriptOperation:
    op: str
    scene_id: str | None = None
    shot_id: str | None = None
    segment_id: str | None = None
    after_id: str | None = None
    fields: dict[str, object] | None = None
    shot: ScriptShotInput | None = None
    segment: ScriptSegmentInput | None = None
    new_segment: ScriptNewSegmentInput | None = None
    attach_to_segment_id: str | None = None
    first: ScriptSegmentInput | None = None
    second: ScriptSegmentInput | None = None
    preserve_id: Literal["first", "second", "left", "right"] | None = None
    right_segment_id: str | None = None
    right_scene_id: str | None = None
    scene: ScriptSceneInput | None = None


# 与 Scene 模型长度上限一致；Core 模型仍是最终校验。
_SCENE_TEXT_LIMITS = {"title": 300, "summary": 4_000, "setting": 4_000}
_SCENE_OPTIONAL_FIELDS = {"driver", "shots", "segments", "narration_cue"}


@dataclass(frozen=True, slots=True)
class ScriptOperationsPatch:
    scope_scene_ids: tuple[str, ...]
    operations: tuple[ScriptOperation, ...]


def parse_script_operations_patch(value: object) -> ScriptOperationsPatch:
    root = _exact(value, {"scope", "operations"}, "script.apply_operations.arguments")
    scope = _exact(root["scope"], {"scene_ids"}, "script scope")
    scene_ids = _id_list(scope["scene_ids"], "scope.scene_ids")
    if not scene_ids:
        raise ValueError("script scope 必须至少包含一个 Scene。")
    raw_operations = root["operations"]
    if not isinstance(raw_operations, list) or not 1 <= len(raw_operations) <= 100:
        raise ValueError("script operations 必须包含 1 到 100 项。")
    return ScriptOperationsPatch(
        scene_ids,
        tuple(_parse_operation(item) for item in raw_operations),
    )


def _parse_operation(value: object) -> ScriptOperation:
    if not isinstance(value, dict) or not isinstance(value.get("op"), str):
        raise ValueError("script operation 必须包含字符串 op。")
    op = value["op"]
    if op == "update_scene_fields":
        item = _exact(value, {"op", "scene_id", "fields"}, op)
        return ScriptOperation(
            op, scene_id=_id(item["scene_id"], "scene_id"), fields=_scene_fields(item["fields"])
        )
    if op == "insert_scene":
        item = _exact(value, {"op", "after_scene_id", "scene"}, op)
        return ScriptOperation(
            op,
            after_id=_optional_id(item["after_scene_id"], "after_scene_id"),
            scene=_scene(item["scene"]),
        )
    if op == "move_scene":
        item = _exact(value, {"op", "scene_id", "after_scene_id"}, op)
        return ScriptOperation(
            op,
            scene_id=_id(item["scene_id"], "scene_id"),
            after_id=_optional_id(item["after_scene_id"], "after_scene_id"),
        )
    if op == "delete_scene":
        item = _exact(value, {"op", "scene_id"}, op)
        return ScriptOperation(op, scene_id=_id(item["scene_id"], "scene_id"))
    if op == "update_shot_fields":
        item = _exact(value, {"op", "shot_id", "fields"}, op)
        return ScriptOperation(
            op, shot_id=_id(item["shot_id"], "shot_id"), fields=_shot_fields(item["fields"])
        )
    if op == "insert_shot":
        required = {"op", "scene_id", "after_shot_id", "shot"}
        optional = {"attach_to_segment_id", "new_segment"}
        item = _exact(value, required | (optional & set(value)), op)
        attach_to_segment_id = _optional_id(
            item.get("attach_to_segment_id"), "attach_to_segment_id"
        )
        raw_new_segment = item.get("new_segment")
        new_segment = None if raw_new_segment is None else _new_segment(raw_new_segment)
        if (attach_to_segment_id is None) == (new_segment is None):
            raise ValueError(
                "insert_shot 必须且只能给出 attach_to_segment_id 或 new_segment 之一。"
            )
        return ScriptOperation(
            op,
            scene_id=_id(item["scene_id"], "scene_id"),
            after_id=_optional_id(item["after_shot_id"], "after_shot_id"),
            shot=_shot(item["shot"]),
            attach_to_segment_id=attach_to_segment_id,
            new_segment=new_segment,
        )
    if op == "delete_shot":
        item = _exact(value, {"op", "scene_id", "shot_id"}, op)
        return ScriptOperation(
            op,
            scene_id=_id(item["scene_id"], "scene_id"),
            shot_id=_id(item["shot_id"], "shot_id"),
        )
    if op == "update_segment_fields":
        item = _exact(value, {"op", "segment_id", "fields"}, op)
        return ScriptOperation(
            op,
            segment_id=_id(item["segment_id"], "segment_id"),
            fields=_segment_fields(item["fields"]),
        )
    if op == "insert_segment":
        item = _exact(value, {"op", "scene_id", "after_segment_id", "segment"}, op)
        return ScriptOperation(
            op,
            scene_id=_id(item["scene_id"], "scene_id"),
            after_id=_optional_id(item["after_segment_id"], "after_segment_id"),
            segment=_segment(item["segment"]),
        )
    if op in {"move_segment", "delete_segment"}:
        keys = {"op", "scene_id", "segment_id"} | (
            {"after_segment_id"} if op == "move_segment" else set()
        )
        item = _exact(value, keys, op)
        return ScriptOperation(
            op,
            scene_id=_id(item["scene_id"], "scene_id"),
            segment_id=_id(item["segment_id"], "segment_id"),
            after_id=_optional_id(item["after_segment_id"], "after_segment_id")
            if op == "move_segment"
            else None,
        )
    if op == "split_segment":
        item = _exact(value, {"op", "segment_id", "preserve_id", "first", "second"}, op)
        preserve_id = _string(item["preserve_id"], "preserve_id")
        if preserve_id not in {"first", "second"}:
            raise ValueError("split_segment.preserve_id 只允许 first 或 second。")
        return ScriptOperation(
            op,
            segment_id=_id(item["segment_id"], "segment_id"),
            first=_segment(item["first"]),
            second=_segment(item["second"]),
            preserve_id=preserve_id,
        )
    if op == "merge_adjacent_segments":
        item = _exact(
            value,
            {"op", "left_segment_id", "right_segment_id", "preserve_id", "merged"},
            op,
        )
        preserve_id = _string(item["preserve_id"], "preserve_id")
        if preserve_id not in {"left", "right"}:
            raise ValueError("merge_adjacent_segments.preserve_id 只允许 left 或 right。")
        return ScriptOperation(
            op,
            segment_id=_id(item["left_segment_id"], "left_segment_id"),
            right_segment_id=_id(item["right_segment_id"], "right_segment_id"),
            segment=_segment(item["merged"]),
            preserve_id=preserve_id,
        )
    if op == "merge_adjacent_scenes":
        item = _exact(value, {"op", "left_scene_id", "right_scene_id"}, op)
        return ScriptOperation(
            op,
            scene_id=_id(item["left_scene_id"], "left_scene_id"),
            right_scene_id=_id(item["right_scene_id"], "right_scene_id"),
        )
    raise ValueError(f"未知的 script operation：{op}。")


def _scene_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError("update_scene_fields.fields 必须是非空 object。")
    if not set(value) <= _SCENE_TEXT_LIMITS.keys():
        raise ValueError("update_scene_fields.fields 包含未声明字段。")
    return {name: _scene_text(item, name) for name, item in value.items()}


def _scene(value: object) -> ScriptSceneInput:
    if not isinstance(value, dict):
        raise ValueError("insert_scene.scene 必须是 object。")
    required = set(_SCENE_TEXT_LIMITS)
    if not required <= set(value) <= required | _SCENE_OPTIONAL_FIELDS:
        raise ValueError("insert_scene.scene 包含缺失或未声明字段。")
    driver = value.get("driver", "drama")
    if driver not in {"drama", "narration"}:
        raise ValueError("insert_scene.scene.driver 只允许 drama 或 narration。")
    shots = value.get("shots", [])
    if not isinstance(shots, list):
        raise ValueError("insert_scene.scene.shots 必须是数组。")
    raw_segments = value.get("segments", [])
    if not isinstance(raw_segments, list):
        raise ValueError("insert_scene.scene.segments 必须是数组。")
    segments = tuple(_new_segment(segment) for segment in raw_segments)
    raw_cue = value.get("narration_cue")
    cue = None if raw_cue is None else _narration_cue(raw_cue)
    if driver == "narration" and (cue is None or shots or segments):
        raise ValueError(
            "新增 Narration Scene 必须提供 narration_cue，且先完成 TTS 选择再规划 Shot。"
        )
    if driver == "drama" and cue is not None:
        raise ValueError(
            "新增 Drama Scene 不能提供 narration_cue；需要旁白请使用 Narration Scene。"
        )
    return ScriptSceneInput(
        _scene_text(value["title"], "title"),
        _scene_text(value["summary"], "summary"),
        _scene_text(value["setting"], "setting"),
        driver,
        tuple(_shot(shot) for shot in shots),
        segments,
        cue,
    )


def _scene_text(value: object, name: str) -> str:
    result = _string(value, f"scene.{name}")
    if len(result) > _SCENE_TEXT_LIMITS[name]:
        raise ValueError(f"scene.{name} 不能超过 {_SCENE_TEXT_LIMITS[name]} 字符。")
    return result


def _narration_cue(value: object) -> ScriptNarrationCueInput:
    if not isinstance(value, dict) or set(value) != {"zh", "en"}:
        raise ValueError("narration_cue 必须且只能包含 zh 与 en 两种语言。")
    return ScriptNarrationCueInput(
        _narration_track(value["zh"], "narration_cue.zh"),
        _narration_track(value["en"], "narration_cue.en"),
    )


def _narration_track(value: object, label: str) -> ScriptNarrationTrackInput:
    if not isinstance(value, dict) or not {"text", "seed"} <= set(value) <= {
        "text",
        "seed",
        "recipe_params",
    }:
        raise ValueError(f"{label} 包含缺失或未声明字段。")
    recipe_params = RecipeParams.from_json(value.get("recipe_params", {}), f"{label}.recipe_params")
    seed = value["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise ValueError(f"{label}.seed 不合法。")
    return ScriptNarrationTrackInput(
        _string(value["text"], f"{label}.text"),
        seed,
        recipe_params,
    )


def _shot_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError("update_shot_fields.fields 必须是非空 object。")
    allowed = SHOT_CONTENT_FIELDS
    if not set(value) <= allowed:
        raise ValueError("update_shot_fields.fields 包含未声明字段。")
    result: dict[str, object] = {}
    for name, item in value.items():
        if name == "visible_character_ids":
            result[name] = _id_list(item, name)
        elif name == "transition_in":
            result[name] = None if item is None else _string(item, name)
        else:
            result[name] = _string(item, name, allow_empty=name == "audio_direction")
    return result


def _segment_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError("update_segment_fields.fields 必须是非空 object。")
    allowed = SEGMENT_FIELDS
    if not set(value) <= allowed:
        raise ValueError("update_segment_fields.fields 包含未声明字段。")
    result: dict[str, object] = {}
    for name, item in value.items():
        if name == "shot_ids":
            shot_ids = _id_list(item, name)
            if not shot_ids:
                raise ValueError("shot_ids 必须至少包含一个 Shot。")
            result[name] = shot_ids
        elif name == "duration_estimate_seconds":
            result[name] = _duration(item)
        elif name == "action":
            result[name] = _string(item, name)
        elif name == "dialogue_lines":
            result[name] = _dialogues(item)
        else:
            result[name] = _boundary(item)
    return result


def _shot(value: object) -> ScriptShotInput:
    item = _exact(
        value,
        SHOT_FIELDS,
        "shot",
    )
    return ScriptShotInput(
        _id_list(item["visible_character_ids"], "visible_character_ids"),
        _string(item["composition"], "composition"),
        _string(item["camera_movement"], "camera_movement"),
        _string(item["action"], "action"),
        _string(item["audio_direction"], "audio_direction", allow_empty=True),
        None if item["transition_in"] is None else _string(item["transition_in"], "transition_in"),
    )


def _segment(value: object) -> ScriptSegmentInput:
    item = _exact(
        value,
        SEGMENT_FIELDS,
        "segment",
    )
    shot_ids = _id_list(item["shot_ids"], "shot_ids")
    if not shot_ids:
        raise ValueError("Segment 必须至少覆盖一个 Shot。")
    return ScriptSegmentInput(
        shot_ids,
        _duration(item["duration_estimate_seconds"]),
        _string(item["action"], "action"),
        _dialogues(item["dialogue_lines"]),
        _boundary(item["boundary_from_previous"]),
    )


def _new_segment(value: object) -> ScriptNewSegmentInput:
    fields = (SEGMENT_FIELDS - {"shot_ids"}) | {"shot_indexes"}
    item = _exact(value, fields, "new_segment")
    shot_indexes = item["shot_indexes"]
    if not isinstance(shot_indexes, list) or not shot_indexes:
        raise ValueError("Segment 必须至少覆盖一个 Shot。")
    return ScriptNewSegmentInput(
        tuple(_index(value, "shot_indexes") for value in shot_indexes),
        _duration(item["duration_estimate_seconds"]),
        _string(item["action"], "action"),
        _dialogues(item["dialogue_lines"]),
        _boundary(item["boundary_from_previous"]),
    )


def _dialogues(value: object) -> tuple[ScriptDialogueInput, ...]:
    if not isinstance(value, list):
        raise ValueError("dialogue_lines 必须是数组。")
    result = []
    for value_item in value:
        if isinstance(value_item, dict):
            value_item = {
                **value_item,
                "speaker_label": value_item.get("speaker_label"),
                "id": value_item.get("id"),
                "voice_description": value_item.get("voice_description"),
            }
        item = _exact(value_item, DIALOGUE_FIELDS, "dialogue_line")
        character_id, label = item["character_id"], item["speaker_label"]
        if (character_id is None) == (label is None):
            raise ValueError("dialogue_line 必须且只能提供 character_id 或 speaker_label 之一。")
        result.append(
            ScriptDialogueInput(
                None if character_id is None else _id(character_id, "character_id"),
                _string(item["text"], "text"),
                _string(item["delivery"], "delivery", allow_empty=True),
                None if label is None else _string(label, "speaker_label"),
                _optional_id(item["id"], "dialogue_line.id"),
                (
                    None
                    if item["voice_description"] is None
                    else _string(item["voice_description"], "voice_description")
                ),
            )
        )
    return tuple(result)


def _boundary(value: object) -> ScriptBoundaryInput | None:
    if value is None:
        return None
    item = _exact(value, BOUNDARY_FIELDS, "boundary_from_previous")
    reason = _string(item["reason"], "reason")
    if reason not in {"model_constraint", "continuity_anchor", "control_boundary", "failure_cost"}:
        raise ValueError(
            "boundary.reason 只允许 model_constraint、continuity_anchor、"
            "control_boundary 或 failure_cost。"
        )
    return ScriptBoundaryInput(
        reason, _string(item["continuity_instruction"], "continuity_instruction")
    )


def _duration(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0.2
    ):
        raise ValueError("duration_estimate_seconds 必须是不短于 0.2 秒的有限数值。")
    return float(value)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} 包含缺失或未声明字段。")
    return value


def _string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()


def _id(value: object, label: str) -> str:
    result = _string(value, label)
    if _ID.fullmatch(result) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return result


def _optional_id(value: object, label: str) -> str | None:
    return None if value is None else _id(value, label)


def _index(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} 必须是非负整数序号。")
    return value


def _id_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 ID 数组。")
    result = tuple(_id(item, label) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} 不能重复。")
    return result
