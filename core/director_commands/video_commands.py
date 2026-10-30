from __future__ import annotations

import re
from dataclasses import dataclass

from core.model_providers.recipe import RecipeInputs
from storyrail_contracts.fields import require_fields

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class VideoInputsUpdate:
    """``inputs`` 按槽位与参数键合并进当前 recipe 输入簿：给出的槽位整体替换，未给出的保留。"""

    scope_scene_ids: tuple[str, ...]
    segment_id: str
    prompt_text: str
    inputs: RecipeInputs
    attach_dialogue_audio: bool = False


@dataclass(frozen=True, slots=True)
class VideoPromptUpdate:
    scope_scene_ids: tuple[str, ...]
    segment_id: str
    prompt_text: str


@dataclass(frozen=True, slots=True)
class VideoRecipeUpdate:
    scope_scene_ids: tuple[str, ...]
    segment_id: str
    recipe_id: str


@dataclass(frozen=True, slots=True)
class VideoSelectionClear:
    scope_scene_ids: tuple[str, ...]
    segment_id: str


def parse_video_prompt_update(value: object) -> VideoPromptUpdate:
    item = _exact(value, {"scope", "segment_id", "prompt_text"}, "video.set_prompt")
    return VideoPromptUpdate(
        _scope(item["scope"]), _id(item["segment_id"], "segment_id"), _prompt(item["prompt_text"])
    )


def parse_video_inputs_update(value: object) -> VideoInputsUpdate:
    required = {"scope", "segment_id", "prompt_text", "bindings", "params"}
    require_fields(
        "video.update_recipe_inputs.arguments", value, required, {"attach_dialogue_audio"}
    )
    attach = value.get("attach_dialogue_audio", False)
    if not isinstance(attach, bool):
        raise ValueError("attach_dialogue_audio 必须是布尔值。")
    return VideoInputsUpdate(
        _scope(value["scope"]),
        _id(value["segment_id"], "segment_id"),
        _prompt(value["prompt_text"]),
        RecipeInputs.from_json({"bindings": value["bindings"], "params": value["params"]}),
        attach,
    )


def parse_video_recipe_update(value: object) -> VideoRecipeUpdate:
    item = _exact(value, {"scope", "segment_id", "recipe_id"}, "video.set_recipe")
    recipe_id = item["recipe_id"]
    if not isinstance(recipe_id, str) or not 0 < len(recipe_id) <= 128:
        raise ValueError("recipe_id 必须是非空 recipe ID。")
    return VideoRecipeUpdate(
        _scope(item["scope"]), _id(item["segment_id"], "segment_id"), recipe_id
    )


def parse_video_selection_clear(value: object) -> VideoSelectionClear:
    item = _exact(value, {"scope", "segment_id"}, "video.clear_selection")
    return VideoSelectionClear(_scope(item["scope"]), _id(item["segment_id"], "segment_id"))


def _prompt(value: object) -> str:
    if not isinstance(value, str) or len(value) > 20_000:
        raise ValueError("video prompt_text 必须是至多 20000 字符的字符串。")
    return value.strip()


def _scope(value: object) -> tuple[str, ...]:
    item = _exact(value, {"scene_ids"}, "video scope")
    raw_ids = item["scene_ids"]
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("video scope.scene_ids 必须是非空 ID 数组。")
    result = tuple(_id(item_id, "scope.scene_ids") for item_id in raw_ids)
    if len(result) != len(set(result)):
        raise ValueError("video scope.scene_ids 不能重复。")
    return result


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    require_fields(f"{label}.arguments", value, keys)
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value


@dataclass(frozen=True, slots=True)
class VideoReferenceCharacter:
    character_id: str
    look_id: str | None


@dataclass(frozen=True, slots=True)
class VideoReferenceImageUpdate:
    scope_scene_ids: tuple[str, ...]
    segment_id: str
    slot_index: int
    prompt_text: str
    description: str
    visible_character_ids: tuple[str, ...]
    character_references: tuple[VideoReferenceCharacter, ...]
    reference_asset_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VideoReferenceImageSelection:
    scope_scene_ids: tuple[str, ...]
    segment_id: str
    slot_index: int
    asset_id: str | None
    description: str
    # 二选一的来源：Core 按当前项目把候选或关键帧已选图解析为 asset_id。
    generation_id: str | None = None
    keyframe_id: str | None = None


_SELECTION_SOURCES = ("asset_id", "generation_id", "keyframe_id")


def _reference_slot(value):
    if type(value) is not int or not 0 <= value < 4:
        raise ValueError("slot_index 必须为 0–3。")
    return value


def parse_video_reference_image_update(value):
    item = _exact(
        value,
        {
            "scope",
            "segment_id",
            "slot_index",
            "prompt_text",
            "description",
            "visible_character_ids",
            "character_references",
            "reference_asset_ids",
        },
        "video.save_reference_image_plan",
    )

    def ids(key):
        values = item[key]
        if not isinstance(values, list):
            raise ValueError(f"{key} 必须是数组。")
        return tuple(_id(value, key) for value in values)

    references = item["character_references"]
    if not isinstance(references, list):
        raise ValueError("character_references 必须是数组。")
    parsed = []
    for reference in references:
        fields = _exact(reference, {"character_id", "look_id"}, "character_reference")
        parsed.append(
            VideoReferenceCharacter(
                _id(fields["character_id"], "character_id"),
                None if fields["look_id"] is None else _id(fields["look_id"], "look_id"),
            )
        )
    if not isinstance(item["description"], str):
        raise ValueError("description 必须是字符串。")
    return VideoReferenceImageUpdate(
        _scope(item["scope"]),
        _id(item["segment_id"], "segment_id"),
        _reference_slot(item["slot_index"]),
        _prompt(item["prompt_text"]),
        item["description"],
        ids("visible_character_ids"),
        tuple(parsed),
        ids("reference_asset_ids"),
    )


def parse_video_reference_image_selection(value):
    """来源恰好一个：asset_id（null 表示移除）、generation_id 或 keyframe_id。"""
    sources = [key for key in _SELECTION_SOURCES if isinstance(value, dict) and key in value]
    if len(sources) != 1:
        raise ValueError(
            "video.select_reference_image 必须且只能给出 "
            "asset_id、generation_id、keyframe_id 之一。"
        )
    source = sources[0]
    item = _exact(
        value,
        {"scope", "segment_id", "slot_index", "description", source},
        "video.select_reference_image",
    )
    if not isinstance(item["description"], str):
        raise ValueError("description 必须是字符串。")
    raw = item[source]
    if raw is None and source != "asset_id":
        raise ValueError(f"{source} 不能为 null；移除图片请传 asset_id: null。")
    resolved = None if raw is None else _id(raw, source)
    return VideoReferenceImageSelection(
        _scope(item["scope"]),
        _id(item["segment_id"], "segment_id"),
        _reference_slot(item["slot_index"]),
        resolved if source == "asset_id" else None,
        item["description"],
        generation_id=resolved if source == "generation_id" else None,
        keyframe_id=resolved if source == "keyframe_id" else None,
    )
