"""单次图片调用的实际输入：名额优先级、同一 Asset 合并用途、超额拒绝。

Keyframe 与独立地点图片共用；上限只有 `models.MAX_IMAGE_INPUTS` 一个事实源。
调用方按名额优先级给出输入，超过上限时拒绝并按顺序列出会被挤掉的输入，不静默丢弃。
编辑底图（`source_asset_id`）在提交时排第一，不改变名额优先级。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .image_prompt_style import DEFAULT_IMAGE_PROMPT_STYLE, ImagePromptStyle
from .models import MAX_IMAGE_INPUTS, GenerationOperation, StructuredDirectorDocument


@dataclass(frozen=True, slots=True)
class ImageInput:
    asset_id: str
    # 拒绝信息里的短角色名，例如“角色参考”“前置帧”。
    role: str
    # 只读来源信息，不进入最终提示词；视觉用途由人或看图后的 Agent 编写。
    description: str


@dataclass(frozen=True, slots=True)
class ImageInputs:
    """实际传入图片插件的输入，顺序即 `Generation.input_asset_ids`。"""

    asset_ids: tuple[str, ...]
    # 与 asset_ids 同序：(Asset 显示名, 来源信息)，只用于输入预览。
    mapping: tuple[tuple[str, str], ...]
    operation: GenerationOperation
    # 与 asset_ids 同序：每张图承担的角色名（同一 Asset 合并多个角色），供预览按图展示。
    roles: tuple[tuple[str, ...], ...]

    def labels(self, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE) -> tuple[str, ...]:
        return tuple(
            style.label(index, len(self.asset_ids), f"<Picture{index}>")
            for index in range(1, len(self.asset_ids) + 1)
        )

    def lines(self, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE) -> tuple[str, ...]:
        """只读输入清单；不推断用途，也不拼接进最终提示词。"""
        return tuple(
            f"{label}: {name}（{' / '.join(roles)}）"
            for label, (name, _context), roles in zip(
                self.labels(style), self.mapping, self.roles, strict=True
            )
        )

    def describe(self, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE) -> list[dict]:
        return [
            {
                "index": index,
                "asset_id": asset_id,
                "label": label,
                "roles": list(roles),
            }
            for index, (asset_id, label, roles) in enumerate(
                zip(self.asset_ids, self.labels(style), self.roles, strict=True), 1
            )
        ]

    def validate_prompt(
        self, prompt_text: str, style: ImagePromptStyle = DEFAULT_IMAGE_PROMPT_STYLE
    ) -> str:
        """只核对显式标签，不生成、替换或重排任何引用说明；历史纯正文原样使用。"""
        text = prompt_text.strip()
        lines = text.splitlines()
        if lines and lines[0].strip() in {"图片引用：", "图片引用:"}:
            lines = lines[1:]
        labels = self.labels(style)
        actual = "|".join(re.escape(label) for label in labels)
        pattern = (
            rf"^({actual + '|' if actual else ''}<[^>\n]+>|图片|第 \d+ 张输入图)"
            r"\s*[:：]\s*(.*)$"
        )
        if not self.asset_ids:
            if lines and re.fullmatch(pattern, lines[0].strip()):
                raise ValueError("本次没有实际输入图，请直接填写画面正文，不写图片引用段。")
            return text
        if not lines or re.fullmatch(pattern, lines[0].strip()) is None:
            return text
        for index, label in enumerate(labels):
            match = re.fullmatch(pattern, lines[index].strip()) if index < len(lines) else None
            if match is None or match[1] != label or not match[2].strip():
                raise ValueError("图片引用段须按实际输入顺序填写标签与用途，请重读图片工作集。")
        body = "\n".join(lines[len(labels) :]).strip()
        for heading in ("画面正文：", "画面正文:"):
            if body.startswith(heading):
                body = body[len(heading) :].strip()
        if (
            not body
            or re.fullmatch(pattern, body.splitlines()[0])
            or any(label not in body for label in labels)
        ):
            raise ValueError("画面正文必须明确引用每张实际输入图的标签，说明保留与调整的内容。")
        return text


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
