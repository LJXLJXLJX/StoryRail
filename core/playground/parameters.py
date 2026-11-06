"""Playground 能力的参数契约：结构校验、规范化、输入推导与 Ref2VA 标签映射。

L1 纯结构层：不访问 Asset，不 import store、service 或 capabilities。
"""

from __future__ import annotations

import json
from math import isfinite
from typing import Any

from core.audio_effects.presets import preset_names
from core.model_providers.contracts import (
    PANO_HFOV_RANGE,
    PANO_PITCH_RANGE,
    PANO_YAW_RANGE,
    validate_pano_view_geometry,
)
from core.model_providers.manifest import Recipe, Role
from core.model_providers.recipe import (
    SlotBinding,
    binding_labels,
    parse_recipe_wire,
    recipe_wire_value,
    slot_wire_key,
)

from .models import PlaygroundCapability, PlaygroundRun, canonical_json

_ID_SCHEMA: dict[str, object] = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
_ASPECT_SCHEMA: dict[str, object] = {"type": "string", "enum": ["16:9", "9:16", "2:1"]}
_SEED_SCHEMA: dict[str, object] = {
    "type": "integer",
    "minimum": 0,
    "maximum": 2**63 - 1,
    "description": "随机种子；Core 不会自动递增。",
}
_NULLABLE_NUMBER: dict[str, object] = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_NULLABLE_ID: dict[str, object] = {"anyOf": [_ID_SCHEMA, {"type": "null"}]}
_NULLABLE_TEXT: dict[str, object] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

_DURATION_SCHEMA: dict[str, object] = {
    "type": "number",
    "minimum": 0.2,
    "description": "视频时长（秒），不设上限；超过 15 秒可能 OOM。",
}
_GAIN_SCHEMA: dict[str, object] = {"type": "number", "minimum": -100, "maximum": 24}
_DESCRIBED_IMAGE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asset_id", "description"],
    "properties": {
        "asset_id": _ID_SCHEMA,
        "description": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "description": "这张图在提示词里的作用。",
        },
    },
}

_PRESET_NAMES = preset_names()

# 每个能力的 wire 键与 JSON Schema 属性；解析器与 schema 共用同一份声明，
# 保证「schema 键集合 == 解析器接受的键集合」不会漂移。
_SPECS: dict[PlaygroundCapability, tuple[tuple[str, dict[str, object]], ...]] = {
    PlaygroundCapability.VIDEO_EXTRACT_FRAME: (
        ("video_asset_id", {**_ID_SCHEMA, "description": "来源 MP4。"}),
        (
            "frame_index",
            {
                "type": "integer",
                "minimum": 0,
                "description": "0 到 N-1 的帧号；N 由 Core 从 MP4 读出。",
            },
        ),
    ),
    PlaygroundCapability.IMAGE_PANO_VIEW: (
        (
            "image_asset_id",
            {**_ID_SCHEMA, "description": "2:1 等距柱状全景 PNG/JPEG，宽 1024–16384。"},
        ),
        (
            "yaw_deg",
            {
                "type": "number",
                "minimum": PANO_YAW_RANGE[0],
                "exclusiveMaximum": PANO_YAW_RANGE[1],
                "description": "水平朝向（度），全景正中为 0，顺时针（向右）为正。",
            },
        ),
        (
            "pitch_deg",
            {
                "type": "number",
                "minimum": PANO_PITCH_RANGE[0],
                "maximum": PANO_PITCH_RANGE[1],
                "description": "俯仰（度），抬头为正。",
            },
        ),
        (
            "hfov_deg",
            {
                "type": "number",
                "minimum": PANO_HFOV_RANGE[0],
                "maximum": PANO_HFOV_RANGE[1],
                "description": "输出水平视场角（度）。",
            },
        ),
        ("aspect_ratio", {**_ASPECT_SCHEMA, "description": "输出画幅。"}),
    ),
    PlaygroundCapability.AUDIO_REMIX: (
        ("video_asset_id", {**_ID_SCHEMA, "description": "来源 MP4。"}),
        ("voice_asset_id", {**_ID_SCHEMA, "description": "人声 WAV。"}),
        ("background_asset_id", {**_ID_SCHEMA, "description": "背景声 WAV。"}),
        ("voice_gain_db", {**_GAIN_SCHEMA, "description": "人声音量增益。"}),
        ("background_gain_db", {**_GAIN_SCHEMA, "description": "背景声音量增益。"}),
        ("voice_gain_start_seconds", _NULLABLE_NUMBER),
        ("voice_gain_end_seconds", _NULLABLE_NUMBER),
        ("background_gain_start_seconds", _NULLABLE_NUMBER),
        ("background_gain_end_seconds", _NULLABLE_NUMBER),
    ),
    PlaygroundCapability.AUDIO_EFFECT: (
        ("audio_asset_id", {**_ID_SCHEMA, "description": "要处理的 WAV。"}),
        (
            "preset",
            {
                "type": "string",
                "enum": list(_PRESET_NAMES),
                "description": "Core 内置的电台 preset。",
            },
        ),
        (
            "strength",
            {"type": "number", "minimum": 0, "maximum": 1, "description": "效果强度。"},
        ),
        ("seed", _SEED_SCHEMA),
        ("start_seconds", _NULLABLE_NUMBER),
        ("end_seconds", _NULLABLE_NUMBER),
    ),
    PlaygroundCapability.AUDIO_TRIM: (
        ("audio_asset_id", {**_ID_SCHEMA, "description": "要截取的 WAV。"}),
        ("start_seconds", {"type": "number", "minimum": 0, "description": "截取起点。"}),
        ("end_seconds", {"type": "number", "exclusiveMinimum": 0, "description": "截取终点。"}),
    ),
}

PARAMETER_KEYS: dict[PlaygroundCapability, tuple[str, ...]] = {
    capability: tuple(key for key, _schema in fields) for capability, fields in _SPECS.items()
}

PARAMETER_SCHEMAS: dict[PlaygroundCapability, dict[str, object]] = {
    capability: {
        "type": "object",
        "additionalProperties": False,
        "required": list(keys),
        "properties": {key: schema for key, schema in fields},
    }
    for capability, fields in _SPECS.items()
    for keys in (PARAMETER_KEYS[capability],)
}

_ASSET_LIST_KEYS = frozenset({"additional_images", "reference_audios", "reference_videos"})

_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


def _capability(value: object) -> PlaygroundCapability:
    if isinstance(value, PlaygroundCapability):
        return value
    try:
        return PlaygroundCapability(value)
    except ValueError as exc:
        raise ValueError(f"不支持的 capability：{value}") from exc


def _exact_keys(capability: PlaygroundCapability, value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("parameters 必须是 JSON 对象。")
    expected = set(PARAMETER_KEYS[capability])
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"缺少 {', '.join(missing)}")
        if extra:
            detail.append(f"多出 {', '.join(extra)}")
        raise ValueError(f"{capability.value} 的参数键不匹配：{'；'.join(detail)}。")
    return dict(value)


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是文本。")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} 必须是 1 到 {maximum} 字符。")
    return normalized


def _nullable_text(value: object, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, label, maximum)


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} 必须是有限数字。")
    return float(value)


def _nullable_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    return _finite_number(value, label)


def _seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("seed 必须是整数。")
    if not 0 <= value <= 2**63 - 1:
        raise ValueError("seed 超出范围。")
    return value


def _asset_id(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} 必须是 32 位十六进制 Asset ID。")
    return value


def _nullable_asset_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _asset_id(value, label)


def _asset_id_list(value: object, label: str, maximum: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组。")
    if len(value) > maximum:
        raise ValueError(f"{label} 最多 {maximum} 项。")
    identifiers = [_asset_id(item, label) for item in value]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{label} 不能重复。")
    return identifiers


def _described_assets(value: object, label: str, maximum: int) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组。")
    if len(value) > maximum:
        raise ValueError(f"{label} 最多 {maximum} 项。")
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"asset_id", "description"}:
            raise ValueError(f"{label} 的每一项必须只有 asset_id 和 description。")
        asset_id = _asset_id(entry["asset_id"], f"{label}.asset_id")
        if asset_id in seen:
            raise ValueError(f"{label} 不能重复引用同一个 Asset。")
        seen.add(asset_id)
        items.append(
            {
                "asset_id": asset_id,
                "description": _text(entry["description"], f"{label}.description", 2000),
            }
        )
    return items


def _aspect_ratio(value: object, label: str) -> str:
    if value not in {"16:9", "9:16", "2:1"}:
        raise ValueError(f"{label} 只允许 16:9、9:16 或 2:1。")
    return value


def _duration(value: object, label: str) -> float:
    number = _finite_number(value, label)
    if number < 0.2:
        raise ValueError(f"{label} 不能短于 0.2 秒。")
    return number


def _window(start: object, end: object, label: str) -> tuple[float | None, float | None]:
    if (start is None) != (end is None):
        raise ValueError(f"{label}的开始和结束时间必须同时提供或同时省略。")
    if start is None:
        return None, None
    begin = _finite_number(start, f"{label}开始时间")
    finish = _finite_number(end, f"{label}结束时间")
    if begin < 0 or finish <= begin:
        raise ValueError(f"{label}的时间范围不合法。")
    return begin, finish


def _parse_video_extract_frame(value: object) -> dict[str, object]:
    raw = _exact_keys(PlaygroundCapability.VIDEO_EXTRACT_FRAME, value)
    index = raw["frame_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("frame_index 必须是非负整数。")
    return {
        "video_asset_id": _asset_id(raw["video_asset_id"], "video_asset_id"),
        "frame_index": index,
    }


def _parse_image_pano_view(value: object) -> dict[str, object]:
    raw = _exact_keys(PlaygroundCapability.IMAGE_PANO_VIEW, value)
    yaw = _finite_number(raw["yaw_deg"], "yaw_deg")
    pitch = _finite_number(raw["pitch_deg"], "pitch_deg")
    hfov = _finite_number(raw["hfov_deg"], "hfov_deg")
    aspect_ratio = raw["aspect_ratio"]
    # 范围与生产契约共用一份校验，Playground 不另设常量。
    validate_pano_view_geometry(yaw, pitch, hfov, aspect_ratio)
    return {
        "image_asset_id": _asset_id(raw["image_asset_id"], "image_asset_id"),
        "yaw_deg": yaw,
        "pitch_deg": pitch,
        "hfov_deg": hfov,
        "aspect_ratio": aspect_ratio,
    }


def _parse_audio_remix(value: object) -> dict[str, object]:
    raw = _exact_keys(PlaygroundCapability.AUDIO_REMIX, value)
    voice_window = _window(
        raw["voice_gain_start_seconds"], raw["voice_gain_end_seconds"], "人声音量"
    )
    background_window = _window(
        raw["background_gain_start_seconds"],
        raw["background_gain_end_seconds"],
        "背景声音量",
    )
    gains = []
    for key in ("voice_gain_db", "background_gain_db"):
        gain = _finite_number(raw[key], key)
        if not -100 <= gain <= 24:
            raise ValueError(f"{key} 必须在 -100 到 24 dB 之间。")
        gains.append(gain)
    return {
        "video_asset_id": _asset_id(raw["video_asset_id"], "video_asset_id"),
        "voice_asset_id": _asset_id(raw["voice_asset_id"], "voice_asset_id"),
        "background_asset_id": _asset_id(raw["background_asset_id"], "background_asset_id"),
        "voice_gain_db": gains[0],
        "background_gain_db": gains[1],
        "voice_gain_start_seconds": voice_window[0],
        "voice_gain_end_seconds": voice_window[1],
        "background_gain_start_seconds": background_window[0],
        "background_gain_end_seconds": background_window[1],
    }


def _parse_audio_effect(value: object) -> dict[str, object]:
    raw = _exact_keys(PlaygroundCapability.AUDIO_EFFECT, value)
    if raw["preset"] not in _PRESET_NAMES:
        raise ValueError("preset 不在 Core 内置的 preset 列表里。")
    strength = _finite_number(raw["strength"], "strength")
    if not 0 <= strength <= 1:
        raise ValueError("strength 必须在 0 到 1 之间。")
    window = _window(raw["start_seconds"], raw["end_seconds"], "效果区间")
    return {
        "audio_asset_id": _asset_id(raw["audio_asset_id"], "audio_asset_id"),
        "preset": raw["preset"],
        "strength": strength,
        "seed": _seed(raw["seed"]),
        "start_seconds": window[0],
        "end_seconds": window[1],
    }


def _parse_audio_trim(value: object) -> dict[str, object]:
    raw = _exact_keys(PlaygroundCapability.AUDIO_TRIM, value)
    start = _finite_number(raw["start_seconds"], "start_seconds")
    end = _finite_number(raw["end_seconds"], "end_seconds")
    if start < 0 or end <= start:
        raise ValueError("截取区间必须满足 0 ≤ start < end。")
    return {
        "audio_asset_id": _asset_id(raw["audio_asset_id"], "audio_asset_id"),
        "start_seconds": start,
        "end_seconds": end,
    }


_PARSERS = {
    PlaygroundCapability.VIDEO_EXTRACT_FRAME: _parse_video_extract_frame,
    PlaygroundCapability.IMAGE_PANO_VIEW: _parse_image_pano_view,
    PlaygroundCapability.AUDIO_REMIX: _parse_audio_remix,
    PlaygroundCapability.AUDIO_EFFECT: _parse_audio_effect,
    PlaygroundCapability.AUDIO_TRIM: _parse_audio_trim,
}


def parse_parameters(
    capability: object, value: object, *, recipe: Recipe | None = None
) -> dict[str, object]:
    """结构与范围校验并规范化（去首尾空白）。不访问 Asset。

    recipe 能力必须给出提交时解析的 recipe；载入历史 run 时没有 recipe，只做结构校验。
    """
    if recipe is not None:
        if str(capability) != recipe.id:
            raise ValueError("capability 与 recipe 不一致。")
        bindings, params = parse_recipe_wire(recipe, value)
        return recipe_wire_value(recipe, bindings, params)
    return _PARSERS[_capability(capability)](value)


def input_asset_ids(
    capability: object, parameters: dict[str, object], *, recipe: Recipe | None = None
) -> tuple[str, ...]:
    """按参数里出现的稳定顺序收集全部 Asset 引用并去重。"""
    keys = parameters if recipe is None else [slot_wire_key(slot) for slot in recipe.slots]
    found: list[str] = []
    for key in keys:
        value = parameters.get(key)
        if key.endswith("_asset_id") and isinstance(value, str):
            found.append(value)
        elif key.endswith("_asset_ids") and isinstance(value, list):
            found.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, list):
            found.extend(
                item["asset_id"]
                for item in value
                if isinstance(item, dict) and isinstance(item.get("asset_id"), str)
            )
    seen: set[str] = set()
    ordered: list[str] = []
    for asset_id in found:
        if asset_id not in seen:
            seen.add(asset_id)
            ordered.append(asset_id)
    return tuple(ordered)


def parameter_seed(
    capability: object, parameters: dict[str, object], *, recipe: Recipe | None = None
) -> int | None:
    key = (
        "seed"
        if recipe is None
        else next((field.key for field in recipe.params if field.role is Role.SEED), None)
    )
    value = parameters.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def validate_run_parameters(run: PlaygroundRun) -> None:
    """载入时只做结构校验：参数、输入推导与 seed 必须自洽。"""
    try:
        raw = json.loads(run.parameters_json)
    except ValueError as exc:
        raise ValueError("run.parameters 不是合法 JSON。") from exc
    parameters = parse_parameters(run.capability, raw, recipe=run.recipe)
    if canonical_json(parameters) != run.parameters_json:
        raise ValueError("run.parameters 不是规范化参数。")
    if input_asset_ids(run.capability, parameters, recipe=run.recipe) != run.input_asset_ids:
        raise ValueError("run.input_asset_ids 与参数不一致。")
    if parameter_seed(run.capability, parameters, recipe=run.recipe) != run.seed:
        raise ValueError("run.seed 与参数不一致。")


def recipe_input_labels(
    recipe: Recipe, parameters: dict[str, object], *, draft: bool = False
) -> list[dict[str, object]]:
    """按已保存 recipe 的槽位与 namespace 计算输入标签。"""
    if draft:
        bindings = {}
        for slot in recipe.slots:
            raw = parameters.get(slot_wire_key(slot))
            values = raw if isinstance(raw, list) else [raw]
            items = []
            for value in values:
                asset_id = value.get("asset_id") if isinstance(value, dict) else value
                if (
                    isinstance(asset_id, str)
                    and len(asset_id) == 32
                    and all(char in "0123456789abcdef" for char in asset_id)
                ):
                    description = value.get("description") if isinstance(value, dict) else None
                    items.append(
                        SlotBinding(asset_id, description if isinstance(description, str) else None)
                    )
            bindings[slot.key] = tuple(items)
    else:
        bindings, _params = parse_recipe_wire(recipe, parameters)
    slots = {slot.key: slot for slot in recipe.slots}
    return [
        {
            "label": item["label"],
            "provider_input": item["slot"]
            if slots[item["slot"]].maximum == 1
            else f"{item['slot']}_{item['index'] + 1}",
            "asset_id": item["asset_id"],
            "description": item["description"],
        }
        for item in binding_labels(recipe, bindings)
        if item["label"] is not None
    ]
