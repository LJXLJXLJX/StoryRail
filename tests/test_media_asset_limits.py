"""单个 Asset 的字节上限：视频 2 GiB、WAV 256 MiB、图片 64 MiB，项目与 Playground 共用。"""

from __future__ import annotations

import pytest

from core.media_assets import max_media_bytes, validate_media_bytes
from core.playground.models import AssetOrigin, PlaygroundAsset
from core.structured_director.models import Asset

MIB = 1024 * 1024
SHA256 = "ab" * 32
# YuE2 6 分钟 48 kHz 立体声 16-bit WAV 的真实字节数，超过旧的 64 MiB 上限。
SIX_MINUTE_SONG = 69_119_788


def _wav_header(size: int) -> bytes:
    return (b"RIFF" + b"\x00" * 4 + b"WAVE").ljust(size, b"\x00")


def test_limits_by_media_type() -> None:
    assert max_media_bytes("video/mp4") == 2 * 1024 * MIB
    assert max_media_bytes("audio/wav") == 256 * MIB
    for image in ("image/png", "image/jpeg", "image/webp"):
        assert max_media_bytes(image) == 64 * MIB


def test_validate_accepts_long_wav_and_rejects_oversize() -> None:
    validate_media_bytes("audio/wav", _wav_header(SIX_MINUTE_SONG))
    with pytest.raises(ValueError, match="不合法"):
        validate_media_bytes("audio/wav", _wav_header(256 * MIB + 1))
    with pytest.raises(ValueError, match="不合法"):
        validate_media_bytes("image/png", b"\x89PNG\r\n\x1a\n".ljust(64 * MIB + 1, b"\x00"))


def _playground(media_type: str, byte_count: int, path: str) -> PlaygroundAsset:
    return PlaygroundAsset(
        id=SHA256[:32],
        media_type=media_type,
        byte_count=byte_count,
        sha256=SHA256,
        relative_path=path,
        duration_seconds=360.0 if media_type == "audio/wav" else None,
        origin=AssetOrigin("imported"),
        created_at="2026-11-01T12:00:00+00:00",
    )


def _project(media_type: str, byte_count: int, path: str) -> Asset:
    return Asset(
        id=SHA256[:32],
        media_type=media_type,
        byte_count=byte_count,
        sha256=SHA256,
        relative_path=path,
        duration_seconds=360.0 if media_type == "audio/wav" else None,
    )


@pytest.mark.parametrize(
    ("factory", "wav_path", "png_path"),
    [
        (_playground, "assets/audio/imported/song-ab.wav", "assets/images/imported/a-ab.png"),
        (_project, "assets/audio/imported/song-ab.wav", "assets/images/library/a-ab.png"),
    ],
)
def test_asset_models_share_limits(factory, wav_path: str, png_path: str) -> None:
    assert factory("audio/wav", SIX_MINUTE_SONG, wav_path).byte_count == SIX_MINUTE_SONG
    with pytest.raises(ValueError, match="byte_count"):
        factory("audio/wav", 256 * MIB + 1, wav_path)
    with pytest.raises(ValueError, match="byte_count"):
        factory("image/png", 64 * MIB + 1, png_path)
