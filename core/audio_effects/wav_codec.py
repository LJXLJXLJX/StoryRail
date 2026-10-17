from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from struct import pack, unpack_from


@dataclass(frozen=True, slots=True)
class DecodedWave:
    sample_rate: int
    channels: int
    frames: tuple[tuple[float, ...], ...]


def decode_pcm_wav(content: bytes) -> DecodedWave:
    if not content:
        raise ValueError("输入 WAV 不能为空。")
    try:
        with wave.open(io.BytesIO(content), "rb") as source:
            if source.getcomptype() != "NONE":
                raise ValueError("仅支持未压缩 PCM WAV。")
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            raw = source.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise ValueError("输入不是有效的 PCM WAV。") from exc
    if not 1 <= channels <= 8:
        raise ValueError("WAV 声道数必须在 1 到 8 之间。")
    if not 8_000 <= sample_rate <= 384_000:
        raise ValueError("WAV 采样率不受支持。")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError("WAV PCM 位深只支持 8/16/24/32-bit。")
    if frame_count <= 0:
        raise ValueError("WAV 必须至少包含一个采样帧。")
    expected = frame_count * channels * sample_width
    if len(raw) != expected:
        raise ValueError("WAV PCM 数据长度不完整。")

    decoded: list[list[float]] = [[] for _ in range(channels)]
    offset = 0
    for _ in range(frame_count):
        for channel in range(channels):
            if sample_width == 1:
                value = (raw[offset] - 128) / 128.0
            elif sample_width == 2:
                value = unpack_from("<h", raw, offset)[0] / 32768.0
            elif sample_width == 3:
                integer = int.from_bytes(raw[offset : offset + 3], "little", signed=False)
                if integer & 0x800000:
                    integer -= 1 << 24
                value = integer / 8388608.0
            else:
                value = unpack_from("<i", raw, offset)[0] / 2147483648.0
            decoded[channel].append(value)
            offset += sample_width
    return DecodedWave(sample_rate, channels, tuple(tuple(item) for item in decoded))


def encode_pcm16_wav(waveform: DecodedWave) -> bytes:
    if len(waveform.frames) != waveform.channels or not waveform.frames:
        raise ValueError("音频声道数据不完整。")
    frame_count = len(waveform.frames[0])
    if frame_count <= 0 or any(len(channel) != frame_count for channel in waveform.frames):
        raise ValueError("音频声道长度不一致。")
    raw = bytearray()
    for index in range(frame_count):
        for channel in waveform.frames:
            sample = max(-1.0, min(1.0, channel[index]))
            integer = max(-32768, min(32767, round(sample * 32767)))
            raw.extend(pack("<h", integer))
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(waveform.channels)
        destination.setsampwidth(2)
        destination.setframerate(waveform.sample_rate)
        destination.writeframes(raw)
    return output.getvalue()
