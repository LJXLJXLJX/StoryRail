"""ReferenceGeneration 的按域校验函数（从 __post_init__ 原样抽取）。

校验顺序与错误消息与抽取前完全一致：同一输入下首先抛出的错误不变。
"""

from __future__ import annotations

from datetime import datetime

from core.model_providers.manifest import IMAGE_ASPECT_RATIOS

from .._shared import (
    LANGUAGE_GENERATION_KINDS,
    GenerationOperation,
    NarrationLanguage,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    _require_id,
    _require_text,
    _validate_timestamp,
)


def validate_reference_generation(generation) -> None:
    """按原 __post_init__ 顺序执行全部 generation 校验。"""
    _validate_common_fields(generation)
    _validate_timestamps(generation)
    _validate_kind_contract(generation)
    _validate_provider_handle(generation)
    _validate_phase_handle_consistency(generation)
    _validate_lifecycle_fields(generation)


def _validate_common_fields(generation) -> None:
    if generation.aspect_ratio is not None and (
        generation.kind
        not in {
            ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
            ReferenceGenerationKind.LOCATION_MASTER_IMAGE,
        }
        or generation.aspect_ratio not in IMAGE_ASPECT_RATIOS
    ):
        raise ValueError("只有造型设定图与地点主图可以指定受支持的图片比例。")
    if generation.kind in LANGUAGE_GENERATION_KINDS:
        if not isinstance(generation.language, NarrationLanguage):
            raise ValueError("旁白音色、旁白音频与成片 Generation 必须标明语言。")
    elif generation.language is not None:
        raise ValueError("只有旁白音色、旁白音频与成片 Generation 可以标明语言。")
    if (
        generation.video_frame_request is not None
        and generation.kind is not ReferenceGenerationKind.VIDEO_FRAME
    ):
        raise ValueError("只有抽帧任务可包含 video_frame_request。")
    if (generation.location_crop_request is not None) != (
        generation.kind is ReferenceGenerationKind.LOCATION_VIEW_CROP
    ):
        raise ValueError("全景裁切必须且只有全景裁切保存 location_crop_request。")
    if (
        generation.video_input_snapshot is not None
        and generation.kind is not ReferenceGenerationKind.SEGMENT_VIDEO
    ):
        raise ValueError("只有 Segment 视频可包含 video_input_snapshot。")
    _require_id(generation.id, "generation.id")
    _require_id(generation.target_id, "generation.target_id")
    if not 0.0 <= generation.progress <= 1.0:
        raise ValueError("generation.progress 必须在 0 到 1 之间。")
    _require_text(generation.prompt_text, "generation.prompt_text", 20_000)
    if len(generation.recipe_params.entries) > 1 or (
        generation.recipe_params.entries
        and (
            generation.provider_snapshot is None
            or generation.recipe_params.entries[0][0] != generation.provider_snapshot.recipe_id
        )
    ):
        raise ValueError("generation.recipe_params 只能记录本次提交 recipe 的参数。")
    for asset_id in generation.input_asset_ids:
        _require_id(asset_id, "generation.input_asset_ids")
    if len(set(generation.input_asset_ids)) != len(generation.input_asset_ids):
        raise ValueError("generation.input_asset_ids 不能重复。")
    maximum_inputs = (
        700
        if generation.kind
        in {
            ReferenceGenerationKind.FINAL_VIDEO,
            ReferenceGenerationKind.SCENE_FINAL_VIDEO,
            ReferenceGenerationKind.SCENE_ANIMATIC,
        }
        else 17
        if generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO
        else 5
    )
    if len(generation.input_asset_ids) > maximum_inputs:
        raise ValueError(f"Generation 最多引用 {maximum_inputs} 个输入 Asset。")
    if len(generation.message) > 2_000:
        raise ValueError("generation.message 过长。")


def _validate_timestamps(generation) -> None:
    created_at = None
    updated_at = None
    if generation.created_at is not None:
        _validate_timestamp(generation.created_at, "generation.created_at")
        created_at = datetime.fromisoformat(generation.created_at)
        if created_at.utcoffset() is None:
            raise ValueError("generation.created_at 必须包含时区。")
    if generation.updated_at is not None:
        _validate_timestamp(generation.updated_at, "generation.updated_at")
        updated_at = datetime.fromisoformat(generation.updated_at)
        if updated_at.utcoffset() is None:
            raise ValueError("generation.updated_at 必须包含时区。")
    if created_at is not None and updated_at is not None and updated_at < created_at:
        raise ValueError("generation.updated_at 不能早于 created_at。")


def _validate_kind_contract(generation) -> None:
    if generation.kind in {
        ReferenceGenerationKind.CHARACTER_VOICE,
        ReferenceGenerationKind.NARRATOR_VOICE,
    }:
        if generation.operation is not GenerationOperation.VOICE_DESIGN:
            raise ValueError("音色 Generation 必须使用 voice_design 操作。")
        _require_text(generation.sample_text or "", "generation.sample_text", 2_000)
        if generation.input_asset_ids:
            raise ValueError("音色设计不能包含输入图片。")
        if (
            isinstance(generation.seed, bool)
            or not isinstance(generation.seed, int)
            or not 0 <= generation.seed <= 2**32 - 1
        ):
            raise ValueError("音色设计 generation.seed 不合法。")
        if generation.duration_seconds is not None:
            raise ValueError("音色设计不能包含旁白合成参数。")
    elif generation.kind is ReferenceGenerationKind.GENERATED_AUDIO:
        if generation.operation is GenerationOperation.VOICE_DESIGN:
            _require_text(generation.sample_text or "", "generation.sample_text", 2_000)
            if generation.input_asset_ids:
                raise ValueError("Voice Design 通用音频生成不能包含参考音频。")
            if (
                isinstance(generation.seed, bool)
                or not isinstance(generation.seed, int)
                or not 0 <= generation.seed <= 2**32 - 1
            ):
                raise ValueError("Voice Design 通用音频 generation.seed 不合法。")
        elif generation.operation is GenerationOperation.SYNTHESIZE:
            if len(generation.input_asset_ids) != 1:
                raise ValueError("音频克隆必须且只能引用一个参考音频 Asset。")
            _require_text(generation.sample_text or "", "generation.reference_transcript", 20_000)
            if (
                isinstance(generation.seed, bool)
                or not isinstance(generation.seed, int)
                or not 0 <= generation.seed <= 2**63 - 1
            ):
                raise ValueError("音频克隆 generation.seed 不合法。")
        else:
            raise ValueError("通用音频 Generation 操作不合法。")
        if generation.duration_seconds is not None:
            raise ValueError("通用音频 Generation 不预存产物时长。")
    elif generation.kind is ReferenceGenerationKind.VIDEO_FRAME:
        if (
            generation.operation is not GenerationOperation.PROCESS
            or generation.video_frame_request is None
        ):
            raise ValueError("抽帧必须使用 process 并保存来源请求。")
        if generation.input_asset_ids != (generation.video_frame_request.source_video_asset_id,):
            raise ValueError("抽帧输入必须等于冻结的源视频。")
        if any(
            x is not None
            for x in (
                generation.seed,
                generation.sample_text,
                generation.duration_seconds,
            )
        ):
            raise ValueError("抽帧不能包含生成参数。")
    elif generation.kind is ReferenceGenerationKind.LOCATION_VIEW_CROP:
        if generation.operation is not GenerationOperation.PROCESS:
            raise ValueError("全景裁切必须使用 process 操作。")
        if generation.input_asset_ids != (generation.location_crop_request.master_asset_id,):
            raise ValueError("全景裁切输入必须等于冻结的主图。")
        if any(
            x is not None
            for x in (generation.seed, generation.sample_text, generation.duration_seconds)
        ):
            raise ValueError("全景裁切不能包含生成参数。")
    elif generation.kind is ReferenceGenerationKind.AUDIO_EFFECT:
        if generation.operation is not GenerationOperation.PROCESS:
            raise ValueError("音频后处理 Generation 必须使用 process 操作。")
        if (
            len(generation.input_asset_ids) != 1
            or generation.target_id != generation.input_asset_ids[0]
        ):
            raise ValueError("音频后处理必须且只能引用目标源音频 Asset。")
        if (
            isinstance(generation.seed, bool)
            or not isinstance(generation.seed, int)
            or not 0 <= generation.seed <= 2**63 - 1
        ):
            raise ValueError("音频后处理 generation.seed 不合法。")
        if generation.sample_text is not None or generation.duration_seconds is not None:
            raise ValueError("音频后处理不能包含语音合成或视频参数。")
        if generation.phase is not ReferenceGenerationPhase.SUCCEEDED or not generation.dismissed:
            raise ValueError("本地音频后处理必须原子完成并隐藏执行记录。")
        if (
            generation.plugin_id != "storyrail.audio_effects"
            or generation.plugin_version not in {1, 2}
            or generation.external_id != generation.id
        ):
            raise ValueError("音频后处理必须记录固定的本地处理器身份。")
    elif generation.kind is ReferenceGenerationKind.AUDIO_TRIM:
        if generation.operation is not GenerationOperation.PROCESS:
            raise ValueError("音频截取 Generation 必须使用 process 操作。")
        if (
            len(generation.input_asset_ids) != 1
            or generation.target_id != generation.input_asset_ids[0]
        ):
            raise ValueError("音频截取必须且只能引用目标源音频 Asset。")
        if generation.seed is not None or any(
            value is not None for value in (generation.sample_text,)
        ):
            raise ValueError("音频截取不能包含语音合成参数或 seed。")
        if generation.duration_seconds is None or generation.duration_seconds <= 0:
            raise ValueError("音频截取必须记录有效输出时长。")
        if generation.phase is not ReferenceGenerationPhase.SUCCEEDED or not generation.dismissed:
            raise ValueError("本地音频截取必须原子完成并隐藏执行记录。")
        if (
            generation.plugin_id != "storyrail.audio_trim"
            or generation.plugin_version != 1
            or generation.external_id != generation.id
        ):
            raise ValueError("音频截取必须记录固定的本地处理器身份。")
    elif generation.kind is ReferenceGenerationKind.NARRATION_AUDIO:
        if generation.operation is not GenerationOperation.SYNTHESIZE:
            raise ValueError("旁白 Generation 必须使用 synthesize 操作。")
        _require_text(generation.sample_text or "", "generation.reference_transcript", 20_000)
        if len(generation.input_asset_ids) != 1:
            raise ValueError("旁白 Generation 必须引用一个旁白音色 Asset。")
        if (
            isinstance(generation.seed, bool)
            or not isinstance(generation.seed, int)
            or not 0 <= generation.seed <= 2**63 - 1
        ):
            raise ValueError("旁白 generation.seed 不合法。")
        if generation.duration_seconds is not None:
            raise ValueError("旁白 Generation 不保存视频时长。")
    elif generation.kind in {
        ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
        ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
    }:
        if generation.operation is not GenerationOperation.SEPARATE:
            raise ValueError("视频音轨分离 Generation 必须使用 separate 操作。")
        if (
            len(generation.input_asset_ids) != 1
            or generation.target_id != generation.input_asset_ids[0]
        ):
            raise ValueError("视频音轨分离必须且只能引用目标源视频 Asset。")
        if generation.seed is not None or any(
            value is not None for value in (generation.sample_text,)
        ):
            raise ValueError("视频音轨分离不能包含语音合成参数或 seed。")
    elif generation.kind is ReferenceGenerationKind.VIDEO_AUDIO_REMIX:
        if generation.operation is not GenerationOperation.REMIX:
            raise ValueError("视频音轨混音 Generation 必须使用 remix 操作。")
        if (
            len(generation.input_asset_ids) != 3
            or generation.target_id != generation.input_asset_ids[0]
        ):
            raise ValueError("视频音轨混音必须引用源视频、voice 和 background。")
        if generation.seed is not None or any(
            value is not None for value in (generation.sample_text,)
        ):
            raise ValueError("视频音轨混音不能包含语音合成参数或 seed。")
    elif generation.kind in {
        ReferenceGenerationKind.SEGMENT_VIDEO,
        ReferenceGenerationKind.VIDEO_UPSCALE,
        ReferenceGenerationKind.FINAL_VIDEO,
        ReferenceGenerationKind.SCENE_FINAL_VIDEO,
        ReferenceGenerationKind.SCENE_ANIMATIC,
    }:
        expected = (
            GenerationOperation.RENDER
            if generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO
            else GenerationOperation.UPSCALE
            if generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE
            else GenerationOperation.ASSEMBLE
        )
        attaching_segment_video = (
            generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO
            and generation.operation is GenerationOperation.ATTACH
        )
        if generation.operation is not expected and not attaching_segment_video:
            raise ValueError("视频 Generation 操作不合法。")
        if generation.sample_text is not None:
            raise ValueError("视频 Generation 不能包含语音参数。")
        if generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO:
            if attaching_segment_video:
                if generation.input_asset_ids or generation.seed is not None:
                    raise ValueError("资产库视频候选不能伪造生成输入或 seed。")
            elif not 1 <= len(generation.input_asset_ids) <= 17:
                raise ValueError(
                    "Segment 视频必须记录最多2张边界图、4张附加图、8条参考音频及3条参考视频血缘。"
                )
            if attaching_segment_video:
                if generation.duration_seconds is None or generation.duration_seconds < 0.2:
                    raise ValueError("资产库视频候选必须保存不短于 0.2 秒的真实时长。")
            elif generation.duration_seconds is None or generation.duration_seconds < 0.2:
                raise ValueError("Segment 视频必须保存不短于 0.2 秒的时长。")
            if not attaching_segment_video and (
                generation.seed is None or not 0 <= generation.seed <= 2**63 - 1
            ):
                raise ValueError("Segment 视频 seed 不合法。")
        elif generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE:
            if len(generation.input_asset_ids) != 1 or generation.duration_seconds is not None:
                raise ValueError("视频超分必须且只能引用一个源视频。")
            if generation.seed is None or not 0 <= generation.seed <= 2**63 - 1:
                raise ValueError("视频超分 seed 不合法。")
        else:
            if not generation.input_asset_ids:
                raise ValueError("成片装配必须记录输入媒体血缘。")
            if generation.seed is not None:
                raise ValueError("成片装配不使用随机 seed。")
            if generation.duration_seconds is None or generation.duration_seconds <= 0:
                raise ValueError("成片装配必须保存有效预期时长。")
    else:
        # 首帧抽帧候选以 attach 登记到 Keyframe，产物来自同 id 的 VIDEO_FRAME 任务。
        attaching_keyframe_frame = (
            generation.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
            and generation.operation is GenerationOperation.ATTACH
        )
        if (
            generation.operation not in {GenerationOperation.GENERATE, GenerationOperation.EDIT}
            and not attaching_keyframe_frame
        ):
            raise ValueError("图片 Generation 操作不合法。")
        if attaching_keyframe_frame and (
            generation.input_asset_ids or generation.phase is not ReferenceGenerationPhase.SUCCEEDED
        ):
            raise ValueError("首帧抽帧候选只能登记已成功的产物，不能伪造生成输入。")
        if generation.sample_text is not None:
            raise ValueError("图片 generation 不能包含音色设计参数。")

        # 声明 Seed 角色的图片插件由 Core 分配 seed；抽帧登记没有采样过程。
        if generation.seed is not None and (
            attaching_keyframe_frame or not 0 <= generation.seed <= 2**63 - 1
        ):
            raise ValueError("图片 generation seed 不合法。")
        if generation.duration_seconds is not None:
            raise ValueError("图片 generation 不能包含旁白合成参数。")
        if generation.operation is GenerationOperation.EDIT and not generation.input_asset_ids:
            raise ValueError("图片编辑必须包含底图 Asset。")


def _validate_provider_handle(generation) -> None:
    handle_values = (generation.plugin_id, generation.plugin_version, generation.external_id)
    if any(value is None for value in handle_values) and not all(
        value is None for value in handle_values
    ):
        raise ValueError("generation Provider handle 不完整。")
    if generation.plugin_id is not None:
        if not generation.plugin_id.strip() or len(generation.plugin_id) > 200:
            raise ValueError("generation.plugin_id 不合法。")
        if (
            isinstance(generation.plugin_version, bool)
            or not isinstance(generation.plugin_version, int)
            or generation.plugin_version < 1
        ):
            raise ValueError("generation.plugin_version 不合法。")
        if not generation.external_id or len(generation.external_id) > 1_000:
            raise ValueError("generation.external_id 不合法。")


def _validate_phase_handle_consistency(generation) -> None:
    has_handle = generation.plugin_id is not None
    rejected_before_handle = (
        generation.phase is ReferenceGenerationPhase.FAILED
        and generation.error_code == "submission_rejected"
    )
    no_handle_allowed = (
        generation.phase
        in {
            ReferenceGenerationPhase.SUBMITTING,
            ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
        }
        or rejected_before_handle
    )
    if no_handle_allowed and has_handle:
        raise ValueError("未建立外部任务的 generation 不能保存 Provider handle。")
    if not no_handle_allowed and not has_handle:
        raise ValueError("已提交的 generation 必须保存 Provider handle。")


def _validate_lifecycle_fields(generation) -> None:
    if generation.output_asset_id is not None:
        _require_id(generation.output_asset_id, "generation.output_asset_id")
    if (
        generation.phase is ReferenceGenerationPhase.SUCCEEDED
        and generation.output_asset_id is None
    ):
        raise ValueError("成功的 generation 必须引用输出 Asset。")
    if (
        generation.phase is not ReferenceGenerationPhase.SUCCEEDED
        and generation.output_asset_id is not None
    ):
        raise ValueError("未成功的 generation 不能引用输出 Asset。")
    if generation.retry_of is not None:
        _require_id(generation.retry_of, "generation.retry_of")
    if generation.phase is ReferenceGenerationPhase.FAILED and not generation.error_code:
        raise ValueError("失败的 generation 必须保存 error_code。")
    if not isinstance(generation.cancellation_requested, bool):
        raise ValueError("generation.cancellation_requested 必须是布尔值。")
    if not isinstance(generation.dismissed, bool):
        raise ValueError("generation.dismissed 必须是布尔值。")
    if generation.dismissed and generation.phase not in {
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
        ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
    }:
        raise ValueError("只有已经结束的 Generation 可以隐藏历史卡片。")
