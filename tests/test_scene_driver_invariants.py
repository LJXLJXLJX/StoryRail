"""Scene driver 与生产切片规则：通过真实 Store / typed commands 验证。"""

import asyncio
import json
from dataclasses import replace

import pytest
from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from script_helpers import shot_segments_at
from structured_director_fixtures import (
    NarrationReferenceProposer,
    NarrationScriptProposer,
    RecordingProposer,
    RecordingProvider,
    RecordingScriptProposer,
    TwoSceneScriptProposer,
    create_project,
    synthesize_and_select_narration,
    upload_narrator_voice,
    wav_bytes,
)

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.structured_director import StructuredDirectorStore
from core.structured_director.assembly_timeline import (
    _align_clip_durations_to_narration,
    _clip_starts,
    _final_transition,
)
from core.structured_director.errors import RevisionConflictError
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.models import (
    DialogueLine,
    FinalNarrationPlacement,
    NarrationCue,
    NarrationTrack,
    ReferenceGenerationPhase,
    Scene,
    SceneAssemblyClip,
    SceneAssemblyPlan,
    Shot,
    ShotSegment,
)
from core.structured_director.production_context import _script_json
from core.structured_director.reads.snapshot_view import _allowed_actions
from core.structured_director.reads.workflow_state import workflow_state


class TwoNarrationFirstProposer(NarrationScriptProposer):
    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        first = proposal.scenes[0]
        return replace(
            proposal,
            scenes=(
                first,
                replace(
                    first,
                    title="第二段旁白",
                    summary="列车驶入夜色。",
                    setting="深夜，列车车厢内。",
                ),
            ),
        )


def shot_input():
    return {
        "visible_character_ids": [],
        "composition": "全景",
        "camera_movement": "缓慢推进",
        "action": "同一镜头连续观察环境",
        "audio_direction": "风声",
        "transition_in": None,
    }


def segment_input(duration: float, index: int) -> dict:
    return {
        "duration_estimate_seconds": duration,
        "action": "连续推进的前半程" if index == 0 else "连续推进的后半程",
        "dialogue_lines": [],
        "boundary_from_previous": (
            None
            if index == 0
            else {
                "reason": "model_constraint",
                "continuity_instruction": "从同一静态交接时刻继续",
            }
        ),
    }


def insert_shot(
    registry,
    document,
    *,
    scene_id=None,
    durations=(8, 8),
    after_shot_id=None,
    idempotency_key="plan-real-duration",
):
    """插入一个新 Shot：首段随 Shot 创建，其余段以 insert_segment 接到同一 Shot 上。"""
    scene_id = scene_id or document.director_script.scenes[0].id
    existing = next(scene for scene in document.director_script.scenes if scene.id == scene_id)
    known_shot_ids = {shot.id for shot in existing.shots}
    first, *rest = durations
    result = registry.execute(
        DirectorCommand(
            "script.apply_operations",
            document.revision,
            idempotency_key,
            {
                "scope": {"scene_ids": [scene_id]},
                "operations": [
                    {
                        "op": "insert_shot",
                        "scene_id": scene_id,
                        "after_shot_id": after_shot_id,
                        "shot": shot_input(),
                        "new_segment": {"shot_indexes": [0], **segment_input(first, 0)},
                    },
                ],
            },
        )
    )
    scene = next(item for item in result.document.director_script.scenes if item.id == scene_id)
    inserted = next(shot for shot in scene.shots if shot.id not in known_shot_ids)
    if rest:
        covering = [segment.id for segment in scene.segments if inserted.id in segment.shot_ids]
        # narration Scene 每次写入都会把 Segment 时长校准到规划总长；同批补段时按总长填，
        # 最终各段均分。drama Scene 不做校准，按字面时长写入。
        total = float(sum(durations))
        result = registry.execute(
            DirectorCommand(
                "script.apply_operations",
                result.document.revision,
                f"{idempotency_key}-rest",
                {
                    "scope": {"scene_ids": [scene_id]},
                    "operations": [
                        {
                            "op": "insert_segment",
                            "scene_id": scene_id,
                            "after_segment_id": covering[-1],
                            "segment": {
                                "shot_ids": [inserted.id],
                                **segment_input(
                                    total if existing.driver == "narration" else duration,
                                    index,
                                ),
                            },
                        }
                        for index, duration in enumerate(rest, start=1)
                    ],
                },
            )
        )
    return result


async def narration_project(path, proposer=None):
    store = StructuredDirectorStore(path, "a" * 32)
    provider = RecordingProvider(media_type="audio/wav", content=wav_bytes(duration_seconds=16))
    service = StructuredDirectorService(
        store,
        NarrationReferenceProposer(),
        script_proposer=proposer or NarrationScriptProposer(),
        speech_provider=provider,
    )
    create_project(store)
    document = await service.prepare_references()
    document = await upload_narrator_voice(service, document)
    document = await service.prepare_script(expected_revision=document.revision)
    document = await service.confirm_script(expected_revision=document.revision)
    return store, service, provider, document


async def select_audio(service, document):
    """为第一个 Scene 的旁白合成并选择中英文音频。"""
    cue = document.director_script.scenes[0].narration_cues[0]
    selected, _ = await synthesize_and_select_narration(
        service, cue.id, document.revision, document.narration_languages
    )
    return selected


def test_mixed_cut_and_seam_math_uses_only_boundary_identity():
    assert _final_transition("a", "b") is None
    assert _final_transition("a", "a").value == "seam_blend"
    assert _clip_starts([4, 4, 4], 0.1, [None, None, "seam_blend"]) == [0, 4, 7.9]


def test_tts_first_then_one_sixteen_second_shot_and_invalidation(tmp_path):
    asyncio.run(_test_tts_first_then_one_sixteen_second_shot_and_invalidation(tmp_path))


async def _test_tts_first_then_one_sixteen_second_shot_and_invalidation(tmp_path):
    store, service, _provider, document = await narration_project(tmp_path)
    scene = document.director_script.scenes[0]
    assert scene.driver == "narration" and scene.shots == ()
    assert scene.segments == ()
    registry = DirectorCommandRegistry(store)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="必须先选择项目所选语言的 TTS"):
        registry.execute(insert_shot(registry, document))
    assert store.path.read_bytes() == before

    # The manual UI saves the cue before narration-driven Shot planning.
    cue = scene.narration_cues[0]
    api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
    saved = await api.handle(
        "PUT",
        f"/structured-director/scenes/{scene.id}/narration-cues/{cue.id}",
        json.dumps(
            {
                "expected_revision": document.revision,
                **{
                    language.value: {
                        "text": track.text,
                        "seed": track.seed,
                        "recipe_params": track.recipe_params.to_json(),
                    }
                    for language, track in cue.tracks
                },
            }
        ).encode(),
    )
    assert saved.status == 200, saved.body
    document = store.read()
    selected = await select_audio(service, document)
    workflow = workflow_state(selected)
    assert workflow["current_stage"] == "narration"
    assert workflow["stage_status"] == "awaiting_plan"
    assert workflow["required_next_actions"] == [
        {
            "action": "script.apply_operations",
            "tool": "edit_script",
            "target_ids": [scene.id],
            "human_only": False,
            "requires_explicit_user_request": True,
            "purpose": "plan_shots_from_selected_narration_timing",
            "reason": "narration_shot_plan_required",
        }
    ]
    context = json.loads(_script_json(selected.director_script.scenes, selected))
    timing = context["scenes"][0]["narration_timing"][0]
    assert timing["duration_seconds"] == 16
    assert timing["zh"]["duration_seconds"] == timing["en"]["duration_seconds"] == 16
    # Narration Scene 尚无 Shot 时 Core 无法校准，生产基线保持失效。
    assert selected.director_script.production_baseline_revision != (
        selected.director_script.revision
    )
    planned = insert_shot(registry, selected).document
    cue = planned.director_script.scenes[0].narration_cues[0]
    assert cue.fully_selected
    # 规划 Shot 的同一次写入里 Core 按真实音频校准并建立生产基线，直接进入视觉生产解锁。
    assert planned.director_script.production_baseline_revision == planned.director_script.revision
    workflow = workflow_state(planned)
    assert workflow["current_stage"] == "visual_production"
    assert workflow["stage_status"] == "awaiting_unlock"
    ready = store.read()
    assert ready == planned
    assert (
        sum(
            s.duration_estimate_seconds
            for s in shot_segments_at(ready.director_script.scenes[0], 0)
        )
        == 16
    )
    visual = await service.unlock_visual_production(expected_revision=ready.revision)
    left, right = visual.keyframe_plan.segments
    # Shot 内边界默认独立；单侧启用与共享、拆分都是显式且合法的操作。
    assert left.end_keyframe_id != right.start_keyframe_id
    assert not (left.end_enabled or right.start_enabled)
    shared = registry.execute(
        DirectorCommand(
            "keyframe.apply_operations",
            visual.revision,
            "share-internal-boundary",
            {
                "operations": [
                    {
                        "op": "share_boundary",
                        "left_segment_id": left.segment_id,
                        "right_segment_id": right.segment_id,
                        "expected_adjacency": "intra_shot",
                    },
                    {
                        "op": "set_activation",
                        "segment_id": right.segment_id,
                        "start_enabled": False,
                        "end_enabled": True,
                    },
                ]
            },
        )
    ).document
    shared_left, shared_right = shared.keyframe_plan.segments
    assert shared_left.end_keyframe_id == shared_right.start_keyframe_id
    assert shared_left.end_enabled and not shared_right.start_enabled
    split = registry.execute(
        DirectorCommand(
            "keyframe.apply_operations",
            shared.revision,
            "split-internal-boundary",
            {
                "operations": [
                    {
                        "op": "split_boundary",
                        "left_segment_id": left.segment_id,
                        "right_segment_id": right.segment_id,
                        "clone_side": "right_start",
                    }
                ]
            },
        )
    ).document
    split_left, split_right = split.keyframe_plan.segments
    assert split_left.end_keyframe_id != split_right.start_keyframe_id
    visual = split

    changed = await service.save_narration_cue(
        scene_id=scene.id,
        cue=replace(cue, zh=replace(cue.zh, text="他问：真的吗？她点头，这才是他最后的希望。")),
        expected_revision=visual.revision,
    )
    assert changed.director_script.scenes[0].shots == visual.director_script.scenes[0].shots
    assert changed.director_script.scenes[0].segments == visual.director_script.scenes[0].segments
    changed_cue = changed.director_script.scenes[0].narration_cues[0]
    assert changed_cue.zh.selected_audio_asset_id is None
    assert changed_cue.en.selected_audio_asset_id is not None
    assert changed.director_script.production_baseline_revision != changed.director_script.revision
    assert changed.keyframe_plan.segments == visual.keyframe_plan.segments
    assert "generate_segment_video" not in _allowed_actions(changed)
    with pytest.raises(ValueError, match="timing 已失效"):
        await service._media.generate_segment_video(
            segment_id=left.segment_id, expected_revision=changed.revision
        )
    assert StructuredDirectorStore(tmp_path, "a" * 32).read() == changed


def test_adjacent_narration_planning_keeps_fixed_visual_tail(tmp_path):
    asyncio.run(_test_adjacent_narration_planning_keeps_fixed_visual_tail(tmp_path))


async def _test_adjacent_narration_planning_keeps_fixed_visual_tail(tmp_path):
    store, service, provider, document = await narration_project(
        tmp_path, TwoNarrationFirstProposer()
    )
    for scene in document.director_script.scenes:
        cue = scene.narration_cues[0]
        document, _ = await synthesize_and_select_narration(
            service, cue.id, document.revision, document.narration_languages
        )

    context = json.loads(_script_json(document.director_script.scenes, document))
    first_timing = context["scenes"][0]["narration_timing"][0]
    second_timing = context["scenes"][1]["narration_timing"][0]
    first_cue = document.director_script.scenes[0].narration_cues[0]
    assert first_timing == {
        "cue_id": first_cue.id,
        "zh": {
            "selected_audio_asset_id": first_cue.zh.selected_audio_asset_id,
            "duration_seconds": 16,
        },
        "en": {
            "selected_audio_asset_id": first_cue.en.selected_audio_asset_id,
            "duration_seconds": 16,
        },
        "timing_language": "zh",
        "duration_seconds": 16,
        "visual_tail_seconds": 0.4,
        "planning_duration_seconds": 16.4,
    }
    assert second_timing["duration_seconds"] == 16
    assert second_timing["visual_tail_seconds"] == 0.0
    assert second_timing["planning_duration_seconds"] == 16.0

    registry = DirectorCommandRegistry(store)
    first, second = document.director_script.scenes
    document = insert_shot(
        registry,
        document,
        scene_id=first.id,
        durations=(8.2, 8.2),
        idempotency_key="plan-first-narration-with-tail",
    ).document
    document = insert_shot(
        registry,
        document,
        scene_id=second.id,
        durations=(8.0, 8.0),
        idempotency_key="plan-final-narration-without-tail",
    ).document
    baseline = document
    assert [
        sum(segment.duration_estimate_seconds for segment in scene.segments)
        for scene in baseline.director_script.scenes
    ] == [16.4, 16.0]

    clips = tuple(
        SceneAssemblyClip(segment.id, f"{index:032x}", None)
        for index, scene in enumerate(baseline.director_script.scenes)
        for segment in scene.segments
    )
    narrations = tuple(
        FinalNarrationPlacement(
            scene.narration_cues[0].id,
            scene.narration_cues[0].zh.selected_audio_asset_id,
            scene.segments[0].id,
            16.0,
        )
        for scene in baseline.director_script.scenes
    )
    plan = SceneAssemblyPlan(baseline.director_script.revision, clips, narrations)
    aligned = _align_clip_durations_to_narration(
        baseline,
        plan,
        [8.0, 8.0, 8.0, 8.0],
        {item.cue_id: 16.0 for item in narrations},
        0.1,
    )
    assert aligned == pytest.approx([8.0, 8.4, 8.0, 8.0])


def test_transient_progress_does_not_commit_or_survive_restart(tmp_path):
    asyncio.run(_test_transient_progress_does_not_commit_or_survive_restart(tmp_path))


async def _test_transient_progress_does_not_commit_or_survive_restart(tmp_path):
    store, service, _provider, document = await narration_project(tmp_path)
    cue = document.director_script.scenes[0].narration_cues[0]
    document = await service.generate_narration(
        cue_id=cue.id, language="zh", expected_revision=document.revision
    )
    document = await service._generation_observer.refresh_generation(document.generations[-1].id)
    generation = document.generations[-1]
    assert generation.phase is ReferenceGenerationPhase.RUNNING
    before = store.path.read_bytes()
    for progress in (0.51, 0.6, 0.8):
        observed = replace(generation, progress=progress, message=f"采样 ETA {progress}")
        assert store.update_generation(observed).revision == document.revision
    assert store.path.read_bytes() == before
    assert "progress" not in json.loads(before)["generations"][-1]
    assert b"ETA" not in before
    assert service.observed_generation(generation).progress == 0.8
    restored = StructuredDirectorStore(tmp_path, "a" * 32)
    assert restored.observed_generation(restored.read().generations[-1]).progress == 0
    with pytest.raises(RevisionConflictError):
        store._atomic_write(document)
    assert store.path.read_bytes() == before


def test_explicit_boundary_sharing_crosses_scene_without_reference_inference(tmp_path):
    asyncio.run(_test_explicit_boundary_sharing_crosses_scene_without_reference_inference(tmp_path))


async def _test_explicit_boundary_sharing_crosses_scene_without_reference_inference(tmp_path):
    store = StructuredDirectorStore(tmp_path, "b" * 32)
    service = StructuredDirectorService(
        store, RecordingProposer(), script_proposer=TwoSceneScriptProposer()
    )
    create_project(store)
    document = await service.prepare_references()
    document = await service.prepare_script(expected_revision=document.revision)
    document = await service.confirm_script(expected_revision=document.revision)
    document = await service.unlock_visual_production(expected_revision=document.revision)
    left, right = document.keyframe_plan.segments[:2]
    assert _final_transition(left.end_keyframe_id, right.start_keyframe_id) is None
    command = DirectorCommand(
        "keyframe.apply_operations",
        document.revision,
        "share-across-scenes",
        {
            "operations": [
                {
                    "op": "share_boundary",
                    "left_segment_id": left.segment_id,
                    "right_segment_id": right.segment_id,
                    "source_keyframe_id": left.end_keyframe_id,
                }
            ],
        },
    )
    result = DirectorCommandRegistry(store).execute(command)
    bindings = result.document.keyframe_plan.segments
    assert bindings[0].end_keyframe_id == bindings[1].start_keyframe_id
    assert bindings[0].end_enabled and bindings[1].start_enabled


class MixedProposer(NarrationScriptProposer):
    async def propose(self, **kwargs):
        narrated = await super().propose(**kwargs)
        drama = await RecordingScriptProposer().propose(**kwargs)
        return replace(narrated, scenes=(*narrated.scenes, *drama.scenes))


def test_drama_can_plan_long_shot_while_narration_waits_for_tts(tmp_path):
    asyncio.run(_mixed_authoring(tmp_path))


async def _mixed_authoring(tmp_path):
    store, _service, _provider, document = await narration_project(tmp_path, MixedProposer())
    narration, drama = document.director_script.scenes
    assert narration.driver == "narration" and narration.shots == ()
    assert drama.driver == "drama" and drama.shots
    result = insert_shot(
        DirectorCommandRegistry(store),
        document,
        scene_id=drama.id,
        after_shot_id=drama.shots[-1].id,
        idempotency_key="drama-shot-before-tts",
    )
    assert result.document.director_script.scenes[0] == narration
    assert (
        sum(
            segment.duration_estimate_seconds
            for segment in shot_segments_at(result.document.director_script.scenes[1], -1)
        )
        == 16
    )
    assert store.read() == result.document


def _scene_with(driver, *, cues=(), dialogue=()):
    segment = ShotSegment("1" * 32, ("2" * 32,), 3.0, "站台保持安静。", dialogue, None)
    shot = Shot("2" * 32, ("3" * 32,), "全景。", "固定。", "站台保持安静。", "", None)
    return Scene(
        "4" * 32, "末班车", "等待末班车。", "傍晚站台。", (shot,), (segment,), cues, driver
    )


def test_scene_model_rejects_drama_narration_and_narration_dialogue():
    cue = NarrationCue(
        "5" * 32,
        NarrationTrack("末班车还没有来。", 1),
        NarrationTrack("The last train has not come yet.", 1),
    )
    line = DialogueLine("3" * 32, "还会来吗？", "轻声")
    with pytest.raises(ValueError, match="Drama Scene 不能包含旁白"):
        _scene_with("drama", cues=(cue,))
    with pytest.raises(ValueError, match="Narration Scene 不能包含对白"):
        _scene_with("narration", cues=(cue,), dialogue=(line,))
    assert _scene_with("drama", dialogue=(line,)).narration_cues == ()
    assert _scene_with("narration", cues=(cue,)).narration_cues == (cue,)


def test_script_commands_cannot_add_dialogue_to_narration_or_cue_to_drama(tmp_path):
    asyncio.run(_driver_rule_commands(tmp_path))


async def _driver_rule_commands(tmp_path):
    store, service, _provider, document = await narration_project(tmp_path, MixedProposer())
    document = await select_audio(service, document)
    registry = DirectorCommandRegistry(store)
    document = insert_shot(registry, document).document
    narration, drama = document.director_script.scenes
    character_id = document.reference_library.characters[0].id
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="Narration Scene 不能包含对白"):
        registry.execute(
            DirectorCommand(
                "script.apply_operations",
                document.revision,
                "dialogue-into-narration",
                {
                    "scope": {"scene_ids": [narration.id]},
                    "operations": [
                        {
                            "op": "update_segment_fields",
                            "segment_id": narration.segments[0].id,
                            "fields": {
                                "dialogue_lines": [
                                    {
                                        "character_id": character_id,
                                        "text": "还会来吗？",
                                        "delivery": "轻声",
                                    }
                                ]
                            },
                        }
                    ],
                },
            )
        )
    track = {"text": "末班车还没有来。", "seed": 1}
    with pytest.raises(ValueError, match="Drama Scene 不能提供 narration_cue"):
        registry.execute(
            DirectorCommand(
                "script.apply_operations",
                document.revision,
                "drama-with-cue",
                {
                    "scope": {"scene_ids": [drama.id]},
                    "operations": [
                        {
                            "op": "insert_scene",
                            "after_scene_id": drama.id,
                            "scene": {
                                "title": "加场",
                                "summary": "补一段表演。",
                                "setting": "站台。",
                                "driver": "drama",
                                "shots": [shot_input()],
                                "narration_cue": {"zh": track, "en": track},
                            },
                        }
                    ],
                },
            )
        )
    assert store.path.read_bytes() == before
