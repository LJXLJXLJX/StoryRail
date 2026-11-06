"""Generation 生命周期 mutations characterization（P2-C4）。

补齐 generation 守卫负例的逐字消息锁定：既有测试锁定状态机正例与
submit/attach/complete/dismiss 主路径，但 L2 抽取后 29 条守卫消息此前零锁定。
覆盖纯函数 validate_generation_target / create_generations / attach /
dismiss / validate_completion_payload / update / recover。
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_models_validation import make_generation

from core.director_commands import GenerationTarget
from core.structured_director import mutations as _mutations_pkg
from core.structured_director.models import (
    Asset,
    CharacterCard,
    CharacterLook,
    DirectorScript,
    GenerationOperation,
    Keyframe,
    KeyframePlan,
    Location,
    LocationImage,
    LocationImageKind,
    LocationLibrary,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    NarratorProfile,
    NarratorVoice,
    PanoramaCaptureRequest,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    Scene,
    SegmentKeyframes,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
)
from core.structured_director.schema import PROJECT_SCHEMA_VERSION

_generation = _mutations_pkg.generation

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32
NOW = "2024-06-01T00:00:00+00:00"

CUE = NarrationCue(ID_C, NarrationTrack("旁白", 1), NarrationTrack("Narration.", 1))
SCENE = Scene(ID_B, "场景", "摘要", "环境", (), (), (CUE,), "narration", None)
SCRIPT = DirectorScript(1, 1, None, None, (SCENE,))
KF = Keyframe(ID_C, ID_B, None, "帧", ())
KF_END = Keyframe("e" * 32, ID_B, ID_C, "尾帧", ())


def _mp4_asset(asset_id: str = ID_B) -> Asset:
    return Asset(
        asset_id, "video/mp4", 24, asset_id + "f" * 32, "assets/videos/segments/s.mp4", 4.0
    )


def _png_asset(asset_id: str = ID_B) -> Asset:
    return Asset(asset_id, "image/png", 12, asset_id + "f" * 32, "assets/images/library/p.png")


def _wav_asset(asset_id: str = ID_B) -> Asset:
    return Asset(
        asset_id, "audio/wav", 8, asset_id + "f" * 32, "assets/audio/voice-references/v.wav", 1.0
    )


def _document(**kw) -> StructuredDirectorDocument:
    base = dict(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=ID_A,
        revision=3,
        title="generation 校验",
        aspect_ratio=__import__(
            "core.project_settings", fromlist=["ProjectAspectRatio"]
        ).ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案",
        status=StructuredDirectorStatus.REVIEWING,
        workspace_layers=WorkspaceLayers(),
        reference_library=ReferenceLibrary(),
        generations=(),
        narration_languages=tuple(NarrationLanguage),
    )
    base.update(kw)
    return StructuredDirectorDocument(**base)


def _expect(fn, expected: str, **kwargs):
    with pytest.raises(ValueError, match=re.escape(expected)):
        fn(**kwargs)


def test_validate_generation_target_guards():
    voice_only = ReferenceLibrary((CharacterCard(ID_B, "声音", None, (), "描述"),), None)
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标造型不存在。",
        document=_document(reference_library=voice_only),
        gen=make_generation(
            ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
            GenerationOperation.GENERATE,
            target_id=ID_B,
        ),
    )
    location_doc = _document(
        location_library=LocationLibrary(
            (
                Location(
                    ID_B,
                    "客厅",
                    images=(
                        LocationImage(
                            ID_D,
                            "正打",
                            LocationImageKind.IMAGE,
                            "人眼高中景。",
                            "生成正打。",
                        ),
                    ),
                ),
            )
        )
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标地点图片不存在。",
        document=location_doc,
        gen=make_generation(
            ReferenceGenerationKind.LOCATION_IMAGE,
            GenerationOperation.GENERATE,
            target_id=ID_C,
        ),
    )
    crop = PanoramaCaptureRequest(ID_C, 0.0, 0.0, 60.0, "16:9")
    for gen in (
        replace(
            make_generation(ReferenceGenerationKind.LOCATION_IMAGE, GenerationOperation.GENERATE),
            kind=ReferenceGenerationKind.PANORAMA_CAPTURE,
            operation=GenerationOperation.PROCESS,
            target_id=ID_B,
            input_asset_ids=(ID_C,),
            seed=None,
            panorama_capture_request=crop,
        ),
        make_generation(
            ReferenceGenerationKind.LOCATION_IMAGE,
            GenerationOperation.GENERATE,
            target_id=ID_B,
        ),
    ):
        _expect(
            lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
            "Generation 目标地点图片不存在。",
            document=location_doc,
            gen=gen,
        )
    segment = __import__("core.structured_director.models", fromlist=["ShotSegment"]).ShotSegment(
        ID_B, ("5" * 32,), 4.0, "动作", (), None
    )
    shot = __import__("core.structured_director.models", fromlist=["Shot"]).Shot(
        "5" * 32, (), "构图", "固定", "动作", "环境声", None
    )
    plan_scene = Scene("6" * 32, "场景", "摘要", "环境", (shot,), (segment,), (), "drama", None)
    baseline_script = DirectorScript(1, 1, 1, (plan_scene,), (plan_scene,))
    keyframe_doc = _document(
        status=StructuredDirectorStatus.REVIEWING_KEYFRAMES,
        workspace_layers=WorkspaceLayers(narration_unlocked=True, keyframes_unlocked=True),
        director_script=baseline_script,
        keyframe_plan=KeyframePlan(
            1,
            (Keyframe(ID_C, ID_B, None, "帧", ()), Keyframe("e" * 32, ID_B, ID_C, "尾", ())),
            (SegmentKeyframes(ID_B, ID_C, "e" * 32),),
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标 Keyframe 不存在。",
        document=keyframe_doc,
        gen=make_generation(
            ReferenceGenerationKind.KEYFRAME_IMAGE, GenerationOperation.GENERATE, target_id="0" * 32
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标旁白 Cue 不存在。",
        document=_document(
            status=StructuredDirectorStatus.REVIEWING_NARRATION,
            workspace_layers=WorkspaceLayers(narration_unlocked=True),
            director_script=SCRIPT,
            assets=(
                Asset(
                    "1" * 32,
                    "audio/wav",
                    8,
                    "1" * 32 + "f" * 32,
                    "assets/audio/voice-references/v.wav",
                    1.0,
                ),
            ),
        ),
        gen=make_generation(
            ReferenceGenerationKind.NARRATION_AUDIO,
            GenerationOperation.SYNTHESIZE,
            target_id="0" * 32,
            input_asset_ids=("1" * 32,),
            sample_text="完整文字稿",
            seed=1,
            language=NarrationLanguage.ZH,
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "视频音轨 Generation 目标必须是项目内 MP4 Asset。",
        document=_document(),
        gen=make_generation(
            ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
            GenerationOperation.SEPARATE,
            target_id=ID_B,
            input_asset_ids=(ID_B,),
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "抽帧 Generation 目标必须是 Keyframe 或项目内 MP4 Asset。",
        document=_document(),
        gen=make_generation(
            ReferenceGenerationKind.VIDEO_FRAME,
            GenerationOperation.PROCESS,
            target_id=ID_B,
            input_asset_ids=(ID_B,),
            video_frame_request=__import__(
                "core.structured_director.video_contracts", fromlist=["VideoFrameRequest"]
            ).VideoFrameRequest(ID_B, "f" * 64, 0, 1),
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标 Segment 不存在。",
        document=_document(),
        gen=make_generation(
            ReferenceGenerationKind.SEGMENT_VIDEO,
            GenerationOperation.RENDER,
            target_id=ID_B,
            input_asset_ids=(ID_C,),
            seed=1,
            duration_seconds=4.0,
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标成片装配不存在。",
        document=_document(),
        gen=make_generation(
            ReferenceGenerationKind.FINAL_VIDEO,
            GenerationOperation.ASSEMBLE,
            target_id=ID_A,
            input_asset_ids=(ID_C,),
            duration_seconds=10.0,
            language=NarrationLanguage.ZH,
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标 Scene 不存在。",
        document=_document(
            status=StructuredDirectorStatus.REVIEWING_KEYFRAMES,
            workspace_layers=WorkspaceLayers(narration_unlocked=True, keyframes_unlocked=True),
            director_script=SCRIPT,
        ),
        gen=make_generation(
            ReferenceGenerationKind.SCENE_FINAL_VIDEO,
            GenerationOperation.ASSEMBLE,
            target_id="0" * 32,
            input_asset_ids=(ID_C,),
            duration_seconds=10.0,
            language=NarrationLanguage.ZH,
        ),
    )
    narrator_doc = _document(
        reference_library=ReferenceLibrary(
            (), NarratorProfile(ID_B, "旁白", NarratorVoice("描述"), NarratorVoice("描述"))
        )
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标旁白身份不存在。",
        document=narrator_doc,
        gen=make_generation(
            ReferenceGenerationKind.NARRATOR_VOICE,
            GenerationOperation.VOICE_DESIGN,
            target_id=ID_C,
            sample_text="文",
            seed=1,
            language=NarrationLanguage.ZH,
        ),
    )
    _expect(
        lambda **kw: _generation.validate_generation_target(kw.pop("document"), kw.pop("gen")),
        "Generation 目标卡片不存在。",
        document=_document(),
        gen=make_generation(
            ReferenceGenerationKind.CHARACTER_VOICE,
            GenerationOperation.VOICE_DESIGN,
            target_id=ID_B,
            sample_text="文",
            seed=1,
        ),
    )
    # 合法目标通过：通用音频无目标约束。
    _generation.validate_generation_target(
        _document(),
        make_generation(
            ReferenceGenerationKind.GENERATED_AUDIO,
            GenerationOperation.VOICE_DESIGN,
            sample_text="文",
            seed=1,
        ),
    )


def test_create_generations_guards():
    document = _document()
    _expect(
        lambda **kw: _generation.create_generations(
            kw.pop("document"), kw.pop("gens"), timestamp=NOW
        ),
        "必须创建至少一个 Generation。",
        document=document,
        gens=(),
    )
    one = make_generation(
        ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
        GenerationOperation.SEPARATE,
        target_id=ID_B,
        input_asset_ids=(ID_B,),
    )
    _expect(
        lambda **kw: _generation.create_generations(
            kw.pop("document"), kw.pop("gens"), timestamp=NOW
        ),
        "Generation ID 不能重复。",
        document=document,
        gens=(one, one),
    )
    other = make_generation(
        ReferenceGenerationKind.KEYFRAME_IMAGE, GenerationOperation.GENERATE, target_id=ID_B
    )
    _expect(
        lambda **kw: _generation.create_generations(
            kw.pop("document"), kw.pop("gens"), timestamp=NOW
        ),
        "批量 Generation 入口仅用于关联音轨分离。",
        document=document,
        gens=(other,),
    )
    _expect(
        lambda **kw: _generation.create_generations(
            kw.pop("document"), kw.pop("gens"), timestamp=NOW
        ),
        "视频音轨分离目标必须是项目内 MP4 Asset。",
        document=document,
        gens=(one,),
    )


def _succeeded_voice_generation(generation_id: str = ID_D) -> ReferenceGeneration:
    return make_generation(
        ReferenceGenerationKind.CHARACTER_VOICE,
        GenerationOperation.VOICE_DESIGN,
        id=generation_id,
        target_id=ID_B,
        sample_text="文",
        seed=1,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        output_asset_id=ID_D,
    )


def test_attach_generation_output_guards():
    card = CharacterCard(ID_B, "角色", "视觉", (), "描述")
    document = _document(
        reference_library=ReferenceLibrary((card,), None),
        assets=(_wav_asset(ID_D),),
        generations=(_succeeded_voice_generation(),),
    )
    # kind 不匹配（voice 期望 CHARACTER_VOICE；构造一个造型设定图 Generation）
    image_gen = make_generation(
        ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
        GenerationOperation.GENERATE,
        id=ID_D,
        target_id=ID_B,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        output_asset_id=ID_D,
    )
    doc_image = _document(
        reference_library=ReferenceLibrary((card,), None),
        assets=(_png_asset(ID_D),),
        generations=(image_gen,),
    )
    _expect(
        lambda **kw: _generation.attach_generation_output(kw.pop("document"), **kw),
        "该 Generation 不是参考音色。",
        document=doc_image,
        kind="voice",
        card_id=ID_B,
        generation_id=ID_D,
        note="n",
    )
    # 角色图只经造型选择入口，不再挂到卡片
    _expect(
        lambda **kw: _generation.attach_generation_output(kw.pop("document"), **kw),
        "未知的参考素材类型。",
        document=document,
        kind="characters",
        card_id=ID_B,
        generation_id=ID_D,
        note="n",
    )
    # 成功路径：挂音色
    updated = _generation.attach_generation_output(
        document, kind="voice", card_id=ID_B, generation_id=ID_D, note="n"
    )
    assert updated.reference_library.characters[0].voice_reference_asset_id == ID_D


def test_dismiss_guards():
    running = make_generation(
        ReferenceGenerationKind.KEYFRAME_IMAGE,
        GenerationOperation.GENERATE,
        id=ID_D,
        target_id="e" * 32,
    )
    document = _document(generations=(running,))
    _expect(
        lambda **kw: _generation.dismiss_generation(
            kw.pop("document"), kw.pop("target"), command_id="cmd", timestamp=NOW
        ),
        "只有已经结束的 Generation 可以删除历史卡片。",
        document=document,
        target=GenerationTarget(ID_D),
    )
    succeeded = replace(running, phase=ReferenceGenerationPhase.SUCCEEDED, output_asset_id=ID_D)
    with_image = CharacterCard(
        ID_B, "角色", "视觉", (CharacterLook(ID_C, "日常", "外观", "场合", ID_D),), "描述"
    )
    referenced = _document(
        generations=(succeeded,),
        reference_library=ReferenceLibrary((with_image,), None),
        assets=(_png_asset(ID_D),),
    )
    _expect(
        lambda **kw: _generation.dismiss_generation(
            kw.pop("document"), kw.pop("target"), command_id="cmd", timestamp=NOW
        ),
        "该候选已经成为参考素材，请先解除引用。",
        document=referenced,
        target=GenerationTarget(ID_D),
    )
    # noop：已隐藏时 write=False。
    dismissed = replace(succeeded, dismissed=True)
    doc_done = _document(generations=(dismissed,), assets=(_png_asset(ID_D), _wav_asset("e" * 32)))
    _updated, receipt, write = _generation.dismiss_generation(
        doc_done, GenerationTarget(ID_D), command_id="cmd", timestamp=NOW
    )
    assert write is False and receipt.status == "noop"


def test_validate_completion_payload_guards():
    voice = make_generation(
        ReferenceGenerationKind.CHARACTER_VOICE,
        GenerationOperation.VOICE_DESIGN,
        target_id=ID_B,
        sample_text="文",
        seed=1,
    )
    content = b"x" * 24
    sha = __import__("hashlib").sha256(content).hexdigest()
    _expect(
        lambda **kw: _generation.validate_completion_payload(kw.pop("gen"), **kw),
        "音色 Generation 只能产出 WAV Asset。",
        gen=voice,
        media_type="image/png",
        content=content,
        expected_sha256=sha,
        expected_byte_count=24,
    )
    segment = make_generation(
        ReferenceGenerationKind.SEGMENT_VIDEO,
        GenerationOperation.RENDER,
        target_id=ID_B,
        input_asset_ids=(ID_C,),
        seed=1,
        duration_seconds=4.0,
    )
    _expect(
        lambda **kw: _generation.validate_completion_payload(kw.pop("gen"), **kw),
        "视频 Generation 只能产出 MP4 Asset。",
        gen=segment,
        media_type="audio/wav",
        content=content,
        expected_sha256=sha,
        expected_byte_count=24,
    )
    _expect(
        lambda **kw: _generation.validate_completion_payload(kw.pop("gen"), **kw),
        "图片 Generation 只能产出图片 Asset。",
        gen=make_generation(
            ReferenceGenerationKind.KEYFRAME_IMAGE, GenerationOperation.GENERATE, target_id=ID_B
        ),
        media_type="audio/wav",
        content=content,
        expected_sha256=sha,
        expected_byte_count=24,
    )
    _expect(
        lambda **kw: _generation.validate_completion_payload(kw.pop("gen"), **kw),
        "Provider Artifact 字节与描述不一致。",
        gen=segment,
        media_type="video/mp4",
        content=content,
        expected_sha256="0" * 64,
        expected_byte_count=24,
    )


def test_update_and_recover():
    document = _document()
    _expect(
        lambda **kw: _generation.update_generation(
            kw.pop("document"), kw.pop("gen"), timestamp=NOW
        ),
        "Generation 不存在。",
        document=document,
        gen=make_generation(
            ReferenceGenerationKind.KEYFRAME_IMAGE,
            GenerationOperation.GENERATE,
            target_id="e" * 32,
        ),
    )
    submitting = make_generation(
        ReferenceGenerationKind.KEYFRAME_IMAGE,
        GenerationOperation.GENERATE,
        id=ID_D,
        target_id="e" * 32,
        phase=ReferenceGenerationPhase.SUBMITTING,
        plugin_id=None,
        plugin_version=None,
        external_id=None,
    )
    doc = _document(generations=(submitting,))
    recovered, changed = _generation.recover_interrupted_submissions(doc, timestamp=NOW)
    assert changed is True
    assert recovered.generations[0].phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN
    assert recovered.generations[0].error_code == "core_restarted_during_submit"
    again, changed = _generation.recover_interrupted_submissions(recovered, timestamp=NOW)
    assert changed is False and again is recovered
