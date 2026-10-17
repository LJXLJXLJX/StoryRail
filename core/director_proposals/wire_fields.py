"""脚本、镜头、旁白编辑字段的唯一名字集合。

http 请求、director 命令和 MCP 模型都引用这里。集合来自 proposal dataclass，
HTTP 编辑器多出来的稳定 ID 或地点绑定在此显式加回。
"""

from __future__ import annotations

import dataclasses

from core.director_proposals.script import (
    DialogueLineProposal,
    EditableSceneProposal,
    SegmentBoundaryProposal,
    ShotProposal,
    ShotSegmentProposal,
)


def _names(model: type) -> frozenset[str]:
    return frozenset(field.name for field in dataclasses.fields(model))


DIALOGUE_FIELDS = _names(DialogueLineProposal)
BOUNDARY_FIELDS = _names(SegmentBoundaryProposal)
SEGMENT_FIELDS = _names(ShotSegmentProposal)
SHOT_CONTENT_FIELDS = _names(ShotProposal) - {"segments"}
SHOT_FIELDS = SHOT_CONTENT_FIELDS | {"segments"}
# 地点绑定随整卡回传但只读：脚本编辑按 ID 保留原绑定，修改绑定走地点操作。
SCENE_EDITOR_FIELDS = _names(EditableSceneProposal) | {"location_id", "state_id"}
SEGMENT_EDITOR_FIELDS = SEGMENT_FIELDS | {"id"}
SHOT_EDITOR_FIELDS = SHOT_FIELDS | {"id", "view_id"}
# 旁白固定中英双语：Cue 级字段只有 Shot 范围，正文与合成参数在 zh / en 两条轨道里。
NARRATION_LANGUAGE_KEYS = frozenset({"zh", "en"})
NARRATION_TRACK_EDIT_FIELDS = frozenset({"text", "recipe_params", "seed"})
NARRATION_TRACK_EDITOR_FIELDS = NARRATION_TRACK_EDIT_FIELDS | {"selected_audio_asset_id"}
NARRATION_CUE_EDIT_FIELDS = frozenset({"start_shot_id", "end_shot_id"}) | NARRATION_LANGUAGE_KEYS
NARRATION_CUE_EDITOR_FIELDS = NARRATION_CUE_EDIT_FIELDS | {"id"}
# 人类整卡保存的造型字段：id 为 null 表示新造型，由 Core 分配 ID；造型图只经选择入口改变。
CHARACTER_LOOK_EDITOR_FIELDS = frozenset({"id", "name", "appearance", "usage"})
