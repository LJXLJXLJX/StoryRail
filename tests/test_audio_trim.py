from __future__ import annotations

import hashlib
import io
import math
import unittest
import wave
from struct import pack

from core.audio_effects import AudioTrimRequest, trim_audio


def make_wav(*, sample_rate: int, channels: int, frames: int) -> bytes:
    raw = bytearray()
    for index in range(frames):
        for channel in range(channels):
            sample = 0.4 * math.sin(2 * math.pi * (440 + channel * 110) * index / sample_rate)
            raw.extend(pack("<h", round(sample * 32767)))
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        destination.writeframes(raw)
    return output.getvalue()


class AudioTrimTests(unittest.TestCase):
    def test_trim_is_byte_deterministic_and_preserves_audio_shape(self) -> None:
        for sample_rate in (8_000, 12_000, 44_100):
            for channels in (1, 2):
                with self.subTest(sample_rate=sample_rate, channels=channels):
                    source = make_wav(
                        sample_rate=sample_rate,
                        channels=channels,
                        frames=sample_rate,
                    )
                    request = AudioTrimRequest(0.125, 0.625)
                    first = trim_audio(source, request)
                    replay = trim_audio(source, request)
                    self.assertEqual(
                        hashlib.sha256(first.audio).digest(),
                        hashlib.sha256(replay.audio).digest(),
                    )
                    with wave.open(io.BytesIO(first.audio), "rb") as result:
                        self.assertEqual(result.getframerate(), sample_rate)
                        self.assertEqual(result.getnchannels(), channels)
                        self.assertEqual(result.getsampwidth(), 2)
                        self.assertEqual(result.getnframes(), sample_rate // 2)
                    self.assertEqual(first.metadata.output_duration_seconds, 0.5)

    def test_times_are_aligned_to_frames_and_very_short_trim_is_supported(self) -> None:
        result = trim_audio(
            make_wav(sample_rate=8_000, channels=1, frames=8),
            AudioTrimRequest(0, 1 / 8_000),
        )
        with wave.open(io.BytesIO(result.audio), "rb") as output:
            self.assertEqual(output.getnframes(), 1)
        self.assertEqual(result.metadata.start_seconds, 0)
        self.assertEqual(result.metadata.end_seconds, 1 / 8_000)

    def test_invalid_or_out_of_bounds_ranges_are_rejected(self) -> None:
        source = make_wav(sample_rate=8_000, channels=1, frames=800)
        for start, end in ((-1, 0.1), (0.1, 0.1), (0.2, 0.1)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                AudioTrimRequest(start, end)
        with self.assertRaisesRegex(ValueError, "不能超过"):
            trim_audio(source, AudioTrimRequest(0, 0.101))
        with self.assertRaisesRegex(ValueError, "必须短于"):
            trim_audio(source, AudioTrimRequest(0, 0.1))
        with self.assertRaisesRegex(ValueError, "至少需要包含一个采样帧"):
            trim_audio(source, AudioTrimRequest(0, 0.00001))


if __name__ == "__main__":
    unittest.main()
