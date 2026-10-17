from __future__ import annotations

from dataclasses import dataclass

from .models import (
    FinalAssemblyClip,
    FinalAssemblyPlan,
    FinalNarrationPlacement,
    FinalTransition,
    NarrationLanguage,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    SceneAssemblyClip,
    SceneAssemblyPlan,
    StructuredDirectorDocument,
)
from .narration_timing import (
    narration_timing_language,
    narration_timing_seconds,
    narration_visual_duration_seconds,
)
from .video_inputs import effective_video


@dataclass(frozen=True, slots=True)
class _SceneAnimaticSpec:
    clip_asset_ids: tuple[str, ...]
    clip_transitions: tuple[str | None, ...]
    clip_durations: tuple[float, ...]
    narration_asset_ids: tuple[str, ...]
    narration_start_clip_indices: tuple[int, ...]
    duration_seconds: float


def _build_scene_animatic_spec(
    document: StructuredDirectorDocument, scene_id: str
) -> _SceneAnimaticSpec:
    """组装 Scene 级 Animatic 时间线；未就绪时抛出带中文原因的 ValueError。"""
    script = document.director_script
    plan = document.keyframe_plan
    if script is None or plan is None:
        raise ValueError("导演脚本或关键帧计划不存在。")
    if script.production_baseline_revision != script.revision:
        raise ValueError("当前 Shot timing 已失效；请确认时序后再生成 Animatic。")
    scene = next((item for item in script.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError("Scene 不存在。")
    transition_seconds = 0.1
    keyframes = {item.id: item for item in plan.keyframes}
    bindings = {item.segment_id: item for item in plan.segments}
    asset_by_id = {item.id: item for item in document.assets}

    clip_asset_ids: list[str] = []
    clip_transitions: list[str | None] = []
    clip_durations: list[float] = []
    segment_first_clip: dict[str, int] = {}
    segment_clip_counts: dict[str, int] = {}
    previous_end_keyframe_id: str | None = None
    for shot_number, shot in enumerate(scene.shots, start=1):
        for segment_number, segment in enumerate(shot.segments, start=1):
            location = f"Shot {shot_number} Segment {segment_number}"
            binding = bindings.get(segment.id)
            if binding is None:
                raise ValueError(f"{location} 缺少关键帧绑定。")
            start_keyframe = keyframes[binding.start_keyframe_id]
            end_keyframe = keyframes[binding.end_keyframe_id]
            start_asset_id = start_keyframe.selected_asset_id if binding.start_enabled else None
            end_asset_id = end_keyframe.selected_asset_id if binding.end_enabled else None
            if (binding.start_enabled and start_asset_id is None) or (
                binding.end_enabled and end_asset_id is None
            ):
                raise ValueError(f"{location} 启用的边界关键帧尚未全部选择图片。")
            if start_asset_id is None and end_asset_id is None:
                raise ValueError(f"{location} 尚未选择已激活的关键帧图片。")
            duration = segment.duration_estimate_seconds
            transition = (
                None
                if previous_end_keyframe_id is None or not binding.start_enabled
                else _final_transition(previous_end_keyframe_id, binding.start_keyframe_id)
            )
            if start_asset_id is not None and end_asset_id is not None:
                # FL2VA 画面输入：首尾帧平分该段时长，段内硬切。
                frames = (
                    (start_asset_id, duration / 2),
                    (end_asset_id, duration / 2),
                )
            elif start_asset_id is not None:
                frames = ((start_asset_id, duration),)
            else:
                assert end_asset_id is not None
                frames = ((end_asset_id, duration),)
            segment_first_clip[segment.id] = len(clip_asset_ids)
            segment_clip_counts[segment.id] = len(frames)
            for frame_index, (asset_id, frame_duration) in enumerate(frames):
                clip_asset_ids.append(asset_id)
                clip_transitions.append(transition if frame_index == 0 else None)
                clip_durations.append(frame_duration)
            previous_end_keyframe_id = binding.end_keyframe_id if binding.end_enabled else None

    narration_asset_ids: list[str] = []
    narration_starts: list[int] = []
    ranges: list[tuple[int, int, float]] = []
    shot_by_id = {shot.id: shot for shot in scene.shots}
    for cue in scene.narration_cues:
        # 预览节奏与成片一致：按中英较长的一条对轨并播放它。
        audio_duration = narration_timing_seconds(cue, asset_by_id)
        timing_track = cue.track(narration_timing_language(cue, asset_by_id))
        start_shot = shot_by_id[cue.start_shot_id]
        end_shot = shot_by_id[cue.end_shot_id]
        start = segment_first_clip[start_shot.segments[0].id]
        end_segment = end_shot.segments[-1].id
        end = segment_first_clip[end_segment] + segment_clip_counts[end_segment] - 1
        # 只有 Narration Scene 有旁白（模型不变量），画面按旁白加边界缓冲对齐。
        ranges.append(
            (
                start,
                end,
                narration_visual_duration_seconds(script.scenes, scene.id, audio_duration),
            )
        )
        assert timing_track.selected_audio_asset_id is not None
        narration_asset_ids.append(timing_track.selected_audio_asset_id)
        narration_starts.append(start)
    clip_durations = _align_animatic_durations(
        clip_durations, clip_transitions, ranges, transition_seconds
    )
    starts = _animatic_clip_starts(clip_durations, clip_transitions, transition_seconds)
    return _SceneAnimaticSpec(
        clip_asset_ids=tuple(clip_asset_ids),
        clip_transitions=tuple(clip_transitions),
        clip_durations=tuple(clip_durations),
        narration_asset_ids=tuple(narration_asset_ids),
        narration_start_clip_indices=tuple(narration_starts),
        duration_seconds=starts[-1] + clip_durations[-1],
    )


def _animatic_clip_starts(
    durations: list[float],
    transitions: list[str | None],
    transition_seconds: float,
) -> list[float]:
    starts = [0.0]
    for index in range(1, len(durations)):
        if transitions[index] is None:
            overlap = 0.0
        else:
            overlap = min(
                transition_seconds,
                durations[index - 1] / 2,
                durations[index] / 2,
            )
        starts.append(starts[-1] + durations[index - 1] - overlap)
    return starts


def _align_animatic_durations(
    durations: list[float],
    transitions: list[str | None],
    ranges: list[tuple[int, int, float]],
    transition_seconds: float,
) -> list[float]:
    """把 Cue 画面精确对齐到真实 WAV 与确定性的旁白边界视觉缓冲。"""
    adjusted = list(durations)
    for start, end, audio_duration in ranges:
        for _ in range(24):
            starts = _animatic_clip_starts(adjusted, transitions, transition_seconds)
            visual_duration = starts[end] + adjusted[end] - starts[start]
            delta = audio_duration - visual_duration
            if abs(delta) <= 0.000_001:
                break
            candidate = adjusted[end] + delta
            if candidate < 0.05:
                raise ValueError(
                    "Animatic 画面时长无法与旁白覆盖区间精确对齐；"
                    "请缩短该 Cue 的旁白或调整其 Shot 范围。"
                )
            adjusted[end] = candidate
        starts = _animatic_clip_starts(adjusted, transitions, transition_seconds)
        aligned = starts[end] + adjusted[end] - starts[start]
        if abs(aligned - audio_duration) > 0.000_01:
            raise ValueError("Animatic 旁白与画面时间轴无法精确收敛。")
    return adjusted


def _build_scene_final_plan(
    document: StructuredDirectorDocument,
    scene_id: str,
    language: NarrationLanguage,
) -> SceneAssemblyPlan:
    """单个 Scene 某一语言的成片装配输入：Segment 视频加该语言旁白。

    画面按已选旁白的时间基准对齐；未就绪时抛出带中文原因的 ValueError。
    """
    script = document.director_script
    keyframes = document.keyframe_plan
    videos = document.video_plan
    if script is None or keyframes is None or videos is None:
        raise ValueError("当前视频生产输入不完整。")
    if script.production_baseline_revision != script.revision:
        raise ValueError("请先重新校准旁白时长，建立当前脚本的生产基线。")
    scene = next((item for item in script.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError("Scene 不存在。")
    if language not in document.narration_languages:
        raise ValueError("项目未启用该旁白语言。")
    video_by_segment = {item.segment_id: item for item in videos.segments}
    binding_by_segment = {item.segment_id: item for item in keyframes.segments}
    ordered_segments = [segment for shot in scene.shots for segment in shot.segments]
    clips: list[SceneAssemblyClip] = []
    previous_end: str | None = None
    for segment in ordered_segments:
        video = video_by_segment.get(segment.id)
        binding = binding_by_segment.get(segment.id)
        if video is None or binding is None:
            raise ValueError("Segment 的视频或关键帧计划不完整。")
        asset_id = effective_video(document, segment.id)
        if asset_id is None:
            raise ValueError("请先为全部 Segment 选择视频候选。")
        transition = None
        if previous_end is not None and binding.start_enabled:
            transition = _final_transition(previous_end, binding.start_keyframe_id)
        clips.append(SceneAssemblyClip(segment.id, asset_id, transition))
        previous_end = binding.end_keyframe_id if binding.end_enabled else None
    if not clips:
        raise ValueError("导演脚本中没有可装配的 Segment。")
    narrations: list[FinalNarrationPlacement] = []
    timing_asset_ids: list[str] = []
    shot_by_id = {item.id: item for item in scene.shots}
    asset_by_id = {item.id: item for item in document.assets}
    for cue in scene.narration_cues:
        if not cue.fully_selected:
            raise ValueError("请先为全部旁白 Cue 选择审核通过的所选语言音频。")
        start_shot = shot_by_id.get(cue.start_shot_id)
        if start_shot is None or not start_shot.segments:
            raise ValueError("旁白 Cue 的起始 Shot 无法定位。")
        asset_id = cue.track(language).selected_audio_asset_id
        assert asset_id is not None
        narrations.append(
            FinalNarrationPlacement(
                cue.id,
                asset_id,
                start_shot.segments[0].id,
                narration_timing_seconds(cue, asset_by_id),
            )
        )
        timing_asset_ids.extend(
            track.selected_audio_asset_id
            for _, track in cue.tracks
            if track.selected_audio_asset_id is not None
        )
    return SceneAssemblyPlan(
        script.revision,
        tuple(clips),
        tuple(narrations),
        language,
        tuple(dict.fromkeys(timing_asset_ids)),
    )


def scene_final_input_asset_ids(plan: SceneAssemblyPlan) -> tuple[str, ...]:
    """Scene 成片的精确输入：Segment 视频、该语言旁白，以及决定画面时长的另一语言旁白。"""
    return tuple(
        dict.fromkeys(
            [clip.asset_id for clip in plan.clips]
            + [narration.asset_id for narration in plan.narrations]
            + list(plan.timing_asset_ids)
        )
    )


def _current_scene_final_asset_id(
    document: StructuredDirectorDocument, scene_id: str, language: NarrationLanguage
) -> str | None:
    """返回该语言基于当前视频与所选语言旁白生成的 Scene 成片；没有或已过期时为 None。"""
    try:
        plan = _build_scene_final_plan(document, scene_id, language)
    except ValueError:
        return None
    expected_inputs = scene_final_input_asset_ids(plan)
    for generation in reversed(document.generations):
        if (
            generation.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
            and generation.target_id == scene_id
            and generation.language is language
            and generation.phase is ReferenceGenerationPhase.SUCCEEDED
            and not generation.dismissed
            and generation.output_asset_id is not None
        ):
            if tuple(generation.input_asset_ids) == expected_inputs:
                return generation.output_asset_id
            return None
    return None


def _scenes_missing_final(
    document: StructuredDirectorDocument,
) -> tuple[str, ...]:
    """按脚本顺序返回任一语言尚无基于当前输入生成的 Scene 成片的 Scene ID。"""
    script = document.director_script
    if script is None:
        return ()
    return tuple(
        scene.id
        for scene in script.scenes
        if any(
            _current_scene_final_asset_id(document, scene.id, language) is None
            for language in document.narration_languages
        )
    )


def _build_final_assembly_plan(
    document: StructuredDirectorDocument,
) -> FinalAssemblyPlan:
    """最终成片只拼接 Scene 成片；Scene 内转场与旁白已固化在成片字节里。

    每个 Scene 必须存在基于当前 Segment 视频与旁白选择生成的 Scene 成片，
    否则拒绝装配并一次列出全部缺失 Scene。
    """
    script = document.director_script
    if script is None or document.keyframe_plan is None or document.video_plan is None:
        raise ValueError("当前视频生产输入不完整。")
    if script.production_baseline_revision != script.revision:
        raise ValueError("请先重新校准旁白时长，建立当前脚本的生产基线。")
    bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
    clips: list[FinalAssemblyClip] = []
    missing: list[str] = []
    previous_end: str | None = None
    for scene_number, scene in enumerate(script.scenes, start=1):
        scene_assets = {
            language: _current_scene_final_asset_id(document, scene.id, language)
            for language in document.narration_languages
        }
        zh_asset_id = scene_assets.get(NarrationLanguage.ZH)
        en_asset_id = scene_assets.get(NarrationLanguage.EN)
        if any(value is None for value in scene_assets.values()):
            absent = "、".join(
                "中文" if language is NarrationLanguage.ZH else "英文"
                for language, value in scene_assets.items()
                if value is None
            )
            missing.append(f"Scene {scene_number}《{scene.title}》（{absent}）")
            continue
        first_segment = (
            scene.shots[0].segments[0] if scene.shots and scene.shots[0].segments else None
        )
        last_segment = (
            scene.shots[-1].segments[-1] if scene.shots and scene.shots[-1].segments else None
        )
        start_binding = None if first_segment is None else bindings.get(first_segment.id)
        end_binding = None if last_segment is None else bindings.get(last_segment.id)
        transition = None
        if previous_end is not None and start_binding is not None and start_binding.start_enabled:
            transition = _final_transition(previous_end, start_binding.start_keyframe_id)
        clips.append(FinalAssemblyClip(scene.id, zh_asset_id, en_asset_id, transition))
        previous_end = (
            end_binding.end_keyframe_id
            if end_binding is not None and end_binding.end_enabled
            else None
        )
    if missing:
        raise ValueError(
            "以下 Scene 尚无基于当前 Segment 与所选语言旁白选择生成的 Scene 成片："
            + "、".join(missing)
            + "。请先在对应 Scene 卡片生成 Scene 成片。"
        )
    if not clips:
        raise ValueError("导演脚本中没有可装配的 Scene。")
    return FinalAssemblyPlan(script.revision, tuple(clips))


def _align_clip_durations_to_narration(
    document: StructuredDirectorDocument,
    plan: SceneAssemblyPlan,
    source_durations: list[float],
    narration_durations: dict[str, float],
    transition_seconds: float,
    *,
    scene_ids: set[str] | None = None,
) -> list[float]:
    """Trim or pad the final clip of each Cue so its visual range equals the WAV."""
    if document.director_script is None:
        raise ValueError("结构化导演脚本不存在。")
    if any(duration <= 0 for duration in source_durations):
        raise ValueError("Scene 成片包含缺少真实时长的 Segment 视频 Asset。")
    clip_index = {item.segment_id: index for index, item in enumerate(plan.clips)}
    ranges: list[tuple[int, int, float]] = []
    for scene in document.director_script.scenes:
        if scene_ids is not None and scene.id not in scene_ids:
            continue
        shot_by_id = {shot.id: shot for shot in scene.shots}
        for cue in scene.narration_cues:
            audio_duration = narration_durations.get(cue.id)
            if audio_duration is None or audio_duration <= 0:
                raise ValueError("旁白 Cue 缺少真实音频时长。")
            start_shot = shot_by_id[cue.start_shot_id]
            end_shot = shot_by_id[cue.end_shot_id]
            start = clip_index[start_shot.segments[0].id]
            end = clip_index[end_shot.segments[-1].id]
            ranges.append(
                (
                    start,
                    end,
                    narration_visual_duration_seconds(
                        document.director_script.scenes,
                        scene.id,
                        audio_duration,
                    ),
                )
            )
    durations = _align_duration_ranges(
        source_durations,
        ranges,
        transition_seconds,
        [clip.transition_from_previous for clip in plan.clips],
    )
    return durations


def _align_duration_ranges(
    source_durations: list[float],
    ranges: list[tuple[int, int, float]],
    transition_seconds: float,
    transitions: list[str | None],
) -> list[float]:
    durations = list(source_durations)
    for start, end, audio_duration in ranges:
        for _ in range(24):
            starts = _clip_starts(durations, transition_seconds, transitions)
            visual_duration = starts[end] + durations[end] - starts[start]
            delta = audio_duration - visual_duration
            if abs(delta) <= 0.000_001:
                break
            adjusted = durations[end] + delta
            if adjusted < 0.05:
                raise ValueError(
                    "所选视频的真实时长无法与旁白覆盖区间精确对齐；"
                    "请缩短前序视频或调整 Cue 的 Shot 范围。"
                )
            durations[end] = adjusted
        starts = _clip_starts(durations, transition_seconds, transitions)
        aligned = starts[end] + durations[end] - starts[start]
        if abs(aligned - audio_duration) > 0.000_01:
            raise ValueError("旁白与视频时间轴无法精确收敛。")
    return durations


def _clip_starts(
    durations: list[float], transition_seconds: float, transitions: list[str | None]
) -> list[float]:
    return _animatic_clip_starts(durations, transitions, transition_seconds)


def _final_transition(
    previous_end_keyframe_id: str,
    current_start_keyframe_id: str,
) -> FinalTransition | None:
    if previous_end_keyframe_id == current_start_keyframe_id:
        return FinalTransition.SEAM_BLEND
    return None
