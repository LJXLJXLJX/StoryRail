from __future__ import annotations

import random
from dataclasses import dataclass
from math import exp, isfinite, pi, sqrt, tanh

from .models import RadioParameters, TimelineEvent
from .wav_codec import DecodedWave


@dataclass(frozen=True, slots=True)
class RadioProcessResult:
    waveform: DecodedWave
    dropouts: tuple[TimelineEvent, ...]
    bursts: tuple[TimelineEvent, ...]
    deterioration_envelope: tuple[dict[str, float], ...]


def process_radio(
    waveform: DecodedWave,
    parameters: RadioParameters,
    *,
    seed: int,
) -> RadioProcessResult:
    parameters.validate(waveform.sample_rate)
    rng = random.Random(seed)
    sample_rate = waveform.sample_rate
    frame_count = len(waveform.frames[0])
    duration = frame_count / sample_rate

    channels = [list(channel) for channel in waveform.frames]
    channels = [
        _radio_band_pass(channel, parameters.high_pass_hz, parameters.low_pass_hz, sample_rate)
        for channel in channels
    ]
    _compress_linked(channels, sample_rate, parameters)
    _saturate(channels, parameters.saturation_drive)
    if parameters.degradation_sample_rate_hz is not None:
        _degrade_sample_rate(
            channels,
            sample_rate,
            parameters.degradation_sample_rate_hz,
            parameters.deterioration,
        )

    dropouts = _schedule_dropouts(rng, duration, parameters)
    bursts = _schedule_bursts(rng, duration, dropouts, parameters)
    _apply_dropouts(channels, sample_rate, dropouts)
    _add_static(channels, sample_rate, rng, parameters)
    _add_bursts(channels, sample_rate, rng, bursts, parameters)
    _apply_output_ceiling(channels, parameters.output_ceiling_dbfs)
    if any(not isfinite(sample) for channel in channels for sample in channel):
        raise ValueError("DSP 产生了非有限采样。")

    envelope = tuple(
        {
            "time": round(duration * position, 6),
            "amount": round(parameters.deterioration * position, 6),
            "noise_multiplier": round(1 + 3 * parameters.deterioration * position, 6),
            "dropout_multiplier": round(1 + 2 * parameters.deterioration * position, 6),
        }
        for position in (0.0, 0.5, 1.0)
    )
    return RadioProcessResult(
        DecodedWave(sample_rate, waveform.channels, tuple(tuple(item) for item in channels)),
        dropouts,
        bursts,
        envelope,
    )


def _low_pass(samples: list[float], cutoff: float, sample_rate: int) -> list[float]:
    alpha = 1 - exp(-2 * pi * cutoff / sample_rate)
    output: list[float] = []
    state = 0.0
    for sample in samples:
        state += alpha * (sample - state)
        output.append(state)
    return output


def _high_pass(samples: list[float], cutoff: float, sample_rate: int) -> list[float]:
    decay = exp(-2 * pi * cutoff / sample_rate)
    output: list[float] = []
    state = 0.0
    previous = 0.0
    for sample in samples:
        state = decay * (state + sample - previous)
        previous = sample
        output.append(state)
    return output


def _radio_band_pass(
    samples: list[float], high_pass_hz: float, low_pass_hz: float, sample_rate: int
) -> list[float]:
    # 两级一阶滤波形成稳定的二阶滚降，无需引入平台相关的外部 DSP 库。
    output = _high_pass(samples, high_pass_hz, sample_rate)
    output = _high_pass(output, high_pass_hz, sample_rate)
    output = _low_pass(output, low_pass_hz, sample_rate)
    return _low_pass(output, low_pass_hz, sample_rate)


def _compress_linked(channels: list[list[float]], sample_rate: int, p: RadioParameters) -> None:
    attack = exp(-1 / (sample_rate * p.compression_attack_ms / 1000))
    release = exp(-1 / (sample_rate * p.compression_release_ms / 1000))
    makeup = 10 ** (p.makeup_gain_db / 20)
    envelope = 0.0
    threshold = 10 ** (p.compression_threshold_db / 20)
    for index in range(len(channels[0])):
        level = max(abs(channel[index]) for channel in channels)
        coefficient = attack if level > envelope else release
        envelope = coefficient * envelope + (1 - coefficient) * level
        gain = 1.0
        if envelope > threshold and threshold > 0:
            compressed = threshold * (envelope / threshold) ** (1 / p.compression_ratio)
            gain = compressed / envelope
        for channel in channels:
            channel[index] *= gain * makeup


def _saturate(channels: list[list[float]], drive: float) -> None:
    normalization = tanh(drive)
    for channel in channels:
        for index, sample in enumerate(channel):
            channel[index] = tanh(sample * drive) / normalization


def _degrade_sample_rate(
    channels: list[list[float]], source_rate: int, target_rate: int, deterioration: float
) -> None:
    # 零阶保持模拟传输端降采样再恢复。dying preset 会让目标速率沿时间继续下降。
    phase = 0.0
    held = [0.0] * len(channels)
    frame_count = len(channels[0])
    for index in range(frame_count):
        progress = index / max(1, frame_count - 1)
        effective_rate = target_rate * (1 - 0.58 * deterioration * progress)
        phase += effective_rate / source_rate
        if index == 0 or phase >= 1.0:
            phase %= 1.0
            held = [channel[index] for channel in channels]
        for channel_index, channel in enumerate(channels):
            channel[index] = held[channel_index]


def _schedule_dropouts(
    rng: random.Random, duration: float, p: RadioParameters
) -> tuple[TimelineEvent, ...]:
    if p.dropout_rate_hz <= 0 or duration <= 0:
        return ()
    events: list[TimelineEvent] = []
    maximum_rate = p.dropout_rate_hz * (1 + 2 * p.deterioration)
    cursor = rng.expovariate(maximum_rate)
    while cursor < duration:
        progress = cursor / duration
        relative_rate = (1 + 2 * p.deterioration * progress) / (1 + 2 * p.deterioration)
        if rng.random() <= relative_rate:
            event_duration = (
                rng.uniform(p.dropout_duration_min_ms, p.dropout_duration_max_ms) / 1000
            )
            attenuation = p.dropout_attenuation_db * (1 + 1.7 * p.deterioration * progress)
            if rng.random() < p.dropout_silence_probability * (1 + progress) / 2:
                attenuation = -100.0
            events.append(
                TimelineEvent(
                    round(cursor, 6),
                    round(min(event_duration, duration - cursor), 6),
                    round(max(-100.0, attenuation), 3),
                    source="random",
                )
            )
        cursor += rng.expovariate(maximum_rate)
    return tuple(events)


def _schedule_bursts(
    rng: random.Random,
    duration: float,
    dropouts: tuple[TimelineEvent, ...],
    p: RadioParameters,
) -> tuple[TimelineEvent, ...]:
    if duration <= 0:
        return ()
    events: list[TimelineEvent] = []

    def add(start: float, source: str) -> None:
        length = rng.uniform(p.burst_duration_min_ms, p.burst_duration_max_ms) / 1000
        start = max(0.0, min(start, max(0.0, duration - length)))
        progress = start / duration
        level = p.burst_dbfs + 8 * p.deterioration * progress
        events.append(
            TimelineEvent(
                round(start, 6),
                round(min(length, duration - start), 6),
                level_dbfs=round(min(-3.0, level), 3),
                source=source,
            )
        )

    if p.edge_bursts:
        add(0.0, "start")
        if duration > p.burst_duration_min_ms / 500:
            add(max(0.0, duration - p.burst_duration_max_ms / 1000), "end")
    for dropout in dropouts:
        if rng.random() < 0.48:
            add(dropout.start, "dropout")
    if p.burst_rate_hz > 0:
        cursor = rng.expovariate(p.burst_rate_hz)
        while cursor < duration:
            add(cursor, "random")
            cursor += rng.expovariate(p.burst_rate_hz)
    return tuple(sorted(events, key=lambda item: (item.start, item.source or "")))


def _apply_dropouts(
    channels: list[list[float]], sample_rate: int, events: tuple[TimelineEvent, ...]
) -> None:
    frame_count = len(channels[0])
    for event in events:
        start = min(frame_count, round(event.start * sample_rate))
        end = min(frame_count, start + max(1, round(event.duration * sample_rate)))
        base_gain = 10 ** ((event.attenuation_db or 0.0) / 20)
        fade_frames = min(max(1, round(0.004 * sample_rate)), max(1, (end - start) // 3))
        for index in range(start, end):
            edge = min(index - start + 1, end - index, fade_frames) / fade_frames
            gain = 1 - (1 - base_gain) * edge
            for channel in channels:
                channel[index] *= gain


def _add_static(
    channels: list[list[float]], sample_rate: int, rng: random.Random, p: RadioParameters
) -> None:
    frame_count = len(channels[0])
    white = [rng.uniform(-1.0, 1.0) for _ in range(frame_count)]
    noise = _low_pass(
        _high_pass(white, p.noise_high_pass_hz, sample_rate),
        p.noise_low_pass_hz,
        sample_rate,
    )
    rms = sqrt(sum(sample * sample for sample in noise) / max(1, frame_count))
    base = (10 ** (p.noise_dbfs / 20)) / max(rms, 1e-12)
    for index, sample in enumerate(noise):
        progress = index / max(1, frame_count - 1)
        gain = base * (1 + 3 * p.deterioration * progress)
        # 同一传输静电馈入所有声道，避免 stereo 声像随机漂移。
        for channel in channels:
            channel[index] += sample * gain


def _add_bursts(
    channels: list[list[float]],
    sample_rate: int,
    rng: random.Random,
    events: tuple[TimelineEvent, ...],
    p: RadioParameters,
) -> None:
    frame_count = len(channels[0])
    for event in events:
        start = min(frame_count, round(event.start * sample_rate))
        length = min(frame_count - start, max(1, round(event.duration * sample_rate)))
        if length <= 0:
            continue
        white = [rng.uniform(-1.0, 1.0) for _ in range(length)]
        noise = _low_pass(
            _high_pass(white, p.noise_high_pass_hz, sample_rate), p.noise_low_pass_hz, sample_rate
        )
        rms = sqrt(sum(sample * sample for sample in noise) / length)
        gain = (10 ** ((event.level_dbfs or -120.0) / 20)) / max(rms, 1e-12)
        for offset, sample in enumerate(noise):
            window = _burst_window(offset, length)
            for channel in channels:
                channel[start + offset] += sample * gain * window


def _burst_window(index: int, length: int) -> float:
    attack = max(1, length // 8)
    release = max(1, length // 3)
    return min(1.0, (index + 1) / attack, (length - index) / release)


def _apply_output_ceiling(channels: list[list[float]], ceiling_dbfs: float) -> None:
    ceiling = 10 ** (ceiling_dbfs / 20)
    peak = max((abs(sample) for channel in channels for sample in channel), default=0.0)
    if peak <= ceiling or peak == 0:
        return
    # 只在需要防止非法溢出时施加统一保护增益，不做逐文件响度 normalize。
    gain = ceiling / peak
    for channel in channels:
        for index in range(len(channel)):
            channel[index] *= gain
