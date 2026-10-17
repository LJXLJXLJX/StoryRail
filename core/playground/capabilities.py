"""Playground 能力目录：能力描述、输入解析与 Provider 请求构造。

L2：读取 Asset 元数据与字节（通过调用方传入的 ``read_asset``），构造 Provider
请求对象，但不调用 Provider、不写文档。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from core.media_assets import Mp4VideoFrames, read_mp4_video_frames
from core.model_providers.contracts import (
    AudioRemixRequest,
    PanoViewRequest,
    VideoFrameRequest,
)
from core.model_providers.manifest import Capability, PluginManifest, Recipe
from core.model_providers.recipe import (
    MediaInput,
    build_recipe_request,
    parse_recipe_wire,
)

from .models import PlaygroundAsset, PlaygroundCapability, PlaygroundDocument
from .parameters import (
    PARAMETER_SCHEMAS,
    input_asset_ids,
    parameter_seed,
    parse_parameters,
)

_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    id: str
    label: str
    execution: Literal["async", "sync"]
    registry_capability: str | None
    # None：参数形状来自当前绑定插件的 recipe（见 RECIPE_CAPABILITIES）。
    parameters_schema: dict[str, object] | None
    output_media_types: frozenset[str]
    notes: str
    group: str = "audio"


def resolve_recipe_request(
    manifest: PluginManifest,
    recipe: Recipe,
    parameters: dict[str, object],
    *,
    read_asset: Callable[[str], tuple[PlaygroundAsset, bytes]],
    settings: dict[str, object],
) -> ResolvedRequest:
    """按线上约定读出槽位 Asset，构造经 manifest 校验的 recipe 请求。"""
    bindings, params = parse_recipe_wire(recipe, parameters)
    inputs: dict[str, tuple[MediaInput, ...]] = {}
    sources: list[PlaygroundAsset] = []
    for slot in recipe.slots:
        items = []
        for binding in bindings[slot.key]:
            try:
                asset, content = read_asset(binding.asset_id)
            except (FileNotFoundError, KeyError) as exc:
                raise ValueError("参数引用的 Asset 不存在。") from exc
            sources.append(asset)
            items.append(
                MediaInput(asset.media_type, content, binding.description, asset.duration_seconds)
            )
        inputs[slot.key] = tuple(items)
    request = build_recipe_request(
        manifest, recipe.id, inputs=inputs, params=params, settings=settings
    )
    return ResolvedRequest(request, "submit_recipe", tuple(sources))


@dataclass(frozen=True, slots=True)
class ResolvedRequest:
    provider_request: object | None
    submit_method: str
    source_assets: tuple[PlaygroundAsset, ...]


CAPABILITY_SPECS: dict[PlaygroundCapability, CapabilitySpec] = {
    PlaygroundCapability.VIDEO_EXTRACT_FRAME: CapabilitySpec(
        id=PlaygroundCapability.VIDEO_EXTRACT_FRAME,
        group="video",
        label="按帧号抽帧",
        execution="async",
        registry_capability="video_frame",
        parameters_schema=PARAMETER_SCHEMAS[PlaygroundCapability.VIDEO_EXTRACT_FRAME],
        output_media_types=frozenset({"image/png"}),
        notes="帧号范围由 Core 从 MP4 读出；同一视频同时只允许一个抽帧任务。",
    ),
    PlaygroundCapability.IMAGE_PANO_VIEW: CapabilitySpec(
        id=PlaygroundCapability.IMAGE_PANO_VIEW,
        group="image",
        label="全景裁切",
        execution="async",
        registry_capability="pano_view",
        parameters_schema=PARAMETER_SCHEMAS[PlaygroundCapability.IMAGE_PANO_VIEW],
        output_media_types=frozenset({"image/png"}),
        notes=(
            "输入必须是 2:1 等距柱状全景 PNG/JPEG（宽 1024–16384）；yaw [0, 360)、"
            "pitch [-60, 60]、hfov [20, 120]，与生产全景裁切契约一致；一次裁一个视图。"
        ),
    ),
    PlaygroundCapability.AUDIO_REMIX: CapabilitySpec(
        id=PlaygroundCapability.AUDIO_REMIX,
        label="音轨重新混音",
        execution="async",
        registry_capability="audio_remix",
        parameters_schema=PARAMETER_SCHEMAS[PlaygroundCapability.AUDIO_REMIX],
        output_media_types=frozenset({"video/mp4"}),
        notes="增益范围 -100 到 24 dB；每一对起止时间必须同时提供或同时省略。",
    ),
    PlaygroundCapability.AUDIO_EFFECT: CapabilitySpec(
        id=PlaygroundCapability.AUDIO_EFFECT,
        label="音频后处理",
        execution="sync",
        registry_capability=None,
        parameters_schema=PARAMETER_SCHEMAS[PlaygroundCapability.AUDIO_EFFECT],
        output_media_types=frozenset({"audio/wav"}),
        notes="Core 本地 DSP，固定 radio 效果，不开放高级参数覆盖。",
    ),
    PlaygroundCapability.AUDIO_TRIM: CapabilitySpec(
        id=PlaygroundCapability.AUDIO_TRIM,
        label="音频截取",
        execution="sync",
        registry_capability=None,
        parameters_schema=PARAMETER_SCHEMAS[PlaygroundCapability.AUDIO_TRIM],
        output_media_types=frozenset({"audio/wav"}),
        notes="Core 本地 DSP；结束时间不能超过源音频时长。",
    ),
}


def _require_asset(
    read_asset: Callable[[str], tuple[PlaygroundAsset, bytes]],
    asset_id: str,
    field: str,
    media_type: str,
) -> tuple[PlaygroundAsset, bytes]:
    try:
        asset, content = read_asset(asset_id)
    except FileNotFoundError as exc:
        raise ValueError(f"参数引用的 Asset 不存在：{asset_id}。") from exc
    if media_type == "image":
        if asset.media_type not in _IMAGE_MEDIA_TYPES:
            raise ValueError(f"{field} 必须是图片。")
    elif asset.media_type != media_type:
        label = {"audio/wav": "WAV 音频", "video/mp4": "MP4 视频"}.get(media_type, media_type)
        raise ValueError(f"{field} 必须是 {label}。")
    return asset, content


def _image(
    read_asset: Callable[[str], tuple[PlaygroundAsset, bytes]], asset_id: str, field: str
) -> tuple[PlaygroundAsset, bytes]:
    return _require_asset(read_asset, asset_id, field, "image")


def resolve_request(
    capability: object,
    parameters: dict[str, object],
    *,
    document: PlaygroundDocument,
    read_asset: Callable[[str], tuple[PlaygroundAsset, bytes]],
) -> ResolvedRequest:
    """检查 Asset 存在性与媒体类型，并构造 Provider 请求（只在内存中）。

    已迁移的模型能力使用 resolve_recipe_request，确定性工具仍走类型化请求。
    """
    del document
    resolved = PlaygroundCapability(capability)
    if resolved is PlaygroundCapability.VIDEO_EXTRACT_FRAME:
        asset, content = _require_asset(
            read_asset, str(parameters["video_asset_id"]), "video_asset_id", "video/mp4"
        )
        frames = read_mp4_video_frames(content)
        index = int(parameters["frame_index"])  # type: ignore[arg-type]
        if index >= frames.frame_count:
            raise ValueError(f"帧号超出范围 0-{frames.frame_count - 1}。")
        return ResolvedRequest(
            VideoFrameRequest(content=content, frame_index=index), "submit", (asset,)
        )
    if resolved is PlaygroundCapability.IMAGE_PANO_VIEW:
        asset, content = _image(read_asset, str(parameters["image_asset_id"]), "image_asset_id")
        return ResolvedRequest(
            PanoViewRequest(
                content=content,
                yaw_deg=float(parameters["yaw_deg"]),  # type: ignore[arg-type]
                pitch_deg=float(parameters["pitch_deg"]),  # type: ignore[arg-type]
                hfov_deg=float(parameters["hfov_deg"]),  # type: ignore[arg-type]
                aspect_ratio=str(parameters["aspect_ratio"]),
            ),
            "submit",
            (asset,),
        )
    if resolved is PlaygroundCapability.AUDIO_REMIX:
        video_asset, video = _require_asset(
            read_asset, str(parameters["video_asset_id"]), "video_asset_id", "video/mp4"
        )
        voice_asset, voice = _require_asset(
            read_asset, str(parameters["voice_asset_id"]), "voice_asset_id", "audio/wav"
        )
        background_asset, background = _require_asset(
            read_asset,
            str(parameters["background_asset_id"]),
            "background_asset_id",
            "audio/wav",
        )
        assert voice_asset is not None and background_asset is not None
        return ResolvedRequest(
            AudioRemixRequest(
                video=video,
                voice=voice,
                background=background,
                voice_gain_db=float(parameters["voice_gain_db"]),  # type: ignore[arg-type]
                background_gain_db=float(parameters["background_gain_db"]),  # type: ignore[arg-type]
                voice_gain_start_seconds=parameters["voice_gain_start_seconds"],  # type: ignore[arg-type]
                voice_gain_end_seconds=parameters["voice_gain_end_seconds"],  # type: ignore[arg-type]
                background_gain_start_seconds=parameters["background_gain_start_seconds"],  # type: ignore[arg-type]
                background_gain_end_seconds=parameters["background_gain_end_seconds"],  # type: ignore[arg-type]
            ),
            "submit",
            (video_asset, voice_asset, background_asset),
        )
    # 本地能力：只校验源 Asset，Provider 请求留空。
    asset, _content = _require_asset(
        read_asset, str(parameters["audio_asset_id"]), "audio_asset_id", "audio/wav"
    )
    return ResolvedRequest(None, "", (asset,))


def run_output_label(
    capability: object,
    parameters: dict[str, object],
    *,
    run_id: str,
    document: PlaygroundDocument,
    recipe: Recipe | None = None,
) -> str:
    """01 §6.4 的产物可读文件名；源 Asset 已删除时用占位名。"""
    if recipe is not None:
        return f"{recipe.label}-{run_id[:8]}"
    resolved = PlaygroundCapability(capability)

    def source_name(asset_id: object) -> str:
        asset = next(
            (item for item in document.assets if item.id == asset_id),
            None,
        )
        if asset is not None:
            return asset.display_name
        if isinstance(asset_id, str) and len(asset_id) >= 8:
            return f"已删除素材-{asset_id[:8]}"
        return "已删除素材"

    if resolved is PlaygroundCapability.VIDEO_EXTRACT_FRAME:
        return f"{source_name(parameters['video_asset_id'])}-第{parameters['frame_index']}帧"
    if resolved is PlaygroundCapability.IMAGE_PANO_VIEW:
        return f"{source_name(parameters['image_asset_id'])}-全景裁切-yaw{parameters['yaw_deg']:g}"
    if resolved is PlaygroundCapability.AUDIO_REMIX:
        return f"{source_name(parameters['video_asset_id'])}-音轨混音"
    if resolved is PlaygroundCapability.AUDIO_EFFECT:
        return f"{source_name(parameters['audio_asset_id'])}-{parameters['preset']}"
    return f"{source_name(parameters['audio_asset_id'])}-截取"


def recipe_spec(recipe: Recipe) -> CapabilitySpec:
    output = {
        Capability.IMAGE_GENERATE: _IMAGE_MEDIA_TYPES,
        Capability.IMAGE_EDIT: _IMAGE_MEDIA_TYPES,
        Capability.VIDEO_GENERATE: frozenset({"video/mp4"}),
        Capability.VIDEO_UPSCALE: frozenset({"video/mp4"}),
        Capability.SPEECH_RECOGNIZE: frozenset(),
    }.get(recipe.capability, frozenset({"audio/wav"}))
    return CapabilitySpec(
        recipe.id,
        recipe.label,
        "sync" if recipe.capability is Capability.SPEECH_RECOGNIZE else "async",
        None,
        None,
        output,
        "参数约束与生产共用当前插件声明。",
        "speech"
        if recipe.capability
        in {Capability.VOICE_DESIGN, Capability.SPEECH_SYNTHESIZE, Capability.SPEECH_RECOGNIZE}
        else recipe.capability.value.split(".")[0],
    )


def capability_spec(capability: object, *, recipe: Recipe | None = None) -> CapabilitySpec:
    if recipe is not None:
        return recipe_spec(recipe)
    try:
        return CAPABILITY_SPECS[PlaygroundCapability(capability)]
    except ValueError as exc:
        raise ValueError(f"不支持的 capability：{capability}") from exc


__all__ = [
    "CAPABILITY_SPECS",
    "CapabilitySpec",
    "Mp4VideoFrames",
    "ResolvedRequest",
    "capability_spec",
    "input_asset_ids",
    "parameter_seed",
    "parse_parameters",
    "run_output_label",
    "resolve_request",
]
