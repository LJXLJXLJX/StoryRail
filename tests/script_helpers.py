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


def v32_scene_payload(scene: dict) -> dict:
    """把 v33 snapshot Scene 转成仍为 v32 形状的整卡手工保存请求（脚本写入面翻转后删除）。"""
    shots = [
        {
            **shot,
            "segments": [
                {key: value for key, value in segment.items() if key != "shot_ids"}
                for segment in scene["segments"]
                if segment["shot_ids"][0] == shot["id"]
            ],
        }
        for shot in scene["shots"]
    ]
    anchors = (shots[0]["id"], shots[-1]["id"]) if shots else (None, None)
    return {
        **{key: value for key, value in scene.items() if key != "segments"},
        "shots": shots,
        "narration_cues": [
            {**cue, "start_shot_id": anchors[0], "end_shot_id": anchors[1]}
            for cue in scene["narration_cues"]
        ],
    }
