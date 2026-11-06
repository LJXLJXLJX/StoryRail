from __future__ import annotations

import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from struct import pack, unpack_from

from core.audio_effects import (
    AudioEffectRequest,
    apply_audio_effect,
    preset_names,
    resolve_radio_parameters,
)


def make_wav(
    *, sample_rate: int = 16_000, channels: int = 1, duration: float = 1.5, silence: bool = False
) -> bytes:
    frame_count = max(1, round(sample_rate * duration))
    raw = bytearray()
    for index in range(frame_count):
        time = index / sample_rate
        voice_like = (
            0.0
            if silence
            else (
                0.30 * math.sin(2 * math.pi * 180 * time)
                + 0.16 * math.sin(2 * math.pi * 1_100 * time)
                + 0.08 * math.sin(2 * math.pi * 5_500 * time)
            )
        )
        for channel in range(channels):
            sample = voice_like * (1.0 - channel * 0.18)
            raw.extend(pack("<h", round(sample * 32767)))
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        destination.writeframes(raw)
    return output.getvalue()


def wav_info(content: bytes) -> tuple[int, int, list[list[float]]]:
    with wave.open(io.BytesIO(content), "rb") as source:
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        raw = source.readframes(source.getnframes())
    decoded = [[] for _ in range(channels)]
    for frame in range(len(raw) // (2 * channels)):
        for channel in range(channels):
            offset = (frame * channels + channel) * 2
            decoded[channel].append(unpack_from("<h", raw, offset)[0] / 32768)
    return sample_rate, channels, decoded


def make_pcm_width_wav(sample_width: int) -> bytes:
    raw = bytearray()
    for index in range(800):
        sample = 0.5 * math.sin(2 * math.pi * 700 * index / 16_000)
        if sample_width == 1:
            raw.append(max(0, min(255, round(sample * 127 + 128))))
        elif sample_width == 2:
            raw.extend(pack("<h", round(sample * 32767)))
        elif sample_width == 3:
            raw.extend(round(sample * 8388607).to_bytes(3, "little", signed=True))
        elif sample_width == 4:
            raw.extend(pack("<i", round(sample * 2147483647)))
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(sample_width)
        destination.setframerate(16_000)
        destination.writeframes(raw)
    return output.getvalue()


def rms(samples: list[float]) -> float:
    return math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))


def tone_amplitude(samples: list[float], sample_rate: int, frequency: float) -> float:
    cosine = 0.0
    sine = 0.0
    for index, sample in enumerate(samples):
        angle = 2 * math.pi * frequency * index / sample_rate
        cosine += sample * math.cos(angle)
        sine += sample * math.sin(angle)
    return math.hypot(cosine, sine) / max(1, len(samples))


class AudioEffectsTests(unittest.TestCase):
    def test_presets_are_parameter_bundles_and_allow_strict_overrides(self) -> None:
        self.assertEqual(
            preset_names(),
            (
                "walkie_talkie",
                "military_radio",
                "weak_signal",
                "bad_signal",
                "dying_transmission",
            ),
        )
        weak = resolve_radio_parameters("weak_signal", 0.7)
        overridden = resolve_radio_parameters(
            "weak_signal", 0.7, {"high_pass_hz": 410.0, "edge_bursts": False}
        )
        self.assertEqual(overridden.high_pass_hz, 410)
        self.assertFalse(overridden.edge_bursts)
        self.assertEqual(overridden.low_pass_hz, weak.low_pass_hz)
        with self.assertRaisesRegex(ValueError, "未知 radio 参数"):
            resolve_radio_parameters("weak_signal", 1.0, {"shell": 1})
        with self.assertRaisesRegex(ValueError, "尚未注册 audio effect"):
            apply_audio_effect(make_wav(), AudioEffectRequest("telephone", "narrow", 1.0, 1))

    def test_same_seed_is_byte_deterministic_and_different_seed_changes_timeline(self) -> None:
        content = make_wav(duration=3.0)
        overrides = {"dropout_rate_hz": 3.0, "burst_rate_hz": 2.0, "edge_bursts": False}
        first = apply_audio_effect(
            content, AudioEffectRequest("radio", "bad_signal", 0.8, 42, overrides)
        )
        replay = apply_audio_effect(
            content, AudioEffectRequest("radio", "bad_signal", 0.8, 42, overrides)
        )
        other = apply_audio_effect(
            content, AudioEffectRequest("radio", "bad_signal", 0.8, 43, overrides)
        )
        self.assertEqual(
            hashlib.sha256(first.audio).digest(), hashlib.sha256(replay.audio).digest()
        )
        self.assertEqual(first.metadata.to_dict(), replay.metadata.to_dict())
        self.assertNotEqual(first.metadata.dropouts, other.metadata.dropouts)
        self.assertNotEqual(
            hashlib.sha256(first.audio).digest(), hashlib.sha256(other.audio).digest()
        )

    def test_mono_stereo_and_sample_rates_are_preserved(self) -> None:
        for sample_rate in (8_000, 16_000, 44_100):
            for channels in (1, 2):
                with self.subTest(sample_rate=sample_rate, channels=channels):
                    result = apply_audio_effect(
                        make_wav(sample_rate=sample_rate, channels=channels, duration=0.18),
                        AudioEffectRequest("radio", "military_radio", 0.6, 9),
                    )
                    actual_rate, actual_channels, decoded = wav_info(result.audio)
                    self.assertEqual((actual_rate, actual_channels), (sample_rate, channels))
                    self.assertEqual(len(decoded[0]), round(sample_rate * 0.18))

    def test_degradation_rate_is_clamped_to_low_rate_input(self) -> None:
        result = apply_audio_effect(
            make_wav(sample_rate=8_000, duration=0.1),
            AudioEffectRequest("radio", "weak_signal", 1.0, 3),
        )
        self.assertEqual(result.metadata.parameters.degradation_sample_rate_hz, 8_000)

    def test_pcm_integer_widths_are_explicitly_converted_to_pcm16(self) -> None:
        for sample_width in (1, 2, 3, 4):
            with self.subTest(sample_width=sample_width):
                result = apply_audio_effect(
                    make_pcm_width_wav(sample_width),
                    AudioEffectRequest("radio", "walkie_talkie", 0.5, 4),
                )
                with wave.open(io.BytesIO(result.audio), "rb") as output:
                    self.assertEqual(output.getsampwidth(), 2)
                    self.assertEqual(output.getnframes(), 800)

    def test_very_short_and_silent_inputs_remain_finite_and_bounded(self) -> None:
        for content in (
            make_wav(sample_rate=16_000, duration=1 / 16_000),
            make_wav(sample_rate=16_000, duration=0.4, silence=True),
        ):
            with self.subTest(bytes=len(content)):
                result = apply_audio_effect(
                    content, AudioEffectRequest("radio", "dying_transmission", 1.0, 7)
                )
                _, _, decoded = wav_info(result.audio)
                self.assertTrue(
                    all(math.isfinite(value) for channel in decoded for value in channel)
                )
                self.assertLessEqual(
                    max(abs(value) for channel in decoded for value in channel), 1.0
                )

    def test_radio_filter_prefers_voice_band_over_low_and_high_tones(self) -> None:
        result = apply_audio_effect(
            make_wav(sample_rate=16_000, duration=1.0),
            AudioEffectRequest(
                "radio",
                "walkie_talkie",
                1.0,
                1,
                {
                    "noise_dbfs": -120.0,
                    "dropout_rate_hz": 0.0,
                    "burst_rate_hz": 0.0,
                    "edge_bursts": False,
                    "compression_ratio": 1.0,
                    "makeup_gain_db": 0.0,
                    "saturation_drive": 1.0,
                    "degradation_sample_rate_hz": None,
                },
            ),
        )
        sample_rate, _, decoded = wav_info(result.audio)
        voice = tone_amplitude(decoded[0], sample_rate, 1_100)
        low = tone_amplitude(decoded[0], sample_rate, 180)
        high = tone_amplitude(decoded[0], sample_rate, 5_500)
        self.assertGreater(voice, low)
        self.assertGreater(voice, high)

    def test_static_noise_is_band_limited(self) -> None:
        result = apply_audio_effect(
            make_wav(sample_rate=16_000, duration=1.0, silence=True),
            AudioEffectRequest(
                "radio",
                "weak_signal",
                1.0,
                8,
                {"dropout_rate_hz": 0.0, "burst_rate_hz": 0.0, "edge_bursts": False},
            ),
        )
        sample_rate, _, decoded = wav_info(result.audio)
        middle = tone_amplitude(decoded[0], sample_rate, 1_200)
        sub_band = tone_amplitude(decoded[0], sample_rate, 80)
        above_band = tone_amplitude(decoded[0], sample_rate, 7_000)
        self.assertGreater(middle, sub_band)
        self.assertGreater(middle, above_band)

    def test_dying_transmission_has_increasing_degradation(self) -> None:
        result = apply_audio_effect(
            make_wav(sample_rate=16_000, duration=2.0, silence=True),
            AudioEffectRequest(
                "radio",
                "dying_transmission",
                1.0,
                22,
                {"dropout_rate_hz": 0.0, "burst_rate_hz": 0.0, "edge_bursts": False},
            ),
        )
        envelope = result.metadata.deterioration_envelope
        self.assertLess(envelope[0]["amount"], envelope[-1]["amount"])
        self.assertLess(envelope[0]["noise_multiplier"], envelope[-1]["noise_multiplier"])
        _, _, decoded = wav_info(result.audio)
        midpoint = len(decoded[0]) // 2
        self.assertGreater(rms(decoded[0][midpoint:]), rms(decoded[0][:midpoint]) * 1.25)

    def test_metadata_is_json_serializable_and_events_are_in_bounds(self) -> None:
        result = apply_audio_effect(
            make_wav(duration=2.0),
            AudioEffectRequest(
                "radio", "bad_signal", 1.0, 5, {"dropout_rate_hz": 4.0, "burst_rate_hz": 3.0}
            ),
        )
        encoded = json.dumps(result.metadata.to_dict(), sort_keys=True)
        self.assertIn('"seed": 5', encoded)
        for event in (*result.metadata.dropouts, *result.metadata.bursts):
            self.assertGreaterEqual(event.start, 0)
            self.assertGreater(event.duration, 0)
            self.assertLessEqual(event.start + event.duration, 2.000001)

    def test_selected_range_preserves_audio_outside_and_offsets_timeline(self) -> None:
        source = make_wav(duration=2.0)
        request = AudioEffectRequest(
            "radio",
            "bad_signal",
            0.9,
            42,
            {"dropout_rate_hz": 4.0, "burst_rate_hz": 3.0},
            start_seconds=0.5,
            end_seconds=1.5,
        )
        first = apply_audio_effect(source, request)
        replay = apply_audio_effect(source, request)
        sample_rate, _, dry = wav_info(source)
        _, _, wet = wav_info(first.audio)
        start = round(0.5 * sample_rate)
        end = round(1.5 * sample_rate)

        self.assertEqual(first.audio, replay.audio)
        self.assertEqual(first.metadata.start_seconds, 0.5)
        self.assertEqual(first.metadata.end_seconds, 1.5)
        self.assertLessEqual(
            max(
                abs(left - right)
                for left, right in zip(dry[0][:start], wet[0][:start], strict=True)
            ),
            2 / 32768,
        )
        self.assertLessEqual(
            max(abs(left - right) for left, right in zip(dry[0][end:], wet[0][end:], strict=True)),
            2 / 32768,
        )
        self.assertGreater(
            rms(
                [
                    left - right
                    for left, right in zip(dry[0][start:end], wet[0][start:end], strict=True)
                ]
            ),
            0.01,
        )
        for event in (*first.metadata.dropouts, *first.metadata.bursts):
            self.assertGreaterEqual(event.start, 0.5)
            self.assertLessEqual(event.start + event.duration, 1.500001)
        self.assertEqual(first.metadata.deterioration_envelope[0]["time"], 0.5)
        self.assertEqual(first.metadata.deterioration_envelope[-1]["time"], 1.5)

    def test_selection_must_be_paired_ordered_and_within_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须同时提供"):
            AudioEffectRequest("radio", "weak_signal", start_seconds=0.2)
        with self.assertRaisesRegex(ValueError, "大于 start_seconds"):
            AudioEffectRequest("radio", "weak_signal", start_seconds=0.5, end_seconds=0.5)
        with self.assertRaisesRegex(ValueError, "不能超过"):
            apply_audio_effect(
                make_wav(duration=1.0),
                AudioEffectRequest("radio", "weak_signal", start_seconds=0.2, end_seconds=1.1),
            )

    def test_explicit_full_range_matches_legacy_full_file_request(self) -> None:
        source = make_wav(duration=1.0)
        legacy = apply_audio_effect(source, AudioEffectRequest("radio", "weak_signal", 0.7, 42))
        ranged = apply_audio_effect(
            source,
            AudioEffectRequest("radio", "weak_signal", 0.7, 42, start_seconds=0.0, end_seconds=1.0),
        )
        self.assertEqual(legacy.audio, ranged.audio)
        self.assertEqual(legacy.metadata.dropouts, ranged.metadata.dropouts)

    def test_cli_writes_audio_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "clean.wav"
            output = root / "radio.wav"
            metadata = root / "radio.json"
            source.write_bytes(make_wav(duration=0.2))
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "core.audio_effects",
                    str(source),
                    str(output),
                    "--preset",
                    "weak_signal",
                    "--strength",
                    "0.7",
                    "--seed",
                    "42",
                    "--metadata",
                    str(metadata),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(output.read_bytes().startswith(b"RIFF"))
            self.assertEqual(json.loads(metadata.read_text())["seed"], 42)


if __name__ == "__main__":
    unittest.main()
