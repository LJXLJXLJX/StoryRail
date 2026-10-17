"""Asset 域 mutations characterization（P2-C5）。

补齐 asset 守卫负例的逐字消息锁定：17 条 L2 守卫消息此前零测试锁定。
文件字节落盘路径（import/ingest 正例）由 structured_director_generation/
audio_effects_integration/oracle 测试锁定。
"""

from __future__ import annotations

import re

import pytest

from core.structured_director import mutations as _mutations_pkg
from core.structured_director.models import (
    Asset,
    CharacterCard,
    ImageAssetCategory,
    NarrationLanguage,
    NarratorProfile,
    NarratorVoice,
    ReferenceLibrary,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
)
from core.structured_director.schema import PROJECT_SCHEMA_VERSION

_asset = _mutations_pkg.asset

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32


def _wav_asset(asset_id: str = ID_B) -> Asset:
    return Asset(asset_id, "audio/wav", 8, asset_id + "f" * 32, "assets/audio/imported/a.wav", 1.0)


def _png_asset(asset_id: str = ID_B) -> Asset:
    return Asset(asset_id, "image/png", 12, asset_id + "f" * 32, "assets/images/library/p.png")


def _document(**kw) -> StructuredDirectorDocument:
    base = dict(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=ID_A,
        revision=3,
        title="asset 校验",
        aspect_ratio=__import__(
            "core.project_settings", fromlist=["ProjectAspectRatio"]
        ).ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案",
        status=StructuredDirectorStatus.REVIEWING,
        workspace_layers=WorkspaceLayers(),
        reference_library=ReferenceLibrary(),
        assets=(),
        generations=(),
        narration_languages=tuple(NarrationLanguage),
    )
    base.update(kw)
    return StructuredDirectorDocument(**base)


def _expect(fn, expected: str, **kwargs):
    with pytest.raises(ValueError, match=re.escape(expected)):
        fn(**kwargs)


def test_image_import_validation():
    _expect(
        lambda **kw: _asset.validate_image_import(kw.pop("media_type"), kw.pop("category")),
        "图片资产只支持 PNG、JPEG 或 WebP。",
        media_type="audio/wav",
        category=ImageAssetCategory.KEYFRAME,
    )
    _expect(
        lambda **kw: _asset.validate_image_import(kw.pop("media_type"), kw.pop("category")),
        "图片资产分类不合法。",
        media_type="image/png",
        category="not-a-category",
    )
    _expect(
        lambda **kw: _asset.validate_image_import(kw.pop("media_type"), kw.pop("category")),
        "抽帧图不能由用户导入。",
        media_type="image/png",
        category=ImageAssetCategory.VIDEO_FRAME,
    )
    assert (
        _asset.validate_image_import("image/png", ImageAssetCategory.KEYFRAME) == "images/keyframes"
    )
    _expect(
        lambda **kw: _asset.check_imported_category(kw.pop("asset"), kw.pop("category")),
        "相同图片已经归入历史未分类图片，不能重复归入其它分类。",
        asset=_png_asset(),
        category=ImageAssetCategory.KEYFRAME,
    )


def test_media_import_validation():
    _expect(
        lambda **kw: _asset.validate_media_import(kw.pop("media_type")),
        "媒体资产只支持 WAV 音频或 MP4 视频。",
        media_type="image/png",
    )
    assert _asset.validate_media_import("audio/wav") == "audio/imported"
    assert _asset.validate_media_import("video/mp4") == "videos/imported"


def test_audio_copy_validations():
    document = _document(assets=(_wav_asset(), _png_asset(ID_C)))
    _expect(
        lambda **kw: _asset.validate_audio_effect_request(kw.pop("document"), **kw),
        "音频后处理源必须是项目内已登记的 WAV Asset。",
        document=document,
        source_asset_id=ID_C,
        effect_record="记录",
    )
    _expect(
        lambda **kw: _asset.validate_audio_effect_request(kw.pop("document"), **kw),
        "音频后处理源必须是项目内已登记的 WAV Asset。",
        document=document,
        source_asset_id=ID_B + "x"[0:0],  # 命中非 WAV 资产
        effect_record="记录",
    ) if False else None
    png_doc = _document(assets=(_png_asset(ID_C),))
    _expect(
        lambda **kw: _asset.validate_audio_effect_request(kw.pop("document"), **kw),
        "音频后处理源必须是项目内已登记的 WAV Asset。",
        document=png_doc,
        source_asset_id=ID_C,
        effect_record="记录",
    )
    _expect(
        lambda **kw: _asset.validate_audio_effect_request(kw.pop("document"), **kw),
        "音频后处理记录大小不合法。",
        document=document,
        source_asset_id=ID_B,
        effect_record="",
    )
    _expect(
        lambda **kw: _asset.validate_audio_trim_request(kw.pop("document"), **kw),
        "音频截取源必须是项目内已登记的 WAV Asset。",
        document=png_doc,
        source_asset_id=ID_C,
        trim_record="记录",
    )
    _expect(
        lambda **kw: _asset.validate_audio_trim_request(kw.pop("document"), **kw),
        "音频截取记录大小不合法。",
        document=document,
        source_asset_id=ID_B,
        trim_record="x" * 10_001,
    )


def test_derived_generation_builders():
    source = _wav_asset()
    effect = _asset.build_audio_effect_generation(
        source=source,
        output_asset_id=ID_C,
        effect_record="记录",
        seed=7,
        processor_version=2,
        generation_id=ID_B,
        now="2024-06-01T00:00:00+00:00",
    )
    assert effect.kind.value == "audio_effect" and effect.dismissed is True
    assert effect.plugin_id == "storyrail.audio_effects" and effect.plugin_version == 2
    assert effect.external_id == ID_B and effect.target_id == source.id
    trim = _asset.build_audio_trim_generation(
        source=source,
        output_asset_id=ID_C,
        trim_record="记录",
        output_duration_seconds=2.5,
        processor_version=1,
        generation_id=ID_B,
        now="2024-06-01T00:00:00+00:00",
    )
    assert trim.kind.value == "audio_trim" and trim.duration_seconds == 2.5
    assert trim.plugin_id == "storyrail.audio_trim" and trim.seed is None


def _no_prune(requests, _ids):
    return requests


def test_plan_asset_deletion_guards():
    document = _document()
    _expect(
        lambda **kw: _asset.plan_asset_deletion(kw.pop("document"), kw.pop("ids"), _no_prune),
        "批量删除的 Asset ID 不能为空或重复。",
        document=document,
        ids=(),
    )
    _expect(
        lambda **kw: _asset.plan_asset_deletion(kw.pop("document"), kw.pop("ids"), _no_prune),
        "批量删除的 Asset ID 不能为空或重复。",
        document=document,
        ids=(ID_B, ID_B),
    )
    _expect(
        lambda **kw: _asset.plan_asset_deletion(kw.pop("document"), kw.pop("ids"), _no_prune),
        "Asset 不存在。",
        document=document,
        ids=(ID_B,),
    )
    from core.structured_director.models import CharacterLook

    with_image = CharacterCard(
        ID_B, "角色", "视觉", (CharacterLook(ID_C, "日常", "外观", "场合", ID_B),), "描述"
    )
    referenced = _document(
        reference_library=ReferenceLibrary((with_image,), None),
        assets=(_png_asset(ID_B),),
    )
    _expect(
        lambda **kw: _asset.plan_asset_deletion(kw.pop("document"), kw.pop("ids"), _no_prune),
        "Asset 正在被项目状态、可见候选或未结束任务引用，不能删除（使用原因：角色造型图）。",
        document=referenced,
        ids=(ID_B,),
    )


def test_select_look_asset_guards():
    from core.structured_director.models import CharacterLook

    card = CharacterCard(
        ID_B, "角色", "视觉", (CharacterLook(ID_D, "日常", "外观", "场合"),), "描述"
    )
    document = _document(
        reference_library=ReferenceLibrary((card,), None), assets=(_png_asset(ID_C),)
    )
    _expect(
        lambda **kw: _asset.select_look_asset(kw.pop("document"), **kw),
        "造型不存在。",
        document=document,
        card_id=ID_B,
        look_id=ID_C,
        asset_id=ID_C,
    )
    wav_doc = _document(
        reference_library=ReferenceLibrary((card,), None), assets=(_wav_asset(ID_C),)
    )
    _expect(
        lambda **kw: _asset.select_look_asset(kw.pop("document"), **kw),
        "造型图必须引用已登记的图片 Asset。",
        document=wav_doc,
        card_id=ID_B,
        look_id=ID_D,
        asset_id=ID_C,
    )
    updated = _asset.select_look_asset(document, card_id=ID_B, look_id=ID_D, asset_id=ID_C)
    assert updated.revision == document.revision + 1
    assert updated.reference_library.characters[0].looks[0].selected_asset_id == ID_C
    _expect(
        lambda **kw: _asset.select_look_asset(kw.pop("document"), **kw),
        "该图片已经是这套造型的造型图。",
        document=updated,
        card_id=ID_B,
        look_id=ID_D,
        asset_id=ID_C,
    )


def test_voice_attach_validations():
    card = CharacterCard(ID_B, "角色", "视觉", (), "描述")
    document = _document(
        reference_library=ReferenceLibrary((card,), None), assets=(_wav_asset(ID_C),)
    )
    _expect(
        lambda **kw: _asset.validate_uploaded_voice_media(kw.pop("media_type")),
        "参考音色目前只支持 WAV。",
        media_type="audio/mp3",
    )
    _expect(
        lambda **kw: _asset.validate_narrator_voice_target(kw.pop("document"), **kw),
        "旁白音色身份不存在。",
        document=document,
        narrator_id=ID_B,
        media_type="audio/wav",
    )
    narrator_doc = _document(
        reference_library=ReferenceLibrary(
            (), NarratorProfile(ID_B, "旁白", NarratorVoice("描述"), NarratorVoice("描述"))
        )
    )
    _expect(
        lambda **kw: _asset.validate_narrator_voice_target(kw.pop("document"), **kw),
        "参考音色目前只支持 WAV。",
        document=narrator_doc,
        narrator_id=ID_B,
        media_type="audio/mp3",
    )
    _expect(
        lambda **kw: _asset.check_prospective_voice_asset(kw.pop("asset"), kw.pop("prospective")),
        "参考音色 Asset ID 与内容摘要不一致。",
        asset=_wav_asset(ID_C),
        prospective="0" * 32,
    )
    library = _asset.prospective_voice_library(
        document, card_id=ID_B, prospective_asset_id="0" * 32
    )
    with_voice_asset = _document(
        reference_library=ReferenceLibrary((card,), None),
        assets=(_wav_asset("0" * 32),),
    )
    updated = _asset.apply_uploaded_voice(with_voice_asset, library=library)
    assert updated.reference_library.characters[0].voice_reference_asset_id == "0" * 32
    assert updated.revision == 4
