"""proposal schema 生成器（P3-T1，02 号文档 §3.2）。

纯标准库：从 dataclass 自省生成严格 JSON Schema（additionalProperties: false、
必填集合、类型约束），并提供统一解析入口（剥 markdown 围栏 → strict_json →
schema 校验 → 构造 dataclass）。校验错误统一为 ``ProposalError``。

类型映射：str/int/float/bool/list/tuple/dict/Optional/嵌套 dataclass/Enum/
Literal；其余类型显式报错（不允许静默跳过）。值域约束（minLength/范围/
pattern 等）由 dataclass ``__post_init__`` 负责；结构级约束可经
``field(metadata={"json_schema": {...}})`` 或 ``overrides`` 参数合并。
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import typing
from enum import Enum
from typing import Any

__all__ = [
    "ProposalError",
    "generate_schema",
    "validate_against_schema",
    "parse_proposal",
    "strip_markdown_fence",
]


class ProposalError(ValueError):
    """proposal 解析/校验的唯一错误类型（domain, code, message）。"""

    def __init__(self, domain: str, code: str, message: str) -> None:
        self.domain = domain
        self.code = code
        self.message = message
        super().__init__(f"[{domain}:{code}] {message}")


# ---------------------------------------------------------------------------
# schema 生成
# ---------------------------------------------------------------------------

_SCHEMA_METADATA_KEY = "json_schema"

# 按 recipe 保存的合成机制参数：{recipe_id: {参数 key: JSON 标量或数值数组}}。
# 这里只约束形状；取值是否符合 recipe 由 Core 写入时按当前插件 manifest 校验。
RECIPE_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "additionalProperties": {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "null"},
                {"type": "array", "items": {"type": "number"}},
            ]
        },
    },
}

_MISSING = object()


def narration_language_schema(schema: dict, languages: tuple) -> dict:
    """按项目已选语言约束旁白轨道和音色字段；保留原 schema 的全部其它约束。"""
    result = copy.deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            properties = value.get("properties", {})
            for language in ("zh", "en"):
                for key in (language, f"{language}_voice_description"):
                    if key not in properties:
                        continue
                    field = properties[key]
                    if language not in languages:
                        properties[key] = {"type": "null"}
                    elif "anyOf" in field:
                        properties[key] = next(
                            item for item in field["anyOf"] if item.get("type") != "null"
                        )
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(result)
    return result


def _resolve_hints(model: type) -> dict[str, Any]:
    try:
        return typing.get_type_hints(model)
    except Exception as exc:  # noqa: BLE001 - 前向引用失败给显式报错
        raise TypeError(f"无法解析 {model.__name__} 的类型标注：{exc}") from exc


def _schema_for_type(tp: Any, path: str, overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if tp is str:
        return {"type": "string"}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is dict or tp is dict[str, Any]:
        return {"type": "object"}
    if tp is Any:
        raise TypeError(f"{path}: 不支持 Any 类型，请显式声明字段类型。")

    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    if origin is dict:
        return {"type": "object"}
    if origin is typing.Union or origin is getattr(__import__("types"), "UnionType", None):
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) != len(args) and len(non_none) == 1:
            inner = _schema_for_type(non_none[0], path, overrides)
            return {"anyOf": [inner, {"type": "null"}]}
        return {"anyOf": [_schema_for_type(arg, path, overrides) for arg in args]}

    if origin in (list, tuple):
        if not args:
            return {"type": "array"}
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                return {
                    "type": "array",
                    "items": _schema_for_type(args[0], f"{path}[]", overrides),
                }
            # 固定长度元组：prefixItems（keyframe 动态 schema 场景）
            return {
                "type": "array",
                "prefixItems": [
                    _schema_for_type(arg, f"{path}[{i}]", overrides) for i, arg in enumerate(args)
                ],
                "minItems": len(args),
                "maxItems": len(args),
            }
        return {
            "type": "array",
            "items": _schema_for_type(args[0], f"{path}[]", overrides),
        }

    if origin is not None and str(origin).endswith("Literal"):
        return _literal_schema(args, path)
    if origin is typing.Literal:
        return _literal_schema(args, path)

    if isinstance(tp, type):
        if issubclass(tp, Enum):
            return {"enum": [item.value for item in tp]}
        if dataclasses.is_dataclass(tp):
            return generate_schema(tp, overrides, _prefix=path)

    raise TypeError(
        f"{path}: 不支持的类型 {tp!r}（允许 str/int/float/bool/list/tuple/dict/"
        "Optional/嵌套 dataclass/Enum/Literal）。"
    )


def _literal_schema(args: tuple[Any, ...], path: str) -> dict[str, Any]:
    if not args:
        raise TypeError(f"{path}: Literal 至少需要一个取值。")
    if len(args) == 1:
        return {"const": args[0]}
    return {"enum": list(args)}


def generate_schema(
    model: type,
    overrides: dict[str, dict[str, Any]] | None = None,
    *,
    _prefix: str = "",
) -> dict[str, Any]:
    """从 dataclass 生成严格 JSON Schema。

    ``overrides`` 以 ``字段路径``（嵌套用 ``.``、集合项用 ``[]``）为键合并/
    覆盖生成的子 schema。特殊键 ``__required__`` 可强制默认字段仍为 wire 必填，
    ``__exclude__`` 可从特定 wire schema 排除兼容字段。
    ``dataclasses.field(metadata={"json_schema": {...}})`` 逐字段合并。
    """
    if not dataclasses.is_dataclass(model):
        raise TypeError(f"{model!r} 不是 dataclass。")
    overrides = overrides or {}
    hints = _resolve_hints(model)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(model):
        if field.name not in hints:
            raise TypeError(f"{model.__name__}.{field.name}: 缺少类型标注。")
        path = f"{_prefix}.{field.name}" if _prefix else field.name
        override = dict(overrides.get(path, {}))
        if override.pop("__exclude__", False):
            continue
        force_required = override.pop("__required__", False)
        schema = _schema_for_type(hints[field.name], path, overrides)
        meta = field.metadata.get(_SCHEMA_METADATA_KEY) if field.metadata else None
        if meta:
            schema = {**schema, **meta}
        if override:
            schema = {**schema, **override}
        properties[field.name] = schema
        default = field.default
        default_factory = field.default_factory  # type: ignore[comparison-overlap]
        if force_required or (
            default is dataclasses.MISSING and default_factory is dataclasses.MISSING
        ):
            required.append(field.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# schema 校验（生成器子集）
# ---------------------------------------------------------------------------


def validate_against_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """校验 value 是否符合生成器子集 JSON Schema；返回错误消息列表。"""
    errors: list[str] = []

    def fail(message: str) -> None:
        errors.append(f"{path}: {message}")

    if "const" in schema:
        if value != schema["const"]:
            fail(f"必须是常量 {schema['const']!r}。")
        return errors
    if "enum" in schema:
        if value not in schema["enum"]:
            fail(f"必须是 {schema['enum']!r} 之一。")
        return errors
    if "anyOf" in schema:
        if not any(not validate_against_schema(value, sub, path) for sub in schema["anyOf"]):
            fail("不匹配任何允许的形态。")
        return errors

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            fail("类型必须是 object。")
            return errors
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                fail(f"缺少字段 {key!r}。")
        extra = schema.get("additionalProperties")
        if extra is False:
            for key in value:
                if key not in properties:
                    fail(f"包含未声明字段 {key!r}。")
        elif isinstance(extra, dict):
            for key, item in value.items():
                if key not in properties:
                    errors.extend(validate_against_schema(item, extra, f"{path}.{key}"))
        for key, sub in properties.items():
            if key in value:
                errors.extend(validate_against_schema(value[key], sub, f"{path}.{key}"))
    elif expected == "array":
        if not isinstance(value, list):
            fail("类型必须是 array。")
            return errors
        if "minItems" in schema and len(value) < schema["minItems"]:
            fail(f"至少需要 {schema['minItems']} 个元素。")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            fail(f"最多允许 {schema['maxItems']} 个元素。")
        if "prefixItems" in schema:
            for index, sub in enumerate(schema["prefixItems"]):
                if index < len(value):
                    errors.extend(validate_against_schema(value[index], sub, f"{path}[{index}]"))
            if schema.get("items") is False and len(value) > len(schema["prefixItems"]):
                fail("不允许超出固定位置的额外元素。")
        elif "items" in schema:
            for index, item in enumerate(value):
                errors.extend(validate_against_schema(item, schema["items"], f"{path}[{index}]"))
    elif expected == "string":
        if not isinstance(value, str):
            fail("类型必须是 string。")
            return errors
        if "minLength" in schema and len(value) < schema["minLength"]:
            fail(f"长度不能小于 {schema['minLength']}。")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            fail(f"长度不能大于 {schema['maxLength']}。")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            fail(f"不匹配模式 {schema['pattern']!r}。")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            fail("类型必须是 integer。")
            return errors
        _check_bounds(value, schema, fail)
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("类型必须是 number。")
            return errors
        _check_bounds(value, schema, fail)
    elif expected == "boolean":
        if not isinstance(value, bool):
            fail("类型必须是 boolean。")
    elif expected == "null":
        if value is not None:
            fail("类型必须是 null。")
    elif expected is not None:
        fail(f"未知类型约束 {expected!r}。")
    return errors


def _check_bounds(value: float, schema: dict[str, Any], fail) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        fail(f"不能小于 {schema['minimum']}。")
    if "maximum" in schema and value > schema["maximum"]:
        fail(f"不能大于 {schema['maximum']}。")


# ---------------------------------------------------------------------------
# 解析入口
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n?\s*```\s*$", re.S)


def strip_markdown_fence(raw: str) -> str:
    """剥掉 ```json ... ``` 围栏；无围栏时原样返回。"""
    match = _FENCE_RE.match(raw)
    if match is not None:
        return match.group("body")
    if raw.lstrip().startswith("```"):
        raise ProposalError("proposal", "invalid_fence", "markdown 围栏不完整。")
    return raw


def _strict_json(raw: str, domain: str) -> Any:
    def reject_constant(name: str) -> None:
        raise ValueError(f"非法常量 {name}")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (ValueError, TypeError) as exc:
        raise ProposalError(domain, "invalid_json", f"不是合法 JSON：{exc}") from exc


def _construct(value: Any, tp: Any, path: str) -> Any:
    """把已校验的 JSON 值构造为标注类型（嵌套 dataclass 递归）。"""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union or (args and type(None) in args and origin is not None):
        non_none = [arg for arg in args if arg is not type(None)]
        if value is None:
            return None
        return _construct(value, non_none[0], path)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        hints = _resolve_hints(tp)
        kwargs = {
            key: _construct(val, hints[key], f"{path}.{key}")
            for key, val in value.items()
            if key in hints
        }
        try:
            return tp(**kwargs)
        except (TypeError, ValueError) as exc:
            raise ProposalError(
                "proposal", "invalid_value", f"{path}: 值未通过领域校验：{exc}"
            ) from exc
    if origin in (list, tuple) and args:
        if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            return tuple(
                _construct(item, item_type, f"{path}[{i}]")
                for i, (item, item_type) in enumerate(zip(value, args, strict=True))
            )
        item_tp = (
            args[0]
            if origin is tuple and len(args) == 2 and args[1] is Ellipsis
            else (args[0] if origin is list else None)
        )
        if item_tp is not None:
            items = tuple(_construct(item, item_tp, f"{path}[{i}]") for i, item in enumerate(value))
            return items if origin is tuple else list(items)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    return value


def parse_proposal(raw: str, schema: dict[str, Any], model: type, *, domain: str = "proposal"):
    """统一解析入口：剥围栏 → strict_json → schema 校验 → 构造 dataclass。"""
    value = _strict_json(strip_markdown_fence(raw), domain)
    errors = validate_against_schema(value, schema)
    if errors:
        raise ProposalError(domain, "schema_violation", "；".join(errors))
    hints = _resolve_hints(model)
    kwargs = {key: _construct(val, hints[key], key) for key, val in value.items() if key in hints}
    try:
        return model(**kwargs)
    except (TypeError, ValueError) as exc:
        raise ProposalError(domain, "invalid_value", f"值未通过领域校验：{exc}") from exc
