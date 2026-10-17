from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

_OUTPUT_CANVAS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "2:1": (1920, 960)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        render(arguments.request_file.resolve(strict=True))
    except Exception as exc:
        _event("error", message=f"FFmpeg Animatic 预览失败：{type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


def render(request_file: Path) -> None:
    root = request_file.parent.resolve(strict=True)
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if request.get("schema") != "ffmpeg_animatic_request_v1":
        raise ValueError("内部 Animatic 请求版本不受支持。")
    width, height = _OUTPUT_CANVAS[request["aspect_ratio"]]
    clips = request["clips"]
    narrations = request["narrations"]
    durations = [float(clip["duration_seconds"]) for clip in clips]
    if any(duration <= 0 for duration in durations):
        raise ValueError("片段目标时长无效。")
    normalized: list[Path] = []
    for index, clip in enumerate(clips):
        source = _owned_file(root, clip["file"])
        output = root / f"normalized-{index:04d}.mp4"
        _normalize_image(source, output, durations[index], width, height)
        normalized.append(output)
        _event(
            "progress",
            value=0.08 + 0.42 * (index + 1) / len(clips),
            message=f"正在统一片段规格（{index + 1}/{len(clips)}）。",
        )

    transition_cap = float(request["transition_seconds"])
    transitions = _transition_plan(
        durations,
        [clip["transition_from_previous"] for clip in clips],
        transition_cap,
    )
    starts = _clip_starts(durations, transitions)
    visual_duration = starts[-1] + durations[-1]
    narration_durations = [
        float(_probe(_owned_file(root, item["file"]))["format"]["duration"]) for item in narrations
    ]
    required_duration = _required_duration(visual_duration, starts, narrations, narration_durations)
    _event("progress", value=0.55, message="正在建立转场与旁白时间线。")
    output = root / "output.mp4"
    _assemble(
        normalized,
        [_owned_file(root, item["file"]) for item in narrations],
        clips,
        narrations,
        starts,
        transitions,
        visual_duration,
        required_duration,
        output,
    )
    _event("progress", value=0.97, message="正在封装最终 MP4。")


def _transition_plan(
    durations: list[float],
    transitions: list[str | None],
    transition_cap: float,
) -> list[float]:
    return [
        0.0,
        *[
            min(transition_cap, durations[index - 1] / 2, durations[index] / 2)
            if transitions[index] is not None
            else 0.0
            for index in range(1, len(durations))
        ],
    ]


def _clip_starts(durations: list[float], transitions: list[float]) -> list[float]:
    starts = [0.0]
    for index in range(1, len(durations)):
        starts.append(starts[-1] + durations[index - 1] - transitions[index])
    return starts


def _required_duration(
    visual_duration: float,
    starts: list[float],
    narrations: list[dict[str, Any]],
    narration_durations: list[float],
) -> float:
    return max(
        [visual_duration]
        + [
            starts[item["start_clip_index"]] + narration_durations[index]
            for index, item in enumerate(narrations)
        ]
    )


def _assemble(
    clips: list[Path],
    narrations: list[Path],
    clip_specs: list[dict[str, Any]],
    narration_specs: list[dict[str, Any]],
    starts: list[float],
    transitions: list[float],
    visual_duration: float,
    required_duration: float,
    output: Path,
) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip)])
    for narration in narrations:
        command.extend(["-i", str(narration)])
    filters: list[str] = []
    for index in range(len(clips)):
        filters.append(f"[{index}:v]fps=24,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v{index}]")
        filters.append(
            f"[{index}:a]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
    video_label, audio_label = "v0", "a0"
    for index in range(1, len(clips)):
        next_video = f"vx{index}"
        next_audio = f"ax{index}"
        if transitions[index] > 0:
            transition = "fade"
            filters.append(
                f"[{video_label}][v{index}]xfade=transition={transition}:"
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
        narration_labels: list[str] = []
        for index, item in enumerate(narration_specs):
            label = f"narration{index}"
            delay = round(starts[item["start_clip_index"]] * 1000)
            filters.append(
                f"[{len(clips) + index}:a]aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"adelay={delay}:all=1[{label}]"
            )
            narration_labels.append(label)
        inputs = "".join(f"[{item}]" for item in [audio_label, *narration_labels])
        filters.append(
            f"{inputs}amix=inputs={1 + len(narration_labels)}:duration=longest:"
            "dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]"
        )
        audio_label = "aout"
    if filters:
        command.extend(["-filter_complex", ";".join(filters)])
    command.extend(
        [
            "-map",
            f"[{video_label}]" if ":" not in video_label else video_label,
            "-map",
            f"[{audio_label}]" if ":" not in audio_label else audio_label,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-t",
            f"{required_duration:.6f}",
            str(output),
        ]
    )
    _run(command)


def _normalize_image(source: Path, output: Path, duration: float, width: int, height: int) -> None:
    command = [
        "ffmpeg",
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
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{duration:.6f}",
        str(output),
    ]
    _run(command)


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or not isinstance(value.get("format"), dict):
        raise ValueError("ffprobe 没有返回有效媒体信息。")
    return value


def _owned_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("内部媒体文件名不合法。")
    path = (root / name).resolve(strict=True)
    path.relative_to(root)
    return path


def _run(command: list[str]) -> None:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[-2_000:] or f"退出码 {result.returncode}"
        raise RuntimeError(f"FFmpeg 执行失败：{detail}")


def _event(kind: str, **fields: object) -> None:
    print(json.dumps({"event": kind, **fields}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
