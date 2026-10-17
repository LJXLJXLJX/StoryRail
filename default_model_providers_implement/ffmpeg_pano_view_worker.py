"""把 2:1 等距柱状全景按机位裁切成透视 PNG。输入输出均是媒体服务创建的任务内文件。

几何约定：`yaw_deg` ∈ [0, 360)，0° 为全景正中，顺时针（向右）为正；
`pitch_deg` ∈ [-60, 60]，抬头为正；`hfov_deg` ∈ [20, 120] 是输出水平视场角。
v360 的 yaw 正方向同样向右、pitch 正方向向上，yaw 只需从 [0, 360) 折算到 (-180, 180]。

垂直视场角不是按画幅线性缩放：透视投影平面上半宽 = tan(hfov/2)，半高 = 半宽 · 高/宽，
所以 v_fov = 2 · atan(tan(hfov/2) · 高/宽)。例如 hfov=90° 时 16:9 的 v_fov ≈ 58.7°，
9:16 的 v_fov ≈ 121.3°。

确定性：单线程解码与滤镜、固定 lanczos 插值与 rgb24 输出，去掉元数据并使用 bitexact，
同输入两次输出逐字节相同。
"""

import argparse
import json
import math
import subprocess
from pathlib import Path

SCHEMA = "pano_view_v1"
MIN_WIDTH = 1024
MAX_WIDTH = 16384
# 长边固定 2048，短边按画幅取偶数。
OUTPUT_SIZES = {"16:9": (2048, 1152), "9:16": (1152, 2048), "2:1": (2048, 1024)}
SOURCES = frozenset({"source.png", "source.jpg"})


def _finite(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def check_view(yaw_deg, pitch_deg, hfov_deg, aspect_ratio) -> None:
    if not _finite(yaw_deg) or not 0 <= yaw_deg < 360:
        raise ValueError("全景裁切 yaw 必须在 [0, 360) 度内。")
    if not _finite(pitch_deg) or not -60 <= pitch_deg <= 60:
        raise ValueError("全景裁切 pitch 必须在 [-60, 60] 度内。")
    if not _finite(hfov_deg) or not 20 <= hfov_deg <= 120:
        raise ValueError("全景裁切水平视场角必须在 [20, 120] 度内。")
    if aspect_ratio not in OUTPUT_SIZES:
        raise ValueError("全景裁切画幅只允许 16:9、9:16 或 2:1。")


def vertical_fov(hfov_deg: float, width: int, height: int) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) * height / width))


def render(request_file: Path):
    root = request_file.resolve(strict=True).parent
    request = json.loads(request_file.read_text())
    if (
        not isinstance(request, dict)
        or set(request) != {"schema", "source", "yaw_deg", "pitch_deg", "hfov_deg", "aspect_ratio"}
        or request["schema"] != SCHEMA
        or request["source"] not in SOURCES
    ):
        raise ValueError("全景裁切请求不合法。")
    yaw, pitch, hfov = request["yaw_deg"], request["pitch_deg"], request["hfov_deg"]
    check_view(yaw, pitch, hfov, request["aspect_ratio"])
    source = root / request["source"]
    if source.is_symlink() or not source.is_file():
        raise ValueError("源全景不合法。")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    if len(streams) != 1 or probe.stderr.strip():
        raise ValueError("源全景不能解码。")
    source_width, source_height = streams[0]["width"], streams[0]["height"]
    if abs(source_width - 2 * source_height) > 1 or not MIN_WIDTH <= source_width <= MAX_WIDTH:
        raise ValueError(
            f"全景必须是 2:1 等距柱状图，宽度在 {MIN_WIDTH} 到 {MAX_WIDTH} 像素之间；"
            f"实际 {source_width}×{source_height}。"
        )
    width, height = OUTPUT_SIZES[request["aspect_ratio"]]
    v360 = (
        "v360=input=equirect:output=flat"
        f":yaw={yaw - 360 if yaw > 180 else yaw:.6f}:pitch={pitch:.6f}"
        f":h_fov={hfov:.6f}:v_fov={vertical_fov(hfov, width, height):.6f}"
        f":w={width}:h={height}:interp=lanczos"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-nostdin",
            "-y",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            f"{v360},format=rgb24",
            "-frames:v",
            "1",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags",
            "+bitexact",
            "-c:v",
            "png",
            str(root / "output.png"),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", required=True, type=Path)
    render(parser.parse_args().request_file)
