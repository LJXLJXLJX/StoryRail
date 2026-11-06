from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import (
    FailingCancelProvider,
    RecordingProposer,
    create_project,
    wav_bytes,
)

from core.structured_director import (
    DirectorRunKind,
    DirectorRunStatus,
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorStatus,
    StructuredDirectorStore,
)
from core.structured_director.models import CharacterLook
from core.structured_director.reads.read_tools import execute_project_read


class StructuredDirectorRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reading_authoritative_json_restores_original_director_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("f" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "f" * 32)

            service = StructuredDirectorService(store, RecordingProposer())
            entered = create_project(store)
            restored = service.snapshot_required()

            self.assertEqual(restored, entered)
            self.assertIn("小满", restored.director_plan_markdown)

    async def test_agent_failure_is_recoverable_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("b" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "b" * 32)
            failing = StructuredDirectorService(store, RecordingProposer(fail=True))
            create_project(store)

            with self.assertRaisesRegex(RuntimeError, "模拟 Agent 中断"):
                await failing.prepare_references()

            pending = store.read()
            proposer = RecordingProposer()
            recovered = await StructuredDirectorService(store, proposer).prepare_references()

            self.assertIs(pending.status, StructuredDirectorStatus.AWAITING_PROPOSAL)
            self.assertIsNotNone(pending.active_director_run)
            self.assertIs(
                pending.active_director_run.kind,
                DirectorRunKind.REFERENCE_PROPOSAL,
            )
            self.assertIs(recovered.status, StructuredDirectorStatus.REVIEWING)
            self.assertIsNone(recovered.active_director_run)
            self.assertIs(recovered.director_runs[-1].status, DirectorRunStatus.COMPLETED)
            self.assertEqual(proposer.restart_values, [True])

    async def test_cancel_intent_is_saved_before_external_call(self) -> None:
        wav = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("b" * 32)
            project.mkdir()
            provider = FailingCancelProvider(media_type="audio/wav", content=wav)
            store = StructuredDirectorStore(project, "b" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            submitted = await service._media.design_voice(
                card_id=prepared.reference_library.characters[0].id,
                voice_description="年轻、温和",
                sample_text="测试声音。",
                seed=42,
                expected_revision=prepared.revision,
            )

            with self.assertRaisesRegex(RuntimeError, "暂时无法取消"):
                await service._generation_observer.cancel_generation(submitted.generations[0].id)

            persisted = store.read().generations[0]
            self.assertTrue(persisted.cancellation_requested)
            self.assertIs(persisted.phase, ReferenceGenerationPhase.QUEUED)
            discovery = execute_project_read(store.read(), "project.get_handoff", {})[
                "task_discovery"
            ]
            task = next(
                item
                for item in (*discovery["active"], *discovery["recent"])
                if item["id"] == persisted.id
            )
            self.assertEqual(task["recovery"]["failure_origin"], "provider_cancellation")
            self.assertEqual(task["recovery"]["retry_policy"], "wait_same_generation")

    async def test_restart_marks_unresolved_submission_uncertain_without_retrying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("3" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "3" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            card = prepared.reference_library.characters[0]
            look = CharacterLook("5" * 32, "日常", "蓝色外套", "全片")
            prepared = await service.update_character(
                replace(card, looks=(look,)),
                expected_revision=prepared.revision,
                created_look_ids=frozenset({look.id}),
            )
            card = prepared.reference_library.characters[0]
            store.create_generation(
                ReferenceGeneration(
                    id="4" * 32,
                    kind=ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
                    operation=GenerationOperation.GENERATE,
                    target_id=card.looks[0].id,
                    phase=ReferenceGenerationPhase.SUBMITTING,
                    progress=0.0,
                    message="提交中",
                    prompt_text="角色设定图",
                    input_asset_ids=(),
                    sample_text=None,
                    seed=None,
                    plugin_id=None,
                    plugin_version=None,
                    external_id=None,
                    output_asset_id=None,
                    error_code=None,
                    cancellation_requested=False,
                    retry_of=None,
                ),
                expected_revision=prepared.revision,
            )

            restored = StructuredDirectorService(store, RecordingProposer()).snapshot_required()

            self.assertIs(
                restored.generations[0].phase,
                ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
            )
            self.assertEqual(
                restored.generations[0].error_code,
                "core_restarted_during_submit",
            )
