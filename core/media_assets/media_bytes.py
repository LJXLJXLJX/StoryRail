"""媒体字节校验与时长读取；没有状态，也不读写文件。"""

from __future__ import annotations

import io
import struct
import wave

MEDIA_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "audio/wav": "wav",
    "video/mp4": "mp4",
}


def validate_media_bytes(media_type: str, content: bytes) -> None:
    maximum = 2 * 1024 * 1024 * 1024 if media_type == "video/mp4" else 64 * 1024 * 1024
    if not content or len(content) > maximum or media_type not in MEDIA_EXTENSION:
        raise ValueError("Asset 内容或媒体类型不合法。")
    signatures = {
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        "audio/wav": content.startswith(b"RIFF") and content[8:12] == b"WAVE",
        "video/mp4": len(content) >= 12 and content[4:8] == b"ftyp",
    }
    if not signatures[media_type]:
        raise ValueError("Asset 字节与声明的媒体类型不一致。")


def wav_duration(content: bytes) -> float:
    try:
        with wave.open(io.BytesIO(content), "rb") as source:
            frame_rate = source.getframerate()
            frames = source.getnframes()
    except (EOFError, wave.Error) as exc:
        raise ValueError("WAV Asset 无法读取真实时长。") from exc
    if frame_rate <= 0 or frames <= 0:
        raise ValueError("WAV Asset 时长不合法。")
    return frames / frame_rate


def mp4_duration(content: bytes) -> float:
    """Read the movie duration from the ISO BMFF ``mvhd`` box.

    Imported video is business input, so its duration must come from the bytes
    Core persists rather than from browser metadata supplied by the caller.
    """

    def boxes(start: int, end: int):
        offset = start
        while offset + 8 <= end:
            size = struct.unpack_from(">I", content, offset)[0]
            kind = content[offset + 4 : offset + 8]
            header_size = 8
            if size == 1:
                if offset + 16 > end:
                    raise ValueError("MP4 Asset 容器结构不完整。")
                size = struct.unpack_from(">Q", content, offset + 8)[0]
                header_size = 16
            elif size == 0:
                size = end - offset
            if size < header_size or offset + size > end:
                raise ValueError("MP4 Asset 容器结构不合法。")
            yield kind, offset + header_size, offset + size
            offset += size
        if offset != end:
            raise ValueError("MP4 Asset 容器结构不完整。")

    try:
        moov = next((item for item in boxes(0, len(content)) if item[0] == b"moov"), None)
        if moov is None:
            raise ValueError("MP4 Asset 缺少 movie metadata。")
        mvhd = next((item for item in boxes(moov[1], moov[2]) if item[0] == b"mvhd"), None)
        if mvhd is None:
            raise ValueError("MP4 Asset 缺少有效时长。")
        payload = mvhd[1]
        version = content[payload]
        if version == 0:
            timescale_offset, duration_offset, duration_size = payload + 12, payload + 16, 4
        elif version == 1:
            timescale_offset, duration_offset, duration_size = payload + 20, payload + 24, 8
        else:
            raise ValueError("MP4 Asset 的 movie metadata 版本不受支持。")
        if duration_offset + duration_size > mvhd[2]:
            raise ValueError("MP4 Asset 的 movie metadata 不完整。")
        timescale = struct.unpack_from(">I", content, timescale_offset)[0]
        duration = struct.unpack_from(
            ">I" if duration_size == 4 else ">Q", content, duration_offset
        )[0]
    except (IndexError, StopIteration, struct.error) as exc:
        raise ValueError("MP4 Asset 无法读取真实时长。") from exc
    if timescale <= 0 or duration <= 0 or duration == (1 << (duration_size * 8)) - 1:
        raise ValueError("MP4 Asset 时长不合法。")
    return duration / timescale


def prepend_wav_silence(content: bytes, seconds: float) -> bytes:
    """在 WAV 数据前补指定秒数的静音，其余 chunk 原样保留；用于把旁白定位到 Scene 中间。"""
    if seconds <= 0:
        return content
    if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
        raise ValueError("旁白音频必须是真实 WAV。")
    offset = 12
    block_align = sample_rate = None
    silence_byte = b"\x00"
    while offset + 8 <= len(content):
        kind = content[offset : offset + 4]
        size = struct.unpack_from("<I", content, offset + 4)[0]
        body = offset + 8
        if kind == b"fmt " and size >= 16:
            format_tag, _channels, sample_rate, _byte_rate, block_align, bits = struct.unpack_from(
                "<HHIIHH", content, body
            )
            if format_tag == 1 and bits == 8:
                # 8-bit PCM 是无符号采样，静音为 0x80。
                silence_byte = b"\x80"
        elif kind == b"data":
            if not block_align or not sample_rate:
                raise ValueError("WAV 缺少可用的 fmt chunk。")
            padding = silence_byte * (round(seconds * sample_rate) * block_align)
            data_size = size + len(padding)
            riff_size = struct.unpack_from("<I", content, 4)[0] + len(padding)
            return (
                content[:4]
                + struct.pack("<I", riff_size)
                + content[8:offset]
                + b"data"
                + struct.pack("<I", data_size)
                + padding
                + content[body:]
            )
        offset = body + size + (size & 1)
    raise ValueError("WAV 缺少 data chunk。")
