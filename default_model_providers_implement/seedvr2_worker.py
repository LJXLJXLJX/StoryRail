"""Resident SeedVR2 7B Sharp FP8 worker; deployment details stay outside Core."""

from __future__ import annotations

import argparse
import contextlib
import gc
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

_OUT = sys.stdout
_CURRENT_REQUEST_ID: str | None = None
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")
_FIELDS = {"schema", "input_video", "target_short_side", "max_long_side", "seed"}
_MODEL = "seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors"


def emit(event: str, message: str, **values: Any) -> None:
    request = {} if _CURRENT_REQUEST_ID is None else {"request_id": _CURRENT_REQUEST_ID}
    print(
        json.dumps({"event": event, "message": message, **request, **values}, ensure_ascii=False),
        file=_OUT,
        flush=True,
    )


def load(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    data = json.loads(resolved.read_bytes())
    if (
        not isinstance(data, dict)
        or set(data) != _FIELDS
        or data["schema"] != ("seedvr2_7b_sharp_fp8_request_v1")
    ):
        raise ValueError("SeedVR2 内部请求 schema 不合法。")
    task_dir = resolved.parent
    source = task_dir / str(data["input_video"])
    if source.name != "input.mp4" or not source.is_file():
        raise ValueError("SeedVR2 输入视频不存在。")
    short_side = _integer(data["target_short_side"], "target_short_side", 720, 1440)
    max_side = _integer(data["max_long_side"], "max_long_side", 1280, 2560)
    if short_side not in {720, 1080, 1440} or max_side not in {1280, 1920, 2560}:
        raise ValueError("SeedVR2 输出尺寸不受支持。")
    return {
        "task_dir": task_dir,
        "source": source,
        "target_short_side": short_side,
        "max_long_side": max_side,
        "seed": _integer(data["seed"], "seed", 0, 2**63 - 1),
    }


class SeedVR2Runtime:
    def __init__(self, repository_root: Path, model_root: Path) -> None:
        self._repository = repository_root.resolve(strict=True)
        self._model_root = model_root.resolve(strict=True)
        if not (self._repository / "inference_cli.py").is_file():
            raise RuntimeError("SeedVR2 仓库缺少 inference_cli.py。")
        for name in (_MODEL, "ema_vae_fp16.safetensors"):
            if not (self._model_root / name).is_file():
                raise RuntimeError(f"SeedVR2 模型文件缺失：{name}。")
        emit("progress", "正在初始化 SeedVR2 常驻 worker。", value=0.05, runtime_pid=os.getpid())
        sys.path.insert(0, str(self._repository))
        with contextlib.redirect_stdout(sys.stderr):
            import inference_cli
        self._cli = inference_cli
        self._cache: dict[str, Any] = {}

    def run(self, request: dict[str, Any]) -> None:
        output = request["task_dir"] / "output.mp4"
        output.unlink(missing_ok=True)
        argv = [
            "inference_cli.py",
            str(request["source"]),
            "--output",
            str(output),
            "--output_format",
            "mp4",
            "--video_backend",
            "ffmpeg",
            "--model_dir",
            str(self._model_root),
            "--dit_model",
            _MODEL,
            "--resolution",
            str(request["target_short_side"]),
            "--max_resolution",
            str(request["max_long_side"]),
            "--batch_size",
            "5",
            "--uniform_batch_size",
            "--seed",
            str(request["seed"]),
            "--dit_offload_device",
            "cpu",
            "--vae_offload_device",
            "cpu",
            "--tensor_offload_device",
            "cpu",
            "--blocks_to_swap",
            "24",
            "--swap_io_components",
            "--vae_encode_tiled",
            "--vae_decode_tiled",
            "--cache_dit",
            "--cache_vae",
        ]
        previous = sys.argv
        try:
            sys.argv = argv
            args = self._cli.parse_arguments()
        finally:
            sys.argv = previous
        emit("progress", "SeedVR2 正在复用 7B Sharp FP8 runtime。", value=0.18)
        with contextlib.redirect_stdout(sys.stderr):
            frames = self._cli.process_single_file(
                str(request["source"]), args, ["0"], str(output), False, self._cache
            )
        if not output.is_file() or frames <= 0:
            raise RuntimeError("SeedVR2 没有产生有效视频。")
        emit("progress", "SeedVR2 超分完成，模型继续驻留。", value=0.96)
        emit("result", "SeedVR2 超分完成，模型继续驻留。")

    def close(self) -> None:
        self._cache.clear()
        gc.collect()
        with contextlib.suppress(Exception):
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} 不合法。")
    return value


def serve(repository_root: Path, model_root: Path) -> int:
    global _CURRENT_REQUEST_ID
    runtime: SeedVR2Runtime | None = None
    try:
        runtime = SeedVR2Runtime(repository_root, model_root)
        emit("ready", "SeedVR2 worker 已就绪；首次任务将加载并驻留模型。", runtime_pid=os.getpid())
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if value == {"command": "shutdown"}:
                    return 0
                if (
                    not isinstance(value, dict)
                    or set(value) != {"command", "request_id", "request_file"}
                    or value["command"] != "run"
                ):
                    raise ValueError("SeedVR2 runtime command schema 不合法。")
                if not isinstance(value["request_id"], str) or not _REQUEST_ID.fullmatch(
                    value["request_id"]
                ):
                    raise ValueError("SeedVR2 request_id 不合法。")
                _CURRENT_REQUEST_ID = value["request_id"]
                runtime.run(load(Path(value["request_file"])))
            except Exception as exc:
                emit("error", f"SeedVR2 运行失败（{type(exc).__name__}）：{exc}")
                traceback.print_exc(file=sys.stderr)
            finally:
                _CURRENT_REQUEST_ID = None
        return 0
    finally:
        if runtime is not None:
            runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    args = parser.parse_args()
    return serve(args.repository_root, args.model_root)


if __name__ == "__main__":
    raise SystemExit(main())
