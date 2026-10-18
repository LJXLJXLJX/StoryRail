"""视频抽帧与视频输入的严格值对象；不读取项目或执行媒体任务。"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields


def _id(value: object, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise ValueError(f"{label} 必须是有效 ID。")


LEGACY_TAIL_EXTRACTOR_VERSION = 1
FRAME_INDEX_EXTRACTOR_VERSION = 2


@dataclass(frozen=True, slots=True)
class VideoFrameRequest:
    """一次按帧号抽帧的冻结输入。

    `frame_index` 从 0 开始，`frame_count` 是 Core 提交前从源 MP4 读出的视频帧总数。
    `source_segment_id` 只在从 Segment 视频抽取时记录来源，用于展示血缘，不形成
    程序级续接保证。extractor_version 1 只用于 schema v21 读入的历史尾帧任务，
    其帧号未知。
    """

    source_video_asset_id: str
    source_sha256: str
    frame_index: int | None
    frame_count: int | None
    source_segment_id: str | None = None
    extractor_version: int = FRAME_INDEX_EXTRACTOR_VERSION

    def __post_init__(self) -> None:
        _id(self.source_video_asset_id, "source_video_asset_id")
        _id(self.source_segment_id, "source_segment_id", optional=True)
        if (
            not isinstance(self.source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
        ):
            raise ValueError("源视频摘要不合法。")
        if self.extractor_version == LEGACY_TAIL_EXTRACTOR_VERSION:
            if self.frame_index is not None or self.frame_count is not None:
                raise ValueError("历史尾帧任务不能声明帧号。")
            return
        if self.extractor_version != FRAME_INDEX_EXTRACTOR_VERSION:
            raise ValueError("抽帧处理版本不受支持。")
        if type(self.frame_count) is not int or self.frame_count < 1:
            raise ValueError("源视频帧数不合法。")
        if type(self.frame_index) is not int or not 0 <= self.frame_index < self.frame_count:
            raise ValueError(f"抽帧帧号必须在 0-{self.frame_count - 1} 之间。")


@dataclass(frozen=True, slots=True)
class VideoInputSnapshot:
    input_signature: str
    start_asset_id: str | None
    end_asset_id: str | None
    dialogue_signature: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.input_signature, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.input_signature) is None
        ):
            raise ValueError("视频输入签名不合法。")
        for name in ("start_asset_id", "end_asset_id"):
            _id(getattr(self, name), name, optional=True)
        if (
            self.dialogue_signature is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.dialogue_signature) is None
        ):
            raise ValueError("对白输入签名不合法。")


def parse_video_value(cls, value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
        raise ValueError("视频快照包含缺失或未声明字段。")
    return cls(**value)
