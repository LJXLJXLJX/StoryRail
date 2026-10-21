"""当前绑定图片插件的提示词约定：输入图指代与画幅句；预览、工作集与提交共用。"""

from __future__ import annotations

from dataclasses import dataclass

from core.model_providers.manifest import Capability, PluginManifest

from .models import GenerationOperation


@dataclass(frozen=True, slots=True)
class ImagePromptStyle:
    """未绑定插件或插件未声明约定时，使用 Core 默认 Picture 标签并写画幅句。"""

    manifest: PluginManifest | None = None
    recipe_id: str | None = None

    def label(self, index: int, total: int, default: str) -> str:
        """第 index 张（从 1 起）输入图的指代；default 是 Core 默认写法。"""
        if self.manifest is None or self.recipe_id is None:
            return default
        label = self.manifest.image_input_label(self.recipe_id, index, total)
        return default if label is None else label

    @property
    def labelled(self) -> bool:
        return self.manifest is not None and self.manifest.image_prompt is not None

    @property
    def aspect_ratio_in_prompt(self) -> bool:
        if self.manifest is None or self.manifest.image_prompt is None:
            return True
        return self.manifest.image_prompt.aspect_ratio_in_prompt


DEFAULT_IMAGE_PROMPT_STYLE = ImagePromptStyle()


def image_capability(operation: GenerationOperation) -> Capability:
    return (
        Capability.IMAGE_EDIT
        if operation is GenerationOperation.EDIT
        else Capability.IMAGE_GENERATE
    )


def image_prompt_style(catalog, operation: GenerationOperation) -> ImagePromptStyle:
    """按当前全局绑定解析；catalog 为 None（无 Provider 装配）时使用默认写法。"""
    if catalog is None:
        return DEFAULT_IMAGE_PROMPT_STYLE
    found = catalog.recipe_for(image_capability(operation))
    if found is None:
        return DEFAULT_IMAGE_PROMPT_STYLE
    plugin, recipe = found
    return ImagePromptStyle(plugin.manifest, recipe.id)
