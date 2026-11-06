"""Core 确定性工具提交契约的构造与校验。"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest

from core.model_providers.contracts import (
    AnimaticClip,
    AnimaticNarration,
    AnimaticRequest,
    AssemblyClip,
    AssemblyNarration,
    AudioRemixRequest,
    FinalAssemblyRequest,
    PanoViewRequest,
    VideoFrameRequest,
)

_ROOT = Path(__file__).resolve().parents[1]
_32_MIB = 32 * 1024 * 1024
_64_MIB = 64 * 1024 * 1024
_512_MIB = 512 * 1024 * 1024


class _Sized(bytes):
    """只改写长度，避免上限用例分配数百 MiB。"""

    def __new__(cls, payload: bytes, size: int):
        value = bytes.__new__(cls, payload)
        value._size = size
        return value

    def __len__(self) -> int:
        return self._size


def _png(size: int | None = None) -> bytes:
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    return payload if size is None else _Sized(payload, size)


def _jpeg() -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * 8


def _mp4(size: int | None = None) -> bytes:
    payload = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
    return payload if size is None else _Sized(payload, size)


def _wav(size: int | None = None) -> bytes:
    payload = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32
    return payload if size is None else _Sized(payload, size)


def _clip(transition: str | None = None, duration: float = 1.0) -> AssemblyClip:
    return AssemblyClip(_mp4(), transition, duration)


def _narration(index: int = 0) -> AssemblyNarration:
    return AssemblyNarration(_wav(), index)


def _animatic_clip(
    content: bytes | None = None,
    transition: str | None = None,
    duration: float = 1.0,
) -> AnimaticClip:
    return AnimaticClip(_png() if content is None else content, transition, duration)


def _animatic_narration(index: int = 0) -> AnimaticNarration:
    return AnimaticNarration(_wav(), index)


_PANO_SIZE = "全景必须是 2:1 等距柱状图，宽度在 1024 到 16384 像素之间。"


def _rejects(factory, message: str) -> None:
    with pytest.raises(ValueError, match=rf"^{re.escape(message)}$"):
        factory()


def _pano_png(width: int = 2048, height: int = 1024, size: int | None = None) -> bytes:
    payload = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )
    return payload if size is None else _Sized(payload, size)


def _pano_jpeg(width: int, height: int) -> bytes:
    # SOI、一个 APP0 段，然后是 SOF0：长度、精度、高、宽。
    return (
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03"
    )


def _webp_like() -> bytes:
    return b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 16


def test_submission_dataclasses_are_frozen_slots() -> None:
    for cls in (
        AssemblyClip,
        AssemblyNarration,
        AnimaticClip,
        AnimaticNarration,
        FinalAssemblyRequest,
        AnimaticRequest,
        VideoFrameRequest,
        PanoViewRequest,
        AudioRemixRequest,
    ):
        params = cls.__dataclass_params__
        assert params.frozen
        # 3.11 的 _DataclassParams 还没有 slots 属性；槽位本身从 3.10 起就在类上。
        assert cls.__slots__ == tuple(cls.__dataclass_fields__)


def test_contracts_import_only_the_standard_library() -> None:
    source = (_ROOT / "core/model_providers/contracts.py").read_text()
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert modules
    assert all(name in {"__future__", "dataclasses", "math"} for name in modules)


def test_provider_ports_use_core_contracts() -> None:
    source = (_ROOT / "core/structured_director/provider_ports.py").read_text()
    assert "from core.model_providers.contracts import" in source
    for name in (
        "CodexImageGenerateRequest",
        "CodexImageEditRequest",
        "BreezeTTS2Request",
        "WhisperASRRequest",
        "MiniMaxH3FL2VARequest",
        "MiniMaxH3Ref2VARequest",
        "SeedVR2UpscaleRequest",
        "DemucsAudioSeparationRequest",
        "FFmpegAudioRemixRequest",
    ):
        assert name not in source


def test_final_assembly_request_constructs() -> None:
    clip = _clip()
    blended = _clip("seam_blend", 0.05)
    long_clip = _clip(duration=600)
    request = FinalAssemblyRequest(
        (clip,) * 499 + (blended,),
        (_narration(499),) * 200,
        "9:16",
        1.0,
        0.0,
        2.0,
    )
    assert request.clips[-1].transition_from_previous == "seam_blend"
    assert long_clip.duration_seconds == 600
    assert request.video_audio_volume == 0.0
    assert request.narration_audio_volume == 2.0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: AssemblyClip(b"", None, 1), "成片片段大小不合法。"),
        (lambda: AssemblyClip(_mp4(_512_MIB + 1), None, 1), "成片片段大小不合法。"),
        (lambda: AssemblyClip(b"not-an-mp4-file", None, 1), "成片片段必须是真实 MP4。"),
        (lambda: AssemblyClip(_mp4(), "dissolve", 1), "成片转场类型不受支持。"),
        (lambda: AssemblyClip(_mp4(), None, 0.049), "成片片段目标时长不合法。"),
        (lambda: AssemblyClip(_mp4(), None, 600.1), "成片片段目标时长不合法。"),
        (lambda: AssemblyNarration(b"", 0), "旁白音频大小不合法。"),
        (lambda: AssemblyNarration(_wav(_64_MIB + 1), 0), "旁白音频大小不合法。"),
        (lambda: AssemblyNarration(b"not-a-wav-file", 0), "旁白音频必须是真实 WAV。"),
        (lambda: AssemblyNarration(_wav(), -1), "旁白起始片段索引不合法。"),
        (lambda: AssemblyNarration(_wav(), True), "旁白起始片段索引不合法。"),
        (lambda: FinalAssemblyRequest((), (), "16:9"), "成片必须包含 1 到 500 个片段。"),
        (
            lambda: FinalAssemblyRequest((_clip(),) * 501, (), "16:9"),
            "成片必须包含 1 到 500 个片段。",
        ),
        (
            lambda: FinalAssemblyRequest((_clip("seam_blend"),), (), "16:9"),
            "首个片段不能包含入场转场。",
        ),
        (
            lambda: FinalAssemblyRequest((_clip(),), (_narration(0),) * 201, "16:9"),
            "成片旁白数量过多。",
        ),
        (
            lambda: FinalAssemblyRequest((_clip(),), (_narration(1),), "16:9"),
            "旁白起始片段不存在。",
        ),
        (lambda: FinalAssemblyRequest((_clip(),), (), "1:1"), "成片画幅只允许 16:9、9:16 或 2:1。"),
        (lambda: FinalAssemblyRequest((_clip(),), (), "16:9", 0.09), "转场时长不合法。"),
        (lambda: FinalAssemblyRequest((_clip(),), (), "16:9", 1.01), "转场时长不合法。"),
        (
            lambda: FinalAssemblyRequest((_clip(),), (), "16:9", 0.1, True, 1.0),
            "视频自带音频音量必须在 0 到 2 之间。",
        ),
        (
            lambda: FinalAssemblyRequest((_clip(),), (), "16:9", 0.1, 1.0, 2.1),
            "旁白音频音量必须在 0 到 2 之间。",
        ),
    ],
)
def test_final_assembly_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_animatic_request_constructs() -> None:
    opening = _animatic_clip(transition="seam_blend", duration=0.05)
    jpeg_clip = _animatic_clip(_jpeg(), duration=600)
    request = AnimaticRequest((opening,) * 500, (_animatic_narration(499),) * 200, "16:9", 1.0)
    assert request.clips[0].transition_from_previous == "seam_blend"
    assert jpeg_clip.content.startswith(b"\xff\xd8\xff")
    assert request.transition_seconds == 1.0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: AnimaticClip(b"", None, 1), "Animatic 关键帧图片大小不合法。"),
        (lambda: AnimaticClip(_png(_64_MIB + 1), None, 1), "Animatic 关键帧图片大小不合法。"),
        (
            lambda: AnimaticClip(b"GIF89a" + b"\x00" * 8, None, 1),
            "Animatic 关键帧图片必须是 PNG 或 JPEG。",
        ),
        (lambda: AnimaticClip(_png(), "dissolve", 1), "Animatic 转场类型不受支持。"),
        (lambda: AnimaticClip(_png(), None, 0.049), "Animatic 片段目标时长不合法。"),
        (lambda: AnimaticNarration(b"", 0), "Animatic 旁白音频大小不合法。"),
        (lambda: AnimaticNarration(_wav(_64_MIB + 1), 0), "Animatic 旁白音频大小不合法。"),
        (lambda: AnimaticNarration(b"not-a-wav-file", 0), "Animatic 旁白音频必须是真实 WAV。"),
        (lambda: AnimaticNarration(_wav(), 500), "Animatic 旁白起始片段索引不合法。"),
        (lambda: AnimaticNarration(_wav(), True), "Animatic 旁白起始片段索引不合法。"),
        (lambda: AnimaticRequest((), (), "16:9"), "Animatic 必须包含 1 到 500 个片段。"),
        (
            lambda: AnimaticRequest((_animatic_clip(),) * 501, (), "16:9"),
            "Animatic 必须包含 1 到 500 个片段。",
        ),
        (
            lambda: AnimaticRequest((_animatic_clip(),), (_animatic_narration(0),) * 201, "16:9"),
            "Animatic 旁白数量过多。",
        ),
        (
            lambda: AnimaticRequest((_animatic_clip(),), (_animatic_narration(1),), "16:9"),
            "Animatic 旁白起始片段不存在。",
        ),
        (
            lambda: AnimaticRequest((_animatic_clip(),), (), "1:1"),
            "Animatic 画幅只允许 16:9、9:16 或 2:1。",
        ),
        (
            lambda: AnimaticRequest((_animatic_clip(),), (), "9:16", 0.09),
            "Animatic 转场时长不合法。",
        ),
    ],
)
def test_animatic_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_video_frame_request_constructs() -> None:
    request = VideoFrameRequest(_mp4(), 0)
    assert request.content[4:8] == b"ftyp"
    assert request.frame_index == 0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: VideoFrameRequest(b"short", 0), "抽帧输入必须是受限 MP4 字节。"),
        (lambda: VideoFrameRequest(b"0123456789abcdef", 0), "抽帧输入必须是受限 MP4 字节。"),
        (lambda: VideoFrameRequest(_mp4(_512_MIB + 1), 0), "抽帧输入必须是受限 MP4 字节。"),
        (lambda: VideoFrameRequest(_mp4(), -1), "抽帧帧号必须是非负整数。"),
        (lambda: VideoFrameRequest(_mp4(), True), "抽帧帧号必须是非负整数。"),
    ],
)
def test_video_frame_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_pano_view_request_constructs() -> None:
    request = PanoViewRequest(_pano_png(), 0, -60, 120, "9:16")
    assert (request.yaw_deg, request.pitch_deg, request.hfov_deg) == (0, -60, 120)
    assert PanoViewRequest(_pano_png(2049, 1024), 359.9, 60, 20, "2:1").aspect_ratio == "2:1"
    assert PanoViewRequest(_pano_jpeg(4096, 2048), 180.5, 0, 90, "16:9").yaw_deg == 180.5
    assert PanoViewRequest(_pano_png(16384, 8192), 0, 0, 90, "16:9").hfov_deg == 90


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: PanoViewRequest(_webp_like(), 0, 0, 90, "16:9"), "全景输入必须是 PNG 或 JPEG。"),
        (
            lambda: PanoViewRequest(_pano_png(size=_64_MIB + 1), 0, 0, 90, "16:9"),
            "全景图片大小不合法。",
        ),
        (lambda: PanoViewRequest(_pano_png(2048, 1000), 0, 0, 90, "16:9"), _PANO_SIZE),
        (lambda: PanoViewRequest(_pano_png(1000, 500), 0, 0, 90, "16:9"), _PANO_SIZE),
        (lambda: PanoViewRequest(_pano_png(16386, 8193), 0, 0, 90, "16:9"), _PANO_SIZE),
        (lambda: PanoViewRequest(_pano_jpeg(2048, 2048), 0, 0, 90, "16:9"), _PANO_SIZE),
        (lambda: PanoViewRequest(b"\xff\xd8\xff\xe0", 0, 0, 90, "16:9"), _PANO_SIZE),
        (lambda: PanoViewRequest(_png(), 0, 0, 90, "16:9"), _PANO_SIZE),
        (
            lambda: PanoViewRequest(_pano_png(), 360, 0, 90, "16:9"),
            "全景裁切 yaw 必须在 [0, 360) 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), -1, 0, 90, "16:9"),
            "全景裁切 yaw 必须在 [0, 360) 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), True, 0, 90, "16:9"),
            "全景裁切 yaw 必须在 [0, 360) 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), 0, 60.5, 90, "16:9"),
            "全景裁切 pitch 必须在 [-60, 60] 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), 0, math.inf, 90, "16:9"),
            "全景裁切 pitch 必须在 [-60, 60] 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), 0, 0, 19.9, "16:9"),
            "全景裁切水平视场角必须在 [20, 120] 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), 0, 0, 121, "16:9"),
            "全景裁切水平视场角必须在 [20, 120] 度内。",
        ),
        (
            lambda: PanoViewRequest(_pano_png(), 0, 0, 90, "1:1"),
            "全景裁切画幅只允许 16:9、9:16 或 2:1。",
        ),
    ],
)
def test_pano_view_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_audio_remix_request_constructs() -> None:
    request = AudioRemixRequest(
        _mp4(),
        _wav(),
        _wav(),
        -100,
        24,
        0,
        1.5,
        0.25,
        2,
    )
    assert request.voice_gain_db == -100
    assert request.background_gain_end_seconds == 2
    omitted = AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 0)
    assert omitted.voice_gain_start_seconds is None
    assert omitted.background_gain_end_seconds is None


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: AudioRemixRequest(b"short", _wav(), _wav(), 0, 0),
            "音轨混音输入必须是真实 MP4。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(_512_MIB + 1), _wav(), _wav(), 0, 0),
            "音轨混音输入必须是真实 MP4。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), b"not-a-wav-file", _wav(), 0, 0),
            "音轨混音输入必须是真实 WAV。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), b"not-a-wav-file", 0, 0),
            "音轨混音输入必须是真实 WAV。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), True, 0),
            "音轨增益必须在 -100 到 24 dB 之间。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), -100.1, 0),
            "音轨增益必须在 -100 到 24 dB 之间。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 24.1),
            "音轨增益必须在 -100 到 24 dB 之间。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), math.nan, 0),
            "音轨增益必须在 -100 到 24 dB 之间。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 0, 0, None),
            "人声音量开始和结束时间必须同时提供或同时省略。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 0, 1, 1),
            "人声音量时间范围不合法。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 0, -1, 1),
            "人声音量时间范围不合法。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 0, None, None, 0, None),
            "背景声音量开始和结束时间必须同时提供或同时省略。",
        ),
        (
            lambda: AudioRemixRequest(_mp4(), _wav(), _wav(), 0, 0, None, None, True, 1),
            "背景声音量时间范围不合法。",
        ),
    ],
)
def test_audio_remix_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)
