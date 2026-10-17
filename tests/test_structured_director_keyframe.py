from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import (
    RecordingProposer,
    RecordingProvider,
    RecordingScriptProposer,
    SingleKeyframePlanner,
    create_project,
)

from core.structured_director import (
    ImageAssetCategory,
    ReferenceGenerationKind,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)
from core.structured_director.service import (
    _final_transition,
)


class StructuredDirectorKeyframeTests(unittest.IsolatedAsyncioTestCase):
    def test_final_transition_depends_only_on_shared_boundary_keyframe(self) -> None:
        self.assertEqual(
            _final_transition("keyframe-shared", "keyframe-shared").value,
            "seam_blend",
        )
        self.assertEqual(
            _final_transition("keyframe-before", "keyframe-after"),
            None,
        )

    async def test_imported_project_image_can_be_selected_as_keyframe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("7" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "7" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(),
                keyframe_planner=SingleKeyframePlanner(),
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            narration = await service.confirm_script(expected_revision=scripted.revision)
            baseline = narration
            visual = await service.unlock_visual_production(expected_revision=baseline.revision)
            planned = await service.prepare_keyframes(expected_revision=visual.revision)
            imported = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nmanual-keyframe",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=planned.revision,
            )
            assert imported.keyframe_plan is not None
            keyframe_id = imported.keyframe_plan.keyframes[0].id
            asset_id = imported.assets[-1].id

            selected = await service.select_keyframe(
                keyframe_id=keyframe_id,
                asset_id=asset_id,
                expected_revision=imported.revision,
            )

            assert selected.keyframe_plan is not None
            self.assertEqual(selected.keyframe_plan.keyframes[0].selected_asset_id, asset_id)
            selected_keyframe = selected.keyframe_plan.keyframes[0]
            binding = selected.keyframe_plan.segments[0]
            replanned = await service.prepare_keyframes(expected_revision=selected.revision)
            assert replanned.keyframe_plan is not None
            self.assertIn(selected_keyframe, replanned.keyframe_plan.keyframes)
            self.assertIn(binding, replanned.keyframe_plan.segments)
            retained_prompt = selected_keyframe.prompt_text
            changed_references = await service.save_segment_keyframe_references(
                segment_id=binding.segment_id,
                asset_ids=(asset_id,),
                expected_revision=replanned.revision,
            )
            assert changed_references.keyframe_plan is not None
            self.assertIsNone(changed_references.keyframe_plan.keyframes[0].selected_asset_id)

            reselected = await service.select_keyframe(
                keyframe_id=keyframe_id,
                asset_id=asset_id,
                expected_revision=changed_references.revision,
            )
            assert reselected.keyframe_plan is not None
            current_keyframe = reselected.keyframe_plan.keyframes[0]
            changed_prompt = await service.save_keyframe(
                replace(current_keyframe, prompt_text=retained_prompt + " 冷色天光。"),
                expected_revision=reselected.revision,
            )
            assert changed_prompt.keyframe_plan is not None
            self.assertIsNone(changed_prompt.keyframe_plan.keyframes[0].selected_asset_id)
            selected = await service.select_keyframe(
                keyframe_id=keyframe_id,
                asset_id=asset_id,
                expected_revision=changed_prompt.revision,
            )
            assert selected.keyframe_plan is not None
            selected_keyframe = next(
                item for item in selected.keyframe_plan.keyframes if item.id == keyframe_id
            )
            role_only_change = await service.save_keyframe(
                replace(selected_keyframe, visible_character_ids=()),
                expected_revision=selected.revision,
            )
            assert role_only_change.keyframe_plan is not None
            self.assertEqual(
                next(
                    item
                    for item in role_only_change.keyframe_plan.keyframes
                    if item.id == keyframe_id
                ).selected_asset_id,
                asset_id,
            )
            deactivated = await service.save_segment_keyframe_activation(
                segment_id=binding.segment_id,
                start_enabled=False,
                end_enabled=True,
                expected_revision=role_only_change.revision,
            )
            assert deactivated.keyframe_plan is not None
            retained = next(
                item for item in deactivated.keyframe_plan.keyframes if item.id == keyframe_id
            )
            self.assertEqual(retained.prompt_text, retained_prompt + " 冷色天光。")
            self.assertEqual(retained.selected_asset_id, asset_id)
            fully_deactivated = await service.save_segment_keyframe_activation(
                segment_id=binding.segment_id,
                start_enabled=False,
                end_enabled=False,
                expected_revision=deactivated.revision,
            )
            assert fully_deactivated.keyframe_plan is not None
            fully_deactivated_binding = next(
                item
                for item in fully_deactivated.keyframe_plan.segments
                if item.segment_id == binding.segment_id
            )
            self.assertFalse(fully_deactivated_binding.start_enabled)
            self.assertFalse(fully_deactivated_binding.end_enabled)
            no_op = await service.save_segment_keyframe_activation(
                segment_id=binding.segment_id,
                start_enabled=False,
                end_enabled=False,
                expected_revision=fully_deactivated.revision,
            )
            self.assertEqual(no_op.revision, fully_deactivated.revision)
            with self.assertRaisesRegex(ValueError, "未激活"):
                await service.generate_keyframe(
                    keyframe_id=keyframe_id,
                    expected_revision=fully_deactivated.revision,
                )

    async def test_replanning_preserves_unselected_successful_keyframe_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("3" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "3" * 32)
            provider = RecordingProvider(
                media_type="image/png", content=b"\x89PNG\r\n\x1a\ngenerated-keyframe"
            )
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(),
                keyframe_planner=SingleKeyframePlanner(),
                image_provider=provider,
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            narration = await service.confirm_script(expected_revision=scripted.revision)
            baseline = narration
            visual = await service.unlock_visual_production(expected_revision=baseline.revision)
            planned = await service.prepare_keyframes(expected_revision=visual.revision)
            assert planned.keyframe_plan is not None
            frame = planned.keyframe_plan.keyframes[0]
            binding = planned.keyframe_plan.segments[0]
            submitted = await service.generate_keyframe(
                keyframe_id=frame.id, expected_revision=planned.revision
            )
            running = await service._generation_observer.refresh_generation(
                submitted.generations[-1].id
            )
            succeeded = await service._generation_observer.refresh_generation(
                running.generations[-1].id
            )
            assert succeeded.keyframe_plan is not None
            self.assertEqual(len(provider.requests), 1)
            self.assertEqual(
                len(
                    [
                        item
                        for item in succeeded.generations
                        if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                    ]
                ),
                1,
            )
            self.assertIsNone(
                next(
                    item for item in succeeded.keyframe_plan.keyframes if item.id == frame.id
                ).selected_asset_id
            )

            replanned = await service.prepare_keyframes(expected_revision=succeeded.revision)

            assert replanned.keyframe_plan is not None
            self.assertIn(frame, replanned.keyframe_plan.keyframes)
            self.assertIn(binding, replanned.keyframe_plan.segments)
            self.assertIn(
                succeeded.generations[-1].target_id,
                {item.id for item in replanned.keyframe_plan.keyframes},
            )

            explicitly_replanned = await service.prepare_keyframes(
                expected_revision=replanned.revision,
                user_message="明确重做这组关键帧，不保留旧候选绑定。",
            )

            assert explicitly_replanned.keyframe_plan is not None
            self.assertIn(frame, explicitly_replanned.keyframe_plan.keyframes)
            self.assertIn(binding, explicitly_replanned.keyframe_plan.segments)
            self.assertIn(succeeded.generations[-1], explicitly_replanned.generations)

    async def test_production_script_revision_keeps_keyframe_slots_for_every_segment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("9" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "9" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(),
                keyframe_planner=SingleKeyframePlanner(),
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            narration = await service.confirm_script(expected_revision=scripted.revision)
            baseline = narration
            visual = await service.unlock_visual_production(expected_revision=baseline.revision)
            planned = await service.prepare_keyframes(expected_revision=visual.revision)
            assert planned.keyframe_plan is not None
            original_segment_id = planned.keyframe_plan.segments[0].segment_id

            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            snapshot = await api.handle("GET", "/structured-director")
            scenes = snapshot.body["director_script"]["scenes"]
            split_source = dict(scenes[0]["shots"][0]["segments"][0])
            split_source["action"] = "前半段动作。"
            split_source["duration_estimate_seconds"] = 1.0
            second_segment = dict(scenes[0]["shots"][0]["segments"][0])
            second_segment.update(
                id=None,
                action="后半段动作。",
                duration_estimate_seconds=1.0,
                boundary_from_previous={
                    "reason": "control_boundary",
                    "continuity_instruction": "延续前半段结束状态。",
                },
            )
            scenes[0]["shots"][0]["segments"] = [split_source, second_segment]
            edited = await api.handle(
                "PUT",
                "/structured-director/director-script",
                json.dumps(
                    {
                        "expected_revision": snapshot.body["revision"],
                        "scenes": scenes,
                    }
                ).encode(),
            )
            self.assertEqual(edited.status, 200, edited.body)
            keyframe_plan = edited.body["keyframe_plan"]
            self.assertEqual(
                keyframe_plan["source_script_revision"],
                edited.body["director_script"]["revision"],
            )
            bindings = {item["segment_id"]: item for item in keyframe_plan["segments"]}
            live_segment_ids = {
                item["id"]
                for scene in edited.body["director_script"]["scenes"]
                for shot in scene["shots"]
                for item in shot["segments"]
            }
            self.assertEqual(set(bindings), live_segment_ids)
            retained_binding = bindings[original_segment_id]
            original_binding = snapshot.body["keyframe_plan"]["segments"][0]
            self.assertEqual(retained_binding, original_binding)
            new_segment_id = next(
                segment_id for segment_id in bindings if segment_id != original_segment_id
            )
            new_binding = bindings[new_segment_id]
            # 新 Segment 立即获得独立的空首尾槽位，不与相邻 Segment 共享。
            self.assertNotEqual(
                new_binding["start_keyframe_id"],
                retained_binding["end_keyframe_id"],
            )
            self.assertFalse(new_binding["start_enabled"])
            self.assertFalse(new_binding["end_enabled"])
            new_start_id = new_binding["start_keyframe_id"]
            referenced_keyframe_ids = {
                keyframe_id
                for item in keyframe_plan["segments"]
                for keyframe_id in (item["start_keyframe_id"], item["end_keyframe_id"])
            }
            self.assertEqual(
                referenced_keyframe_ids,
                {item["id"] for item in keyframe_plan["keyframes"]},
            )
            keyframe_by_id = {item["id"]: item for item in keyframe_plan["keyframes"]}
            new_end = keyframe_by_id[new_binding["end_keyframe_id"]]
            self.assertEqual(new_end["owner_segment_id"], new_segment_id)
            self.assertEqual(new_end["predecessor_keyframe_id"], new_binding["start_keyframe_id"])
            new_start = keyframe_by_id[new_start_id]
            self.assertEqual(new_start["owner_segment_id"], new_segment_id)
            self.assertIsNone(new_start["predecessor_keyframe_id"])
