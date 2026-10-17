from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from provider_factory import provider_registry
from script_helpers import shot_segments_at
from structured_director_fixtures import RecordingProvider, install_location
from video_recipes import (
    SegmentVideoAudioReference,
    SegmentVideoGenerationMode,
    SegmentVideoImageReference,
    SegmentVideoVideoReference,
    recipe_id,
    replace_video,
    save_video_inputs,
    video_mode,
    video_slot,
    video_wire_dict,
)

from core.director_commands import (
    CommandNeedsUserInput,
    DirectorCommand,
    DirectorCommandRegistry,
    SetKeyframeActivation,
    ShareKeyframeBoundary,
    SplitKeyframeBoundary,
    UpdateKeyframeFields,
    parse_script_operations_patch,
)
from core.director_proposals import (
    CharacterCardProposal,
    DialogueLineProposal,
    KeyframeOperationsProposal,
    KeyframePlanProposal,
    KeyframeSegmentProposal,
    KeyframeShotProposal,
    ReferenceLibraryProposal,
    SceneProposal,
    ShotProposal,
    ShotSegmentProposal,
    StructuredDirectorScriptProposal,
)
from core.project_settings import ProjectAspectRatio
from core.structured_director import (
    Asset,
    DirectorRunStatus,
    GenerationOperation,
    ImageAssetCategory,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)
from core.structured_director.models import NarrationCue, NarrationLanguage, NarrationTrack, Scene
from core.structured_director.script_index import shot_segments
from core.structured_director.service import (
    _director_recent_scene_ids,
)
from core.structured_director.store.domains.keyframe import (
    _translate_keyframe_plan_to_operations,
)


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(b"\x00\x00" * 8_000)
    return output.getvalue()


class _ReferenceCompiler:
    async def propose(self, **_kwargs: object) -> ReferenceLibraryProposal:
        return ReferenceLibraryProposal(
            characters=(
                CharacterCardProposal("甲", "穿蓝色外套。", "克制。"),
                CharacterCardProposal("乙", "穿红色外套。", "敏捷。"),
            )
        )


class _ScriptCompiler:
    async def propose(self, **kwargs: object) -> StructuredDirectorScriptProposal:
        characters = kwargs["characters"]

        def shot(action: str, character_id: str) -> ShotProposal:
            return ShotProposal(
                visible_character_ids=(character_id,),
                composition="中景。",
                camera_movement="固定。",
                action=action,
                audio_direction="环境声。",
                transition_in=None,
                segments=(
                    ShotSegmentProposal(
                        duration_estimate_seconds=3.0,
                        action=action,
                        dialogue_lines=(DialogueLineProposal(character_id, "好。", "轻声。"),),
                        boundary_from_previous=None,
                    ),
                ),
            )

        return StructuredDirectorScriptProposal(
            scenes=(
                SceneProposal(
                    title="连续动作",
                    summary="甲完成一个连续动作。",
                    setting="室内午后。",
                    shots=(
                        shot("甲抬头。", characters[0].id),
                        shot("乙转身。", characters[1].id),
                    ),
                    narration_cues=(),
                ),
            )
        )


class _TwoSceneScriptCompiler(_ScriptCompiler):
    async def propose(self, **kwargs: object) -> StructuredDirectorScriptProposal:
        proposal = await super().propose(**kwargs)
        first = proposal.scenes[0]
        second = replace(
            first,
            title="连续动作二",
            summary="同一空间里的下一段动作。",
            setting="室内午后，空间陈设不变。",
        )
        return StructuredDirectorScriptProposal((first, second))


class _NeverRoute:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(self, **_kwargs: object):
        self.calls += 1
        raise AssertionError("精确共享请求不应调用 Director inference。")


class _OperationsPlanner:
    async def propose(self, **kwargs: object) -> KeyframeOperationsProposal:
        scenes = kwargs["scenes"]
        shot = scenes[0].shots[0]
        segment = shot.segments[0]
        return KeyframeOperationsProposal(
            operations=(
                UpdateKeyframeFields(
                    keyframe_id=segment.start_keyframe_id,
                    prompt_text="operations 写入的首帧。",
                    visible_character_ids=tuple(item.id for item in shot.visible_characters),
                    environment_mode="none",
                    environment_none_reason="首帧是纯黑场，没有环境信息。",
                    environment_changed=True,
                ),
                SetKeyframeActivation(segment.id, True, False),
            ),
            decision_summary="只更新目标 Shot 的现有首帧槽位。",
        )


class _LockAwarePlanner:
    def __init__(self) -> None:
        self.scenes = ()

    async def propose(self, **kwargs: object) -> KeyframeOperationsProposal:
        self.scenes = kwargs["scenes"]
        return KeyframeOperationsProposal(
            operations=(),
            decision_summary="锁定节点保持不变。",
        )


async def _visual_project(
    directory: str,
    *,
    keyframe_planner: object | None = None,
    director_router: object | None = None,
    script_proposer: object | None = None,
):
    project_id = "a" * 32
    project = Path(directory) / project_id
    project.mkdir()
    store = StructuredDirectorStore(project, project_id)
    route = director_router or _NeverRoute()
    service = StructuredDirectorService(
        store,
        _ReferenceCompiler(),
        script_proposer=script_proposer or _ScriptCompiler(),
        keyframe_planner=keyframe_planner,
        registry=provider_registry(
            fl2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture"),
            ref2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture-ref"),
        ),
    )
    store.create_project(
        title="命令测试",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案\n\n两个连续镜头。",
        narration_languages=tuple(NarrationLanguage),
    )
    document = await service.prepare_references()
    document = await service.prepare_script(expected_revision=document.revision)
    document = await service.confirm_script(expected_revision=document.revision)
    document = service.snapshot_required()
    document = await service.unlock_visual_production(expected_revision=document.revision)
    return store, service, document, route


async def _location_project(
    directory: str,
    *,
    director_router: object | None = None,
):
    project_id = "c" * 32
    project = Path(directory) / project_id
    project.mkdir()
    store = StructuredDirectorStore(project, project_id)
    route = director_router or _NeverRoute()
    service = StructuredDirectorService(
        store,
        _ReferenceCompiler(),
        script_proposer=_TwoSceneScriptCompiler(),
    )
    store.create_project(
        title="地点命令测试",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案\n\n同一空间内的两个连续 Scene。",
        narration_languages=tuple(NarrationLanguage),
    )
    document = await service.prepare_references()
    document = await service.prepare_script(expected_revision=document.revision)
    document = await service.confirm_script(expected_revision=document.revision)
    # 每个 Scene 一个地点，视图已选定导入图片。
    for index, scene in enumerate(document.director_script.scenes):
        document = await service.import_image_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\nlocation-view" + bytes([index]),
            category=ImageAssetCategory.LOCATION_VIEW,
            expected_revision=document.revision,
        )
        document = install_location(
            store,
            view_asset_id=document.assets[-1].id,
            scene_ids=(scene.id,),
            name=scene.title,
        )
    return store, service, document, route


class DirectorCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_keyframe_plan_can_split_a_previously_shared_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            started, _ = store.begin_keyframe_plan(expected_revision=document.revision)
            assert started.director_script is not None
            scene = started.director_script.scenes[0]
            first, second = scene.shots
            shared_characters = first.visible_character_ids + second.visible_character_ids

            def proposal(*, continuous: bool) -> KeyframePlanProposal:
                first_end_characters = (
                    shared_characters if continuous else first.visible_character_ids
                )
                second_start_characters = (
                    shared_characters if continuous else second.visible_character_ids
                )
                boundary_prompt = "共享边界。" if continuous else "第二镜头独立首帧。"
                return KeyframePlanProposal(
                    (
                        KeyframeShotProposal(
                            first.id,
                            False,
                            "第一镜头首帧。",
                            first.visible_character_ids,
                            (
                                KeyframeSegmentProposal(
                                    shot_segments(scene, first.id)[0].id,
                                    "both",
                                    "共享边界。" if continuous else "第一镜头尾帧。",
                                    first_end_characters,
                                ),
                            ),
                        ),
                        KeyframeShotProposal(
                            second.id,
                            continuous,
                            boundary_prompt,
                            second_start_characters,
                            (
                                KeyframeSegmentProposal(
                                    shot_segments(scene, second.id)[0].id,
                                    "both",
                                    "第二镜头尾帧。",
                                    second.visible_character_ids,
                                ),
                            ),
                        ),
                    )
                )

            shared = store.apply_keyframe_plan(proposal(continuous=True))
            assert shared.keyframe_plan is not None
            left, right = shared.keyframe_plan.segments
            self.assertEqual(left.end_keyframe_id, right.start_keyframe_id)

            store.begin_keyframe_plan(expected_revision=shared.revision)
            split = store.apply_keyframe_plan(proposal(continuous=False))
            assert split.keyframe_plan is not None
            left, right = split.keyframe_plan.segments
            self.assertNotEqual(left.end_keyframe_id, right.start_keyframe_id)
            second_start = next(
                item for item in split.keyframe_plan.keyframes if item.id == right.start_keyframe_id
            )
            self.assertEqual(second_start.prompt_text, "第二镜头独立首帧。")

    async def test_keyframe_three_mutation_paths_have_equivalent_project_evolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            started, _ = store.begin_keyframe_plan(expected_revision=document.revision)
            assert started.director_script is not None
            assert started.director_script.production_baseline_scenes is not None
            proposal = KeyframePlanProposal(
                tuple(
                    KeyframeShotProposal(
                        shot.id,
                        False,
                        f"{shot.id} 首帧。",
                        shot.visible_character_ids,
                        tuple(
                            KeyframeSegmentProposal(
                                segment.id,
                                "both",
                                f"{segment.id} 尾帧。",
                                shot.visible_character_ids,
                            )
                            for segment in shot_segments(scene, shot.id)
                        ),
                    )
                    for scene in started.director_script.production_baseline_scenes
                    for shot in scene.shots
                )
            )
            operations = _translate_keyframe_plan_to_operations(
                started, proposal, target_shot_ids=()
            )
            source = store.path.parent
            operation_plan_root = Path(directory) / "operation-plan"
            direct_root = Path(directory) / "direct"
            shutil.copytree(source, operation_plan_root)
            shutil.copytree(source, direct_root)
            operation_plan_store = StructuredDirectorStore(operation_plan_root, started.project_id)
            direct_store = StructuredDirectorStore(direct_root, started.project_id)

            planned = store.apply_keyframe_plan(proposal)
            operation_planned = operation_plan_store.apply_keyframe_operation_plan(
                KeyframeOperationsProposal(operations, "等价操作计划。")
            )
            directly_planned, _receipt = direct_store.apply_keyframe_operations(
                operations,
                expected_revision=started.revision,
                command_id="equivalent-direct-operations",
            )

            for candidate in (operation_planned, directly_planned):
                self.assertEqual(candidate.keyframe_plan, planned.keyframe_plan)
                self.assertEqual(candidate.video_plan, planned.video_plan)
                self.assertEqual(candidate.final_assembly, planned.final_assembly)
                self.assertEqual(candidate.revision, planned.revision)

            def project_without_run(target: StructuredDirectorStore) -> dict[str, object]:
                payload = json.loads(target.path.read_text(encoding="utf-8"))
                structured = payload["structured_director"]
                structured.pop("director_runs", None)
                structured.pop("director_directives", None)
                return payload

            expected = project_without_run(store)
            self.assertEqual(project_without_run(operation_plan_store), expected)
            self.assertEqual(project_without_run(direct_store), expected)

    async def test_project_video_asset_can_be_added_as_segment_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.video_plan is not None
            segment_id = document.video_plan.segments[0].segment_id
            asset = Asset(
                "9" * 32,
                "video/mp4",
                24,
                "9" * 64,
                "assets/videos/segments/fog-candidate-9999999999.mp4",
                4.0,
            )
            image = Asset(
                "8" * 32,
                "image/png",
                12,
                "8" * 64,
                "assets/images/library/still-8888888888.png",
            )
            seeded = replace(
                document,
                revision=document.revision + 1,
                assets=(*document.assets, asset, image),
            )
            store._atomic_write(seeded)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            response = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/attach-candidate",
                json.dumps({"expected_revision": seeded.revision, "asset_id": asset.id}).encode(),
            )

            self.assertEqual(response.status, 200, response.body)
            attached = store.read()
            self.assertEqual(attached.revision, seeded.revision + 1)
            self.assertEqual(attached.video_plan, seeded.video_plan)
            self.assertEqual(attached.final_assembly, seeded.final_assembly)
            generation = attached.generations[-1]
            self.assertIs(generation.operation, GenerationOperation.ATTACH)
            self.assertIs(generation.kind, ReferenceGenerationKind.SEGMENT_VIDEO)
            self.assertIs(generation.phase, ReferenceGenerationPhase.SUCCEEDED)
            self.assertEqual(generation.target_id, segment_id)
            self.assertEqual(generation.output_asset_id, asset.id)
            self.assertEqual(generation.input_asset_ids, ())
            self.assertIsNone(generation.seed)
            self.assertIn("attach_segment_video_candidate", response.body["allowed_actions"])

            duplicate = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/attach-candidate",
                json.dumps({"expected_revision": attached.revision, "asset_id": asset.id}).encode(),
            )
            self.assertEqual(duplicate.status, 200, duplicate.body)
            self.assertEqual(store.read().revision, attached.revision)
            self.assertEqual(len(store.read().generations), len(attached.generations))

            hidden = await service.dismiss_generation(
                generation.id,
                expected_revision=attached.revision,
            )
            revived_response = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/attach-candidate",
                json.dumps({"expected_revision": hidden.revision, "asset_id": asset.id}).encode(),
            )
            self.assertEqual(revived_response.status, 200, revived_response.body)
            revived = store.read()
            self.assertEqual(len(revived.generations), len(attached.generations))
            self.assertEqual(revived.generations[-1].id, generation.id)
            self.assertFalse(revived.generations[-1].dismissed)

            selected_response = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/select",
                json.dumps({"expected_revision": revived.revision, "asset_id": asset.id}).encode(),
            )
            self.assertEqual(selected_response.status, 200, selected_response.body)
            selected = store.read()
            self.assertEqual(selected.video_plan.segments[0].selected_asset_id, asset.id)

            cleared_response = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/clear-selection",
                json.dumps({"expected_revision": selected.revision}).encode(),
            )
            self.assertEqual(cleared_response.status, 200, cleared_response.body)
            cleared = store.read()
            self.assertIsNone(cleared.video_plan.segments[0].selected_asset_id)

            wrong_type = await api.handle(
                "POST",
                f"/structured-director/segments/{segment_id}/videos/attach-candidate",
                json.dumps(
                    {
                        "expected_revision": cleared.revision,
                        "asset_id": image.id,
                    }
                ).encode(),
            )
            self.assertEqual(wrong_type.status, 400)
            self.assertIn("MP4", wrong_type.body["error"]["message"])
            self.assertEqual(store.read().revision, cleared.revision)

    async def test_scene_keyframe_scope_deduplicates_shared_slots_without_expanding_scene(self):
        from core.structured_director.keyframe_mutations import _apply_keyframe_operations
        from core.structured_director.keyframe_requests import _resolve_keyframe_generation_targets

        with tempfile.TemporaryDirectory() as directory:
            _store, service, document, _route = await _location_project(directory)
            document = await service.unlock_visual_production(expected_revision=document.revision)
            scene = document.director_script.scenes[1]
            left, right = (shot_segments(scene, shot.id)[0].id for shot in scene.shots)
            document = _apply_keyframe_operations(
                document,
                (
                    SetKeyframeActivation(left, True, True),
                    SetKeyframeActivation(right, True, False),
                    ShareKeyframeBoundary(left, right, None, "cross_shot"),
                ),
            ).document
            bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
            resolved = _resolve_keyframe_generation_targets(
                document, (scene.id, scene.shots[1].id, left)
            )
            self.assertEqual(
                resolved,
                (
                    bindings[left].start_keyframe_id,
                    bindings[left].end_keyframe_id,
                ),
            )
            self.assertEqual(bindings[left].end_keyframe_id, bindings[right].start_keyframe_id)
            with self.assertRaisesRegex(ValueError, "未激活"):
                _resolve_keyframe_generation_targets(document, (bindings[right].end_keyframe_id,))
            with self.assertRaisesRegex(ValueError, "尚无已启用"):
                _resolve_keyframe_generation_targets(
                    document, (document.director_script.scenes[0].id,)
                )

    async def test_keyframe_activation_can_return_to_an_empty_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, base, _route = await _visual_project(directory)
            assert base.keyframe_plan is not None
            binding = base.keyframe_plan.segments[0]
            registry = DirectorCommandRegistry(store)
            activated = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    base.revision,
                    "activate-start",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": binding.segment_id,
                                "start_enabled": True,
                                "end_enabled": False,
                            }
                        ]
                    },
                )
            )
            deactivated = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    activated.document.revision,
                    "deactivate-all",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": binding.segment_id,
                                "start_enabled": False,
                                "end_enabled": False,
                            }
                        ]
                    },
                )
            )

            assert deactivated.document.keyframe_plan is not None
            current = next(
                item
                for item in deactivated.document.keyframe_plan.segments
                if item.segment_id == binding.segment_id
            )
            self.assertFalse(current.start_enabled)
            self.assertFalse(current.end_enabled)
            self.assertEqual(deactivated.receipt.status, "succeeded")
            self.assertIn(binding.segment_id, deactivated.receipt.changed_ids)
            no_op = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    deactivated.document.revision,
                    "deactivate-all-again",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": binding.segment_id,
                                "start_enabled": False,
                                "end_enabled": False,
                            }
                        ]
                    },
                )
            )
            self.assertEqual(no_op.receipt.status, "noop")
            self.assertEqual(no_op.document.revision, deactivated.document.revision)

    async def test_manual_keyframe_activation_retargets_only_unrelated_revision_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service, base, _route = await _visual_project(directory)
            assert base.keyframe_plan is not None
            binding = base.keyframe_plan.segments[0]
            activated = await service.save_segment_keyframe_activation(
                segment_id=binding.segment_id,
                start_enabled=True,
                end_enabled=False,
                expected_revision=base.revision,
            )
            unrelated = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nunrelated-revision",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=activated.revision,
            )
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            stale_request = {
                "expected_revision": activated.revision,
                "start_enabled": False,
                "end_enabled": False,
                "expected_start_keyframe_id": binding.start_keyframe_id,
                "expected_end_keyframe_id": binding.end_keyframe_id,
                "expected_start_enabled": True,
                "expected_end_enabled": False,
                "expected_start_selected_asset_id": None,
                "expected_end_selected_asset_id": None,
            }
            retargeted = await api.handle(
                "PUT",
                f"/structured-director/segments/{binding.segment_id}/keyframe-activation",
                json.dumps(stale_request).encode(),
            )

            self.assertEqual(retargeted.status, 200)
            self.assertEqual(retargeted.body["revision"], unrelated.revision + 1)
            changed = await service.save_segment_keyframe_activation(
                segment_id=binding.segment_id,
                start_enabled=True,
                end_enabled=False,
                expected_revision=retargeted.body["revision"],
            )
            conflict = await api.handle(
                "PUT",
                f"/structured-director/segments/{binding.segment_id}/keyframe-activation",
                json.dumps(
                    {
                        **stale_request,
                        "expected_revision": retargeted.body["revision"],
                        "expected_start_enabled": False,
                    }
                ).encode(),
            )
            self.assertEqual(conflict.status, 409)
            self.assertEqual(conflict.body["error"]["code"], "revision_conflict")
            self.assertEqual(changed.revision, retargeted.body["revision"] + 1)

    async def test_recent_scene_context_survives_across_director_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, base, _route = await _visual_project(directory)
            assert base.director_script is not None
            scene = base.director_script.scenes[0]
            started, _ = store.begin_production_instruction(
                "先检查 Scene 1。",
                expected_revision=base.revision,
            )
            finished = store.finish_production_instruction()
            continued, _ = store.begin_production_instruction(
                "继续处理刚才的目标。",
                expected_revision=finished.revision,
            )

            self.assertGreater(continued.revision, started.revision)
            self.assertEqual(_director_recent_scene_ids(continued), (scene.id,))

    async def test_run_resume_command_uses_persisted_cursor_and_latest_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            document, _ = store.begin_production_instruction(
                "等待用户补充范围。",
                expected_revision=document.revision,
            )
            assert document.active_director_run is not None
            run_id = document.active_director_run.id
            waiting = store.wait_director_run(
                run_id=run_id,
                status=DirectorRunStatus.WAITING_USER,
                reason="缺少目标范围。",
                expected_revision=document.revision,
            )
            registry = DirectorCommandRegistry(store)
            api = StructuredDirectorHttpApi(_service, resource_path="/api/test/director")
            response = await api.handle(
                "POST",
                "/api/test/director/commands",
                json.dumps(
                    {
                        "name": "run.resume",
                        "expected_revision": waiting.revision,
                        "idempotency_key": "resume-with-scope",
                        "arguments": {
                            "run_id": run_id,
                            "raw_user_request": "只处理 Scene 1。",
                        },
                    },
                    ensure_ascii=False,
                ).encode(),
            )
            self.assertEqual(response.status, 200)
            resumed_document = store.read()

            assert resumed_document.active_director_run is not None
            self.assertIs(
                resumed_document.active_director_run.status,
                DirectorRunStatus.RUNNING,
            )
            self.assertEqual(resumed_document.active_director_run.cursor.step, 1)
            self.assertEqual(
                resumed_document.director_directives[-1].raw_user_request,
                "只处理 Scene 1。",
            )
            replay = registry.execute(
                DirectorCommand(
                    "run.resume",
                    resumed_document.revision,
                    "resume-with-scope-replay",
                    {
                        "run_id": run_id,
                        "raw_user_request": "只处理 Scene 1。",
                    },
                )
            )
            self.assertEqual(replay.receipt.status, "noop")
            self.assertEqual(replay.document.revision, resumed_document.revision)
            with self.assertRaisesRegex(ValueError, "缺失或未声明"):
                registry.execute(
                    DirectorCommand(
                        "run.resume",
                        replay.document.revision,
                        "resume-unknown-field",
                        {
                            "run_id": run_id,
                            "raw_user_request": None,
                            "force": True,
                        },
                    )
                )

    async def test_video_prompt_mode_and_clear_commands_preserve_history_and_scope(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.video_plan is not None
            scene = document.director_script.scenes[0]
            segment = scene.segments[0]
            character_id = segment.dialogue_lines[0].character_id
            document = await service.upload_reference_voice(
                card_id=character_id,
                media_type="audio/wav",
                content=_wav_bytes(),
                expected_revision=document.revision,
            )
            registry = DirectorCommandRegistry(store)
            selected_id = "d" * 32
            upscaled_id = "e" * 32

            def seed_selection(current):
                assert current.video_plan is not None
                assets = {item.id: item for item in current.assets}
                assets.setdefault(
                    selected_id,
                    Asset(
                        selected_id,
                        "video/mp4",
                        1,
                        "d" * 64,
                        "assets/videos/segments/selected-dddddddddd.mp4",
                        1.0,
                    ),
                )
                assets.setdefault(
                    upscaled_id,
                    Asset(
                        upscaled_id,
                        "video/mp4",
                        1,
                        "e" * 64,
                        "assets/videos/upscaled/upscaled-eeeeeeeeee.mp4",
                        1.0,
                    ),
                )
                seeded = replace(
                    current,
                    assets=tuple(assets.values()),
                    video_plan=replace(
                        current.video_plan,
                        segments=tuple(
                            replace(
                                item,
                                selected_asset_id=selected_id,
                                upscaled_asset_id=upscaled_id,
                            )
                            if item.segment_id == segment.id
                            else item
                            for item in current.video_plan.segments
                        ),
                    ),
                )
                seeded = replace(seeded, revision=store.read().revision + 1)
                store._atomic_write(seeded)
                return seeded

            document = seed_selection(document)
            noop = registry.execute(
                DirectorCommand(
                    "video.set_prompt",
                    document.revision,
                    "video-prompt-noop",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment.id,
                        "prompt_text": "",
                    },
                )
            )
            self.assertEqual(noop.receipt.status, "noop")
            assert noop.document.video_plan is not None
            self.assertEqual(noop.document.video_plan.segments[0].selected_asset_id, selected_id)

            prompt_command = DirectorCommand(
                "video.set_prompt",
                noop.document.revision,
                "video-prompt",
                {
                    "scope": {"scene_ids": [scene.id]},
                    "segment_id": segment.id,
                    "prompt_text": "角色抬头，固定镜头，保留环境声。",
                },
            )
            preview = await service.execute_director_command(
                DirectorCommand(
                    "project.preview_impact",
                    noop.document.revision,
                    "preview-video-prompt",
                    {
                        "command": {
                            "name": prompt_command.name,
                            "expected_revision": prompt_command.expected_revision,
                            "idempotency_key": prompt_command.idempotency_key,
                            "arguments": prompt_command.arguments,
                        }
                    },
                )
            )
            prompt = registry.execute(prompt_command)
            assert prompt.document.video_plan is not None
            self.assertEqual(
                prompt.document.video_plan.segments[0].prompt_text,
                "角色抬头，固定镜头，保留环境声。",
            )
            self.assertIsNone(prompt.document.video_plan.segments[0].selected_asset_id)
            self.assertIn(f"video_selection:{segment.id}", prompt.receipt.invalidated)
            self.assertIn(f"video_upscale:{segment.id}", prompt.receipt.invalidated)
            assert preview.data is not None
            self.assertEqual(set(preview.data["invalidated"]), set(prompt.receipt.invalidated))
            self.assertEqual(set(preview.data["preserved"]), set(prompt.receipt.preserved))

            document = seed_selection(prompt.document)
            mode = registry.execute(
                DirectorCommand(
                    "video.set_recipe",
                    document.revision,
                    "video-mode",
                    video_wire_dict(
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "segment_id": segment.id,
                            "generation_mode": "fl2va",
                        }
                    ),
                )
            )
            assert mode.document.video_plan is not None
            self.assertEqual(
                video_mode(mode.document.video_plan.segments[0]).value,
                "fl2va",
            )
            self.assertIsNone(mode.document.video_plan.segments[0].selected_asset_id)
            repeated_mode = registry.execute(
                DirectorCommand(
                    "video.set_recipe",
                    mode.document.revision,
                    "video-mode-repeat",
                    video_wire_dict(
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "segment_id": segment.id,
                            "generation_mode": "fl2va",
                        }
                    ),
                )
            )
            self.assertEqual(repeated_mode.receipt.status, "noop")

            document = seed_selection(repeated_mode.document)
            cleared = registry.execute(
                DirectorCommand(
                    "video.clear_selection",
                    document.revision,
                    "video-clear",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment.id,
                    },
                )
            )
            assert cleared.document.video_plan is not None
            self.assertIsNone(cleared.document.video_plan.segments[0].selected_asset_id)
            self.assertIsNone(cleared.document.video_plan.segments[0].upscaled_asset_id)
            self.assertEqual(cleared.document.assets, document.assets)
            self.assertEqual(cleared.document.generations, document.generations)
            repeated_clear = registry.execute(
                DirectorCommand(
                    "video.clear_selection",
                    cleared.document.revision,
                    "video-clear-repeat",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment.id,
                    },
                )
            )
            self.assertEqual(repeated_clear.receipt.status, "noop")

            before = store.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "scope"):
                registry.execute(
                    DirectorCommand(
                        "video.set_prompt",
                        cleared.document.revision,
                        "video-scope",
                        {
                            "scope": {"scene_ids": ["f" * 32]},
                            "segment_id": segment.id,
                            "prompt_text": "越界",
                        },
                    )
                )
            with self.assertRaisesRegex(ValueError, "未声明字段"):
                registry.execute(
                    DirectorCommand(
                        "video.set_recipe",
                        cleared.document.revision,
                        "video-unknown",
                        video_wire_dict(
                            {
                                "scope": {"scene_ids": [scene.id]},
                                "segment_id": segment.id,
                                "generation_mode": "fl2va",
                                "seed": 1,
                            }
                        ),
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_reselecting_character_voice_does_not_change_explicit_audio_references(
        self,
    ) -> None:
        from core.structured_director.models import (
            FinalAssemblyClip,
            FinalAssemblyPlan,
            StructuredDirectorStatus,
        )

        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.video_plan is not None
            scene = document.director_script.scenes[0]
            first_segment = scene.segments[0]
            second_segment = shot_segments_at(scene, 1)[0]
            character_id = first_segment.dialogue_lines[0].character_id
            document = await service.upload_reference_voice(
                card_id=character_id,
                media_type="audio/wav",
                content=_wav_bytes(),
                expected_revision=document.revision,
            )
            document = await service.save_segment_video_recipe(
                segment_id=first_segment.id,
                recipe_id=recipe_id(SegmentVideoGenerationMode.REF2VA),
                expected_revision=document.revision,
            )
            current_voice_id = next(
                item.voice_reference_asset_id
                for item in document.reference_library.characters
                if item.id == character_id
            )
            assert current_voice_id is not None
            document = await save_video_inputs(
                service,
                segment_id=first_segment.id,
                prompt_text="使用 <Audio 1> 作为参考。",
                additional_image_references=(),
                audio_references=(SegmentVideoAudioReference(current_voice_id, "角色音色参考。"),),
                expected_revision=document.revision,
            )
            video = Asset(
                "d" * 32,
                "video/mp4",
                1,
                "d" * 64,
                "assets/videos/segments/selected-dddddddddd.mp4",
                3.0,
            )
            upscale = Asset(
                "e" * 32,
                "video/mp4",
                1,
                "e" * 64,
                "assets/videos/upscaled/upscaled-eeeeeeeeee.mp4",
                3.0,
            )
            videos = replace(
                document.video_plan,
                segments=tuple(
                    replace(item, selected_asset_id=video.id, upscaled_asset_id=upscale.id)
                    for item in document.video_plan.segments
                ),
            )
            seeded = replace(
                document,
                revision=document.revision + 1,
                status=StructuredDirectorStatus.REVIEWING_FINAL,
                workspace_layers=replace(document.workspace_layers, final_assembly_unlocked=True),
                assets=(*document.assets, video, upscale),
                video_plan=videos,
                final_assembly=FinalAssemblyPlan(
                    document.director_script.revision,
                    tuple(
                        FinalAssemblyClip(scene.id, upscale.id, upscale.id, None)
                        for scene in document.director_script.scenes
                    ),
                ),
            )
            store._atomic_write(seeded)

            replacement_voice = bytearray(_wav_bytes())
            replacement_voice[-1] = 1
            replacement_content = bytes(replacement_voice)
            active = ReferenceGeneration(
                id="f" * 32,
                kind=ReferenceGenerationKind.SEGMENT_VIDEO,
                operation=GenerationOperation.RENDER,
                target_id=first_segment.id,
                phase=ReferenceGenerationPhase.QUEUED,
                progress=0.0,
                message="视频排队中",
                prompt_text="使用显式参考音频。",
                input_asset_ids=(current_voice_id,),
                sample_text=None,
                seed=42,
                plugin_id="test.video",
                plugin_version=1,
                external_id="provider-video",
                output_asset_id=None,
                error_code=None,
                cancellation_requested=False,
                retry_of=None,
                duration_seconds=3.0,
            )
            with_active = store.create_generation(active, expected_revision=seeded.revision)
            updated = await service.upload_reference_voice(
                card_id=character_id,
                media_type="audio/wav",
                content=replacement_content,
                expected_revision=with_active.revision,
            )

            assert updated.video_plan is not None
            current = {item.segment_id: item for item in updated.video_plan.segments}
            self.assertEqual(current[first_segment.id].selected_asset_id, video.id)
            self.assertEqual(current[first_segment.id].upscaled_asset_id, upscale.id)
            self.assertEqual(
                video_slot(current[first_segment.id], "reference_audios")[0].asset_id,
                current_voice_id,
            )
            self.assertEqual(current[second_segment.id].selected_asset_id, video.id)
            self.assertEqual(current[second_segment.id].upscaled_asset_id, upscale.id)
            self.assertEqual(updated.final_assembly, seeded.final_assembly)
            self.assertEqual(updated.generations, with_active.generations)
            self.assertEqual(len(updated.assets), len(seeded.assets) + 1)

    async def test_video_set_plan_video_references_strict_persisted_and_mode_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.video_plan is not None
            scene = document.director_script.scenes[0]
            segment = scene.segments[0]
            reference_video = Asset(
                "9" * 32,
                "video/mp4",
                24,
                "9" * 64,
                "assets/videos/imported/reference-9999999999.mp4",
                5.0,
            )
            seeded = replace(
                document,
                revision=document.revision + 1,
                assets=(*document.assets, reference_video),
                video_plan=replace(
                    document.video_plan,
                    segments=tuple(
                        replace_video(item, generation_mode=SegmentVideoGenerationMode.REF2VA)
                        if item.segment_id == segment.id
                        else item
                        for item in document.video_plan.segments
                    ),
                ),
            )
            store._atomic_write(seeded)
            registry = DirectorCommandRegistry(store)
            base_arguments = video_wire_dict(
                {
                    "scope": {"scene_ids": [scene.id]},
                    "segment_id": segment.id,
                    "prompt_text": "使用 <Video 1> 的运镜。",
                    "additional_image_references": [],
                    "audio_references": [],
                }
            )
            with self.assertRaisesRegex(ValueError, "未声明字段"):
                registry.execute(
                    DirectorCommand(
                        "video.update_recipe_inputs",
                        seeded.revision,
                        "video-plan-missing-video-references",
                        {key: value for key, value in base_arguments.items() if key != "params"},
                    )
                )
            with self.assertRaisesRegex(ValueError, "0 到 3 项"):
                registry.execute(
                    DirectorCommand(
                        "video.update_recipe_inputs",
                        seeded.revision,
                        "video-plan-too-many-video-references",
                        video_wire_dict(
                            {
                                **base_arguments,
                                "video_references": [
                                    {
                                        "asset_id": reference_video.id,
                                        "description": f"参考 {index}。",
                                    }
                                    for index in range(4)
                                ],
                            }
                        ),
                    )
                )
            with self.assertRaisesRegex(ValueError, "不能重复"):
                registry.execute(
                    DirectorCommand(
                        "video.update_recipe_inputs",
                        seeded.revision,
                        "video-plan-duplicate-video-references",
                        video_wire_dict(
                            {
                                **base_arguments,
                                "video_references": [
                                    {"asset_id": reference_video.id, "description": "参考运镜。"},
                                    {"asset_id": reference_video.id, "description": "重复引用。"},
                                ],
                            }
                        ),
                    )
                )
            with self.assertRaisesRegex(ValueError, "填写说明"):
                registry.execute(
                    DirectorCommand(
                        "video.update_recipe_inputs",
                        seeded.revision,
                        "video-plan-empty-video-description",
                        video_wire_dict(
                            {
                                **base_arguments,
                                "video_references": [
                                    {"asset_id": reference_video.id, "description": "  "}
                                ],
                            }
                        ),
                    )
                )
            self.assertEqual(store.read().revision, seeded.revision)

            saved = registry.execute(
                DirectorCommand(
                    "video.update_recipe_inputs",
                    seeded.revision,
                    "video-plan-with-video-references",
                    video_wire_dict(
                        {
                            **base_arguments,
                            "video_references": [
                                {"asset_id": reference_video.id, "description": "参考运镜与节奏。"}
                            ],
                        }
                    ),
                )
            )
            self.assertEqual(saved.receipt.status, "succeeded")
            reloaded = store.read()
            assert reloaded.video_plan is not None
            reloaded_video = next(
                item for item in reloaded.video_plan.segments if item.segment_id == segment.id
            )
            self.assertEqual(
                video_slot(reloaded_video, "reference_videos"),
                (SegmentVideoVideoReference(reference_video.id, "参考运镜与节奏。"),),
            )

            with self.assertRaisesRegex(ValueError, "切换为 FL2VA"):
                registry.execute(
                    DirectorCommand(
                        "video.set_recipe",
                        reloaded.revision,
                        "video-mode-fl2va-blocked-by-video-references",
                        video_wire_dict(
                            {
                                "scope": {"scene_ids": [scene.id]},
                                "segment_id": segment.id,
                                "generation_mode": "fl2va",
                            }
                        ),
                    )
                )
            self.assertEqual(store.read().revision, reloaded.revision)

    async def test_script_operations_reject_unknown_fields_and_scope_without_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            shot = scene.shots[0]
            registry = DirectorCommandRegistry(store)
            before = store.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "未声明字段"):
                registry.execute(
                    DirectorCommand(
                        "script.apply_operations",
                        document.revision,
                        "script-unknown-field",
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "operations": [
                                {
                                    "op": "update_shot_fields",
                                    "shot_id": shot.id,
                                    "fields": {"selected_asset_id": "f" * 32},
                                }
                            ],
                        },
                    )
                )
            with self.assertRaisesRegex(ValueError, "scope"):
                registry.execute(
                    DirectorCommand(
                        "script.apply_operations",
                        document.revision,
                        "script-invalid-scope",
                        {
                            "scope": {"scene_ids": ["f" * 32]},
                            "operations": [
                                {
                                    "op": "update_shot_fields",
                                    "shot_id": shot.id,
                                    "fields": {"composition": "近景。"},
                                }
                            ],
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_script_field_edit_preserves_existing_keyframe_selection_and_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.keyframe_plan is not None
            scene = document.director_script.scenes[0]
            shot = scene.shots[0]
            binding = document.keyframe_plan.segments[0]
            keyframe_id = binding.start_keyframe_id
            document = (
                DirectorCommandRegistry(store)
                .execute(
                    DirectorCommand(
                        "keyframe.apply_operations",
                        document.revision,
                        "activate-script-invalidation-target",
                        {
                            "operations": [
                                {
                                    "op": "set_activation",
                                    "segment_id": binding.segment_id,
                                    "start_enabled": True,
                                    "end_enabled": False,
                                }
                            ],
                        },
                    )
                )
                .document
            )
            document = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nscript-selection",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=document.revision,
            )
            asset = document.assets[-1]
            document = await service.select_keyframe(
                keyframe_id=keyframe_id,
                asset_id=asset.id,
                expected_revision=document.revision,
            )
            execution = DirectorCommandRegistry(store).execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "script-visual-invalidation",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_shot_fields",
                                "shot_id": shot.id,
                                "fields": {"composition": "人物面部近景。"},
                            }
                        ],
                    },
                )
            )

            self.assertNotIn(
                f"keyframe_selection:{keyframe_id}",
                execution.receipt.invalidated,
            )
            self.assertIn(asset, execution.document.assets)
            assert execution.document.keyframe_plan is not None
            self.assertEqual(
                next(
                    item.selected_asset_id
                    for item in execution.document.keyframe_plan.keyframes
                    if item.id == keyframe_id
                ),
                asset.id,
            )

    async def test_script_segment_field_edit_preserves_video_plan_metadata(self) -> None:

        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.keyframe_plan is not None
            assert document.video_plan is not None
            scene = document.director_script.scenes[0]
            segment = scene.segments[0]
            original_binding = next(
                item for item in document.keyframe_plan.segments if item.segment_id == segment.id
            )
            image = Asset(
                "4" * 32,
                "image/png",
                12,
                "4" * 64,
                "assets/images/library/additional-4444444444.png",
            )
            audio = Asset(
                "5" * 32,
                "audio/wav",
                24,
                "5" * 64,
                "assets/audio/imported/reference-5555555555.wav",
                3.0,
            )
            selected = Asset(
                "6" * 32,
                "video/mp4",
                24,
                "6" * 64,
                "assets/videos/segments/selected-6666666666.mp4",
                3.0,
            )
            upscaled = Asset(
                "7" * 32,
                "video/mp4",
                24,
                "7" * 64,
                "assets/videos/upscaled/upscaled-7777777777.mp4",
                3.0,
            )
            reference_video = Asset(
                "8" * 32,
                "video/mp4",
                24,
                "8" * 64,
                "assets/videos/imported/reference-8888888888.mp4",
                5.0,
            )
            original_video = next(
                item for item in document.video_plan.segments if item.segment_id == segment.id
            )
            planned_video = replace_video(
                original_video,
                prompt_text="使用 <Picture 1>、<Picture 2> 与 <Audio 1> 保持连续性。",
                generation_mode=SegmentVideoGenerationMode.REF2VA,
                additional_image_references=(
                    SegmentVideoImageReference(image.id, "穹顶的巨型触手。"),
                ),
                audio_references=(SegmentVideoAudioReference(audio.id, "保留撞击声的质感。"),),
                video_references=(
                    SegmentVideoVideoReference(reference_video.id, "参考运镜与节奏。"),
                ),
                selected_asset_id=selected.id,
                upscaled_asset_id=upscaled.id,
            )
            seeded = replace(
                document,
                revision=document.revision + 1,
                assets=(*document.assets, image, audio, selected, upscaled, reference_video),
                video_plan=replace(
                    document.video_plan,
                    segments=tuple(
                        planned_video if item.segment_id == segment.id else item
                        for item in document.video_plan.segments
                    ),
                ),
            )
            store._atomic_write(seeded)

            execution = DirectorCommandRegistry(store).execute(
                DirectorCommand(
                    "script.apply_operations",
                    seeded.revision,
                    "script-segment-video-plan-preservation",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_segment_fields",
                                "segment_id": segment.id,
                                "fields": {
                                    "action": "甲迅速抬头并后退。",
                                    "duration_estimate_seconds": 4.0,
                                },
                            }
                        ],
                    },
                )
            )

            assert execution.document.keyframe_plan is not None
            assert execution.document.video_plan is not None
            updated_binding = next(
                item
                for item in execution.document.keyframe_plan.segments
                if item.segment_id == segment.id
            )
            updated_video = next(
                item
                for item in execution.document.video_plan.segments
                if item.segment_id == segment.id
            )
            self.assertEqual(updated_binding, original_binding)
            self.assertEqual(updated_video.prompt_text, planned_video.prompt_text)
            self.assertEqual(video_mode(updated_video), video_mode(planned_video))
            self.assertEqual(
                video_slot(updated_video, "additional_images"),
                video_slot(planned_video, "additional_images"),
            )
            self.assertEqual(
                video_slot(updated_video, "reference_audios"),
                video_slot(planned_video, "reference_audios"),
            )
            self.assertEqual(
                video_slot(updated_video, "reference_videos"),
                video_slot(planned_video, "reference_videos"),
            )
            self.assertIsNone(updated_video.selected_asset_id)
            self.assertIsNone(updated_video.upscaled_asset_id)
            self.assertIn(f"video_selection:{segment.id}", execution.receipt.invalidated)
            self.assertIn(f"video_upscale:{segment.id}", execution.receipt.invalidated)

    async def test_script_shot_crud_rebuilds_current_plans_without_deleting_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            first_shot, second_shot = scene.shots
            character_id = document.reference_library.characters[0].id
            assert document.keyframe_plan is not None
            original_bindings = {
                item.segment_id: (item.start_keyframe_id, item.end_keyframe_id)
                for item in document.keyframe_plan.segments
            }
            registry = DirectorCommandRegistry(store)
            inserted = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "script-shot-insert",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "insert_shot",
                                "scene_id": scene.id,
                                "after_shot_id": first_shot.id,
                                "shot": _script_shot_payload(character_id, "新镜头动作。"),
                            }
                        ],
                    },
                )
            )
            assert inserted.document.director_script is not None
            shots = inserted.document.director_script.scenes[0].shots
            self.assertEqual(len(shots), 3)
            inserted_shot = shots[1]
            self.assertNotIn(inserted_shot.id, {first_shot.id, second_shot.id})
            inserted_segment_id = shot_segments(
                inserted.document.director_script.scenes[0], inserted_shot.id
            )[0].id
            assert inserted.document.keyframe_plan is not None
            assert inserted.document.video_plan is not None
            self.assertIn(
                inserted_segment_id,
                {item.segment_id for item in inserted.document.keyframe_plan.segments},
            )
            self.assertIn(
                inserted_segment_id,
                {item.segment_id for item in inserted.document.video_plan.segments},
            )
            inserted_bindings = {
                item.segment_id: (item.start_keyframe_id, item.end_keyframe_id)
                for item in inserted.document.keyframe_plan.segments
            }
            for segment_id, binding in original_bindings.items():
                self.assertEqual(inserted_bindings[segment_id], binding)
            moved = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    inserted.document.revision,
                    "script-shot-move",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "move_shot",
                                "scene_id": scene.id,
                                "shot_id": inserted_shot.id,
                                "after_shot_id": None,
                            }
                        ],
                    },
                )
            )
            assert moved.document.director_script is not None
            self.assertEqual(
                moved.document.director_script.scenes[0].shots[0].id,
                inserted_shot.id,
            )
            deleted = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    moved.document.revision,
                    "script-shot-delete",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "delete_shot",
                                "scene_id": scene.id,
                                "shot_id": inserted_shot.id,
                            }
                        ],
                    },
                )
            )
            assert deleted.document.director_script is not None
            self.assertEqual(
                [item.id for item in deleted.document.director_script.scenes[0].shots],
                [first_shot.id, second_shot.id],
            )
            self.assertEqual(deleted.document.assets, document.assets)
            self.assertEqual(deleted.document.generations, document.generations)

    async def test_script_scene_fields_update_preserves_structure_and_location(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            document = install_location(
                store, scene_ids=(document.director_script.scenes[0].id,), name="大厅"
            )
            scene = document.director_script.scenes[0]
            location = document.location_library.locations[-1]
            execution = DirectorCommandRegistry(store).execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "script-scene-fields",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_scene_fields",
                                "scene_id": scene.id,
                                "fields": {"title": "拐角通道·时空重叠交错"},
                            }
                        ],
                    },
                )
            )
            assert execution.document.director_script is not None
            updated = execution.document.director_script.scenes[0]
            self.assertEqual(updated.title, "拐角通道·时空重叠交错")
            self.assertEqual(updated.summary, scene.summary)
            self.assertEqual(updated.setting, scene.setting)
            self.assertEqual(updated.shots, scene.shots)
            self.assertEqual(updated.driver, scene.driver)
            self.assertEqual(updated.location_id, location.id)
            self.assertEqual(execution.receipt.new_revision, document.revision + 1)
            self.assertIn(scene.id, execution.receipt.changed_ids)
            replay = DirectorCommandRegistry(store).execute(
                DirectorCommand(
                    "script.apply_operations",
                    execution.document.revision,
                    "script-scene-fields-repeat",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_scene_fields",
                                "scene_id": scene.id,
                                "fields": {"title": "拐角通道·时空重叠交错"},
                            }
                        ],
                    },
                )
            )
            self.assertEqual(replay.receipt.status, "noop")
            with self.assertRaisesRegex(ValueError, "非空 object"):
                parse_script_operations_patch(
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {"op": "update_scene_fields", "scene_id": scene.id, "fields": {}}
                        ],
                    }
                )
            with self.assertRaisesRegex(ValueError, "未声明字段"):
                parse_script_operations_patch(
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_scene_fields",
                                "scene_id": scene.id,
                                "fields": {"driver": "narration"},
                            }
                        ],
                    }
                )

    async def test_script_scene_insert_split_move_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.keyframe_plan is not None
            document = install_location(store, scene_ids=(document.director_script.scenes[0].id,))
            scene = document.director_script.scenes[0]
            first_shot, second_shot = scene.shots
            original_bindings = {
                item.segment_id: (item.start_keyframe_id, item.end_keyframe_id)
                for item in document.keyframe_plan.segments
            }
            registry = DirectorCommandRegistry(store)
            split = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "script-scene-split",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "insert_scene",
                                "after_scene_id": scene.id,
                                "scene": {
                                    "title": "母船甲板",
                                    "summary": "转移到数海里外的母船甲板。",
                                    "setting": "夜间母船甲板，海风强烈。",
                                    "move_shot_ids": [second_shot.id],
                                },
                            }
                        ],
                    },
                )
            )
            assert split.document.director_script is not None
            scenes = split.document.director_script.scenes
            self.assertEqual([item.id for item in scenes[0].shots], [first_shot.id])
            new_scene = scenes[1]
            self.assertNotEqual(new_scene.id, scene.id)
            self.assertEqual(new_scene.title, "母船甲板")
            self.assertEqual(new_scene.driver, "drama")
            self.assertIsNone(new_scene.location_id)
            self.assertEqual([item.id for item in new_scene.shots], [second_shot.id])
            # 移出原地点的 Shot 不再保留视图绑定；留下的 Shot 保持原绑定。
            self.assertIsNone(new_scene.shots[0].view_id)
            self.assertEqual(scenes[0].shots[0].view_id, first_shot.view_id)
            self.assertIsNotNone(first_shot.view_id)
            self.assertEqual(split.receipt.new_revision, document.revision + 1)
            self.assertIn(new_scene.id, split.receipt.changed_ids)
            self.assertIn(new_scene.id, split.receipt.decision_summary or "")
            assert split.document.keyframe_plan is not None
            self.assertEqual(
                {
                    item.segment_id: (item.start_keyframe_id, item.end_keyframe_id)
                    for item in split.document.keyframe_plan.segments
                },
                original_bindings,
            )

            with self.assertRaisesRegex(ValueError, "超出已授权 Scene scope"):
                registry.execute(
                    DirectorCommand(
                        "script.apply_operations",
                        split.document.revision,
                        "script-scene-out-of-scope",
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "operations": [
                                {
                                    "op": "move_scene",
                                    "scene_id": scene.id,
                                    "after_scene_id": new_scene.id,
                                }
                            ],
                        },
                    )
                )
            moved_back = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    split.document.revision,
                    "script-scene-merge-back",
                    {
                        "scope": {"scene_ids": [scene.id, new_scene.id]},
                        "operations": [
                            {
                                "op": "move_scene",
                                "scene_id": new_scene.id,
                                "after_scene_id": None,
                            },
                            {
                                "op": "move_shot",
                                "scene_id": new_scene.id,
                                "shot_id": second_shot.id,
                                "target_scene_id": scene.id,
                                "after_shot_id": first_shot.id,
                            },
                            {"op": "delete_scene", "scene_id": new_scene.id},
                        ],
                    },
                )
            )
            assert moved_back.document.director_script is not None
            self.assertEqual(
                [item.id for item in moved_back.document.director_script.scenes],
                [scene.id],
            )
            # 移出后再移回的 Shot 不会自动恢复视图绑定。
            self.assertEqual(
                moved_back.document.director_script.scenes[0].shots,
                (scene.shots[0], replace(scene.shots[1], view_id=None)),
            )
            self.assertEqual(moved_back.document.assets, document.assets)
            self.assertEqual(moved_back.document.generations, document.generations)

    async def test_script_scene_operations_reject_invalid_states_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            character_id = document.reference_library.characters[0].id
            registry = DirectorCommandRegistry(store)
            before = store.path.read_bytes()
            new_scene = {
                "title": "新场景",
                "summary": "新的时空。",
                "setting": "室外。",
            }
            cases = (
                ("仍包含 Shot", [{"op": "delete_scene", "scene_id": scene.id}]),
                (
                    "至少需要一个 Shot",
                    [{"op": "insert_scene", "after_scene_id": scene.id, "scene": new_scene}],
                ),
                (
                    "Scene 不存在",
                    [
                        {
                            "op": "insert_scene",
                            "after_scene_id": "f" * 32,
                            "scene": {
                                **new_scene,
                                "shots": [_script_shot_payload(character_id, "动作。")],
                            },
                        }
                    ],
                ),
                (
                    "narration_cue",
                    [
                        {
                            "op": "insert_scene",
                            "after_scene_id": None,
                            "scene": {**new_scene, "driver": "narration"},
                        }
                    ],
                ),
                (
                    "自身之后",
                    [{"op": "move_scene", "scene_id": scene.id, "after_scene_id": scene.id}],
                ),
            )
            for index, (message, operations) in enumerate(cases):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    registry.execute(
                        DirectorCommand(
                            "script.apply_operations",
                            document.revision,
                            f"script-scene-invalid-{index}",
                            {"scope": {"scene_ids": [scene.id]}, "operations": operations},
                        )
                    )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_script_insert_narration_scene_creates_unplanned_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            execution = DirectorCommandRegistry(store).execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "script-scene-insert-narration",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "insert_scene",
                                "after_scene_id": None,
                                "scene": {
                                    "title": "序章旁白",
                                    "summary": "旁白引入。",
                                    "setting": "黑场。",
                                    "driver": "narration",
                                    "narration_cue": {
                                        "zh": {"text": "很多年以后，他仍记得那晚的海。", "seed": 7},
                                        "en": {
                                            "text": "Years later, he still remembered the sea.",
                                            "seed": 7,
                                        },
                                    },
                                },
                            }
                        ],
                    },
                )
            )
            assert execution.document.director_script is not None
            inserted = execution.document.director_script.scenes[0]
            self.assertEqual(inserted.driver, "narration")
            self.assertEqual(inserted.shots, ())
            (cue,) = inserted.narration_cues
            self.assertEqual(cue.zh.text, "很多年以后，他仍记得那晚的海。")
            self.assertEqual(cue.en.text, "Years later, he still remembered the sea.")
            self.assertEqual(inserted.segments, ())
            self.assertEqual(cue.selected_audio_asset_ids, ())
            self.assertEqual(execution.document.director_script.scenes[1].id, scene.id)

    async def test_script_segment_crud_allows_only_a_valid_atomic_final_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            shot = scene.shots[0]
            original = shot_segments(scene, shot.id)[0]
            registry = DirectorCommandRegistry(store)
            inserted = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    document.revision,
                    "script-segment-insert",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "insert_segment",
                                "shot_id": shot.id,
                                "after_segment_id": original.id,
                                "segment": _script_segment_payload(
                                    document.reference_library.characters[0].id,
                                    "新增动作。",
                                    boundary=True,
                                ),
                            }
                        ],
                    },
                )
            )
            assert inserted.document.director_script is not None
            segments = shot_segments_at(inserted.document.director_script.scenes[0], 0)
            added = segments[1]
            moved = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    inserted.document.revision,
                    "script-segment-move-and-fix-boundaries",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "move_segment",
                                "shot_id": shot.id,
                                "segment_id": added.id,
                                "after_segment_id": None,
                            },
                            {
                                "op": "update_segment_fields",
                                "segment_id": added.id,
                                "fields": {
                                    "boundary_from_previous": None,
                                    "duration_estimate_seconds": 4,
                                },
                            },
                            {
                                "op": "update_segment_fields",
                                "segment_id": original.id,
                                "fields": {"boundary_from_previous": _boundary_payload()},
                            },
                        ],
                    },
                )
            )
            assert moved.document.director_script is not None
            segments = shot_segments_at(moved.document.director_script.scenes[0], 0)
            self.assertEqual([item.id for item in segments], [added.id, original.id])
            self.assertEqual(segments[0].duration_estimate_seconds, 4)
            before = store.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "后续 Segment"):
                registry.execute(
                    DirectorCommand(
                        "script.apply_operations",
                        moved.document.revision,
                        "script-invalid-boundary",
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "operations": [
                                {
                                    "op": "update_segment_fields",
                                    "segment_id": original.id,
                                    "fields": {"boundary_from_previous": None},
                                }
                            ],
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)
            deleted = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    moved.document.revision,
                    "script-segment-delete",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "delete_segment",
                                "shot_id": shot.id,
                                "segment_id": original.id,
                            }
                        ],
                    },
                )
            )
            assert deleted.document.director_script is not None
            self.assertEqual(
                [
                    item.id
                    for item in shot_segments_at(deleted.document.director_script.scenes[0], 0)
                ],
                [added.id],
            )

    async def test_script_split_merge_preserves_explicit_id_and_uses_formal_update(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            shot = scene.shots[0]
            original = shot_segments(scene, shot.id)[0]
            character_id = document.reference_library.characters[0].id
            registry = DirectorCommandRegistry(store)
            repaired = registry.execute(
                DirectorCommand(
                    "project.apply_repair_patch",
                    document.revision,
                    "repair-before-formal-command",
                    {
                        "run_id": "script-gap",
                        "reason_code": "CAPABILITY_GAP",
                        "missing_command": "script.update_shot_fields",
                        "raw_user_request": "改成跟拍。",
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "entity_type": "shot",
                                "entity_id": shot.id,
                                "op": "set_fields",
                                "fields": {"camera_movement": "跟拍。"},
                            }
                        ],
                    },
                )
            ).document
            formal = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    repaired.revision,
                    "formal-shot-update",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_shot_fields",
                                "shot_id": shot.id,
                                "fields": {"camera_movement": "跟拍。"},
                            }
                        ],
                    },
                )
            )
            self.assertEqual(formal.receipt.status, "noop")
            self.assertEqual(formal.document.capability_gap_alerts, ())
            split = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    formal.document.revision,
                    "script-segment-split",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "split_segment",
                                "segment_id": original.id,
                                "preserve_id": "first",
                                "first": _script_segment_payload(
                                    character_id,
                                    "前半动作。",
                                    boundary=False,
                                ),
                                "second": _script_segment_payload(
                                    character_id,
                                    "后半动作。",
                                    boundary=True,
                                ),
                            }
                        ],
                    },
                )
            )
            assert split.document.director_script is not None
            split_segments = shot_segments_at(split.document.director_script.scenes[0], 0)
            self.assertEqual(split_segments[0].id, original.id)
            self.assertNotEqual(split_segments[1].id, original.id)
            merged = registry.execute(
                DirectorCommand(
                    "script.apply_operations",
                    split.document.revision,
                    "script-segment-merge",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "merge_adjacent_segments",
                                "left_segment_id": split_segments[0].id,
                                "right_segment_id": split_segments[1].id,
                                "preserve_id": "right",
                                "merged": _script_segment_payload(
                                    character_id,
                                    "完整动作。",
                                    boundary=False,
                                ),
                            }
                        ],
                    },
                )
            )
            assert merged.document.director_script is not None
            merged_segments = shot_segments_at(merged.document.director_script.scenes[0], 0)
            self.assertEqual(len(merged_segments), 1)
            self.assertEqual(merged_segments[0].id, split_segments[1].id)

    async def test_repair_patch_is_scoped_atomic_persistent_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            shot = scene.shots[0]
            registry = DirectorCommandRegistry(store)
            arguments = {
                "run_id": "run-gap-1",
                "reason_code": "CAPABILITY_GAP",
                "missing_command": "script.update_scene_fields",
                "raw_user_request": "补充场景摘要。",
                "scope": {"scene_ids": [scene.id]},
                "operations": [
                    {
                        "entity_type": "scene",
                        "entity_id": scene.id,
                        "op": "set_fields",
                        "fields": {
                            "summary": "甲在室内完成连续动作。",
                        },
                    }
                ],
            }
            execution = registry.execute(
                DirectorCommand(
                    "project.apply_repair_patch",
                    document.revision,
                    "run-gap-1:step-1",
                    arguments,
                )
            )

            self.assertEqual(execution.receipt.status, "succeeded")
            self.assertIn(
                "CAPABILITY_GAP:script.update_scene_fields",
                execution.receipt.warnings,
            )
            assert execution.repair_receipt is not None
            self.assertEqual(
                execution.repair_receipt.reverse_operations[0].fields["summary"],
                scene.summary,
            )
            repaired = execution.document
            assert repaired.director_script is not None
            self.assertEqual(
                repaired.director_script.scenes[0].summary,
                "甲在室内完成连续动作。",
            )
            self.assertEqual(len(repaired.capability_gap_alerts), 1)
            alert = repaired.capability_gap_alerts[0]
            self.assertEqual(alert.status.value, "open")
            self.assertEqual(alert.occurrence_count, 1)
            self.assertEqual(store.read().capability_gap_alerts, (alert,))

            replay = registry.execute(
                DirectorCommand(
                    "project.apply_repair_patch",
                    repaired.revision,
                    "run-gap-1:step-1",
                    arguments,
                )
            )
            self.assertEqual(replay.receipt.status, "noop")
            self.assertEqual(replay.document.revision, repaired.revision)
            self.assertEqual(replay.document.capability_gap_alerts[0].occurrence_count, 1)

            before = store.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "repair scope"):
                registry.execute(
                    DirectorCommand(
                        "project.apply_repair_patch",
                        repaired.revision,
                        "run-gap-1:step-2",
                        {
                            **arguments,
                            "scope": {"scene_ids": ["f" * 32]},
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

            with self.assertRaisesRegex(ValueError, "未声明字段"):
                registry.execute(
                    DirectorCommand(
                        "project.apply_repair_patch",
                        repaired.revision,
                        "run-gap-1:step-3",
                        {
                            **arguments,
                            "operations": [
                                {
                                    "entity_type": "shot",
                                    "entity_id": shot.id,
                                    "op": "set_fields",
                                    "fields": {"selected_asset_id": "e" * 32},
                                }
                            ],
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_project_read_tools_return_bounded_scoped_data_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.keyframe_plan is not None
            scene = document.director_script.scenes[0]
            segment = scene.segments[0]
            frame_id = document.keyframe_plan.segments[0].start_keyframe_id
            before = store.path.read_bytes()

            requests = (
                ("project.get_outline", {"depth": "segment", "limit": 1}),
                ("project.get_entities", {"entity_type": "character", "limit": 1}),
                (
                    "project.get_scene",
                    {"scene_id": scene.id, "layers": ["script", "keyframes"]},
                ),
                ("project.get_target", {"target_id": segment.id}),
                (
                    "project.list_candidates",
                    {
                        "kind": "keyframe_image",
                        "target_ids": [frame_id],
                        "phases": ["succeeded"],
                    },
                ),
                (
                    "project.get_dependencies",
                    {"action": "keyframe.generate", "target_ids": [frame_id]},
                ),
            )
            results = []
            for index, (name, arguments) in enumerate(requests):
                execution = await service.execute_director_command(
                    DirectorCommand(
                        name,
                        document.revision,
                        f"read-{index}",
                        arguments,
                    )
                )
                results.append(execution)
                self.assertEqual(execution.receipt.status, "noop")
                self.assertEqual(execution.document.revision, document.revision)
                self.assertIsNotNone(execution.data)

            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(results[0].data["items"][0]["id"], scene.id)
            self.assertEqual(results[1].data["next_cursor"], "1")
            self.assertEqual(results[2].data["scene_id"], scene.id)
            self.assertEqual(results[3].data["target_type"], "segment")
            self.assertEqual(results[4].data["items"], [])
            self.assertEqual(results[5].data["blocked_target_ids"], [frame_id])

    async def test_http_read_tool_omits_full_snapshot_and_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            response = await api.handle(
                "POST",
                "/structured-director/commands",
                json.dumps(
                    {
                        "name": "project.get_outline",
                        "expected_revision": document.revision,
                        "id": "ignored",
                    }
                ).encode(),
            )
            self.assertEqual(response.status, 400)
            valid = await api.handle(
                "POST",
                "/structured-director/commands",
                json.dumps(
                    {
                        "name": "project.get_outline",
                        "expected_revision": document.revision,
                        "idempotency_key": "http-outline",
                        "arguments": {"depth": "scene"},
                    }
                ).encode(),
            )
            self.assertEqual(valid.status, 200, valid.body)
            self.assertIn("data", valid.body)
            self.assertNotIn("snapshot", valid.body)
            self.assertEqual(store.read().revision, document.revision)

    async def test_impact_preview_covers_formal_commands_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            assert document.keyframe_plan is not None
            scene = document.director_script.scenes[0]
            shot = scene.shots[0]
            segment = shot_segments(scene, shot.id)[0]
            binding = document.keyframe_plan.segments[0]
            cue_id = "d" * 32
            # 旁白只属于 Narration Scene：另附一个尚未规划 Shot 的旁白场景。
            cue = NarrationCue(
                cue_id,
                NarrationTrack("夜色渐深，甲缓慢抬头望向窗外，随后乙转身离开房间。", 1),
                NarrationTrack("Night deepens; A looks out as B leaves the room.", 1),
            )
            narration_scene = Scene(
                id="c" * 32,
                title="夜色",
                summary="旁白交代夜色。",
                setting="夜晚，窗外。",
                shots=(),
                segments=(),
                narration_cues=(cue,),
                driver="narration",
            )
            document = replace(
                document,
                director_script=replace(document.director_script, scenes=(scene, narration_scene)),
            )
            document = replace(document, revision=store.read().revision + 1)
            store._atomic_write(document)
            generation_id = "f" * 32
            asset_id = "e" * 32
            commands = (
                (
                    "script.apply_operations",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "op": "update_segment_fields",
                                "segment_id": segment.id,
                                "fields": {"action": segment.action},
                            }
                        ],
                    },
                ),
                (
                    "project.apply_repair_patch",
                    {
                        "run_id": "preview-run",
                        "reason_code": "CAPABILITY_GAP",
                        "missing_command": "script.preview_test",
                        "raw_user_request": "预览影响。",
                        "scope": {"scene_ids": [scene.id]},
                        "operations": [
                            {
                                "entity_type": "scene",
                                "entity_id": scene.id,
                                "op": "set_fields",
                                "fields": {"summary": scene.summary},
                            }
                        ],
                    },
                ),
                (
                    "narration.update_cue",
                    {
                        "scope": {"scene_ids": [narration_scene.id]},
                        "cue_id": cue_id,
                        "fields": {
                            "zh": {"text": "天色渐暗，甲缓慢抬头望向窗外，随后乙转身离开房间。"}
                        },
                    },
                ),
                (
                    "narration.clear_selection",
                    {
                        "scope": {"scene_ids": [narration_scene.id]},
                        "cue_id": cue_id,
                        "language": "zh",
                    },
                ),
                (
                    "keyframe.apply_operations",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": binding.segment_id,
                                "start_enabled": True,
                                "end_enabled": False,
                            }
                        ]
                    },
                ),
                (
                    "video.set_prompt",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment.id,
                        "prompt_text": "保持动作。",
                    },
                ),
                (
                    "video.set_recipe",
                    video_wire_dict(
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "segment_id": segment.id,
                            "generation_mode": "fl2va",
                        }
                    ),
                ),
                (
                    "video.clear_selection",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "segment_id": segment.id,
                    },
                ),
                ("generation.cancel", {"generation_id": generation_id}),
                ("generation.retry", {"generation_id": generation_id}),
                ("generation.dismiss", {"generation_id": generation_id}),
                ("generation.wait", {"generation_ids": [generation_id]}),
                ("animatic.generate_scene", {"scene_id": scene.id}),
                ("final.assemble_scene", {"scene_id": scene.id}),
                ("final.assemble", {}),
                ("final.select_candidate", {"generation_id": generation_id}),
                ("final.clear_selection", {}),
                ("final.approve", {"zh_asset_id": asset_id, "en_asset_id": asset_id}),
                ("final.reopen_production", {}),
            )
            before = store.path.read_bytes()

            for index, (name, arguments) in enumerate(commands):
                execution = await service.execute_director_command(
                    DirectorCommand(
                        "project.preview_impact",
                        document.revision,
                        f"preview-{index}",
                        {
                            "command": {
                                "name": name,
                                "expected_revision": document.revision,
                                "idempotency_key": f"planned-{index}",
                                "arguments": arguments,
                            }
                        },
                    )
                )
                assert execution.data is not None
                self.assertEqual(execution.data["command_name"], name)
                self.assertEqual(execution.data["revision"], document.revision)
                self.assertEqual(execution.document.revision, document.revision)

            self.assertEqual(store.path.read_bytes(), before)

            with self.assertRaisesRegex(ValueError, "未声明字段"):
                await service.execute_director_command(
                    DirectorCommand(
                        "project.preview_impact",
                        document.revision,
                        "preview-strict",
                        {
                            "command": {
                                "name": "final.assemble",
                                "expected_revision": document.revision,
                                "idempotency_key": "planned-strict",
                                "arguments": {"force": True},
                            }
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_planner_operations_update_existing_slots_in_target_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service, document, _route = await _visual_project(
                directory, keyframe_planner=_OperationsPlanner()
            )
            assert document.keyframe_plan is not None
            original_ids = tuple(item.id for item in document.keyframe_plan.keyframes)
            first_shot = document.director_script.scenes[0].shots[0]
            second_binding = document.keyframe_plan.segments[1]

            planned = await service.prepare_keyframes(
                expected_revision=document.revision,
                target_ids=(first_shot.id,),
            )
            assert planned.keyframe_plan is not None
            self.assertEqual(
                tuple(item.id for item in planned.keyframe_plan.keyframes), original_ids
            )
            first_binding = planned.keyframe_plan.segments[0]
            first_frame = next(
                item
                for item in planned.keyframe_plan.keyframes
                if item.id == first_binding.start_keyframe_id
            )
            self.assertEqual(first_frame.prompt_text, "operations 写入的首帧。")
            self.assertTrue(first_binding.start_enabled)
            self.assertFalse(first_binding.end_enabled)
            self.assertEqual(planned.keyframe_plan.segments[1], second_binding)

    async def test_script_impact_preview_uses_actual_mutation_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            segment = scene.segments[0]
            command = DirectorCommand(
                "script.apply_operations",
                document.revision,
                "preview-exact-script",
                {
                    "scope": {"scene_ids": [scene.id]},
                    "operations": [
                        {
                            "op": "update_segment_fields",
                            "segment_id": segment.id,
                            "fields": {"action": "甲缓慢抬头。"},
                        }
                    ],
                },
            )
            preview = await service.execute_director_command(
                DirectorCommand(
                    "project.preview_impact",
                    document.revision,
                    "preview-wrapper",
                    {
                        "command": {
                            "name": command.name,
                            "expected_revision": command.expected_revision,
                            "idempotency_key": command.idempotency_key,
                            "arguments": command.arguments,
                        }
                    },
                )
            )
            actual = DirectorCommandRegistry(store).execute(command)

            assert preview.data is not None
            self.assertEqual(
                set(preview.data["invalidated"]),
                set(actual.receipt.invalidated),
            )
            self.assertEqual(
                set(preview.data["changed_ids"]),
                set(actual.receipt.changed_ids),
            )
            self.assertEqual(
                set(preview.data["preserved"]),
                set(actual.receipt.preserved),
            )
            self.assertTrue(preview.data["will_write"])

    async def test_keyframe_plan_checks_final_boundary_before_atomic_write(self) -> None:
        for undo in ("split", "disable"):
            with self.subTest(undo=undo), tempfile.TemporaryDirectory() as directory:
                store, _service, document, _route = await _visual_project(directory)
                left, right = document.keyframe_plan.segments
                started, _ = store.begin_keyframe_plan(expected_revision=document.revision)
                share = ShareKeyframeBoundary(left.segment_id, right.segment_id, None, "cross_shot")
                reversal = (
                    SplitKeyframeBoundary(left.segment_id, right.segment_id, "right_start", False)
                    if undo == "split"
                    else SetKeyframeActivation(right.segment_id, False, True)
                )
                with self.assertRaisesRegex(ValueError, "最终计划未落实"):
                    store.apply_keyframe_operation_plan(
                        KeyframeOperationsProposal((share, reversal), "共享后撤销。"),
                        required_shared_boundaries=((left.segment_id, right.segment_id),),
                    )
                self.assertEqual(store.read(), started)
                saved = store.apply_keyframe_operation_plan(
                    KeyframeOperationsProposal((share,), "共享连续边界。"),
                    required_shared_boundaries=((left.segment_id, right.segment_id),),
                )
                a, b = saved.keyframe_plan.segments
                self.assertEqual(a.end_keyframe_id, b.start_keyframe_id)
                self.assertTrue(a.end_enabled and b.start_enabled)

    async def test_share_boundary_preserves_source_lineage_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.keyframe_plan is not None
            left, right = document.keyframe_plan.segments
            source_id = left.end_keyframe_id
            document = await service.execute_director_command(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "activate-source",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": left.segment_id,
                                "start_enabled": True,
                                "end_enabled": True,
                            }
                        ]
                    },
                )
            )
            document = document.document
            document = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nsource",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=document.revision,
            )
            asset = document.assets[-1]
            document = await service.select_keyframe(
                keyframe_id=source_id,
                asset_id=asset.id,
                expected_revision=document.revision,
            )
            generation = ReferenceGeneration(
                id="b" * 32,
                kind=ReferenceGenerationKind.KEYFRAME_IMAGE,
                operation=GenerationOperation.GENERATE,
                target_id=source_id,
                phase=ReferenceGenerationPhase.SUCCEEDED,
                progress=1.0,
                message="完成",
                prompt_text="原提示词",
                input_asset_ids=(),
                sample_text=None,
                seed=None,
                plugin_id="test.image",
                plugin_version=1,
                external_id="external",
                output_asset_id=asset.id,
                error_code=None,
                cancellation_requested=False,
                retry_of=None,
                duration_seconds=None,
            )
            document = store.create_generation(generation, expected_revision=document.revision)
            registry = DirectorCommandRegistry(store)
            command = DirectorCommand(
                "keyframe.apply_operations",
                document.revision,
                "share-boundary",
                {
                    "operations": [
                        {
                            "op": "share_boundary",
                            "left_segment_id": left.segment_id,
                            "right_segment_id": right.segment_id,
                            "expected_adjacency": "cross_shot",
                        },
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": source_id,
                            "fields": {
                                "visible_character_ids": [
                                    document.reference_library.characters[1].id
                                ]
                            },
                        },
                    ]
                },
            )
            execution = registry.execute(command)

            self.assertEqual(execution.receipt.status, "succeeded")
            self.assertIn(f"keyframe:{source_id}", execution.receipt.preserved)
            self.assertIn(f"asset:{asset.id}", execution.receipt.preserved)
            self.assertIn(f"generation:{generation.id}", execution.receipt.preserved)
            current = execution.document
            assert current.keyframe_plan is not None
            bindings = {item.segment_id: item for item in current.keyframe_plan.segments}
            self.assertEqual(
                bindings[left.segment_id].end_keyframe_id,
                bindings[right.segment_id].start_keyframe_id,
            )
            self.assertEqual(bindings[left.segment_id].end_keyframe_id, source_id)
            selected = next(
                item for item in current.keyframe_plan.keyframes if item.id == source_id
            )
            self.assertEqual(selected.selected_asset_id, asset.id)
            self.assertEqual(
                selected.visible_character_ids,
                (document.reference_library.characters[1].id,),
            )
            self.assertEqual(current.director_script.revision, document.director_script.revision)
            self.assertEqual(
                current.director_script.production_baseline_revision,
                document.director_script.production_baseline_revision,
            )
            replay = registry.execute(
                DirectorCommand(
                    command.name,
                    current.revision,
                    "share-boundary-reversed-wording",
                    command.arguments,
                )
            )
            self.assertEqual(replay.receipt.status, "noop")
            self.assertEqual(replay.document.revision, current.revision)

            neutral = registry.execute(
                DirectorCommand(
                    command.name,
                    replay.document.revision,
                    "neutralize-shared-roles",
                    {
                        "operations": [
                            {
                                "op": "update_frame_fields",
                                "keyframe_id": source_id,
                                "fields": {"visible_character_ids": []},
                            }
                        ]
                    },
                )
            )
            split = registry.execute(
                DirectorCommand(
                    command.name,
                    neutral.document.revision,
                    "split-right",
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
            )
            assert split.document.keyframe_plan is not None
            split_bindings = {
                item.segment_id: item for item in split.document.keyframe_plan.segments
            }
            clone_id = split_bindings[right.segment_id].start_keyframe_id
            self.assertNotEqual(clone_id, source_id)
            clone = next(
                item for item in split.document.keyframe_plan.keyframes if item.id == clone_id
            )
            self.assertEqual(clone.prompt_text, selected.prompt_text)
            self.assertIsNone(clone.selected_asset_id)
            rebound = registry.execute(
                DirectorCommand(
                    command.name,
                    split.document.revision,
                    "bind-right-start",
                    {
                        "operations": [
                            {
                                "op": "bind_slot",
                                "segment_id": right.segment_id,
                                "slot": "start",
                                "keyframe_id": source_id,
                            }
                        ]
                    },
                )
            )
            assert rebound.document.keyframe_plan is not None
            rebound_bindings = {
                item.segment_id: item for item in rebound.document.keyframe_plan.segments
            }
            self.assertEqual(rebound_bindings[right.segment_id].start_keyframe_id, source_id)
            self.assertNotIn(
                clone_id, {item.id for item in rebound.document.keyframe_plan.keyframes}
            )

    async def test_share_boundary_with_different_selections_requires_user_without_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.keyframe_plan is not None
            left, right = document.keyframe_plan.segments
            execution = await service.execute_director_command(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "activate-both",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": left.segment_id,
                                "start_enabled": True,
                                "end_enabled": True,
                            },
                            {
                                "op": "set_activation",
                                "segment_id": right.segment_id,
                                "start_enabled": True,
                                "end_enabled": True,
                            },
                        ]
                    },
                )
            )
            document = execution.document
            for payload in (b"\x89PNG\r\n\x1a\nleft", b"\x89PNG\r\n\x1a\nright"):
                document = await service.import_image_asset(
                    media_type="image/png",
                    content=payload,
                    category=ImageAssetCategory.KEYFRAME,
                    expected_revision=document.revision,
                )
            left_asset, right_asset = document.assets[-2:]
            document = await service.select_keyframe(
                keyframe_id=left.end_keyframe_id,
                asset_id=left_asset.id,
                expected_revision=document.revision,
            )
            document = await service.select_keyframe(
                keyframe_id=right.start_keyframe_id,
                asset_id=right_asset.id,
                expected_revision=document.revision,
            )
            before = (document.revision, store.path.read_bytes())
            with self.assertRaises(CommandNeedsUserInput):
                DirectorCommandRegistry(store).execute(
                    DirectorCommand(
                        "keyframe.apply_operations",
                        document.revision,
                        "ambiguous-share",
                        {
                            "operations": [
                                {
                                    "op": "share_boundary",
                                    "left_segment_id": left.segment_id,
                                    "right_segment_id": right.segment_id,
                                }
                            ]
                        },
                    )
                )
            self.assertEqual((store.read().revision, store.path.read_bytes()), before)

    async def test_keyframe_operation_batch_is_atomic_on_late_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.keyframe_plan is not None
            segment_id = document.keyframe_plan.segments[0].segment_id
            before = store.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "不存在"):
                DirectorCommandRegistry(store).execute(
                    DirectorCommand(
                        "keyframe.apply_operations",
                        document.revision,
                        "atomic-failure",
                        {
                            "operations": [
                                {
                                    "op": "set_activation",
                                    "segment_id": segment_id,
                                    "start_enabled": True,
                                    "end_enabled": False,
                                },
                                {
                                    "op": "clear_selection",
                                    "keyframe_id": "f" * 32,
                                },
                            ]
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_frame_fields_aux_references_and_clear_selection_share_one_handler(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _route = await _visual_project(directory)
            assert document.keyframe_plan is not None
            binding = document.keyframe_plan.segments[0]
            registry = DirectorCommandRegistry(store)
            document = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "activate-edit-target",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": binding.segment_id,
                                "start_enabled": True,
                                "end_enabled": True,
                            }
                        ]
                    },
                )
            ).document
            document = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\naux",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=document.revision,
            )
            asset = document.assets[-1]
            for keyframe_id in (binding.start_keyframe_id, binding.end_keyframe_id):
                document = await service.select_keyframe(
                    keyframe_id=keyframe_id,
                    asset_id=asset.id,
                    expected_revision=document.revision,
                )
            document = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "clear-one",
                    {
                        "operations": [
                            {
                                "op": "clear_selection",
                                "keyframe_id": binding.start_keyframe_id,
                            }
                        ]
                    },
                )
            ).document
            assert document.keyframe_plan is not None
            by_id = {item.id: item for item in document.keyframe_plan.keyframes}
            self.assertIsNone(by_id[binding.start_keyframe_id].selected_asset_id)
            self.assertEqual(by_id[binding.end_keyframe_id].selected_asset_id, asset.id)
            document = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "set-aux-and-prompt",
                    {
                        "operations": [
                            {
                                "op": "set_aux_references",
                                "segment_id": binding.segment_id,
                                "asset_ids": [asset.id],
                            },
                            {
                                "op": "update_frame_fields",
                                "keyframe_id": binding.end_keyframe_id,
                                "fields": {"prompt_text": "新的静态尾帧。"},
                            },
                        ]
                    },
                )
            ).document
            assert document.keyframe_plan is not None
            current_binding = next(
                item
                for item in document.keyframe_plan.segments
                if item.segment_id == binding.segment_id
            )
            current_end = next(
                item
                for item in document.keyframe_plan.keyframes
                if item.id == binding.end_keyframe_id
            )
            self.assertEqual(current_binding.reference_asset_ids, (asset.id,))
            self.assertEqual(current_end.prompt_text, "新的静态尾帧。")
            self.assertIsNone(current_end.selected_asset_id)

    async def test_http_command_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service, document, _route = await _visual_project(directory)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            response = await api.handle(
                "POST",
                "/structured-director/commands",
                json.dumps(
                    {
                        "name": "keyframe.apply_operations",
                        "expected_revision": document.revision,
                        "idempotency_key": "strict",
                        "arguments": {"operations": [], "unknown": True},
                    }
                ).encode(),
            )
            self.assertEqual(response.status, 400)

    async def test_http_repair_returns_receipt_and_non_blocking_alert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            response = await api.handle(
                "POST",
                "/structured-director/commands",
                json.dumps(
                    {
                        "name": "project.apply_repair_patch",
                        "expected_revision": document.revision,
                        "idempotency_key": "http-repair",
                        "arguments": {
                            "run_id": "http-run",
                            "reason_code": "CAPABILITY_GAP",
                            "missing_command": "script.update_scene_fields",
                            "raw_user_request": "补充场景摘要。",
                            "scope": {"scene_ids": [scene.id]},
                            "operations": [
                                {
                                    "entity_type": "scene",
                                    "entity_id": scene.id,
                                    "op": "set_fields",
                                    "fields": {"summary": "甲完成连续动作。"},
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ).encode(),
            )

            self.assertEqual(response.status, 200)
            payload = response.body
            self.assertEqual(
                payload["repair_receipt"]["reverse_operations"][0]["fields"]["summary"],
                scene.summary,
            )
            self.assertEqual(
                payload["snapshot"]["capability_gap_alerts"][0]["status"],
                "open",
            )


def _boundary_payload() -> dict[str, str]:
    return {
        "reason": "continuity_anchor",
        "continuity_instruction": "延续上一段结束姿态。",
    }


def _script_segment_payload(
    character_id: str,
    action: str,
    *,
    boundary: bool,
) -> dict[str, object]:
    return {
        "duration_estimate_seconds": 2.0,
        "action": action,
        "dialogue_lines": [
            {
                "character_id": character_id,
                "text": "好。",
                "delivery": "轻声。",
            }
        ],
        "boundary_from_previous": _boundary_payload() if boundary else None,
    }


def _script_shot_payload(character_id: str, action: str) -> dict[str, object]:
    return {
        "visible_character_ids": [character_id],
        "composition": "中景。",
        "camera_movement": "固定。",
        "action": action,
        "audio_direction": "环境声。",
        "transition_in": None,
        "segments": [
            _script_segment_payload(character_id, action, boundary=False),
        ],
    }
