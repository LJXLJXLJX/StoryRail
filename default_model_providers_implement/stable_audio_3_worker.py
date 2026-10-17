"""Stable Audio 3 Medium 一次性生成。由 Windows 模型服务通过 WSL 调用。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def load_request(path: Path) -> dict[str, object]:
    request = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("schema") != "stable_audio_3_request_v1":
        raise ValueError("Stable Audio request schema 不受支持。")
    prompt = request.get("prompt")
    duration = request.get("duration_seconds")
    seed = request.get("seed")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
        raise ValueError("prompt 不合法。")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("duration_seconds 不合法。")
    if not 1 <= float(duration) <= 380:
        raise ValueError("duration_seconds 超出范围。")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed 不合法。")
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    args = parser.parse_args()
    request = load_request(args.request_file)
    root = args.request_file.parent
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    print(
        json.dumps({"event": "progress", "value": 0.05, "message": "正在加载 Stable Audio 3。"}),
        flush=True,
    )
    import torchaudio
    from stable_audio_3 import StableAudioModel

    model = StableAudioModel.from_pretrained("medium", model_half=True)
    print(
        json.dumps({"event": "progress", "value": 0.35, "message": "正在生成音频。"}),
        flush=True,
    )
    audio = model.generate(
        prompt=str(request["prompt"]),
        duration=float(request["duration_seconds"]),
        steps=8,
        cfg_scale=1.0,
        seed=int(request["seed"]),
        chunked_decode=True,
    )
    torchaudio.save(str(root / "output.wav"), audio[0].cpu(), model.model.sample_rate)
    print(
        json.dumps({"event": "progress", "value": 1.0, "message": "音频已写好。"}),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps({"event": "error", "message": str(exc)}),
            flush=True,
        )
        sys.exit(1)
