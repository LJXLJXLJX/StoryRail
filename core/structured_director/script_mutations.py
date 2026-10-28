from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.director_commands import (
    ScriptBoundaryInput,
    ScriptDialogueInput,
    ScriptOperationsPatch,
    ScriptSceneInput,
    ScriptSegmentInput,
    ScriptShotInput,
)
from core.director_proposals import (
    EditableSceneProposal,
    ScriptRevisionOperationProposal,
    StructuredDirectorScriptProposal,
)
from core.model_providers.recipe import RecipeParams

from .models import (
    DialogueAudio,
    DialogueLine,
    DialoguePlan,
    DirectorRun,
    DirectorRunKind,
    DirectorRunStatus,
    DirectorScript,
    Keyframe,
    KeyframePlan,
    NarrationCue,
    NarrationTrack,
    ReferenceLibrary,
    Scene,
    SegmentBoundary,
    SegmentBoundaryReason,
    SegmentKeyframes,
    SegmentVideo,
    Shot,
    ShotSegment,
    StructuredDirectorDocument,
    VideoPlan,
    blank_keyframe,
)
from .narration_timing import conform_production_scenes
from .script_index import (
    scene_segments,
    script_segments,
    segment_shots,
)


def _finish_director_run(
    document: StructuredDirectorDocument, kind: DirectorRunKind, *, failed: bool = False
) -> tuple[DirectorRun, ...]:
    active = document.active_director_run
    if active is None or active.kind is not kind:
        raise ValueError("当前没有匹配的 Director Agent 任务。")
    now = datetime.now(UTC).isoformat()
    return tuple(
        replace(
            item,
            status=DirectorRunStatus.FAILED if failed else DirectorRunStatus.COMPLETED,
            waiting_reason=None,
            last_project_revision=document.revision + 1,
            updated_at=now,
        )
        if item.id == active.id
        else item
        for item in document.director_runs
    )


def _materialize_track(track) -> NarrationTrack | None:
    if track is None:
        return None
    recipe_params = track.recipe_params
    return NarrationTrack(
        text=track.text.strip(),
        seed=track.seed,
        recipe_params=(
            recipe_params
            if isinstance(recipe_params, RecipeParams)
            else RecipeParams.from_json(recipe_params)
        ),
    )


def _materialize_script(
    proposal: StructuredDirectorScriptProposal,
    *,
    source_reference_revision: int,
) -> DirectorScript:
    def new_dialogue_id(value: str | None) -> str:
        if value is not None:
            raise ValueError("初始脚本 proposal 的 dialogue_line.id 必须为空，由 Core 分配。")
        return uuid4().hex

    scenes: list[Scene] = []
    for scene in proposal.scenes:
        if scene.driver == "narration" and (scene.shots or scene.segments):
            raise ValueError("Narration Scene 初稿只提交旁白；TTS 审核后再规划 Shot。")
        shot_values, segments = _materialize_scene_parts(
            scene.title.strip(),
            scene.shots,
            scene.segments,
            shot_id=lambda _shot: uuid4().hex,
            dialogue_id=new_dialogue_id,
        )
        cues = []
        for cue in scene.narration_cues:
            cues.append(
                NarrationCue(
                    id=uuid4().hex,
                    zh=_materialize_track(cue.zh),
                    en=_materialize_track(cue.en),
                )
            )
        scenes.append(
            Scene(
                id=uuid4().hex,
                title=scene.title.strip(),
                summary=scene.summary.strip(),
                setting=scene.setting.strip(),
                driver=scene.driver,
                shots=shot_values,
                segments=segments,
                narration_cues=tuple(cues),
            )
        )
    return DirectorScript(
        revision=1,
        source_reference_revision=source_reference_revision,
        production_baseline_revision=None,
        production_baseline_scenes=None,
        scenes=tuple(scenes),
    )


def _materialize_script_revision(
    proposals: tuple[EditableSceneProposal, ...],
    previous: tuple[Scene, ...],
) -> tuple[Scene, ...]:
    known_scene_ids = {scene.id for scene in previous}
    known_shot_ids = {shot.id for scene in previous for shot in scene.shots}
    known_segment_ids = {segment.id for segment in script_segments(previous)}
    known_cue_ids = {cue.id for scene in previous for cue in scene.narration_cues}
    known_dialogue_ids = {
        line.id
        for scene in previous
        for segment in scene.segments
        for line in segment.dialogue_lines
        if line.id is not None
    }
    all_known_ids = (
        known_scene_ids | known_shot_ids | known_segment_ids | known_cue_ids | known_dialogue_ids
    )
    previous_cues = {cue.id: cue for scene in previous for cue in scene.narration_cues}

    def resolved(value: str | None, expected: set[str], label: str) -> str:
        if value is None:
            candidate = uuid4().hex
            while candidate in all_known_ids:
                candidate = uuid4().hex
            all_known_ids.add(candidate)
            return candidate
        if value not in expected:
            raise ValueError(f"{label} 不是当前脚本中同类型的已有 ID。")
        return value

    scenes: list[Scene] = []
    for scene in proposals:
        shot_values, segments = _materialize_scene_parts(
            scene.title.strip(),
            scene.shots,
            scene.segments,
            shot_id=lambda shot: resolved(shot.id, known_shot_ids, "shot.id"),
            segment_id=lambda value: resolved(value, known_segment_ids, "segment.id"),
            dialogue_id=lambda value: resolved(value, known_dialogue_ids, "dialogue_line.id"),
        )
        cues: list[NarrationCue] = []
        for cue in scene.narration_cues:
            cue_id = resolved(cue.id, known_cue_ids, "narration_cue.id")
            previous_cue = previous_cues.get(cue_id)
            candidate = NarrationCue(
                id=cue_id,
                zh=_materialize_track(cue.zh),
                en=_materialize_track(cue.en),
            )
            if previous_cue is not None:
                # 每种语言只要正文与合成参数不变就保留已选音频。
                for language, track in candidate.tracks:
                    previous_track = previous_cue.track(language)
                    if replace(previous_track, selected_audio_asset_id=None) == track:
                        candidate = candidate.with_track(language, previous_track)
            cues.append(candidate)
        scene_id = resolved(scene.id, known_scene_ids, "scene.id")
        previous_scene = next((x for x in previous if x.id == scene_id), None)
        location_id = None if previous_scene is None else previous_scene.location_id
        scenes.append(
            Scene(
                id=scene_id,
                location_id=location_id,
                state_id=None if previous_scene is None else previous_scene.state_id,
                title=scene.title.strip(),
                summary=scene.summary.strip(),
                setting=scene.setting.strip(),
                driver=scene.driver,
                shots=shot_values,
                segments=segments,
                narration_cues=tuple(cues),
            )
        )
    return tuple(scenes)


def _apply_script_scene_operations(
    operations: tuple[ScriptRevisionOperationProposal, ...],
    previous: tuple[Scene, ...],
    *,
    target_scene_ids: tuple[str, ...] = (),
) -> tuple[Scene, ...]:
    """按顺序应用显式 Scene 操作；未触及 Scene 原样保留。"""
    if len(target_scene_ids) != len(set(target_scene_ids)):
        raise ValueError("局部脚本修改目标不能重复。")
    known_ids = {scene.id for scene in previous}
    if not set(target_scene_ids) <= known_ids:
        raise ValueError("局部脚本修改包含不存在的目标 Scene。")
    touched: set[str] = set()
    scenes = list(previous)
    last_inserted_after: dict[str | None, str] = {}

    def locate(scene_id: str) -> int:
        for index, scene in enumerate(scenes):
            if scene.id == scene_id:
                return index
        raise ValueError("脚本操作引用了不存在或已经删除的 Scene。")

    def insertion_index(after_scene_id: str | None) -> int:
        effective_anchor = last_inserted_after.get(after_scene_id, after_scene_id)
        return 0 if effective_anchor is None else locate(effective_anchor) + 1

    for operation in operations:
        scene_id = operation.scene_id
        if target_scene_ids and (
            operation.operation not in {"replace_scene", "replace_segment"}
            or scene_id not in target_scene_ids
        ):
            raise ValueError("Agent 必须且只能返回指定目标 Scene 的替换操作。")
        touch_id = (
            operation.segment.id
            if operation.operation == "replace_segment" and operation.segment is not None
            else scene_id
        )
        if touch_id is not None:
            if touch_id in touched:
                raise ValueError("同一脚本节点不能在一个 proposal 中重复操作。")
            touched.add(touch_id)
        if operation.operation == "replace_scene":
            assert scene_id is not None and operation.scene is not None
            _validate_scene_revision_scope((operation.scene,), previous, (scene_id,))
            scenes[locate(scene_id)] = _materialize_script_revision((operation.scene,), previous)[0]
        elif operation.operation == "insert_scene":
            assert operation.scene is not None
            _validate_new_scene_ids(operation.scene)
            materialized = _materialize_script_revision((operation.scene,), previous)[0]
            scenes.insert(insertion_index(operation.after_scene_id), materialized)
            last_inserted_after[operation.after_scene_id] = materialized.id
        elif operation.operation == "delete_scene":
            assert scene_id is not None
            scenes.pop(locate(scene_id))
        elif operation.operation == "move_scene":
            assert scene_id is not None
            scene = scenes.pop(locate(scene_id))
            scenes.insert(insertion_index(operation.after_scene_id), scene)
        else:
            assert (
                operation.operation == "replace_segment"
                and scene_id is not None
                and operation.segment is not None
                and operation.segment.id is not None
            )
            scene_index = locate(scene_id)
            scene = scenes[scene_index]
            replacement = operation.segment
            if all(segment.id != replacement.id for segment in scene.segments):
                raise ValueError("replace_segment 的 Segment 不属于指定 Scene。")
            indexes = _coverage_indexes(scene, replacement)
            resolved = _resolve_shot_indexes(
                scene_label=f"Scene「{scene.title}」",
                shot_ids=tuple(shot.id for shot in scene.shots),
                segment_indexes=indexes,
                has_boundary=tuple(
                    (
                        replacement.boundary_from_previous is not None
                        if segment.id == replacement.id
                        else segment.boundary_from_previous is not None
                    )
                    for segment in scene.segments
                ),
            )
            segments = tuple(
                _materialize_segment(replacement, segment.id, shot_ids)
                if segment.id == replacement.id
                else replace(segment, shot_ids=shot_ids)
                for segment, shot_ids in zip(scene.segments, resolved, strict=True)
            )
            scenes[scene_index] = replace(scene, segments=segments)
    if not scenes:
        raise ValueError("结构化导演脚本至少需要一个 Scene。")
    return tuple(scenes)


def _validate_new_scene_ids(scene: EditableSceneProposal) -> None:
    if scene.id is not None:
        raise ValueError("新增 Scene 的 ID 必须为 null。")
    if any(shot.id is not None for shot in scene.shots):
        raise ValueError("新增 Scene 的 Shot ID 必须为 null。")
    if any(segment.id is not None for segment in scene.segments):
        raise ValueError("新增 Scene 的 Segment ID 必须为 null。")
    if any(line.id is not None for segment in scene.segments for line in segment.dialogue_lines):
        raise ValueError("新增 Scene 的 DialogueLine ID 必须为 null。")
    if any(cue.id is not None for cue in scene.narration_cues):
        raise ValueError("新增 Scene 的旁白 Cue ID 必须为 null。")


def _coverage_indexes(scene: Any, replacement: Any) -> tuple[tuple[int, ...], ...]:
    """replace_segment 里被替换的 Segment 用新的 shot_indexes，其余沿用现状。"""
    positions = {shot.id: index for index, shot in enumerate(scene.shots)}
    return tuple(
        replacement.shot_indexes
        if segment.id == replacement.id
        else tuple(positions[shot_id] for shot_id in segment.shot_ids)
        for segment in scene.segments
    )


def _materialize_segment(segment: Any, segment_id: str, shot_ids: tuple[str, ...]) -> ShotSegment:
    return ShotSegment(
        id=segment_id,
        shot_ids=shot_ids,
        duration_estimate_seconds=segment.duration_estimate_seconds,
        action=segment.action.strip(),
        dialogue_lines=tuple(_dialogue_line(line) for line in segment.dialogue_lines),
        boundary_from_previous=(
            None
            if segment.boundary_from_previous is None
            else SegmentBoundary(
                SegmentBoundaryReason(segment.boundary_from_previous.reason),
                segment.boundary_from_previous.continuity_instruction.strip(),
            )
        ),
    )


def _validate_scene_revision_scope(
    proposals: tuple[EditableSceneProposal, ...],
    previous: tuple[Scene, ...],
    target_scene_ids: tuple[str, ...],
) -> None:
    if not target_scene_ids or len(target_scene_ids) != len(set(target_scene_ids)):
        raise ValueError("生产期局部脚本修改必须指定不重复的目标 Scene。")
    previous_by_id = {scene.id: scene for scene in previous}
    if not set(target_scene_ids) <= previous_by_id.keys():
        raise ValueError("生产期局部脚本修改包含不存在的目标 Scene。")
    proposal_ids = tuple(scene.id for scene in proposals)
    if any(scene_id is None for scene_id in proposal_ids) or set(proposal_ids) != set(
        target_scene_ids
    ):
        raise ValueError("Agent 必须且只能返回指定的现有 Scene。")

    for proposal in proposals:
        assert proposal.id is not None
        current = previous_by_id[proposal.id]
        shot_ids = {shot.id for shot in current.shots}
        segment_ids = {segment.id for segment in scene_segments(current)}
        cue_ids = {cue.id for cue in current.narration_cues}
        dialogue_ids = {
            line.id
            for segment in current.segments
            for line in segment.dialogue_lines
            if line.id is not None
        }
        if any(shot.id is not None and shot.id not in shot_ids for shot in proposal.shots):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的 Shot ID。")
        if any(
            segment.id is not None and segment.id not in segment_ids
            for segment in proposal.segments
        ):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的 Segment ID。")
        if any(cue.id is not None and cue.id not in cue_ids for cue in proposal.narration_cues):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的旁白 Cue ID。")
        if any(
            line.id is not None and line.id not in dialogue_ids
            for segment in proposal.segments
            for line in segment.dialogue_lines
        ):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的 DialogueLine ID。")


def _with_production_baseline(
    document: StructuredDirectorDocument, script: DirectorScript
) -> DirectorScript:
    """旁白层解锁后由 Core 按真实音频校准并写入生产基线；无法校准时基线保持失效。"""
    if not document.workspace_layers.narration_unlocked:
        return script
    try:
        scenes = conform_production_scenes(
            script.scenes,
            {asset.id: asset for asset in document.assets},
            narrator_ready=document.reference_library.narrator is not None,
        )
    except ValueError:
        return script
    return replace(
        script,
        scenes=scenes,
        production_baseline_revision=script.revision,
        production_baseline_scenes=scenes,
    )


def _invalidate_production_after_script_revision(
    document: StructuredDirectorDocument,
    scenes: tuple[Scene, ...],
    *,
    dialogue_plan_override: DialoguePlan | None = None,
) -> StructuredDirectorDocument:
    if document.director_script is None:
        raise ValueError("生产期脚本不存在。")
    previous_scenes = {scene.id: scene for scene in document.director_script.scenes}
    for scene in scenes:
        previous = previous_scenes.get(scene.id)
        if (
            scene.driver == "narration"
            and scene.shots
            and (
                previous is None
                or previous.driver != "narration"
                or (previous.shots, previous.segments) != (scene.shots, scene.segments)
            )
            and not all(cue.fully_selected for cue in scene.narration_cues)
        ):
            raise ValueError(
                "Narration Scene 必须先选择项目所选语言的 TTS 音频及真实时长，"
                "再规划 Shot / Segment。"
            )
    script = _with_production_baseline(
        document,
        replace(
            document.director_script,
            revision=document.director_script.revision + 1,
            scenes=scenes,
        ),
    )
    video_plan = _rebase_video_plan(
        document.video_plan,
        source_script_revision=script.revision,
        previous_scenes=document.director_script.scenes,
        scenes=script.scenes,
    )
    keyframe_plan = _rebase_keyframe_plan(
        document.keyframe_plan,
        source_script_revision=script.revision,
        scenes=script.scenes,
    )
    dialogue_plan = _rebase_dialogue_plan(
        document.dialogue_plan if dialogue_plan_override is None else dialogue_plan_override,
        source_script_revision=script.revision,
        previous_scenes=document.director_script.scenes,
        scenes=script.scenes,
        clear_timing_for_changed_segments=dialogue_plan_override is None,
    )
    director_runs = document.director_runs
    active = document.active_director_run
    if active is not None and active.kind in {
        DirectorRunKind.SCRIPT_EDIT,
        DirectorRunKind.NARRATION_EDIT,
    }:
        director_runs = _finish_director_run(document, active.kind)
    return replace(
        document,
        revision=document.revision + 1,
        status=document.review_status,
        director_script=script,
        pending_script_edit=None,
        pending_narration_edit=None,
        dialogue_plan=dialogue_plan,
        keyframe_plan=keyframe_plan,
        video_plan=video_plan,
        final_assembly=None,
        director_runs=director_runs,
    )


def dialogue_plan_for_script(script: DirectorScript) -> DialoguePlan:
    """为首次物化的脚本建立逐句空 TTS 计划。"""
    return DialoguePlan(
        script.revision,
        tuple(
            DialogueAudio(line.id or "", _dialogue_seed(line))
            for scene in script.scenes
            for segment in scene.segments
            for line in segment.dialogue_lines
        ),
    )


def _dialogue_seed(line: DialogueLine) -> int:
    speaker = line.character_id or f"label:{line.speaker_label}"
    return int.from_bytes(hashlib.sha256(speaker.encode("utf-8")).digest()[:4], "big")


def _rebase_dialogue_plan(
    plan: DialoguePlan | None,
    *,
    source_script_revision: int,
    previous_scenes: tuple[Scene, ...],
    scenes: tuple[Scene, ...],
    clear_timing_for_changed_segments: bool = True,
) -> DialoguePlan:
    old_items = {} if plan is None else {item.dialogue_line_id: item for item in plan.items}
    old_lines = {
        line.id: (segment.id, line)
        for scene in previous_scenes
        for segment in scene.segments
        for line in segment.dialogue_lines
        if line.id is not None
    }
    previous_segments = {
        segment.id: segment for scene in previous_scenes for segment in scene.segments
    }
    changed_segments = {
        segment.id
        for scene in scenes
        for segment in scene.segments
        if (
            (old := previous_segments.get(segment.id)) is None
            or old.dialogue_lines != segment.dialogue_lines
            or old.duration_estimate_seconds != segment.duration_estimate_seconds
        )
    }
    items: list[DialogueAudio] = []
    for scene in scenes:
        for segment in scene.segments:
            for line in segment.dialogue_lines:
                assert line.id is not None
                old_item = old_items.get(line.id)
                old = old_lines.get(line.id)
                if old_item is None or old is None:
                    items.append(DialogueAudio(line.id, _dialogue_seed(line)))
                    continue
                old_segment_id, old_line = old
                if old_line != line:
                    items.append(
                        DialogueAudio(
                            line.id,
                            (
                                old_item.seed
                                if old_line.character_id == line.character_id
                                else _dialogue_seed(line)
                            ),
                            old_item.recipe_params,
                        )
                    )
                    continue
                items.append(
                    replace(
                        old_item,
                        start_seconds=(
                            None
                            if (
                                clear_timing_for_changed_segments and segment.id in changed_segments
                            )
                            or old_segment_id != segment.id
                            else old_item.start_seconds
                        ),
                    )
                )
    return DialoguePlan(source_script_revision, tuple(items))


def _assign_missing_dialogue_ids(scenes: tuple[Scene, ...]) -> tuple[Scene, ...]:
    """Core 为直接领域写入中新增的 DialogueLine 分配稳定 ID。"""
    used = {
        line.id
        for scene in scenes
        for segment in scene.segments
        for line in segment.dialogue_lines
        if line.id is not None
    }

    def fresh() -> str:
        value = uuid4().hex
        while value in used:
            value = uuid4().hex
        used.add(value)
        return value

    return tuple(
        replace(
            scene,
            segments=tuple(
                replace(
                    segment,
                    dialogue_lines=tuple(
                        line if line.id is not None else replace(line, id=fresh())
                        for line in segment.dialogue_lines
                    ),
                )
                for segment in scene.segments
            ),
        )
        for scene in scenes
    )


@dataclass(slots=True)
class _ScriptSegmentDraft:
    id: str
    shot_ids: tuple[str, ...]
    duration_estimate_seconds: float
    action: str
    dialogue_lines: tuple[DialogueLine, ...]
    boundary_from_previous: SegmentBoundary | None


@dataclass(slots=True)
class _ScriptShotDraft:
    id: str
    visible_character_ids: tuple[str, ...]
    composition: str
    camera_movement: str
    action: str
    audio_direction: str
    transition_in: str | None


@dataclass(slots=True)
class _ScriptSceneDraft:
    id: str
    title: str
    summary: str
    setting: str
    shots: list[_ScriptShotDraft]
    segments: list[_ScriptSegmentDraft]
    narration_cues: tuple[NarrationCue, ...]
    driver: str
    location_id: str | None
    state_id: str | None


def _validate_script_references(
    scenes: tuple[Scene, ...],
    library: ReferenceLibrary,
    *,
    previous_scenes: tuple[Scene, ...],
) -> None:
    character_ids = {item.id for item in library.characters}
    for scene in previous_scenes:
        for shot in scene.shots:
            character_ids.update(shot.visible_character_ids)
        for segment in scene.segments:
            character_ids.update(
                line.character_id
                for line in segment.dialogue_lines
                if line.character_id is not None
            )
    for scene in scenes:
        for shot in scene.shots:
            if any(item not in character_ids for item in shot.visible_character_ids):
                raise ValueError("Shot 引用了未声明的角色卡。")
        if any(
            line.character_id is not None and line.character_id not in character_ids
            for segment in scene.segments
            for line in segment.dialogue_lines
        ):
            raise ValueError("角色对白引用了未声明的角色卡。")


def _apply_script_operations(
    scenes: tuple[Scene, ...],
    patch: ScriptOperationsPatch,
    *,
    command_id: str,
) -> tuple[tuple[Scene, ...], set[str]]:
    drafts = [_script_scene_draft(scene) for scene in scenes]
    known_scene_ids = {scene.id for scene in drafts}
    if not set(patch.scope_scene_ids) <= known_scene_ids:
        raise ValueError("script scope 包含不存在的 Scene。")
    changed_ids: set[str] = set()
    # 本 patch 新建的 Scene 视为已授权，允许同一 patch 后续操作引用。
    created_scene_ids: set[str] = set()
    all_ids = {
        value
        for scene in drafts
        for value in (
            scene.id,
            *(shot.id for shot in scene.shots),
            *(segment.id for segment in scene.segments),
            *(
                line.id
                for segment in scene.segments
                for line in segment.dialogue_lines
                if line.id is not None
            ),
        )
    }

    def scoped(scene: _ScriptSceneDraft) -> None:
        if scene.id not in patch.scope_scene_ids and scene.id not in created_scene_ids:
            raise ValueError("script operation 超出已授权 Scene scope。")

    def find_scene(scene_id: str) -> _ScriptSceneDraft:
        scene = next((item for item in drafts if item.id == scene_id), None)
        if scene is None:
            raise ValueError("script operation 的 Scene 不存在。")
        scoped(scene)
        return scene

    def find_shot(shot_id: str) -> tuple[_ScriptSceneDraft, _ScriptShotDraft]:
        matches = [(scene, shot) for scene in drafts for shot in scene.shots if shot.id == shot_id]
        if len(matches) != 1:
            raise ValueError("script operation 的 Shot 不存在或不唯一。")
        scoped(matches[0][0])
        return matches[0]

    def find_segment(segment_id: str) -> tuple[_ScriptSceneDraft, _ScriptSegmentDraft]:
        matches = [
            (scene, segment)
            for scene in drafts
            for segment in scene.segments
            if segment.id == segment_id
        ]
        if len(matches) != 1:
            raise ValueError("script operation 的 Segment 不存在或不唯一。")
        scoped(matches[0][0])
        return matches[0]

    def scene_insertion_index(after_scene_id: str | None) -> int:
        if after_scene_id is None:
            return 0
        return drafts.index(find_scene(after_scene_id)) + 1

    def fresh_id(operation_index: int, label: str) -> str:
        candidate = hashlib.sha256(f"{command_id}:{operation_index}:{label}".encode()).hexdigest()[
            :32
        ]
        if candidate in all_ids:
            raise ValueError("script operation 派生 ID 与现有节点冲突。")
        all_ids.add(candidate)
        return candidate

    for operation_index, operation in enumerate(patch.operations):
        if operation.op == "update_scene_fields":
            assert operation.scene_id is not None and operation.fields is not None
            scene = find_scene(operation.scene_id)
            for name, value in operation.fields.items():
                setattr(scene, name, value)
            changed_ids.add(scene.id)
            continue
        if operation.op == "insert_scene":
            assert operation.scene is not None
            index = scene_insertion_index(operation.after_id)
            scene = _script_new_scene_draft(
                operation.scene,
                fresh_id=lambda label, current=operation_index: fresh_id(current, label),
            )
            drafts.insert(index, scene)
            created_scene_ids.add(scene.id)
            changed_ids.update(
                (
                    scene.id,
                    *(shot.id for shot in scene.shots),
                    *(segment.id for segment in scene.segments),
                    *(cue.id for cue in scene.narration_cues),
                )
            )
            continue
        if operation.op == "move_scene":
            assert operation.scene_id is not None
            scene = find_scene(operation.scene_id)
            if operation.after_id == scene.id:
                raise ValueError("Scene 不能移动到自身之后。")
            drafts.remove(scene)
            drafts.insert(scene_insertion_index(operation.after_id), scene)
            changed_ids.add(scene.id)
            continue
        if operation.op == "delete_scene":
            assert operation.scene_id is not None
            scene = find_scene(operation.scene_id)
            if any(
                track.selected_audio_asset_id is not None
                for cue in scene.narration_cues
                for _, track in cue.tracks
            ):
                raise ValueError("Scene 旁白已选择音频；请先解除旁白音频选择后再删除 Scene。")
            drafts.remove(scene)
            changed_ids.add(scene.id)
            continue
        if operation.op == "update_shot_fields":
            assert operation.shot_id is not None and operation.fields is not None
            scene, shot = find_shot(operation.shot_id)
            for name, value in operation.fields.items():
                setattr(shot, name, value)
            changed_ids.update((scene.id, shot.id))
            continue
        if operation.op == "insert_shot":
            assert operation.scene_id is not None and operation.shot is not None
            scene = find_scene(operation.scene_id)
            shot_id = fresh_id(operation_index, "shot")
            shot = _script_shot_draft(operation.shot, shot_id=shot_id)
            order_before = [item.id for item in scene.shots]
            _insert_after(scene.shots, shot, operation.after_id, "Shot")
            position = scene.shots.index(shot)
            if operation.attach_to_segment_id is not None:
                segment = next(
                    (item for item in scene.segments if item.id == operation.attach_to_segment_id),
                    None,
                )
                if segment is None:
                    raise ValueError("insert_shot 的 attach_to_segment_id 不属于指定 Scene。")
                first = order_before.index(segment.shot_ids[0])
                last = order_before.index(segment.shot_ids[-1])
                if position == first and segment.boundary_from_previous is not None:
                    raise ValueError(
                        "insert_shot 不能把新 Shot 插在 Segment 的共享边界 Shot 之前；"
                        "请改为 attach 到前一个 Segment。"
                    )
                if not first <= position <= last + 1:
                    raise ValueError(
                        "insert_shot 的插入位置不在 attach_to_segment_id 的覆盖区间内；"
                        "新 Shot 只能并入与之相邻的 Segment。"
                    )
                segment.shot_ids = tuple(item.id for item in scene.shots[first : last + 2])
                changed_ids.update((scene.id, shot_id, segment.id))
            elif operation.new_segment is not None:
                for item in scene.segments:
                    first = order_before.index(item.shot_ids[0])
                    last = order_before.index(item.shot_ids[-1])
                    if first < position <= last:
                        raise ValueError(
                            "insert_shot 的 new_segment 不能落在已有 Segment 的覆盖区间中间；"
                            "请用 attach_to_segment_id 并入该 Segment。"
                        )
                segment_id = fresh_id(operation_index, "segment")
                new_segment = _script_segment_draft(
                    operation.new_segment,
                    segment_id,
                    (shot_id,),
                )
                insertion = next(
                    (
                        item_index
                        for item_index, item in enumerate(scene.segments)
                        if order_before.index(item.shot_ids[-1]) >= position
                    ),
                    len(scene.segments),
                )
                scene.segments.insert(insertion, new_segment)
                changed_ids.update((scene.id, shot_id, segment_id))
            else:
                raise ValueError("insert_shot 必须同时给出 attach_to_segment_id 或 new_segment。")
            continue
        if operation.op == "delete_shot":
            assert operation.scene_id is not None and operation.shot_id is not None
            scene = find_scene(operation.scene_id)
            actual_scene, shot = find_shot(operation.shot_id)
            if actual_scene is not scene:
                raise ValueError("Shot 不属于 operation 指定的 Scene。")
            scene.shots.remove(shot)
            for segment in scene.segments:
                if shot.id not in segment.shot_ids:
                    continue
                remaining = tuple(item for item in segment.shot_ids if item != shot.id)
                if not remaining:
                    raise ValueError(
                        f"删除 Shot 会使 Segment「{segment.id}」失去全部 Shot；"
                        "请先在同一次修改里调整覆盖。"
                    )
                segment.shot_ids = remaining
            changed_ids.update((scene.id, shot.id))
            continue
        if operation.op == "update_segment_fields":
            assert operation.segment_id is not None and operation.fields is not None
            scene, segment = find_segment(operation.segment_id)
            for name, value in operation.fields.items():
                setattr(
                    segment,
                    name,
                    _script_segment_field(
                        name,
                        value,
                        previous_dialogue_lines=segment.dialogue_lines,
                    ),
                )
            changed_ids.update((scene.id, segment.id))
            continue
        if operation.op == "insert_segment":
            assert operation.scene_id is not None and operation.segment is not None
            scene = find_scene(operation.scene_id)
            segment_id = fresh_id(operation_index, "segment")
            segment = _script_segment_draft(
                operation.segment,
                segment_id,
                operation.segment.shot_ids,
            )
            _insert_after(scene.segments, segment, operation.after_id, "Segment")
            changed_ids.update((scene.id, segment_id))
            continue
        if operation.op in {"move_segment", "delete_segment"}:
            assert operation.scene_id is not None and operation.segment_id is not None
            scene, segment = find_segment(operation.segment_id)
            if scene.id != operation.scene_id:
                raise ValueError("Segment 不属于 operation 指定的 Scene。")
            scene.segments.remove(segment)
            if operation.op == "move_segment":
                if operation.after_id == segment.id:
                    raise ValueError("Segment 不能移动到自身之后。")
                _insert_after(scene.segments, segment, operation.after_id, "Segment")
            changed_ids.update((scene.id, segment.id))
            continue
        if operation.op == "split_segment":
            assert (
                operation.segment_id is not None
                and operation.first is not None
                and operation.second is not None
                and operation.preserve_id in {"first", "second"}
            )
            scene, segment = find_segment(operation.segment_id)
            segment_index = scene.segments.index(segment)
            new_id = fresh_id(operation_index, "split")
            first_id = segment.id if operation.preserve_id == "first" else new_id
            second_id = segment.id if operation.preserve_id == "second" else new_id
            first_dialogue, second_dialogue = _reconcile_dialogue_line_groups(
                (operation.first.dialogue_lines, operation.second.dialogue_lines),
                segment.dialogue_lines,
            )
            first = _script_segment_draft(operation.first, first_id, operation.first.shot_ids)
            second = _script_segment_draft(operation.second, second_id, operation.second.shot_ids)
            first = replace(first, dialogue_lines=first_dialogue)
            second = replace(second, dialogue_lines=second_dialogue)
            scene.segments[segment_index : segment_index + 1] = [first, second]
            changed_ids.update((scene.id, segment.id, new_id))
            continue
        if operation.op == "merge_adjacent_segments":
            assert (
                operation.segment_id is not None
                and operation.right_segment_id is not None
                and operation.segment is not None
                and operation.preserve_id in {"left", "right"}
            )
            scene, left = find_segment(operation.segment_id)
            right_scene, right = find_segment(operation.right_segment_id)
            if scene is not right_scene:
                raise ValueError("只能合并同一 Scene 中的相邻 Segment。")
            left_index = scene.segments.index(left)
            if left_index + 1 >= len(scene.segments) or scene.segments[left_index + 1] is not right:
                raise ValueError("merge_adjacent_segments 的左右 Segment 不相邻。")
            union = tuple(dict.fromkeys((*left.shot_ids, *right.shot_ids)))
            if operation.segment.shot_ids != union:
                raise ValueError("合并后的 shot_ids 必须是两段覆盖的并集。")
            merged_id = left.id if operation.preserve_id == "left" else right.id
            merged = _script_segment_draft(operation.segment, merged_id, union)
            (merged_dialogue,) = _reconcile_dialogue_line_groups(
                (operation.segment.dialogue_lines,),
                (*left.dialogue_lines, *right.dialogue_lines),
            )
            merged = replace(merged, dialogue_lines=merged_dialogue)
            scene.segments[left_index : left_index + 2] = [merged]
            changed_ids.update((scene.id, left.id, right.id))
            continue
        if operation.op == "merge_adjacent_scenes":
            assert operation.scene_id is not None and operation.right_scene_id is not None
            left_scene = find_scene(operation.scene_id)
            right_scene = find_scene(operation.right_scene_id)
            left_index = drafts.index(left_scene)
            if left_index + 1 >= len(drafts) or drafts[left_index + 1] is not right_scene:
                raise ValueError("merge_adjacent_scenes 的左右 Scene 不相邻。")
            if left_scene.driver != right_scene.driver:
                raise ValueError("只能合并 driver 相同的 Scene；旁白与对白 Scene 不能合并。")
            if left_scene.driver == "narration":
                raise ValueError(
                    "每个 Narration Scene 只能有一条旁白 Cue，两个 Narration Scene 不能合并。"
                )
            # 只重组归属：Shot、Segment、对白与旁白 Cue 原样保留 ID，
            # 关键帧、视频与候选随 ID 留在原卡片。
            left_scene.shots.extend(right_scene.shots)
            left_scene.segments.extend(right_scene.segments)
            left_scene.narration_cues = (*left_scene.narration_cues, *right_scene.narration_cues)
            if left_scene.location_id is None:
                left_scene.location_id = right_scene.location_id
                left_scene.state_id = right_scene.state_id
            drafts.remove(right_scene)
            changed_ids.update((left_scene.id, right_scene.id))
            continue
        raise TypeError("未支持的 Script operation。")

    materialized = tuple(_materialize_script_scene_draft(scene) for scene in drafts)
    DirectorScript(1, 1, None, None, materialized)
    return materialized, changed_ids


def _script_scene_draft(scene: Scene) -> _ScriptSceneDraft:
    return _ScriptSceneDraft(
        scene.id,
        scene.title,
        scene.summary,
        scene.setting,
        [
            _ScriptShotDraft(
                shot.id,
                shot.visible_character_ids,
                shot.composition,
                shot.camera_movement,
                shot.action,
                shot.audio_direction,
                shot.transition_in,
            )
            for shot in scene.shots
        ],
        [
            _ScriptSegmentDraft(
                segment.id,
                segment.shot_ids,
                segment.duration_estimate_seconds,
                segment.action,
                segment.dialogue_lines,
                segment.boundary_from_previous,
            )
            for segment in scene.segments
        ],
        scene.narration_cues,
        scene.driver,
        scene.location_id,
        scene.state_id,
    )


def _script_new_scene_draft(
    value: ScriptSceneInput,
    *,
    fresh_id: Callable[[str], str],
) -> _ScriptSceneDraft:
    scene_id = fresh_id("scene")
    shot_ids = {index: fresh_id(f"scene:shot:{index}") for index in range(len(value.shots))}
    shots = [
        _script_shot_draft(shot, shot_id=shot_ids[index]) for index, shot in enumerate(value.shots)
    ]
    resolved = _resolve_shot_indexes(
        scene_label=f"Scene「{value.title}」",
        shot_ids=tuple(shot_ids[index] for index in range(len(value.shots))),
        segment_indexes=tuple(segment.shot_indexes for segment in value.segments),
        has_boundary=tuple(
            segment.boundary_from_previous is not None for segment in value.segments
        ),
    )
    segments = [
        _script_segment_draft(segment, fresh_id(f"scene:segment:{index}"), shot_ids_for_segment)
        for index, (segment, shot_ids_for_segment) in enumerate(
            zip(value.segments, resolved, strict=True)
        )
    ]
    cues = (
        ()
        if value.narration_cue is None
        else (
            NarrationCue(
                id=fresh_id("scene:narration_cue"),
                zh=_materialize_track(value.narration_cue.zh),
                en=_materialize_track(value.narration_cue.en),
            ),
        )
    )
    return _ScriptSceneDraft(
        scene_id,
        value.title,
        value.summary,
        value.setting,
        shots,
        segments,
        cues,
        value.driver,
        None,
        None,
    )


def _script_shot_draft(
    value: ScriptShotInput,
    *,
    shot_id: str,
) -> _ScriptShotDraft:
    return _ScriptShotDraft(
        shot_id,
        value.visible_character_ids,
        value.composition,
        value.camera_movement,
        value.action,
        value.audio_direction,
        value.transition_in,
    )


def _script_segment_draft(
    value: ScriptSegmentInput,
    segment_id: str,
    shot_ids: tuple[str, ...],
) -> _ScriptSegmentDraft:
    return _ScriptSegmentDraft(
        segment_id,
        shot_ids,
        value.duration_estimate_seconds,
        value.action,
        tuple(_script_dialogue(item) for item in value.dialogue_lines),
        _script_boundary(value.boundary_from_previous),
    )


def _script_dialogue(value: ScriptDialogueInput) -> DialogueLine:
    return DialogueLine(
        value.character_id,
        value.text,
        value.delivery,
        value.speaker_label,
        value.id or uuid4().hex,
        value.voice_description,
    )


def _reconcile_dialogue_line_groups(
    groups: tuple[tuple[ScriptDialogueInput, ...], ...],
    previous: tuple[DialogueLine, ...],
) -> tuple[tuple[DialogueLine, ...], ...]:
    """未显式回传 ID 时，只为真正新增或改写的对白分配新 ID。"""
    explicit_ids = {item.id for group in groups for item in group if item.id is not None}
    used_ids = set(explicit_ids)
    reconciled: list[tuple[DialogueLine, ...]] = []
    for group in groups:
        lines: list[DialogueLine] = []
        for item in group:
            line = _script_dialogue(item)
            if item.id is None:
                match = next(
                    (
                        old
                        for old in previous
                        if old.id is not None
                        and old.id not in used_ids
                        and replace(line, id=old.id) == old
                    ),
                    None,
                )
                if match is not None:
                    line = match
                    used_ids.add(match.id)
            lines.append(line)
        reconciled.append(tuple(lines))
    return tuple(reconciled)


def _dialogue_line(line: Any) -> DialogueLine:
    label = line.speaker_label
    return DialogueLine(
        line.character_id,
        line.text.strip(),
        line.delivery.strip(),
        None if label is None else label.strip(),
        getattr(line, "id", None) or uuid4().hex,
        (
            None
            if getattr(line, "voice_description", None) is None
            else line.voice_description.strip()
        ),
    )


def _script_boundary(value: ScriptBoundaryInput | None) -> SegmentBoundary | None:
    return (
        None
        if value is None
        else SegmentBoundary(
            SegmentBoundaryReason(value.reason),
            value.continuity_instruction,
        )
    )


def _script_segment_field(
    name: str,
    value: object,
    *,
    previous_dialogue_lines: tuple[DialogueLine, ...] = (),
) -> object:
    if name == "dialogue_lines":
        assert isinstance(value, tuple)
        (dialogue_lines,) = _reconcile_dialogue_line_groups((value,), previous_dialogue_lines)
        return dialogue_lines
    if name == "boundary_from_previous":
        assert value is None or isinstance(value, ScriptBoundaryInput)
        return _script_boundary(value)
    return value


def _insert_after(
    items: list[Any],
    value: Any,
    after_id: str | None,
    label: str,
) -> None:
    if after_id is None:
        items.insert(0, value)
        return
    index = next(
        (item_index for item_index, item in enumerate(items) if item.id == after_id),
        None,
    )
    if index is None:
        raise ValueError(f"{label} 插入或移动锚点不属于当前父节点。")
    items.insert(index + 1, value)


def _materialize_script_scene_draft(scene: _ScriptSceneDraft) -> Scene:
    shots = tuple(
        Shot(
            shot.id,
            shot.visible_character_ids,
            shot.composition,
            shot.camera_movement,
            shot.action,
            shot.audio_direction,
            shot.transition_in,
        )
        for shot in scene.shots
    )
    segments = tuple(
        ShotSegment(
            segment.id,
            segment.shot_ids,
            segment.duration_estimate_seconds,
            segment.action,
            segment.dialogue_lines,
            segment.boundary_from_previous,
        )
        for segment in scene.segments
    )
    return Scene(
        scene.id,
        scene.title,
        scene.summary,
        scene.setting,
        shots,
        segments,
        scene.narration_cues,
        scene.driver,
        scene.location_id,
        scene.state_id,
    )


def _rebase_keyframe_plan(
    plan: KeyframePlan | None,
    *,
    source_script_revision: int,
    scenes: tuple[Scene, ...],
) -> KeyframePlan | None:
    if plan is None:
        return None
    # 只按 Segment ID 保留既有绑定与关键帧：纯文本调整不丢已有关键帧（环境字段保持原值）；
    # 新增的 Segment 获得独立的空首尾槽位，环境按所属 Shot 的视图取默认值。
    # 显式共享的边界只在两侧 Segment 仍然紧邻时保留，
    # 否则把首帧复制为该 Segment 自己的独立 Keyframe（保留正文与已选图片）。
    old_keyframes = {item.id: item for item in plan.keyframes}
    old_bindings = {item.segment_id: item for item in plan.segments}
    current_segment_ids = {segment.id for segment in script_segments(scenes)}
    keyframes: dict[str, Keyframe] = {}
    bindings: list[SegmentKeyframes] = []

    def clone(source_id: str, segment_id: str, predecessor_id: str | None) -> str:
        clone_id = uuid4().hex
        keyframes[clone_id] = replace(
            old_keyframes[source_id],
            id=clone_id,
            owner_segment_id=segment_id,
            predecessor_keyframe_id=predecessor_id,
        )
        return clone_id

    for scene in scenes:
        previous_end_id: str | None = None
        for segment in scene_segments(scene):
            old_binding = old_bindings.get(segment.id)
            reuse_binding = (
                old_binding is not None
                and old_binding.start_keyframe_id in old_keyframes
                and old_binding.end_keyframe_id in old_keyframes
            )
            if not reuse_binding:
                start_id = uuid4().hex
                keyframes[start_id] = blank_keyframe(start_id, segment.id, None)
            elif old_binding.start_keyframe_id == previous_end_id:
                start_id = old_binding.start_keyframe_id
            elif old_binding.start_keyframe_id in keyframes or any(
                item.end_keyframe_id == old_binding.start_keyframe_id
                and item.segment_id in current_segment_ids
                for item in plan.segments
            ):
                start_id = clone(old_binding.start_keyframe_id, segment.id, None)
            else:
                start_id = old_binding.start_keyframe_id
                keyframes[start_id] = replace(
                    old_keyframes[start_id],
                    owner_segment_id=segment.id,
                    predecessor_keyframe_id=None,
                )
            if not reuse_binding:
                end_id = uuid4().hex
                keyframes[end_id] = blank_keyframe(end_id, segment.id, start_id)
            elif old_binding.end_keyframe_id in keyframes:
                # 已被前面某个 Segment 作为首帧占用，说明原共享边界已不再紧邻。
                end_id = clone(old_binding.end_keyframe_id, segment.id, start_id)
            else:
                end_id = old_binding.end_keyframe_id
                keyframes[end_id] = replace(
                    old_keyframes[end_id],
                    owner_segment_id=segment.id,
                    predecessor_keyframe_id=start_id,
                )
            bindings.append(
                SegmentKeyframes(
                    segment_id=segment.id,
                    start_keyframe_id=start_id,
                    end_keyframe_id=end_id,
                    start_enabled=old_binding.start_enabled if reuse_binding else False,
                    end_enabled=old_binding.end_enabled if reuse_binding else False,
                    reference_asset_ids=(old_binding.reference_asset_ids if reuse_binding else ()),
                )
            )
            previous_end_id = end_id
    return KeyframePlan(source_script_revision, tuple(keyframes.values()), tuple(bindings))


def _rebase_video_plan(
    plan: VideoPlan | None,
    *,
    source_script_revision: int,
    previous_scenes: tuple[Scene, ...],
    scenes: tuple[Scene, ...],
) -> VideoPlan | None:
    if plan is None:
        return None
    previous_contexts = _segment_visual_contexts(previous_scenes)
    current_contexts = _segment_visual_contexts(scenes)
    old_items = {item.segment_id: item for item in plan.segments}
    items = []
    for segment in script_segments(scenes):
        current = old_items.get(segment.id)
        previous_context = previous_contexts.get(segment.id)
        current_context = current_contexts[segment.id]
        if previous_context is not None and previous_context[0] != current_context[0]:
            # Scene 合并只改变归属：并入的 Segment 沿用左侧 Scene 的 setting 文本，
            # 不因此失效已选视频。
            unchanged = previous_context[2:] == current_context[2:]
        else:
            unchanged = previous_context == current_context
        if current is not None and unchanged:
            items.append(current)
        elif current is not None:
            # 剧本字段与用户显式保存的视频计划属于不同内容层。剧本回改可以让
            # 已选渲染产物过期，但不能丢弃 H3 正文、模式或带描述的参考素材。
            items.append(
                replace(
                    current,
                    selected_asset_id=None,
                    upscaled_asset_id=None,
                )
            )
        else:
            items.append(
                SegmentVideo(
                    segment.id,
                    "",
                )
            )
    return VideoPlan(source_script_revision, tuple(items))


def _segment_visual_contexts(scenes: tuple[Scene, ...]) -> dict[str, tuple[object, ...]]:
    return {
        segment.id: (
            scene.id,
            scene.setting,
            tuple(
                (
                    shot.visible_character_ids,
                    shot.composition,
                    shot.camera_movement,
                    shot.action,
                    shot.transition_in,
                )
                for shot in segment_shots(scene, segment.id)
            ),
            segment.duration_estimate_seconds,
            segment.action,
            segment.dialogue_lines,
            segment.boundary_from_previous,
        )
        for scene in scenes
        for segment in scene.segments
    }


def _materialize_scene_parts(
    title: str,
    shots: tuple[Any, ...],
    segments: tuple[Any, ...],
    *,
    shot_id: Callable[[Any], str],
    segment_id: Callable[[str | None], str] | None = None,
    dialogue_id: Callable[[str | None], str] | None = None,
) -> tuple[tuple[Shot, ...], tuple[ShotSegment, ...]]:
    """把 proposal 的 shots + segments（shot_indexes）物化为 v33 的并列结构并校验覆盖。"""
    materialized_shots = tuple(
        Shot(
            id=shot_id(shot),
            visible_character_ids=shot.visible_character_ids,
            composition=shot.composition.strip(),
            camera_movement=shot.camera_movement.strip(),
            action=shot.action.strip(),
            audio_direction=shot.audio_direction.strip(),
            transition_in=None if shot.transition_in is None else shot.transition_in.strip(),
        )
        for shot in shots
    )
    resolved = _resolve_shot_indexes(
        scene_label=f"Scene「{title}」",
        shot_ids=tuple(item.id for item in materialized_shots),
        segment_indexes=tuple(segment.shot_indexes for segment in segments),
        has_boundary=tuple(segment.boundary_from_previous is not None for segment in segments),
    )
    segment_id = segment_id or (lambda _value: uuid4().hex)
    materialized_segments: list[ShotSegment] = []
    for segment, shot_ids in zip(segments, resolved, strict=True):
        materialized = _materialize_segment(
            segment, segment_id(getattr(segment, "id", None)), shot_ids
        )
        if dialogue_id is not None:
            materialized = replace(
                materialized,
                dialogue_lines=tuple(
                    replace(line, id=dialogue_id(getattr(source, "id", None)))
                    for line, source in zip(
                        materialized.dialogue_lines, segment.dialogue_lines, strict=True
                    )
                ),
            )
        materialized_segments.append(materialized)
    return materialized_shots, tuple(materialized_segments)


def _resolve_shot_indexes(
    *,
    scene_label: str,
    shot_ids: tuple[str, ...],
    segment_indexes: tuple[tuple[int, ...], ...],
    has_boundary: tuple[bool, ...],
) -> tuple[tuple[str, ...], ...]:
    """按 §4.1 把 shot_indexes 解析为 shot_ids；错误指出 Scene、Segment 序号与子规则。"""
    resolved: list[tuple[str, ...]] = []
    previous_last: int | None = None
    for ordinal, indexes in enumerate(segment_indexes, start=1):
        label = f"{scene_label} 的第 {ordinal} 个 Segment"
        if not indexes:
            raise ValueError(f"{label} 必须至少覆盖一个 Shot。")
        if any(index >= len(shot_ids) for index in indexes):
            raise ValueError(f"{label} 的 shot_indexes 引用了不属于本 Scene 的 Shot 序号。")
        if indexes != tuple(range(indexes[0], indexes[0] + len(indexes))):
            raise ValueError(f"{label} 必须按 Shot 顺序连续覆盖，不能倒序或跳过中间的 Shot。")
        shares = previous_last is not None and indexes[0] == previous_last
        if previous_last is None and indexes[0] != 0:
            raise ValueError(f"{label} 必须从本 Scene 的第一个 Shot 开始，不能跳过前面的 Shot。")
        if previous_last is not None and not shares:
            if indexes[0] < previous_last:
                raise ValueError(
                    f"{label} 重复覆盖了前面的 Shot；只允许相邻 Segment 共享边界 Shot。"
                )
            if indexes[0] > previous_last + 1:
                raise ValueError(f"{label} 跳过了第 {previous_last + 2} 个 Shot。")
        boundary = has_boundary[ordinal - 1]
        if shares and not boundary:
            raise ValueError(
                f"{label} 延续上一段镜头（共享边界 Shot），必须填写 boundary_from_previous。"
            )
        if not shares and boundary:
            raise ValueError(f"{label} 不延续上一段镜头，boundary_from_previous 必须为 null。")
        previous_last = indexes[-1]
        resolved.append(tuple(shot_ids[index] for index in indexes))
    if previous_last is not None and previous_last != len(shot_ids) - 1:
        raise ValueError(
            f"{scene_label} 的 Segment 没有覆盖到最后一个 Shot"
            f"（第 {len(shot_ids)} 个 Shot 未被覆盖）。"
        )
    return tuple(resolved)
