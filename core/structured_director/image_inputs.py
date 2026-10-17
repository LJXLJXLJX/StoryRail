"""单次图片调用的实际输入：名额优先级、同一 Asset 合并用途、超额拒绝。

Keyframe 与地点主图/视图共用；上限只有 `models.MAX_IMAGE_INPUTS` 一个事实源。
调用方按名额优先级给出输入，超过上限时拒绝并按顺序列出会被挤掉的输入，不静默丢弃。
编辑底图（`source_asset_id`）在提交时排第一，不改变名额优先级。
"""

from __future__ import annotations

from dataclasses import dataclass

from .image_prompt_style import DEFAULT_IMAGE_PROMPT_STYLE, ImagePromptStyle
from .models import MAX_IMAGE_INPUTS, GenerationOperation, StructuredDirectorDocument


@dataclass(frozen=True, slots=True)
class ImageInput:
    asset_id: str
    # 拒绝信息里的短角色名，例如“地点视图”“前置帧”。
    role: str
    # 写进输入图对应关系的用途说明。
    description: str


@dataclass(frozen=True, slots=True)
class ImageInputs:
    """实际传入图片插件的输入，顺序即 `Generation.input_asset_ids`。"""

    asset_ids: tuple[str, ...]
    # 与 asset_ids 同序：(Asset 显示名, 用途说明)；指代写法由图片插件约定决定。
    mapping: tuple[tuple[str, str], ...]
    operation: GenerationOperation
    # 与 asset_ids 同序：每张图承担的角色名（同一 Asset 合并多个角色），供预览按图展示。
    roles: tuple[tuple[str, ...], ...]

    def lines(self, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE) -> tuple[str, ...]:
        total = len(self.mapping)
        return tuple(
            f"{style.label(index, total, f'第 {index} 张输入图')}「{name}」：{description}"
            for index, (name, description) in enumerate(self.mapping, start=1)
        )


def ordered_image_inputs(
    document: StructuredDirectorDocument,
    entries: list[ImageInput],
    *,
    operation: GenerationOperation,
    label: str,
    source_asset_id: str | None = None,
) -> ImageInputs:
    """`entries` 按名额优先级排列；同一 Asset 只占一个名额并合并用途。"""
    ordered: list[str] = []
    roles: dict[str, list[str]] = {}
    descriptions: dict[str, list[str]] = {}
    for entry in entries:
        if entry.asset_id not in descriptions:
            ordered.append(entry.asset_id)
            roles[entry.asset_id] = []
            descriptions[entry.asset_id] = []
        if entry.role not in roles[entry.asset_id]:
            roles[entry.asset_id].append(entry.role)
        if entry.description not in descriptions[entry.asset_id]:
            descriptions[entry.asset_id].append(entry.description)
    names = {item.id: item.display_name for item in document.assets}
    if len(ordered) > MAX_IMAGE_INPUTS:
        dropped = "、".join(
            f"「{names.get(asset_id, asset_id)}」（{'/'.join(roles[asset_id])}）"
            for asset_id in ordered[MAX_IMAGE_INPUTS:]
        )
        raise ValueError(
            f"{label}合计 {len(ordered)} 张输入图，超过上限 {MAX_IMAGE_INPUTS} 张；"
            f"会被挤掉的输入：{dropped}。请减少参考后再生成。"
        )
    if source_asset_id is not None:
        if source_asset_id not in descriptions:
            raise RuntimeError("编辑底图必须出现在输入列表中。")
        ordered.remove(source_asset_id)
        ordered.insert(0, source_asset_id)
    return ImageInputs(
        tuple(ordered),
        tuple((names[asset_id], " ".join(descriptions[asset_id])) for asset_id in ordered),
        operation,
        tuple(tuple(roles[asset_id]) for asset_id in ordered),
    )
