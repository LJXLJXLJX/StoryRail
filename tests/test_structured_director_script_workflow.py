from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import (
    RecordingProposer,
    RecordingScriptProposer,
    create_project,
)

from core.director_proposals import (
    DialogueLineProposal,
    EditableShotSegmentProposal,
    ScriptRevisionOperationProposal,
    StructuredDirectorScriptRevisionProposal,
)
from core.structured_director import (
    DirectorRunKind,
    DirectorRunStatus,
    StructuredDirectorHttpApi,
    StructuredDirectorStatus,
    StructuredDirectorStore,
)


class StructuredDirectorScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_agent_edit_state_locks_manual_script_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("d" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "d" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(),
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            editing, _ = store.begin_script_edit(
                "把第一场改成雨夜。",
                expected_revision=scripted.revision,
            )
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            snapshot = await api.handle("GET", "/structured-director")

            blocked = await api.handle(
                "PUT",
                "/structured-director/director-script",
                json.dumps(
                    {
                        "expected_revision": editing.revision,
                        "scenes": snapshot.body["director_script"]["scenes"],
                    }
                ).encode(),
            )

            self.assertEqual(snapshot.body["allowed_actions"], [])
            self.assertEqual(blocked.status, 409)
            self.assertIn("Agent 工作期间", blocked.body["error"]["message"])
            persisted = store.read()
            self.assertIs(persisted.status, StructuredDirectorStatus.REVIEWING_SCRIPT)
            self.assertIsNotNone(persisted.active_director_run)
            self.assertIs(persisted.active_director_run.kind, DirectorRunKind.SCRIPT_EDIT)

    async def test_empty_script_revision_exits_edit_without_bumping_script_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("0" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "0" * 32)
            service = StructuredDirectorService(
                store, RecordingProposer(), script_proposer=RecordingScriptProposer()
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            assert scripted.director_script is not None
            editing, _ = store.begin_script_edit(
                "检查一下，不需要修改就保持原样。", expected_revision=scripted.revision
            )

            unchanged = store.apply_script_revision_proposal(
                StructuredDirectorScriptRevisionProposal("当前脚本无需修改。")
            )

            assert unchanged.director_script is not None
            self.assertEqual(unchanged.director_script.revision, scripted.director_script.revision)
            self.assertEqual(unchanged.director_script.scenes, scripted.director_script.scenes)
            self.assertEqual(unchanged.revision, editing.revision + 1)
            self.assertIsNone(unchanged.pending_script_edit)

    async def test_segment_revision_changes_only_the_target_segment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("1" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "1" * 32)
            service = StructuredDirectorService(
                store, RecordingProposer(), script_proposer=RecordingScriptProposer()
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            assert scripted.director_script is not None
            original_scene = scripted.director_script.scenes[0]
            original_shot = original_scene.shots[0]
            original_segment = original_shot.segments[0]
            store.begin_script_edit("只改第一个 Segment。", expected_revision=scripted.revision)
            replacement = EditableShotSegmentProposal(
                id=original_segment.id,
                duration_estimate_seconds=original_segment.duration_estimate_seconds,
                action="小满抬头后又低头看向手机。",
                dialogue_lines=tuple(
                    DialogueLineProposal(item.character_id, item.text, item.delivery)
                    for item in original_segment.dialogue_lines
                ),
                boundary_from_previous=None,
            )

            revised = store.apply_script_revision_proposal(
                StructuredDirectorScriptRevisionProposal(
                    "仅修改了目标 Segment。",
                    operations=(
                        ScriptRevisionOperationProposal(
                            operation="replace_segment",
                            scene_id=original_scene.id,
                            shot_id=original_shot.id,
                            segment=replacement,
                        ),
                    ),
                )
            )

            assert revised.director_script is not None
            revised_scene = revised.director_script.scenes[0]
            self.assertEqual(revised_scene.id, original_scene.id)
            self.assertEqual(revised_scene.title, original_scene.title)
            self.assertEqual(revised_scene.shots[0].id, original_shot.id)
            self.assertEqual(revised_scene.shots[0].segments[0].id, original_segment.id)
            self.assertEqual(
                revised_scene.shots[0].segments[0].action,
                "小满抬头后又低头看向手机。",
            )

    async def test_script_proposal_is_persisted_with_core_owned_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("1" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "1" * 32)
            script_proposer = RecordingScriptProposer()
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=script_proposer,
            )
            create_project(store)
            prepared = await service.prepare_references()

            scripted = await service.prepare_script(expected_revision=prepared.revision)
            restored = StructuredDirectorStore(project, "1" * 32).read()

            self.assertIs(scripted.status, StructuredDirectorStatus.REVIEWING_SCRIPT)
            self.assertEqual(scripted.director_script, restored.director_script)
            script = scripted.director_script
            self.assertIsNotNone(script)
            assert script is not None
            self.assertEqual(script.revision, 1)
            self.assertEqual(
                script.source_reference_revision, prepared.revision + 1
            )  # 人工审核提交
            self.assertIsNone(script.production_baseline_revision)
            ids = {
                script.scenes[0].id,
                script.scenes[0].shots[0].id,
                script.scenes[0].shots[0].segments[0].id,
            }
            self.assertEqual(len(ids), 3)
            self.assertTrue(all(len(item) == 32 for item in ids))
            self.assertEqual(script_proposer.restart_values, [False])

    async def test_script_agent_failure_recovers_same_persisted_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("2" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "2" * 32)
            failing = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(fail=True),
            )
            create_project(store)
            prepared = await failing.prepare_references()

            with self.assertRaisesRegex(RuntimeError, "结构化脚本 Agent 中断"):
                await failing.prepare_script(expected_revision=prepared.revision)

            pending = store.read()
            recovered_proposer = RecordingScriptProposer()
            recovered = await StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=recovered_proposer,
            ).prepare_script(expected_revision=pending.revision)

            self.assertIs(pending.status, StructuredDirectorStatus.REVIEWING)
            self.assertIsNotNone(pending.active_director_run)
            self.assertIs(pending.active_director_run.kind, DirectorRunKind.SCRIPT_PROPOSAL)
            self.assertIs(recovered.status, StructuredDirectorStatus.REVIEWING_SCRIPT)
            self.assertIsNone(recovered.active_director_run)
            self.assertIs(recovered.director_runs[-1].status, DirectorRunStatus.COMPLETED)
            self.assertEqual(recovered_proposer.restart_values, [True])

    async def test_script_edit_and_confirmation_keep_an_explicit_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("4" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "4" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(),
            )
            create_project(store)
            prepared = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=prepared.revision)
            assert scripted.director_script is not None
            scene = scripted.director_script.scenes[0]
            edited_scene = replace(scene, summary="小满最终决定不再等待。")
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            snapshot = await api.handle("GET", "/structured-director")
            scenes_payload = snapshot.body["director_script"]["scenes"]
            scenes_payload[0]["shots"][0]["model_prompt"] = "cinematic"

            unknown_field = await api.handle(
                "PUT",
                "/structured-director/director-script",
                json.dumps(
                    {
                        "expected_revision": scripted.revision,
                        "scenes": scenes_payload,
                    }
                ).encode(),
            )

            edited = await service.save_script(
                (edited_scene,),
                expected_revision=scripted.revision,
            )
            confirmed = await service.confirm_script(expected_revision=edited.revision)
            assert confirmed.director_script is not None
            edited_again = await service.save_script(
                (
                    replace(
                        confirmed.director_script.scenes[0],
                        setting="夜色降临，站台只剩一盏顶灯。",
                    ),
                ),
                expected_revision=confirmed.revision,
            )

            assert edited.director_script is not None
            assert edited_again.director_script is not None
            self.assertEqual(unknown_field.status, 400)

            self.assertEqual(edited.director_script.revision, 2)
            self.assertEqual(confirmed.director_script.production_baseline_revision, 2)
            self.assertEqual(edited_again.director_script.revision, 3)
            # 旁白层解锁后，每次脚本写入都由 Core 自动重建生产基线，不需要人工确认时序。
            self.assertEqual(edited_again.director_script.production_baseline_revision, 3)
            self.assertEqual(
                edited_again.director_script.production_baseline_scenes,
                edited_again.director_script.scenes,
            )
            self.assertEqual(store.read(), edited_again)

    async def test_http_script_schema_is_strict_and_unknown_references_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("e" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "e" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(unknown_character=True),
            )
            create_project(store)
            prepared = await service.prepare_references()
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            extra = await api.handle(
                "POST",
                "/structured-director/script-proposal",
                json.dumps({"expected_revision": prepared.revision, "auto_confirm": True}).encode(),
            )
            invalid = await api.handle(
                "POST",
                "/structured-director/script-proposal",
                json.dumps({"expected_revision": prepared.revision}).encode(),
            )

            self.assertEqual(extra.status, 404)
            self.assertEqual(invalid.status, 404)
            self.assertEqual(invalid.body["error"]["code"], "not_found")
            with self.assertRaises(ValueError):
                await service.prepare_script(expected_revision=prepared.revision)
            self.assertIsNone(service.snapshot_required().director_script)
