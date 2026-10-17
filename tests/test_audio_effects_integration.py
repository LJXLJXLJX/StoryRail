from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import RecordingProposer, create_project, wav_bytes

from core.audio_effects import AudioEffectRequest, AudioTrimRequest
from core.structured_director import (
    GenerationOperation,
    ReferenceGenerationKind,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)


class AudioEffectIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _project_with_audio(self, directory: str):
        project_id = "0" * 32
        project = Path(directory) / project_id
        project.mkdir()
        store = StructuredDirectorStore(project, project_id)
        service = StructuredDirectorService(store, RecordingProposer())
        create_project(store)
        prepared = await service.prepare_references()
        card = prepared.reference_library.characters[0]
        source_bytes = wav_bytes(duration_seconds=0.25, sample_rate=12_000)
        uploaded = await service.upload_reference_voice(
            card_id=card.id,
            media_type="audio/wav",
            content=source_bytes,
            filename="source.wav",
            expected_revision=prepared.revision,
        )
        source_id = uploaded.reference_library.characters[0].voice_reference_asset_id
        self.assertIsNotNone(source_id)
        return project, store, service, uploaded, source_id or "", source_bytes

    async def test_effect_creates_deterministic_immutable_copy_with_hidden_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _, service, uploaded, source_id, source_bytes = await self._project_with_audio(
                directory
            )
            request = AudioEffectRequest(
                effect="radio",
                preset="weak_signal",
                strength=0.7,
                seed=42,
            )

            processed = await service.apply_audio_effect(
                source_asset_id=source_id,
                request=request,
                expected_revision=uploaded.revision,
            )

            self.assertEqual(service.read_asset(source_id)[1], source_bytes)
            generation = processed.generations[-1]
            self.assertEqual(generation.kind, ReferenceGenerationKind.AUDIO_EFFECT)
            self.assertEqual(generation.operation, GenerationOperation.PROCESS)
            self.assertEqual(generation.input_asset_ids, (source_id,))
            self.assertTrue(generation.dismissed)
            self.assertEqual(generation.plugin_id, "storyrail.audio_effects")
            self.assertEqual(generation.plugin_version, 2)
            self.assertIsNotNone(generation.output_asset_id)
            output_id = generation.output_asset_id or ""
            output_asset, output_bytes = service.read_asset(output_id)
            self.assertEqual(output_asset.media_type, "audio/wav")
            self.assertIn("assets/audio/effects/", output_asset.relative_path)
            self.assertNotEqual(output_id, source_id)
            self.assertNotEqual(output_bytes, source_bytes)
            record = json.loads(generation.prompt_text)
            self.assertEqual(record["schema"], "storyrail_audio_effect_v1")
            self.assertEqual(record["request"]["preset"], "weak_signal")
            self.assertEqual(record["metadata"]["seed"], 42)

            restored = StructuredDirectorStore(project, "0" * 32).read()
            self.assertEqual(restored.generations[-1], generation)
            self.assertIn(output_id, {asset.id for asset in restored.assets})

            repeated = await service.apply_audio_effect(
                source_asset_id=source_id,
                request=request,
                expected_revision=processed.revision,
            )
            self.assertEqual(repeated.generations[-1].output_asset_id, output_id)
            self.assertEqual(len(repeated.assets), len(processed.assets))

            deleted = await service.delete_asset(
                output_id,
                expected_revision=repeated.revision,
            )
            self.assertEqual(service.read_asset(source_id)[1], source_bytes)
            self.assertNotIn(output_id, {asset.id for asset in deleted.assets})
            self.assertFalse(
                any(
                    item.kind is ReferenceGenerationKind.AUDIO_EFFECT
                    for item in deleted.generations
                )
            )

    async def test_http_exposes_audio_action_and_creates_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, service, uploaded, source_id, _ = await self._project_with_audio(directory)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            visible = await api.handle("GET", "/structured-director")
            source = next(item for item in visible.body["assets"] if item["id"] == source_id)
            self.assertIn("apply_audio_effect", visible.body["allowed_actions"])
            self.assertEqual(source["allowed_actions"], ["audio_trim", "audio_effect"])

            response = await api.handle(
                "POST",
                f"/structured-director/assets/{source_id}/audio-effect",
                json.dumps(
                    {
                        "expected_revision": uploaded.revision,
                        "effect": "radio",
                        "preset": "dying_transmission",
                        "strength": 0.8,
                        "seed": 7,
                        "start_seconds": 0.05,
                        "end_seconds": 0.2,
                    }
                ).encode(),
            )
            self.assertEqual(response.status, 200)
            output_id = response.body["generations"][-1]["output_asset_id"]
            self.assertIsNotNone(output_id)
            output = next(item for item in response.body["assets"] if item["id"] == output_id)
            self.assertEqual(output["media_type"], "audio/wav")
            self.assertEqual(output["allowed_actions"], ["audio_trim", "audio_effect", "delete"])
            record = json.loads(response.body["generations"][-1]["prompt_text"])
            self.assertEqual(record["metadata"]["start_seconds"], 0.05)
            self.assertEqual(record["metadata"]["end_seconds"], 0.2)

            invalid = await api.handle(
                "POST",
                f"/structured-director/assets/{source_id}/audio-effect",
                json.dumps(
                    {
                        "expected_revision": response.body["revision"],
                        "effect": "radio",
                        "preset": "weak_signal",
                        "strength": 0.7,
                        "seed": 42,
                        "unexpected": True,
                    }
                ).encode(),
            )
            self.assertEqual(invalid.status, 400)

    async def test_trim_creates_immutable_copy_with_hidden_lineage_and_http_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _, service, uploaded, source_id, source_bytes = await self._project_with_audio(
                directory
            )
            trimmed = await service.trim_audio(
                source_asset_id=source_id,
                request=AudioTrimRequest(0.05, 0.20),
                expected_revision=uploaded.revision,
            )
            self.assertEqual(service.read_asset(source_id)[1], source_bytes)
            generation = trimmed.generations[-1]
            self.assertEqual(generation.kind, ReferenceGenerationKind.AUDIO_TRIM)
            self.assertEqual(generation.operation, GenerationOperation.PROCESS)
            self.assertEqual(generation.input_asset_ids, (source_id,))
            self.assertTrue(generation.dismissed)
            self.assertEqual(generation.plugin_id, "storyrail.audio_trim")
            self.assertEqual(generation.plugin_version, 1)
            self.assertAlmostEqual(generation.duration_seconds or 0, 0.15)
            output_id = generation.output_asset_id or ""
            output_asset, output_bytes = service.read_asset(output_id)
            self.assertIn("assets/audio/trims/", output_asset.relative_path)
            self.assertNotEqual(output_bytes, source_bytes)
            record = json.loads(generation.prompt_text)
            self.assertEqual(record["schema"], "storyrail_audio_trim_v1")
            self.assertEqual(record["request"], {"start_seconds": 0.05, "end_seconds": 0.2})
            self.assertAlmostEqual(record["metadata"]["output_duration_seconds"], 0.15)
            restored = StructuredDirectorStore(project, "0" * 32).read()
            self.assertEqual(restored.generations[-1], generation)

            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            response = await api.handle(
                "POST",
                f"/structured-director/assets/{source_id}/audio-trim",
                json.dumps(
                    {
                        "expected_revision": trimmed.revision,
                        "start_seconds": 0.10,
                        "end_seconds": 0.24,
                    }
                ).encode(),
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(response.body["generations"][-1]["kind"], "audio_trim")
            invalid = await api.handle(
                "POST",
                f"/structured-director/assets/{source_id}/audio-trim",
                json.dumps(
                    {
                        "expected_revision": response.body["revision"],
                        "start_seconds": 0.20,
                        "end_seconds": 0.30,
                    }
                ).encode(),
            )
            self.assertEqual(invalid.status, 400)


if __name__ == "__main__":
    unittest.main()
