"""测试读取脚本树的辅助：按 Shot 序号取覆盖它的 Segment（经脚本访问层）。"""

from __future__ import annotations

from core.structured_director.models import Scene, ShotSegment
from core.structured_director.script_index import shot_segments


def shot_segments_at(scene: Scene, shot_index: int) -> tuple[ShotSegment, ...]:
    return shot_segments(scene, scene.shots[shot_index].id)


def segments_of_shot(document, shot) -> tuple[ShotSegment, ...]:
    """在文档当前脚本中找到 Shot 所在 Scene，返回覆盖它的 Segment。"""
    for scene in document.director_script.scenes:
        if any(item.id == shot.id for item in scene.shots):
            return shot_segments(scene, shot.id)
    raise AssertionError("Shot 不在当前脚本中。")
