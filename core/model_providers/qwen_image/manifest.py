"""Qwen Image 2.1（NoctQ V4）插件 manifest：生图与改图两个 recipe，共用同一张固定图。"""

from __future__ import annotations

from core.model_providers.manifest import (
    IMAGE_MEDIA_TYPES,
    Capability,
    Field,
    ImagePromptConvention,
    Option,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
    image_aspect_ratio_field,
    prompt_field,
    seed_field,
)

SKILL = "qwen-image-prompt-writing"
# 模型提示词模板按传入顺序给每张图加 <imageN> 前缀；官方约定单图不加标签。
LABELS = (("image", "<image{n}>"),)
SIZE_HELP = "留空时按画面比例与全局分辨率档位计算；填写时宽高须同时填写，且为 32 的倍数。"
# 分辨率档位 = 画布长边；短边按画面比例取整到 32 像素网格。
RESOLUTION_LONG_EDGE = {"1k": 1024, "1_5k": 1536, "2k": 2048}


def _params() -> tuple[Field, ...]:
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
            help=SIZE_HELP,
            advanced=True,
        ),
        Field(
            "height",
            Widget.NUMBER,
            "高",
            nullable=True,
            minimum=256,
            maximum=2048,
            help=SIZE_HELP,
            advanced=True,
        ),
    )


SETTINGS = (
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
    Field(
        "cfg",
        Widget.SLIDER,
        "CFG",
        default=3.0,
        minimum=1.0,
        maximum=8.0,
        help="大于 1 时启用负向提示词，提示词服从性更强，耗时约翻倍。",
    ),
    Field("steps", Widget.NUMBER, "采样步数", default=25, minimum=4, maximum=60),
    Field(
        "negative_prompt",
        Widget.TEXT,
        "负向提示词",
        default="",
        max_length=4_000,
        help="CFG 为 1 时不生效。",
    ),
)


MANIFEST = PluginManifest(
    plugin_id="qwen_image",
    plugin_version=1,
    label="Qwen Image 2.1（NoctQ V4）",
    settings=SETTINGS,
    recipes=(
        Recipe(
            "qwen_image.generate",
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
            params=_params(),
            label_namespaces=LABELS,
            skills=(SKILL,),
        ),
        Recipe(
            "qwen_image.edit",
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
            params=_params(),
            label_namespaces=LABELS,
            skills=(SKILL,),
            distinct_slots=("source_image", "reference_image"),
        ),
    ),
    image_prompt=ImagePromptConvention(
        "image", single_image_label="图片", aspect_ratio_in_prompt=False
    ),
)
