"""从 MP4 容器读取首个视频轨的帧数与时长；只解析 box，不解码画面。

抽帧帧号的合法范围 `0 … frame_count-1` 由这里给出。普通 MP4 读 `stsz/stz2`
的 sample 数，分片 MP4 累加同一轨的 `trun` sample 数。
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass

_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"moof", b"traf", b"edts"}


@dataclass(frozen=True, slots=True)
class Mp4VideoFrames:
    frame_count: int
    duration_seconds: float | None


def _boxes(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            if offset + 16 > end:
                raise ValueError("MP4 box 头不完整。")
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            raise ValueError("MP4 box 长度不合法。")
        yield kind, offset + header, offset + size
        offset += size


def _child(data: bytes, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    for name, body_start, body_end in _boxes(data, start, end):
        if name == kind:
            return body_start, body_end
    return None


def _path(data: bytes, start: int, end: int, *kinds: bytes) -> tuple[int, int] | None:
    span: tuple[int, int] | None = (start, end)
    for kind in kinds:
        if span is None:
            return None
        span = _child(data, span[0], span[1], kind)
    return span


def _video_track(data: bytes, moov: tuple[int, int]) -> tuple[int, int, int] | None:
    """返回 (track_id, trak_start, trak_end)。"""
    for name, start, end in _boxes(data, *moov):
        if name != b"trak":
            continue
        hdlr = _path(data, start, end, b"mdia", b"hdlr")
        if hdlr is None or hdlr[1] - hdlr[0] < 12 or data[hdlr[0] + 8 : hdlr[0] + 12] != b"vide":
            continue
        tkhd = _child(data, start, end, b"tkhd")
        if tkhd is None:
            raise ValueError("MP4 视频轨缺少 tkhd。")
        version = data[tkhd[0]]
        track_id = struct.unpack_from(">I", data, tkhd[0] + (20 if version == 1 else 12))[0]
        return track_id, start, end
    return None


def _duration(data: bytes, trak: tuple[int, int]) -> float | None:
    mdhd = _path(data, trak[0], trak[1], b"mdia", b"mdhd")
    if mdhd is None:
        return None
    if data[mdhd[0]] == 1:
        timescale, duration = struct.unpack_from(">IQ", data, mdhd[0] + 20)
    else:
        timescale, duration = struct.unpack_from(">II", data, mdhd[0] + 12)
    if timescale <= 0 or duration <= 0 or duration == 0xFFFFFFFF:
        return None
    return duration / timescale


def _sample_table_count(data: bytes, trak: tuple[int, int]) -> int:
    stbl = _path(data, trak[0], trak[1], b"mdia", b"minf", b"stbl")
    if stbl is None:
        return 0
    stsz = _child(data, *stbl, b"stsz")
    if stsz is not None:
        return struct.unpack_from(">I", data, stsz[0] + 8)[0]
    stz2 = _child(data, *stbl, b"stz2")
    if stz2 is not None:
        return struct.unpack_from(">I", data, stz2[0] + 8)[0]
    return 0


def _fragment_count(data: bytes, track_id: int) -> int:
    total = 0
    for name, start, end in _boxes(data, 0, len(data)):
        if name != b"moof":
            continue
        for traf_name, traf_start, traf_end in _boxes(data, start, end):
            if traf_name != b"traf":
                continue
            tfhd = _child(data, traf_start, traf_end, b"tfhd")
            if tfhd is None or struct.unpack_from(">I", data, tfhd[0] + 4)[0] != track_id:
                continue
            for run_name, run_start, _run_end in _boxes(data, traf_start, traf_end):
                if run_name == b"trun":
                    total += struct.unpack_from(">I", data, run_start + 4)[0]
    return total


def read_mp4_video_frames(content: bytes) -> Mp4VideoFrames:
    """读不出视频轨或帧数为 0 时抛出 ValueError。"""
    try:
        moov = _child(content, 0, len(content), b"moov")
        if moov is None:
            raise ValueError("MP4 缺少 moov。")
        track = _video_track(content, moov)
        if track is None:
            raise ValueError("MP4 没有视频轨。")
        track_id, trak_start, trak_end = track
        count = _sample_table_count(content, (trak_start, trak_end))
        count += _fragment_count(content, track_id)
        duration = _duration(content, (trak_start, trak_end))
    except struct.error as exc:
        raise ValueError("MP4 结构不完整。") from exc
    if count < 1:
        raise ValueError("MP4 视频轨没有可抽取的帧。")
    return Mp4VideoFrames(count, duration)
