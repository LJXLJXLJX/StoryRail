"""Asset 域 mutations：纯函数化的资产登记/派生/删除/挂载逻辑（P2-C5）。

从 store asset 方法原样抽取的**纯文档变换**：导入校验、音频效果/截取
派生 Generation 构造、删除闭包计划、参考图/音色挂载。文件字节落盘
（_ingest_asset、删除文件 stage/unlink）留在 store；删除计划经 prune
依赖注入保持 L2 向下依赖。
"""

from __future__ import annotations

from dataclasses import replace

from ..asset_metadata import _image_category_label
from ..models import (
    Asset,
    GenerationOperation,
    ImageAssetCategory,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    StructuredDirectorDocument,
    asset_deletion_closure,
    asset_usage_reasons,
)
from ..video_mutations import _apply_reference_library_change
from .generation import _map_card
from .reference import set_look_asset

# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def validate_image_import(media_type: str, category: ImageAssetCategory) -> str:
    """校验图片导入并返回受控目录；返回目录名供 store 落盘。"""
    if not media_type.startswith("image/"):
        raise ValueError("图片资产只支持 PNG、JPEG 或 WebP。")
    if not isinstance(category, ImageAssetCategory):
        raise ValueError("图片资产分类不合法。")
    directory = {
        ImageAssetCategory.CHARACTER_REFERENCE: "images/characters",
        ImageAssetCategory.LOCATION_MASTER: "images/locations/master",
        ImageAssetCategory.LOCATION_VIEW: "images/locations/views",
        ImageAssetCategory.KEYFRAME: "images/keyframes",
    }.get(category)
    if directory is None:
        # 抽帧图由视频尾帧抽取产生，不是用户导入分类。
        raise ValueError(f"{_image_category_label(category)}不能由用户导入。")
    return directory


def check_imported_category(asset: Asset, category: ImageAssetCategory) -> None:
    """重复字节按已登记分类明确拒绝跨分类导入。"""
    if asset.image_category is not category:
        raise ValueError(
            f"相同图片已经归入{_image_category_label(asset.image_category)}，不能重复归入其它分类。"
        )


def bump_ingested(
    document: StructuredDirectorDocument, updated: StructuredDirectorDocument
) -> StructuredDirectorDocument:
    """导入未变更（重复字节）时返回原文档，否则 revision +1。"""
    if updated is document:
        return document
    return replace(updated, revision=document.revision + 1)


def validate_media_import(media_type: str) -> str:
    """校验媒体导入类型并返回受控目录。"""
    if media_type not in {"audio/wav", "video/mp4"}:
        raise ValueError("媒体资产只支持 WAV 音频或 MP4 视频。")
    return "audio/imported" if media_type == "audio/wav" else "videos/imported"


# ---------------------------------------------------------------------------
# 音频效果/截取派生
# ---------------------------------------------------------------------------


def validate_audio_effect_request(
    document: StructuredDirectorDocument, *, source_asset_id: str, effect_record: str
) -> Asset:
    source = next((item for item in document.assets if item.id == source_asset_id), None)
    if source is None or source.media_type != "audio/wav":
        raise ValueError("音频后处理源必须是项目内已登记的 WAV Asset。")
    if not effect_record or len(effect_record) > 20_000:
        raise ValueError("音频后处理记录大小不合法。")
    return source


def validate_audio_trim_request(
    document: StructuredDirectorDocument, *, source_asset_id: str, trim_record: str
) -> Asset:
    source = next((item for item in document.assets if item.id == source_asset_id), None)
    if source is None or source.media_type != "audio/wav":
        raise ValueError("音频截取源必须是项目内已登记的 WAV Asset。")
    if not trim_record or len(trim_record) > 10_000:
        raise ValueError("音频截取记录大小不合法。")
    return source


def build_audio_effect_generation(
    *,
    source: Asset,
    output_asset_id: str,
    effect_record: str,
    seed: int,
    processor_version: int,
    generation_id: str,
    now: str,
) -> ReferenceGeneration:
    """音频效果副本的隐藏血缘记录（本地处理器原子完成）。"""
    return ReferenceGeneration(
        id=generation_id,
        kind=ReferenceGenerationKind.AUDIO_EFFECT,
        operation=GenerationOperation.PROCESS,
        target_id=source.id,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        message="音频后处理完成。",
        prompt_text=effect_record,
        input_asset_ids=(source.id,),
        sample_text=None,
        seed=seed,
        plugin_id="storyrail.audio_effects",
        plugin_version=processor_version,
        external_id=generation_id,
        output_asset_id=output_asset_id,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        dismissed=True,
        created_at=now,
        updated_at=now,
    )


def build_audio_trim_generation(
    *,
    source: Asset,
    output_asset_id: str,
    trim_record: str,
    output_duration_seconds: float,
    processor_version: int,
    generation_id: str,
    now: str,
) -> ReferenceGeneration:
    """音频截取副本的隐藏血缘记录。"""
    return ReferenceGeneration(
        id=generation_id,
        kind=ReferenceGenerationKind.AUDIO_TRIM,
        operation=GenerationOperation.PROCESS,
        target_id=source.id,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        message="音频截取完成。",
        prompt_text=trim_record,
        input_asset_ids=(source.id,),
        sample_text=None,
        seed=None,
        plugin_id="storyrail.audio_trim",
        plugin_version=processor_version,
        external_id=generation_id,
        output_asset_id=output_asset_id,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        dismissed=True,
        duration_seconds=output_duration_seconds,
        created_at=now,
        updated_at=now,
    )


def append_generation(
    document: StructuredDirectorDocument, generation: ReferenceGeneration
) -> StructuredDirectorDocument:
    return replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, generation),
    )


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def plan_asset_deletion(
    document: StructuredDirectorDocument,
    asset_ids: tuple[str, ...],
    prune_generation_references,
) -> tuple[StructuredDirectorDocument, tuple[Asset, ...]]:
    """计算删除闭包与新 document；文件 stage/unlink 与写入由 store 负责。

    ``prune_generation_references`` 由 store 注入（application_requests 的
    L5 依赖，L2 不向上 import）。
    """
    if not asset_ids or len(asset_ids) != len(set(asset_ids)):
        raise ValueError("批量删除的 Asset ID 不能为空或重复。")
    known_asset_ids = {item.id for item in document.assets}
    if any(asset_id not in known_asset_ids for asset_id in asset_ids):
        raise ValueError("Asset 不存在。")
    deleted_asset_ids: set[str] = set()
    deleted_generation_ids: set[str] = set()
    for asset_id in asset_ids:
        deletion = asset_deletion_closure(document, asset_id)
        if deletion is None:
            detail = "、".join(reason.label for reason in asset_usage_reasons(document, asset_id))
            raise ValueError(
                f"Asset 正在被项目状态、可见候选或未结束任务引用，不能删除（使用原因：{detail}）。"
            )
        deleted_asset_ids.update(deletion.asset_ids)
        deleted_generation_ids.update(deletion.generation_ids)
    deleted_assets = tuple(item for item in document.assets if item.id in deleted_asset_ids)
    updated = replace(
        document,
        revision=document.revision + 1,
        assets=tuple(item for item in document.assets if item.id not in deleted_asset_ids),
        generations=tuple(
            replace(item, retry_of=None) if item.retry_of in deleted_generation_ids else item
            for item in document.generations
            if item.id not in deleted_generation_ids
        ),
        application_requests=prune_generation_references(
            document.application_requests, deleted_generation_ids
        ),
    )
    return updated, deleted_assets


# ---------------------------------------------------------------------------
# attach（参考图 / 上传音色）
# ---------------------------------------------------------------------------


def _require_card_target(document: StructuredDirectorDocument, kind: str, card_id: str) -> None:
    cards = document.reference_library.characters if kind == "characters" else None
    if cards is None:
        raise ValueError("未知的卡片类型。")
    if not any(card.id == card_id for card in cards):
        raise ValueError("卡片不存在。")


def select_look_asset(
    document: StructuredDirectorDocument, *, card_id: str, look_id: str, asset_id: str
) -> StructuredDirectorDocument:
    """人类把资产库已有图片设为造型图。"""
    updated = set_look_asset(document, card_id=card_id, look_id=look_id, asset_id=asset_id)
    return replace(updated, revision=document.revision + 1)


def prospective_voice_library(
    document: StructuredDirectorDocument, *, card_id: str, prospective_asset_id: str
) -> ReferenceLibrary:
    """预计算上传音色后的角色卡库（供 store 在 ingest 后一次性应用）。"""
    _require_card_target(document, "characters", card_id)
    return _map_card(
        document.reference_library,
        "characters",
        card_id,
        lambda item: replace(
            item,
            voice_reference_asset_id=prospective_asset_id,
            voice_reference_transcript=None,
        ),
    )


def check_prospective_voice_asset(asset: Asset, prospective_asset_id: str) -> None:
    if asset.id != prospective_asset_id:
        raise ValueError("参考音色 Asset ID 与内容摘要不一致。")


def uploaded_voice_label(document: StructuredDirectorDocument, card_id: str) -> str:
    card = next(item for item in document.reference_library.characters if item.id == card_id)
    return f"角色-{card.name}-参考音色"


def narrator_voice_label(document: StructuredDirectorDocument, language: NarrationLanguage) -> str:
    narrator = document.reference_library.narrator
    label = "中文" if language is NarrationLanguage.ZH else "英文"
    return f"旁白-{narrator.name}-{label}参考音色"


def validate_narrator_voice_target(
    document: StructuredDirectorDocument, *, narrator_id: str, media_type: str
) -> None:
    narrator = document.reference_library.narrator
    if narrator is None or narrator.id != narrator_id:
        raise ValueError("旁白音色身份不存在。")
    if media_type != "audio/wav":
        raise ValueError("参考音色目前只支持 WAV。")


def apply_uploaded_voice(
    document: StructuredDirectorDocument, *, library: ReferenceLibrary
) -> StructuredDirectorDocument:
    """ingest 成功后应用预计算的库（revision +1）。"""
    return _replace_library(document, library)


def apply_uploaded_narrator_voice(
    document: StructuredDirectorDocument,
    *,
    narrator_id: str,
    language: NarrationLanguage,
    asset_id: str,
) -> StructuredDirectorDocument:
    """上传的 WAV 只替换该语言的参考音色，并清空需要重新填写的文字稿。"""
    narrator = document.reference_library.narrator
    library = replace(
        document.reference_library,
        narrator=narrator.with_voice(
            language,
            replace(
                narrator.voice(language),
                voice_reference_asset_id=asset_id,
                voice_reference_transcript=None,
            ),
        ),
    )
    return _replace_library(document, library)


def validate_uploaded_voice_media(media_type: str) -> None:
    if media_type != "audio/wav":
        raise ValueError("参考音色目前只支持 WAV。")


def _replace_library(
    document: StructuredDirectorDocument, library: ReferenceLibrary
) -> StructuredDirectorDocument:
    return replace(
        _apply_reference_library_change(document, library),
        revision=document.revision + 1,
    )
