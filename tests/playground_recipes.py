"""插件场景测试名与真实 recipe；生产目录从 manifest 生成。"""

from enum import StrEnum

from core.model_providers.breeze_tts2.manifest import MANIFEST as TTS
from core.model_providers.codex_image.manifest import MANIFEST as IMAGE
from core.model_providers.demucs_audio.manifest import MANIFEST as SEPARATE
from core.model_providers.minimax_h3.manifest import MANIFEST as VIDEO
from core.model_providers.recipe import recipe_wire_schema
from core.model_providers.seedvr2_7b_sharp_fp8.manifest import MANIFEST as UPSCALE
from core.model_providers.stable_audio_3.manifest import MANIFEST as AUDIO
from core.model_providers.whisper_asr.manifest import MANIFEST as ASR
from core.playground.capabilities import (
    CAPABILITY_SPECS as TOOLS,
)
from core.playground.capabilities import (
    recipe_spec,
    resolve_recipe_request,
)
from core.playground.capabilities import (
    resolve_request as resolve_tool,
)
from core.playground.parameters import parse_parameters as parse_core


class PlaygroundCapability(StrEnum):
    IMAGE_GENERATE = "codex_image.generate"
    IMAGE_EDIT = "codex_image.edit"
    TTS_VOICE_DESIGN = "breeze_tts2.voice_design"
    TTS_VOICE_CLONE = "breeze_tts2.clone"
    ASR_TRANSCRIBE = "whisper_asr.transcribe"
    VIDEO_FL2VA = "minimax_h3.fl2va"
    VIDEO_REF2VA = "minimax_h3.ref2va"
    VIDEO_UPSCALE = "seedvr2_7b_sharp_fp8.upscale"
    AUDIO_SEPARATE = "demucs_audio.separate"
    AUDIO_GENERATE = "stable_audio_3.generate"
    VIDEO_EXTRACT_FRAME = "video.extract_frame"
    IMAGE_PANO_VIEW = "image.pano_view"
    AUDIO_REMIX = "audio.remix"
    AUDIO_EFFECT = "audio.effect"
    AUDIO_TRIM = "audio.trim"


MANIFESTS = (IMAGE, TTS, VIDEO, UPSCALE, SEPARATE, AUDIO, ASR)
RECIPES = {r.id: (m, r) for m in MANIFESTS for r in m.recipes}
RECIPE_CAPABILITIES = {key: recipe.capability for key, (_manifest, recipe) in RECIPES.items()}
CAPABILITY_SPECS = {
    **TOOLS,
    **{key: recipe_spec(recipe) for key, (_manifest, recipe) in RECIPES.items()},
}
PARAMETER_SCHEMAS = {
    **{key: value.parameters_schema for key, value in TOOLS.items()},
    **{key: recipe_wire_schema(recipe) for key, (_m, recipe) in RECIPES.items()},
}


def recipe_for(capability):
    return RECIPES.get(str(capability), (None, None))[1]


def parse_parameters(capability, value, **kwargs):
    return parse_core(
        capability, value, recipe=kwargs.pop("recipe", recipe_for(capability)), **kwargs
    )


def resolve_request(capability, parameters, *, document, read_asset):
    if capability in RECIPES:
        manifest, recipe = RECIPES[capability]
        return resolve_recipe_request(
            manifest,
            recipe,
            parameters,
            read_asset=read_asset,
            settings=manifest.default_settings(),
        )
    return resolve_tool(capability, parameters, document=document, read_asset=read_asset)
