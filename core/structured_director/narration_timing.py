from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from .models import Asset, NarrationCue, NarrationLanguage, Scene

NARRATION_BOUNDARY_VISUAL_TAIL_SECONDS = 0.4


def narration_visual_tail_seconds(scenes: Sequence[Scene], scene_id: str) -> float:
    """Return the fixed visual tail for an adjacent narration Scene boundary."""
    for index, scene in enumerate(scenes):
        if scene.id != scene_id:
            continue
        if index + 1 >= len(scenes):
            return 0.0
        following = scenes[index + 1]
        if (
            scene.driver == "narration"
            and following.driver == "narration"
            and scene.narration_cues
            and following.narration_cues
        ):
            return NARRATION_BOUNDARY_VISUAL_TAIL_SECONDS
        return 0.0
    raise ValueError("Scene 不存在，无法计算旁白画面缓冲。")


def narration_visual_duration_seconds(
    scenes: Sequence[Scene], scene_id: str, audio_duration_seconds: float
) -> float:
    return audio_duration_seconds + narration_visual_tail_seconds(scenes, scene_id)


def narration_audio_seconds(
    cue: NarrationCue, language: NarrationLanguage, assets: Mapping[str, Asset]
) -> float:
    """返回该语言已选旁白音频的真实时长；未选择或缺少时长时抛出中文原因。"""
    track = cue.track(language)
    label = "中文" if language is NarrationLanguage.ZH else "英文"
    if track.selected_audio_asset_id is None:
        raise ValueError(f"旁白 Cue 尚未选择审核通过的{label}音频。")
    asset = assets.get(track.selected_audio_asset_id)
    if asset is None or asset.duration_seconds is None or asset.duration_seconds <= 0:
        raise ValueError(f"旁白 Cue 的{label}音频缺少真实时长。")
    return asset.duration_seconds


def narration_timing_seconds(cue: NarrationCue, assets: Mapping[str, Asset]) -> float:
    """双语旁白的时间基准：中英已选音频中较长的一条。两种语言在同一起点开始。"""
    return max(narration_audio_seconds(cue, language, assets) for language, _ in cue.tracks)


def narration_timing_language(cue: NarrationCue, assets: Mapping[str, Asset]) -> NarrationLanguage:
    """返回决定时间基准的语言；等长时取中文。"""
    return max(cue.tracks, key=lambda item: narration_audio_seconds(cue, item[0], assets))[0]


def conform_production_scenes(
    scenes: tuple[Scene, ...], assets: Mapping[str, Asset], *, narrator_ready: bool
) -> tuple[Scene, ...]:
    """按已选旁白真实时长校准全部 Scene，作为生产基线；无法建立时抛出中文原因。"""
    cues = [cue for scene in scenes for cue in scene.narration_cues]
    if cues and not narrator_ready:
        raise ValueError("脚本包含旁白，但尚未建立旁白音色。")
    if not all(cue.fully_selected for cue in cues):
        raise ValueError("请先为每条旁白选择审核通过的所选语言音频。")
    return tuple(conform_scene_narration(scene, assets, scenes) for scene in scenes)


def conform_scene_narration(
    scene: Scene,
    assets: Mapping[str, Asset],
    source_scenes: Sequence[Scene],
) -> Scene:
    """让 Narration Scene 画面覆盖真实音频及相邻旁白边界的固定尾部缓冲。"""
    if not scene.shots:
        raise ValueError("请基于已选 TTS 真实时长规划 Shot / Segment。")
    segments = scene.segments
    for cue in scene.narration_cues:
        # 唯一 Cue 覆盖整个 Scene；双语旁白以中英较长的一条为时间基准，短的一条同起点提前结束。
        timing_seconds = narration_timing_seconds(cue, assets)
        current_duration = sum(segment.duration_estimate_seconds for segment in segments)
        required = narration_visual_duration_seconds(
            source_scenes,
            scene.id,
            timing_seconds,
        )
        if abs(current_duration - required) <= 0.000_001:
            # 每次脚本写入都会重新校准；已对齐的画面保持原值，避免浮点重算改写时长。
            continue
        factor = required / current_duration
        scaled_durations = [segment.duration_estimate_seconds * factor for segment in segments]
        # Put the floating-point remainder on the final Segment so the serialized
        # script remains an exact timing contract instead of accumulating drift.
        scaled_durations[-1] = required - sum(scaled_durations[:-1])
        if any(duration < 0.2 for duration in scaled_durations):
            raise ValueError(
                "旁白真实时长无法在当前 Segment 结构内精确分配；请合并过短的 Segment。"
            )
        segments = tuple(
            replace(segment, duration_estimate_seconds=duration)
            for segment, duration in zip(segments, scaled_durations, strict=True)
        )
    return replace(scene, segments=segments)
