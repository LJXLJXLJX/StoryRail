from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from math import isfinite

from .wav_codec import DecodedWave, decode_pcm_wav, encode_pcm16_wav

AUDIO_TRIM_PROCESSOR_VERSION = 1


@dataclass(frozen=True, slots=True)
class AudioTrimRequest:
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in (self.start_seconds, self.end_seconds)
        ):
            raise ValueError("音频截取时间必须是有限数字。")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("音频截取结束时间必须晚于非负的开始时间。")


@dataclass(frozen=True, slots=True)
class AudioTrimMetadata:
    sample_rate: int
    channels: int
    source_duration_seconds: float
    start_seconds: float
    end_seconds: float
    output_duration_seconds: float


@dataclass(frozen=True, slots=True)
class AudioTrimResult:
    audio: bytes
    metadata: AudioTrimMetadata


def trim_audio(content: bytes, request: AudioTrimRequest) -> AudioTrimResult:
    waveform = decode_pcm_wav(content)
    frame_count = len(waveform.frames[0])
    source_duration = frame_count / waveform.sample_rate
    if request.end_seconds > source_duration + 1e-9:
        raise ValueError("音频截取结束时间不能超过源音频时长。")
    start_frame = round(request.start_seconds * waveform.sample_rate)
    end_frame = min(frame_count, round(request.end_seconds * waveform.sample_rate))
    if start_frame >= end_frame:
        raise ValueError("音频截取范围至少需要包含一个采样帧。")
    if start_frame == 0 and end_frame == frame_count:
        raise ValueError("音频截取范围必须短于完整源音频。")
    trimmed = DecodedWave(
        waveform.sample_rate,
        waveform.channels,
        tuple(tuple(channel[start_frame:end_frame]) for channel in waveform.frames),
    )
    output = encode_pcm16_wav(trimmed)
    metadata = AudioTrimMetadata(
        sample_rate=waveform.sample_rate,
        channels=waveform.channels,
        source_duration_seconds=source_duration,
        start_seconds=start_frame / waveform.sample_rate,
        end_seconds=end_frame / waveform.sample_rate,
        output_duration_seconds=(end_frame - start_frame) / waveform.sample_rate,
    )
    return AudioTrimResult(output, metadata)


def audio_trim_record(request: AudioTrimRequest, result: AudioTrimResult) -> str:
    record = {
        "schema": "storyrail_audio_trim_v1",
        "processor_version": AUDIO_TRIM_PROCESSOR_VERSION,
        "request": {
            "start_seconds": request.start_seconds,
            "end_seconds": request.end_seconds,
        },
        "metadata": asdict(result.metadata),
        "output_sha256": hashlib.sha256(result.audio).hexdigest(),
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
