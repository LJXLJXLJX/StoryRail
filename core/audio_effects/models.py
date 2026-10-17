from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from re import fullmatch
from typing import TypeAlias

ParameterValue: TypeAlias = float | int | bool | None


@dataclass(frozen=True, slots=True)
class AudioEffectRequest:
    effect: str
    preset: str
    strength: float = 1.0
    seed: int = 0
    parameters: dict[str, ParameterValue] | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.effect, str) or not fullmatch(r"[a-z][a-z0-9_]{0,63}", self.effect):
            raise ValueError("effect 标识不合法。")
        if not isinstance(self.preset, str) or not self.preset:
            raise ValueError("preset 必须是非空字符串。")
        if (
            isinstance(self.strength, bool)
            or not isinstance(self.strength, (int, float))
            or not isfinite(self.strength)
        ):
            raise ValueError("strength 必须是有限数字。")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("strength 必须在 0 到 1 之间。")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= 2**63 - 1
        ):
            raise ValueError("seed 必须是 0 到 2^63-1 之间的整数。")
        if self.parameters is not None and not isinstance(self.parameters, dict):
            raise ValueError("parameters 必须是对象或 null。")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("start_seconds 和 end_seconds 必须同时提供或同时省略。")
        if self.start_seconds is not None and (
            isinstance(self.start_seconds, bool)
            or not isinstance(self.start_seconds, (int, float))
            or not isfinite(self.start_seconds)
            or self.start_seconds < 0
        ):
            raise ValueError("start_seconds 必须是非负有限数字。")
        if self.end_seconds is not None and (
            isinstance(self.end_seconds, bool)
            or not isinstance(self.end_seconds, (int, float))
            or not isfinite(self.end_seconds)
            or self.end_seconds <= (self.start_seconds or 0)
        ):
            raise ValueError("end_seconds 必须是大于 start_seconds 的有限数字。")


@dataclass(frozen=True, slots=True)
class RadioParameters:
    high_pass_hz: float
    low_pass_hz: float
    compression_threshold_db: float
    compression_ratio: float
    compression_attack_ms: float
    compression_release_ms: float
    makeup_gain_db: float
    saturation_drive: float
    degradation_sample_rate_hz: int | None
    noise_dbfs: float
    noise_high_pass_hz: float
    noise_low_pass_hz: float
    dropout_rate_hz: float
    dropout_duration_min_ms: float
    dropout_duration_max_ms: float
    dropout_attenuation_db: float
    dropout_silence_probability: float
    burst_rate_hz: float
    burst_duration_min_ms: float
    burst_duration_max_ms: float
    burst_dbfs: float
    edge_bursts: bool
    deterioration: float
    output_ceiling_dbfs: float

    def validate(self, sample_rate: int) -> None:
        values = asdict(self)
        if not isinstance(self.edge_bursts, bool):
            raise ValueError("edge_bursts 必须是 boolean。")
        if self.degradation_sample_rate_hz is not None and (
            isinstance(self.degradation_sample_rate_hz, bool)
            or not isinstance(self.degradation_sample_rate_hz, int)
        ):
            raise ValueError("degradation_sample_rate_hz 必须是整数或 null。")
        numeric_values = {
            key: value
            for key, value in values.items()
            if key not in {"edge_bursts", "degradation_sample_rate_hz"}
        }
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in numeric_values.values()
        ):
            raise ValueError("radio 数值参数必须是有限数字。")
        nyquist = sample_rate / 2
        if not 0 < self.high_pass_hz < self.low_pass_hz < nyquist:
            raise ValueError("radio EQ 频率必须满足 0 < high_pass < low_pass < Nyquist。")
        if not 0 < self.noise_high_pass_hz < self.noise_low_pass_hz < nyquist:
            raise ValueError("noise 频率必须满足 0 < high_pass < low_pass < Nyquist。")
        if self.compression_ratio < 1:
            raise ValueError("compression_ratio 必须至少为 1。")
        if self.compression_attack_ms <= 0 or self.compression_release_ms <= 0:
            raise ValueError("compressor attack/release 必须大于 0。")
        if self.saturation_drive < 1:
            raise ValueError("saturation_drive 必须至少为 1。")
        if self.degradation_sample_rate_hz is not None and not (
            2_000 <= self.degradation_sample_rate_hz <= sample_rate
        ):
            raise ValueError("degradation_sample_rate_hz 必须在 2000 到输入采样率之间。")
        if self.dropout_rate_hz < 0 or self.burst_rate_hz < 0:
            raise ValueError("事件 rate 不能为负数。")
        if not 0 <= self.dropout_silence_probability <= 1:
            raise ValueError("dropout_silence_probability 必须在 0 到 1 之间。")
        if not 0 <= self.deterioration <= 1:
            raise ValueError("deterioration 必须在 0 到 1 之间。")
        for low, high, label in (
            (self.dropout_duration_min_ms, self.dropout_duration_max_ms, "dropout"),
            (self.burst_duration_min_ms, self.burst_duration_max_ms, "burst"),
        ):
            if low <= 0 or high < low:
                raise ValueError(f"{label} duration 范围不合法。")


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    start: float
    duration: float
    attenuation_db: float | None = None
    level_dbfs: float | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, float | str]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True, slots=True)
class AudioEffectMetadata:
    effect: str
    preset: str
    strength: float
    seed: int
    sample_rate: int
    channels: int
    duration_seconds: float
    start_seconds: float
    end_seconds: float
    parameters: RadioParameters
    dropouts: tuple[TimelineEvent, ...]
    bursts: tuple[TimelineEvent, ...]
    deterioration_envelope: tuple[dict[str, float], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "effect": self.effect,
            "preset": self.preset,
            "strength": self.strength,
            "seed": self.seed,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_seconds": self.duration_seconds,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "parameters": asdict(self.parameters),
            "dropouts": [event.to_dict() for event in self.dropouts],
            "bursts": [event.to_dict() for event in self.bursts],
            "deterioration_envelope": list(self.deterioration_envelope),
        }


@dataclass(frozen=True, slots=True)
class AudioEffectResult:
    audio: bytes
    metadata: AudioEffectMetadata
