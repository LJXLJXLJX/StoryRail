"""Standalone WSL worker; this file intentionally has no StoryRail imports."""

from __future__ import annotations

import argparse
import contextlib
import gc
import json
import os
import random
import re
import sys
import traceback
import wave
from pathlib import Path
from typing import Any

_OUT = sys.stdout
_CURRENT_REQUEST_ID: str | None = None
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")
_MODEL_FILES = {
    "config.yaml",
    "gpt.pth",
    "s2mel.pth",
    "codec.pth",
    "wav2vec2bert_stats.pt",
    "multilingual_zh_ja_yue_char_del.tiktoken",
}


def emit(event: str, message: str, **values: Any) -> None:
    request = {} if _CURRENT_REQUEST_ID is None else {"request_id": _CURRENT_REQUEST_ID}
    print(
        json.dumps(
            {"event": event, "message": message, **request, **values},
            ensure_ascii=False,
        ),
        file=_OUT,
        flush=True,
    )


def load(path: Path, model_root: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    task_dir = resolved.parent
    data = json.loads(resolved.read_bytes())
    expected = {
        "schema",
        "text",
        "seed",
        "duration_factor",
        "emotion_vector",
        "voice_file",
        "language",
    }
    if (
        not isinstance(data, dict)
        or set(data) != expected
        or data["schema"] != "indextts2_request_v2"
    ):
        raise ValueError("IndexTTS2 内部请求 schema 不合法。")
    if not isinstance(data["text"], str) or not data["text"] or len(data["text"]) > 20_000:
        raise ValueError("IndexTTS2 text 不合法。")
    if (
        isinstance(data["seed"], bool)
        or not isinstance(data["seed"], int)
        or not 0 <= data["seed"] <= 2**63 - 1
    ):
        raise ValueError("IndexTTS2 seed 不合法。")
    if (
        isinstance(data["duration_factor"], bool)
        or not isinstance(data["duration_factor"], (int, float))
        or not 0.5 <= data["duration_factor"] <= 2
    ):
        raise ValueError("IndexTTS2 duration_factor 不合法。")
    vector = data["emotion_vector"]
    if (
        not isinstance(vector, list)
        or len(vector) != 8
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not -1 <= value <= 1
            for value in vector
        )
    ):
        raise ValueError("IndexTTS2 emotion_vector 不合法。")
    if data["language"] not in ("auto", "zh", "en"):
        raise ValueError("IndexTTS2 language 不合法。")
    name = data["voice_file"]
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("IndexTTS2 voice_file 不合法。")
    voice = (task_dir / name).resolve(strict=True)
    voice.relative_to(task_dir)
    model = model_root.resolve(strict=True)
    missing = sorted(item for item in _MODEL_FILES if not (model / item).is_file())
    if missing:
        raise RuntimeError("IndexTTS2 模型文件缺失：" + ", ".join(missing))
    return {**data, "task_dir": task_dir, "voice": voice, "model_root": model}


class IndexTTS2Runtime:
    def __init__(self, model_root: Path) -> None:
        emit("progress", "正在加载 IndexTTS2 2.5。", value=0.08, runtime_pid=os.getpid())
        import numpy
        import torch as torch_module
        from indextts.infer_v2_5 import IndexTTS2

        self._numpy = numpy
        self._torch = torch_module
        self._tts: Any | None = IndexTTS2(
            cfg_path=str(model_root / "config.yaml"),
            model_dir=str(model_root),
            use_bf16=torch_module.cuda.is_available() and torch_module.cuda.is_bf16_supported(),
            use_cuda_kernel=False,
            use_deepspeed=False,
            use_accel=False,
            use_torch_compile=False,
            use_qwen_emo=False,
        )

    def run(self, request: dict[str, Any]) -> None:
        tts = self._tts
        if tts is None:
            raise RuntimeError("IndexTTS2 runtime 已释放。")
        seed = request["seed"]
        random.seed(seed)
        self._numpy.random.seed(seed % (2**32))
        self._torch.manual_seed(seed)
        if self._torch.cuda.is_available():
            self._torch.cuda.manual_seed_all(seed)
        tts.gr_progress = lambda value, desc="正在生成语音": emit(
            "progress", str(desc), value=max(0.2, min(0.92, 0.2 + float(value) * 0.72))
        )
        emotion = tts.normalize_emo_vec(list(request["emotion_vector"]), apply_bias=True)
        output = request["task_dir"] / "output.wav"
        output.unlink(missing_ok=True)
        emit("progress", "正在复用已驻留的 IndexTTS2 合成语音。", value=0.2)
        try:
            result = tts.infer(
                spk_audio_prompt=str(request["voice"]),
                text=request["text"],
                output_path=str(output),
                lang="zhen" if request["language"] == "auto" else request["language"],
                emo_audio_prompt=None,
                emo_alpha=1.0,
                emo_vector=emotion,
                use_emo_text=False,
                emo_text=None,
                use_random=False,
                verbose=False,
                max_text_tokens_per_segment=120,
                duration_factor=float(request["duration_factor"]),
            )
            if result is None or not output.is_file():
                raise RuntimeError("IndexTTS2 未生成 WAV。")
            with wave.open(str(output), "rb") as audio:
                emit(
                    "result",
                    "IndexTTS2 完成，模型继续驻留。",
                    sample_rate=audio.getframerate(),
                    frame_count=audio.getnframes(),
                    channels=audio.getnchannels(),
                )
        finally:
            tts.gr_progress = None

    def close(self) -> None:
        self._tts = None
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.synchronize()
            self._torch.cuda.empty_cache()
            with contextlib.suppress(RuntimeError):
                self._torch.cuda.ipc_collect()
        gc.collect()


def _serve(model_root: Path) -> int:
    global _CURRENT_REQUEST_ID
    runtime: IndexTTS2Runtime | None = None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            runtime = IndexTTS2Runtime(model_root)
        emit("ready", "IndexTTS2 已加载并驻留。", runtime_pid=os.getpid())
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if value == {"command": "shutdown"}:
                    emit("stopping", "IndexTTS2 正在释放。")
                    return 0
                if not isinstance(value, dict) or set(value) != {
                    "command",
                    "request_id",
                    "request_file",
                }:
                    raise ValueError("IndexTTS2 runtime command schema 不合法。")
                request_id = value["request_id"]
                request_file = value["request_file"]
                if (
                    value["command"] != "run"
                    or not isinstance(request_id, str)
                    or not _REQUEST_ID.fullmatch(request_id)
                    or not isinstance(request_file, str)
                ):
                    raise ValueError("IndexTTS2 runtime command 不合法。")
                _CURRENT_REQUEST_ID = request_id
                request = load(Path(request_file), model_root)
                with contextlib.redirect_stdout(sys.stderr):
                    runtime.run(request)
            except Exception as exc:
                print(traceback.format_exc(), file=sys.stderr, flush=True)
                emit("error", f"IndexTTS2 失败（{type(exc).__name__}）：{str(exc)[:1000]}")
            finally:
                _CURRENT_REQUEST_ID = None
        return 0
    finally:
        if runtime is not None:
            with contextlib.redirect_stdout(sys.stderr):
                runtime.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return _serve(args.model_root.resolve(strict=True))
    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        emit("error", f"IndexTTS2 失败（{type(exc).__name__}）：{str(exc)[:1000]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
