"""角色造型设定图：输入图、固定版式与提示词编译；预览、提交与重试共用。

设定图固定 2:1：柔和浅灰底（纯白底容易过曝），左侧四视角，右侧头部特写。
版式只有一套、不预设人形：主体描述放在最前，非人形主体靠提示词约束（不得人形化、不画所处环境），不依赖额外的形体标记。
画幅与分辨率由插件画布保证时（`aspect_ratio_in_prompt = False`）沿用全局分辨率设置；
否则 Core 在提示词里写画幅与 4K 分辨率。
"""

from __future__ import annotations

from dataclasses import dataclass

from .image_inputs import ImageInput, ImageInputs, ordered_image_inputs
from .image_prompt_style import DEFAULT_IMAGE_PROMPT_STYLE, ImagePromptStyle
from .models import (
    CharacterCard,
    CharacterLook,
    GenerationOperation,
    StructuredDirectorDocument,
)

LOOK_SHEET_ASPECT_RATIO = "2:1"
LOOK_SHEET_MAX_IDENTITY_REFERENCES = 4

# 版式措辞刻意避开“站姿、双臂、头肩、五官、妆容、服装”等只属于人的词：
# 这些词会把动物、昆虫或怪物拉成人形。
_LAYOUT_RULE = (
    "设定图硬约束：\n"
    "- 画面主体只有一个，就是上方描述的对象。严格按描述的物种、身体结构、肢体数量与比例绘制；"
    "描述的是动物、昆虫、怪物或其它非人生物时，按真实生物绘制，不得画成人、人形或拟人化形象，"
    "不得添加描述中没有的人体、人脸或衣服；\n"
    "- 柔和的中性浅灰色（约 #BEBEBE）无缝背景，不用纯白；主体曝光正常，白色或浅色衣物、皮肤与毛发的"
    "亮部保留纹理细节，不过曝；只画主体本身，不画巢穴、蛛网、栖木、地面或任何所处环境，"
    "即使描述中提到；不出现文字、标注、色卡、水印或边框；\n"
    "- 画面左侧约四分之三：同一主体的四个视角等间距并排、同一比例，依次为正面、正侧面、背面，"
    "以及最能展示整体形态的第四个角度（直立的人形取四分之三侧面，伏地、爬行或多足生物取正上方俯视）；"
    "每个视角都是主体自然放松的静止姿态，完整不出画；\n"
    "- 画面右侧约四分之一：主体头部的正面特写，清晰呈现最能辨认身份的特征；\n"
    "- 所有视角中的外观、体型、颜色、花纹与附属物完全一致；均匀柔和的影棚平光，"
    "不加戏剧化光影、动作或特效。"
)


@dataclass(frozen=True, slots=True)
class LookSheetPlan:
    card: CharacterCard
    look: CharacterLook
    inputs: ImageInputs


def find_look(
    document: StructuredDirectorDocument, look_id: str
) -> tuple[CharacterCard, CharacterLook]:
    owner = document.reference_library.look_owner(look_id)
    if owner is None:
        raise ValueError("造型不存在。")
    return owner


def look_sheet_plan(
    document: StructuredDirectorDocument,
    look_id: str,
    identity_asset_ids: tuple[str, ...],
) -> LookSheetPlan:
    """校验身份参考并给出实际输入；身份参考只由调用方显式给出，Core 不推导。"""
    card, look = find_look(document, look_id)
    if len(identity_asset_ids) > LOOK_SHEET_MAX_IDENTITY_REFERENCES:
        raise ValueError(f"设定图最多使用 {LOOK_SHEET_MAX_IDENTITY_REFERENCES} 张身份参考图。")
    if len(set(identity_asset_ids)) != len(identity_asset_ids):
        raise ValueError("身份参考图不能重复。")
    assets = {item.id: item for item in document.assets}
    entries: list[ImageInput] = []
    for asset_id in identity_asset_ids:
        asset = assets.get(asset_id)
        if asset is None or not asset.media_type.startswith("image/"):
            raise ValueError("身份参考必须是项目内图片 Asset。")
        entries.append(
            ImageInput(
                asset_id,
                "身份参考",
                f"「{card.name}」身份参考；只保持身份识别特征、体型与比例一致，外观以本造型描述为准，"
                "不复制其构图、姿势或背景。",
            )
        )
    return LookSheetPlan(
        card,
        look,
        ordered_image_inputs(
            document, entries, operation=GenerationOperation.GENERATE, label="造型设定图的参考图"
        ),
    )


def look_sheet_prompt(
    plan: LookSheetPlan, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE
) -> str:
    lines = plan.inputs.lines(style)
    mapping = "输入图对应关系（按实际传入顺序）：\n" + "\n".join(lines) + "\n\n" if lines else ""
    # 画幅由插件画布保证时不写画幅与分辨率句，避免提示词与画布形成两个来源。
    canvas = (
        f"固定画幅：{LOOK_SHEET_ASPECT_RATIO} 横构图；"
        "以 4K 超高分辨率（4096×2048）输出，细节清晰锐利。\n"
        if style.aspect_ratio_in_prompt
        else ""
    )
    card, look = plan.card, plan.look
    # 主体描述放在版式之前：先确定“画的是什么”，版式只约束构图。
    return (
        mapping
        + canvas
        + f"主体「{card.name}」：{(card.visual_description or '').strip()}"
        + f"\n本次造型「{look.name}」：{look.appearance.strip()}"
        + "\n\n"
        + _LAYOUT_RULE
    )
