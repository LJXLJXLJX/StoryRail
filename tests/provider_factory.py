"""测试公共工厂：Service 的唯一构造入口是 ProviderRegistry。

业务槽位名（`image_provider` 等）只作为测试表达便利保留在这里；产品代码不接受这些关键字参数。
recipe 能力以 `sample_plugins` 的示例 manifest 安装；测试替身收到的是 Core 的通用 `RecipeRequest`
（`slot()` / `param()` / `setting()`），不经过任何具体插件的请求翻译。
"""

from __future__ import annotations

import sample_plugins

from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.structured_director import StructuredDirectorService, StructuredDirectorStore

PROVIDER_SLOT_CAPABILITIES = {
    "final_assembly_provider": "final_assembly",
    "animatic_provider": "animatic",
    "video_frame_provider": "video_frame",
    "pano_view_provider": "pano_view",
    "audio_remix_provider": "audio_remix",
}


RECIPE_SLOTS = {
    "voice_provider": "sample_voice.voice_design",
    "speech_provider": "sample_voice.clone",
    "fl2va_provider": "sample_video.fl2va",
    "ref2va_provider": "sample_video.ref2va",
    "image_provider": "sample_image.generate",
    "speech_recognition_provider": "sample_asr.transcribe",
    "upscale_provider": "sample_upscale.upscale",
    "audio_separation_provider": "sample_separation.separate",
    "text_to_audio_provider": "sample_audio.generate",
}

# 同一个替身同时实现的 recipe。
_SHARED_RECIPES = {"sample_image.generate": ("sample_image.edit",)}


class RecipeAdapter:
    """把只有 `submit` / `transcribe` 的测试替身接成 recipe 实现；已有 recipe 方法的原样转发。"""

    def __init__(self, provider):
        self.provider = provider

    def __getattr__(self, key):
        return getattr(self.provider, key)

    def submit_recipe(self, request):
        if callable(getattr(self.provider, "submit_recipe", None)):
            return self.provider.submit_recipe(request)
        # 图片替身可以按生图 / 改图分别签发句柄。
        for suffix, method in ((".generate", "submit_generate"), (".edit", "submit_edit")):
            if request.recipe_id.endswith(suffix) and callable(
                getattr(self.provider, method, None)
            ):
                return getattr(self.provider, method)(request)
        return self.provider.submit(request)

    def execute_recipe(self, request):
        if callable(getattr(self.provider, "execute_recipe", None)):
            return self.provider.execute_recipe(request)
        return self.provider.transcribe(request)

    def observe(self, handle):
        return self.provider.observe(handle)

    def cancel(self, handle):
        return self.provider.cancel(handle)

    def read_artifact(self, handle, artifact_id):
        return self.provider.read_artifact(handle, artifact_id)


def sample_plugin(manifest, recipes, **kwargs) -> PluginInstance:
    """按示例 manifest 安装一组替身；视频与画布图片插件自动带上示例提示词钩子。"""
    if manifest.plugin_id == sample_plugins.VIDEO.plugin_id:
        kwargs.setdefault("prompt_formatter", sample_plugins.format_video_workset)
        kwargs.setdefault("prompt_skills", sample_plugins.video_prompt_skills)
        kwargs.setdefault("prompt_linter", sample_plugins.lint_video_prompt)
    if manifest.plugin_id == sample_plugins.CANVAS_IMAGE.plugin_id:
        kwargs.setdefault("prompt_skills", sample_plugins.canvas_image_prompt_skills)
    # 同一个替身实现多个 recipe 时共用一个适配器，句柄才能唯一回到它。
    adapters: dict[int, RecipeAdapter] = {}
    return PluginInstance(
        manifest,
        recipes={
            key: adapters.setdefault(id(value), RecipeAdapter(value))
            for key, value in recipes.items()
        },
        **kwargs,
    )


def provider_registry(**providers: object) -> ProviderRegistry:
    """按业务槽位名登记 Provider，返回唯一 ProviderRegistry。"""
    unknown = set(providers) - set(PROVIDER_SLOT_CAPABILITIES) - set(RECIPE_SLOTS)
    if unknown:
        raise TypeError(f"未知 Provider 槽位：{sorted(unknown)}")
    registry = ProviderRegistry()
    for slot, capability in PROVIDER_SLOT_CAPABILITIES.items():
        provider = providers.get(slot)
        if provider is not None:
            registry.register(capability, provider)
    for manifest in sample_plugins.MANIFESTS:
        recipes = {}
        for slot, recipe_id in RECIPE_SLOTS.items():
            provider = providers.get(slot)
            if provider is None or not any(recipe.id == recipe_id for recipe in manifest.recipes):
                continue
            recipes[recipe_id] = provider
            for shared in _SHARED_RECIPES.get(recipe_id, ()):
                recipes[shared] = provider
        if recipes:
            registry.install(sample_plugin(manifest, recipes))
    return registry


def make_service(store: StructuredDirectorStore, **providers: object) -> StructuredDirectorService:
    """测试工厂：Service 的唯一 registry 构造入口。"""
    return StructuredDirectorService(store, registry=provider_registry(**providers))
