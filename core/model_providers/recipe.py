"""按 recipe 提交的通用请求：Core 按语义角色填好槽位与参数，按 manifest 校验后交给插件翻译。

线上约定（Playground 参数、Web 表单与 Agent 输入共用）：

- 单图/单音频且不需要说明的槽位：``<slot>_asset_id``（最少 0 个时可为 null）；
- 多项且不需要说明的槽位：``<slot>_asset_ids``（ID 数组）；
- 需要说明的槽位：``<slot>``（``{asset_id, description}`` 数组，顺序即 Provider 输入顺序）；
- 参数：manifest 字段 key → 值；可空字段显式传 null。

带语义角色的参数在项目里由领域事实填写；没有角色的参数是插件机制参数，按 recipe 分别保存。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .manifest import Field, PluginManifest, Recipe, Role, Slot, Widget

_ID = re.compile(r"^[0-9a-f]{32}$")
_DESCRIPTION_MAX = 2_000


@dataclass(frozen=True, slots=True)
class MediaInput:
    media_type: str
    content: bytes
    description: str | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class RecipeRequest:
    """一次已校验的 recipe 提交：槽位按 manifest 顺序，参数为完整字段集。"""

    recipe_id: str
    inputs: tuple[tuple[str, tuple[MediaInput, ...]], ...]
    params: tuple[tuple[str, Any], ...]
    settings: tuple[tuple[str, Any], ...] = ()

    def slot(self, key: str) -> tuple[MediaInput, ...]:
        return dict(self.inputs).get(key, ())

    def single(self, key: str) -> MediaInput | None:
        items = self.slot(key)
        return items[0] if items else None

    def param(self, key: str) -> Any:
        return dict(self.params)[key]

    def setting(self, key: str) -> Any:
        return dict(self.settings)[key]


def mechanism_fields(recipe: Recipe) -> tuple[Field, ...]:
    """没有语义角色的参数：插件机制参数，由用户或 Agent 按 recipe 填写并分别保存。"""
    return tuple(item for item in recipe.params if item.role is None)


_DOMAIN_SLOT_ROLES = frozenset(
    {Role.FIRST_FRAME, Role.LAST_FRAME, Role.VOICE_REFERENCE, Role.EDIT_SOURCE}
)


def explicit_slots(recipe: Recipe) -> tuple[Slot, ...]:
    """需要人或 Agent 显式绑定的槽位；首尾帧、音色参考与编辑底图由 Core 按领域事实填写。"""
    return tuple(slot for slot in recipe.slots if slot.role not in _DOMAIN_SLOT_ROLES)


def role_field(recipe: Recipe, role: Role) -> Field | None:
    return next((item for item in recipe.params if item.role is role), None)


def validate_mechanism_params(recipe: Recipe, value: object) -> dict[str, Any]:
    """机制参数的完整对象：缺键、多键或取值不合法都拒绝。"""
    if not isinstance(value, Mapping):
        raise ValueError(f"{recipe.label} 参数必须是 JSON 对象。")
    fields = mechanism_fields(recipe)
    expected = {item.key for item in fields}
    if set(value) != expected:
        raise ValueError(_key_mismatch(f"{recipe.label} 参数", expected, set(value)))
    return {item.key: item.validate(value[item.key]) for item in fields}


def default_mechanism_params(recipe: Recipe) -> dict[str, Any]:
    return {item.key: item.default for item in mechanism_fields(recipe)}


def validate_required_slots(recipe: Recipe, inputs: Mapping[str, Sequence[object]]) -> None:
    """按 recipe 的声明校验跨领域槽位要求；调用方可以同时传自动与显式输入。"""
    if recipe.require_any and not any(inputs.get(key, ()) for key in recipe.require_any):
        labels = "或".join(slot.label for slot in recipe.slots if slot.key in recipe.require_any)
        raise ValueError(f"{recipe.label} 至少需要{labels}之一。")


def build_recipe_request(
    manifest: PluginManifest,
    recipe_id: str,
    *,
    inputs: Mapping[str, Sequence[MediaInput]],
    params: Mapping[str, Any],
    settings: Mapping[str, Any] | None = None,
) -> RecipeRequest:
    recipe = manifest.recipe(recipe_id)
    slot_keys = {slot.key for slot in recipe.slots}
    if set(inputs) - slot_keys:
        raise ValueError(_key_mismatch(f"{recipe.label} 输入", slot_keys, set(inputs)))
    ordered = tuple(
        (slot.key, _validate_slot(slot, tuple(inputs.get(slot.key, ())))) for slot in recipe.slots
    )
    validate_required_slots(recipe, dict(ordered))
    distinct = [
        item.content for key, items in ordered if key in recipe.distinct_slots for item in items
    ]
    if len(distinct) != len(set(distinct)):
        raise ValueError("参考图不能与底图重复；声明互斥的输入槽位不能重复。")
    expected = {item.key for item in recipe.params}
    if set(params) != expected:
        raise ValueError(_key_mismatch(f"{recipe.label} 参数", expected, set(params)))
    validated = tuple((item.key, item.validate(params[item.key])) for item in recipe.params)
    return RecipeRequest(
        recipe.id,
        ordered,
        validated,
        tuple(sorted((settings or manifest.default_settings()).items())),
    )


def _validate_slot(slot: Slot, items: tuple[MediaInput, ...]) -> tuple[MediaInput, ...]:
    if not slot.minimum <= len(items) <= slot.maximum:
        if slot.minimum == slot.maximum:
            raise ValueError(f"{slot.label}必须是 {slot.minimum} 项。")
        raise ValueError(f"{slot.label}必须是 {slot.minimum} 到 {slot.maximum} 项。")
    for item in items:
        if slot.media_types and item.media_type not in slot.media_types:
            raise ValueError(f"{slot.label}只接受 {'、'.join(slot.media_types)}。")
        if slot.duration_seconds is not None:
            low, high = slot.duration_seconds
            if item.duration_seconds is None or not low <= item.duration_seconds <= high:
                raise ValueError(f"{slot.label}必须是 {low:g} 到 {high:g} 秒。")
        if slot.describe == "required" and not (item.description or "").strip():
            raise ValueError(f"{slot.label}每一项都必须填写说明。")
        if item.description is not None and len(item.description) > _DESCRIPTION_MAX:
            raise ValueError(f"{slot.label}说明不能超过 {_DESCRIPTION_MAX} 字。")
    if slot.unique and len({(item.media_type, item.content) for item in items}) != len(items):
        raise ValueError(f"{slot.label}不能重复。")
    return items


def _key_mismatch(label: str, expected: set[str], actual: set[str]) -> str:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    parts = [
        f"缺少 {', '.join(missing)}" if missing else "",
        f"多出 {', '.join(extra)}" if extra else "",
    ]
    return f"{label}键不匹配：{'；'.join(part for part in parts if part)}。"


# ---------------------------------------------------------------------------
# 线上形状：Playground 参数、Web 表单与 Agent 输入
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlotBinding:
    asset_id: str
    description: str | None = None


def slot_wire_key(slot: Slot) -> str:
    if slot.describe != "none":
        return slot.key
    return f"{slot.key}_asset_id" if slot.maximum == 1 else f"{slot.key}_asset_ids"


def parse_recipe_wire(
    recipe: Recipe, value: object, *, fields: Sequence[Field] | None = None
) -> tuple[dict[str, tuple[SlotBinding, ...]], dict[str, Any]]:
    """按线上约定解析为槽位绑定与参数；``fields`` 默认是 recipe 的全部参数。"""
    if not isinstance(value, Mapping):
        raise ValueError(f"{recipe.label} 参数必须是 JSON 对象。")
    params_fields = tuple(recipe.params if fields is None else fields)
    keys = {slot_wire_key(slot) for slot in recipe.slots} | {item.key for item in params_fields}
    if set(value) != keys:
        raise ValueError(_key_mismatch(f"{recipe.label} 参数", keys, set(value)))
    bindings = {
        slot.key: _parse_slot_wire(slot, value[slot_wire_key(slot)]) for slot in recipe.slots
    }
    validate_required_slots(recipe, bindings)
    distinct = [
        item.asset_id
        for key, items in bindings.items()
        if key in recipe.distinct_slots
        for item in items
    ]
    if len(distinct) != len(set(distinct)):
        raise ValueError("参考图不能与底图重复；声明互斥的输入槽位不能重复。")
    params = {
        item.key: item.validate(
            value[item.key].strip() if isinstance(value[item.key], str) else value[item.key]
        )
        for item in params_fields
    }
    return bindings, params


def _parse_slot_wire(slot: Slot, value: object) -> tuple[SlotBinding, ...]:
    label = slot_wire_key(slot)
    if slot.describe == "none" and slot.maximum == 1:
        if value is None:
            items: tuple[SlotBinding, ...] = ()
        elif isinstance(value, str) and _ID.match(value):
            items = (SlotBinding(value),)
        else:
            raise ValueError(f"{label} 必须是 Asset ID{'或 null' if slot.minimum == 0 else ''}。")
    elif slot.describe == "none":
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not _ID.match(item) for item in value
        ):
            raise ValueError(f"{label} 必须是 Asset ID 数组。")
        items = tuple(SlotBinding(item) for item in value)
    else:
        if not isinstance(value, list):
            raise ValueError(f"{label} 必须是数组。")
        parsed = []
        for item in value:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"asset_id", "description"}
                or not isinstance(item["asset_id"], str)
                or not _ID.match(item["asset_id"])
            ):
                raise ValueError(f"{label} 每项必须且只能包含 asset_id 与 description。")
            description = item["description"]
            if description is not None and not isinstance(description, str):
                raise ValueError(f"{label} 的 description 必须是字符串。")
            parsed.append(
                SlotBinding(item["asset_id"], None if description is None else description.strip())
            )
        items = tuple(parsed)
    if not slot.minimum <= len(items) <= slot.maximum:
        raise ValueError(f"{slot.label}必须是 {slot.minimum} 到 {slot.maximum} 项。")
    if slot.unique and len({item.asset_id for item in items}) != len(items):
        raise ValueError(f"{slot.label}不能重复。")
    if slot.describe == "required" and any(not item.description for item in items):
        raise ValueError(f"{slot.label}每一项都必须填写说明。")
    return items


def recipe_wire_value(
    recipe: Recipe,
    bindings: Mapping[str, Sequence[SlotBinding]],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """槽位绑定与参数 → 规范化线上形状（parse_recipe_wire 的逆）。"""
    value: dict[str, Any] = {}
    for slot in recipe.slots:
        items = tuple(bindings.get(slot.key, ()))
        key = slot_wire_key(slot)
        if slot.describe != "none":
            value[key] = [
                {"asset_id": item.asset_id, "description": item.description} for item in items
            ]
        elif slot.maximum == 1:
            value[key] = items[0].asset_id if items else None
        else:
            value[key] = [item.asset_id for item in items]
    value.update(params)
    return value


def recipe_wire_schema(recipe: Recipe, *, fields: Sequence[Field] | None = None) -> dict[str, Any]:
    """线上约定对应的 JSON Schema（Playground 能力目录与 Agent 工具使用）。"""
    properties: dict[str, Any] = {}
    for slot in recipe.slots:
        properties[slot_wire_key(slot)] = _slot_schema(slot)
    for item in recipe.params if fields is None else fields:
        properties[item.key] = field_schema(item)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


_ID_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{32}$"}


def _slot_schema(slot: Slot) -> dict[str, Any]:
    description = slot.label
    if slot.media_types:
        description += f"（{'、'.join(slot.media_types)}）"
    if slot.describe == "none" and slot.maximum == 1:
        schema: dict[str, Any] = (
            dict(_ID_SCHEMA) if slot.minimum == 1 else {"anyOf": [_ID_SCHEMA, {"type": "null"}]}
        )
        return {**schema, "description": f"{description}的 Asset ID。"}
    if slot.describe == "none":
        items: dict[str, Any] = _ID_SCHEMA
    else:
        text: dict[str, Any] = {"type": "string", "maxLength": _DESCRIPTION_MAX}
        if slot.describe == "required":
            text["minLength"] = 1
        items = {
            "type": "object",
            "additionalProperties": False,
            "required": ["asset_id", "description"],
            "properties": {
                "asset_id": _ID_SCHEMA,
                "description": text
                if slot.describe == "required"
                else {"anyOf": [text, {"type": "null"}]},
            },
        }
    schema = {"type": "array", "maxItems": slot.maximum, "items": items, "description": description}
    if slot.minimum:
        schema["minItems"] = slot.minimum
    return schema


def field_schema(item: Field) -> dict[str, Any]:
    schema: dict[str, Any]
    if item.widget in {Widget.ENUM, Widget.PRESET}:
        schema = {"type": "string", "enum": [option.id for option in item.options]}
    elif item.widget is Widget.TOGGLE:
        schema = {"type": "boolean"}
    elif item.widget in {Widget.TEXT, Widget.PROMPT}:
        schema = {"type": "string"}
        if item.min_length:
            schema["minLength"] = item.min_length
        if item.max_length is not None:
            schema["maxLength"] = item.max_length
    elif item.widget is Widget.SEED:
        schema = {"type": "integer", "minimum": 0, "maximum": 2**63 - 1}
    elif item.widget is Widget.VECTOR:
        schema = {
            "type": "array",
            "minItems": item.dimension,
            "maxItems": item.dimension,
            "items": _number_schema(item),
        }
    else:
        schema = _number_schema(item)
    description = item.label + (f"：{item.help}" if item.help else "。")
    if item.nullable:
        return {"anyOf": [schema, {"type": "null"}], "description": description}
    return {**schema, "description": description}


def _number_schema(item: Field) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "number"}
    if item.minimum is not None:
        schema["minimum"] = item.minimum
    if item.maximum is not None:
        schema["maximum"] = item.maximum
    return schema


# ---------------------------------------------------------------------------
# 按 recipe 保存的机制参数
# ---------------------------------------------------------------------------

_PARAMS_JSON_MAX = 20_000


def _param_value(value: Any, label: str) -> Any:
    if isinstance(value, str):
        # 机制参数里的文本按自然语言保存，去掉首尾空白。
        return value.strip()
    if isinstance(value, float) and not isfinite(value):
        raise ValueError(f"{label} 必须是有限数值。")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, list | tuple) and all(
        isinstance(item, int | float) and not isinstance(item, bool) and isfinite(item)
        for item in value
    ):
        return tuple(value)
    raise ValueError(f"{label} 只能保存 JSON 标量或数值数组。")


@dataclass(frozen=True, slots=True)
class RecipeParams:
    """recipe_id → 机制参数。切换绑定再切回时参数仍在；按 recipe 分别校验与失效。"""

    entries: tuple[tuple[str, tuple[tuple[str, Any], ...]], ...] = ()

    def __post_init__(self) -> None:
        recipe_ids = [recipe_id for recipe_id, _params in self.entries]
        if recipe_ids != sorted(recipe_ids) or len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("recipe_params 必须按 recipe 排序且不重复。")
        for recipe_id, params in self.entries:
            if not isinstance(recipe_id, str) or not 0 < len(recipe_id) <= 128:
                raise ValueError("recipe_params 的 recipe ID 不合法。")
            keys = [key for key, _value in params]
            if keys != sorted(keys) or len(keys) != len(set(keys)):
                raise ValueError("recipe_params 的参数必须按键排序且不重复。")
            for key, value in params:
                _param_value(value, f"recipe_params.{recipe_id}.{key}")
        if len(repr(self.entries)) > _PARAMS_JSON_MAX:
            raise ValueError("recipe_params 过大。")

    @classmethod
    def from_json(cls, value: object, label: str = "recipe_params") -> RecipeParams:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} 必须是 JSON 对象。")
        entries = []
        for recipe_id, params in sorted(value.items()):
            if not isinstance(params, Mapping):
                raise ValueError(f"{label}.{recipe_id} 必须是 JSON 对象。")
            entries.append(
                (
                    recipe_id,
                    tuple(
                        (key, _param_value(item, f"{label}.{recipe_id}.{key}"))
                        for key, item in sorted(params.items())
                    ),
                )
            )
        return cls(tuple(entries))

    def to_json(self) -> dict[str, dict[str, Any]]:
        return {
            recipe_id: {
                key: list(value) if isinstance(value, tuple) else value for key, value in params
            }
            for recipe_id, params in self.entries
        }

    def get(self, recipe_id: str) -> dict[str, Any] | None:
        for current, params in self.entries:
            if current == recipe_id:
                return {
                    key: list(value) if isinstance(value, tuple) else value for key, value in params
                }
        return None

    def with_entry(self, recipe_id: str, params: Mapping[str, Any]) -> RecipeParams:
        merged = {**self.to_json(), recipe_id: dict(params)}
        return RecipeParams.from_json(merged)

    def changed_entries(self, previous: RecipeParams) -> tuple[str, ...]:
        """相对 previous 新增或改变的 recipe。"""
        before = previous.to_json()
        return tuple(
            recipe_id
            for recipe_id, params in self.to_json().items()
            if before.get(recipe_id) != params
        )


@dataclass(frozen=True, slots=True)
class RecipeInputs:
    """单个 recipe 的显式资产绑定与机制参数；首尾帧等领域自动槽位不保存于此。"""

    bindings: tuple[tuple[str, tuple[SlotBinding, ...]], ...] = ()
    params: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self):
        keys = [key for key, _items in self.bindings]
        if (
            keys != sorted(keys)
            or len(keys) != len(set(keys))
            or any(not isinstance(key, str) or not key for key in keys)
        ):
            raise ValueError("recipe bindings 的槽位名必须按键排序且不重复。")
        for _key, items in self.bindings:
            if not isinstance(items, tuple) or any(
                not isinstance(item, SlotBinding) for item in items
            ):
                raise ValueError("recipe bindings 必须保存 SlotBinding 元组。")
            for item in items:
                if not isinstance(item.asset_id, str) or not _ID.fullmatch(item.asset_id):
                    raise ValueError("recipe binding.asset_id 不合法。")
                if item.description is not None and (
                    not isinstance(item.description, str)
                    or len(item.description) > _DESCRIPTION_MAX
                ):
                    raise ValueError("recipe binding.description 不合法。")
        RecipeParams((("inputs", self.params),))

    @classmethod
    def from_json(cls, value: object) -> RecipeInputs:
        if not isinstance(value, Mapping) or set(value) != {"bindings", "params"}:
            raise ValueError("recipe 输入必须且只能包含 bindings 与 params。")
        raw = value["bindings"]
        if not isinstance(raw, Mapping):
            raise ValueError("recipe bindings 必须是对象。")
        bindings = []
        for slot, items in sorted(raw.items()):
            if not isinstance(slot, str) or not slot or not isinstance(items, list):
                raise ValueError("recipe bindings 的槽位名与列表不合法。")
            parsed = []
            for item in items:
                if not isinstance(item, Mapping) or set(item) != {"asset_id", "description"}:
                    raise ValueError("recipe binding 必须且只能包含 asset_id 与 description。")
                asset_id, description = item["asset_id"], item["description"]
                if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
                    raise ValueError("recipe binding.asset_id 不合法。")
                if description is not None and (
                    not isinstance(description, str) or len(description) > _DESCRIPTION_MAX
                ):
                    raise ValueError("recipe binding.description 不合法。")
                parsed.append(
                    SlotBinding(asset_id, None if description is None else description.strip())
                )
            bindings.append((slot, tuple(parsed)))
        params = RecipeParams.from_json({"input": value["params"]}).entries[0][1]
        return cls(tuple(bindings), params)

    def to_json(self) -> dict[str, Any]:
        return {
            "bindings": {
                key: [
                    {"asset_id": item.asset_id, "description": item.description} for item in items
                ]
                for key, items in self.bindings
            },
            "params": {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in self.params
            },
        }

    def slot(self, key: str) -> tuple[SlotBinding, ...]:
        return dict(self.bindings).get(key, ())

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.asset_id for _key, items in self.bindings for item in items)
        )


def binding_labels(
    recipe: Recipe, bindings: Mapping[str, Sequence[SlotBinding]]
) -> list[dict[str, Any]]:
    """按 manifest 槽位顺序计算 namespace 标签，同一序列用于工作集、预览与提交。"""
    counters: dict[str, int] = {}
    namespaces = dict(recipe.label_namespaces)
    result = []
    for slot in recipe.slots:
        for index, item in enumerate(bindings.get(slot.key, ())):
            label = None
            if slot.namespace:
                number = counters.get(slot.namespace, 0) + 1
                counters[slot.namespace] = number
                label = namespaces[slot.namespace].format(n=number)
            result.append(
                {
                    "slot": slot.key,
                    "role": slot.role.value,
                    "index": index,
                    "asset_id": item.asset_id,
                    "description": item.description,
                    "label": label,
                }
            )
    return result


@dataclass(frozen=True, slots=True)
class RecipeBook:
    """按 recipe 保存显式输入，切换时保留各 recipe 的用户参数。"""

    entries: tuple[tuple[str, RecipeInputs], ...] = ()

    def __post_init__(self) -> None:
        keys = [key for key, _value in self.entries]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("recipes 必须按 ID 排序且不重复。")
        for key, value in self.entries:
            if (
                not isinstance(key, str)
                or not 0 < len(key) <= 128
                or not isinstance(value, RecipeInputs)
            ):
                raise ValueError("recipes 的 ID 或输入不合法。")

    @classmethod
    def from_json(cls, value: object) -> RecipeBook:
        if not isinstance(value, Mapping):
            raise ValueError("recipes 必须是对象。")
        return cls(
            tuple((key, RecipeInputs.from_json(item)) for key, item in sorted(value.items()))
        )

    def to_json(self) -> dict[str, Any]:
        return {key: value.to_json() for key, value in self.entries}

    def get(self, recipe_id: str | None) -> RecipeInputs:
        return dict(self.entries).get(recipe_id, RecipeInputs())

    def with_entry(self, recipe_id: str, value: RecipeInputs) -> RecipeBook:
        return RecipeBook(tuple(sorted({**dict(self.entries), recipe_id: value}.items())))
