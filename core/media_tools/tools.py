"""五个确定性媒体工具的渲染函数：输入是 Core 契约，输出是任务目录里的产物文件。"""

from __future__ import annotations

import math
import threading
from pathlib import Path

from core.model_providers.contracts import (
    AnimaticRequest,
    AudioRemixRequest,
    FinalAssemblyRequest,
    PanoViewRequest,
    VideoFrameRequest,
)

from .ffmpeg import OUTPUT_CANVAS, FFmpeg, has_audio, image_suffix, write_input
from .timeline import (
    Progress,
    TimelineClip,
    TimelineNarration,
    normalize_still,
    normalize_video_clip,
    render_timeline,
)

# 全景取景长边固定 2048，短边按画幅取偶数。
PANO_OUTPUT_SIZES = {"16:9": (2048, 1152), "9:16": (1152, 2048), "2:1": (2048, 1024)}


def render_final_assembly(
    ff: FFmpeg,
    request: FinalAssemblyRequest,
    directory: Path,
    cancel: threading.Event,
    progress: Progress,
) -> Path:
    width, height = OUTPUT_CANVAS[request.aspect_ratio]
    clips: list[TimelineClip] = []
    for index, clip in enumerate(request.clips):
        source = write_input(directory, f"clip-{index:04d}.mp4", clip.content)
        info = ff.format_info(source)
        if float(info["format"]["duration"]) <= 0:
            raise ValueError("片段时长无效。")
        normalized = directory / f"normalized-{index:04d}.mp4"
        normalize_video_clip(
            ff,
            source,
            normalized,
            duration=clip.duration_seconds,
            width=width,
            height=height,
            has_audio=has_audio(info),
            cancel=cancel,
        )
        clips.append(
            TimelineClip(
                normalized, clip.transition_from_previous == "seam_blend", clip.duration_seconds
            )
        )
        progress(
            0.08 + 0.42 * (index + 1) / len(request.clips),
            f"正在统一片段规格（{index + 1}/{len(request.clips)}）。",
        )
    output = directory / "output.mp4"
    render_timeline(
        ff,
        clips,
        _narrations(directory, request.narrations),
        transition_seconds=request.transition_seconds,
        video_audio_volume=request.video_audio_volume,
        narration_audio_volume=request.narration_audio_volume,
        output=output,
        cancel=cancel,
        progress=progress,
    )
    return output


def render_animatic(
    ff: FFmpeg,
    request: AnimaticRequest,
    directory: Path,
    cancel: threading.Event,
    progress: Progress,
) -> Path:
    width, height = OUTPUT_CANVAS[request.aspect_ratio]
    clips: list[TimelineClip] = []
    for index, clip in enumerate(request.clips):
        source = write_input(
            directory, f"clip-{index:04d}{image_suffix(clip.content)}", clip.content
        )
        normalized = directory / f"normalized-{index:04d}.mp4"
        normalize_still(
            ff,
            source,
            normalized,
            duration=clip.duration_seconds,
            width=width,
            height=height,
            cancel=cancel,
        )
        clips.append(
            TimelineClip(
                normalized, clip.transition_from_previous is not None, clip.duration_seconds
            )
        )
        progress(
            0.08 + 0.42 * (index + 1) / len(request.clips),
            f"正在统一片段规格（{index + 1}/{len(request.clips)}）。",
        )
    output = directory / "output.mp4"
    render_timeline(
        ff,
        clips,
        _narrations(directory, request.narrations),
        transition_seconds=request.transition_seconds,
        video_audio_volume=1.0,
        narration_audio_volume=1.0,
        output=output,
        cancel=cancel,
        progress=progress,
    )
    return output


def render_video_frame(
    ff: FFmpeg,
    request: VideoFrameRequest,
    directory: Path,
    cancel: threading.Event,
    progress: Progress,
) -> Path:
    """按解码顺序取视频轨第 ``frame_index`` 帧，按显示宽高比输出 PNG。"""
    source = write_input(directory, "source.mp4", request.content)
    data = ff.probe(
        source,
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp",
    )
    frames = data.get("frames", [])
    if not frames or data.get("_stderr"):
        raise ValueError("源视频不能完整解码。")
    if request.frame_index >= len(frames):
        raise ValueError(f"抽帧帧号超出范围：源视频只有 0-{len(frames) - 1} 帧。")
    output = directory / "output.png"
    ff.run(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"select=eq(n\\,{request.frame_index}),scale=iw*sar:ih,setsar=1",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            "1",
            str(output),
        ],
        cancel,
        log=directory / "output.log",
    )
    return output


def pano_vertical_fov(hfov_deg: float, width: int, height: int) -> float:
    """透视投影平面上半宽 = tan(hfov/2)，半高 = 半宽 · 高/宽，所以 v_fov 不随画幅线性缩放。"""
    return math.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) * height / width))


def render_pano_view(
    ff: FFmpeg,
    request: PanoViewRequest,
    directory: Path,
    cancel: threading.Event,
    progress: Progress,
) -> Path:
    """把 2:1 等距柱状全景按机位裁切成透视 PNG。

    ``yaw_deg`` 0° 为全景正中、向右为正；``pitch_deg`` 抬头为正；``hfov_deg`` 是输出水平视场角。
    v360 的 yaw/pitch 方向与此一致，yaw 只需从 [0, 360) 折算到 (-180, 180]。
    单线程、固定 lanczos 插值、rgb24 与 bitexact，同输入两次输出逐字节相同。
    """
    source = write_input(directory, f"source{image_suffix(request.content)}", request.content)
    streams = ff.probe(source, "-select_streams", "v:0", "-show_entries", "stream=width,height")
    if len(streams.get("streams", [])) != 1 or streams.get("_stderr"):
        raise ValueError("源全景不能解码。")
    width, height = PANO_OUTPUT_SIZES[request.aspect_ratio]
    yaw = request.yaw_deg - 360 if request.yaw_deg > 180 else request.yaw_deg
    v_fov = pano_vertical_fov(request.hfov_deg, width, height)
    v360 = (
        "v360=input=equirect:output=flat"
        f":yaw={yaw:.6f}:pitch={request.pitch_deg:.6f}"
        f":h_fov={request.hfov_deg:.6f}:v_fov={v_fov:.6f}"
        f":w={width}:h={height}:interp=lanczos"
    )
    output = directory / "output.png"
    ff.run(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-y",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            f"{v360},format=rgb24",
            "-frames:v",
            "1",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags",
            "+bitexact",
            "-c:v",
            "png",
            str(output),
        ],
        cancel,
        log=directory / "output.log",
    )
    return output


def render_audio_remix(
    ff: FFmpeg,
    request: AudioRemixRequest,
    directory: Path,
    cancel: threading.Event,
    progress: Progress,
) -> Path:
    """保留视频轨，按增益（可限定时间窗）重新混合人声与背景声。"""
    progress(0.1, "正在重新混合音轨。")
    video = write_input(directory, "input.mp4", request.video)
    voice = write_input(directory, "voice.wav", request.voice)
    background = write_input(directory, "background.wav", request.background)
    graph = (
        _volume_filter(
            1,
            "voice",
            request.voice_gain_db,
            request.voice_gain_start_seconds,
            request.voice_gain_end_seconds,
        )
        + ";"
        + _volume_filter(
            2,
            "background",
            request.background_gain_db,
            request.background_gain_start_seconds,
            request.background_gain_end_seconds,
        )
        + ";[voice][background]amix=inputs=2:duration=longest:normalize=0,"
        "alimiter=limit=0.95[audio]"
    )
    output = directory / "output.mp4"
    ff.run(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-i",
            str(voice),
            "-i",
            str(background),
            "-filter_complex",
            graph,
            "-map",
            "0:v:0",
            "-map",
            "[audio]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output),
        ],
        cancel,
        log=directory / "output.log",
    )
    progress(0.98, "处理后视频已封装。")
    return output


def _narrations(directory: Path, narrations) -> list[TimelineNarration]:
    return [
        TimelineNarration(
            write_input(directory, f"narration-{index:04d}.wav", item.content),
            item.start_clip_index,
        )
        for index, item in enumerate(narrations)
    ]


def _volume_filter(
    input_index: int, label: str, gain_db: float, start: float | None, end: float | None
) -> str:
    result = f"[{input_index}:a]volume={gain_db}dB"
    if start is not None and end is not None:
        result += f":enable='between(t,{start},{end})'"
    return f"{result}[{label}]"
