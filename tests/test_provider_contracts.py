"""Core 媒体提交 DTO 的构造与校验。"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest

from core.model_providers.breeze_tts2 import MANIFEST as BREEZE_MANIFEST
from core.model_providers.codex_image import CodexImageEditRequest as ImageEditRequest
from core.model_providers.codex_image import CodexImageGenerateRequest as ImageGenerateRequest
from core.model_providers.codex_image import InputImage as ImageBytes
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
from core.model_providers.demucs_audio import DemucsAudioSeparationRequest as AudioSeparationRequest
from core.model_providers.minimax_h3.contracts import (
    FL2VARequest,
    KeyframeImage,
    Ref2VARequest,
    ReferenceAudio,
    ReferenceImage,
    ReferenceVideo,
)
from core.model_providers.recipe import MediaInput, build_recipe_request
from core.model_providers.seedvr2_7b_sharp_fp8 import SeedVR2UpscaleRequest as VideoUpscaleRequest
from core.model_providers.seedvr2_7b_sharp_fp8 import SeedVR2Video as UpscaleVideo
from core.model_providers.stable_audio_3 import StableAudio3Request as TextToAudioRequest
from core.model_providers.whisper_asr import WhisperASRRequest as SpeechRecognitionRequest

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


def _image() -> ImageBytes:
    return ImageBytes("image/png", _png())


def _keyframe() -> KeyframeImage:
    return KeyframeImage("image/png", _png())


def _reference_image() -> ReferenceImage:
    return ReferenceImage("image/jpeg", _jpeg())


def _reference_audio() -> ReferenceAudio:
    return ReferenceAudio("audio/wav", _wav())


def _reference_video(duration: float = 3.0) -> ReferenceVideo:
    return ReferenceVideo("video/mp4", _mp4(), duration)


def _video() -> UpscaleVideo:
    return UpscaleVideo("video/mp4", _mp4())


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


def _rejects(factory, message: str) -> None:
    with pytest.raises(ValueError, match=rf"^{re.escape(message)}$"):
        factory()


def test_submission_dataclasses_are_frozen_slots() -> None:
    for cls in (
        ImageBytes,
        KeyframeImage,
        ReferenceImage,
        ReferenceAudio,
        ReferenceVideo,
        UpscaleVideo,
        AssemblyClip,
        AssemblyNarration,
        AnimaticClip,
        AnimaticNarration,
        ImageGenerateRequest,
        ImageEditRequest,
        SpeechRecognitionRequest,
        FL2VARequest,
        Ref2VARequest,
        VideoUpscaleRequest,
        FinalAssemblyRequest,
        AnimaticRequest,
        VideoFrameRequest,
        PanoViewRequest,
        AudioSeparationRequest,
        AudioRemixRequest,
        TextToAudioRequest,
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


def test_image_bytes_and_generate_request_construct() -> None:
    images = tuple(
        ImageBytes(media_type, _png()) for media_type in ("image/png", "image/jpeg", "image/webp")
    )
    request = ImageGenerateRequest("p" * 20_000, "9:16", images + (_image(), _image()), "m" * 128)
    assert request.model == "m" * 128
    assert len(request.reference_images) == 5
    bare = ImageGenerateRequest("客厅", "16:9")
    assert bare.model == "gpt-5.6-terra"
    assert bare.reference_images == ()


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ImageBytes("image/gif", b"x"), "输入图片类型不受支持。"),
        (lambda: ImageBytes("image/png", b""), "输入图片大小不合法。"),
        (lambda: ImageBytes("image/png", _png(_32_MIB + 1)), "输入图片大小不合法。"),
        (lambda: ImageGenerateRequest("", "16:9"), "prompt 必须是 1 到 20000 字符。"),
        (lambda: ImageGenerateRequest("p" * 20_001, "16:9"), "prompt 必须是 1 到 20000 字符。"),
        (lambda: ImageGenerateRequest("客厅", "16:9", model=""), "model 不合法。"),
        (lambda: ImageGenerateRequest("客厅", "16:9", model="m" * 129), "model 不合法。"),
        (lambda: ImageGenerateRequest("客厅", "16:9", (_image(),) * 6), "最多接受 5 张参考图片。"),
        (lambda: ImageGenerateRequest("客厅", "7:5"), "aspect_ratio 不在支持的图片比例中。"),
        (lambda: ImageGenerateRequest("客厅", "16:9", (object(),)), "输入图片类型不受支持。"),
    ],
)
def test_image_generate_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_image_edit_request_constructs() -> None:
    request = ImageEditRequest("改成傍晚", _image(), "9:16", (_image(),) * 4)
    assert request.source_image.media_type == "image/png"
    assert request.model == "gpt-5.6-terra"
    assert len(request.reference_images) == 4


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ImageEditRequest("", _image(), "16:9"), "prompt 必须是 1 到 20000 字符。"),
        (lambda: ImageEditRequest("改", object(), "16:9"), "输入图片类型不受支持。"),
        (lambda: ImageEditRequest("改", _image(), "16:9", model=""), "model 不合法。"),
        (
            lambda: ImageEditRequest("改", _image(), "16:9", (_image(),) * 5),
            "图片编辑除底图外最多接受 4 张参考图片。",
        ),
        (
            lambda: ImageEditRequest("改", _image(), "7:5"),
            "aspect_ratio 不在支持的图片比例中。",
        ),
        (
            lambda: ImageEditRequest("改", _image(), "16:9", (object(),)),
            "输入图片类型不受支持。",
        ),
    ],
)
def test_image_edit_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def _breeze(recipe_id: str, *, voice: MediaInput | None = None, **params):
    return build_recipe_request(
        BREEZE_MANIFEST,
        recipe_id,
        inputs={} if voice is None else {"voice": (voice,)},
        params=params,
    )


def test_breeze_recipe_requests_construct() -> None:
    design = _breeze(
        "breeze_tts2.voice_design",
        text="欢迎来到镜序。",
        voice_description="温柔、清晰的女声",
        seed=7,
    )
    assert design.slot("voice") == ()
    clone = _breeze(
        "breeze_tts2.clone",
        voice=MediaInput("audio/wav", _wav()),
        text="旁白",
        reference_transcript="完整文字稿",
        performance_instruction="放慢",
        seed=2**63 - 1,
    )
    assert clone.single("voice").content == _wav()
    assert clone.param("reference_transcript") == "完整文字稿"


_CLONE = {"text": "你好", "reference_transcript": "稿", "performance_instruction": None, "seed": 1}


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: _breeze("breeze_tts2.voice_design", text="  ", voice_description="声", seed=1),
            "朗读文本不能为空。",
        ),
        (
            lambda: _breeze("breeze_tts2.voice_design", text="你好", voice_description=" ", seed=1),
            "音色描述不能为空。",
        ),
        (
            lambda: _breeze(
                "breeze_tts2.clone",
                voice=MediaInput("audio/wav", _wav()),
                **{**_CLONE, "performance_instruction": " "},
            ),
            "表演指示不能为空。",
        ),
        (
            lambda: _breeze("breeze_tts2.clone", **_CLONE),
            "参考音色必须是 1 项。",
        ),
        (
            lambda: _breeze(
                "breeze_tts2.clone",
                voice=MediaInput("audio/wav", _wav()),
                **{**_CLONE, "reference_transcript": None},
            ),
            "参考音频文字稿不能为空。",
        ),
        (
            lambda: _breeze("breeze_tts2.clone", voice=MediaInput("audio/webm", b"x"), **_CLONE),
            "参考音色只接受 audio/wav。",
        ),
        (
            lambda: _breeze(
                "breeze_tts2.voice_design", text="你好", voice_description="声", seed=True
            ),
            "Seed必须是 0 到 2^63-1 的整数。",
        ),
    ],
)
def test_breeze_recipe_requests_reject(factory, message: str) -> None:
    _rejects(factory, message)


def test_speech_recognition_request_constructs() -> None:
    assert len(_wav()) >= 44
    for language in ("auto", "zh", "en"):
        request = SpeechRecognitionRequest(_wav(), "audio/wav", language)
        assert request.language == language
    assert SpeechRecognitionRequest(_wav(), "audio/wav").language == "auto"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: SpeechRecognitionRequest(_wav(), "audio/mpeg"),
            "Whisper ASR 当前只接受 WAV Reference Voice。",
        ),
        (
            lambda: SpeechRecognitionRequest(_wav()[:43], "audio/wav"),
            "Whisper ASR 输入必须是真实 WAV 音频。",
        ),
        (
            lambda: SpeechRecognitionRequest(
                b"RIFF" + b"\x00" * 4 + b"data" + b"\x00" * 32, "audio/wav"
            ),
            "Whisper ASR 输入必须是真实 WAV 音频。",
        ),
        (
            lambda: SpeechRecognitionRequest(_wav(_64_MIB + 1), "audio/wav"),
            "Whisper ASR 输入必须是真实 WAV 音频。",
        ),
        (
            lambda: SpeechRecognitionRequest(_wav(), "audio/wav", "ja"),
            "Whisper ASR language 只允许 auto、zh 或 en。",
        ),
    ],
)
def test_speech_recognition_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_fl2va_request_constructs() -> None:
    frame = _keyframe()
    KeyframeImage("image/webp", _png())
    request = FL2VARequest(
        "船驶入港湾",
        first_frame=frame,
        width=256,
        height=256,
        duration_seconds=0.2,
        seed=0,
        steps=8,
        cfg=0,
        save_audio=True,
        sage_attention=False,
        selflift=False,
    )
    assert request.last_frame is None
    assert (request.sage_attention, request.selflift) == (False, False)
    assert request.save_audio is True
    tail = FL2VARequest(
        "船靠岸",
        last_frame=frame,
        width=1920,
        height=1088,
        duration_seconds=15,
        seed=2**63 - 1,
        steps=20,
        cfg=30,
    )
    assert tail.first_frame is None
    assert tail.width == 1920
    defaults = FL2VARequest("船", first_frame=frame)
    assert (defaults.width, defaults.height, defaults.duration_seconds) == (832, 480, 3.0)
    assert (defaults.seed, defaults.steps, defaults.cfg, defaults.save_audio) == (
        42,
        20,
        1.0,
        False,
    )
    assert (defaults.sage_attention, defaults.selflift) == (True, True)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: KeyframeImage("image/gif", _png()), "关键帧图片类型不受支持。"),
        (lambda: KeyframeImage("image/png", b""), "关键帧图片大小不合法。"),
        (lambda: KeyframeImage("image/png", _png(_64_MIB + 1)), "关键帧图片大小不合法。"),
        (lambda: FL2VARequest("船"), "H3 FL2VA 至少需要首帧或尾帧之一。"),
        (lambda: FL2VARequest("船", first_frame=object()), "关键帧图片类型不受支持。"),
        (lambda: FL2VARequest("", first_frame=_keyframe()), "prompt 必须是 1 到 20000 字符。"),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), width=272),
            "画布边长必须是 32 的倍数且在 256 到 1920 之间。",
        ),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), width=257),
            "画布边长必须是 32 的倍数且在 256 到 1920 之间。",
        ),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), height=1952),
            "画布边长必须是 32 的倍数且在 256 到 1920 之间。",
        ),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), width=1920, height=1120),
            "画布像素过大。",
        ),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), duration_seconds=0.19),
            "duration_seconds 必须是不短于 0.2 秒的有限数值。",
        ),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), duration_seconds=float("inf")),
            "duration_seconds 必须是不短于 0.2 秒的有限数值。",
        ),
        (lambda: FL2VARequest("船", first_frame=_keyframe(), steps=0), "H3 步数只允许 20 或 8。"),
        (lambda: FL2VARequest("船", first_frame=_keyframe(), steps=12), "H3 步数只允许 20 或 8。"),
        (
            lambda: FL2VARequest("船", first_frame=_keyframe(), selflift=1),
            "H3 sage_attention 与 selflift 必须是布尔值。",
        ),
        (lambda: FL2VARequest("船", first_frame=_keyframe(), seed=-1), "采样参数不合法。"),
        (lambda: FL2VARequest("船", first_frame=_keyframe(), cfg=-0.1), "采样参数不合法。"),
        (lambda: FL2VARequest("船", first_frame=_keyframe(), cfg=30.1), "采样参数不合法。"),
    ],
)
def test_fl2va_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_ref2va_request_constructs() -> None:
    audios = tuple(_reference_audio() for _ in range(8))
    frames = tuple(_reference_image() for _ in range(4))
    videos = (ReferenceVideo("video/mp4", _mp4(), 2.0), _reference_video(15.0), _reference_video())
    request = Ref2VARequest(
        "保持房间一致",
        audios,
        first_frame=_reference_image(),
        additional_frames=frames,
        width=480,
        height=832,
        duration_seconds=15,
        seed=2**63 - 1,
        steps=8,
        cfg=30,
        save_audio=True,
        reference_videos=videos,
    )
    assert len(request.reference_audios) == 8
    assert len(request.additional_frames) == 4
    assert len(request.reference_videos) == 3
    assert request.reference_videos[0].duration_seconds == 2.0
    tail_only = Ref2VARequest("两段参考", (), last_frame=_reference_image())
    assert tail_only.first_frame is None
    assert tail_only.reference_audios == ()
    assert tail_only.reference_videos == ()
    assert tail_only.save_audio is False
    audio_only = Ref2VARequest("只使用音频参考", (_reference_audio(),))
    assert audio_only.first_frame is None
    assert audio_only.last_frame is None
    assert audio_only.additional_frames == ()
    assert len(audio_only.reference_audios) == 1
    assert audio_only.reference_videos == ()


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ReferenceImage("text/plain", _jpeg()), "参考图片类型不受支持。"),
        (lambda: ReferenceImage("image/png", _png(_64_MIB + 1)), "参考图片大小不合法。"),
        (lambda: ReferenceAudio("audio/mpeg", _wav()), "H3 参考音频只接受 WAV。"),
        (lambda: ReferenceAudio("audio/wav", b""), "H3 参考音频大小不合法。"),
        (lambda: ReferenceAudio("audio/wav", _wav(_64_MIB + 1)), "H3 参考音频大小不合法。"),
        (lambda: ReferenceVideo("video/webm", _mp4(), 3.0), "H3 参考视频只接受 MP4。"),
        (lambda: ReferenceVideo("video/mp4", b"", 3.0), "H3 参考视频必须是真实 MP4。"),
        (
            lambda: ReferenceVideo("video/mp4", b"not-an-mp4-file", 3.0),
            "H3 参考视频必须是真实 MP4。",
        ),
        (
            lambda: ReferenceVideo("video/mp4", _mp4(_512_MIB + 1), 3.0),
            "H3 参考视频必须是真实 MP4。",
        ),
        (
            lambda: ReferenceVideo("video/mp4", _mp4(), 1.9),
            "H3 参考视频时长必须在 2 到 15 秒之间。",
        ),
        (
            lambda: ReferenceVideo("video/mp4", _mp4(), 15.1),
            "H3 参考视频时长必须在 2 到 15 秒之间。",
        ),
        (
            lambda: Ref2VARequest("房间", ()),
            "Ref2VA 至少需要一个媒体参考。",
        ),
        (
            lambda: Ref2VARequest(
                "房间",
                (),
                first_frame=_reference_image(),
                reference_videos=(_reference_video(),) * 4,
            ),
            "Ref2VA 参考视频必须是最多 3 项的元组。",
        ),
        (
            lambda: Ref2VARequest(
                "房间",
                (),
                first_frame=_reference_image(),
                reference_videos=[_reference_video()],
            ),
            "Ref2VA 参考视频必须是最多 3 项的元组。",
        ),
        (
            lambda: Ref2VARequest(
                "房间",
                (),
                first_frame=_reference_image(),
                reference_videos=(_reference_audio(),),
            ),
            "Ref2VA 参考视频必须是最多 3 项的元组。",
        ),
        (lambda: Ref2VARequest("房间", (), first_frame=object()), "参考图片类型不受支持。"),
        (
            lambda: Ref2VARequest(
                "房间",
                (),
                first_frame=_reference_image(),
                additional_frames=(_reference_image(),) * 5,
            ),
            "Ref2VA 附加参考图必须是最多 4 项的图片元组。",
        ),
        (
            lambda: Ref2VARequest(
                "房间", (), first_frame=_reference_image(), additional_frames=[_reference_image()]
            ),
            "Ref2VA 附加参考图必须是最多 4 项的图片元组。",
        ),
        (
            lambda: Ref2VARequest(
                "房间", (), first_frame=_reference_image(), additional_frames=(_image(),)
            ),
            "Ref2VA 附加参考图必须是最多 4 项的图片元组。",
        ),
        (
            lambda: Ref2VARequest(
                "房间", (_reference_audio(),) * 9, first_frame=_reference_image()
            ),
            "Ref2VA 参考音频必须是最多 8 项的元组。",
        ),
        (
            lambda: Ref2VARequest("房间", [_reference_audio()], first_frame=_reference_image()),
            "Ref2VA 参考音频必须是最多 8 项的元组。",
        ),
        (
            lambda: Ref2VARequest("", (), first_frame=_reference_image()),
            "prompt 必须是 1 到 20000 字符。",
        ),
        (
            lambda: Ref2VARequest(
                "房间", (), first_frame=_reference_image(), width=1920, height=1120
            ),
            "画布像素过大。",
        ),
        (
            lambda: Ref2VARequest(
                "房间", (), first_frame=_reference_image(), duration_seconds=0.19
            ),
            "duration_seconds 必须是不短于 0.2 秒的有限数值。",
        ),
        (
            lambda: Ref2VARequest("房间", (), first_frame=_reference_image(), width=255),
            "画布边长必须是 32 的倍数且在 256 到 1920 之间。",
        ),
        (
            lambda: Ref2VARequest("房间", (), first_frame=_reference_image(), steps=0),
            "H3 步数只允许 20 或 8。",
        ),
    ],
)
def test_ref2va_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_video_upscale_request_constructs() -> None:
    UpscaleVideo("video/mp4", _mp4())
    request = VideoUpscaleRequest(
        _video(), target_short_side=1440, max_long_side=1280, seed=2**63 - 1
    )
    assert request.target_short_side == 1440
    defaults = VideoUpscaleRequest(_video())
    assert (defaults.target_short_side, defaults.max_long_side, defaults.seed) == (720, 1280, 42)
    assert VideoUpscaleRequest(_video(), 720, 2560, 0).seed == 0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: UpscaleVideo("video/webm", _mp4()), "SeedVR2 输入必须是非空 MP4。"),
        (lambda: UpscaleVideo("video/mp4", b""), "SeedVR2 输入必须是非空 MP4。"),
        (lambda: UpscaleVideo("video/mp4", _mp4(_512_MIB + 1)), "SeedVR2 输入视频过大。"),
        (lambda: VideoUpscaleRequest(object()), "SeedVR2 输入必须是非空 MP4。"),
        (
            lambda: VideoUpscaleRequest(_video(), target_short_side=1081),
            "SeedVR2 target_short_side 不受支持。",
        ),
        (
            lambda: VideoUpscaleRequest(_video(), max_long_side=3840),
            "SeedVR2 max_long_side 不受支持。",
        ),
        (lambda: VideoUpscaleRequest(_video(), seed=-1), "SeedVR2 seed 不合法。"),
    ],
)
def test_video_upscale_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


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


def test_pano_view_request_constructs() -> None:
    request = PanoViewRequest(_pano_png(), 0, -60, 120, "9:16")
    assert (request.yaw_deg, request.pitch_deg, request.hfov_deg) == (0, -60, 120)
    assert PanoViewRequest(_pano_png(2049, 1024), 359.9, 60, 20, "2:1").aspect_ratio == "2:1"
    assert PanoViewRequest(_pano_jpeg(4096, 2048), 180.5, 0, 90, "16:9").yaw_deg == 180.5
    assert PanoViewRequest(_pano_png(16384, 8192), 0, 0, 90, "16:9").hfov_deg == 90


_PANO_SIZE = "全景必须是 2:1 等距柱状图，宽度在 1024 到 16384 像素之间。"


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


def _webp_like() -> bytes:
    return b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 16


def test_audio_separation_request_constructs() -> None:
    assert AudioSeparationRequest(_mp4(), "voice").stem == "voice"
    assert AudioSeparationRequest(_mp4(), "background").stem == "background"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: AudioSeparationRequest(b"short", "voice"), "音轨分离输入必须是真实 MP4。"),
        (
            lambda: AudioSeparationRequest(_mp4(_512_MIB + 1), "voice"),
            "音轨分离输入必须是真实 MP4。",
        ),
        (
            lambda: AudioSeparationRequest(_mp4(), "music"),
            "音轨分离 stem 只允许 voice 或 background。",
        ),
    ],
)
def test_audio_separation_request_rejects(factory, message: str) -> None:
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


def test_text_to_audio_request_constructs() -> None:
    request = TextToAudioRequest("安静的钢琴", 10, 7)
    assert request.duration_seconds == 10
    assert request.seed == 7


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: TextToAudioRequest("  ", 10, 0), "文生音频提示词必须是 1 到 1000 个字符。"),
        (lambda: TextToAudioRequest("钢琴", 0.5, 0), "文生音频时长必须在 1 到 380 秒之间。"),
        (lambda: TextToAudioRequest("钢琴", 381, 0), "文生音频时长必须在 1 到 380 秒之间。"),
        (lambda: TextToAudioRequest("钢琴", True, 0), "文生音频时长必须在 1 到 380 秒之间。"),
        (lambda: TextToAudioRequest("钢琴", 10, -1), "文生音频 seed 不合法。"),
        (lambda: TextToAudioRequest("钢琴", 10, True), "文生音频 seed 不合法。"),
    ],
)
def test_text_to_audio_request_rejects(factory, message: str) -> None:
    _rejects(factory, message)


def test_h3_requests_have_no_duration_upper_limit():
    # 超过 15 秒只是可能 OOM 的软约束；Provider 契约不拒绝。
    assert (
        FL2VARequest("船", first_frame=_keyframe(), duration_seconds=30.0).duration_seconds == 30.0
    )
    assert (
        Ref2VARequest(
            "房间", (), first_frame=_reference_image(), duration_seconds=30.0
        ).duration_seconds
        == 30.0
    )
