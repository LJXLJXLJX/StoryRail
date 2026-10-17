"""Core 拥有的媒体能力提交请求。

本模块只提供确定性媒体工具的类型化请求。模型推理统一通过 recipe.RecipeRequest，
具体模型的 HTTP DTO 与约束由各插件包拥有。

`VideoFrameRequest` 是抽帧提交的 MP4 字节，不是
`structured_director.video_contracts.VideoFrameRequest`。
`PanoViewRequest` 是全景裁切提交的等距柱状全景字节与机位几何，不认识 Location。
音色设计与声音克隆已按插件 recipe 提交（`recipe.RecipeRequest`），不再有 Core 专用请求类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

_ASPECT_RATIOS = frozenset({"16:9", "9:16", "2:1"})
_IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
_64_MIB = 64 * 1024 * 1024
_512_MIB = 512 * 1024 * 1024


def _mp4(content: bytes, *, message: str, limit: int = _512_MIB) -> None:
    if not 12 <= len(content) <= limit or content[4:8] != b"ftyp":
        raise ValueError(message)


def _wav(content: bytes, *, message: str) -> None:
    if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
        raise ValueError(message)


def _aspect_ratio(value: str, message: str) -> None:
    if not isinstance(value, str) or value not in _ASPECT_RATIOS:
        raise ValueError(message)


_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def image_dimensions(content: bytes) -> tuple[int, int] | None:
    """只读 PNG IHDR 或 JPEG SOF 头取得 (宽, 高)；无法识别时返回 None。"""
    if content.startswith(_IMAGE_SIGNATURES[0]):
        if len(content) < 24 or content[12:16] != b"IHDR":
            return None
        return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
    if not content.startswith(_IMAGE_SIGNATURES[1]):
        return None
    index = 2
    while index + 4 <= len(content):
        if content[index] != 0xFF:
            return None
        marker = content[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            index += 2
            continue
        if marker in _JPEG_SOF_MARKERS:
            if index + 9 > len(content):
                return None
            height = int.from_bytes(content[index + 5 : index + 7], "big")
            width = int.from_bytes(content[index + 7 : index + 9], "big")
            return width, height
        index += 2 + int.from_bytes(content[index + 2 : index + 4], "big")
    return None


def _degrees(value: float, minimum: float, maximum: float, *, include_maximum: bool) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return False
    return minimum <= value <= maximum if include_maximum else minimum <= value < maximum


def _gain_window(start: float | None, end: float | None, label: str) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{label}开始和结束时间必须同时提供或同时省略。")
    if start is None or end is None:
        return
    if (
        any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in (start, end)
        )
        or start < 0
        or end <= start
    ):
        raise ValueError(f"{label}时间范围不合法。")


@dataclass(frozen=True, slots=True)
class AssemblyClip:
    content: bytes
    transition_from_previous: str | None
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > _512_MIB:
            raise ValueError("成片片段大小不合法。")
        _mp4(self.content, message="成片片段必须是真实 MP4。")
        if self.transition_from_previous not in {None, "seam_blend"}:
            raise ValueError("成片转场类型不受支持。")
        if not 0.05 <= self.duration_seconds <= 600:
            raise ValueError("成片片段目标时长不合法。")


@dataclass(frozen=True, slots=True)
class AssemblyNarration:
    content: bytes
    start_clip_index: int

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > _64_MIB:
            raise ValueError("旁白音频大小不合法。")
        _wav(self.content, message="旁白音频必须是真实 WAV。")
        if isinstance(self.start_clip_index, bool) or self.start_clip_index < 0:
            raise ValueError("旁白起始片段索引不合法。")


@dataclass(frozen=True, slots=True)
class AnimaticClip:
    content: bytes
    transition_from_previous: str | None
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > _64_MIB:
            raise ValueError("Animatic 关键帧图片大小不合法。")
        if not self.content.startswith(_IMAGE_SIGNATURES):
            raise ValueError("Animatic 关键帧图片必须是 PNG 或 JPEG。")
        if self.transition_from_previous not in {None, "seam_blend"}:
            raise ValueError("Animatic 转场类型不受支持。")
        if not 0.05 <= self.duration_seconds <= 600:
            raise ValueError("Animatic 片段目标时长不合法。")


@dataclass(frozen=True, slots=True)
class AnimaticNarration:
    content: bytes
    start_clip_index: int

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > _64_MIB:
            raise ValueError("Animatic 旁白音频大小不合法。")
        _wav(self.content, message="Animatic 旁白音频必须是真实 WAV。")
        if isinstance(self.start_clip_index, bool) or not 0 <= self.start_clip_index < 500:
            raise ValueError("Animatic 旁白起始片段索引不合法。")


@dataclass(frozen=True, slots=True)
class FinalAssemblyRequest:
    clips: tuple[AssemblyClip, ...]
    narrations: tuple[AssemblyNarration, ...]
    aspect_ratio: str
    transition_seconds: float = 0.1
    video_audio_volume: float = 1.0
    narration_audio_volume: float = 1.0

    def __post_init__(self) -> None:
        if not 1 <= len(self.clips) <= 500:
            raise ValueError("成片必须包含 1 到 500 个片段。")
        if self.clips[0].transition_from_previous is not None:
            raise ValueError("首个片段不能包含入场转场。")
        if len(self.narrations) > 200:
            raise ValueError("成片旁白数量过多。")
        if any(item.start_clip_index >= len(self.clips) for item in self.narrations):
            raise ValueError("旁白起始片段不存在。")
        _aspect_ratio(self.aspect_ratio, "成片画幅只允许 16:9、9:16 或 2:1。")
        if not 0.1 <= self.transition_seconds <= 1.0:
            raise ValueError("转场时长不合法。")
        for value, label in (
            (self.video_audio_volume, "视频自带音频音量"),
            (self.narration_audio_volume, "旁白音频音量"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= value <= 2.0
            ):
                raise ValueError(f"{label}必须在 0 到 2 之间。")


@dataclass(frozen=True, slots=True)
class AnimaticRequest:
    clips: tuple[AnimaticClip, ...]
    narrations: tuple[AnimaticNarration, ...]
    aspect_ratio: str
    transition_seconds: float = 0.1

    def __post_init__(self) -> None:
        if not 1 <= len(self.clips) <= 500:
            raise ValueError("Animatic 必须包含 1 到 500 个片段。")
        if len(self.narrations) > 200:
            raise ValueError("Animatic 旁白数量过多。")
        if any(item.start_clip_index >= len(self.clips) for item in self.narrations):
            raise ValueError("Animatic 旁白起始片段不存在。")
        _aspect_ratio(self.aspect_ratio, "Animatic 画幅只允许 16:9、9:16 或 2:1。")
        if not 0.1 <= self.transition_seconds <= 1.0:
            raise ValueError("Animatic 转场时长不合法。")


@dataclass(frozen=True, slots=True)
class VideoFrameRequest:
    """抽帧能力的 MP4 提交。与领域对象 video_contracts.VideoFrameRequest 不是同一类型。

    `frame_index` 从 0 开始，按解码顺序选择视频轨的第 N 帧。
    """

    content: bytes
    frame_index: int

    def __post_init__(self) -> None:
        _mp4(self.content, message="抽帧输入必须是受限 MP4 字节。")
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError("抽帧帧号必须是非负整数。")


PANO_MIN_WIDTH = 1024
PANO_MAX_WIDTH = 16384
# 机位几何范围：yaw 左闭右开，pitch 与 hfov 闭区间。Playground 与项目都只引用这里。
PANO_YAW_RANGE = (0.0, 360.0)
PANO_PITCH_RANGE = (-60.0, 60.0)
PANO_HFOV_RANGE = (20.0, 120.0)


def validate_pano_source(content: bytes) -> None:
    """全景输入：PNG/JPEG、≤64 MiB、2:1（±1 像素）且宽度在 [1024, 16384]。"""
    if not content.startswith(_IMAGE_SIGNATURES):
        raise ValueError("全景输入必须是 PNG 或 JPEG。")
    if len(content) > _64_MIB:
        raise ValueError("全景图片大小不合法。")
    size = image_dimensions(content)
    if (
        size is None
        or abs(size[0] - 2 * size[1]) > 1
        or not PANO_MIN_WIDTH <= size[0] <= PANO_MAX_WIDTH
    ):
        raise ValueError(
            f"全景必须是 2:1 等距柱状图，宽度在 {PANO_MIN_WIDTH} 到 {PANO_MAX_WIDTH} 像素之间。"
        )


def validate_pano_view_geometry(
    yaw_deg: float, pitch_deg: float, hfov_deg: float, aspect_ratio: str
) -> None:
    """全景裁切机位与输出画幅的范围校验，不依赖图片字节。"""
    if not _degrees(yaw_deg, *PANO_YAW_RANGE, include_maximum=False):
        raise ValueError("全景裁切 yaw 必须在 [0, 360) 度内。")
    if not _degrees(pitch_deg, *PANO_PITCH_RANGE, include_maximum=True):
        raise ValueError("全景裁切 pitch 必须在 [-60, 60] 度内。")
    if not _degrees(hfov_deg, *PANO_HFOV_RANGE, include_maximum=True):
        raise ValueError("全景裁切水平视场角必须在 [20, 120] 度内。")
    _aspect_ratio(aspect_ratio, "全景裁切画幅只允许 16:9、9:16 或 2:1。")


@dataclass(frozen=True, slots=True)
class PanoViewRequest:
    """全景裁切能力的提交：2:1 等距柱状全景 PNG/JPEG 与一个透视机位。

    `yaw_deg` 以全景正中为 0°、顺时针（向右）为正，范围 [0, 360)；`pitch_deg` 抬头为正，
    范围 [-60, 60]；`hfov_deg` 是输出水平视场角，范围 [20, 120]；`aspect_ratio` 是项目画幅。
    """

    content: bytes
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float
    aspect_ratio: str

    def __post_init__(self) -> None:
        validate_pano_source(self.content)
        validate_pano_view_geometry(self.yaw_deg, self.pitch_deg, self.hfov_deg, self.aspect_ratio)


@dataclass(frozen=True, slots=True)
class AudioRemixRequest:
    video: bytes
    voice: bytes
    background: bytes
    voice_gain_db: float
    background_gain_db: float
    voice_gain_start_seconds: float | None = None
    voice_gain_end_seconds: float | None = None
    background_gain_start_seconds: float | None = None
    background_gain_end_seconds: float | None = None

    def __post_init__(self) -> None:
        _mp4(self.video, message="音轨混音输入必须是真实 MP4。")
        for content in (self.voice, self.background):
            _wav(content, message="音轨混音输入必须是真实 WAV。")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or not -100 <= value <= 24
            for value in (self.voice_gain_db, self.background_gain_db)
        ):
            raise ValueError("音轨增益必须在 -100 到 24 dB 之间。")
        _gain_window(self.voice_gain_start_seconds, self.voice_gain_end_seconds, "人声音量")
        _gain_window(
            self.background_gain_start_seconds,
            self.background_gain_end_seconds,
            "背景声音量",
        )
