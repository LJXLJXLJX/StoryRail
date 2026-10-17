"""脚本访问层：Scene / Shot / Segment 之间的只读遍历与覆盖关系（L1 纯函数）。

Scene 下并列 ``shots`` 与 ``segments``，``segment.shot_ids`` 记录 Segment 覆盖的 Shot
（按顺序、连续）。一个 Segment 可覆盖多个 Shot，一个 Shot 可跨多个相邻 Segment；
相邻 Segment 共享边界 Shot 即延续同一镜头。
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import DirectorScript, Scene, Shot, ShotSegment


def scene_segments(scene: Scene) -> tuple[ShotSegment, ...]:
    """Scene 内全部 Segment，按脚本顺序。"""
    return scene.segments


def script_segments(script: DirectorScript | Iterable[Scene]) -> tuple[ShotSegment, ...]:
    """全脚本 Segment，按脚本顺序；接受 DirectorScript 或 Scene 序列。"""
    scenes = script.scenes if isinstance(script, DirectorScript) else script
    return tuple(segment for scene in scenes for segment in scene.segments)


def shot_segments(scene: Scene, shot_id: str) -> tuple[ShotSegment, ...]:
    """覆盖该 Shot 的 Segment，按顺序；Shot 不在本 Scene 时为空。"""
    return tuple(segment for segment in scene.segments if shot_id in segment.shot_ids)


def segment_shots(scene: Scene, segment_id: str) -> tuple[Shot, ...]:
    """Segment 覆盖的 Shot，按顺序；Segment 不在本 Scene 时为空。"""
    segment = next((item for item in scene.segments if item.id == segment_id), None)
    if segment is None:
        return ()
    shots = {shot.id: shot for shot in scene.shots}
    return tuple(shots[shot_id] for shot_id in segment.shot_ids)


def segment_visible_character_ids(scene: Scene, segment_id: str) -> tuple[str, ...]:
    """覆盖 Shot 的可见角色并集，保持出现顺序去重。"""
    return tuple(
        dict.fromkeys(
            character_id
            for shot in segment_shots(scene, segment_id)
            for character_id in shot.visible_character_ids
        )
    )


def segment_view_ids(scene: Scene, segment_id: str) -> tuple[str | None, str | None]:
    """(首个覆盖 Shot 的视图, 最后一个覆盖 Shot 的视图)；Segment 不在本 Scene 时均为 None。"""
    shots = segment_shots(scene, segment_id)
    if not shots:
        return None, None
    return shots[0].view_id, shots[-1].view_id


def find_segment(
    scenes: DirectorScript | Iterable[Scene], segment_id: str
) -> tuple[Scene, ShotSegment] | None:
    """定位 Segment 所在 Scene；不存在时为 None。"""
    scenes = scenes.scenes if isinstance(scenes, DirectorScript) else scenes
    for scene in scenes:
        for segment in scene.segments:
            if segment.id == segment_id:
                return scene, segment
    return None


def segment_continues_previous(scene: Scene, segment_id: str) -> bool:
    """Segment 是否与本 Scene 上一个 Segment 共享边界 Shot（延续同一镜头）。"""
    segments = scene.segments
    index = next((i for i, segment in enumerate(segments) if segment.id == segment_id), None)
    if not index:
        return False
    return segments[index - 1].shot_ids[-1] == segments[index].shot_ids[0]


def segment_continues_next(scene: Scene, segment_id: str) -> bool:
    """Segment 是否与本 Scene 下一个 Segment 共享边界 Shot（延续同一镜头）。"""
    segments = scene.segments
    index = next((i for i, segment in enumerate(segments) if segment.id == segment_id), None)
    if index is None or index + 1 >= len(segments):
        return False
    return segments[index].shot_ids[-1] == segments[index + 1].shot_ids[0]
