"""合成媒体字节：确定性 PNG/WAV，只用于协议与字节验证。

这些字节通过 Core 的媒体类型嗅探与 SHA-256 校验，不代表任何视觉或音质结论。
"""

from __future__ import annotations

import io
import struct
import wave
import zlib


def png(width: int = 160, height: int = 90) -> bytes:
    """指定尺寸的纯色 PNG，默认 160x90；程序化生成，逐字节确定。"""

    def chunk(kind: bytes, content: bytes) -> bytes:
        data = kind + content
        return struct.pack("!I", len(content)) + data + struct.pack("!I", zlib.crc32(data))

    pixels = b"".join(b"\0" + b"\x60\x90\xb0" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def wav(duration: float = 8) -> bytes:
    """16 kHz 单声道静音 WAV，时长精确等于 ``duration`` 秒。"""
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * int(16000 * duration))
    return output.getvalue()
