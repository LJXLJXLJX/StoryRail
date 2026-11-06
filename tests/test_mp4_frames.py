"""MP4 容器帧数读取：抽帧帧号范围 0…N-1 的来源。"""

import shutil
import struct
import subprocess

import pytest

from core.media_assets import read_mp4_video_frames


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def _full(kind: bytes, body: bytes) -> bytes:
    return _box(kind, b"\x00\x00\x00\x00" + body)


def _video_trak(sample_count: int, *, timescale=1000, duration=2000) -> bytes:
    tkhd = _full(b"tkhd", b"\x00" * 8 + struct.pack(">I", 1) + b"\x00" * 68)
    mdhd = _full(b"mdhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 4)
    hdlr = _full(b"hdlr", b"\x00" * 4 + b"vide" + b"\x00" * 13)
    stsz = _full(b"stsz", struct.pack(">II", 0, sample_count))
    stbl = _box(b"stbl", stsz)
    minf = _box(b"minf", stbl)
    return _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr + minf))


def _audio_trak() -> bytes:
    tkhd = _full(b"tkhd", b"\x00" * 8 + struct.pack(">I", 2) + b"\x00" * 68)
    hdlr = _full(b"hdlr", b"\x00" * 4 + b"soun" + b"\x00" * 13)
    stsz = _full(b"stsz", struct.pack(">II", 0, 999))
    minf = _box(b"minf", _box(b"stbl", stsz))
    return _box(b"trak", tkhd + _box(b"mdia", hdlr + minf))


FTYP = _box(b"ftyp", b"isom\x00\x00\x02\x00isom")


def test_reads_video_track_sample_count_and_duration_ignoring_audio():
    content = FTYP + _box(b"moov", _audio_trak() + _video_trak(48))
    frames = read_mp4_video_frames(content)
    assert frames.frame_count == 48
    assert frames.duration_seconds == pytest.approx(2.0)


def test_fragmented_mp4_adds_trun_samples_of_the_same_track():
    trun = _full(b"trun", struct.pack(">I", 12))
    other = _box(
        b"traf", _full(b"tfhd", struct.pack(">I", 2)) + _full(b"trun", b"\x00\x00\x00\x07")
    )
    video = _box(b"traf", _full(b"tfhd", struct.pack(">I", 1)) + trun)
    content = (
        FTYP + _box(b"moov", _video_trak(0)) + _box(b"moof", video + other) + _box(b"moof", video)
    )
    assert read_mp4_video_frames(content).frame_count == 24


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (FTYP, "moov"),
        (FTYP + _box(b"moov", _audio_trak()), "没有视频轨"),
        (FTYP + _box(b"moov", _video_trak(0)), "没有可抽取的帧"),
        (FTYP + struct.pack(">I4s", 999, b"moov"), "长度不合法"),
    ],
)
def test_rejects_unreadable_or_empty_video(content, message):
    with pytest.raises(ValueError, match=message):
        read_mp4_video_frames(content)


def test_matches_ffprobe_for_regular_and_fragmented_encodes(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("需要 FFmpeg")
    for name, flags in (("plain", []), ("fragmented", ["-movflags", "frag_keyframe+empty_moov"])):
        path = tmp_path / f"{name}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=32x32:r=24:d=1.5",
                "-c:v",
                "libx264",
                "-g",
                "12",
                "-pix_fmt",
                "yuv420p",
                *flags,
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        assert read_mp4_video_frames(path.read_bytes()).frame_count == 36, name
