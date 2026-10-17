"""JSONL 入口：常驻进程串行执行同一种固定 Comfy Core 任务（H3 FL2VA / Ref2VA 或 Qwen Image）。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from default_model_providers_implement.h3_request import parse_request
from default_model_providers_implement.qwen_image_request import (
    parse_request as parse_qwen_image_request,
)

# AIMDO/CUDA 的原生库绕过 Python redirect_stdout 直接写 fd 1。先复制 Provider
# 管道，再把进程 fd 1 指向 stderr，保证 stdout 永远只有 JSONL 协议事件。
_PROTOCOL_STDOUT = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_CURRENT_REQUEST_ID: str | None = None


def _emit(event: str, message: str, **values: Any) -> None:
    identity = {} if _CURRENT_REQUEST_ID is None else {"request_id": _CURRENT_REQUEST_ID}
    print(
        json.dumps({"event": event, "message": message, **identity, **values}, ensure_ascii=False),
        file=_PROTOCOL_STDOUT,
        flush=True,
    )


def _root(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"未配置 {name}。")
    return Path(value)


def serve() -> int:
    global _CURRENT_REQUEST_ID
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        expected_mode = os.environ.get("STORYRAIL_COMFY_CORE_MODE")
        if expected_mode not in {"fl2va", "ref2va", "qwen_image"}:
            raise RuntimeError("未配置合法的 STORYRAIL_COMFY_CORE_MODE。")
        report = lambda value, message: _emit("progress", message, value=value)  # noqa: E731
        work_root = _root("STORYRAIL_COMFY_CORE_WORK_ROOT")
        if expected_mode == "qwen_image":
            from .qwen_image import ComfyCoreQwenImageRuntime

            runtime = ComfyCoreQwenImageRuntime(_root("STORYRAIL_COMFYUI_ROOT"), work_root, report)
        else:
            from .runtime import ComfyCoreH3Runtime

            runtime = ComfyCoreH3Runtime(_root("STORYRAIL_COMFYUI_ROOT"), work_root, report)
        runtime.initialize()
        _emit("ready", "最小 Comfy Core 已加载。", value=0.10, runtime_pid=os.getpid())
        for line in sys.stdin:
            command = json.loads(line)
            if command == {"command": "shutdown"}:
                return 0
            if (
                not isinstance(command, dict)
                or set(command) != {"command", "request_id", "request_file"}
                or command.get("command") != "run"
                or not isinstance(command.get("request_id"), str)
                or _REQUEST_ID.fullmatch(command["request_id"]) is None
                or not isinstance(command.get("request_file"), str)
            ):
                raise ValueError("Comfy Core worker command 不合法。")
            _CURRENT_REQUEST_ID = command["request_id"]
            if expected_mode == "qwen_image":
                request = parse_qwen_image_request(Path(command["request_file"]))
                summary = runtime.run(_CURRENT_REQUEST_ID, request)
                _emit("result", "Qwen Image 图片已生成。", value=1.0, summary=summary)
            else:
                request = parse_request(Path(command["request_file"]))
                if request.mode != expected_mode:
                    raise ValueError(
                        f"H3 {expected_mode.upper()} runtime 收到错误 mode：{request.mode}。"
                    )
                summary = runtime.run(_CURRENT_REQUEST_ID, request)
                _emit(
                    "result",
                    f"H3 {request.mode.upper()} 视频已生成。",
                    value=1.0,
                    summary=summary,
                )
            _CURRENT_REQUEST_ID = None
        return 0
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit("error", f"{type(exc).__name__}: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", required=True)
    parser.parse_args()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
