"""旁白域 mutations：纯函数化的"改 document + 失效"逻辑（P2-C2）。

从 store 旁白方法原样抽取：每个函数接收权威 document，执行校验与对象变换，
返回变更后的 document（或 NarrationCommandResult 携带完整回执）。
不做任何文件 I/O；revision CAS 与 _atomic_write 由 store pipeline 负责。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.director_commands import (
    CommandReceipt,
    NarrationCueUpdate,
    NarrationSelectionClear,
)
from core.director_proposals import NarrationReviewProposal
from core.model_providers.recipe import RecipeParams

from ..models import (
    DirectorRunKind,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    PendingNarrationEdit,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
)
from ..repair_mutations import _repair_invalidated_items
from ..run_state import _active_run_is, _start_director_run
from ..script_mutations import (
    _finish_director_run,
    _invalidate_production_after_script_revision,
)
from ..v32_projection import require_v32_cue_anchors, v32_cue_anchors


@dataclass(frozen=True, slots=True)
class NarrationCommandResult:
    """update/clear 一类命令式旁白操作的 L2 结果：document + 完整回执。"""

    document: StructuredDirectorDocument
    receipt: CommandReceipt
    write: bool


def merge_recipe_params(current: RecipeParams, updates: RecipeParams) -> RecipeParams:
    """逐 recipe 覆盖：只替换给出的 recipe，其它 recipe 的参数保留。"""
    merged = current
    for recipe_id in (entry for entry, _params in updates.entries):
        params = updates.get(recipe_id)
        assert params is not None
        merged = merged.with_entry(recipe_id, params)
    return merged


def _preserve_unchanged_selections(current: NarrationCue, candidate: NarrationCue) -> NarrationCue:
    """内容未变化的语言保留原音频选择。"""
    result = candidate
    for language, track in candidate.tracks:
        previous = current.track(language)
        kept = (
            previous.selected_audio_asset_id
            if replace(previous, selected_audio_asset_id=None)
            == replace(track, selected_audio_asset_id=None)
            else None
        )
        result = result.with_track(language, replace(track, selected_audio_asset_id=kept))
    return result


def save_narration_cue(
    document: StructuredDirectorDocument, scene_id: str, cue: NarrationCue
) -> StructuredDirectorDocument:
    """保存单条旁白 Cue；语义未变化的字段保留原音频选择。"""
    if (
        document.status
        not in {
            StructuredDirectorStatus.REVIEWING_SCRIPT,
            StructuredDirectorStatus.REVIEWING_NARRATION,
            StructuredDirectorStatus.REVIEWING_KEYFRAMES,
            StructuredDirectorStatus.REVIEWING_VIDEOS,
            StructuredDirectorStatus.REVIEWING_FINAL,
        }
        or document.director_script is None
    ):
        raise ValueError("当前不能修改旁白。")
    scenes: list[Scene] = []
    found = False
    for scene in document.director_script.scenes:
        if scene.id != scene_id:
            scenes.append(scene)
            continue
        current = next((item for item in scene.narration_cues if item.id == cue.id), None)
        if current is None:
            raise ValueError("旁白 Cue 不存在。")
        candidate = _preserve_unchanged_selections(current, cue)
        cues = tuple(candidate if item.id == cue.id else item for item in scene.narration_cues)
        scenes.append(replace(scene, narration_cues=cues))
        found = True
    if not found:
        raise ValueError("Scene 不存在。")
    script = replace(
        document.director_script,
        revision=document.director_script.revision + 1,
        scenes=tuple(scenes),
        production_baseline_revision=None,
        production_baseline_scenes=None,
    )
    return _invalidate_production_after_script_revision(document, script.scenes)


def update_narration_cue(
    document: StructuredDirectorDocument, update: NarrationCueUpdate, command_id: str
) -> NarrationCommandResult:
    """按 scope 精确更新 Cue 字段；内容未变化时保留选择并返回 noop。"""
    script = document.director_script
    if script is None:
        raise ValueError("结构化导演脚本尚未建立。")
    scene_ids = {scene.id for scene in script.scenes}
    if not set(update.scope_scene_ids) <= scene_ids:
        raise ValueError("narration scope 包含不存在的 Scene。")
    containing = tuple(
        (scene, cue)
        for scene in script.scenes
        for cue in scene.narration_cues
        if cue.id == update.cue_id
    )
    if len(containing) != 1:
        raise ValueError("旁白 Cue 不存在或不唯一。")
    target_scene, current = containing[0]
    if target_scene.id not in update.scope_scene_ids:
        raise ValueError("旁白 update 超出已授权 Scene scope。")
    fields = dict(update.fields)
    require_v32_cue_anchors(
        [shot.id for shot in target_scene.shots],
        fields.pop("start_shot_id", v32_cue_anchors(target_scene)[0]),
        fields.pop("end_shot_id", v32_cue_anchors(target_scene)[1]),
    )
    candidate = replace(current, **fields)
    for key, changes in update.track_fields.items():
        language = NarrationLanguage(key)
        track = candidate.track(language)
        changes = dict(changes)
        if "recipe_params" in changes:
            changes["recipe_params"] = merge_recipe_params(
                track.recipe_params, changes["recipe_params"]
            )
        candidate = candidate.with_track(language, replace(track, **changes))
    candidate = _preserve_unchanged_selections(current, candidate)
    if candidate == current:
        return NarrationCommandResult(
            document,
            CommandReceipt(
                command_id=command_id,
                status="noop",
                old_revision=document.revision,
                new_revision=document.revision,
                preserved=("narration_selection",),
                decision_summary="旁白 Cue 已满足目标字段，没有重复写入或清除选择。",
                next_allowed_actions=("narration.generate",),
            ),
            write=False,
        )
    scenes = tuple(
        replace(
            scene,
            narration_cues=tuple(
                candidate if cue.id == update.cue_id else cue for cue in scene.narration_cues
            ),
        )
        if scene.id == target_scene.id
        else scene
        for scene in script.scenes
    )
    updated = _invalidate_production_after_script_revision(document, scenes)
    invalidated = _repair_invalidated_items(document, updated)
    return NarrationCommandResult(
        updated,
        CommandReceipt(
            command_id=command_id,
            status="succeeded",
            old_revision=document.revision,
            new_revision=updated.revision,
            changed_ids=(target_scene.id, current.id),
            invalidated=invalidated,
            preserved=("asset_history", "generation_history"),
            decision_summary="已保存旁白 Cue 精确字段；旧候选选择按内容变化失效。",
            applied_summary={
                "fields": len(update.fields)
                + sum(len(changes) for changes in update.track_fields.values())
            },
            next_allowed_actions=("narration.generate",),
        ),
        write=True,
    )


def clear_narration_selection(
    document: StructuredDirectorDocument, clear: NarrationSelectionClear, command_id: str
) -> NarrationCommandResult:
    """清除 Cue 当前音频选择；无选择时返回 noop。"""
    script = document.director_script
    if script is None:
        raise ValueError("结构化导演脚本尚未建立。")
    scene_ids = {scene.id for scene in script.scenes}
    if not set(clear.scope_scene_ids) <= scene_ids:
        raise ValueError("narration scope 包含不存在的 Scene。")
    containing = tuple(
        (scene, cue)
        for scene in script.scenes
        for cue in scene.narration_cues
        if cue.id == clear.cue_id
    )
    if len(containing) != 1:
        raise ValueError("旁白 Cue 不存在或不唯一。")
    target_scene, current = containing[0]
    if target_scene.id not in clear.scope_scene_ids:
        raise ValueError("旁白 clear 超出已授权 Scene scope。")
    language = NarrationLanguage(clear.language)
    if current.track(language).selected_audio_asset_id is None:
        return NarrationCommandResult(
            document,
            CommandReceipt(
                command_id=command_id,
                status="noop",
                old_revision=document.revision,
                new_revision=document.revision,
                decision_summary="旁白 Cue 该语言当前没有音频选择。",
                next_allowed_actions=("narration.generate",),
            ),
            write=False,
        )
    scenes = tuple(
        replace(
            scene,
            narration_cues=tuple(
                cue.with_track(language, replace(cue.track(language), selected_audio_asset_id=None))
                if cue.id == clear.cue_id
                else cue
                for cue in scene.narration_cues
            ),
        )
        if scene.id == target_scene.id
        else scene
        for scene in script.scenes
    )
    updated = _invalidate_production_after_script_revision(document, scenes)
    invalidated = _repair_invalidated_items(document, updated)
    return NarrationCommandResult(
        updated,
        CommandReceipt(
            command_id=command_id,
            status="succeeded",
            old_revision=document.revision,
            new_revision=updated.revision,
            changed_ids=(target_scene.id, current.id),
            invalidated=invalidated,
            preserved=("asset_history", "generation_history"),
            decision_summary="已清除旁白该语言的当前音频选择，历史候选仍保留。",
            next_allowed_actions=("narration.generate",),
        ),
        write=True,
    )


def select_narration_audio(
    document: StructuredDirectorDocument, *, cue_id: str, generation_id: str
) -> StructuredDirectorDocument:
    """为 Cue 选择真实 TTS 音频，并按真实合成参数回写 Cue。"""
    if (
        not document.is_reviewing
        or not document.workspace_layers.narration_unlocked
        or document.director_script is None
    ):
        raise ValueError("当前不能选择旁白音频。")
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if (
        generation is None
        or generation.kind is not ReferenceGenerationKind.NARRATION_AUDIO
        or generation.target_id != cue_id
        or generation.phase is not ReferenceGenerationPhase.SUCCEEDED
        or generation.output_asset_id is None
        or generation.dismissed
        or generation.language is None
    ):
        raise ValueError("旁白候选不存在或尚未完成。")
    language = generation.language
    current_cue = next(
        (
            cue
            for scene in document.director_script.scenes
            for cue in scene.narration_cues
            if cue.id == cue_id
        ),
        None,
    )
    if current_cue is None:
        raise ValueError("旁白 Cue 不存在。")
    if generation.prompt_text != current_cue.track(language).text:
        raise ValueError("该候选对应的是旧版旁白正文，不能用于当前 Cue。")
    scenes: list[Scene] = []
    found = False
    for scene in document.director_script.scenes:
        cues = tuple(
            cue.with_track(
                language,
                replace(
                    cue.track(language),
                    seed=generation.seed,
                    selected_audio_asset_id=generation.output_asset_id,
                ),
            )
            if cue.id == cue_id
            else cue
            for cue in scene.narration_cues
        )
        if cues != scene.narration_cues:
            found = True
        scenes.append(replace(scene, narration_cues=cues))
    if not found:
        raise ValueError("旁白 Cue 不存在。")
    return _invalidate_production_after_script_revision(document, tuple(scenes))


def begin_narration_edit(
    document: StructuredDirectorDocument, message: str | None
) -> tuple[StructuredDirectorDocument, bool]:
    """开启旁白 Agent 编辑 run；同类型 run 已在进行时返回 (document, True)。"""
    active = document.active_director_run
    if active is not None:
        if active.kind is not DirectorRunKind.NARRATION_EDIT:
            raise ValueError("另一个 Director Agent 任务正在执行。")
        return document, True
    if (
        not document.is_reviewing
        or not document.workspace_layers.narration_unlocked
        or document.director_script is None
        or message is None
    ):
        raise ValueError("当前不能请求旁白 Agent。")
    started = _start_director_run(
        document,
        DirectorRunKind.NARRATION_EDIT,
        goal=message.strip(),
        raw_user_request=message.strip(),
    )
    updated = replace(
        document,
        revision=document.revision + 1,
        pending_narration_edit=PendingNarrationEdit(
            document.director_script.revision, message.strip()
        ),
        director_runs=started.runs,
        director_directives=started.directives,
    )
    return updated, False


def apply_narration_review_proposal(
    document: StructuredDirectorDocument, proposal: NarrationReviewProposal
) -> StructuredDirectorDocument:
    """保存旁白 Agent proposal；参数变化的 Cue 清除音频选择。"""
    if (
        not _active_run_is(document, DirectorRunKind.NARRATION_EDIT)
        or document.pending_narration_edit is None
        or document.director_script is None
    ):
        raise ValueError("当前没有等待保存的旁白 Agent proposal。")
    updates = {(item.cue_id, item.language): item for item in proposal.cue_updates}
    existing_ids = {
        cue.id for scene in document.director_script.scenes for cue in scene.narration_cues
    }
    if not {cue_id for cue_id, _ in updates}.issubset(existing_ids):
        raise ValueError("旁白 Agent 引用了不存在的 Cue。")

    def apply(cue: NarrationCue) -> NarrationCue:
        for language, track in cue.tracks:
            update = updates.get((cue.id, language.value))
            if update is None:
                continue
            recipe_params = merge_recipe_params(
                track.recipe_params, RecipeParams.from_json(update.recipe_params)
            )
            unchanged = track.seed == update.seed and track.recipe_params == recipe_params
            cue = cue.with_track(
                language,
                NarrationTrack(
                    text=track.text,
                    seed=update.seed,
                    recipe_params=recipe_params,
                    selected_audio_asset_id=track.selected_audio_asset_id if unchanged else None,
                ),
            )
        return cue

    scenes = tuple(
        replace(scene, narration_cues=tuple(apply(cue) for cue in scene.narration_cues))
        for scene in document.director_script.scenes
    )
    script = replace(
        document.director_script,
        revision=document.director_script.revision + (scenes != document.director_script.scenes),
        scenes=scenes,
    )
    updated = _invalidate_production_after_script_revision(document, script.scenes)
    return replace(
        updated,
        director_runs=_finish_director_run(document, DirectorRunKind.NARRATION_EDIT),
    )
