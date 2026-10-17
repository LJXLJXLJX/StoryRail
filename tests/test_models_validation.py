"""models/validation characterization（P2-B2）。

逐条锁定两个超长 ``__post_init__`` 抽取前后的校验行为：每条规则至少一个
"触发即抛"用例，错误消息逐字匹配（re.escape）。generation 规则全覆盖；
document 规则覆盖可由最小 document 直接触发的子集——深层图校验
（keyframe_plan 图、video_plan、final 装配/approval 链）由
test_structured_director_*、test_final_scene_assembly 与 oracle 全旅程的
真实构造路径间接锁定（每次 document 构造都会执行完整 validate_document）。
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from video_recipes import SegmentVideoGenerationMode, SegmentVideoVideoReference, make_video

from core.model_providers.recipe import RecipeParams
from core.structured_director.models import (
    Asset,
    CharacterCard,
    DirectorScript,
    FinalApproval,
    GenerationOperation,
    Keyframe,
    KeyframePlan,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    PendingScriptEdit,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    Scene,
    SegmentKeyframes,
    Shot,
    ShotSegment,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    VideoPlan,
    WorkspaceLayers,
)

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32
SHA = "f" * 64


def _ids(n: int) -> tuple[str, ...]:
    return tuple(f"{i:032x}" for i in range(n))


def _asset(
    asset_id: str, media_type: str, byte_count: int, relative_path: str, duration: float | None
) -> Asset:
    # Asset.id 必须等于 sha256 前 32 位；按 asset_id 派生确定性哈希。
    return Asset(asset_id, media_type, byte_count, asset_id + "f" * 32, relative_path, duration)


def _wav_asset(asset_id: str = ID_C) -> Asset:
    return _asset(asset_id, "audio/wav", 8, "assets/audio/voice-references/ref.wav", 1.0)


def _mp4_asset(asset_id: str = ID_C) -> Asset:
    return _asset(asset_id, "video/mp4", 24, "assets/videos/segments/clip.mp4", 4.0)


def _png_asset(asset_id: str = ID_C) -> Asset:
    return _asset(asset_id, "image/png", 12, "assets/images/library/still.png", None)


def make_generation(kind, operation, **kw) -> ReferenceGeneration:
    fields = dict(
        id=ID_A,
        kind=kind,
        operation=operation,
        target_id=ID_B,
        phase=ReferenceGenerationPhase.QUEUED,
        progress=0.0,
        message="",
        prompt_text="提示词",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id="test.provider",
        plugin_version=1,
        external_id="external-1",
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=None,
        dismissed=False,
        created_at=None,
        updated_at=None,
        video_frame_request=None,
        video_input_snapshot=None,
    )
    fields.update(kw)
    return ReferenceGeneration(**fields)


def _frame_request() -> object:
    from core.structured_director.video_contracts import VideoFrameRequest

    return VideoFrameRequest("e" * 32, SHA, 4, 5, "a" * 32)


VOICE_BASE = dict(
    kind=ReferenceGenerationKind.CHARACTER_VOICE,
    operation=GenerationOperation.VOICE_DESIGN,
    sample_text="朗读文本",
    seed=1,
)
DESIGN_AUDIO_BASE = dict(
    kind=ReferenceGenerationKind.GENERATED_AUDIO,
    operation=GenerationOperation.VOICE_DESIGN,
    sample_text="朗读文本",
    seed=1,
)
CLONE_AUDIO_BASE = dict(
    kind=ReferenceGenerationKind.GENERATED_AUDIO,
    operation=GenerationOperation.SYNTHESIZE,
    input_asset_ids=(ID_C,),
    sample_text="完整文字稿",
    seed=1,
)


def _video_frame_base():
    return dict(
        kind=ReferenceGenerationKind.VIDEO_FRAME,
        operation=GenerationOperation.PROCESS,
        video_frame_request=_frame_request(),
        input_asset_ids=("e" * 32,),
    )


AUDIO_EFFECT_BASE = dict(
    kind=ReferenceGenerationKind.AUDIO_EFFECT,
    operation=GenerationOperation.PROCESS,
    target_id=ID_C,
    input_asset_ids=(ID_C,),
    seed=1,
    plugin_id="storyrail.audio_effects",
    plugin_version=2,
    external_id=ID_A,
    phase=ReferenceGenerationPhase.SUCCEEDED,
    output_asset_id=ID_D,
    dismissed=True,
)
AUDIO_TRIM_BASE = dict(
    kind=ReferenceGenerationKind.AUDIO_TRIM,
    operation=GenerationOperation.PROCESS,
    target_id=ID_C,
    input_asset_ids=(ID_C,),
    plugin_id="storyrail.audio_trim",
    plugin_version=1,
    external_id=ID_A,
    phase=ReferenceGenerationPhase.SUCCEEDED,
    output_asset_id=ID_D,
    dismissed=True,
    duration_seconds=1.0,
)
NARRATION_BASE = dict(
    kind=ReferenceGenerationKind.NARRATION_AUDIO,
    operation=GenerationOperation.SYNTHESIZE,
    input_asset_ids=(ID_C,),
    sample_text="完整文字稿",
    seed=1,
    language=NarrationLanguage.ZH,
)
SEPARATE_BASE = dict(
    kind=ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
    operation=GenerationOperation.SEPARATE,
    target_id=ID_C,
    input_asset_ids=(ID_C,),
)
REMIX_BASE = dict(
    kind=ReferenceGenerationKind.VIDEO_AUDIO_REMIX,
    operation=GenerationOperation.REMIX,
    target_id=ID_A,
    input_asset_ids=(ID_A, ID_B, ID_C),
)
SEGMENT_RENDER_BASE = dict(
    kind=ReferenceGenerationKind.SEGMENT_VIDEO,
    operation=GenerationOperation.RENDER,
    input_asset_ids=(ID_C,),
    seed=1,
    duration_seconds=5.0,
)
SEGMENT_ATTACH_BASE = dict(
    kind=ReferenceGenerationKind.SEGMENT_VIDEO,
    operation=GenerationOperation.ATTACH,
    phase=ReferenceGenerationPhase.SUCCEEDED,
    output_asset_id=ID_D,
    duration_seconds=5.0,
)
UPSCALE_BASE = dict(
    kind=ReferenceGenerationKind.VIDEO_UPSCALE,
    operation=GenerationOperation.UPSCALE,
    input_asset_ids=(ID_C,),
    seed=1,
)
FINAL_BASE = dict(
    kind=ReferenceGenerationKind.FINAL_VIDEO,
    operation=GenerationOperation.ASSEMBLE,
    input_asset_ids=(ID_C,),
    duration_seconds=10.0,
    language=NarrationLanguage.EN,
)

IMAGE_BASE = dict(
    kind=ReferenceGenerationKind.CHARACTER_LOOK_SHEET, operation=GenerationOperation.GENERATE
)

GENERATION_CASES = [
    # ---- 语言：旁白音色、旁白音频与成片按语言生成，其它 Generation 不得标明语言 ----
    ("narration_requires_language", NARRATION_BASE, dict(language=None), "必须标明语言"),
    ("final_requires_language", FINAL_BASE, dict(language=None), "必须标明语言"),
    (
        "narrator_voice_requires_language",
        VOICE_BASE,
        dict(kind=ReferenceGenerationKind.NARRATOR_VOICE),
        "必须标明语言",
    ),
    (
        "character_voice_rejects_language",
        VOICE_BASE,
        dict(language=NarrationLanguage.EN),
        "只有旁白音色、旁白音频与成片 Generation 可以标明语言。",
    ),
    (
        "image_rejects_language",
        IMAGE_BASE,
        dict(language=NarrationLanguage.ZH),
        "只有旁白音色、旁白音频与成片 Generation 可以标明语言。",
    ),
    # ---- 通用字段（图片基线） ----
    (
        "frame_request_only_for_video_frame",
        IMAGE_BASE,
        dict(video_frame_request=_frame_request()),
        "只有抽帧任务可包含 video_frame_request。",
    ),
    (
        "input_snapshot_only_for_segment_video",
        IMAGE_BASE,
        dict(video_input_snapshot=object()),
        "只有 Segment 视频可包含 video_input_snapshot。",
    ),
    ("progress_range", IMAGE_BASE, dict(progress=1.5), "generation.progress 必须在 0 到 1 之间。"),
    (
        "recipe_params_only_for_snapshot_recipe",
        IMAGE_BASE,
        dict(recipe_params=RecipeParams.from_json({"x.y": {"a": 1}})),
        "generation.recipe_params 只能记录本次提交 recipe 的参数。",
    ),
    (
        "input_assets_duplicate",
        IMAGE_BASE,
        dict(input_asset_ids=(ID_C, ID_C)),
        "generation.input_asset_ids 不能重复。",
    ),
    (
        "input_assets_image_maximum",
        IMAGE_BASE,
        dict(input_asset_ids=_ids(6)),
        "Generation 最多引用 5 个输入 Asset。",
    ),
    (
        "input_assets_final_maximum",
        FINAL_BASE,
        dict(input_asset_ids=_ids(701)),
        "Generation 最多引用 700 个输入 Asset。",
    ),
    ("message_length", IMAGE_BASE, dict(message="x" * 2001), "generation.message 过长。"),
    (
        "created_at_timezone",
        IMAGE_BASE,
        dict(created_at="2024-01-01T00:00:00"),
        "generation.created_at 必须包含时区。",
    ),
    (
        "updated_at_timezone",
        IMAGE_BASE,
        dict(updated_at="2024-01-01T00:00:00"),
        "generation.updated_at 必须包含时区。",
    ),
    (
        "updated_at_before_created",
        IMAGE_BASE,
        dict(created_at="2024-01-01T00:00:00+00:00", updated_at="2023-01-01T00:00:00+00:00"),
        "generation.updated_at 不能早于 created_at。",
    ),
    # ---- Provider handle 与生命周期 ----
    (
        "handle_incomplete",
        IMAGE_BASE,
        dict(plugin_version=None),
        "generation Provider handle 不完整。",
    ),
    ("plugin_id_invalid", IMAGE_BASE, dict(plugin_id="   "), "generation.plugin_id 不合法。"),
    (
        "plugin_version_invalid",
        IMAGE_BASE,
        dict(plugin_version=0),
        "generation.plugin_version 不合法。",
    ),
    ("external_id_invalid", IMAGE_BASE, dict(external_id=""), "generation.external_id 不合法。"),
    (
        "handle_before_submission",
        IMAGE_BASE,
        dict(phase=ReferenceGenerationPhase.SUBMITTING),
        "未建立外部任务的 generation 不能保存 Provider handle。",
    ),
    (
        "succeeded_requires_output",
        IMAGE_BASE,
        dict(phase=ReferenceGenerationPhase.SUCCEEDED),
        "成功的 generation 必须引用输出 Asset。",
    ),
    (
        "output_requires_success",
        IMAGE_BASE,
        dict(output_asset_id=ID_D),
        "未成功的 generation 不能引用输出 Asset。",
    ),
    (
        "failed_requires_error_code",
        IMAGE_BASE,
        dict(phase=ReferenceGenerationPhase.FAILED),
        "失败的 generation 必须保存 error_code。",
    ),
    (
        "cancellation_flag_bool",
        IMAGE_BASE,
        dict(cancellation_requested="yes"),
        "generation.cancellation_requested 必须是布尔值。",
    ),
    (
        "dismissed_flag_bool",
        IMAGE_BASE,
        dict(dismissed="yes"),
        "generation.dismissed 必须是布尔值。",
    ),
    (
        "dismiss_requires_terminal",
        IMAGE_BASE,
        dict(dismissed=True),
        "只有已经结束的 Generation 可以隐藏历史卡片。",
    ),
    # ---- 音色设计 ----
    (
        "voice_requires_voice_design",
        VOICE_BASE,
        dict(operation=GenerationOperation.GENERATE),
        "音色 Generation 必须使用 voice_design 操作。",
    ),
    (
        "voice_design_no_images",
        VOICE_BASE,
        dict(input_asset_ids=(ID_C,)),
        "音色设计不能包含输入图片。",
    ),
    ("voice_design_seed", VOICE_BASE, dict(seed=None), "音色设计 generation.seed 不合法。"),
    (
        "voice_design_no_narration_params",
        VOICE_BASE,
        dict(duration_seconds=1.0),
        "音色设计不能包含旁白合成参数。",
    ),
    # ---- 通用音频（Breeze Voice Design / Clone）----
    (
        "design_audio_no_reference_audio",
        DESIGN_AUDIO_BASE,
        dict(input_asset_ids=(ID_C,)),
        "Voice Design 通用音频生成不能包含参考音频。",
    ),
    (
        "design_audio_seed",
        DESIGN_AUDIO_BASE,
        dict(seed=None),
        "Voice Design 通用音频 generation.seed 不合法。",
    ),
    (
        "generic_audio_no_duration",
        DESIGN_AUDIO_BASE,
        dict(duration_seconds=1.0),
        "通用音频 Generation 不预存产物时长。",
    ),
    (
        "generic_audio_operation",
        DESIGN_AUDIO_BASE,
        dict(operation=GenerationOperation.GENERATE),
        "通用音频 Generation 操作不合法。",
    ),
    (
        "clone_requires_one_reference",
        CLONE_AUDIO_BASE,
        dict(input_asset_ids=()),
        "音频克隆必须且只能引用一个参考音频 Asset。",
    ),
    (
        "clone_requires_exactly_one_reference",
        CLONE_AUDIO_BASE,
        dict(input_asset_ids=(ID_C, ID_D)),
        "音频克隆必须且只能引用一个参考音频 Asset。",
    ),
    (
        "clone_needs_transcript",
        CLONE_AUDIO_BASE,
        dict(sample_text=None),
        "generation.reference_transcript 不能为空或超过 20000 字符。",
    ),
    (
        "clone_seed",
        CLONE_AUDIO_BASE,
        dict(seed=None),
        "音频克隆 generation.seed 不合法。",
    ),
    # ---- 抽帧 ----
    (
        "video_frame_process_and_request",
        _video_frame_base(),
        dict(operation=GenerationOperation.GENERATE),
        "抽帧必须使用 process 并保存来源请求。",
    ),
    (
        "video_frame_request_required",
        _video_frame_base(),
        dict(video_frame_request=None),
        "抽帧必须使用 process 并保存来源请求。",
    ),
    (
        "video_frame_input_is_source",
        _video_frame_base(),
        dict(input_asset_ids=("0" * 32,)),
        "抽帧输入必须等于冻结的源视频。",
    ),
    (
        "video_frame_no_generation_params",
        _video_frame_base(),
        dict(seed=1),
        "抽帧不能包含生成参数。",
    ),
    # ---- 音频后处理 ----
    (
        "audio_effect_process",
        AUDIO_EFFECT_BASE,
        dict(operation=GenerationOperation.GENERATE),
        "音频后处理 Generation 必须使用 process 操作。",
    ),
    (
        "audio_effect_single_source",
        AUDIO_EFFECT_BASE,
        dict(input_asset_ids=()),
        "音频后处理必须且只能引用目标源音频 Asset。",
    ),
    (
        "audio_effect_seed",
        AUDIO_EFFECT_BASE,
        dict(seed=None),
        "音频后处理 generation.seed 不合法。",
    ),
    (
        "audio_effect_no_voice_params",
        AUDIO_EFFECT_BASE,
        dict(sample_text="文"),
        "音频后处理不能包含语音合成或视频参数。",
    ),
    (
        "audio_effect_atomic_hidden",
        AUDIO_EFFECT_BASE,
        dict(dismissed=False),
        "本地音频后处理必须原子完成并隐藏执行记录。",
    ),
    (
        "audio_effect_fixed_identity",
        AUDIO_EFFECT_BASE,
        dict(plugin_version=3),
        "音频后处理必须记录固定的本地处理器身份。",
    ),
    # ---- 音频截取 ----
    (
        "audio_trim_process",
        AUDIO_TRIM_BASE,
        dict(operation=GenerationOperation.GENERATE),
        "音频截取 Generation 必须使用 process 操作。",
    ),
    (
        "audio_trim_single_source",
        AUDIO_TRIM_BASE,
        dict(input_asset_ids=()),
        "音频截取必须且只能引用目标源音频 Asset。",
    ),
    (
        "audio_trim_no_voice_params",
        AUDIO_TRIM_BASE,
        dict(seed=1),
        "音频截取不能包含语音合成参数或 seed。",
    ),
    (
        "audio_trim_duration",
        AUDIO_TRIM_BASE,
        dict(duration_seconds=None),
        "音频截取必须记录有效输出时长。",
    ),
    (
        "audio_trim_atomic_hidden",
        AUDIO_TRIM_BASE,
        dict(dismissed=False),
        "本地音频截取必须原子完成并隐藏执行记录。",
    ),
    (
        "audio_trim_fixed_identity",
        AUDIO_TRIM_BASE,
        dict(plugin_version=2),
        "音频截取必须记录固定的本地处理器身份。",
    ),
    # ---- 旁白 ----
    (
        "narration_synthesize",
        NARRATION_BASE,
        dict(operation=GenerationOperation.VOICE_DESIGN),
        "旁白 Generation 必须使用 synthesize 操作。",
    ),
    (
        "narration_one_voice_asset",
        NARRATION_BASE,
        dict(input_asset_ids=()),
        "旁白 Generation 必须引用一个旁白音色 Asset。",
    ),
    ("narration_seed", NARRATION_BASE, dict(seed=None), "旁白 generation.seed 不合法。"),
    (
        "narration_needs_transcript",
        NARRATION_BASE,
        dict(sample_text=None),
        "generation.reference_transcript 不能为空或超过 20000 字符。",
    ),
    (
        "narration_no_video_duration",
        NARRATION_BASE,
        dict(duration_seconds=1.0),
        "旁白 Generation 不保存视频时长。",
    ),
    # ---- 视频音轨分离/混音 ----
    (
        "separate_operation",
        SEPARATE_BASE,
        dict(operation=GenerationOperation.GENERATE),
        "视频音轨分离 Generation 必须使用 separate 操作。",
    ),
    (
        "separate_single_source",
        SEPARATE_BASE,
        dict(input_asset_ids=()),
        "视频音轨分离必须且只能引用目标源视频 Asset。",
    ),
    (
        "separate_no_voice_params",
        SEPARATE_BASE,
        dict(seed=1),
        "视频音轨分离不能包含语音合成参数或 seed。",
    ),
    (
        "remix_operation",
        REMIX_BASE,
        dict(operation=GenerationOperation.SEPARATE),
        "视频音轨混音 Generation 必须使用 remix 操作。",
    ),
    (
        "remix_three_inputs",
        REMIX_BASE,
        dict(input_asset_ids=(ID_A, ID_B)),
        "视频音轨混音必须引用源视频、voice 和 background。",
    ),
    (
        "remix_no_voice_params",
        REMIX_BASE,
        dict(seed=1),
        "视频音轨混音不能包含语音合成参数或 seed。",
    ),
    # ---- Segment 视频 ----
    (
        "video_operation",
        SEGMENT_RENDER_BASE,
        dict(operation=GenerationOperation.PROCESS),
        "视频 Generation 操作不合法。",
    ),
    (
        "video_no_voice_params",
        SEGMENT_RENDER_BASE,
        dict(sample_text="文"),
        "视频 Generation 不能包含语音参数。",
    ),
    (
        "segment_video_duration",
        SEGMENT_RENDER_BASE,
        dict(duration_seconds=0.1),
        "Segment 视频必须保存不短于 0.2 秒的时长。",
    ),
    ("segment_video_seed", SEGMENT_RENDER_BASE, dict(seed=None), "Segment 视频 seed 不合法。"),
    (
        "attach_no_fake_inputs",
        SEGMENT_ATTACH_BASE,
        dict(input_asset_ids=(ID_C,)),
        "资产库视频候选不能伪造生成输入或 seed。",
    ),
    (
        "attach_no_seed",
        SEGMENT_ATTACH_BASE,
        dict(seed=1),
        "资产库视频候选不能伪造生成输入或 seed。",
    ),
    (
        "attach_real_duration",
        SEGMENT_ATTACH_BASE,
        dict(duration_seconds=None),
        "资产库视频候选必须保存不短于 0.2 秒的真实时长。",
    ),
    # ---- 超分与成片装配 ----
    (
        "upscale_single_source",
        UPSCALE_BASE,
        dict(input_asset_ids=(ID_C, ID_D)),
        "视频超分必须且只能引用一个源视频。",
    ),
    (
        "upscale_no_duration",
        UPSCALE_BASE,
        dict(duration_seconds=1.0),
        "视频超分必须且只能引用一个源视频。",
    ),
    ("upscale_seed", UPSCALE_BASE, dict(seed=None), "视频超分 seed 不合法。"),
    ("assemble_lineage", FINAL_BASE, dict(input_asset_ids=()), "成片装配必须记录输入媒体血缘。"),
    ("assemble_no_seed", FINAL_BASE, dict(seed=1), "成片装配不使用随机 seed。"),
    (
        "assemble_duration",
        FINAL_BASE,
        dict(duration_seconds=None),
        "成片装配必须保存有效预期时长。",
    ),
    # ---- 图片 ----
    (
        "image_edit_needs_base",
        dict(kind=ReferenceGenerationKind.KEYFRAME_IMAGE, operation=GenerationOperation.EDIT),
        {},
        "图片编辑必须包含底图 Asset。",
    ),
    (
        "image_no_voice_params",
        IMAGE_BASE,
        dict(sample_text="样本"),
        "图片 generation 不能包含音色设计参数。",
    ),
    ("image_seed_range", IMAGE_BASE, dict(seed=-1), "图片 generation seed 不合法。"),
    (
        "image_ratio_vocabulary",
        IMAGE_BASE,
        dict(aspect_ratio="7:5"),
        "只有造型设定图与地点主图可以指定受支持的图片比例。",
    ),
    (
        "keyframe_has_no_ratio",
        dict(kind=ReferenceGenerationKind.KEYFRAME_IMAGE, operation=GenerationOperation.GENERATE),
        dict(aspect_ratio="1:1"),
        "只有造型设定图与地点主图可以指定受支持的图片比例。",
    ),
    (
        "image_no_narration_params",
        IMAGE_BASE,
        dict(duration_seconds=1.0),
        "图片 generation 不能包含旁白合成参数。",
    ),
]


@pytest.mark.parametrize(
    "case_id,base,mutation,message", GENERATION_CASES, ids=[c[0] for c in GENERATION_CASES]
)
def test_reference_generation_rule_messages(case_id, base, mutation, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        make_generation(**{**base, **mutation})


# ---------------------------------------------------------------------------
# document 规则（最小 document 直接触发的子集）
# ---------------------------------------------------------------------------

SEGMENT = ShotSegment(ID_B, 4.0, "动作", (), None)
KF_START = Keyframe(ID_A, ID_B, None, "首帧", ())
KF_END = Keyframe("c" * 32, ID_B, ID_A, "尾帧", ())
KEYFRAME_PLAN = KeyframePlan(
    1,
    (KF_START, KF_END),
    (SegmentKeyframes(ID_B, ID_A, "c" * 32, True, True),),
)
SHOT = Shot("e" * 32, (), "构图", "固定", "动作", "环境声", None, (SEGMENT,))
CUE_PLAIN = NarrationCue(
    "5" * 32, None, None, NarrationTrack("旁白", 1), NarrationTrack("Narration.", 1)
)
SCENE_EMPTY = Scene("f" * 32, "场景", "摘要", "环境", (), (CUE_PLAIN,), "narration", None)
SCENE_ONE_SHOT = Scene("f" * 32, "场景", "摘要", "环境", (SHOT,), (), "drama", None)
SCRIPT_EMPTY = DirectorScript(1, 1, None, None, (SCENE_EMPTY,))


def _document(store) -> StructuredDirectorDocument:
    return store.read()


def _expect(document: StructuredDirectorDocument, message: str, **changes):
    with pytest.raises(ValueError, match=re.escape(message)):
        replace(document, **changes)


def test_document_rules(store_factory):
    store = store_factory()
    document = _document(store)
    cases = [
        (dict(schema_version=999), "不支持的 project.json schema_version。"),
        (dict(revision=0), "project.json revision 必须是正整数。"),
        (dict(title=""), "project.json title 不能为空或超过 56 字符。"),
        (
            dict(director_plan_markdown=""),
            "project.json director_plan_markdown 不能为空或超过 50000 字符。",
        ),
        (
            dict(status=StructuredDirectorStatus.REVIEWING_VIDEOS),
            "当前工作状态对应的导演台内容层尚未解锁。",
        ),
        (
            dict(status=StructuredDirectorStatus.REVIEWING_SCRIPT),
            "审核结构化脚本时必须保存脚本草稿。",
        ),
        (dict(director_script=SCRIPT_EMPTY), "结构化脚本 proposal 完成前不能保存脚本草稿。"),
        (
            dict(pending_script_edit=PendingScriptEdit(1, "请求")),
            "只有 Agent 编辑脚本时才能保存待处理请求。",
        ),
        (dict(keyframe_plan=KEYFRAME_PLAN), "关键帧内容层尚未解锁。"),
        (dict(assets=(_wav_asset(), _wav_asset())), "Asset ID 不能重复。"),
        (
            dict(
                generations=(
                    make_generation(
                        ReferenceGenerationKind.KEYFRAME_IMAGE,
                        GenerationOperation.GENERATE,
                        phase=ReferenceGenerationPhase.SUCCEEDED,
                        output_asset_id=ID_D,
                    ),
                )
            ),
            "generation 输出 Asset 不存在。",
        ),
        (
            dict(
                generations=(
                    make_generation(
                        ReferenceGenerationKind.CHARACTER_VOICE,
                        GenerationOperation.VOICE_DESIGN,
                        sample_text="文",
                        seed=1,
                    ),
                )
            ),
            "角色音色 Generation 的目标不存在。",
        ),
        (
            dict(final_approval=FinalApproval(ID_D, ID_B, ID_D, ID_B, 1, 1)),
            "最终 Approval 只能存在于已批准状态。",
        ),
    ]
    for changes, message in cases:
        _expect(document, message, **changes)


def test_document_voice_only_identity_cannot_be_visible(store_factory):
    store = store_factory()
    document = store.read()
    voice_only = CharacterCard(ID_C, "声音身份", None, (), "描述")
    library = ReferenceLibrary((voice_only,), None)
    shot = Shot("e" * 32, (ID_C,), "构图", "固定", "动作", "环境声", None, (SEGMENT,))
    scene = Scene("f" * 32, "场景", "摘要", "环境", (shot,), (), "drama", None)
    script = DirectorScript(1, 1, None, None, (scene,))
    with pytest.raises(ValueError, match=re.escape("非出镜声音身份不能作为 Shot 可见角色。")):
        replace(
            document,
            status=StructuredDirectorStatus.REVIEWING_SCRIPT,
            reference_library=library,
            director_script=script,
        )


def test_document_cue_selection_requires_successful_generation(store_factory):
    store = store_factory()
    document = store.read()
    cue = NarrationCue(
        "5" * 32,
        None,
        None,
        NarrationTrack("旁白", 1, _wav_asset().id),
        NarrationTrack("Narration.", 1),
    )
    scene = Scene("f" * 32, "场景", "摘要", "环境", (), (cue,), "narration", None)
    script = DirectorScript(1, 1, None, None, (scene,))
    with pytest.raises(
        ValueError, match=re.escape("旁白 Cue 选择的音频没有对应的成功 Generation。")
    ):
        replace(
            document,
            status=StructuredDirectorStatus.REVIEWING_SCRIPT,
            director_script=script,
            assets=(_wav_asset(),),
        )


def test_document_video_reference_requires_project_mp4_asset(store_factory):
    store = store_factory()
    document = store.read()
    layers = WorkspaceLayers(
        narration_unlocked=True,
        keyframes_unlocked=True,
        videos_unlocked=True,
    )
    video = make_video(
        ID_B,
        "提示词",
        SegmentVideoGenerationMode.REF2VA,
        video_references=(SegmentVideoVideoReference(ID_C, "参考运镜。"),),
    )
    script = DirectorScript(1, 1, 1, (SCENE_ONE_SHOT,), (SCENE_ONE_SHOT,))
    base = dict(
        status=StructuredDirectorStatus.REVIEWING_VIDEOS,
        workspace_layers=layers,
        director_script=script,
        keyframe_plan=KEYFRAME_PLAN,
        video_plan=VideoPlan(1, (video,)),
    )
    # 合法 MP4 参考视频可以直接构造。
    replace(document, assets=(_mp4_asset(),), **base)
    from provider_factory import provider_registry
    from structured_director_fixtures import RecordingProvider

    from core.model_providers.manifest import Capability

    catalog = provider_registry(
        ref2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture")
    )
    with pytest.raises(ValueError, match="参考视频只接受 video/mp4"):
        catalog.validate_recipe_inputs(
            Capability.VIDEO_GENERATE, video.active_recipe, video.recipe_inputs, (_wav_asset(),)
        )
    _expect(document, "视频参考输入必须引用本项目 Asset。", **base)


def test_document_approved_requires_assembly_plan(store_factory):
    store = store_factory()
    document = store.read()
    layers = WorkspaceLayers(
        narration_unlocked=True,
        keyframes_unlocked=True,
        videos_unlocked=True,
        final_assembly_unlocked=True,
    )
    with pytest.raises(ValueError, match=re.escape("成片审核阶段必须保存装配计划。")):
        replace(
            document,
            status=StructuredDirectorStatus.APPROVED,
            workspace_layers=layers,
            director_script=SCRIPT_EMPTY,
        )
