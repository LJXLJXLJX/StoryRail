"""测试公共工厂：Service 的唯一构造入口是 ProviderRegistry。

业务槽位名（`image_provider` 等）只作为测试表达便利保留在这里；
产品代码不再接受这些关键字参数。
"""

from __future__ import annotations

from core.model_providers.breeze_tts2 import MANIFEST as BREEZE_MANIFEST
from core.model_providers.codex_image.manifest import MANIFEST as IMAGE_MANIFEST
from core.model_providers.codex_image.provider import to_edit_request, to_generate_request
from core.model_providers.demucs_audio.manifest import MANIFEST as SEPARATION_MANIFEST
from core.model_providers.demucs_audio.provider import to_request as to_separation
from core.model_providers.minimax_h3.manifest import MANIFEST as H3_MANIFEST
from core.model_providers.minimax_h3.prompt_context import format_prompt_workset, prompt_skills
from core.model_providers.minimax_h3.prompt_lint import lint_h3_prompt
from core.model_providers.minimax_h3.requests import to_request
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.model_providers.seedvr2_7b_sharp_fp8.manifest import MANIFEST as UPSCALE_MANIFEST
from core.model_providers.seedvr2_7b_sharp_fp8.provider import to_request as to_upscale
from core.model_providers.stable_audio_3.manifest import MANIFEST as AUDIO_MANIFEST
from core.model_providers.stable_audio_3.provider import to_request as to_audio
from core.model_providers.whisper_asr.manifest import MANIFEST as ASR_MANIFEST
from core.model_providers.whisper_asr.provider import to_request as to_asr
from core.structured_director import StructuredDirectorService, StructuredDirectorStore

PROVIDER_SLOT_CAPABILITIES = {
    "final_assembly_provider": "final_assembly",
    "animatic_provider": "animatic",
    "video_frame_provider": "video_frame",
    "pano_view_provider": "pano_view",
    "audio_remix_provider": "audio_remix",
}


# 已按 recipe 提交的能力：测试替身以真实插件 manifest 安装，提交收到 RecipeRequest。
RECIPE_SLOTS = {
    "voice_provider": "breeze_tts2.voice_design",
    "speech_provider": "breeze_tts2.clone",
    "fl2va_provider": "minimax_h3.fl2va",
    "ref2va_provider": "minimax_h3.ref2va",
    "image_provider": "codex_image.generate",
    "speech_recognition_provider": "whisper_asr.transcribe",
    "upscale_provider": "seedvr2_7b_sharp_fp8.upscale",
    "audio_separation_provider": "demucs_audio.separate",
    "text_to_audio_provider": "stable_audio_3.generate",
}


class _VideoRecipeAdapter:
    def __init__(self, provider):
        self.provider = provider

    def __getattr__(self, key):
        return getattr(self.provider, key)

    def submit_recipe(self, request):
        return self.provider.submit(to_request(request))

    def observe(self, handle):
        return self.provider.observe(handle)

    def cancel(self, handle):
        return self.provider.cancel(handle)

    def read_artifact(self, handle, artifact_id):
        return self.provider.read_artifact(handle, artifact_id)


class _RecipeAdapter(_VideoRecipeAdapter):
    def submit_recipe(self, request):
        if callable(getattr(self.provider, "submit_recipe", None)):
            return self.provider.submit_recipe(request)
        if request.recipe_id == "codex_image.generate":
            return self.provider.submit_generate(to_generate_request(request))
        if request.recipe_id == "codex_image.edit":
            return self.provider.submit_edit(to_edit_request(request))
        translator = {
            "seedvr2_7b_sharp_fp8.upscale": to_upscale,
            "demucs_audio.separate": to_separation,
            "stable_audio_3.generate": to_audio,
        }[request.recipe_id]
        return self.provider.submit(translator(request))

    def execute_recipe(self, request):
        if callable(getattr(self.provider, "execute_recipe", None)):
            return self.provider.execute_recipe(request)
        return self.provider.transcribe(to_asr(request))


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
    video_adapters = {
        id(provider): _VideoRecipeAdapter(provider)
        for slot, provider in providers.items()
        if slot in {"fl2va_provider", "ref2va_provider"}
    }
    for manifest in (
        BREEZE_MANIFEST,
        H3_MANIFEST,
        IMAGE_MANIFEST,
        UPSCALE_MANIFEST,
        SEPARATION_MANIFEST,
        AUDIO_MANIFEST,
        ASR_MANIFEST,
    ):
        recipes = {
            recipe_id: video_adapters[id(providers[slot])]
            if manifest is H3_MANIFEST
            else providers[slot]
            if manifest is BREEZE_MANIFEST
            else _RecipeAdapter(providers[slot])
            for slot, recipe_id in RECIPE_SLOTS.items()
            if providers.get(slot) is not None
            and any(recipe.id == recipe_id for recipe in manifest.recipes)
        }
        if manifest is IMAGE_MANIFEST and recipes:
            recipes["codex_image.edit"] = recipes["codex_image.generate"]
        if recipes:
            registry.install(
                PluginInstance(
                    manifest,
                    recipes=recipes,
                    prompt_formatter=format_prompt_workset if manifest is H3_MANIFEST else None,
                    prompt_skills=prompt_skills if manifest is H3_MANIFEST else None,
                    prompt_linter=lint_h3_prompt if manifest is H3_MANIFEST else None,
                )
            )
    return registry


def make_service(store: StructuredDirectorStore, **providers: object) -> StructuredDirectorService:
    """测试工厂：Service 的唯一 registry 构造入口。"""
    return StructuredDirectorService(store, registry=provider_registry(**providers))
