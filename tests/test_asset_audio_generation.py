from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import (
    FailingSubmitProvider,
    RecordingProposer,
    RecordingProvider,
    create_project,
    wav_bytes,
)

from core.model_providers.boundary import ModelProviderError
from core.model_providers.recipe import RecipeParams, RecipeRequest
from core.structured_director import (
    GenerationOperation,
    ReferenceGenerationKind,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)
from core.structured_director.asset_metadata import _asset_filename, _generation_asset_location


class AssetAudioGenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_asset_filename_keeps_short_names_and_caps_long_names_by_utf8_bytes(self) -> None:
        self.assertEqual(_asset_filename("信号正常，请继续。"), "信号正常,请继续。")
        long_text = "北海09号平台失联第37天。" * 40
        name = _asset_filename(long_text)
        self.assertTrue(name.endswith("…"))
        self.assertTrue(long_text.startswith(name[:-1]))
        self.assertLessEqual(len(name.encode("utf-8")), 200)
        self.assertLessEqual(len(name), 120)
        self.assertEqual(_asset_filename("a" * 120), "a" * 120)

    def test_generated_audio_asset_is_named_after_the_spoken_text_not_the_reference(self) -> None:
        clone = SimpleNamespace(
            kind=ReferenceGenerationKind.GENERATED_AUDIO,
            operation=GenerationOperation.SYNTHESIZE,
            prompt_text="那是……刚才的我？",
            sample_text="1848年，最后一批船员放弃了被冰封的船。",
        )
        design = SimpleNamespace(
            kind=ReferenceGenerationKind.GENERATED_AUDIO,
            operation=GenerationOperation.VOICE_DESIGN,
            prompt_text="低沉的中年男声",
            sample_text="这里是远程观测站。",
        )
        self.assertEqual(
            _generation_asset_location(None, clone), ("audio/generated", "那是……刚才的我？")
        )
        self.assertEqual(
            _generation_asset_location(None, design), ("audio/generated", "这里是远程观测站。")
        )

    async def _service(self, directory: str):
        project_id = "0" * 32
        project = Path(directory) / project_id
        project.mkdir()
        store = StructuredDirectorStore(project, project_id)
        voice_provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
        speech_provider = RecordingProvider(
            media_type="audio/wav",
            content=wav_bytes(duration_seconds=1.25, sample_rate=12_000),
        )
        service = StructuredDirectorService(
            store,
            RecordingProposer(),
            voice_provider=voice_provider,
            speech_provider=speech_provider,
        )
        create_project(store)
        prepared = await service.prepare_references()
        return project, service, prepared, voice_provider, speech_provider

    async def test_breeze_design_and_clone_create_generic_wav_assets_with_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, service, prepared, voice_provider, speech_provider = await self._service(
                directory
            )
            submitted_voice = await service._media.generate_asset_audio(
                text="这里是远程观测站。",
                voice_description="低沉、克制的中年男声",
                seed=42,
                expected_revision=prepared.revision,
            )
            voice_generation = submitted_voice.generations[-1]
            self.assertEqual(voice_generation.kind, ReferenceGenerationKind.GENERATED_AUDIO)
            self.assertEqual(voice_generation.operation, GenerationOperation.VOICE_DESIGN)
            self.assertEqual(voice_generation.target_id, voice_generation.id)
            design_request = voice_provider.requests[-1]
            self.assertIsInstance(design_request, RecipeRequest)
            self.assertEqual(design_request.recipe_id, "breeze_tts2.voice_design")
            self.assertEqual(design_request.slot("voice"), ())
            self.assertEqual(design_request.param("voice_description"), "低沉、克制的中年男声")
            await service._generation_observer.refresh_generation(voice_generation.id)
            completed_voice = await service._generation_observer.refresh_generation(
                voice_generation.id
            )
            voice_generation = completed_voice.generations[-1]
            voice_asset_id = voice_generation.output_asset_id or ""
            voice_asset, _ = service.read_asset(voice_asset_id)
            self.assertIn("assets/audio/generated/", voice_asset.relative_path)
            self.assertEqual(voice_asset.display_name, "这里是远程观测站。.wav")

            submitted_speech = await service._media.generate_asset_audio(
                text="信号正常，请继续。",
                voice_asset_id=voice_asset_id,
                reference_transcript="这里是远程观测站。",
                recipe_params=RecipeParams.from_json(
                    {"breeze_tts2.clone": {"performance_instruction": "冷静、清晰"}}
                ),
                seed=7,
                expected_revision=completed_voice.revision,
            )
            speech_generation = submitted_speech.generations[-1]
            self.assertEqual(speech_generation.kind, ReferenceGenerationKind.GENERATED_AUDIO)
            self.assertEqual(speech_generation.operation, GenerationOperation.SYNTHESIZE)
            self.assertEqual(speech_generation.input_asset_ids, (voice_asset_id,))
            request = speech_provider.requests[-1]
            self.assertIsInstance(request, RecipeRequest)
            self.assertEqual(request.param("text"), "信号正常，请继续。")
            self.assertEqual(request.param("reference_transcript"), "这里是远程观测站。")
            self.assertEqual(request.param("performance_instruction"), "冷静、清晰")
            self.assertEqual(speech_generation.sample_text, "这里是远程观测站。")
            self.assertEqual(
                speech_generation.recipe_params.get("breeze_tts2.clone"),
                {"performance_instruction": "冷静、清晰"},
            )
            await service._generation_observer.refresh_generation(speech_generation.id)
            completed_speech = await service._generation_observer.refresh_generation(
                speech_generation.id
            )
            output_id = completed_speech.generations[-1].output_asset_id or ""
            output, _ = service.read_asset(output_id)
            self.assertIn("assets/audio/generated/", output.relative_path)
            self.assertEqual(output.display_name, "信号正常,请继续。.wav")
            restored = StructuredDirectorStore(project, "0" * 32).read()
            self.assertEqual(restored.generations[-1].output_asset_id, output_id)

            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            visible = await api.handle("GET", "/structured-director")
            generated = next(item for item in visible.body["assets"] if item["id"] == output_id)
            self.assertEqual(generated["allowed_actions"], ["audio_trim", "audio_effect", "delete"])
            self.assertEqual(
                visible.body["generations"][-1]["allowed_actions"], ["dismiss_history"]
            )
            deleted = await api.handle(
                "DELETE",
                f"/structured-director/assets/{output_id}",
                json.dumps({"expected_revision": visible.body["revision"]}).encode(),
            )
            self.assertEqual(deleted.status, 200)
            self.assertNotIn(output_id, {item["id"] for item in deleted.body["assets"]})
            self.assertNotIn(
                speech_generation.id,
                {item["id"] for item in deleted.body["generations"]},
            )

    async def test_http_audio_generation_contract_is_strict_per_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service, prepared, _, _ = await self._service(directory)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            response = await api.handle(
                "POST",
                "/structured-director/audio-generations",
                json.dumps(
                    {
                        "expected_revision": prepared.revision,
                        "operation": "voice_design",
                        "text": "测试语音",
                        "voice_description": "清晰、自然的女声",
                        "seed": 9,
                    }
                ).encode(),
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(response.body["generations"][-1]["kind"], "generated_audio")
            invalid = await api.handle(
                "POST",
                "/structured-director/audio-generations",
                json.dumps(
                    {
                        "expected_revision": response.body["revision"],
                        "operation": "voice_design",
                        "text": "测试语音",
                        "voice_description": "清晰女声",
                        "voice_asset_id": "a" * 32,
                        "seed": 9,
                    }
                ).encode(),
            )
            self.assertEqual(invalid.status, 400)
            removed_model = await api.handle(
                "POST",
                "/structured-director/audio-generations",
                json.dumps(
                    {
                        "expected_revision": response.body["revision"],
                        "model": "breeze_tts_2",
                        "operation": "voice_design",
                        "text": "测试语音",
                        "voice_description": "清晰女声",
                        "seed": 9,
                    }
                ).encode(),
            )
            self.assertEqual(removed_model.status, 400)
            missing_transcript = await api.handle(
                "POST",
                "/structured-director/audio-generations",
                json.dumps(
                    {
                        "expected_revision": response.body["revision"],
                        "operation": "synthesize",
                        "text": "测试语音",
                        "voice_asset_id": "a" * 32,
                        "seed": 9,
                    }
                ).encode(),
            )
            self.assertEqual(missing_transcript.status, 400)

    async def test_failed_generic_audio_generation_can_retry_same_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_id = "0" * 32
            project = Path(directory) / project_id
            project.mkdir()
            store = StructuredDirectorStore(project, project_id)
            provider = FailingSubmitProvider(ModelProviderError("busy", "模型繁忙"))
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            failed = await service._media.generate_asset_audio(
                text="重试文本",
                voice_description="清晰男声",
                seed=11,
                expected_revision=prepared.revision,
            )
            original = failed.generations[-1]
            retried = await service.retry_generation(
                original.id,
                expected_revision=failed.revision,
            )
            self.assertEqual(retried.generations[-1].retry_of, original.id)
            self.assertEqual(retried.generations[-1].target_id, original.target_id)
            self.assertEqual(retried.generations[-1].seed, original.seed)


if __name__ == "__main__":
    unittest.main()
