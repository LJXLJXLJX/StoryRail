"""v33 存储与仍为 v32 形状的对外接口之间的临时投影（L1）。

对外的 proposal、edit_script、Web snapshot、read_story 与工作集暂时保持 Shot 下挂 Segment、
旁白 Cue 带 Shot 锚点的形状；读取面与写入面逐个翻转为 v33 后删除本模块。
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Scene, ShotSegment


def v32_shot_segments(scene: Scene, shot_id: str) -> tuple[ShotSegment, ...]:
    """v32 形状下挂在该 Shot 下的 Segment：每个 Segment 挂到其第一个覆盖 Shot。"""
    return tuple(segment for segment in scene.segments if segment.shot_ids[0] == shot_id)


def v32_cue_anchors(scene: Scene) -> tuple[str | None, str | None]:
    """旁白 Cue 覆盖整个 Scene：锚点为首个与末个 Shot；尚未规划 Shot 时均为 None。"""
    if not scene.shots:
        return None, None
    return scene.shots[0].id, scene.shots[-1].id


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
