"""MiniMax H3 Comfy Core runtime 的严格内部请求。

HTTP 服务把请求写入服务端拥有的任务目录；这里只接受任务目录中的文件名，不接受调用方选择的
工作目录、模型路径、输出路径或任意命令。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FPS = 24
SCHEMA = "storyrail_h3_runtime_request_v5"
MODES = frozenset({"fl2va", "ref2va"})
STEPS = frozenset({8, 20})


@dataclass(frozen=True, slots=True)
class Request:
    task_dir: Path
    mode: str
    prompt: str
    width: int
    height: int
    duration_seconds: float
    frame_count: int
    seed: int
    steps: int
    cfg: float
    sage_attention: bool
    selflift: bool
    save_audio: bool
    first_image: Path | None
    last_image: Path | None
    additional_images: tuple[Path, ...]
    reference_audios: tuple[Path, ...]
    reference_videos: tuple[Path, ...]
    output_path: Path


def parse_request(path: Path) -> Request:
    resolved = path.resolve(strict=True)
    task_dir = resolved.parent
    raw = resolved.read_bytes()
    if len(raw) > 64 * 1024:
        raise ValueError("H3 内部请求文件过大。")
    data = json.loads(raw)
    expected = {
        "schema",
        "mode",
        "prompt",
        "width",
        "height",
        "duration_seconds",
        "seed",
        "steps",
        "cfg",
        "sage_attention",
        "selflift",
        "save_audio",
        "first_image",
        "last_image",
        "additional_images",
        "reference_audios",
        "reference_videos",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("H3 内部请求字段不符合固定 schema。")
    if data["schema"] != SCHEMA or data["mode"] not in MODES:
        raise ValueError("H3 内部请求版本或 mode 不受支持。")
    prompt = data["prompt"]
    width, height = data["width"], data["height"]
    duration = data["duration_seconds"]
    seed, steps, cfg = data["seed"], data["steps"], data["cfg"]
    if not isinstance(prompt, str) or not prompt or len(prompt) > 20_000:
        raise ValueError("H3 prompt 不合法。")
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width % 32
        or height % 32
        or not 256 <= width <= 1920
        or not 256 <= height <= 1920
        or width * height > 2_100_000
    ):
        raise ValueError("H3 画布不合法。")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0.2
    ):
        raise ValueError("H3 duration_seconds 不合法。")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise ValueError("H3 seed 不合法。")
    if isinstance(steps, bool) or steps not in STEPS:
        raise ValueError("H3 steps 只允许 20 或 8。")
    if isinstance(cfg, bool) or not isinstance(cfg, (int, float)) or not 0 <= cfg <= 30:
        raise ValueError("H3 cfg 不合法。")
    for flag in ("save_audio", "sage_attention", "selflift"):
        if not isinstance(data[flag], bool):
            raise ValueError(f"H3 {flag} 不合法。")
    first = _task_file(task_dir, data["first_image"])
    last = _task_file(task_dir, data["last_image"])
    raw_additional_images = data["additional_images"]
    if not isinstance(raw_additional_images, list) or len(raw_additional_images) > 4:
        raise ValueError("H3 附加参考图列表不合法。")
    additional_images = tuple(
        _required_task_image(task_dir, name) for name in raw_additional_images
    )
    raw_reference_audios = data["reference_audios"]
    if not isinstance(raw_reference_audios, list) or len(raw_reference_audios) > 3:
        raise ValueError("H3 参考音频列表不合法。")
    reference_audios = tuple(_required_task_audio(task_dir, name) for name in raw_reference_audios)
    raw_reference_videos = data["reference_videos"]
    if not isinstance(raw_reference_videos, list) or len(raw_reference_videos) > 3:
        raise ValueError("H3 参考视频列表不合法。")
    reference_videos = tuple(_required_task_video(task_dir, name) for name in raw_reference_videos)
    if data["mode"] == "fl2va" and first is None and last is None:
        raise ValueError("H3 FL2VA 至少需要首帧或尾帧之一。")
    if data["mode"] == "ref2va" and not any(
        (first, last, additional_images, reference_audios, reference_videos)
    ):
        raise ValueError("H3 Ref2VA 至少需要一个媒体参考。")
    if data["mode"] == "fl2va" and reference_audios:
        raise ValueError("H3 FL2VA 不能携带参考音频。")
    if data["mode"] == "fl2va" and reference_videos:
        raise ValueError("H3 FL2VA 不能携带参考视频。")
    if data["mode"] == "fl2va" and additional_images:
        raise ValueError("H3 FL2VA 不能携带附加参考图。")
    count = max(5, math.ceil(float(duration) * FPS))
    count += (5 - count) % 17
    return Request(
        task_dir=task_dir,
        mode=data["mode"],
        prompt=prompt,
        width=width,
        height=height,
        duration_seconds=float(duration),
        frame_count=count,
        seed=seed,
        steps=steps,
        cfg=float(cfg),
        sage_attention=data["sage_attention"],
        selflift=data["selflift"],
        save_audio=data["save_audio"],
        first_image=first,
        last_image=last,
        additional_images=additional_images,
        reference_audios=reference_audios,
        reference_videos=reference_videos,
        output_path=task_dir / "output.mp4",
    )


def _task_file(task_dir: Path, name: Any) -> Path | None:
    if name is None:
        return None
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("H3 输入只能引用任务目录中的文件名。")
    path = (task_dir / name).resolve(strict=True)
    path.relative_to(task_dir)
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("H3 输入图片文件不合法。")
    return path


def _required_task_audio(task_dir: Path, name: Any) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("H3 参考音频只能引用任务目录中的文件名。")
    path = (task_dir / name).resolve(strict=True)
    path.relative_to(task_dir)
    if not path.is_file() or path.suffix.lower() != ".wav":
        raise ValueError("H3 参考音频必须是 WAV。")
    return path


def _required_task_video(task_dir: Path, name: Any) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("H3 参考视频只能引用任务目录中的文件名。")
    path = (task_dir / name).resolve(strict=True)
    path.relative_to(task_dir)
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("H3 参考视频必须是 MP4。")
    return path


def _required_task_image(task_dir: Path, name: Any) -> Path:
    path = _task_file(task_dir, name)
    if path is None:
        raise ValueError("H3 附加参考图不能为空。")
    return path
