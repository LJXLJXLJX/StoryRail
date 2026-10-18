"""领域模型：_shared 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

# 单次图片生成/编辑调用的输入图上限；Keyframe 与独立地点图片共用这一个事实源。
MAX_IMAGE_INPUTS = 5

_ID = re.compile(r"[0-9a-f]{32}")

_SHA256 = re.compile(r"[0-9a-f]{64}")

_COMMAND_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")

_ASSET_PATH = re.compile(
    r"assets/(?:"
    r"images/(?:library|characters|locations(?:/(?:captures|master|crops|views))?|keyframes|video-frames)|"
    r"audio/(?:voice-references|narration|dialogue|generated|effects|trims|stems|imported)|"
    r"videos/(?:segments|upscaled|final|scene-final|animatics|audio-remixes|imported)"
    r")/[^/\\\x00-\x1f]+\.(?:png|jpg|webp|wav|mp4)"
)


def _require_id(value: str, field: str) -> None:
    if not _ID.fullmatch(value):
        raise ValueError(f"{field} 不合法。")


def _require_text(value: str, field: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} 不能为空或超过 {maximum} 字符。")


def _validate_timestamp(value: str, field: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 不合法。") from exc


def _validate_unique_ids(values: tuple[str, ...], label: str) -> None:
    for value in values:
        _require_id(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} 不能重复。")


# 跨域共享枚举词汇（P2-B2 抽取校验时移入；models/__init__ 再导出保持路径不变）。


class StructuredDirectorStatus(StrEnum):
    AWAITING_PROPOSAL = "awaiting_reference_proposal"
    REVIEWING = "reviewing_references"
    REVIEWING_SCRIPT = "reviewing_script"
    REVIEWING_NARRATION = "reviewing_narration"
    REVIEWING_KEYFRAMES = "reviewing_keyframes"
    REVIEWING_VIDEOS = "reviewing_videos"
    REVIEWING_FINAL = "reviewing_final"
    APPROVED = "approved"


class NarrationLanguage(StrEnum):
    """旁白按项目所选语言建立；每条 Cue 所选语言各自合成、审核并选择音频。"""

    ZH = "zh"
    EN = "en"


NARRATION_LANGUAGES = (NarrationLanguage.ZH, NarrationLanguage.EN)


def parse_narration_languages(value: object) -> tuple[NarrationLanguage, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not 1 <= len(value) <= 2
        or any(not isinstance(item, str) or item not in {"zh", "en"} for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("旁白语言仅支持中文和英文，至少选择一种且不能重复。")
    return tuple(language for language in NARRATION_LANGUAGES if language in value)


class ReferenceGenerationKind(StrEnum):
    CHARACTER_LOOK_SHEET = "character_look_sheet"
    CHARACTER_VOICE = "character_voice"
    NARRATOR_VOICE = "narrator_voice"
    NARRATION_AUDIO = "narration_audio"
    DIALOGUE_AUDIO = "dialogue_audio"
    GENERATED_AUDIO = "generated_audio"
    AUDIO_EFFECT = "audio_effect"
    AUDIO_TRIM = "audio_trim"
    VIDEO_AUDIO_VOICE = "video_audio_voice"
    VIDEO_AUDIO_BACKGROUND = "video_audio_background"
    VIDEO_AUDIO_REMIX = "video_audio_remix"
    LOCATION_IMAGE = "location_image"
    PANORAMA_CAPTURE = "panorama_capture"
    KEYFRAME_IMAGE = "keyframe_image"
    SEGMENT_VIDEO = "segment_video"
    VIDEO_FRAME = "video_frame"
    VIDEO_UPSCALE = "video_upscale"
    FINAL_VIDEO = "final_video"
    SCENE_FINAL_VIDEO = "scene_final_video"
    SCENE_ANIMATIC = "scene_animatic"


# 按语言分别生成的 Generation：旁白音频、Scene 成片与最终成片。
LANGUAGE_GENERATION_KINDS = frozenset(
    {
        ReferenceGenerationKind.NARRATOR_VOICE,
        ReferenceGenerationKind.NARRATION_AUDIO,
        ReferenceGenerationKind.SCENE_FINAL_VIDEO,
        ReferenceGenerationKind.FINAL_VIDEO,
    }
)


class GenerationOperation(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"
    ATTACH = "attach"
    VOICE_DESIGN = "voice_design"
    SYNTHESIZE = "synthesize"
    RENDER = "render"
    UPSCALE = "upscale"
    ASSEMBLE = "assemble"
    PROCESS = "process"
    SEPARATE = "separate"
    REMIX = "remix"


class ReferenceGenerationPhase(StrEnum):
    SUBMITTING = "submitting"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
