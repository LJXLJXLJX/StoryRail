"""同源视频输入与候选适用性；只读，不提交媒体。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from core.model_providers.manifest import Role
from core.model_providers.recipe import SlotBinding

from .models import ReferenceGenerationKind as Kind
from .models import ReferenceGenerationPhase as Phase
from .script_index import scene_segments, shot_segments
from .video_contracts import VideoInputSnapshot

TERMINAL = {Phase.SUCCEEDED, Phase.FAILED, Phase.CANCELLED}


def segment_context(document, segment_id):
    for scene in document.director_script.scenes if document.director_script else ():
        for shot in scene.shots:
            for index, segment in enumerate(shot_segments(scene, shot.id)):
                if segment.id == segment_id:
                    return scene, shot, segment, index
    raise ValueError("Segment 不存在。")


def binding_for(document, segment_id):
    return (
        next((x for x in document.keyframe_plan.segments if x.segment_id == segment_id), None)
        if document.keyframe_plan
        else None
    )


def video_for(document, segment_id):
    return (
        next((x for x in document.video_plan.segments if x.segment_id == segment_id), None)
        if document.video_plan
        else None
    )


def generation_for(document, generation_id):
    return next((x for x in document.generations if x.id == generation_id), None)


def effective_video(document, segment_id):
    """当前生效视频：有超分取超分，否则取所选原视频。

    只承认用户的选择，不因生成输入变化而作废：旧输入下生成的候选被选中后一样可以
    进入超分与装配；输入是否仍然一致由 ``video_inputs_unchanged`` 作为软提示暴露。
    """

    plan = video_for(document, segment_id)
    if plan is None or plan.selected_asset_id is None:
        return None
    if plan.upscaled_asset_id:
        if not any(
            x.kind is Kind.VIDEO_UPSCALE
            and x.target_id == segment_id
            and x.phase is Phase.SUCCEEDED
            and not x.dismissed
            and x.output_asset_id == plan.upscaled_asset_id
            and x.input_asset_ids == (plan.selected_asset_id,)
            for x in document.generations
        ):
            raise ValueError("超分视频与当前所选原视频不匹配。")
        return plan.upscaled_asset_id
    return plan.selected_asset_id


@dataclass(frozen=True)
class VideoInputs:
    start_asset_id: str | None
    end_asset_id: str | None
    snapshot: VideoInputSnapshot


def resolve_video_inputs(document, segment_id):
    binding = binding_for(document, segment_id)
    plan = video_for(document, segment_id)
    if binding is None or plan is None:
        raise ValueError("视频生产输入不完整。")
    frames = {x.id: x for x in document.keyframe_plan.keyframes}
    start = frames[binding.start_keyframe_id].selected_asset_id if binding.start_enabled else None
    end = frames[binding.end_keyframe_id].selected_asset_id if binding.end_enabled else None
    if (binding.start_enabled and start is None) or (binding.end_enabled and end is None):
        raise ValueError("所有启用的边界输入必须先准备图片；关键帧尚未选择。")
    _, _, segment, _ = segment_context(document, segment_id)
    dialogue = dialogue_audio_inputs(document, segment_id, require_ready=False)
    # 第 3、4 项固定为 schema v21 关键帧来源的取值，保持已有视频候选的签名不变。
    facts = [
        1,
        segment_id,
        "keyframe",
        None,
        start,
        end,
        plan.prompt_text,
        plan.active_recipe,
        plan.recipe_inputs.to_json(),
        [
            (
                item[0].id,
                item[1].selected_audio_asset_id,
                item[1].start_seconds,
                item[2].duration_seconds,
            )
            for item in dialogue
        ],
        segment.duration_estimate_seconds,
        document.aspect_ratio.value,
    ]
    signature = hashlib.sha256(
        json.dumps(facts, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    dialogue_signature = (
        None
        if not segment.dialogue_lines
        else hashlib.sha256(
            json.dumps(
                [
                    (
                        line.id,
                        line.text,
                        item.selected_audio_asset_id,
                        item.start_seconds,
                        asset.duration_seconds,
                    )
                    for line, item, asset in dialogue
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    return VideoInputs(
        start,
        end,
        VideoInputSnapshot(signature, start, end, dialogue_signature),
    )


def dialogue_audio_inputs(document, segment_id, *, require_ready=True):
    """按剧本顺序返回 (DialogueLine, DialogueAudio, Asset)，必要时强制完整真实时序。"""
    _scene, _shot, segment, _index = segment_context(document, segment_id)
    if not segment.dialogue_lines:
        return ()
    if document.dialogue_plan is None:
        raise ValueError("该 Segment 有对白，但 DialoguePlan 不存在。")
    plan = {item.dialogue_line_id: item for item in document.dialogue_plan.items}
    assets = {item.id: item for item in document.assets}
    result = []
    previous_end = 0.0
    for line in segment.dialogue_lines:
        item = plan.get(line.id)
        if item is None or item.selected_audio_asset_id is None:
            if require_ready:
                raise ValueError("请先为该 Segment 的每句对白生成并选择 TTS 音频。")
            continue
        asset = assets.get(item.selected_audio_asset_id)
        if asset is None or asset.media_type != "audio/wav" or asset.duration_seconds is None:
            raise ValueError("对白选择的 WAV Asset 不存在或没有真实时长。")
        if require_ready:
            if item.start_seconds is None:
                raise ValueError(
                    "对白时序尚未校准，请先点击「按真实音频自动校准时长」后再生成视频。"
                )
            if item.start_seconds + 1e-6 < previous_end:
                raise ValueError("对白真实音频时序发生重叠，请重新校准。")
            previous_end = item.start_seconds + asset.duration_seconds
        result.append((line, item, asset))
    if require_ready:
        if len(result) != len(segment.dialogue_lines):
            raise ValueError("请先为该 Segment 的每句对白生成并选择 TTS 音频。")
        if previous_end > segment.duration_estimate_seconds + 1e-6:
            raise ValueError("Segment 视频时长不能短于对白真实音频的结束时间。")
    return tuple(result)


def video_prompt_facts(document, segment, labels):
    """交给插件提示词校验器的领域事实；对白按剧本顺序，Audio 标签按实际显式绑定查找。"""
    audio_labels = {
        item["asset_id"]: item["label"] for item in labels if item["role"] == "reference_audio"
    }
    selected = {
        line.id: asset.id
        for line, _, asset in dialogue_audio_inputs(document, segment.id, require_ready=False)
    }
    characters = {item.id: item.name for item in document.reference_library.characters}
    return {
        "duration_seconds": segment.duration_estimate_seconds,
        "asset_labels": [item["label"] for item in labels if item["label"] is not None],
        "dialogue": [
            {
                "speaker": line.speaker_label
                or characters.get(line.character_id, line.character_id),
                "text": line.text,
                "audio_label": audio_labels.get(selected.get(line.id)),
            }
            for line in segment.dialogue_lines
        ],
    }


def dialogue_audio_bindings(document, segment_id):
    """一键添加用的显式引用草稿；不要求已校准时序，不写 authority。"""
    _, _, segment, _ = segment_context(document, segment_id)
    selected = dialogue_audio_inputs(document, segment_id, require_ready=False)
    selected_ids = {line.id for line, _, _ in selected}
    missing = [
        f"第 {index + 1} 句「{line.text}」"
        for index, line in enumerate(segment.dialogue_lines)
        if line.id not in selected_ids
    ]
    if missing:
        raise ValueError("以下对白尚未选择 TTS 音频：" + "、".join(missing))
    if not selected:
        raise ValueError("本 Segment 没有对白。")
    bindings = {}
    for line, _, asset in selected:
        description = dialogue_audio_description(document, line, asset)
        if len(description) > 2000:
            raise ValueError("对白完整说明超过参考音频的 2000 字限制，请先拆分这句对白。")
        bindings.setdefault(asset.id, SlotBinding(asset.id, description))
    return tuple(bindings.values())


def _dialogue_history_asset_ids(document, segment):
    line_ids = {line.id for line in segment.dialogue_lines}
    return list(
        dict.fromkeys(
            generation.output_asset_id
            for generation in document.generations
            if generation.kind is Kind.DIALOGUE_AUDIO
            and generation.target_id in line_ids
            and generation.output_asset_id is not None
        )
    )


def attach_dialogue_audio(document, segment_id, slot, bindings):
    """与 Web“一键添加本段对白 TTS”同一规则：对白按剧本顺序在前，覆盖本句历史 WAV，
    保留其他手动参考。缺任一句已选 TTS 或合计超出槽位上限时整次拒绝，不部分添加。
    """
    _, _, segment, _ = segment_context(document, segment_id)
    dialogue = dialogue_audio_bindings(document, segment_id)
    replaced = {
        *_dialogue_history_asset_ids(document, segment),
        *(item.asset_id for item in dialogue),
    }
    merged = (
        *dialogue,
        *(item for item in bindings.get(slot.key, ()) if item.asset_id not in replaced),
    )
    if len(merged) > slot.maximum:
        raise ValueError(
            f"本段对白与已有参考音频合计 {len(merged)} 条，超过 {slot.maximum} 条上限。"
            "请先移除其他参考音频或拆分 Segment。"
        )
    return {**bindings, slot.key: merged}


def dialogue_audio_addition(document, segment_id, recipe, bindings):
    """完整引用草稿、可覆盖的历史资产集合与未绑定台词提示，供 Web 与专业工作集共用。"""
    _, _, segment, _ = segment_context(document, segment_id)
    audio_slot = next((slot for slot in recipe.slots if slot.role is Role.REFERENCE_AUDIO), None)
    if audio_slot is not None:
        addition = {
            "slot": audio_slot.key,
            "bindings": [],
            "error": None,
            "replace_asset_ids": _dialogue_history_asset_ids(document, segment),
            "unbound_lines": unbound_dialogue_lines(document, segment_id, recipe, bindings),
        }
        try:
            addition["bindings"] = [
                {"asset_id": item.asset_id, "description": item.description}
                for item in dialogue_audio_bindings(document, segment_id)
            ]
        except ValueError as exc:
            addition["error"] = str(exc)
        # 软约束：对白句数超过参考音频名额时只提示拆分，不阻止保存其中几句或生成。
        if len(segment.dialogue_lines) > audio_slot.maximum:
            addition["error"] = (
                f"本段有 {len(segment.dialogue_lines)} 句对白，超过当前 recipe {audio_slot.label}"
                f" {audio_slot.maximum} 条上限，无法全部加入。建议拆分 Segment；"
                "也可只手动绑定其中几句，未绑定台词不会进入视频。"
            )
        addition["replace_asset_ids"] = list(
            dict.fromkeys(
                [
                    *addition["replace_asset_ids"],
                    *(item["asset_id"] for item in addition["bindings"]),
                ]
            )
        )
        return addition
    return None


def dialogue_audio_description(document, line, asset):
    characters = {item.id: item.name for item in document.reference_library.characters}
    speaker = line.speaker_label or characters.get(line.character_id, line.character_id)
    return (
        f"说话人：{speaker}。\n说话内容：{line.text}\n"
        f"真实时长：{asset.duration_seconds:.3f} 秒。\n"
        "后续视频生成必须严格应用这段对白，保持原台词、声音与表演节奏，不得改写、遗漏或自行替换。"
    )


def validate_dialogue_video_bindings(document, segment_id, recipe, bindings):
    """生成门禁：对白音频须已就绪且 recipe 支持参考音频；是否绑定对白只做软提示。"""
    dialogue = dialogue_audio_inputs(document, segment_id)
    if dialogue and not any(slot.role is Role.REFERENCE_AUDIO for slot in recipe.slots):
        raise ValueError("含对白的 Segment 必须使用支持参考音频的 Ref2VA recipe。")
    return dialogue


def unbound_dialogue_lines(document, segment_id, recipe, bindings):
    """已选对白 TTS 中没有出现在参考音频槽位里的台词；只提示，不阻止生成。"""
    audio_slots = [slot for slot in recipe.slots if slot.role is Role.REFERENCE_AUDIO]
    bound = {item.asset_id for slot in audio_slots for item in bindings.get(slot.key, ())}
    return [
        line.text
        for line, _, asset in dialogue_audio_inputs(document, segment_id, require_ready=False)
        if asset.id not in bound
    ]


def video_candidate_selectable(document, generation):
    """选择和后续装配只要求成功、未隐藏、属于当前视频计划的 Segment 且有 MP4 产物。

    生成输入快照的变化只影响 ``video_inputs_unchanged`` 的软提示，不构成选择门槛：
    用户可以为已变化的输入选一条旧视频，成片会直接使用它。
    """

    base = (
        generation.phase is Phase.SUCCEEDED
        and not generation.dismissed
        and any(
            a.id == generation.output_asset_id and a.media_type == "video/mp4"
            for a in document.assets
        )
        and video_for(document, generation.target_id) is not None
    )
    if not base:
        return False
    try:
        _scene, _shot, segment, _index = segment_context(document, generation.target_id)
    except ValueError:
        return False
    if not segment.dialogue_lines:
        return True
    try:
        current = resolve_video_inputs(document, generation.target_id).snapshot
    except (ValueError, KeyError):
        return False
    return (
        generation.video_input_snapshot is not None
        and generation.video_input_snapshot.dialogue_signature is not None
        and generation.video_input_snapshot.dialogue_signature == current.dialogue_signature
    )


def video_inputs_unchanged(document, generation):
    """只读软提示：候选生成时的输入是否仍等于当前输入；不作为选择门槛。"""

    if generation.video_input_snapshot is None:
        return True
    try:
        return (
            resolve_video_inputs(document, generation.target_id).snapshot
            == generation.video_input_snapshot
        )
    except (ValueError, KeyError):
        return False


def start_frame_extraction_source(document, keyframe_id):
    """首帧卡“从上一 Segment 抽取”的来源；只描述可用性，不建立续接保证。

    上一 Segment 按脚本顺序计算（可跨 Shot/Scene），来源是它当前生效的视频
    （有超分时取超分）。共享边界的首帧同时是上一段尾帧，从上一段视频抽取会形成
    循环依赖，因此不开放。
    """

    plan = document.keyframe_plan
    script = document.director_script
    result = {
        "segment_id": None,
        "source_segment_id": None,
        "source_video_asset_id": None,
        "state": "unavailable",
        "message": "该 Keyframe 不是 Segment 首帧。",
    }
    if plan is None or script is None:
        return result
    binding = next((x for x in plan.segments if x.start_keyframe_id == keyframe_id), None)
    if binding is None:
        return result
    result["segment_id"] = binding.segment_id
    ordered = [segment.id for scene in script.scenes for segment in scene_segments(scene)]
    if binding.segment_id not in ordered or ordered.index(binding.segment_id) == 0:
        result["message"] = "这是第一个 Segment，没有上一段视频可抽取。"
        return result
    previous_id = ordered[ordered.index(binding.segment_id) - 1]
    result["source_segment_id"] = previous_id
    if any(x.end_keyframe_id == keyframe_id for x in plan.segments):
        result["state"] = "shared_boundary"
        result["message"] = "该首帧与上一段尾帧共享，不能从上一段视频抽取；请先拆开边界。"
        return result
    try:
        asset_id = effective_video(document, previous_id)
    except ValueError as exc:
        result["state"] = "source_not_current"
        result["message"] = str(exc)
        return result
    if asset_id is None:
        result["state"] = "waiting_source_video"
        result["message"] = "上一段还没有采用视频。"
        return result
    result.update(state="ready", source_video_asset_id=asset_id, message="可以从上一段视频抽取。")
    return result
