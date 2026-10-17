"""插件把 Core 提交契约翻译成自家请求。"""

from __future__ import annotations

from core.model_providers.breeze_tts2 import MANIFEST as BREEZE_MANIFEST
from core.model_providers.breeze_tts2 import BreezeTTS2Request, BreezeVoiceReference
from core.model_providers.breeze_tts2.provider import to_request as to_breeze
from core.model_providers.codex_image import MANIFEST as IMAGE_MANIFEST
from core.model_providers.codex_image import (
    CodexImageEditRequest,
    CodexImageGenerateRequest,
    InputImage,
)
from core.model_providers.codex_image.provider import to_edit_request, to_generate_request
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
from core.model_providers.demucs_audio import MANIFEST as SEPARATION_MANIFEST
from core.model_providers.demucs_audio import DemucsAudioSeparationRequest
from core.model_providers.demucs_audio.provider import to_request as to_separation
from core.model_providers.ffmpeg_animatic import (
    AnimaticClipInput,
    AnimaticNarrationInput,
)
from core.model_providers.ffmpeg_animatic import (
    AnimaticRequest as PluginAnimaticRequest,
)
from core.model_providers.ffmpeg_animatic.provider import to_request as to_animatic
from core.model_providers.ffmpeg_audio_remix import FFmpegAudioRemixRequest
from core.model_providers.ffmpeg_audio_remix.provider import to_request as to_remix
from core.model_providers.ffmpeg_final_assembly import (
    FinalAssemblyClipInput,
    FinalAssemblyNarrationInput,
)
from core.model_providers.ffmpeg_final_assembly import (
    FinalAssemblyRequest as PluginAssemblyRequest,
)
from core.model_providers.ffmpeg_final_assembly.provider import to_request as to_assembly
from core.model_providers.ffmpeg_pano_view import PanoViewRequest as PluginPanoViewRequest
from core.model_providers.ffmpeg_pano_view.provider import to_request as to_pano
from core.model_providers.ffmpeg_video_frame import VideoFrameRequest as PluginVideoFrameRequest
from core.model_providers.ffmpeg_video_frame.provider import to_request as to_frame
from core.model_providers.minimax_h3.contracts import (
    FL2VARequest,
    KeyframeImage,
    Ref2VARequest,
    ReferenceAudio,
    ReferenceImage,
    ReferenceVideo,
)
from core.model_providers.minimax_h3.fl2va import H3KeyframeImage, MiniMaxH3FL2VARequest
from core.model_providers.minimax_h3.fl2va.provider import to_request as to_fl2va
from core.model_providers.minimax_h3.ref2va import (
    H3ReferenceAudio,
    H3ReferenceFrame,
    H3ReferenceVideo,
    MiniMaxH3Ref2VARequest,
)
from core.model_providers.minimax_h3.ref2va.provider import to_request as to_ref2va
from core.model_providers.recipe import MediaInput, build_recipe_request
from core.model_providers.seedvr2_7b_sharp_fp8 import MANIFEST as UPSCALE_MANIFEST
from core.model_providers.seedvr2_7b_sharp_fp8 import SeedVR2UpscaleRequest, SeedVR2Video
from core.model_providers.seedvr2_7b_sharp_fp8.provider import to_request as to_upscale
from core.model_providers.whisper_asr import MANIFEST as ASR_MANIFEST
from core.model_providers.whisper_asr import WhisperASRRequest
from core.model_providers.whisper_asr.provider import to_request as to_asr

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
_WAV = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32


def test_translations_match_plugin_requests() -> None:
    generated = build_recipe_request(
        IMAGE_MANIFEST,
        "codex_image.generate",
        inputs={"reference_image": (MediaInput("image/png", _PNG),)},
        params={"prompt": "客厅", "aspect_ratio": "16:9"},
    )
    assert to_generate_request(generated) == (
        CodexImageGenerateRequest("客厅", "16:9", (InputImage("image/png", _PNG),), "gpt-5.6-terra")
    )
    edited = to_edit_request(
        build_recipe_request(
            IMAGE_MANIFEST,
            "codex_image.edit",
            inputs={
                "source_image": (MediaInput("image/png", _PNG),),
                "reference_image": (MediaInput("image/png", _PNG + b"reference"),),
            },
            params={"prompt": "傍晚", "aspect_ratio": "9:16"},
        )
    )
    assert edited == CodexImageEditRequest(
        "傍晚",
        InputImage("image/png", _PNG),
        "9:16",
        (InputImage("image/png", _PNG + b"reference"),),
    )
    clone = build_recipe_request(
        BREEZE_MANIFEST,
        "breeze_tts2.clone",
        inputs={"voice": (MediaInput("audio/wav", _WAV),)},
        params={
            "text": "克隆",
            "reference_transcript": "原文",
            "performance_instruction": "慢",
            "seed": 4,
        },
    )
    assert to_breeze(clone) == BreezeTTS2Request(
        "克隆",
        "慢",
        BreezeVoiceReference("audio/wav", _WAV),
        "原文",
        4.0,
        4,
    )
    design = build_recipe_request(
        BREEZE_MANIFEST,
        "breeze_tts2.voice_design",
        inputs={},
        params={"text": "试音", "voice_description": "低沉", "seed": 9},
    )
    assert to_breeze(design) == BreezeTTS2Request("试音", "低沉", None, None, 4.0, 9)
    assert to_asr(
        build_recipe_request(
            ASR_MANIFEST,
            "whisper_asr.transcribe",
            inputs={"audio": (MediaInput("audio/wav", _WAV),)},
            params={"language": "zh"},
        )
    ) == WhisperASRRequest(_WAV, "audio/wav", "zh")
    frame = KeyframeImage("image/png", _PNG)
    assert to_fl2va(FL2VARequest("船", first_frame=frame, seed=8, save_audio=True)) == (
        MiniMaxH3FL2VARequest(
            "船",
            H3KeyframeImage("image/png", _PNG),
            None,
            832,
            480,
            3.0,
            8,
            20,
            1.0,
            True,
        )
    )
    audio = ReferenceAudio("audio/wav", _WAV)
    picture = ReferenceImage("image/jpeg", b"\xff\xd8\xff" + b"\x00" * 8)
    video_a = ReferenceVideo("video/mp4", _MP4, 2.0)
    video_b = ReferenceVideo("video/mp4", _MP4, 15.0)
    assert to_ref2va(
        Ref2VARequest(
            "房间",
            (audio,),
            last_frame=picture,
            additional_frames=(picture,),
            seed=2,
            reference_videos=(video_a, video_b),
        )
    ) == MiniMaxH3Ref2VARequest(
        "房间",
        (H3ReferenceAudio("audio/wav", _WAV),),
        None,
        H3ReferenceFrame("image/jpeg", picture.content),
        (H3ReferenceFrame("image/jpeg", picture.content),),
        832,
        480,
        3.0,
        2,
        20,
        1.0,
        False,
        (H3ReferenceVideo("video/mp4", _MP4, 2.0), H3ReferenceVideo("video/mp4", _MP4, 15.0)),
    )
    assert to_upscale(
        build_recipe_request(
            UPSCALE_MANIFEST,
            "seedvr2_7b_sharp_fp8.upscale",
            inputs={"video": (MediaInput("video/mp4", _MP4),)},
            params={"seed": 6},
        )
    ) == (SeedVR2UpscaleRequest(SeedVR2Video("video/mp4", _MP4), 720, 1280, 6))
    assert to_separation(
        build_recipe_request(
            SEPARATION_MANIFEST,
            "demucs_audio.separate",
            inputs={"video": (MediaInput("video/mp4", _MP4),)},
            params={"stem": "voice"},
        )
    ) == DemucsAudioSeparationRequest(_MP4, "voice")
    assert to_remix(AudioRemixRequest(_MP4, _WAV, _WAV, -3, 1, 0, 1, None, None)) == (
        FFmpegAudioRemixRequest(_MP4, _WAV, _WAV, -3, 1, 0, 1, None, None)
    )
    assert to_assembly(
        FinalAssemblyRequest(
            (AssemblyClip(_MP4, None, 1.25), AssemblyClip(_MP4, "seam_blend", 1.5)),
            (AssemblyNarration(_WAV, 1),),
            "16:9",
            0.2,
            0.5,
            1.5,
        )
    ) == PluginAssemblyRequest(
        (
            FinalAssemblyClipInput(_MP4, None, 1.25),
            FinalAssemblyClipInput(_MP4, "seam_blend", 1.5),
        ),
        (FinalAssemblyNarrationInput(_WAV, 1),),
        "16:9",
        0.2,
        0.5,
        1.5,
    )
    assert to_animatic(
        AnimaticRequest(
            (AnimaticClip(_PNG, None, 1.0),),
            (AnimaticNarration(_WAV, 0),),
            "9:16",
            0.1,
        )
    ) == PluginAnimaticRequest(
        (AnimaticClipInput(_PNG, None, 1.0),),
        (AnimaticNarrationInput(_WAV, 0),),
        "9:16",
        0.1,
    )
    assert to_frame(VideoFrameRequest(_MP4, 7)) == PluginVideoFrameRequest(_MP4, 7)
    pano = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
        + (2048).to_bytes(4, "big")
        + (1024).to_bytes(4, "big")
    )
    assert to_pano(PanoViewRequest(pano, 270, -15, 90, "9:16")) == PluginPanoViewRequest(
        pano, 270, -15, 90, "9:16"
    )
