from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from default_model_providers_implement.codex_worker import (
    _crop_to_aspect_ratio,
    _within,
    load_request,
)

_OUT = sys.stdout
_AGENT = """---
name: storyrail-image
description: StoryRail isolated image generation worker.
mainAgent: true
subagent: false
excludeDefaultComponents: true
tools:
  - generate_image
  - finish
---
你是镜序的图片执行单元。只能调用 generate_image 一次，然后用 finish 返回生成图片的绝对路径。
不得执行命令、读取无关文件、编辑项目文件、联网搜索或创建子 Agent。
"""


def emit(event: str, message: str, **values: Any) -> None:
    print(
        json.dumps({"event": event, "message": message, **values}, ensure_ascii=False),
        file=_OUT,
        flush=True,
    )


def _prompt(operation: str, instruction: str, aspect_ratio: str, images: list[Path]) -> str:
    if operation == "generate":
        operation_text = "重新生成新画面；输入图片只作为身份、风格或空间参考。"
    else:
        operation_text = "编辑第一张底图，保留用户未要求改变的结构；其余图片只作为参考。"
    inputs = "\n".join(f"- {path}" for path in images) or "- 无"
    return (
        "调用 generate_image 严格生成一张图片。\n"
        f"任务：{operation_text}\n"
        f"目标画幅：{aspect_ratio}，必须按此画幅构图。\n"
        "输入图片路径（按顺序传给 generate_image）：\n"
        f"{inputs}\n\n"
        "具体要求：\n"
        f"{instruction}\n\n"
        "完成后只返回生成图片的绝对路径，不要附加说明。"
    )


def _write_agent(task_dir: Path) -> None:
    path = task_dir / ".agents" / "agents" / "storyrail-image" / "agent.md"
    path.parent.mkdir(parents=True)
    path.write_text(_AGENT, encoding="utf-8")


def _result_path(payload: Any, *, task_dir: Path, started_ns: int) -> Path:
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
        raise RuntimeError("AGY 没有返回结构化图片结果。")
    raw = payload["response"].strip().strip("`").strip()
    source = Path(raw).expanduser().resolve(strict=True)
    configured = os.environ.get("STORYRAIL_AGY_OUTPUT_ROOT")
    output_root = (
        Path(configured or (Path.home() / ".gemini" / "antigravity-cli" / "brain"))
        .expanduser()
        .resolve(strict=True)
    )
    if not (_within(source, task_dir) or _within(source, output_root)):
        raise RuntimeError("AGY 返回的图片不在受控输出目录内。")
    if source.stat().st_mtime_ns + 2_000_000_000 < started_ns:
        raise RuntimeError("AGY 返回的图片不是本次任务的新产物。")
    return source


def generate(
    task_dir: Path,
    operation: str,
    instruction: str,
    aspect_ratio: str,
    images: list[Path],
) -> None:
    _write_agent(task_dir)
    emit("progress", "正在连接 AGY 图片能力。", value=0.1)
    started_ns = time.time_ns()
    environment = {
        **os.environ,
        "AGY_CLI_HIDE_LOGO": "1",
        "AGY_CLI_HIDE_ACCOUNT_INFO": "1",
    }
    result = subprocess.run(
        [
            os.environ.get("STORYRAIL_AGY_CLI", "agy"),
            "--print",
            _prompt(operation, instruction, aspect_ratio, images),
            "--output-format",
            "json",
            "--agent",
            "storyrail-image",
            "--mode",
            "accept-edits",
            "--sandbox",
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
            "--print-timeout",
            "20m",
        ],
        cwd=task_dir,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=21 * 60,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AGY 返回了无法解析的结果。") from exc
    source = _result_path(payload, task_dir=task_dir, started_ns=started_ns)
    if result.returncode != 0 and not source.is_file():
        raise RuntimeError("AGY 图片生成未完成。")
    emit("progress", "正在规范化 AGY 图片。", value=0.8)
    from PIL import Image

    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        normalized = _crop_to_aspect_ratio(image.convert("RGB"), aspect_ratio)
        normalized.save(task_dir / "output.png", format="PNG", optimize=True)
    emit("result", "AGY 图片完成。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        task_dir, operation, instruction, _model, aspect_ratio, images = load_request(
            args.request_file
        )
        with contextlib.redirect_stdout(sys.stderr):
            generate(task_dir, operation, instruction, aspect_ratio, images)
        return 0
    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        emit("error", f"AGY 图片失败（{type(exc).__name__}）：{str(exc)[:1000]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
