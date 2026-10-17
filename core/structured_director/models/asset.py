"""领域模型：asset 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING

from ._shared import (
    _ASSET_PATH,
    _SHA256,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    _require_id,
)

if TYPE_CHECKING:
    from .document import StructuredDirectorDocument
    from .generation import ReferenceGeneration


class ImageAssetCategory(StrEnum):
    CHARACTER_REFERENCE = "character_reference"
    LOCATION_MASTER = "location_master"
    # 全景裁切产物；由 Core 生成，不接受用户导入。
    LOCATION_CROP = "location_crop"
    LOCATION_VIEW = "location_view"
    KEYFRAME = "keyframe"
    # 视频抽帧产物；由 Core 生成，不接受用户导入。
    VIDEO_FRAME = "video_frame"


class AssetUsageReason(StrEnum):
    """Core 判定的 Asset 使用关系；Web 只展示该结果，不自行推断。

    只有正式项目字段、正式绑定关系、可见候选、未结束任务输入和 Director 等待会
    产生原因。Generation 的输出关系本身不是项目使用关系：抽帧等产物型任务产出的
    Asset 在没有正式绑定时保持未使用。
    """

    CHARACTER_REFERENCE_IMAGE = "character_reference_image"
    CHARACTER_VOICE_REFERENCE = "character_voice_reference"
    NARRATOR_VOICE_REFERENCE = "narrator_voice_reference"
    NARRATION_AUDIO = "narration_audio"
    LOCATION_MASTER_IMAGE = "location_master_image"
    LOCATION_VIEW_IMAGE = "location_view_image"
    KEYFRAME_REFERENCE_IMAGE = "keyframe_reference_image"
    KEYFRAME_SELECTED_ASSET = "keyframe_selected_asset"
    SEGMENT_VIDEO_SELECTED = "segment_video_selected"
    SEGMENT_VIDEO_UPSCALED = "segment_video_upscaled"
    SEGMENT_VIDEO_INPUT_IMAGE = "segment_video_input_image"
    SEGMENT_VIDEO_INPUT_AUDIO = "segment_video_input_audio"
    SEGMENT_VIDEO_INPUT_VIDEO = "segment_video_input_video"
    FINAL_ASSEMBLY = "final_assembly"
    VISIBLE_CANDIDATE = "visible_candidate"
    UNFINISHED_GENERATION_INPUT = "unfinished_generation_input"
    DIRECTOR_WAIT = "director_wait"

    @property
    def label(self) -> str:
        return {
            AssetUsageReason.CHARACTER_REFERENCE_IMAGE: "角色造型图",
            AssetUsageReason.CHARACTER_VOICE_REFERENCE: "角色参考音色",
            AssetUsageReason.NARRATOR_VOICE_REFERENCE: "旁白参考音色",
            AssetUsageReason.NARRATION_AUDIO: "旁白已选音频",
            AssetUsageReason.LOCATION_MASTER_IMAGE: "地点主图",
            AssetUsageReason.LOCATION_VIEW_IMAGE: "地点视图图片",
            AssetUsageReason.KEYFRAME_REFERENCE_IMAGE: "Keyframe 辅助参考图",
            AssetUsageReason.KEYFRAME_SELECTED_ASSET: "Keyframe 已选图片",
            AssetUsageReason.SEGMENT_VIDEO_SELECTED: "Segment 已选视频",
            AssetUsageReason.SEGMENT_VIDEO_UPSCALED: "Segment 超分视频",
            AssetUsageReason.SEGMENT_VIDEO_INPUT_IMAGE: "Ref2VA 视频附加图片",
            AssetUsageReason.SEGMENT_VIDEO_INPUT_AUDIO: "Ref2VA 视频参考音频",
            AssetUsageReason.SEGMENT_VIDEO_INPUT_VIDEO: "Ref2VA 视频参考视频",
            AssetUsageReason.FINAL_ASSEMBLY: "最终装配成片",
            AssetUsageReason.VISIBLE_CANDIDATE: "可见生成候选",
            AssetUsageReason.UNFINISHED_GENERATION_INPUT: "未结束或结果未知的生成任务输入",
            AssetUsageReason.DIRECTOR_WAIT: "Director 任务等待",
        }[self]


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    media_type: str
    byte_count: int
    sha256: str
    relative_path: str
    duration_seconds: float | None = None

    @property
    def display_name(self) -> str:
        filename = self.relative_path.rsplit("/", 1)[-1]
        return re.sub(r"-[0-9a-f]{10}(?=\.[^.]+$)", "", filename)

    @property
    def image_category(self) -> ImageAssetCategory | None:
        if not self.media_type.startswith("image/"):
            return None
        directory = self.relative_path.rsplit("/", 1)[0].removeprefix("assets/images/")
        return {
            "characters": ImageAssetCategory.CHARACTER_REFERENCE,
            "locations/master": ImageAssetCategory.LOCATION_MASTER,
            "locations/crops": ImageAssetCategory.LOCATION_CROP,
            "locations/views": ImageAssetCategory.LOCATION_VIEW,
            "keyframes": ImageAssetCategory.KEYFRAME,
            "video-frames": ImageAssetCategory.VIDEO_FRAME,
        }.get(directory)

    def __post_init__(self) -> None:
        _require_id(self.id, "asset.id")
        if self.media_type not in {
            "image/png",
            "image/jpeg",
            "image/webp",
            "audio/wav",
            "video/mp4",
        }:
            raise ValueError("asset.media_type 不受支持。")
        maximum = 2 * 1024 * 1024 * 1024 if self.media_type == "video/mp4" else 64 * 1024 * 1024
        if isinstance(self.byte_count, bool) or not 1 <= self.byte_count <= maximum:
            raise ValueError("asset.byte_count 不合法。")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("asset.sha256 不合法。")
        if not _ASSET_PATH.fullmatch(self.relative_path):
            raise ValueError("asset.relative_path 不合法。")
        extension = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "audio/wav": "wav",
            "video/mp4": "mp4",
        }[self.media_type]
        media_directory = (
            "images"
            if self.media_type.startswith("image/")
            else "audio"
            if self.media_type.startswith("audio/")
            else "videos"
        )
        if (
            self.id != self.sha256[:32]
            or not self.relative_path.startswith(f"assets/{media_directory}/")
            or not self.relative_path.endswith(f".{extension}")
        ):
            raise ValueError("Asset 路径、扩展名或 ID 与内容不一致。")
        if self.media_type in {"audio/wav", "video/mp4"}:
            if (
                self.duration_seconds is None
                or not isfinite(self.duration_seconds)
                or self.duration_seconds <= 0
            ):
                raise ValueError("音视频 Asset 必须保存有效时长。")
        elif self.duration_seconds is not None:
            raise ValueError("图片 Asset 不能保存时长。")


def asset_project_usage_reasons(
    document: StructuredDirectorDocument,
    asset_id: str,
) -> tuple[AssetUsageReason, ...]:
    """只返回正式项目字段与正式绑定关系产生的使用原因。

    Generation 的输入/输出关系不属于项目使用关系：它只描述血缘，不证明产物已经
    绑定到项目。这里扫描的每一项都是用户可见、可编辑的项目事实。
    """

    reasons: list[AssetUsageReason] = []
    if any(asset_id in card.look_asset_ids for card in document.reference_library.characters):
        reasons.append(AssetUsageReason.CHARACTER_REFERENCE_IMAGE)
    if any(
        card.voice_reference_asset_id == asset_id for card in document.reference_library.characters
    ):
        reasons.append(AssetUsageReason.CHARACTER_VOICE_REFERENCE)
    narrator = document.reference_library.narrator
    if narrator is not None and asset_id in narrator.voice_reference_asset_ids:
        reasons.append(AssetUsageReason.NARRATOR_VOICE_REFERENCE)
    if document.director_script is not None and any(
        asset_id in cue.selected_audio_asset_ids
        for scene in document.director_script.scenes
        for cue in scene.narration_cues
    ):
        reasons.append(AssetUsageReason.NARRATION_AUDIO)
    locations = document.location_library.locations
    if any(
        asset_id
        in (
            *item.master.reference_asset_ids,
            item.master.selected_asset_id,
            item.calibrated_master_asset_id,
        )
        for item in locations
    ):
        reasons.append(AssetUsageReason.LOCATION_MASTER_IMAGE)
    if any(
        asset_id in (view.crop_asset_id, view.selected_asset_id)
        for item in locations
        for view in item.views
    ):
        reasons.append(AssetUsageReason.LOCATION_VIEW_IMAGE)
    if document.keyframe_plan is not None and any(
        asset_id in item.reference_asset_ids for item in document.keyframe_plan.segments
    ):
        reasons.append(AssetUsageReason.KEYFRAME_REFERENCE_IMAGE)
    if document.keyframe_plan is not None and any(
        item.selected_asset_id == asset_id for item in document.keyframe_plan.keyframes
    ):
        reasons.append(AssetUsageReason.KEYFRAME_SELECTED_ASSET)
    if document.video_plan is not None:
        segments = document.video_plan.segments
        if any(item.selected_asset_id == asset_id for item in segments):
            reasons.append(AssetUsageReason.SEGMENT_VIDEO_SELECTED)
        if any(item.upscaled_asset_id == asset_id for item in segments):
            reasons.append(AssetUsageReason.SEGMENT_VIDEO_UPSCALED)
        if any(
            asset_id in inputs.asset_ids
            for item in segments
            for _recipe, inputs in item.recipes.entries
        ):
            asset = next((item for item in document.assets if item.id == asset_id), None)
            if asset is not None:
                reasons.append(
                    {
                        "image": AssetUsageReason.SEGMENT_VIDEO_INPUT_IMAGE,
                        "audio": AssetUsageReason.SEGMENT_VIDEO_INPUT_AUDIO,
                        "video": AssetUsageReason.SEGMENT_VIDEO_INPUT_VIDEO,
                    }[asset.media_type.split("/")[0]]
                )
    if document.final_assembly is not None and (
        asset_id
        in (
            document.final_assembly.selected_zh_asset_id,
            document.final_assembly.selected_en_asset_id,
        )
        or any(
            asset_id in (item.zh_asset_id, item.en_asset_id)
            for item in document.final_assembly.clips
        )
    ):
        reasons.append(AssetUsageReason.FINAL_ASSEMBLY)
    return tuple(reasons)


def asset_has_project_reference(document: StructuredDirectorDocument, asset_id: str) -> bool:
    """Asset 是否被正式项目字段或正式绑定关系引用。"""

    return bool(asset_project_usage_reasons(document, asset_id))


_ACTIVE_GENERATION_PHASES = frozenset(
    {
        ReferenceGenerationPhase.SUBMITTING,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        ReferenceGenerationPhase.QUEUED,
        ReferenceGenerationPhase.RUNNING,
    }
)


def _generation_output_is_selectable_candidate(
    document: StructuredDirectorDocument, generation: ReferenceGeneration
) -> bool:
    """该 Generation 的输出是否仍是用户可见、可采用的候选。

    产物型任务（通用音频、视频抽帧、全景裁切）产出的只是普通媒体 Asset，不是候选，因此它的
    ``output_asset_id`` 不构成使用关系，也不会单独保护该 Asset 的删除。
    """

    # 角色或造型已删除时，设定图只剩历史血缘，不再是当前造型的候选。
    if generation.kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET:
        return document.reference_library.look_owner(generation.target_id) is not None
    return not (
        generation.kind
        in {
            ReferenceGenerationKind.GENERATED_AUDIO,
            ReferenceGenerationKind.VIDEO_FRAME,
            ReferenceGenerationKind.LOCATION_VIEW_CROP,
        }
        and generation.phase is ReferenceGenerationPhase.SUCCEEDED
    )


@dataclass(frozen=True, slots=True)
class AssetDeletionClosure:
    """一次显式删除实际覆盖的 Asset 与 Generation，以及删除后的清理语义。"""

    asset_ids: frozenset[str]
    generation_ids: frozenset[str]
    retains_derived_assets: bool


def asset_usage_reasons(
    document: StructuredDirectorDocument,
    asset_id: str,
) -> tuple[AssetUsageReason, ...]:
    """Core 唯一的 Asset 使用判定；返回阻止显式删除的全部事实原因。

    正式项目引用、仍是可见候选的产物、未结束或结果未知任务的输入，以及 Director
    正在等待的任务共同构成使用关系。隐藏血缘与纯输出关系不在此列。
    """

    return _asset_deletion_walk(document, asset_id)[2]


def _asset_deletion_walk(
    document: StructuredDirectorDocument,
    asset_id: str,
) -> tuple[frozenset[str], frozenset[str], tuple[AssetUsageReason, ...]]:
    asset_ids = {asset_id}
    generation_ids: set[str] = set()
    reasons: list[AssetUsageReason] = []
    waiting_generation_ids = {
        generation_id
        for run in document.director_runs
        for generation_id in run.cursor.waiting_generation_ids
    }

    def remember(reason: AssetUsageReason) -> None:
        if reason not in reasons:
            reasons.append(reason)

    while True:
        for item in asset_ids:
            for reason in asset_project_usage_reasons(document, item):
                remember(reason)
        changed = False
        for generation in document.generations:
            if generation.id in generation_ids:
                continue
            output_related = generation.output_asset_id in asset_ids
            input_related = bool(asset_ids.intersection(generation.input_asset_ids))
            if not output_related and not input_related:
                continue
            if generation.id in waiting_generation_ids:
                remember(AssetUsageReason.DIRECTOR_WAIT)
            if (
                output_related
                and not generation.dismissed
                and _generation_output_is_selectable_candidate(document, generation)
            ):
                remember(AssetUsageReason.VISIBLE_CANDIDATE)
            if input_related and generation.phase in _ACTIVE_GENERATION_PHASES:
                remember(AssetUsageReason.UNFINISHED_GENERATION_INPUT)
            generation_ids.add(generation.id)
            if generation.dismissed and generation.output_asset_id is not None:
                asset_ids.add(generation.output_asset_id)
            changed = True
        if not changed:
            break
    return frozenset(asset_ids), frozenset(generation_ids), tuple(reasons)


def asset_deletion_closure(
    document: StructuredDirectorDocument,
    asset_id: str,
) -> AssetDeletionClosure | None:
    """Return the assets, terminal generations and cleanup semantics of one deletion.

    A discarded output may still be mentioned by one or more hidden Generation
    records.  Deleting only the Asset would leave an invalid document, so cleanup
    follows hidden downstream input edges and removes that closed lineage atomically.
    A visible, terminal Generation that consumed the Asset is detached instead: its
    already-materialized output Asset is retained, while the Generation record that
    can no longer describe a reproducible operation is removed.  Any live business
    reference, active/uncertain Generation, visible candidate producer, or Director
    wait keeps the deletion protected and returns ``None``; the reasons are available
    from :func:`asset_usage_reasons`. A successful generic audio or video-frame
    producer creates an ordinary Asset rather than a selectable candidate, so it can
    be purged together with that Asset even when its history has not been dismissed.
    """

    asset_ids, generation_ids, reasons = _asset_deletion_walk(document, asset_id)
    if reasons:
        return None
    retains_derived_assets = any(
        generation.output_asset_id is not None
        and generation.output_asset_id not in asset_ids
        and bool(asset_ids.intersection(generation.input_asset_ids))
        for generation in document.generations
        if generation.id in generation_ids
    )
    return AssetDeletionClosure(asset_ids, generation_ids, retains_derived_assets)


def discarded_asset_deletion_closure(
    document: StructuredDirectorDocument,
    asset_id: str,
) -> tuple[frozenset[str], frozenset[str]] | None:
    """``asset_deletion_closure`` 的旧 tuple 入口，语义与清理范围完全相同。"""

    closure = asset_deletion_closure(document, asset_id)
    if closure is None:
        return None
    return closure.asset_ids, closure.generation_ids
