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
    DialogueLine,
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
    segment_view_ids,
    shot_segments,
)
from .v32_projection import require_v32_cue_anchors, require_v32_shot_segments, v32_shot_segments


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
    scenes: list[Scene] = []
    for scene in proposal.scenes:
        if scene.driver == "narration" and scene.shots:
            raise ValueError("Narration Scene 初稿只提交旁白；TTS 审核后再规划 Shot。")
        shots, segments = _materialize_shots(scene.shots, lambda _shot: uuid4().hex)
        cues = []
        for cue in scene.narration_cues:
            _require_cue_anchor_indexes(shots, cue)
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
                shots=shots,
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
    all_known_ids = known_scene_ids | known_shot_ids | known_segment_ids | known_cue_ids
    previous_cues = {cue.id: cue for scene in previous for cue in scene.narration_cues}
    previous_views = _shot_views(previous)

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
        shots, segments = _materialize_shots(
            scene.shots,
            lambda shot: resolved(shot.id, known_shot_ids, "shot.id"),
            segment_id=lambda value: resolved(value, known_segment_ids, "segment.id"),
        )
        cues: list[NarrationCue] = []
        for cue in scene.narration_cues:
            cue_id = resolved(cue.id, known_cue_ids, "narration_cue.id")
            _require_cue_anchor_indexes(shots, cue)
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
                shots=tuple(
                    replace(shot, view_id=_kept_view_id(previous_views.get(shot.id), location_id))
                    for shot in shots
                ),
                segments=segments,
                narration_cues=tuple(cues),
            )
        )
    return tuple(scenes)


def _shot_views(scenes: tuple[Scene, ...]) -> dict[str, tuple[str | None, str]]:
    return {
        shot.id: (scene.location_id, shot.view_id)
        for scene in scenes
        for shot in scene.shots
        if shot.view_id is not None
    }


def _kept_view_id(view: tuple[str | None, str] | None, location_id: str | None) -> str | None:
    """Shot 回改后只在仍处于同一地点的 Scene 时保留原视图绑定。"""
    if view is None or location_id is None or view[0] != location_id:
        return None
    return view[1]


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
                and operation.shot_id is not None
                and operation.segment is not None
                and operation.segment.id is not None
            )
            scene_index = locate(scene_id)
            scene = scenes[scene_index]
            if all(shot.id != operation.shot_id for shot in scene.shots):
                raise ValueError("replace_segment 的 Shot 不属于指定 Scene。")
            if all(
                segment.id != operation.segment.id
                for segment in v32_shot_segments(scene, operation.shot_id)
            ):
                raise ValueError("replace_segment 的 Segment 不属于指定 Shot。")
            segments = tuple(
                _materialize_segment(operation.segment, segment.id, segment.shot_ids)
                if segment.id == operation.segment.id
                else segment
                for segment in scene.segments
            )
            require_v32_shot_segments(
                [segment for segment in segments if segment.shot_ids[0] == operation.shot_id]
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
    if any(segment.id is not None for shot in scene.shots for segment in shot.segments):
        raise ValueError("新增 Scene 的 Segment ID 必须为 null。")
    if any(cue.id is not None for cue in scene.narration_cues):
        raise ValueError("新增 Scene 的旁白 Cue ID 必须为 null。")


def _require_cue_anchor_indexes(shots: tuple[Shot, ...], cue: Any) -> None:
    require_v32_cue_anchors(
        [shot.id for shot in shots],
        None if cue.start_shot_index is None else shots[cue.start_shot_index].id,
        None if cue.end_shot_index is None else shots[cue.end_shot_index].id,
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
        if any(shot.id is not None and shot.id not in shot_ids for shot in proposal.shots):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的 Shot ID。")
        if any(
            segment.id is not None and segment.id not in segment_ids
            for shot in proposal.shots
            for segment in shot.segments
        ):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的 Segment ID。")
        if any(cue.id is not None and cue.id not in cue_ids for cue in proposal.narration_cues):
            raise ValueError("局部脚本修改不能挪用其他 Scene 的旁白 Cue ID。")


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
        keyframe_plan=keyframe_plan,
        video_plan=video_plan,
        final_assembly=None,
        director_runs=director_runs,
    )


@dataclass(slots=True)
class _ScriptSegmentDraft:
    id: str
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
    segments: list[_ScriptSegmentDraft]
    # 原绑定（所在地点, 视图）；Shot 移到其它地点的 Scene 后不再保留。
    view: tuple[str | None, str] | None = None


@dataclass(slots=True)
class _ScriptSceneDraft:
    id: str
    title: str
    summary: str
    setting: str
    shots: list[_ScriptShotDraft]
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
            for segment in shot_segments(scene, shot.id):
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
                for segment in shot_segments(scene, shot.id)
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
            *(segment.id for shot in scene.shots for segment in shot.segments),
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

    def find_segment(
        segment_id: str,
    ) -> tuple[_ScriptSceneDraft, _ScriptShotDraft, _ScriptSegmentDraft]:
        matches = [
            (scene, shot, segment)
            for scene in drafts
            for shot in scene.shots
            for segment in shot.segments
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
            for shot_id in operation.scene.move_shot_ids:
                source, shot = find_shot(shot_id)
                source.shots.remove(shot)
                scene.shots.append(shot)
                changed_ids.update((source.id, shot.id))
            drafts.insert(index, scene)
            created_scene_ids.add(scene.id)
            changed_ids.update(
                (
                    scene.id,
                    *(shot.id for shot in scene.shots),
                    *(segment.id for shot in scene.shots for segment in shot.segments),
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
            if scene.shots:
                raise ValueError("Scene 仍包含 Shot；请先删除或用 move_shot 迁出后再删除 Scene。")
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
            shot = _script_shot_draft(
                operation.shot,
                shot_id=shot_id,
                segment_id=lambda index, current=operation_index: fresh_id(
                    current, f"segment:{index}"
                ),
            )
            _insert_after(scene.shots, shot, operation.after_id, "Shot")
            changed_ids.update((scene.id, shot_id, *(item.id for item in shot.segments)))
            continue
        if operation.op in {"move_shot", "delete_shot"}:
            assert operation.scene_id is not None and operation.shot_id is not None
            scene = find_scene(operation.scene_id)
            actual_scene, shot = find_shot(operation.shot_id)
            if actual_scene is not scene:
                raise ValueError("Shot 不属于 operation 指定的 Scene。")
            target = (
                scene
                if operation.target_scene_id is None
                else find_scene(operation.target_scene_id)
            )
            scene.shots.remove(shot)
            if operation.op == "move_shot":
                if operation.after_id == shot.id:
                    raise ValueError("Shot 不能移动到自身之后。")
                _insert_after(target.shots, shot, operation.after_id, "Shot")
            changed_ids.update((scene.id, target.id, shot.id))
            continue
        if operation.op == "update_segment_fields":
            assert operation.segment_id is not None and operation.fields is not None
            scene, _shot, segment = find_segment(operation.segment_id)
            for name, value in operation.fields.items():
                setattr(segment, name, _script_segment_field(name, value))
            changed_ids.update((scene.id, segment.id))
            continue
        if operation.op == "insert_segment":
            assert operation.shot_id is not None and operation.segment is not None
            scene, shot = find_shot(operation.shot_id)
            segment_id = fresh_id(operation_index, "segment")
            segment = _script_segment_draft(operation.segment, segment_id)
            _insert_after(shot.segments, segment, operation.after_id, "Segment")
            changed_ids.update((scene.id, shot.id, segment_id))
            continue
        if operation.op in {"move_segment", "delete_segment"}:
            assert operation.shot_id is not None and operation.segment_id is not None
            scene, shot = find_shot(operation.shot_id)
            actual_scene, actual_shot, segment = find_segment(operation.segment_id)
            if actual_scene is not scene or actual_shot is not shot:
                raise ValueError("Segment 不属于 operation 指定的 Shot。")
            shot.segments.remove(segment)
            if operation.op == "move_segment":
                if operation.after_id == segment.id:
                    raise ValueError("Segment 不能移动到自身之后。")
                _insert_after(shot.segments, segment, operation.after_id, "Segment")
            changed_ids.update((scene.id, shot.id, segment.id))
            continue
        if operation.op == "split_segment":
            assert (
                operation.segment_id is not None
                and operation.first is not None
                and operation.second is not None
                and operation.preserve_id in {"first", "second"}
            )
            scene, shot, segment = find_segment(operation.segment_id)
            segment_index = shot.segments.index(segment)
            new_id = fresh_id(operation_index, "split")
            first_id = segment.id if operation.preserve_id == "first" else new_id
            second_id = segment.id if operation.preserve_id == "second" else new_id
            first = _script_segment_draft(operation.first, first_id)
            second = _script_segment_draft(operation.second, second_id)
            shot.segments[segment_index : segment_index + 1] = [first, second]
            changed_ids.update((scene.id, shot.id, segment.id, new_id))
            continue
        if operation.op == "merge_adjacent_segments":
            assert (
                operation.segment_id is not None
                and operation.right_segment_id is not None
                and operation.segment is not None
                and operation.preserve_id in {"left", "right"}
            )
            scene, shot, left = find_segment(operation.segment_id)
            right_scene, right_shot, right = find_segment(operation.right_segment_id)
            if scene is not right_scene or shot is not right_shot:
                raise ValueError("只能合并同一 Shot 中的相邻 Segment。")
            left_index = shot.segments.index(left)
            if left_index + 1 >= len(shot.segments) or shot.segments[left_index + 1] is not right:
                raise ValueError("merge_adjacent_segments 的左右 Segment 不相邻。")
            merged_id = left.id if operation.preserve_id == "left" else right.id
            merged = _script_segment_draft(operation.segment, merged_id)
            shot.segments[left_index : left_index + 2] = [merged]
            changed_ids.update((scene.id, shot.id, left.id, right.id))
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
                [
                    _ScriptSegmentDraft(
                        segment.id,
                        segment.duration_estimate_seconds,
                        segment.action,
                        segment.dialogue_lines,
                        segment.boundary_from_previous,
                    )
                    for segment in v32_shot_segments(scene, shot.id)
                ],
                None if shot.view_id is None else (scene.location_id, shot.view_id),
            )
            for shot in scene.shots
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
    shots = []
    for shot_index, shot in enumerate(value.shots):
        shots.append(
            _script_shot_draft(
                shot,
                shot_id=fresh_id(f"scene:shot:{shot_index}"),
                segment_id=lambda index, current=shot_index: fresh_id(
                    f"scene:shot:{current}:segment:{index}"
                ),
            )
        )
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
        cues,
        value.driver,
        None,
        None,
    )


def _script_shot_draft(
    value: ScriptShotInput,
    *,
    shot_id: str,
    segment_id: Callable[[int], str],
) -> _ScriptShotDraft:
    return _ScriptShotDraft(
        shot_id,
        value.visible_character_ids,
        value.composition,
        value.camera_movement,
        value.action,
        value.audio_direction,
        value.transition_in,
        [
            _script_segment_draft(segment, segment_id(index))
            for index, segment in enumerate(value.segments)
        ],
    )


def _script_segment_draft(
    value: ScriptSegmentInput,
    segment_id: str,
) -> _ScriptSegmentDraft:
    return _ScriptSegmentDraft(
        segment_id,
        value.duration_estimate_seconds,
        value.action,
        tuple(_script_dialogue(item) for item in value.dialogue_lines),
        _script_boundary(value.boundary_from_previous),
    )


def _script_dialogue(value: ScriptDialogueInput) -> DialogueLine:
    return DialogueLine(value.character_id, value.text, value.delivery, value.speaker_label)


def _dialogue_line(line: Any) -> DialogueLine:
    label = line.speaker_label
    return DialogueLine(
        line.character_id,
        line.text.strip(),
        line.delivery.strip(),
        None if label is None else label.strip(),
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


def _script_segment_field(name: str, value: object) -> object:
    if name == "dialogue_lines":
        assert isinstance(value, tuple)
        return tuple(_script_dialogue(item) for item in value)
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
    shots: list[Shot] = []
    segments: list[ShotSegment] = []
    for shot in scene.shots:
        require_v32_shot_segments(shot.segments)
        shots.append(
            Shot(
                shot.id,
                shot.visible_character_ids,
                shot.composition,
                shot.camera_movement,
                shot.action,
                shot.audio_direction,
                shot.transition_in,
                view_id=_kept_view_id(shot.view, scene.location_id),
            )
        )
        segments.extend(
            ShotSegment(
                segment.id,
                (shot.id,),
                segment.duration_estimate_seconds,
                segment.action,
                segment.dialogue_lines,
                segment.boundary_from_previous,
            )
            for segment in shot.segments
        )
    return Scene(
        scene.id,
        scene.title,
        scene.summary,
        scene.setting,
        tuple(shots),
        tuple(segments),
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
            start_view_id, end_view_id = segment_view_ids(scene, segment.id)
            old_binding = old_bindings.get(segment.id)
            reuse_binding = (
                old_binding is not None
                and old_binding.start_keyframe_id in old_keyframes
                and old_binding.end_keyframe_id in old_keyframes
            )
            if not reuse_binding:
                start_id = uuid4().hex
                keyframes[start_id] = blank_keyframe(
                    start_id, segment.id, None, shot_view_id=start_view_id
                )
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
                keyframes[end_id] = blank_keyframe(
                    end_id, segment.id, start_id, shot_view_id=end_view_id
                )
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
        unchanged = previous_contexts.get(segment.id) == current_contexts[segment.id]
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


def _materialize_shots(
    shots: tuple[Any, ...],
    shot_id: Callable[[Any], str],
    segment_id: Callable[[str | None], str] | None = None,
) -> tuple[tuple[Shot, ...], tuple[ShotSegment, ...]]:
    """v32 形状的 Shot（各自下挂 Segment）物化为并列的 shots 与覆盖各自 Shot 的 segments。"""
    segment_id = segment_id or (lambda _value: uuid4().hex)
    materialized_shots: list[Shot] = []
    segments: list[ShotSegment] = []
    for shot in shots:
        require_v32_shot_segments(shot.segments)
        materialized = Shot(
            id=shot_id(shot),
            visible_character_ids=shot.visible_character_ids,
            composition=shot.composition.strip(),
            camera_movement=shot.camera_movement.strip(),
            action=shot.action.strip(),
            audio_direction=shot.audio_direction.strip(),
            transition_in=None if shot.transition_in is None else shot.transition_in.strip(),
        )
        materialized_shots.append(materialized)
        segments.extend(
            _materialize_segment(
                segment, segment_id(getattr(segment, "id", None)), (materialized.id,)
            )
            for segment in shot.segments
        )
    return tuple(materialized_shots), tuple(segments)
