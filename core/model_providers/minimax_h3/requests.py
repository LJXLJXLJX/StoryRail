"""通用 recipe 输入翻译为 H3 请求；采样机制与渲染画布仅在插件内解释。"""

from core.model_providers.minimax_h3.contracts import (
    FL2VARequest,
    KeyframeImage,
    Ref2VARequest,
    ReferenceAudio,
    ReferenceImage,
    ReferenceVideo,
)
from core.model_providers.recipe import RecipeRequest

from .manifest import render_settings


def to_request(request: RecipeRequest):
    render = render_settings(dict(request.settings))
    width, height = render.canvas(request.param("aspect_ratio"))
    first, last = request.single("first_frame"), request.single("last_frame")
    common = dict(
        width=width,
        height=height,
        duration_seconds=request.param("duration_seconds"),
        seed=request.param("seed"),
        steps=render.steps,
        save_audio=True,
        sage_attention=render.sage_attention,
        selflift=render.selflift,
    )
    if request.recipe_id == "minimax_h3.fl2va":
        return FL2VARequest(
            request.param("prompt"),
            first_frame=None if first is None else KeyframeImage(first.media_type, first.content),
            last_frame=None if last is None else KeyframeImage(last.media_type, last.content),
            **common,
        )
    if request.recipe_id != "minimax_h3.ref2va":
        raise ValueError("未知 H3 recipe。")
    return Ref2VARequest(
        request.param("prompt"),
        tuple(
            ReferenceAudio(item.media_type, item.content)
            for item in request.slot("reference_audios")
        ),
        first_frame=None if first is None else ReferenceImage(first.media_type, first.content),
        last_frame=None if last is None else ReferenceImage(last.media_type, last.content),
        additional_frames=tuple(
            ReferenceImage(item.media_type, item.content)
            for item in request.slot("additional_images")
        ),
        reference_videos=tuple(
            ReferenceVideo(item.media_type, item.content, item.duration_seconds)
            for item in request.slot("reference_videos")
        ),
        **common,
    )
