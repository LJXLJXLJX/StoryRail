"""Scene 成片、全片装配与 Animatic 共用的时间线渲染。

片段先各自统一为同一画布、24 fps、48 kHz 立体声；相邻片段默认硬切，
声明 ``seam_blend`` 的边界做不超过 ``transition_seconds`` 的淡化融合（且不超过两侧时长的一半）。
旁白按起始片段的开始时间对齐混入；旁白比画面长时冻结最后一帧补齐。
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import FFmpeg

Progress = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class TimelineClip:
    file: Path
    seam_blend_from_previous: bool
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class TimelineNarration:
    file: Path
    start_clip_index: int


def render_timeline(
    ff: FFmpeg,
    clips: Sequence[TimelineClip],
    narrations: Sequence[TimelineNarration],
    *,
    transition_seconds: float,
    video_audio_volume: float,
    narration_audio_volume: float,
    output: Path,
    cancel: threading.Event,
    progress: Progress,
) -> None:
    durations = [clip.duration_seconds for clip in clips]
    transitions = [
        0.0,
        *[
            min(transition_seconds, durations[index - 1] / 2, durations[index] / 2)
            if clips[index].seam_blend_from_previous
            else 0.0
            for index in range(1, len(clips))
        ],
    ]
    starts = [0.0]
    for index in range(1, len(clips)):
        starts.append(starts[-1] + durations[index - 1] - transitions[index])
    visual_duration = starts[-1] + durations[-1]
    narration_durations = [ff.duration_seconds(item.file) for item in narrations]
    required_duration = max(
        [visual_duration]
        + [
            starts[item.start_clip_index] + narration_durations[index]
            for index, item in enumerate(narrations)
        ]
    )
    progress(0.55, "正在建立转场与旁白时间线。")

    arguments = ["-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        arguments.extend(["-i", str(clip.file)])
    for narration in narrations:
        arguments.extend(["-i", str(narration.file)])
    filters: list[str] = []
    # concat 输出 AVTB；每路输入统一时间基，后续 xfade 才能匹配。
    for index in range(len(clips)):
        filters.append(f"[{index}:v]fps=24,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v{index}]")
        filters.append(
            f"[{index}:a]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS,volume={video_audio_volume:.6f}[a{index}]"
        )
    video_label, audio_label = "v0", "a0"
    for index in range(1, len(clips)):
        next_video, next_audio = f"vx{index}", f"ax{index}"
        if transitions[index] > 0:
            filters.append(
                f"[{video_label}][v{index}]xfade=transition=fade:"
                f"duration={transitions[index]:.6f}:offset={starts[index]:.6f}[{next_video}]"
            )
            filters.append(
                f"[{audio_label}][a{index}]acrossfade=d={transitions[index]:.6f}:"
                f"c1=tri:c2=tri[{next_audio}]"
            )
        else:
            filters.append(f"[{video_label}][v{index}]concat=n=2:v=1:a=0[{next_video}]")
            filters.append(f"[{audio_label}][a{index}]concat=n=2:v=0:a=1[{next_audio}]")
        video_label, audio_label = next_video, next_audio
    padding = max(0.0, required_duration - visual_duration)
    if padding > 0.001:
        filters.append(f"[{video_label}]tpad=stop_mode=clone:stop_duration={padding:.6f}[vout]")
        video_label = "vout"
    if narrations:
        labels: list[str] = []
        for index, item in enumerate(narrations):
            label = f"narration{index}"
            delay = round(starts[item.start_clip_index] * 1000)
            filters.append(
                f"[{len(clips) + index}:a]aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={narration_audio_volume:.6f},adelay={delay}:all=1[{label}]"
            )
            labels.append(label)
        inputs = "".join(f"[{item}]" for item in [audio_label, *labels])
        filters.append(
            f"{inputs}amix=inputs={1 + len(labels)}:duration=longest:"
            "dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]"
        )
        audio_label = "aout"
    arguments.extend(["-filter_complex", ";".join(filters)])
    arguments.extend(
        [
            "-map",
            f"[{video_label}]",
            "-map",
            f"[{audio_label}]",
            *_H264_AAC,
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            "-t",
            f"{required_duration:.6f}",
            str(output),
        ]
    )
    ff.run(arguments, cancel, log=output.with_suffix(".log"))
    progress(0.97, "正在封装最终 MP4。")


def normalize_video_clip(
    ff: FFmpeg,
    source: Path,
    output: Path,
    *,
    duration: float,
    width: int,
    height: int,
    has_audio: bool,
    cancel: threading.Event,
) -> None:
    """视频片段铺满画布裁切，不足目标时长时冻结尾帧，没有音轨时补静音。"""
    arguments = ["-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if not has_audio:
        arguments.extend(
            ["-f", "lavfi", "-t", f"{duration:.6f}", "-i", "anullsrc=r=48000:cl=stereo"]
        )
    arguments.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if has_audio else "1:a:0",
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps=24,setsar=1,"
                f"tpad=stop_mode=clone:stop_duration={duration:.6f}"
            ),
            "-af",
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad",
            *_H264_AAC,
            "-preset",
            "veryfast",
            "-t",
            f"{duration:.6f}",
            str(output),
        ]
    )
    ff.run(arguments, cancel, log=output.with_suffix(".log"))


def normalize_still(
    ff: FFmpeg,
    source: Path,
    output: Path,
    *,
    duration: float,
    width: int,
    height: int,
    cancel: threading.Event,
) -> None:
    """静帧按画布等比缩放并以黑边补齐，配同长静音轨。"""
    arguments = [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "24",
        "-t",
        f"{duration:.6f}",
        "-i",
        str(source),
        "-f",
        "lavfi",
        "-t",
        f"{duration:.6f}",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "fps=24,setsar=1"
        ),
        *_H264_AAC,
        "-preset",
        "veryfast",
        "-t",
        f"{duration:.6f}",
        str(output),
    ]
    ff.run(arguments, cancel, log=output.with_suffix(".log"))


_H264_AAC = (
    "-c:v",
    "libx264",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "192k",
)
