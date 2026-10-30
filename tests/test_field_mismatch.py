"""Core 严格对象的字段集合报错点名缺失与多余字段，并列出允许的字段，不回显字段值。"""

import pytest

from core.director_commands.models import InvalidArgumentsError
from core.structured_director.reads.common import _exact_arguments
from storyrail_contracts.fields import field_mismatch, require_fields


def test_names_missing_unknown_and_allowed_fields():
    message = field_mismatch(
        "video.set_prompt.arguments",
        {"scene_id": "x", "prompt_text": "私密正文"},
        {"scope", "segment_id", "prompt_text"},
    )
    assert message == (
        "video.set_prompt.arguments 缺少字段 scope、segment_id；不接受字段 scene_id"
        "（允许的字段：prompt_text、scope、segment_id）。"
    )
    assert "私密正文" not in message


def test_valid_objects_and_optional_fields_pass():
    value = {"scene_id": "x"}
    assert field_mismatch("t", value, {"scene_id"}, {"volume"}) is None
    assert require_fields("t", value, {"scene_id"}, {"volume"}) is value
    assert field_mismatch("t", [], {"a"}) == "t 必须是 JSON 对象。"


def test_long_field_lists_are_bounded():
    value = {f"unknown_{index}": 1 for index in range(30)}
    message = field_mismatch("t", value, set())
    assert "等 30 个" in message
    assert message.count("unknown_") == 12


def test_core_read_arguments_raise_invalid_arguments_with_names():
    with pytest.raises(InvalidArgumentsError, match="缺少字段 kind；不接受字段 extra"):
        _exact_arguments({"extra": 1}, required={"kind"}, optional={"ids"})
