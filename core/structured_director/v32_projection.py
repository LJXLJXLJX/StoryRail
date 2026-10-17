"""Keyframe 规划输入仍按 Shot 分组的临时投影（L1）。

任务的 07 卡片会把 Keyframe Planner 改成以 Segment 为单位；在那之前
`planning_inputs.py` 仍需要把 Segment 挂到它覆盖的第一个 Shot 下。脚本写入面
不再使用本模块。
"""

from __future__ import annotations

from .models import Scene, ShotSegment


def v32_shot_segments(scene: Scene, shot_id: str) -> tuple[ShotSegment, ...]:
    """v32 形状下挂在该 Shot 下的 Segment：每个 Segment 挂到其第一个覆盖 Shot。"""
    return tuple(segment for segment in scene.segments if segment.shot_ids[0] == shot_id)
