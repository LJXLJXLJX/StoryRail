"""与项目和 Playground 都无关的媒体字节工具。

包含媒体字节校验、WAV/MP4 时长读取、可读资产文件名规范化和 MP4 帧数读取。
本包没有状态，不读写文件，也不依赖任何项目或 Playground 领域概念。
"""

from __future__ import annotations

from .filenames import asset_filename as asset_filename
from .filenames import uploaded_asset_label as uploaded_asset_label
from .media_bytes import MEDIA_EXTENSION as MEDIA_EXTENSION
from .media_bytes import mp4_duration as mp4_duration
from .media_bytes import validate_media_bytes as validate_media_bytes
from .media_bytes import wav_duration as wav_duration
from .mp4_frames import Mp4VideoFrames as Mp4VideoFrames
from .mp4_frames import read_mp4_video_frames as read_mp4_video_frames

__all__ = [
    "MEDIA_EXTENSION",
    "Mp4VideoFrames",
    "asset_filename",
    "mp4_duration",
    "read_mp4_video_frames",
    "uploaded_asset_label",
    "validate_media_bytes",
    "wav_duration",
]
