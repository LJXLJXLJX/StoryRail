from __future__ import annotations

from uuid import uuid4

from core.model_providers.manifest import Capability, Role
from core.model_providers.recipe import MediaInput, RecipeParams, SlotBinding, binding_labels

from ..generation_lifecycle import (
    _next_generation_seed,
)
from ..models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from ..production_context import (
    _TERMINAL_PHASES,
)
from ..prompt_worksets import required_dialogue_prompt
from ..script_index import find_segment
from ..video_inputs import dialogue_audio_inputs, resolve_video_inputs
from .support import _commit_submission


def _segment_video_context(owner, document, segment_id: str, expected_revision: int, seed):
    if document.revision != expected_revision:
        raise ValueError("项目已被更新，请重新读取后再生成视频。")
    if not document.is_reviewing or not document.workspace_layers.videos_unlocked:
        raise ValueError("当前不在视频生产阶段。")
    script = document.director_script
    keyframe_plan = document.keyframe_plan
    video_plan = document.video_plan
    if script is None or keyframe_plan is None or video_plan is None:
        raise ValueError("视频生产输入不完整。")
    if script.production_baseline_revision != script.revision:
        raise ValueError("当前 Shot timing 已失效；请先确认时序再生成视频。")
    found = find_segment(script.scenes, segment_id)
    if found is None:
        raise ValueError("Segment 不存在。")
    segment = found[1]
    inputs = resolve_video_inputs(document, segment_id)
    if any(
        item.kind is ReferenceGenerationKind.SEGMENT_VIDEO
        and item.target_id == segment_id
        and item.phase not in _TERMINAL_PHASES
        for item in document.generations
    ):
        raise ValueError("该 Segment 已有进行中的视频任务。")
    plan_item = next(item for item in video_plan.segments if item.segment_id == segment_id)
    if plan_item.active_recipe is None:
        raise ValueError("请先选择视频 recipe。")
    if not plan_item.prompt_text.strip():
        raise ValueError("请先填写并保存当前视频提示词，或显式优化提示词。")
    duration = segment.duration_estimate_seconds
    # 时长没有上限：超过 Agent 侧 15 秒软约束可能 OOM，但是否尝试由用户决定。
    if duration < 0.2:
        raise ValueError("Segment 时长不能短于 0.2 秒；请先调整结构化脚本。")
    if seed is None:
        has_previous_seed = any(
            item.kind is ReferenceGenerationKind.SEGMENT_VIDEO
            and item.target_id == segment.id
            and item.seed is not None
            for item in document.generations
        )
        seed = _next_generation_seed(
            document,
            ReferenceGenerationKind.SEGMENT_VIDEO,
            segment.id,
            0 if has_previous_seed else int(segment.id[:16], 16) % (2**63),
        )
    return inputs, plan_item, segment, duration, seed


def _segment_video_submission(owner, document, context):
    inputs, plan_item, segment, duration, seed = context
    start, end = inputs.start_asset_id, inputs.end_asset_id
    first = owner._store.read_asset(start) if start is not None else None
    last = owner._store.read_asset(end) if end is not None else None
    prepared = owner._registry.prepare_recipe(
        Capability.VIDEO_GENERATE, recipe_id=plan_item.active_recipe
    )
    dialogue = dialogue_audio_inputs(document, segment.id)
    audio_slot = next(
        (slot for slot in prepared.recipe.slots if slot.role is Role.REFERENCE_AUDIO), None
    )
    if dialogue and audio_slot is None:
        raise ValueError("含对白的 Segment 必须使用支持参考音频的 Ref2VA recipe。")
    bindings = dict(plan_item.recipe_inputs.bindings)
    if audio_slot is not None and dialogue:
        if len(dialogue) > audio_slot.maximum:
            raise ValueError(
                f"该 Segment 有 {len(dialogue)} 句对白，超过 Ref2VA 的 "
                f"{audio_slot.maximum} 条音频上限；请先拆分 Segment。"
            )
        system = tuple(
            SlotBinding(
                asset.id,
                _dialogue_description(document, line, item.start_seconds),
            )
            for line, item, asset in dialogue
        )
        manual = bindings.get(audio_slot.key, ())
        if len(system) + len(manual) > audio_slot.maximum:
            raise ValueError("对白系统音频与手工参考音频合计超过当前 recipe 上限。")
        bindings[audio_slot.key] = (*system, *manual)
    labels = binding_labels(prepared.recipe, bindings)
    instruction = required_dialogue_prompt(labels, segment.dialogue_lines)
    effective_prompt = (
        plan_item.prompt_text
        if instruction is None
        else f"{instruction}\n\n{plan_item.prompt_text}"
    )
    inputs_by_slot = {}
    for slot in prepared.recipe.slots:
        automatic = (
            first
            if slot.role is Role.FIRST_FRAME
            else last
            if slot.role is Role.LAST_FRAME
            else None
        )
        if slot.role in {Role.FIRST_FRAME, Role.LAST_FRAME}:
            inputs_by_slot[slot.key] = (
                () if automatic is None else (MediaInput(automatic[0].media_type, automatic[1]),)
            )
        else:
            values = []
            for binding in bindings.get(slot.key, ()):
                asset, content = owner._store.read_asset(binding.asset_id)
                values.append(
                    MediaInput(
                        asset.media_type, content, binding.description, asset.duration_seconds
                    )
                )
            inputs_by_slot[slot.key] = tuple(values)
    request, submitted = prepared.request(
        roles={
            Role.PROMPT: effective_prompt,
            Role.DURATION: duration,
            Role.SEED: seed,
            Role.ASPECT_RATIO: document.aspect_ratio.value,
        },
        mechanism=plan_item.recipe_inputs.to_json()["params"],
        slot_inputs=inputs_by_slot,
    )
    asset_ids = []
    for slot in prepared.recipe.slots:
        if slot.role is Role.FIRST_FRAME:
            asset_ids.extend(() if start is None else (start,))
        elif slot.role is Role.LAST_FRAME:
            asset_ids.extend(() if end is None else (end,))
        else:
            asset_ids.extend(item.asset_id for item in bindings.get(slot.key, ()))
    input_asset_ids = tuple(dict.fromkeys(asset_ids))
    generation = ReferenceGeneration(
        id=uuid4().hex,
        kind=ReferenceGenerationKind.SEGMENT_VIDEO,
        operation=GenerationOperation.RENDER,
        target_id=plan_item.segment_id,
        phase=ReferenceGenerationPhase.SUBMITTING,
        progress=0.0,
        message="正在提交 Segment 视频任务。",
        video_input_snapshot=inputs.snapshot,
        provider_snapshot=prepared.snapshot,
        recipe_params=RecipeParams.from_json({prepared.recipe.id: submitted}),
        prompt_text=effective_prompt,
        input_asset_ids=input_asset_ids,
        sample_text=None,
        seed=seed,
        plugin_id=None,
        plugin_version=None,
        external_id=None,
        output_asset_id=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=duration,
    )
    return request, prepared, generation


def _dialogue_description(document, line, start_seconds):
    characters = {item.id: item.name for item in document.reference_library.characters}
    speaker = line.speaker_label or characters.get(line.character_id, line.character_id)
    assert start_seconds is not None
    return f"{speaker} 的对白，{start_seconds:.3f}s 开始。原始内容：{line.text}"


class VideoSubmission:
    async def generate_segment_video(
        self,
        *,
        segment_id: str,
        expected_revision: int,
        seed: int | None = None,
        _retry_of: ReferenceGeneration | None = None,
    ) -> StructuredDirectorDocument:
        if seed is not None and (
            isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1
        ):
            raise ValueError("视频 Seed 必须是 0 到 9223372036854775807 的整数。")
        async with self._lock:
            document = self._store.read()
            context = _segment_video_context(self, document, segment_id, expected_revision, seed)
            request, prepared, generation = _segment_video_submission(self, document, context)
            return await _commit_submission(
                self,
                document,
                generation,
                expected_revision=document.revision,
                submit=lambda: prepared.submit(request),
                capability="Segment 视频",
                queued_message="Segment 视频任务已提交。",
                retry_of=_retry_of,
            )
