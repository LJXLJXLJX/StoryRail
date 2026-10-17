"""http、命令和 MCP 对同一编辑对象使用同一份字段名。"""

import dataclasses

from core.director_commands.narration_commands import NARRATION_CUE_EDIT_FIELDS
from core.director_commands.script_operations import (
    SEGMENT_FIELDS,
    SHOT_CONTENT_FIELDS,
    SHOT_FIELDS,
)
from core.director_proposals.wire_fields import (
    CHARACTER_LOOK_EDITOR_FIELDS,
    NARRATION_CUE_EDITOR_FIELDS,
    SCENE_EDITOR_FIELDS,
    SEGMENT_EDITOR_FIELDS,
    SHOT_EDITOR_FIELDS,
)
from core.director_proposals.wire_fields import NARRATION_CUE_EDIT_FIELDS as DECLARED_CUE_FIELDS
from core.director_proposals.wire_fields import (
    SEGMENT_FIELDS as DECLARED_SEGMENT_FIELDS,
)
from core.director_proposals.wire_fields import (
    SHOT_CONTENT_FIELDS as DECLARED_SHOT_CONTENT,
)
from core.director_proposals.wire_fields import (
    SHOT_FIELDS as DECLARED_SHOT_FIELDS,
)
from core.structured_director.http_requests import (
    _NARRATION_CUE_FIELDS,
    _SCENE_FIELDS,
    _SEGMENT_FIELDS,
    _SHOT_FIELDS,
)
from core.structured_director.models import CharacterLook
from integrations.storyrail_mcp.production_tools import (
    narration_fields,
    segment_fields,
    shot_fields,
)


def test_script_editor_fields_have_one_declaration() -> None:
    assert SEGMENT_FIELDS == DECLARED_SEGMENT_FIELDS
    assert SHOT_CONTENT_FIELDS == DECLARED_SHOT_CONTENT
    assert SHOT_FIELDS == DECLARED_SHOT_FIELDS
    assert _SEGMENT_FIELDS == SEGMENT_EDITOR_FIELDS
    assert _SHOT_FIELDS == SHOT_EDITOR_FIELDS
    assert _SCENE_FIELDS == SCENE_EDITOR_FIELDS
    assert set(segment_fields) == DECLARED_SEGMENT_FIELDS
    assert set(shot_fields) == DECLARED_SHOT_CONTENT


def test_narration_edit_fields_have_one_declaration() -> None:
    assert NARRATION_CUE_EDIT_FIELDS == DECLARED_CUE_FIELDS
    assert _NARRATION_CUE_FIELDS == NARRATION_CUE_EDITOR_FIELDS
    assert set(narration_fields) - {"clear_selected_audio"} == DECLARED_CUE_FIELDS
    # 造型图只经人类选择入口改变，整卡保存不携带 selected_asset_id。
    assert {field.name for field in dataclasses.fields(CharacterLook)} - {
        "selected_asset_id"
    } == CHARACTER_LOOK_EDITOR_FIELDS
