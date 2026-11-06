"""schema_gen 生成器单元测试（P3-T1）。

覆盖：每个支持的类型映射、每条错误路径（围栏/非法 JSON/多余字段/缺字段/
类型错/嵌套错/值域）、动态 schema（Literal→const / 固定元组 prefixItems）、
不支持的类型显式报错。不切换任何既有 codec。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

import pytest

from core.director_proposals.schema_gen import (
    ProposalError,
    generate_schema,
    parse_proposal,
    strip_markdown_fence,
    validate_against_schema,
)


class _Mode(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"


@dataclass(frozen=True)
class _Scalars:
    text: str
    count: int
    ratio: float
    flag: bool
    notes: dict


@dataclass(frozen=True)
class _Collections:
    names: list[str]
    fixed: tuple[str, ...]
    table: dict[str, int]


@dataclass(frozen=True)
class _Child:
    value: int


@dataclass(frozen=True)
class _Nested:
    child: _Child
    children: tuple[_Child, ...]
    maybe: _Child | None
    mode: _Mode
    kind: Literal["a", "b"]
    single: Literal["only"]


@dataclass(frozen=True)
class _Constrained:
    text: str = field(metadata={"json_schema": {"minLength": 1, "maxLength": 5}})


@dataclass(frozen=True)
class _OverrideItem:
    value: str = "x"
    legacy: str = ""


@dataclass(frozen=True)
class _OverrideRoot:
    items: tuple[_OverrideItem, ...]


@dataclass(frozen=True)
class _FixedTuple:
    pair: tuple[int, str]


# ---------------------------------------------------------------------------
# 类型映射
# ---------------------------------------------------------------------------


def test_scalar_type_mapping():
    schema = generate_schema(_Scalars)
    props = schema["properties"]
    assert props["text"] == {"type": "string"}
    assert props["count"] == {"type": "integer"}
    assert props["ratio"] == {"type": "number"}
    assert props["flag"] == {"type": "boolean"}
    assert props["notes"] == {"type": "object"}
    assert schema["required"] == ["text", "count", "ratio", "flag", "notes"]
    assert schema["additionalProperties"] is False


def test_collection_type_mapping():
    schema = generate_schema(_Collections)
    props = schema["properties"]
    assert props["names"] == {"type": "array", "items": {"type": "string"}}
    assert props["fixed"] == {"type": "array", "items": {"type": "string"}}
    assert props["table"] == {"type": "object"}


def test_nested_optional_enum_literal_mapping():
    schema = generate_schema(_Nested)
    props = schema["properties"]
    assert props["child"]["type"] == "object"
    assert props["child"]["additionalProperties"] is False
    assert props["children"]["items"]["type"] == "object"
    assert props["maybe"]["anyOf"][0]["type"] == "object"
    assert props["maybe"]["anyOf"][1] == {"type": "null"}
    assert props["mode"] == {"enum": ["generate", "edit"]}
    assert props["kind"] == {"enum": ["a", "b"]}
    assert props["single"] == {"const": "only"}


def test_field_metadata_merge():
    schema = generate_schema(_Constrained)
    assert schema["properties"]["text"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 5,
    }


def test_overrides_merge():
    schema = generate_schema(_Scalars, overrides={"text": {"maxLength": 3}})
    assert schema["properties"]["text"] == {"type": "string", "maxLength": 3}


def test_nested_collection_override_and_wire_required_exclusion():
    schema = generate_schema(
        _OverrideRoot,
        overrides={
            "items[].value": {"minLength": 1, "__required__": True},
            "items[].legacy": {"__exclude__": True},
        },
    )
    item = schema["properties"]["items"]["items"]
    assert item["properties"] == {"value": {"type": "string", "minLength": 1}}
    assert item["required"] == ["value"]


def test_default_field_not_required():
    @dataclass(frozen=True)
    class _WithDefault:
        a: int
        b: str = "x"

    schema = generate_schema(_WithDefault)
    assert schema["required"] == ["a"]


def test_unsupported_type_raises():
    @dataclass(frozen=True)
    class _Bad:
        value: set

    with pytest.raises(TypeError, match="不支持的类型"):
        generate_schema(_Bad)


def test_non_dataclass_raises():
    with pytest.raises(TypeError, match="不是 dataclass"):
        generate_schema(dict)


# ---------------------------------------------------------------------------
# 校验器
# ---------------------------------------------------------------------------


def test_validate_missing_and_extra_fields():
    schema = generate_schema(_Scalars)
    errors = validate_against_schema({"text": "x", "count": 1, "ratio": 1.0}, schema)
    assert any("缺少字段 'flag'" in e for e in errors)
    errors = validate_against_schema(
        {"text": "x", "count": 1, "ratio": 1.0, "flag": True, "notes": {}, "extra": 1}, schema
    )
    assert any("未声明字段 'extra'" in e for e in errors)


def test_validate_type_errors_and_bounds():
    schema = generate_schema(_Scalars)
    errors = validate_against_schema(
        {"text": 1, "count": True, "ratio": "x", "flag": 1, "notes": []}, schema
    )
    assert any("必须是 string" in e for e in errors)
    assert any("必须是 integer" in e for e in errors)
    assert any("必须是 number" in e for e in errors)
    assert any("必须是 boolean" in e for e in errors)
    assert any("必须是 object" in e for e in errors)


def test_validate_const_enum_pattern_and_lengths():
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "mode": {"enum": ["generate", "edit"]},
            "seg": {"const": "s1"},
            "tags": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
        },
        "required": ["id", "mode", "seg", "tags"],
        "additionalProperties": False,
    }
    bad = {"id": "z" * 32, "mode": "delete", "seg": "s2", "tags": []}
    errors = validate_against_schema(bad, schema)
    assert any("模式" in e for e in errors)
    assert any("之一" in e for e in errors)
    assert any("常量" in e for e in errors)
    assert any("至少需要 1 个元素" in e for e in errors)


def test_validate_fixed_tuple_prefix_items():
    @dataclass(frozen=True)
    class _Pair:
        pair: tuple[int, str]

    schema = generate_schema(_Pair)
    assert schema["properties"]["pair"]["prefixItems"] == [
        {"type": "integer"},
        {"type": "string"},
    ]
    errors = validate_against_schema({"pair": [1, 2]}, schema)
    assert any("[1]" in e and "string" in e for e in errors)
    errors = validate_against_schema({"pair": [1, "a", 3]}, schema)
    assert any("最多允许 2 个元素" in e for e in errors)


def test_validate_items_false_rejected_outside_prefix():
    schema = {
        "type": "object",
        "properties": {
            "shots": {
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "items": False,
                "minItems": 1,
                "maxItems": 1,
            }
        },
        "required": ["shots"],
        "additionalProperties": False,
    }
    errors = validate_against_schema({"shots": [1, 2]}, schema)
    assert any("固定位置" in e for e in errors)


# ---------------------------------------------------------------------------
# 解析入口
# ---------------------------------------------------------------------------


def test_parse_happy_path():
    schema = generate_schema(_Nested)

    raw = """
{
  "child": {"value": 1},
  "children": [{"value": 2}],
  "maybe": null,
  "mode": "edit",
  "kind": "a",
  "single": "only"
}
"""
    result = parse_proposal(raw, schema, _Nested, domain="test")
    assert result.child.value == 1
    assert result.children[0].value == 2
    assert result.maybe is None
    assert result.mode is _Mode.EDIT
    assert result.kind == "a"


def test_parse_strips_json_fence():
    schema = generate_schema(_Scalars)
    raw = '```json\n{"text": "t", "count": 1, "ratio": 1.0, "flag": true, "notes": {}}\n```'
    result = parse_proposal(raw, schema, _Scalars, domain="test")
    assert result.text == "t"


def test_parse_fixed_tuple_conversion():
    schema = generate_schema(_FixedTuple)
    result = parse_proposal('{"pair":[1,"a"]}', schema, _FixedTuple, domain="test")
    assert result.pair == (1, "a")


def test_parse_strips_plain_fence():
    raw = '```\n{"a": 1}\n```'
    assert strip_markdown_fence(raw) == '{"a": 1}'


def test_parse_unclosed_fence_raises():
    with pytest.raises(ProposalError, match="invalid_fence"):
        strip_markdown_fence('```json\n{"a": 1}')


def test_parse_invalid_json_raises():
    schema = generate_schema(_Scalars)
    with pytest.raises(ProposalError) as exc:
        parse_proposal("{not json", schema, _Scalars, domain="test")
    assert exc.value.code == "invalid_json"
    assert exc.value.domain == "test"


def test_parse_nan_rejected():
    schema = generate_schema(_Scalars)
    with pytest.raises(ProposalError, match="invalid_json"):
        parse_proposal(
            '{"text": "t", "count": 1, "ratio": NaN, "flag": true, "notes": {}}',
            schema,
            _Scalars,
            domain="test",
        )


def test_parse_schema_violation_raises_with_details():
    schema = generate_schema(_Scalars)
    with pytest.raises(ProposalError) as exc:
        parse_proposal(
            '{"text": "t", "count": 1, "ratio": 1.0, "flag": true, "notes": {}, "extra": 1}',
            schema,
            _Scalars,
            domain="test",
        )
    assert exc.value.code == "schema_violation"
    assert "extra" in str(exc.value)


def test_parse_nested_error_path():
    schema = generate_schema(_Nested)
    raw = (
        '{"child": {"value": "x"}, "children": [], "maybe": null, '
        '"mode": "edit", "kind": "a", "single": "only"}'
    )
    with pytest.raises(ProposalError) as exc:
        parse_proposal(raw, schema, _Nested, domain="test")
    assert exc.value.code == "schema_violation"
    assert "$.child.value" in str(exc.value)


def test_parse_post_init_error_becomes_invalid_value():
    @dataclass(frozen=True)
    class _Guarded:
        text: str

        def __post_init__(self) -> None:
            if not self.text.strip():
                raise ValueError("text 不能为空。")

    schema = generate_schema(_Guarded)
    with pytest.raises(ProposalError) as exc:
        parse_proposal('{"text": "   "}', schema, _Guarded, domain="test")
    assert exc.value.code == "invalid_value"
    assert "text 不能为空" in str(exc.value)


def test_proposal_error_attributes():
    error = ProposalError("narration", "schema_violation", "缺字段")
    assert error.domain == "narration"
    assert error.code == "schema_violation"
    assert "[narration:schema_violation]" in str(error)
    assert isinstance(error, ValueError)


def test_pattern_validation():
    @dataclass(frozen=True)
    class _Id:
        value: str = field(metadata={"json_schema": {"pattern": "^[0-9a-f]{32}$"}})

    schema = generate_schema(_Id)
    assert validate_against_schema({"value": "a" * 32}, schema) == []
    errors = validate_against_schema({"value": "z" * 32}, schema)
    assert any(re.search("模式", e) for e in errors)
