"""H3 HTTP 请求 DTO 与插件内约束；共享领域只提交 RecipeRequest。"""

from dataclasses import dataclass
from math import ceil, isfinite

H3_STEPS = (20, 8)
H3_FPS = 24
_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_32_MIB = 32 * 1024 * 1024
_64_MIB = 64 * 1024 * 1024
_512_MIB = 512 * 1024 * 1024


def h3_output_seconds(duration_seconds: float) -> float:
    """H3 服务只输出 17k+5 帧（24fps）：请求时长向上取到这个网格，最多多出 16 帧。

    成片按实际帧数交付、不裁回请求时长；提示词时间轴须写满到这里给出的结束时间。
    """
    frames = max(5, ceil(duration_seconds * H3_FPS))
    frames += (5 - frames) % 17
    return round(frames / H3_FPS, 3)


def _image_content(
    media_type: str,
    content: bytes,
    *,
    limit: int,
    type_message: str,
    size_message: str,
) -> None:
    if media_type not in _IMAGE_TYPES:
        raise ValueError(type_message)
    if not content or len(content) > limit:
        raise ValueError(size_message)


def _mp4(content: bytes, *, message: str, limit: int = _512_MIB) -> None:
    if not 12 <= len(content) <= limit or content[4:8] != b"ftyp":
        raise ValueError(message)


def _wav(content: bytes, *, message: str) -> None:
    if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
        raise ValueError(message)


def _prompt(value: str) -> None:
    if not value or len(value) > 20_000:
        raise ValueError("prompt 必须是 1 到 20000 字符。")


def _h3_canvas(width: int, height: int) -> None:
    if width % 32 or height % 32 or not 256 <= width <= 1920 or not 256 <= height <= 1920:
        raise ValueError("画布边长必须是 32 的倍数且在 256 到 1920 之间。")


def _h3_sampling(steps: int, seed: int, cfg: float, sage_attention: bool, selflift: bool) -> None:
    if isinstance(steps, bool) or steps not in H3_STEPS:
        raise ValueError("H3 步数只允许 20 或 8。")
    if not 0 <= seed <= 2**63 - 1 or not 0 <= cfg <= 30:
        raise ValueError("采样参数不合法。")
    if not isinstance(sage_attention, bool) or not isinstance(selflift, bool):
        raise ValueError("H3 sage_attention 与 selflift 必须是布尔值。")


@dataclass(frozen=True, slots=True)
class KeyframeImage:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        _image_content(
            self.media_type,
            self.content,
            limit=_64_MIB,
            type_message="关键帧图片类型不受支持。",
            size_message="关键帧图片大小不合法。",
        )


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        _image_content(
            self.media_type,
            self.content,
            limit=_64_MIB,
            type_message="参考图片类型不受支持。",
            size_message="参考图片大小不合法。",
        )


@dataclass(frozen=True, slots=True)
class ReferenceAudio:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type != "audio/wav":
            raise ValueError("H3 参考音频只接受 WAV。")
        if not self.content or len(self.content) > _64_MIB:
            raise ValueError("H3 参考音频大小不合法。")


@dataclass(frozen=True, slots=True)
class ReferenceVideo:
    media_type: str
    content: bytes
    duration_seconds: float

    def __post_init__(self) -> None:
        if self.media_type != "video/mp4":
            raise ValueError("H3 参考视频只接受 MP4。")
        _mp4(self.content, message="H3 参考视频必须是真实 MP4。")
        if not 2.0 <= self.duration_seconds <= 15.0:
            raise ValueError("H3 参考视频时长必须在 2 到 15 秒之间。")


@dataclass(frozen=True, slots=True)
class FL2VARequest:
    prompt: str
    first_frame: KeyframeImage | None = None
    last_frame: KeyframeImage | None = None
    width: int = 832
    height: int = 480
    duration_seconds: float = 3.0
    seed: int = 42
    steps: int = 20
    cfg: float = 1.0
    save_audio: bool = False
    sage_attention: bool = True
    selflift: bool = True

    def __post_init__(self) -> None:
        if self.first_frame is None and self.last_frame is None:
            raise ValueError("H3 FL2VA 至少需要首帧或尾帧之一。")
        for frame in (self.first_frame, self.last_frame):
            if frame is not None and not isinstance(frame, KeyframeImage):
                raise ValueError("关键帧图片类型不受支持。")
        _prompt(self.prompt)
        _h3_canvas(self.width, self.height)
        if self.width * self.height > 2_100_000:
            raise ValueError("画布像素过大。")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0.2:
            raise ValueError("duration_seconds 必须是不短于 0.2 秒的有限数值。")
        _h3_sampling(self.steps, self.seed, self.cfg, self.sage_attention, self.selflift)


@dataclass(frozen=True, slots=True)
class Ref2VARequest:
    prompt: str
    reference_audios: tuple[ReferenceAudio, ...]
    first_frame: ReferenceImage | None = None
    last_frame: ReferenceImage | None = None
    additional_frames: tuple[ReferenceImage, ...] = ()
    width: int = 832
    height: int = 480
    duration_seconds: float = 3.0
    seed: int = 42
    steps: int = 20
    cfg: float = 1.0
    save_audio: bool = False
    reference_videos: tuple[ReferenceVideo, ...] = ()
    sage_attention: bool = True
    selflift: bool = True

    def __post_init__(self) -> None:
        if not any(
            (
                self.first_frame,
                self.last_frame,
                self.additional_frames,
                self.reference_audios,
                self.reference_videos,
            )
        ):
            raise ValueError("Ref2VA 至少需要一个媒体参考。")
        for frame in (self.first_frame, self.last_frame):
            if frame is not None and not isinstance(frame, ReferenceImage):
                raise ValueError("参考图片类型不受支持。")
        if (
            not isinstance(self.additional_frames, tuple)
            or len(self.additional_frames) > 4
            or any(not isinstance(item, ReferenceImage) for item in self.additional_frames)
        ):
            raise ValueError("Ref2VA 附加参考图必须是最多 4 项的图片元组。")
        if (
            not isinstance(self.reference_audios, tuple)
            or len(self.reference_audios) > 3
            or any(not isinstance(item, ReferenceAudio) for item in self.reference_audios)
        ):
            raise ValueError("Ref2VA 参考音频必须是最多 3 项的元组。")
        if (
            not isinstance(self.reference_videos, tuple)
            or len(self.reference_videos) > 3
            or any(not isinstance(item, ReferenceVideo) for item in self.reference_videos)
        ):
            raise ValueError("Ref2VA 参考视频必须是最多 3 项的元组。")
        _prompt(self.prompt)
        _h3_canvas(self.width, self.height)
        if self.width * self.height > 2_100_000:
            raise ValueError("画布像素过大。")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0.2:
            raise ValueError("duration_seconds 必须是不短于 0.2 秒的有限数值。")
        _h3_sampling(self.steps, self.seed, self.cfg, self.sage_attention, self.selflift)
