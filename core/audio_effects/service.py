from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from .models import AudioEffectMetadata, AudioEffectRequest, AudioEffectResult, TimelineEvent
from .presets import resolve_radio_parameters
from .radio import process_radio
from .wav_codec import decode_pcm_wav, encode_pcm16_wav

AUDIO_EFFECT_PROCESSOR_VERSION = 2


def apply_audio_effect(content: bytes, request: AudioEffectRequest) -> AudioEffectResult:
    """对受控 WAV bytes 应用一个确定性效果，不读取或修改项目状态。"""
    if request.effect != "radio":
        raise ValueError(f"尚未注册 audio effect：{request.effect}。")
    waveform = decode_pcm_wav(content)
    duration = len(waveform.frames[0]) / waveform.sample_rate
    start_seconds, end_seconds = _resolve_selection(request, duration)
    start_frame = round(start_seconds * waveform.sample_rate)
    end_frame = round(end_seconds * waveform.sample_rate)
    selection = type(waveform)(
        waveform.sample_rate,
        waveform.channels,
        tuple(tuple(channel[start_frame:end_frame]) for channel in waveform.frames),
    )
    parameters = resolve_radio_parameters(request.preset, request.strength, request.parameters)
    if (
        parameters.degradation_sample_rate_hz is not None
        and parameters.degradation_sample_rate_hz > selection.sample_rate
    ):
        parameters = replace(parameters, degradation_sample_rate_hz=waveform.sample_rate)
    processed = process_radio(selection, parameters, seed=request.seed)
    merged = _merge_selection(
        waveform,
        processed.waveform,
        start_frame=start_frame,
        end_frame=end_frame,
    )
    dropouts = tuple(_offset_event(item, start_seconds) for item in processed.dropouts)
    bursts = tuple(_offset_event(item, start_seconds) for item in processed.bursts)
    deterioration_envelope = tuple(
        {**item, "time": round(item["time"] + start_seconds, 6)}
        for item in processed.deterioration_envelope
    )
    metadata = AudioEffectMetadata(
        effect=request.effect,
        preset=request.preset,
        strength=request.strength,
        seed=request.seed,
        sample_rate=waveform.sample_rate,
        channels=waveform.channels,
        duration_seconds=duration,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        parameters=parameters,
        dropouts=dropouts,
        bursts=bursts,
        deterioration_envelope=deterioration_envelope,
    )
    return AudioEffectResult(encode_pcm16_wav(merged), metadata)


def audio_effect_record(request: AudioEffectRequest, result: AudioEffectResult) -> str:
    """返回适合持久化在 Generation 中的规范化请求和可复现时间线。"""
    metadata = result.metadata.to_dict()
    payload: dict[str, object] = {
        "schema": "storyrail_audio_effect_v1",
        "processor_version": AUDIO_EFFECT_PROCESSOR_VERSION,
        "request": {
            "effect": request.effect,
            "preset": request.preset,
            "strength": request.strength,
            "seed": request.seed,
            "parameters": request.parameters or {},
            "start_seconds": request.start_seconds,
            "end_seconds": request.end_seconds,
        },
        "metadata": metadata,
    }
    encoded = _canonical_json(payload)
    if len(encoded) <= 19_000:
        return encoded
    # 极长音频的事件列表可由 source + resolved parameters + seed 精确重建；记录其摘要。
    timeline = {
        "dropouts": metadata["dropouts"],
        "bursts": metadata["bursts"],
    }
    payload["metadata"] = {
        key: value for key, value in metadata.items() if key not in {"dropouts", "bursts"}
    } | {
        "events_omitted": True,
        "timeline_sha256": hashlib.sha256(_canonical_json(timeline).encode()).hexdigest(),
    }
    return _canonical_json(payload)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _resolve_selection(request: AudioEffectRequest, duration: float) -> tuple[float, float]:
    if request.start_seconds is None or request.end_seconds is None:
        return 0.0, duration
    start = float(request.start_seconds)
    end = float(request.end_seconds)
    if end > duration + 1e-9:
        raise ValueError("end_seconds 不能超过输入音频时长。")
    start_frame = round(start * 1_000_000)
    end_frame = round(end * 1_000_000)
    if start_frame >= end_frame:
        raise ValueError("后处理时间范围至少需要一个有效采样区间。")
    return start, min(end, duration)


def _merge_selection(waveform, processed, *, start_frame: int, end_frame: int):
    selection_frames = end_frame - start_frame
    if selection_frames <= 0:
        raise ValueError("后处理时间范围至少需要一个有效采样区间。")
    fade_frames = min(round(0.01 * waveform.sample_rate), selection_frames // 2)
    merged: list[tuple[float, ...]] = []
    for dry_channel, wet_channel in zip(waveform.frames, processed.frames, strict=True):
        output = list(dry_channel)
        for offset, wet in enumerate(wet_channel):
            mix = 1.0
            if start_frame > 0 and fade_frames > 0 and offset < fade_frames:
                mix = min(mix, (offset + 1) / fade_frames)
            remaining = selection_frames - offset
            if end_frame < len(dry_channel) and fade_frames > 0 and remaining <= fade_frames:
                mix = min(mix, remaining / fade_frames)
            dry = dry_channel[start_frame + offset]
            output[start_frame + offset] = dry + (wet - dry) * mix
        merged.append(tuple(output))
    return type(waveform)(waveform.sample_rate, waveform.channels, tuple(merged))


def _offset_event(event: TimelineEvent, offset: float) -> TimelineEvent:
    return TimelineEvent(
        start=round(event.start + offset, 6),
        duration=event.duration,
        attenuation_db=event.attenuation_db,
        level_dbfs=event.level_dbfs,
        source=event.source,
    )
