from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path


def _save_pcm_wav(
    uri,
    source,
    sample_rate,
    *,
    channels_first=True,
    format=None,
    encoding=None,
    bits_per_sample=None,
    buffer_size=4096,
    compression=None,
) -> None:
    del format, encoding, buffer_size, compression
    if bits_per_sample not in {None, 16}:
        raise ValueError("StoryRail Demucs runtime 只写出 16-bit PCM WAV。")
    samples = source.detach().cpu().numpy()
    if channels_first:
        samples = samples.transpose()
    samples = (samples.clip(-1, 1) * 32767).astype("<i2", copy=False)
    with wave.open(str(uri), "wb") as output:
        output.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


def _run_demucs(extracted: Path, output_root: Path) -> None:
    import torchaudio
    from demucs.separate import main as demucs_main

    # 新版 torchaudio.save 需要额外 TorchCodec，并受系统 FFmpeg ABI 约束。
    # Demucs 已完成限幅；在 Provider runtime 边界直接写标准 PCM，避免该可选依赖。
    torchaudio.save = _save_pcm_wav
    with contextlib.redirect_stdout(sys.stderr):
        demucs_main(
            [
                "--two-stems=vocals",
                "-n",
                "htdemucs",
                "--out",
                str(output_root),
                str(extracted),
            ]
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request_file.read_text(encoding="utf-8"))
    if request.get("schema") != "demucs_audio_separation_request_v1":
        raise ValueError("Demucs request schema 不受支持。")
    root = args.request_file.parent
    source = root / request["input"]
    extracted = root / "input.wav"
    print(
        json.dumps({"event": "progress", "value": 0.08, "message": "正在提取视频音轨。"}),
        flush=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_f32le",
            str(extracted),
        ],
        check=True,
    )
    print(
        json.dumps({"event": "progress", "value": 0.15, "message": "正在运行 Demucs 两轨分离。"}),
        flush=True,
    )
    output_root = root / "demucs-output"
    _run_demucs(extracted, output_root)
    filename = "vocals.wav" if request["stem"] == "voice" else "no_vocals.wav"
    candidate = output_root / "htdemucs" / "input" / filename
    if not candidate.is_file():
        raise RuntimeError("Demucs 未生成预期 stem。")
    shutil.copyfile(candidate, root / "output.wav")
    print(
        json.dumps({"event": "progress", "value": 0.98, "message": "分离音轨已写入。"}), flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
