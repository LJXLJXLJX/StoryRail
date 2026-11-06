"""Playground 测试共用的确定性媒体字节构造。

``real_mp4_bytes`` 会生成带 ``ftyp``/``moov``/``mvhd`` 的最小合法 MP4，供导入、
抽帧帧号读取和视频时长校验使用。box 构造方式与 ``tests/test_mp4_frames.py`` 一致。
"""

from __future__ import annotations

import struct


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def _full(kind: bytes, body: bytes) -> bytes:
    return _box(kind, b"\x00\x00\x00\x00" + body)


def _video_trak(sample_count: int, *, timescale: int, duration: int) -> bytes:
    tkhd = _full(b"tkhd", b"\x00" * 8 + struct.pack(">I", 1) + b"\x00" * 68)
    mdhd = _full(b"mdhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 4)
    hdlr = _full(b"hdlr", b"\x00" * 4 + b"vide" + b"\x00" * 13)
    stsz = _full(b"stsz", struct.pack(">II", 0, sample_count))
    stbl = _box(b"stbl", stsz)
    minf = _box(b"minf", stbl)
    return _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr + minf))


_FTYP = _box(b"ftyp", b"isom\x00\x00\x02\x00isom")


def _movie_header(timescale: int, duration: int) -> bytes:
    return _full(b"mvhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 80)


def real_mp4_bytes(frame_count: int, duration_seconds: float) -> bytes:
    """带 ``mvhd`` 与视频轨的真实 box 结构 MP4；时长精确可读。"""
    timescale = 1000
    duration = round(duration_seconds * timescale)
    track = _video_trak(frame_count, timescale=timescale, duration=duration)
    moov = _box(b"moov", _movie_header(timescale, duration) + track)
    return _FTYP + moov


def png_header_bytes(width: int, height: int, *, tag: bytes = b"") -> bytes:
    """只含签名与 IHDR 的 PNG 头；足够让 Core 读出宽高，``tag`` 用于区分字节。"""
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00" * 4 + tag
