"""Core 测试用的示例插件 manifest：覆盖全部 Capability 的典型 recipe 形状，不含任何外部协议。

Core 的测试只依赖 Provider SDK 与这些 manifest；具体模型插件（及其请求翻译、线上协议）由各自的
Provider 包自己测试。recipe 形状刻意贴近真实插件：首尾帧 / 多参考两种视频 recipe、带底图的改图、
带参考音色与文字稿的克隆、带输入检查的超分，以及插件设置与软提示。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from core.media_assets import read_mp4_video_size
from core.model_providers.manifest import (
    IMAGE_MEDIA_TYPES,
    Capability,
    DefaultRule,
    DomainPredicate,
    Field,
    ImagePromptConvention,
    Option,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
    aspect_ratio_field,
    image_aspect_ratio_field,
    prompt_field,
    seed_field,
)

IMAGE = PluginManifest(
    plugin_id="sample_image",
    plugin_version=1,
    label="示例图片",
    recipes=(
        Recipe(
            "sample_image.generate",
            Capability.IMAGE_GENERATE,
            "生图",
            slots=(
                Slot(
                    "reference_image",
                    Role.REFERENCE_IMAGE,
                    "参考图",
                    maximum=5,
                    media_types=IMAGE_MEDIA_TYPES,
                ),
            ),
            params=(prompt_field(20_000), image_aspect_ratio_field()),
        ),
        Recipe(
            "sample_image.edit",
            Capability.IMAGE_EDIT,
            "改图",
            slots=(
                Slot(
                    "source_image",
                    Role.EDIT_SOURCE,
                    "底图",
                    minimum=1,
                    media_types=IMAGE_MEDIA_TYPES,
                ),
                Slot(
                    "reference_image",
                    Role.REFERENCE_IMAGE,
                    "参考图",
                    maximum=4,
                    media_types=IMAGE_MEDIA_TYPES,
                ),
            ),
            params=(prompt_field(20_000), image_aspect_ratio_field()),
            distinct_slots=("source_image", "reference_image"),
        ),
    ),
)

_CANVAS_SIZE_HELP = "留空时按画面比例与全局分辨率档位计算；填写时宽高须同时填写，且为 32 的倍数。"


def _canvas_params() -> tuple[Field, ...]:
    return (
        prompt_field(20_000),
        image_aspect_ratio_field(),
        seed_field(),
        Field(
            "width",
            Widget.NUMBER,
            "宽",
            nullable=True,
            minimum=256,
            maximum=2048,
            help=_CANVAS_SIZE_HELP,
            advanced=True,
        ),
        Field(
            "height",
            Widget.NUMBER,
            "高",
            nullable=True,
            minimum=256,
            maximum=2048,
            help=_CANVAS_SIZE_HELP,
            advanced=True,
        ),
    )


# 画布图片：输入图按 <imageN> 编号、单图不加标签，画幅由画布保证而不写进提示词。
CANVAS_IMAGE = PluginManifest(
    plugin_id="sample_canvas_image",
    plugin_version=1,
    label="示例画布图片",
    settings=(
        Field(
            "resolution",
            Widget.ENUM,
            "分辨率",
            default="2k",
            options=(
                Option("1k", "1K（长边 1024）"),
                Option("1_5k", "1.5K（长边 1536）"),
                Option("2k", "2K（长边 2048）"),
            ),
            summary=True,
        ),
    ),
    recipes=(
        Recipe(
            "sample_canvas_image.generate",
            Capability.IMAGE_GENERATE,
            "生图",
            slots=(
                Slot(
                    "reference_image",
                    Role.REFERENCE_IMAGE,
                    "参考图",
                    maximum=5,
                    media_types=IMAGE_MEDIA_TYPES,
                    namespace="image",
                ),
            ),
            params=_canvas_params(),
            label_namespaces=(("image", "<image{n}>"),),
            skills=("sample-canvas-image-prompt",),
        ),
        Recipe(
            "sample_canvas_image.edit",
            Capability.IMAGE_EDIT,
            "改图",
            slots=(
                Slot(
                    "source_image",
                    Role.EDIT_SOURCE,
                    "底图",
                    minimum=1,
                    media_types=IMAGE_MEDIA_TYPES,
                    namespace="image",
                ),
                Slot(
                    "reference_image",
                    Role.REFERENCE_IMAGE,
                    "参考图",
                    maximum=4,
                    media_types=IMAGE_MEDIA_TYPES,
                    namespace="image",
                ),
            ),
            params=_canvas_params(),
            label_namespaces=(("image", "<image{n}>"),),
            skills=("sample-canvas-image-prompt",),
            distinct_slots=("source_image", "reference_image"),
        ),
    ),
    image_prompt=ImagePromptConvention(
        "image", single_image_label="图片", aspect_ratio_in_prompt=False
    ),
)


def canvas_image_prompt_skills() -> list[dict]:
    return [
        {
            "name": "sample-canvas-image-prompt",
            "resources": [
                {
                    "name": "SKILL.md",
                    "text": "# 示例画布图片提示词\n\n多图时用 `<imageN>` 指代输入图，"
                    "单图称“图片”。\n",
                }
            ],
        }
    ]


_SPEECH_TEXT = Field(
    "text", Widget.PROMPT, "朗读文本", max_length=20_000, min_length=1, role=Role.SPEECH_TEXT
)

VOICE = PluginManifest(
    plugin_id="sample_voice",
    plugin_version=1,
    label="示例语音",
    recipes=(
        Recipe(
            "sample_voice.voice_design",
            Capability.VOICE_DESIGN,
            "音色设计",
            params=(
                _SPEECH_TEXT,
                Field(
                    "voice_description",
                    Widget.TEXT,
                    "音色描述",
                    max_length=4_000,
                    min_length=1,
                    role=Role.PROMPT,
                    help="用自然语言描述音色，不提供参考音频。",
                ),
                seed_field(),
            ),
        ),
        Recipe(
            "sample_voice.clone",
            Capability.SPEECH_SYNTHESIZE,
            "声音克隆",
            slots=(
                Slot(
                    "voice",
                    Role.VOICE_REFERENCE,
                    "参考音色",
                    minimum=1,
                    media_types=("audio/wav",),
                ),
            ),
            params=(
                _SPEECH_TEXT,
                Field(
                    "reference_transcript",
                    Widget.TEXT,
                    "参考音频文字稿",
                    max_length=20_000,
                    min_length=1,
                    role=Role.VOICE_TRANSCRIPT,
                ),
                Field(
                    "performance_instruction",
                    Widget.TEXT,
                    "表演指示",
                    nullable=True,
                    max_length=200,
                    min_length=1,
                    help="自然语言表演方式（语气、情绪、语速、停顿），可留空。",
                ),
                seed_field(),
            ),
        ),
    ),
)

_VIDEO_PARAMS = (
    prompt_field(20_000, "视频提示词"),
    Field(
        "duration_seconds", Widget.NUMBER, "时长（秒）", default=6, minimum=0.2, role=Role.DURATION
    ),
    seed_field(),
    aspect_ratio_field(),
)
_FRAME_SLOTS = (
    Slot(
        "first_frame", Role.FIRST_FRAME, "首帧", media_types=IMAGE_MEDIA_TYPES, namespace="picture"
    ),
    Slot("last_frame", Role.LAST_FRAME, "尾帧", media_types=IMAGE_MEDIA_TYPES, namespace="picture"),
)

VIDEO = PluginManifest(
    plugin_id="sample_video",
    plugin_version=2,
    label="示例视频",
    settings=(
        Field(
            "preset",
            Widget.PRESET,
            "基础模型",
            default="hybrid_v2",
            options=(Option("hybrid_v2", "质量 · 20 步"), Option("turbo_v2", "快速 · 8 步")),
            summary=True,
        ),
        Field(
            "resolution",
            Widget.ENUM,
            "分辨率",
            default="720p",
            options=(Option("480p", "480p"), Option("720p", "720p"), Option("1080p", "1080p")),
            summary=True,
        ),
        Field(
            "sage_attention",
            Widget.TOGGLE,
            "SageAttention",
            default=True,
            summary=True,
            summary_label="Sage",
        ),
        Field("selflift", Widget.TOGGLE, "SelfLift", default=True, summary=True),
    ),
    hints=(("soft_duration_limit_seconds", 15),),
    recipes=(
        Recipe(
            "sample_video.fl2va",
            Capability.VIDEO_GENERATE,
            "FL2VA",
            slots=_FRAME_SLOTS,
            params=_VIDEO_PARAMS,
            require_any=("first_frame", "last_frame"),
            label_namespaces=(("picture", "<Picture {n}>"),),
            skills=("sample-video-prompt",),
        ),
        Recipe(
            "sample_video.ref2va",
            Capability.VIDEO_GENERATE,
            "Ref2VA",
            slots=(
                *_FRAME_SLOTS,
                Slot(
                    "additional_images",
                    Role.REFERENCE_IMAGE,
                    "附加图片",
                    maximum=4,
                    media_types=IMAGE_MEDIA_TYPES,
                    describe="required",
                    namespace="picture",
                ),
                Slot(
                    "reference_audios",
                    Role.REFERENCE_AUDIO,
                    "参考音频",
                    maximum=3,
                    media_types=("audio/wav",),
                    describe="required",
                    namespace="audio",
                ),
                Slot(
                    "reference_videos",
                    Role.REFERENCE_VIDEO,
                    "参考视频",
                    maximum=3,
                    media_types=("video/mp4",),
                    duration_seconds=(2.0, 15.0),
                    describe="required",
                    namespace="video",
                ),
            ),
            params=tuple(
                replace(item, default=8) if item.role is Role.DURATION else item
                for item in _VIDEO_PARAMS
            ),
            require_any=(
                "first_frame",
                "last_frame",
                "additional_images",
                "reference_audios",
                "reference_videos",
            ),
            label_namespaces=(
                ("picture", "<Picture {n}>"),
                ("audio", "<Audio {n}>"),
                ("video", "<Video {n}>"),
            ),
            skills=("sample-video-prompt",),
        ),
    ),
    defaults=(
        (
            Capability.VIDEO_GENERATE,
            (
                DefaultRule("sample_video.ref2va", DomainPredicate.SEGMENT_HAS_DIALOGUE),
                DefaultRule("sample_video.fl2va"),
            ),
        ),
    ),
)


def _check_upscale_input(inputs: Mapping[str, tuple[Any, ...]], settings: Mapping[str, Any]):
    items = inputs.get("video", ())
    size = read_mp4_video_size(items[0].content) if items else None
    target = {"720p": 720, "1080p": 1080}[str(settings["resolution"])]
    if size is not None and min(size) >= target * 0.9:
        raise ValueError(f"原视频短边 {min(size)}px 已接近或超过目标档位，无需超分。")


UPSCALE = PluginManifest(
    plugin_id="sample_upscale",
    plugin_version=1,
    label="示例超分",
    settings=(
        Field(
            "resolution",
            Widget.ENUM,
            "目标分辨率",
            default="1080p",
            options=(Option("720p", "720p"), Option("1080p", "1080p")),
            summary=True,
        ),
    ),
    recipes=(
        Recipe(
            "sample_upscale.upscale",
            Capability.VIDEO_UPSCALE,
            "视频超分",
            slots=(
                Slot("video", Role.SOURCE_VIDEO, "来源视频", minimum=1, media_types=("video/mp4",)),
            ),
            params=(seed_field(maximum=2**32 - 1),),
            input_check=_check_upscale_input,
        ),
    ),
)

SEPARATION = PluginManifest(
    plugin_id="sample_separation",
    plugin_version=1,
    label="示例音轨分离",
    recipes=(
        Recipe(
            "sample_separation.separate",
            Capability.AUDIO_SEPARATE,
            "音轨分离",
            slots=(
                Slot("video", Role.SOURCE_VIDEO, "来源视频", minimum=1, media_types=("video/mp4",)),
            ),
            params=(
                Field(
                    "stem",
                    Widget.ENUM,
                    "音轨",
                    default="voice",
                    role=Role.AUDIO_STEM,
                    options=(Option("voice", "人声"), Option("background", "背景声")),
                ),
            ),
        ),
    ),
)

AUDIO = PluginManifest(
    plugin_id="sample_audio",
    plugin_version=1,
    label="示例文生音频",
    recipes=(
        Recipe(
            "sample_audio.generate",
            Capability.AUDIO_GENERATE,
            "文生音频",
            params=(
                prompt_field(1_000, "音乐或音效描述"),
                Field(
                    "duration_seconds",
                    Widget.NUMBER,
                    "时长（秒）",
                    default=10,
                    minimum=1,
                    maximum=380,
                    role=Role.DURATION,
                ),
                seed_field(),
            ),
        ),
    ),
)

ASR = PluginManifest(
    plugin_id="sample_asr",
    plugin_version=1,
    label="示例转写",
    recipes=(
        Recipe(
            "sample_asr.transcribe",
            Capability.SPEECH_RECOGNIZE,
            "语音转写",
            slots=(
                Slot("audio", Role.SOURCE_AUDIO, "音频", minimum=1, media_types=("audio/wav",)),
            ),
            params=(
                Field(
                    "language",
                    Widget.ENUM,
                    "识别语言",
                    default="auto",
                    options=(Option("auto", "自动"), Option("zh", "中文"), Option("en", "英文")),
                    role=Role.LANGUAGE,
                ),
            ),
        ),
    ),
)

MANIFESTS = (VOICE, VIDEO, IMAGE, UPSCALE, SEPARATION, AUDIO, ASR)

VIDEO_PROMPT_SKILL = {
    "name": "sample-video-prompt",
    "resources": [
        {
            "name": "SKILL.md",
            "text": "# 示例视频提示词\n\n用 `[Shot N] At MM:SS.mmm` 标记段内切镜；"
            "引用输入时使用 Core 给出的标签。\n",
        }
    ],
}


def video_prompt_skills() -> list[dict]:
    return [VIDEO_PROMPT_SKILL]


def video_output_duration(seconds: float) -> float:
    """示例帧网格：24 fps、帧数取 17k+5 且不少于请求时长，实际输出因此略长于请求。"""
    frames = max(5, math.ceil(seconds * 24))
    frames += (5 - frames) % 17
    return round(frames / 24, 3)


def format_video_workset(value: dict) -> dict:
    """示例视频插件的工作集格式：保留 Core 的领域事实，补上插件实际输出时长。"""
    context = value["context"]
    return {
        **value,
        "context": {
            **context,
            "output_duration_seconds": video_output_duration(context["duration_seconds"]),
        },
        "prompt_format": "sample-video-prompt",
    }


def lint_video_prompt(recipe_id: str, prompt: str, facts: dict) -> list[str]:
    """软提示：提示词没有引用任何已提交输入标签时提醒一次。"""
    labels = [label for label in facts.get("asset_labels", ()) if label]
    if labels and not any(label in prompt for label in labels):
        return ["提示词没有引用任何输入标签。"]
    return []
