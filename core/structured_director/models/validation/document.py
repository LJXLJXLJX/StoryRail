"""StructuredDirectorDocument 的按域校验函数（从 __post_init__ 原样抽取）。

校验顺序与错误消息与抽取前完全一致：同一输入下首先抛出的错误不变。
validate_document 依原 __post_init__ 语句顺序调用各分段函数。
"""

from __future__ import annotations

from ...schema import PROJECT_SCHEMA_VERSION
from .._shared import (
    NARRATION_LANGUAGES,
    GenerationOperation,
    NarrationLanguage,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorStatus,
    _require_id,
    _require_text,
)
from ..asset import Asset
from ..generation import ReferenceGeneration
from ..run import DirectorRunKind, DirectorRunStatus


def validate_document(document) -> None:
    """按原 __post_init__ 顺序执行全部 document 校验。"""
    _validate_identity(document)
    _validate_application_requests(document)
    _validate_capability_gaps(document)
    _validate_director_runs(document)
    _validate_status_layers(document)
    _validate_pending_edits(document)
    _validate_keyframe_unlocked(document)
    _validate_script_source_revision(document)
    asset_by_id, generation_by_id = _validate_assets_and_generations(document)
    _validate_voice_only_visibility(document)
    _validate_keyframe_character_references(document)
    _validate_narration_selections(document, asset_by_id)
    _validate_dialogue_plan(document, asset_by_id)
    _validate_locations(document, asset_by_id)
    _validate_keyframe_plan(document, asset_by_id)
    _validate_video_plan(document, asset_by_id)
    _validate_final_assembly(document, asset_by_id)
    _validate_final_approval(document, generation_by_id)


def _unique_by_id(items: tuple[object, ...], label: str) -> dict[str, object]:
    result = {item.id: item for item in items}
    if len(result) != len(items):
        raise ValueError(f"{label} ID 不能重复。")
    return result


def _validate_card_assets(asset_ids: tuple[str, ...], assets: dict[str, object]) -> None:
    for asset_id in asset_ids:
        asset = assets.get(asset_id)
        if not isinstance(asset, Asset) or not asset.media_type.startswith("image/"):
            raise ValueError("造型图必须引用已登记的图片 Asset。")


def _validate_identity(document) -> None:
    if document.schema_version != PROJECT_SCHEMA_VERSION:
        raise ValueError("不支持的 project.json schema_version。")
    _require_id(document.project_id, "project_id")
    if isinstance(document.revision, bool) or document.revision < 1:
        raise ValueError("project.json revision 必须是正整数。")
    _require_text(document.title, "project.json title", 56)
    _require_text(document.director_plan_markdown, "project.json director_plan_markdown", 50_000)
    languages = document.narration_languages
    if (
        not isinstance(languages, tuple)
        or not 1 <= len(languages) <= 2
        or any(not isinstance(language, NarrationLanguage) for language in languages)
        or len(set(languages)) != len(languages)
    ):
        raise ValueError("旁白语言仅支持中文和英文，至少选择一种且不能重复。")
    narrator = document.reference_library.narrator
    if narrator is not None and tuple(language for language, _ in narrator.voices) != languages:
        raise ValueError("旁白音色必须完整对应项目所选语言，未选语言必须为 null。")
    if document.director_script is not None and any(
        tuple(language for language, _ in cue.tracks) != languages
        for scene in document.director_script.scenes
        for cue in scene.narration_cues
    ):
        raise ValueError("旁白轨道必须完整对应项目所选语言，未选语言必须为 null。")


def _validate_application_requests(document) -> None:
    request_ids = [item.request_id for item in document.application_requests]
    namespaces = [(item.caller_id, item.idempotency_key) for item in document.application_requests]
    generation_ids = {item.id for item in document.generations}
    if len(request_ids) != len(set(request_ids)) or len(namespaces) != len(set(namespaces)):
        raise ValueError("application request namespace 不能重复。")
    for item in document.application_requests:
        if item.project_id != document.project_id or item.expected_revision > document.revision:
            raise ValueError("application request scope/revision 不合法。")
        if item.result_revision is not None and item.result_revision > document.revision:
            raise ValueError("application request 不能引用未来回执。")
        if not set(item.generation_ids) <= generation_ids:
            raise ValueError("application request 引用了不存在的 Generation。")


def _validate_capability_gaps(document) -> None:
    gap_ids = [item.gap_id for item in document.capability_gap_alerts]
    if len(gap_ids) != len(set(gap_ids)):
        raise ValueError("capability gap ID 不能重复。")
    if any(item.new_revision > document.revision for item in document.capability_gap_alerts):
        raise ValueError("capability gap 不能引用未来 revision。")
    if any(
        item.closed_revision is not None and item.closed_revision > document.revision
        for item in document.capability_gap_alerts
    ):
        raise ValueError("capability gap 不能在未来 revision 关闭。")


def _validate_director_runs(document) -> None:
    run_by_id = _unique_by_id(document.director_runs, "Director run")
    if any(item.last_project_revision > document.revision for item in document.director_runs):
        raise ValueError("Director run 不能引用未来 project revision。")
    _unique_by_id(document.director_directives, "Director directive")
    if any(item.run_id not in run_by_id for item in document.director_directives):
        raise ValueError("Director directive 引用了不存在的 run。")
    if len(document.director_runs) > 1_000 or len(document.director_directives) > 10_000:
        raise ValueError("Director run/directive 历史超过项目上限。")
    active_runs = [
        item
        for item in document.director_runs
        if item.status
        in {
            DirectorRunStatus.RUNNING,
            DirectorRunStatus.WAITING_USER,
            DirectorRunStatus.WAITING_JOBS,
        }
    ]
    if len(active_runs) > 1:
        raise ValueError("同一项目只能存在一个未结束的 Director run。")


def _validate_status_layers(document) -> None:
    required_layers = {
        StructuredDirectorStatus.REVIEWING_NARRATION: "narration_unlocked",
        StructuredDirectorStatus.REVIEWING_KEYFRAMES: "keyframes_unlocked",
        StructuredDirectorStatus.REVIEWING_VIDEOS: "videos_unlocked",
        StructuredDirectorStatus.REVIEWING_FINAL: "final_assembly_unlocked",
        StructuredDirectorStatus.APPROVED: "final_assembly_unlocked",
    }
    required_layer = required_layers.get(document.status)
    if required_layer is not None and not getattr(document.workspace_layers, required_layer):
        raise ValueError("当前工作状态对应的导演台内容层尚未解锁。")
    if (
        document.status is StructuredDirectorStatus.AWAITING_PROPOSAL
        and document.reference_library.characters
    ):
        raise ValueError("引用库 proposal 完成前不能保存卡片。")
    if document.status in {
        StructuredDirectorStatus.REVIEWING_SCRIPT,
        StructuredDirectorStatus.REVIEWING_NARRATION,
        StructuredDirectorStatus.REVIEWING_KEYFRAMES,
        StructuredDirectorStatus.REVIEWING_VIDEOS,
        StructuredDirectorStatus.REVIEWING_FINAL,
        StructuredDirectorStatus.APPROVED,
    }:
        if document.director_script is None:
            raise ValueError("审核结构化脚本时必须保存脚本草稿。")
    elif document.director_script is not None:
        raise ValueError("结构化脚本 proposal 完成前不能保存脚本草稿。")


def _validate_pending_edits(document) -> None:
    active_kind = (
        None if document.active_director_run is None else document.active_director_run.kind
    )
    if active_kind is DirectorRunKind.SCRIPT_EDIT:
        if document.pending_script_edit is None or document.director_script is None:
            raise ValueError("Agent 编辑脚本时必须保存待处理请求和当前草稿。")
        if document.pending_script_edit.base_script_revision != document.director_script.revision:
            raise ValueError("Agent 编辑请求的 base revision 与当前草稿不一致。")
    elif document.pending_script_edit is not None:
        raise ValueError("只有 Agent 编辑脚本时才能保存待处理请求。")
    if active_kind is DirectorRunKind.NARRATION_EDIT:
        if document.pending_narration_edit is None or document.director_script is None:
            raise ValueError("Agent 调整旁白时必须保存待处理请求和当前脚本。")
        if (
            document.pending_narration_edit.base_script_revision
            != document.director_script.revision
        ):
            raise ValueError("旁白 Agent 请求的 base revision 与当前脚本不一致。")
    elif document.pending_narration_edit is not None:
        raise ValueError("只有旁白 Agent 工作时才能保存待处理请求。")


def _validate_keyframe_unlocked(document) -> None:
    if document.keyframe_plan is not None and not document.workspace_layers.keyframes_unlocked:
        raise ValueError("关键帧内容层尚未解锁。")


def _validate_script_source_revision(document) -> None:
    if (
        document.director_script is not None
        and document.director_script.source_reference_revision > document.revision
    ):
        raise ValueError("结构化脚本引用了未来的项目 revision。")


def _validate_assets_and_generations(document) -> None:
    asset_by_id = _unique_by_id(document.assets, "Asset")
    generation_by_id = _unique_by_id(document.generations, "Generation")
    if any(
        generation_id not in generation_by_id
        for run in document.director_runs
        for generation_id in run.cursor.waiting_generation_ids
    ):
        raise ValueError("Director run 等待了不存在的 Generation。")
    for card in document.reference_library.characters:
        _validate_card_assets(card.look_asset_ids, asset_by_id)
        if card.voice_reference_asset_id is not None:
            asset = asset_by_id.get(card.voice_reference_asset_id)
            if not isinstance(asset, Asset) or asset.media_type != "audio/wav":
                raise ValueError("角色参考音色必须引用已登记的 WAV Asset。")
    narrator = document.reference_library.narrator
    for asset_id in () if narrator is None else narrator.voice_reference_asset_ids:
        asset = asset_by_id.get(asset_id)
        if not isinstance(asset, Asset) or asset.media_type != "audio/wav":
            raise ValueError("旁白音色必须引用已登记的 WAV Asset。")
    for generation in document.generations:
        if (
            generation.language is not None
            and generation.language not in document.narration_languages
        ):
            raise ValueError("Generation 的旁白语言未在项目中启用。")
        for asset_id in generation.input_asset_ids:
            asset = asset_by_id.get(asset_id)
            if generation.kind is ReferenceGenerationKind.VIDEO_FRAME:
                accepted = isinstance(asset, Asset) and asset.media_type == "video/mp4"
            elif generation.kind in {
                ReferenceGenerationKind.AUDIO_EFFECT,
                ReferenceGenerationKind.AUDIO_TRIM,
            }:
                accepted = isinstance(asset, Asset) and asset.media_type == "audio/wav"
            elif generation.kind in {
                ReferenceGenerationKind.GENERATED_AUDIO,
                ReferenceGenerationKind.DIALOGUE_AUDIO,
            }:
                accepted = (
                    generation.operation is GenerationOperation.SYNTHESIZE
                    and isinstance(asset, Asset)
                    and asset.media_type == "audio/wav"
                )
            elif generation.kind in {
                ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
                ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
            }:
                accepted = isinstance(asset, Asset) and asset.media_type == "video/mp4"
            elif generation.kind is ReferenceGenerationKind.VIDEO_AUDIO_REMIX:
                position = generation.input_asset_ids.index(asset_id)
                expected = "video/mp4" if position == 0 else "audio/wav"
                accepted = isinstance(asset, Asset) and asset.media_type == expected
            elif generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE:
                accepted = isinstance(asset, Asset) and asset.media_type == "video/mp4"
            elif generation.kind in {
                ReferenceGenerationKind.FINAL_VIDEO,
                ReferenceGenerationKind.SCENE_FINAL_VIDEO,
            }:
                accepted = isinstance(asset, Asset) and asset.media_type in {
                    "video/mp4",
                    "audio/wav",
                }
            elif generation.kind is ReferenceGenerationKind.SCENE_ANIMATIC:
                accepted = isinstance(asset, Asset) and asset.media_type in {
                    "image/png",
                    "image/jpeg",
                    "audio/wav",
                }
            elif generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO:
                accepted = isinstance(asset, Asset) and (
                    asset.media_type.startswith("image/")
                    or asset.media_type in {"audio/wav", "video/mp4"}
                )
            else:
                expected_input = (
                    "audio/wav"
                    if generation.kind is ReferenceGenerationKind.NARRATION_AUDIO
                    else "image/"
                )
                accepted = isinstance(asset, Asset) and asset.media_type.startswith(expected_input)
            if not accepted:
                raise ValueError("generation 输入 Asset 的媒体类型不匹配。")
        if generation.output_asset_id is not None and generation.output_asset_id not in asset_by_id:
            raise ValueError("generation 输出 Asset 不存在。")
        if generation.output_asset_id is not None:
            output = asset_by_id[generation.output_asset_id]
            expected_media = (
                "video/mp4"
                if generation.kind
                in {
                    ReferenceGenerationKind.SEGMENT_VIDEO,
                    ReferenceGenerationKind.VIDEO_UPSCALE,
                    ReferenceGenerationKind.FINAL_VIDEO,
                    ReferenceGenerationKind.SCENE_FINAL_VIDEO,
                    ReferenceGenerationKind.SCENE_ANIMATIC,
                }
                else "audio/wav"
                if generation.kind
                in {
                    ReferenceGenerationKind.CHARACTER_VOICE,
                    ReferenceGenerationKind.NARRATOR_VOICE,
                    ReferenceGenerationKind.NARRATION_AUDIO,
                    ReferenceGenerationKind.GENERATED_AUDIO,
                    ReferenceGenerationKind.DIALOGUE_AUDIO,
                    ReferenceGenerationKind.AUDIO_EFFECT,
                    ReferenceGenerationKind.AUDIO_TRIM,
                    ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
                    ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
                }
                else "video/mp4"
                if generation.kind is ReferenceGenerationKind.VIDEO_AUDIO_REMIX
                else "image/"
            )
            if not isinstance(output, Asset) or not output.media_type.startswith(expected_media):
                raise ValueError("generation 输出 Asset 的媒体类型不匹配。")
        if generation.retry_of is not None and (
            generation.retry_of not in generation_by_id or generation.retry_of == generation.id
        ):
            raise ValueError("generation.retry_of 不存在或指向自身。")
        if (
            generation.kind is ReferenceGenerationKind.CHARACTER_VOICE
            and generation.target_id
            not in {card.id for card in document.reference_library.characters}
        ):
            raise ValueError("角色音色 Generation 的目标不存在。")
        if generation.kind is ReferenceGenerationKind.NARRATOR_VOICE and (
            narrator is None or generation.target_id != narrator.id
        ):
            raise ValueError("旁白音色 Generation 的目标不存在。")
    return asset_by_id, generation_by_id


def _validate_voice_only_visibility(document) -> None:
    voice_only_ids = {
        card.id for card in document.reference_library.characters if card.visual_description is None
    }
    for scene in document.director_script.scenes if document.director_script else ():
        for shot in scene.shots:
            if voice_only_ids.intersection(shot.visible_character_ids):
                raise ValueError("非出镜声音身份不能作为 Shot 可见角色。")
    for frame in document.keyframe_plan.keyframes if document.keyframe_plan else ():
        if voice_only_ids.intersection(frame.visible_character_ids):
            raise ValueError("非出镜声音身份不能作为 Keyframe 可见角色。")


def _validate_keyframe_character_references(document) -> None:
    card_looks = {
        card.id: {look.id for look in card.looks} for card in document.reference_library.characters
    }
    for frame in document.keyframe_plan.keyframes if document.keyframe_plan else ():
        for reference in frame.character_references:
            looks = card_looks.get(reference.character_id)
            if looks is None or (reference.look_id is not None and reference.look_id not in looks):
                raise ValueError("Keyframe 角色造型必须选自该角色当前的造型。")


def _validate_narration_selections(document, asset_by_id) -> None:
    cue_by_id = {
        cue.id: cue
        for scene in (() if document.director_script is None else document.director_script.scenes)
        for cue in scene.narration_cues
    }
    for cue in cue_by_id.values():
        for language, track in cue.tracks:
            if track.selected_audio_asset_id is None:
                continue
            selected = asset_by_id.get(track.selected_audio_asset_id)
            if not isinstance(selected, Asset) or selected.media_type != "audio/wav":
                raise ValueError("旁白 Cue 必须选择 WAV Asset。")
            if not any(
                generation.kind is ReferenceGenerationKind.NARRATION_AUDIO
                and generation.target_id == cue.id
                and generation.language is language
                and generation.output_asset_id == track.selected_audio_asset_id
                and generation.phase is ReferenceGenerationPhase.SUCCEEDED
                and not generation.dismissed
                for generation in document.generations
            ):
                raise ValueError("旁白 Cue 选择的音频没有对应的成功 Generation。")


def _validate_dialogue_plan(document, asset_by_id) -> None:
    lines = {
        line.id: (segment, line)
        for scene in (() if document.director_script is None else document.director_script.scenes)
        for segment in scene.segments
        for line in segment.dialogue_lines
        if line.id is not None
    }
    plan = document.dialogue_plan
    if document.director_script is None:
        if plan is not None:
            raise ValueError("对白计划不能早于结构化脚本。")
        return
    if plan is None:
        if lines:
            raise ValueError("有对白的脚本必须保存 DialoguePlan。")
        return
    if plan.source_script_revision != document.director_script.revision:
        raise ValueError("对白计划的脚本 revision 与当前脚本不一致。")
    if {item.dialogue_line_id for item in plan.items} != set(lines):
        raise ValueError("对白计划必须完整对应当前 DialogueLine。")
    for item in plan.items:
        if item.selected_audio_asset_id is None:
            continue
        selected = asset_by_id.get(item.selected_audio_asset_id)
        if (
            not isinstance(selected, Asset)
            or selected.media_type != "audio/wav"
            or selected.duration_seconds is None
            or selected.duration_seconds <= 0
        ):
            raise ValueError("对白必须选择带真实时长的 WAV Asset。")
        if not any(
            generation.kind is ReferenceGenerationKind.DIALOGUE_AUDIO
            and generation.target_id == item.dialogue_line_id
            and generation.output_asset_id == item.selected_audio_asset_id
            and generation.phase is ReferenceGenerationPhase.SUCCEEDED
            and not generation.dismissed
            for generation in document.generations
        ):
            raise ValueError("对白选择的音频没有对应的成功 Generation。")
    items = {item.dialogue_line_id: item for item in plan.items}
    for scene in document.director_script.scenes:
        for segment in scene.segments:
            if not segment.dialogue_lines:
                continue
            segment_items = [items[line.id] for line in segment.dialogue_lines]
            if not any(item.start_seconds is not None for item in segment_items):
                continue
            if any(
                item.start_seconds is None or item.selected_audio_asset_id is None
                for item in segment_items
            ):
                raise ValueError("Segment 的对白时序必须一次完整覆盖全部 DialogueLine。")
            previous_end = 0.0
            for item in segment_items:
                assert item.start_seconds is not None
                assert item.selected_audio_asset_id is not None
                asset = asset_by_id[item.selected_audio_asset_id]
                if item.start_seconds + 1e-6 < previous_end:
                    raise ValueError("Segment 的对白音频不能重叠。")
                previous_end = item.start_seconds + asset.duration_seconds
            if previous_end > segment.duration_estimate_seconds + 1e-6:
                raise ValueError("Segment 时长不能短于对白真实音频结束时间。")


def _validate_locations(document, asset_by_id) -> None:
    """地点图片只能引用本项目图片；Scene 只保留可选的语义地点/状态关系。"""
    library = document.location_library
    for location in library.locations:
        for image in location.images:
            for asset_id in (*image.reference_asset_ids, image.selected_asset_id):
                if asset_id is None:
                    continue
                asset = asset_by_id.get(asset_id)
                if not isinstance(asset, Asset) or not asset.media_type.startswith("image/"):
                    raise ValueError("地点图片只能使用本项目图片 Asset。")
    location_by_id = {item.id: item for item in library.locations}
    for scene in document.director_script.scenes if document.director_script else ():
        location = None if scene.location_id is None else location_by_id.get(scene.location_id)
        if scene.location_id is not None and location is None:
            raise ValueError("Scene 引用的地点不存在。")
        if scene.state_id is not None and (
            location is None or all(state.id != scene.state_id for state in location.states)
        ):
            raise ValueError("Scene 的地点状态必须属于该 Scene 的地点。")


def _validate_keyframe_plan(document, asset_by_id) -> None:
    if document.keyframe_plan is not None:
        if (
            document.director_script is None
            or document.director_script.production_baseline_scenes is None
        ):
            raise ValueError("关键帧计划必须基于生产基线。")
        if document.keyframe_plan.source_script_revision != document.director_script.revision:
            raise ValueError("关键帧计划的脚本 revision 与当前脚本不一致。")
        script_scenes = document.director_script.scenes
        segment_ids = {segment.id for scene in script_scenes for segment in scene.segments}
        if {item.segment_id for item in document.keyframe_plan.segments} != segment_ids:
            raise ValueError("关键帧计划必须完整对应每个 Segment。")
        keyframe_by_id = {item.id: item for item in document.keyframe_plan.keyframes}
        binding_by_segment = {item.segment_id: item for item in document.keyframe_plan.segments}
        referenced_keyframe_ids = {
            keyframe_id
            for binding in document.keyframe_plan.segments
            for keyframe_id in (binding.start_keyframe_id, binding.end_keyframe_id)
        }
        if referenced_keyframe_ids != set(keyframe_by_id):
            raise ValueError("关键帧计划不能包含未绑定到 Segment 的 Keyframe。")
        # Segment 边界默认是两个独立 Keyframe；共享边界是显式选择，两侧启用状态各自独立。
        for segment_id in segment_ids:
            binding = binding_by_segment[segment_id]
            end_keyframe = keyframe_by_id[binding.end_keyframe_id]
            if (
                end_keyframe.owner_segment_id != segment_id
                or end_keyframe.predecessor_keyframe_id != binding.start_keyframe_id
            ):
                raise ValueError("Segment 尾帧必须从该 Segment 首帧直接承接。")
        for keyframe in document.keyframe_plan.keyframes:
            if keyframe.owner_segment_id not in segment_ids:
                raise ValueError("Keyframe owner Segment 不存在。")
            if keyframe.selected_asset_id is not None:
                selected = asset_by_id.get(keyframe.selected_asset_id)
                if not isinstance(selected, Asset) or not selected.media_type.startswith("image/"):
                    raise ValueError("关键帧必须选择图片 Asset。")
        for binding in document.keyframe_plan.segments:
            for asset_id in binding.reference_asset_ids:
                asset = asset_by_id.get(asset_id)
                if not isinstance(asset, Asset) or not asset.media_type.startswith("image/"):
                    raise ValueError("Segment 辅助参考必须引用图片 Asset。")
            if binding.start_keyframe_id not in keyframe_by_id:
                raise ValueError("Segment 首帧不存在。")


def _validate_video_plan(document, asset_by_id) -> None:
    if document.video_plan is not None:
        if not document.workspace_layers.videos_unlocked:
            raise ValueError("视频计划只能存在于视频生产阶段。")
        if document.director_script is None or document.keyframe_plan is None:
            raise ValueError("视频计划必须基于导演脚本和关键帧计划。")
        if document.video_plan.source_script_revision != document.director_script.revision:
            raise ValueError("视频计划脚本 revision 已失效。")
        segment_ids = {
            segment.id for scene in document.director_script.scenes for segment in scene.segments
        }
        if {item.segment_id for item in document.video_plan.segments} != segment_ids:
            raise ValueError("视频计划必须完整对应当前 Segment。")
        reference_ids = [
            image.id for video in document.video_plan.segments for image in video.reference_images
        ]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("视频参考图片 ID 不得跨 Segment 重复。")
        characters = {card.id: card for card in document.reference_library.characters}
        for item in document.video_plan.segments:
            for image in item.reference_images:
                if not set(image.visible_character_ids) <= characters.keys():
                    raise ValueError("参考图片的可见角色不存在。")
                for choice in image.character_references:
                    if choice.look_id is not None and not any(
                        look.id == choice.look_id for look in characters[choice.character_id].looks
                    ):
                        raise ValueError("参考图片选择的造型不存在。")
                if any(
                    asset_id not in asset_by_id
                    or not asset_by_id[asset_id].media_type.startswith("image/")
                    for asset_id in image.reference_asset_ids
                ):
                    raise ValueError("参考图片的生图输入必须为项目图片。")
            for _recipe_id, inputs in item.recipes.entries:
                if any(asset_id not in asset_by_id for asset_id in inputs.asset_ids):
                    raise ValueError("视频参考输入必须引用本项目 Asset。")
            for asset_id in (item.selected_asset_id, item.upscaled_asset_id):
                if asset_id is not None:
                    asset = asset_by_id.get(asset_id)
                    if not isinstance(asset, Asset) or asset.media_type != "video/mp4":
                        raise ValueError("Segment 视频必须引用 MP4 Asset。")


def _validate_final_assembly(document, asset_by_id) -> None:
    if document.final_assembly is not None:
        if not document.workspace_layers.final_assembly_unlocked:
            raise ValueError("成片装配计划只能存在于成片审核阶段。")
        if document.director_script is None or document.video_plan is None:
            raise ValueError("成片装配必须基于导演脚本和视频计划。")
        if document.final_assembly.source_script_revision != document.director_script.revision:
            raise ValueError("成片装配计划脚本 revision 已失效。")
        expected_scenes = [scene.id for scene in document.director_script.scenes]
        if [item.scene_id for item in document.final_assembly.clips] != expected_scenes:
            raise ValueError("最终成片装配顺序必须完整对应导演脚本的 Scene。")
        for clip in document.final_assembly.clips:
            if any(
                (clip.asset_id(language) is not None) != (language in document.narration_languages)
                for language in NARRATION_LANGUAGES
            ):
                raise ValueError("Scene 成片必须完整对应项目所选语言。")
            for language in document.narration_languages:
                asset = asset_by_id.get(clip.asset_id(language))
                if not isinstance(asset, Asset) or asset.media_type != "video/mp4":
                    raise ValueError("Scene 成片片段必须引用 MP4 Asset。")
        for language in NARRATION_LANGUAGES:
            selected_asset_id = document.final_assembly.selected_asset_id(language)
            if selected_asset_id is None:
                continue
            if language not in document.narration_languages:
                raise ValueError("项目未启用该成片语言。")
            selected = asset_by_id.get(selected_asset_id)
            if not isinstance(selected, Asset) or selected.media_type != "video/mp4":
                raise ValueError("成片必须选择 MP4 Asset。")
            if not any(
                generation.kind is ReferenceGenerationKind.FINAL_VIDEO
                and generation.language is language
                and generation.output_asset_id == selected.id
                and generation.phase is ReferenceGenerationPhase.SUCCEEDED
                and not generation.dismissed
                for generation in document.generations
            ):
                raise ValueError("成片选择的 Asset 没有成功 Generation。")
    elif document.status is StructuredDirectorStatus.APPROVED:
        raise ValueError("成片审核阶段必须保存装配计划。")


def _validate_final_approval(document, generation_by_id) -> None:
    if document.final_approval is not None:
        approval = document.final_approval
        if any(
            (approval.asset_id(language) is not None) != (language in document.narration_languages)
            or (approval.generation_id(language) is not None)
            != (language in document.narration_languages)
            for language in NARRATION_LANGUAGES
        ):
            raise ValueError("最终 Approval 必须完整对应项目所选语言。")
        if document.status is not StructuredDirectorStatus.APPROVED:
            raise ValueError("最终 Approval 只能存在于已批准状态。")
        plan = document.final_assembly
        if plan is None or any(
            plan.selected_asset_id(language) is None for language in document.narration_languages
        ):
            raise ValueError("批准成片前必须选择项目所选语言的最终候选。")
        if any(
            approval.asset_id(language) != plan.selected_asset_id(language)
            for language in document.narration_languages
        ):
            raise ValueError("最终 Approval 必须绑定当前选择的所选语言成片。")
        if document.director_script is None or (
            approval.source_script_revision != document.director_script.revision
        ):
            raise ValueError("最终 Approval 的脚本 revision 已失效。")
        if approval.approved_project_revision != document.revision:
            raise ValueError("最终 Approval 必须绑定批准写入后的项目 revision。")
        for language in document.narration_languages:
            generation = generation_by_id.get(approval.generation_id(language))
            if not isinstance(generation, ReferenceGeneration) or not (
                generation.kind is ReferenceGenerationKind.FINAL_VIDEO
                and generation.language is language
                and generation.phase is ReferenceGenerationPhase.SUCCEEDED
                and generation.output_asset_id == approval.asset_id(language)
                and not generation.dismissed
            ):
                raise ValueError("最终 Approval 必须绑定成功且未删除的成片 Generation。")
    elif document.status is StructuredDirectorStatus.APPROVED:
        raise ValueError("已批准状态必须保存最终 Approval。")
