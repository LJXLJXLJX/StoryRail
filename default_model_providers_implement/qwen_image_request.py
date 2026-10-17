"""Qwen Image Comfy Core runtime 的严格内部请求。

HTTP 服务把请求写入服务端拥有的任务目录；这里只接受任务目录中的图片文件名，不接受调用方选择的
工作目录、模型路径、节点或输出路径。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "storyrail_qwen_image_request_v1"
MAX_IMAGES = 5
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@dataclass(frozen=True, slots=True)
class QwenImageRequest:
    task_dir: Path
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    cfg: float
    seed: int
    images: tuple[Path, ...]
    output_path: Path


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"Qwen 图片 {name} 不合法。")
    return value


def parse_request(path: Path) -> QwenImageRequest:
    resolved = path.resolve(strict=True)
    task_dir = resolved.parent
    raw = resolved.read_bytes()
    if len(raw) > 128 * 1024:
        raise ValueError("Qwen 图片内部请求文件过大。")
    data = json.loads(raw)
    expected = {
        "schema",
        "prompt",
        "negative_prompt",
        "width",
        "height",
        "steps",
        "cfg",
        "seed",
        "images",
    }
    if not isinstance(data, dict) or set(data) != expected or data["schema"] != SCHEMA:
        raise ValueError("Qwen 图片内部请求不符合固定 schema。")
    prompt, negative = data["prompt"], data["negative_prompt"]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        raise ValueError("Qwen 图片 prompt 不合法。")
    if not isinstance(negative, str) or len(negative) > 4_000:
        raise ValueError("Qwen 图片 negative_prompt 不合法。")
    width = _integer(data["width"], "width", 256, 2048)
    height = _integer(data["height"], "height", 256, 2048)
    if width % 32 or height % 32:
        raise ValueError("Qwen 图片画布必须对齐到 32 像素网格。")
    steps = _integer(data["steps"], "steps", 4, 60)
    seed = _integer(data["seed"], "seed", 0, 2**63 - 1)
    cfg = data["cfg"]
    if (
        isinstance(cfg, bool)
        or not isinstance(cfg, int | float)
        or not math.isfinite(cfg)
        or not 1 <= cfg <= 8
    ):
        raise ValueError("Qwen 图片 cfg 不合法。")
    names = data["images"]
    if not isinstance(names, list) or len(names) > MAX_IMAGES:
        raise ValueError("Qwen 图片输入列表不合法。")
    return QwenImageRequest(
        task_dir=task_dir,
        prompt=prompt,
        negative_prompt=negative,
        width=width,
        height=height,
        steps=steps,
        cfg=float(cfg),
        seed=seed,
        images=tuple(_task_image(task_dir, name) for name in names),
        output_path=task_dir / "output.png",
    )


def _task_image(task_dir: Path, name: object) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Qwen 图片输入只能引用任务目录中的文件名。")
    path = (task_dir / name).resolve(strict=True)
    path.relative_to(task_dir)
    if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("Qwen 图片输入文件不合法。")
    return path
