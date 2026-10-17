"""按帧号抽取单帧。输入输出均是媒体服务创建的任务内文件。"""

import argparse
import json
import subprocess
from pathlib import Path


def extract(request_file: Path):
    root = request_file.resolve(strict=True).parent
    request = json.loads(request_file.read_text())
    if (
        not isinstance(request, dict)
        or set(request) != {"schema", "frame_index"}
        or request["schema"] != "video_frame_v2"
        or type(request["frame_index"]) is not int
        or request["frame_index"] < 0
    ):
        raise ValueError("抽帧请求不合法。")
    index = request["frame_index"]
    source = root / "source.mp4"
    if source.is_symlink() or not source.is_file():
        raise ValueError("源视频不合法。")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_streams",
            "-show_entries",
            "frame=best_effort_timestamp:stream=time_base,width,height",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    data = json.loads(probe.stdout)
    frames = data.get("frames", [])
    if not frames or probe.stderr.strip():
        raise ValueError("源视频不能完整解码。")
    if index >= len(frames):
        raise ValueError(f"抽帧帧号超出范围：源视频只有 0-{len(frames) - 1} 帧。")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"select=eq(n\\,{index}),scale=iw*sar:ih,setsar=1",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            "1",
            str(root / "output.png"),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    (root / "frame-metadata.json").write_text(
        json.dumps(
            {
                "frame_index": index,
                "frame_count": len(frames),
                "pts": frames[index]["best_effort_timestamp"],
                "time_base": data["streams"][0]["time_base"],
                "extractor_version": 2,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", required=True, type=Path)
    extract(parser.parse_args().request_file)
