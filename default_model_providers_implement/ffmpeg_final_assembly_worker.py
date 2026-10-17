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
        _event("error", message=f"FFmpeg 成片装配失败：{type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


def render(request_file: Path) -> None:
    root = request_file.parent.resolve(strict=True)
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if request.get("schema") not in {
        "ffmpeg_final_assembly_request_v1",
        "ffmpeg_final_assembly_request_v2",
    }:
        raise ValueError("内部成片装配请求版本不受支持。")
    video_audio_volume = float(request.get("video_audio_volume", 1.0))
    narration_audio_volume = float(request.get("narration_audio_volume", 1.0))
    if not 0.0 <= video_audio_volume <= 2.0 or not 0.0 <= narration_audio_volume <= 2.0:
        raise ValueError("成片音量必须在 0 到 2 之间。")
    width, height = _OUTPUT_CANVAS[request["aspect_ratio"]]
    clips = request["clips"]
    narrations = request["narrations"]
    durations: list[float] = []
    normalized: list[Path] = []
    for index, clip in enumerate(clips):
        source = _owned_file(root, clip["file"])
        info = _probe(source)
        source_duration = float(info["format"]["duration"])
        if source_duration <= 0:
            raise ValueError("片段时长无效。")
        duration = float(clip["duration_seconds"])
        if duration <= 0:
            raise ValueError("片段目标时长无效。")
        durations.append(duration)
        output = root / f"normalized-{index:04d}.mp4"
        _normalize_clip(source, output, duration, width, height, _has_audio(info))
        normalized.append(output)
        _event(
            "progress",
            value=0.08 + 0.42 * (index + 1) / len(clips),
            message=f"正在统一片段规格（{index + 1}/{len(clips)}）。",
        )

    transition_cap = float(request["transition_seconds"])
    transitions = [
        0.0,
        *[
            (
                min(transition_cap, durations[index - 1] / 2, durations[index] / 2)
                if clips[index]["transition_from_previous"] == "seam_blend"
                else 0.0
            )
            for index in range(1, len(durations))
        ],
    ]
    starts = [0.0]
    for index in range(1, len(durations)):
        starts.append(starts[-1] + durations[index - 1] - transitions[index])
    visual_duration = starts[-1] + durations[-1]
    narration_durations = [
        float(_probe(_owned_file(root, item["file"]))["format"]["duration"]) for item in narrations
    ]
    required_duration = max(
        [visual_duration]
        + [
            starts[item["start_clip_index"]] + narration_durations[index]
            for index, item in enumerate(narrations)
        ]
    )
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
        video_audio_volume,
        narration_audio_volume,
        output,
    )
    _event("progress", value=0.97, message="正在封装最终 MP4。")


def _assemble(
    clips: list[Path],
    narrations: list[Path],
    clip_specs: list[dict[str, Any]],
    narration_specs: list[dict[str, Any]],
    starts: list[float],
    transitions: list[float],
    visual_duration: float,
    required_duration: float,
    video_audio_volume: float,
    narration_audio_volume: float,
    output: Path,
) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip)])
    for narration in narrations:
        command.extend(["-i", str(narration)])
    filters: list[str] = []
    # concat outputs AVTB; normalize every input so a later seam xfade has matching time bases.
    for index in range(len(clips)):
        filters.append(f"[{index}:v]fps=24,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v{index}]")
        filters.append(
            f"[{index}:a]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS,volume={video_audio_volume:.6f}[a{index}]"
        )
    video_label, audio_label = "v0", "a0"
    for index in range(1, len(clips)):
        next_video = f"vx{index}"
        next_audio = f"ax{index}"
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
        narration_labels: list[str] = []
        for index, item in enumerate(narration_specs):
            label = f"narration{index}"
            delay = round(starts[item["start_clip_index"]] * 1000)
            filters.append(
                f"[{len(clips) + index}:a]aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={narration_audio_volume:.6f},adelay={delay}:all=1[{label}]"
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


def _normalize_clip(
    source: Path, output: Path, duration: float, width: int, height: int, has_audio: bool
) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if not has_audio:
        command.extend(["-f", "lavfi", "-t", f"{duration:.6f}", "-i", "anullsrc=r=48000:cl=stereo"])
    command.extend(
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
            ("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad"),
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
    )
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


def _has_audio(info: dict[str, Any]) -> bool:
    return any(item.get("codec_type") == "audio" for item in info.get("streams", []))


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
