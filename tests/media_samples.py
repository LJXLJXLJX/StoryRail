"""按标签生成的确定性媒体字节：不同标签字节不同，时长与帧数可被 Core 读取。"""

import hashlib
import io
import struct
import wave


def png_bytes(label: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + label.encode()


def panorama_png_bytes(label: str, width: int = 2048) -> bytes:
    """带 IHDR 的 2:1 PNG 头，满足全景裁切的宽高契约。"""
    ihdr = struct.pack(">II", width, width // 2) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + label.encode()


def wav_bytes(label: str, duration_seconds: float, sample_rate: int = 8_000) -> bytes:
    """合法 PCM WAV；采样内容由标签重复填充，保证不同标签字节不同。"""
    frames = round(duration_seconds * sample_rate)
    pattern = hashlib.sha256(label.encode()).digest()
    pcm = (pattern * (frames * 2 // len(pattern) + 1))[: frames * 2]
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm)
    return output.getvalue()


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def _full(kind: bytes, body: bytes) -> bytes:
    return _box(kind, b"\x00\x00\x00\x00" + body)


def mp4_bytes(label: str, duration_seconds: float, fps: int = 24) -> bytes:
    """只含 box 结构的 MP4：mvhd/mdhd 时长与 stsz 帧数可被 Core 读取，标签放在 free box。"""
    timescale = 1000
    duration = round(duration_seconds * timescale)
    frames = max(1, round(duration_seconds * fps))
    mvhd = _full(b"mvhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 80)
    tkhd = _full(b"tkhd", b"\x00" * 8 + struct.pack(">I", 1) + b"\x00" * 68)
    mdhd = _full(b"mdhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 4)
    hdlr = _full(b"hdlr", b"\x00" * 4 + b"vide" + b"\x00" * 13)
    stsz = _full(b"stsz", struct.pack(">II", 0, frames))
    trak = _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr + _box(b"minf", _box(b"stbl", stsz))))
    return (
        _box(b"ftyp", b"isom\x00\x00\x02\x00isom")
        + _box(b"moov", mvhd + trak)
        + _box(b"free", label.encode())
    )
