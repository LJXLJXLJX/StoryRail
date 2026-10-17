from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request_file.read_text(encoding="utf-8"))
    if request.get("schema") not in {
        "ffmpeg_audio_remix_request_v1",
        "ffmpeg_audio_remix_request_v2",
    }:
        raise ValueError("FFmpeg audio remix schema 不受支持。")
    root = args.request_file.parent
    print(
        json.dumps({"event": "progress", "value": 0.1, "message": "正在重新混合音轨。"}), flush=True
    )
    filter_graph = (
        _volume_filter(request, 1, "voice") + ";" + _volume_filter(request, 2, "background") + ";"
        "[voice][background]amix=inputs=2:duration=longest:normalize=0,"
        "alimiter=limit=0.95[audio]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(root / request["video"]),
            "-i",
            str(root / request["voice"]),
            "-i",
            str(root / request["background"]),
            "-filter_complex",
            filter_graph,
            "-map",
            "0:v:0",
            "-map",
            "[audio]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(root / "output.mp4"),
        ],
        check=True,
    )
    print(
        json.dumps({"event": "progress", "value": 0.98, "message": "处理后视频已封装。"}),
        flush=True,
    )
    return 0


def _volume_filter(request: dict[str, object], input_index: int, prefix: str) -> str:
    result = f"[{input_index}:a]volume={request[f'{prefix}_gain_db']}dB"
    start = request.get(f"{prefix}_gain_start_seconds")
    end = request.get(f"{prefix}_gain_end_seconds")
    if start is not None and end is not None:
        result += f":enable='between(t,{start},{end})'"
    return f"{result}[{prefix}]"


if __name__ == "__main__":
    raise SystemExit(main())
