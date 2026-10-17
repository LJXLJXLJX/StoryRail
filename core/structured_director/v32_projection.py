"""仍为 v32 形状的写入接口与 v33 存储之间的临时投影（L1）。

脚本 proposal、edit_script 与 Web 整卡手工保存仍按 Shot 下挂 Segment、旁白 Cue 带 Shot 锚点提交；
Keyframe Planner 的输入与 proposal 仍按 Shot 分组 Segment。写入面与 Keyframe 规划翻转后删除本模块。
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Scene, ShotSegment


def v32_shot_segments(scene: Scene, shot_id: str) -> tuple[ShotSegment, ...]:
    """v32 形状下挂在该 Shot 下的 Segment：每个 Segment 挂到其第一个覆盖 Shot。"""
    return tuple(segment for segment in scene.segments if segment.shot_ids[0] == shot_id)


def require_v32_cue_anchors(
    shot_ids: Sequence[str], start_shot_id: str | None, end_shot_id: str | None
) -> None:
    """入站 v32 锚点只能是“覆盖全部 Shot”的唯一取值。"""
    if not shot_ids:
        if start_shot_id is not None or end_shot_id is not None:
            raise ValueError("尚未规划 Shot 的旁白不能包含 Shot 锚点。")
        return
    if start_shot_id not in shot_ids or end_shot_id not in shot_ids:
        raise ValueError("旁白 Cue 必须锚定本 Scene 的 Shot。")
    if (start_shot_id, end_shot_id) != (shot_ids[0], shot_ids[-1]):
        raise ValueError("Scene 旁白必须覆盖本 Scene 的全部 Shot。")


def require_v32_shot_segments(segments: Sequence[object]) -> None:
    """入站 v32 Shot 至少下挂一个 Segment；Shot 内首段无前置边界、后续段必须说明边界。"""
    if not segments:
        raise ValueError("每个 Shot 至少需要一个 Segment。")
    if segments[0].boundary_from_previous is not None:
        raise ValueError("Shot 的第一个 Segment 不能包含前置边界。")
    if any(segment.boundary_from_previous is None for segment in segments[1:]):
        raise ValueError("Shot 的后续 Segment 必须说明前置边界。")
