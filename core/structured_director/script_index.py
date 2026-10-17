"""脚本访问层：Scene / Shot / Segment 之间的只读遍历与覆盖关系（L1 纯函数）。

调用方不直接展开 ``shot.segments``，而经本模块读取“Scene 的 Segment 序列”和“Segment 覆盖的 Shot”，
使脚本存储形状的变化只影响这里与真正构造脚本树的代码。当前存储中每个 Segment 恰好属于一个 Shot。
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import DirectorScript, Scene, Shot, ShotSegment


def scene_segments(scene: Scene) -> tuple[ShotSegment, ...]:
    """Scene 内全部 Segment，按脚本顺序。"""
    return tuple(segment for shot in scene.shots for segment in shot.segments)


def script_segments(script: DirectorScript | Iterable[Scene]) -> tuple[ShotSegment, ...]:
    """全脚本 Segment，按脚本顺序；接受 DirectorScript 或 Scene 序列。"""
    scenes = script.scenes if isinstance(script, DirectorScript) else script
    return tuple(segment for scene in scenes for segment in scene_segments(scene))


def shot_segments(scene: Scene, shot_id: str) -> tuple[ShotSegment, ...]:
    """覆盖该 Shot 的 Segment，按顺序；Shot 不在本 Scene 时为空。"""
    for shot in scene.shots:
        if shot.id == shot_id:
            return shot.segments
    return ()


def segment_shots(scene: Scene, segment_id: str) -> tuple[Shot, ...]:
    """Segment 覆盖的 Shot，按顺序；Segment 不在本 Scene 时为空。"""
    for shot in scene.shots:
        if any(segment.id == segment_id for segment in shot.segments):
            return (shot,)
    return ()


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
        for segment in scene_segments(scene):
            if segment.id == segment_id:
                return scene, segment
    return None


def segment_continues_previous(scene: Scene, segment_id: str) -> bool:
    """Segment 是否与本 Scene 上一个 Segment 延续同一 Shot（共享边界 Shot）。"""
    segments = scene_segments(scene)
    index = next((i for i, segment in enumerate(segments) if segment.id == segment_id), None)
    if not index:
        return False
    previous = segment_shots(scene, segments[index - 1].id)
    current = segment_shots(scene, segment_id)
    return previous[-1].id == current[0].id
