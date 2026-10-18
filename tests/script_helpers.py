"""测试读取与写入脚本树的辅助：按 Shot 取覆盖它的 Segment，并把快照 Scene 转成整卡保存请求。"""

from __future__ import annotations

from core.structured_director.models import Scene, ShotSegment
from core.structured_director.script_index import shot_segments

_SCENE_FIELDS = {
    "id",
    "title",
    "summary",
    "setting",
    "driver",
    "location_id",
    "state_id",
}
_SHOT_FIELDS = {
    "id",
    "visible_character_ids",
    "composition",
    "camera_movement",
    "action",
    "audio_direction",
    "transition_in",
}
_SEGMENT_FIELDS = {
    "id",
    "duration_estimate_seconds",
    "action",
    "dialogue_lines",
    "boundary_from_previous",
}
_TRACK_FIELDS = {"text", "seed", "recipe_params", "selected_audio_asset_id"}


def shot_segments_at(scene: Scene, shot_index: int) -> tuple[ShotSegment, ...]:
    return shot_segments(scene, scene.shots[shot_index].id)


def segments_of_shot(document, shot) -> tuple[ShotSegment, ...]:
    """在文档当前脚本中找到 Shot 所在 Scene，返回覆盖它的 Segment。"""
    for scene in document.director_script.scenes:
        if any(item.id == shot.id for item in scene.shots):
            return shot_segments(scene, shot.id)
    raise AssertionError("Shot 不在当前脚本中。")


def editable_scene_payload(scene: dict) -> dict:
    """v33 快照 Scene → 整卡手工保存请求：Shot 无 segments，Segment 用本 Scene shots 序号。"""
    positions = {shot["id"]: index for index, shot in enumerate(scene["shots"])}
    return {
        **{name: scene[name] for name in _SCENE_FIELDS},
        "shots": [{name: shot[name] for name in _SHOT_FIELDS} for shot in scene["shots"]],
        "segments": [
            {
                **{name: segment[name] for name in _SEGMENT_FIELDS},
                "shot_indexes": [positions[shot_id] for shot_id in segment["shot_ids"]],
            }
            for segment in scene["segments"]
        ],
        "narration_cues": [
            {
                "id": cue["id"],
                "zh": _editable_track(cue["zh"]),
                "en": _editable_track(cue["en"]),
            }
            for cue in scene["narration_cues"]
        ],
    }


def _editable_track(track: dict | None) -> dict | None:
    if track is None:
        return None
    return {name: track[name] for name in _TRACK_FIELDS}
