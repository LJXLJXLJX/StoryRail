from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 与 strict_json.IMAGE_ASPECT_RATIOS 一致；worker 作为独立脚本运行，不导入服务包。
_IMAGE_ASPECT_RATIOS = frozenset(
    {
        "16:9",
        "9:16",
        "2:1",
        "1:2",
        "1:1",
        "3:2",
        "2:3",
        "4:3",
        "3:4",
        "5:4",
        "4:5",
        "21:9",
        "9:21",
        "3:1",
        "1:3",
    }
)

_OUT = sys.stdout


def emit(event: str, message: str, **values: Any) -> None:
    print(
        json.dumps({"event": event, "message": message, **values}, ensure_ascii=False),
        file=_OUT,
        flush=True,
    )


@dataclass(slots=True)
class _ObservedTurnResult:
    status: Any
    items: list[Any]


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    if minutes == 0:
        return f"{remainder} 秒"
    if remainder == 0:
        return f"{minutes} 分钟"
    return f"{minutes} 分 {remainder} 秒"


def _waiting_message(stage: str, elapsed_seconds: float) -> str:
    return f"{stage}；已等待 {_format_elapsed(elapsed_seconds)}。"


def _turn_progress_update(event: Any) -> str | None:
    """把 Codex turn 事件翻译成人可读的图片执行阶段。"""

    payload = getattr(event, "payload", None)
    if getattr(event, "method", None) == "error":
        error = getattr(payload, "error", None)
        message = str(getattr(error, "message", "连接异常")).strip() or "连接异常"
        if len(message) > 240:
            message = message[:237] + "..."
        if bool(getattr(payload, "will_retry", False)):
            return f"Codex 连接中断，正在自动重试：{message}"
        return f"Codex 连接异常：{message}"
    if getattr(event, "method", None) != "item/started":
        return None
    wrapped = getattr(payload, "item", None)
    item = getattr(wrapped, "root", wrapped)
    item_type = getattr(item, "type", None)
    if item_type == "imageGeneration":
        return "远端图片服务正在生成图片"
    if item_type == "dynamicToolCall":
        tool = getattr(item, "tool", None)
        if tool == "exec":
            return "Codex 已提交图片任务，等待远端图片服务"
        if tool == "wait":
            return "远端图片任务仍在处理，等待结果返回"
    return None


async def _observe_turn(
    turn: Any,
    *,
    heartbeat_seconds: float = 15.0,
) -> _ObservedTurnResult:
    """消费 turn 事件，并把远端等待与可恢复连接异常投影给 Provider。"""

    started_at = time.monotonic()
    stage = "Codex 正在准备图片任务"
    items: list[Any] = []
    completed: Any | None = None
    finished = asyncio.Event()

    async def heartbeat() -> None:
        while True:
            try:
                await asyncio.wait_for(finished.wait(), timeout=heartbeat_seconds)
                return
            except TimeoutError:
                emit(
                    "progress",
                    _waiting_message(stage, time.monotonic() - started_at),
                    value=0.35,
                )

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        async for event in turn.stream():
            update = _turn_progress_update(event)
            if update is not None:
                stage = update
                emit(
                    "progress",
                    _waiting_message(stage, time.monotonic() - started_at),
                    value=0.35,
                )
            method = getattr(event, "method", None)
            payload = getattr(event, "payload", None)
            if method == "item/completed":
                item = getattr(payload, "item", None)
                if item is not None:
                    items.append(item)
            elif method == "turn/completed":
                completed = payload
    finally:
        finished.set()
        await heartbeat_task

    if completed is None:
        raise RuntimeError("Codex turn 已结束但没有返回完成事件。")
    completed_turn = getattr(completed, "turn", None)
    if completed_turn is None:
        raise RuntimeError("Codex turn 完成事件缺少结果。")
    status = getattr(completed_turn, "status", None)
    if getattr(status, "value", str(status)) == "failed":
        error = getattr(completed_turn, "error", None)
        message = str(getattr(error, "message", "Codex 图片生成失败。"))
        raise RuntimeError(message)
    return _ObservedTurnResult(status=status, items=items)


def load_request(path: Path) -> tuple[Path, str, str, str, str, list[Path]]:
    resolved = path.resolve(strict=True)
    task_dir = resolved.parent
    data = json.loads(resolved.read_bytes())
    if not isinstance(data, dict) or set(data) != {
        "schema",
        "operation",
        "instruction",
        "model",
        "aspect_ratio",
        "images",
    }:
        raise ValueError("Codex 内部请求字段不合法。")
    if data["schema"] != "codex_image_request_v3":
        raise ValueError("Codex 内部请求版本不受支持。")
    if data["operation"] not in {"generate", "edit"}:
        raise ValueError("Codex 图片 operation 不合法。")
    if not isinstance(data["instruction"], str) or not data["instruction"]:
        raise ValueError("Codex instruction 不合法。")
    if not isinstance(data["model"], str) or not data["model"]:
        raise ValueError("Codex model 不合法。")
    if data["aspect_ratio"] not in _IMAGE_ASPECT_RATIOS:
        raise ValueError("Codex 图片画幅不在支持的比例中。")
    if not isinstance(data["images"], list) or len(data["images"]) > 5:
        raise ValueError("Codex images 不合法。")
    images = []
    for name in data["images"]:
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("Codex 输入只能引用任务目录文件。")
        image = (task_dir / name).resolve(strict=True)
        image.relative_to(task_dir)
        images.append(image)
    if data["operation"] == "edit" and not images:
        raise ValueError("Codex 图片编辑缺少底图。")
    return (
        task_dir,
        data["operation"],
        data["instruction"],
        data["model"],
        data["aspect_ratio"],
        images,
    )


async def generate(
    task_dir: Path,
    operation: str,
    instruction: str,
    model: str,
    aspect_ratio: str,
    images: list[Path],
) -> None:
    try:
        from openai_codex import AsyncCodex, LocalImageInput, Sandbox, TextInput
    except ImportError as exc:
        raise RuntimeError("Codex runtime 未安装 openai-codex。") from exc
    emit("progress", "正在连接 Codex 图片能力。", value=0.1)
    async with AsyncCodex() as codex:
        account = (await codex.account(refresh_token=False)).account
        account_value = getattr(account, "root", account)
        if getattr(account_value, "type", None) != "chatgpt":
            raise RuntimeError("Codex runtime 尚未登录 ChatGPT 账户。")
        thread = await codex.thread_start(
            model=model,
            sandbox=Sandbox.read_only,
            cwd=str(task_dir),
            ephemeral=True,
            developer_instructions=(
                "你是镜序的图片执行单元。只能调用 imagegen；"
                "不得使用 Shell、Python、浏览器或编辑项目文件。"
                "operation=generate 时，输入图只是身份、风格或空间参考，需要重新生成新画面；"
                "operation=edit 时，第一张输入图是必须保留主体结构的编辑底图，其余图片只是参考。"
                "严格遵守用户指令，只返回一张图片。回复与工具理由使用中文。"
            ),
        )
        operation_text = (
            "这是重新生成任务：参考图只用于约束，不要把第一张图误当成必须保留构图的底图。"
            if operation == "generate"
            else "这是图片编辑任务：第一张输入图是编辑底图，保持未要求改变的空间结构和视觉锚点。"
        )
        turn = await thread.turn(
            [
                TextInput(
                    "请使用 $imagegen 严格完成一张图片。\n"
                    + operation_text
                    + f"\n目标画幅固定为 {aspect_ratio}。必须按这一画幅构图，并尽量使用高分辨率。"
                    + "\n\n具体要求：\n"
                    + instruction
                ),
                *(LocalImageInput(str(path)) for path in images),
            ]
        )
        emit("progress", "Codex 正在准备图片任务。", value=0.25)
        response = await _observe_turn(turn)
    if getattr(response.status, "value", str(response.status)) != "completed":
        raise RuntimeError("Codex 图片生成未完成。")
    generated = []
    for wrapped in response.items:
        item = getattr(wrapped, "root", wrapped)
        saved = getattr(item, "saved_path", None)
        if getattr(item, "type", None) == "imageGeneration" and saved:
            generated.append(Path(str(getattr(saved, "root", saved))).resolve(strict=True))
    source = _select_generated_image(generated)
    if len(generated) > 1:
        emit(
            "progress",
            f"Codex 返回了 {len(generated)} 张图片，采用最后一张作为本次候选。",
            value=0.75,
        )
    allowed_roots = [task_dir]
    configured = __import__("os").environ.get("STORYRAIL_CODEX_OUTPUT_ROOT")
    if configured:
        allowed_roots.append(Path(configured).resolve(strict=True))
    if not any(_within(source, root) for root in allowed_roots):
        raise RuntimeError("Codex 返回的图片不在受控目录内。")
    emit("progress", "正在规范化 Codex 图片。", value=0.8)
    from PIL import Image

    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        normalized = _crop_to_aspect_ratio(image.convert("RGB"), aspect_ratio)
        normalized.save(task_dir / "output.png", format="PNG", optimize=True)
    emit("result", "Codex 图片完成。")


def _select_generated_image(generated: list[Path]) -> Path:
    if not generated:
        raise RuntimeError("Codex 没有返回 imageGeneration 图片。")
    return generated[-1]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _crop_to_aspect_ratio(image: Any, aspect_ratio: str) -> Any:
    """保留原图内最大的目标画幅区域，不主动降低像素尺寸。"""
    width_ratio, height_ratio = (int(value) for value in aspect_ratio.split(":"))
    unit = min(image.width // width_ratio, image.height // height_ratio)
    if unit < 1:
        raise ValueError(f"Codex 图片尺寸过小，无法规范化为 {aspect_ratio}。")
    width, height = unit * width_ratio, unit * height_ratio
    left = (image.width - width) // 2
    top = (image.height - height) // 2
    return image.crop((left, top, left + width, top + height))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        task_dir, operation, instruction, model, aspect_ratio, images = load_request(
            args.request_file
        )
        with contextlib.redirect_stdout(sys.stderr):
            asyncio.run(generate(task_dir, operation, instruction, model, aspect_ratio, images))
        return 0
    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        emit("error", f"Codex 图片失败（{type(exc).__name__}）：{str(exc)[:1000]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
