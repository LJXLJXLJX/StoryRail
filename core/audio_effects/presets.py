from __future__ import annotations

from dataclasses import asdict, replace

from .models import ParameterValue, RadioParameters

_PRESETS = {
    "walkie_talkie": RadioParameters(
        300,
        3500,
        -20,
        3.0,
        8,
        90,
        2.0,
        1.35,
        12_000,
        -37,
        450,
        3300,
        0.10,
        45,
        130,
        -12,
        0.03,
        0.12,
        12,
        45,
        -25,
        True,
        0.05,
        -1.0,
    ),
    "military_radio": RadioParameters(
        280,
        3200,
        -24,
        4.0,
        5,
        75,
        3.0,
        1.55,
        8_000,
        -33,
        350,
        3100,
        0.22,
        35,
        150,
        -16,
        0.08,
        0.22,
        10,
        55,
        -22,
        True,
        0.12,
        -1.0,
    ),
    "weak_signal": RadioParameters(
        320,
        3400,
        -22,
        3.5,
        7,
        100,
        2.5,
        1.45,
        12_000,
        -31,
        400,
        3400,
        0.40,
        45,
        180,
        -14,
        0.10,
        0.35,
        12,
        65,
        -20,
        True,
        0.25,
        -1.0,
    ),
    "bad_signal": RadioParameters(
        380,
        3000,
        -25,
        4.5,
        5,
        80,
        3.0,
        1.75,
        8_000,
        -25,
        450,
        3000,
        0.90,
        55,
        260,
        -22,
        0.22,
        0.80,
        15,
        100,
        -15,
        True,
        0.48,
        -1.0,
    ),
    "dying_transmission": RadioParameters(
        320,
        3300,
        -24,
        4.0,
        6,
        90,
        2.5,
        1.60,
        12_000,
        -31,
        400,
        3300,
        0.70,
        45,
        330,
        -18,
        0.25,
        0.65,
        15,
        130,
        -18,
        True,
        1.0,
        -1.0,
    ),
}


def preset_names() -> tuple[str, ...]:
    return tuple(_PRESETS)


def resolve_radio_parameters(
    preset: str,
    strength: float,
    overrides: dict[str, ParameterValue] | None = None,
) -> RadioParameters:
    try:
        target = _PRESETS[preset]
    except KeyError as exc:
        raise ValueError(f"未知 radio preset：{preset}。") from exc

    # strength 在干净传输和 preset 目标之间插值；显式 override 最后应用。
    values = asdict(target)
    values.update(
        high_pass_hz=_lerp(20.0, target.high_pass_hz, strength),
        compression_threshold_db=_lerp(0.0, target.compression_threshold_db, strength),
        compression_ratio=_lerp(1.0, target.compression_ratio, strength),
        makeup_gain_db=target.makeup_gain_db * strength,
        saturation_drive=_lerp(1.0, target.saturation_drive, strength),
        noise_dbfs=_amplitude_scaled_db(target.noise_dbfs, strength),
        dropout_rate_hz=target.dropout_rate_hz * strength,
        dropout_attenuation_db=target.dropout_attenuation_db * strength,
        dropout_silence_probability=target.dropout_silence_probability * strength,
        burst_rate_hz=target.burst_rate_hz * strength,
        burst_dbfs=_amplitude_scaled_db(target.burst_dbfs, strength),
        edge_bursts=target.edge_bursts and strength > 0,
        deterioration=target.deterioration * strength,
    )
    if strength == 0:
        values["degradation_sample_rate_hz"] = None
    if overrides:
        unknown = sorted(set(overrides) - set(values))
        if unknown:
            raise ValueError(f"未知 radio 参数：{', '.join(unknown)}。")
        values.update(overrides)
    return replace(target, **values)


def _lerp(start: float, end: float, amount: float) -> float:
    return start + (end - start) * amount


def _amplitude_scaled_db(level_db: float, strength: float) -> float:
    if strength <= 0:
        return -120.0
    # dBFS level + 20log10(strength)，避免在 preset 间复制 DSP。
    from math import log10

    return level_db + 20 * log10(strength)
