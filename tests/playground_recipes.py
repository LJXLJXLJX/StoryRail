"""插件场景测试名与示例 recipe；生产目录从示例 manifest 生成。"""

from enum import StrEnum

from sample_plugins import ASR, AUDIO, IMAGE, UPSCALE, VIDEO
from sample_plugins import SEPARATION as SEPARATE
from sample_plugins import VOICE as TTS

from core.model_providers.recipe import recipe_wire_schema
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
    IMAGE_GENERATE = "sample_image.generate"
    IMAGE_EDIT = "sample_image.edit"
    TTS_VOICE_DESIGN = "sample_voice.voice_design"
    TTS_VOICE_CLONE = "sample_voice.clone"
    ASR_TRANSCRIBE = "sample_asr.transcribe"
    VIDEO_FL2VA = "sample_video.fl2va"
    VIDEO_REF2VA = "sample_video.ref2va"
    VIDEO_UPSCALE = "sample_upscale.upscale"
    AUDIO_SEPARATE = "sample_separation.separate"
    AUDIO_GENERATE = "sample_audio.generate"
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
