from __future__ import annotations

from core.media_assets import (
    MEDIA_EXTENSION,
    asset_filename,
    mp4_duration,
    uploaded_asset_label,
    validate_media_bytes,
    wav_duration,
)

from .models import (
    GenerationOperation,
    ImageAssetCategory,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    StructuredDirectorDocument,
)
from .script_index import shot_segments

# 位置无关的媒体工具已移到 core/media_assets；这里保留项目内部沿用的下划线名字，
# 现有调用点不需要改动。
_MEDIA_EXTENSION = MEDIA_EXTENSION
_asset_filename = asset_filename
_mp4_duration = mp4_duration
_uploaded_asset_label = uploaded_asset_label
_validate_media_bytes = validate_media_bytes
_wav_duration = wav_duration


def _generation_asset_location(
    document: StructuredDirectorDocument,
    generation: ReferenceGeneration,
) -> tuple[str, str]:
    kind = generation.kind
    if kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        owner = document.reference_library.look_owner(generation.target_id)
        name = "未命名造型" if owner is None else f"{owner[0].name}-{owner[1].name}"
        return "images/characters", f"角色-{name}-设定图候选"
    if kind is ReferenceGenerationKind.CHARACTER_VOICE:
        return (
            "audio/voice-references",
            f"角色-{_character_name(document, generation.target_id)}-参考音色候选",
        )
    if kind is ReferenceGenerationKind.NARRATOR_VOICE:
        narrator = document.reference_library.narrator
        name = narrator.name if narrator is not None else "旁白"
        return (
            "audio/voice-references",
            f"旁白-{name}-{_language_label(generation)}参考音色候选",
        )
    if kind is ReferenceGenerationKind.NARRATION_AUDIO:
        location = _narration_location(document, generation.target_id)
        return "audio/narration", f"{location}-旁白-{_language_label(generation)}"
    if kind is ReferenceGenerationKind.GENERATED_AUDIO:
        # 资产名就是这段音频朗读的文本；模型由快照的 Generation.model 展示。
        # Voice Design 的朗读文本在 sample_text；克隆（synthesize）的朗读文本在
        # prompt_text，sample_text 是参考音频的文字稿，不能用来命名。
        spoken = (
            generation.prompt_text
            if generation.operation is GenerationOperation.SYNTHESIZE
            else generation.sample_text or generation.prompt_text
        )
        return "audio/generated", spoken
    if kind is ReferenceGenerationKind.VIDEO_AUDIO_VOICE:
        return "audio/stems", f"{_asset_stem(document, generation.target_id)}-人声"
    if kind is ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND:
        return "audio/stems", f"{_asset_stem(document, generation.target_id)}-背景"
    if kind is ReferenceGenerationKind.VIDEO_AUDIO_REMIX:
        return "videos/audio-remixes", f"{_asset_stem(document, generation.target_id)}-音轨混音"
    if kind is ReferenceGenerationKind.LOCATION_MASTER_IMAGE:
        return "images/locations/master", f"地点-{_location_name(document, generation)}-主图候选"
    if kind is ReferenceGenerationKind.LOCATION_VIEW_CROP:
        return "images/locations/crops", f"地点-{_location_name(document, generation)}-裁切"
    if kind is ReferenceGenerationKind.LOCATION_VIEW_IMAGE:
        return "images/locations/views", f"地点-{_location_name(document, generation)}-视图候选"
    if kind is ReferenceGenerationKind.KEYFRAME_IMAGE:
        return "images/keyframes", f"{_keyframe_location(document, generation.target_id)}-候选"
    if kind is ReferenceGenerationKind.VIDEO_FRAME:
        return "images/video-frames", _video_frame_name(document, generation)
    if kind is ReferenceGenerationKind.SEGMENT_VIDEO:
        return "videos/segments", f"{_segment_location(document, generation.target_id)}-视频候选"
    if kind is ReferenceGenerationKind.VIDEO_UPSCALE:
        return "videos/upscaled", f"{_segment_location(document, generation.target_id)}-超分视频"
    if kind is ReferenceGenerationKind.FINAL_VIDEO:
        return "videos/final", f"{document.title}-最终成片-{_language_label(generation)}"
    if kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO:
        return (
            "videos/scene-final",
            f"{_scene_location(document, generation.target_id)}-Scene成片-"
            f"{_language_label(generation)}",
        )
    if kind is ReferenceGenerationKind.SCENE_ANIMATIC:
        return "videos/animatics", f"{_scene_location(document, generation.target_id)}-Animatic预览"
    raise ValueError("未知的 Generation Asset 用途。")


def _location_name(document: StructuredDirectorDocument, generation: ReferenceGeneration) -> str:
    """主图以 Location 为目标，裁切与视图以 LocationView 为目标。"""
    library = document.location_library
    if generation.kind is ReferenceGenerationKind.LOCATION_MASTER_IMAGE:
        location = library.location(generation.target_id)
        return "未定位" if location is None else location.name
    owner = library.view_owner(generation.target_id)
    return "未定位" if owner is None else f"{owner[0].name}-{owner[1].name}"


def _language_label(generation: ReferenceGeneration) -> str:
    return "中文" if generation.language is NarrationLanguage.ZH else "英文"


def _video_frame_name(document: StructuredDirectorDocument, generation: ReferenceGeneration) -> str:
    request = generation.video_frame_request
    frame = (
        "尾帧" if request is None or request.frame_index is None else f"第{request.frame_index}帧"
    )
    plan = document.keyframe_plan
    if plan is not None and any(item.id == generation.target_id for item in plan.keyframes):
        return f"{_keyframe_location(document, generation.target_id)}-抽帧-{frame}"
    return f"{_asset_stem(document, generation.target_id)}-抽帧-{frame}"


def _asset_stem(document: StructuredDirectorDocument, asset_id: str) -> str:
    asset = next((item for item in document.assets if item.id == asset_id), None)
    if asset is None:
        return "未定位视频"
    return asset.display_name.rsplit(".", 1)[0]


def _character_name(document: StructuredDirectorDocument, character_id: str) -> str:
    card = next(
        (item for item in document.reference_library.characters if item.id == character_id),
        None,
    )
    return card.name if card is not None else "未命名角色"


def _scene_location(document: StructuredDirectorDocument, scene_id: str) -> str:
    script = document.director_script
    if script is not None:
        for scene_index, scene in enumerate(script.scenes, 1):
            if scene.id == scene_id:
                return f"Scene-{scene_index:02d}-{scene.title}"
    return "Scene-未定位"


def _segment_coordinates(
    document: StructuredDirectorDocument, segment_id: str
) -> tuple[int, str, int, int] | None:
    script = document.director_script
    if script is None:
        return None
    for scene_index, scene in enumerate(script.scenes, 1):
        for shot_index, shot in enumerate(scene.shots, 1):
            for segment_index, segment in enumerate(shot_segments(scene, shot.id), 1):
                if segment.id == segment_id:
                    return scene_index, scene.title, shot_index, segment_index
    return None


def _segment_location(document: StructuredDirectorDocument, segment_id: str) -> str:
    coordinates = _segment_coordinates(document, segment_id)
    if coordinates is None:
        return "Segment-未定位"
    scene_index, scene_title, shot_index, segment_index = coordinates
    return (
        f"Scene-{scene_index:02d}-{scene_title}-Shot-{shot_index:02d}-Segment-{segment_index:02d}"
    )


def _keyframe_location(document: StructuredDirectorDocument, keyframe_id: str) -> str:
    plan = document.keyframe_plan
    if plan is None:
        return "Keyframe-未定位"
    keyframe = next((item for item in plan.keyframes if item.id == keyframe_id), None)
    if keyframe is None:
        return "Keyframe-未定位"
    boundary = "关键帧"
    binding = next(
        (
            item
            for item in plan.segments
            if item.start_keyframe_id == keyframe_id or item.end_keyframe_id == keyframe_id
        ),
        None,
    )
    if binding is not None:
        boundary = "首帧" if binding.start_keyframe_id == keyframe_id else "尾帧"
    return f"{_segment_location(document, keyframe.owner_segment_id)}-{boundary}"


def _narration_location(document: StructuredDirectorDocument, cue_id: str) -> str:
    script = document.director_script
    if script is not None:
        for scene_index, scene in enumerate(script.scenes, 1):
            for cue_index, cue in enumerate(scene.narration_cues, 1):
                if cue.id == cue_id:
                    return f"Scene-{scene_index:02d}-{scene.title}-Cue-{cue_index:02d}"
    return "旁白-Cue-未定位"


def _image_category_label(category: ImageAssetCategory | None) -> str:
    return {
        ImageAssetCategory.CHARACTER_REFERENCE: "角色参考图",
        ImageAssetCategory.LOCATION_MASTER: "地点主图",
        ImageAssetCategory.LOCATION_CROP: "地点裁切图",
        ImageAssetCategory.LOCATION_VIEW: "地点视图",
        ImageAssetCategory.KEYFRAME: "Keyframe 图",
        ImageAssetCategory.VIDEO_FRAME: "抽帧图",
        None: "历史未分类图片",
    }[category]
