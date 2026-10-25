"""MiniMax H3 视频插件 manifest：FL2VA 与 Ref2VA 两个 recipe 共用一组实例设置。"""

from __future__ import annotations

from dataclasses import replace

from core.model_providers.manifest import (
    IMAGE_MEDIA_TYPES,
    Capability,
    DefaultRule,
    DomainPredicate,
    Field,
    Option,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
    aspect_ratio_field,
    prompt_field,
    seed_field,
)
from core.model_providers.minimax_h3.render import H3RenderSettings, H3Resolution

# 预设把“基础模型 + 步数”绑在一起，避免分开选择出非法组合。
_PRESET_STEPS = {"hybrid_v2": 20, "turbo_v2": 8}

_PARAMS = (
    prompt_field(20_000, "H3 提示词"),
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

MANIFEST = PluginManifest(
    plugin_id="minimax_h3",
    plugin_version=2,
    label="MiniMax H3",
    settings=(
        Field(
            "preset",
            Widget.PRESET,
            "基础模型",
            default="hybrid_v2",
            options=(
                Option("hybrid_v2", "DaSiWa Hybrid V2 · 20 步"),
                Option("turbo_v2", "Turbo V2 · 8 步"),
            ),
            summary=True,
        ),
        Field(
            "resolution",
            Widget.ENUM,
            "分辨率",
            default="720p",
            options=tuple(Option(item.value, item.value) for item in H3Resolution),
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
            "minimax_h3.fl2va",
            Capability.VIDEO_GENERATE,
            "FL2VA",
            slots=_FRAME_SLOTS,
            params=_PARAMS,
            require_any=("first_frame", "last_frame"),
            label_namespaces=(("picture", "<Picture {n}>"),),
            skills=("h3-prompt-writing",),
        ),
        Recipe(
            "minimax_h3.ref2va",
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
                replace(item, default=8) if item.role is Role.DURATION else item for item in _PARAMS
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
            skills=("h3-prompt-writing",),
        ),
    ),
    defaults=(
        (
            Capability.VIDEO_GENERATE,
            (
                DefaultRule("minimax_h3.ref2va", DomainPredicate.SEGMENT_HAS_DIALOGUE),
                DefaultRule("minimax_h3.fl2va"),
            ),
        ),
    ),
)


def render_settings(values: dict[str, object]) -> H3RenderSettings:
    """插件设置 → 提交时使用的渲染组合（画布、步数与开关）。"""
    settings = MANIFEST.validate_settings(values)
    return H3RenderSettings(
        H3Resolution(settings["resolution"]),
        _PRESET_STEPS[settings["preset"]],
        settings["sage_attention"],
        settings["selflift"],
    )
