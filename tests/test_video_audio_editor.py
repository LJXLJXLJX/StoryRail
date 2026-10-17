from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import RecordingProposer, create_project, wav_bytes

from core.audio_effects import AudioEffectRequest
from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ProviderHandle,
)
from core.structured_director import (
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)


class ImmediateStemProvider:
    plugin_id = "demucs.audio-separation"
    plugin_version = 1

    def __init__(self) -> None:
        self.requests = []
        self.outputs: dict[str, bytes] = {}

    def submit(self, request) -> ProviderHandle:
        self.requests.append(request)
        task_id = f"{len(self.requests):032x}"
        content = bytearray(wav_bytes(duration_seconds=0.25, sample_rate=12_000))
        content[-2:] = b"\x01\x00" if request.stem == "voice" else b"\x02\x00"
        self.outputs[task_id] = bytes(content)
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        content = self.outputs[handle.external_id]
        return GenerationObservation(
            GenerationPhase.SUCCEEDED,
            1.0,
            "分离完成",
            ArtifactDescriptor(
                handle.external_id,
                "audio/wav",
                len(content),
                hashlib.sha256(content).hexdigest(),
                0.25,
            ),
        )

    def cancel(self, _handle: ProviderHandle) -> GenerationObservation:
        return GenerationObservation(GenerationPhase.CANCELLED, 0.0, "已取消")

    def read_artifact(self, handle: ProviderHandle, _artifact_id: str) -> bytes:
        return self.outputs[handle.external_id]


class ImmediateRemixProvider(ImmediateStemProvider):
    plugin_id = "ffmpeg.audio-remix"

    def submit(self, request) -> ProviderHandle:
        self.requests.append(request)
        task_id = f"{len(self.requests) + 100:032x}"
        self.outputs[task_id] = b"\x00\x00\x00\x18ftypmp42remixed"
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        content = self.outputs[handle.external_id]
        return GenerationObservation(
            GenerationPhase.SUCCEEDED,
            1.0,
            "混音完成",
            ArtifactDescriptor(
                handle.external_id,
                "video/mp4",
                len(content),
                hashlib.sha256(content).hexdigest(),
                0.25,
            ),
        )


class VideoAudioEditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_separate_effect_and_remix_preserve_source_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_id = "0" * 32
            project = Path(directory) / project_id
            project.mkdir()
            store = StructuredDirectorStore(project, project_id)
            stems = ImmediateStemProvider()
            remix = ImmediateRemixProvider()
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                audio_separation_provider=stems,
                audio_remix_provider=remix,
            )
            create_project(store)
            prepared = await service.prepare_references()
            source_bytes = b"\x00\x00\x00\x18ftypmp42source-video"
            document, source = store._ingest_asset(
                prepared,
                "video/mp4",
                source_bytes,
                duration_seconds=0.25,
                directory="videos/segments",
                label="测试视频",
            )
            document = replace(document, revision=prepared.revision + 1)
            store._atomic_write(document)

            submitted = await service.separate_video_audio(
                source_asset_id=source.id,
                expected_revision=document.revision,
            )
            separated = [
                item
                for item in submitted.generations
                if item.kind
                in {
                    ReferenceGenerationKind.VIDEO_AUDIO_VOICE,
                    ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND,
                }
            ]
            self.assertEqual(len(separated), 2)
            self.assertEqual(
                len({json.loads(item.prompt_text)["batch_id"] for item in separated}), 1
            )
            for generation in separated:
                await service._generation_observer.refresh_generation(generation.id)
            completed = service.snapshot_required()
            voice_generation = next(
                item
                for item in completed.generations
                if item.kind is ReferenceGenerationKind.VIDEO_AUDIO_VOICE
            )
            background_generation = next(
                item
                for item in completed.generations
                if item.kind is ReferenceGenerationKind.VIDEO_AUDIO_BACKGROUND
            )
            voice_id = voice_generation.output_asset_id or ""
            background_id = background_generation.output_asset_id or ""
            self.assertEqual(service.read_asset(source.id)[1], source_bytes)
            self.assertEqual(service.read_asset(voice_id)[0].media_type, "audio/wav")
            self.assertEqual(service.read_asset(background_id)[0].media_type, "audio/wav")

            effected = await service.apply_audio_effect(
                source_asset_id=voice_id,
                request=AudioEffectRequest("radio", "weak_signal", 0.7, 42),
                expected_revision=completed.revision,
            )
            processed_voice_id = effected.generations[-1].output_asset_id or ""
            remixed = await service.remix_video_audio(
                source_asset_id=source.id,
                voice_asset_id=processed_voice_id,
                background_asset_id=background_id,
                voice_gain_db=-2.5,
                background_gain_db=-6.0,
                expected_revision=effected.revision,
                voice_gain_start_seconds=0.05,
                voice_gain_end_seconds=0.2,
                background_gain_start_seconds=0.1,
                background_gain_end_seconds=0.24,
            )
            request = remix.requests[-1]
            self.assertEqual(request.voice_gain_start_seconds, 0.05)
            self.assertEqual(request.voice_gain_end_seconds, 0.2)
            self.assertEqual(request.background_gain_start_seconds, 0.1)
            self.assertEqual(request.background_gain_end_seconds, 0.24)
            remix_generation = remixed.generations[-1]
            remix_parameters = json.loads(remix_generation.prompt_text)
            self.assertEqual(remix_parameters["schema"], "storyrail_audio_remix_v2")
            self.assertEqual(remix_parameters["voice_gain_start_seconds"], 0.05)
            await service._generation_observer.refresh_generation(remix_generation.id)
            final = service.snapshot_required()
            output = final.generations[-1]
            self.assertEqual(output.kind, ReferenceGenerationKind.VIDEO_AUDIO_REMIX)
            self.assertEqual(output.input_asset_ids, (source.id, processed_voice_id, background_id))
            self.assertEqual(
                service.read_asset(output.output_asset_id or "")[0].media_type, "video/mp4"
            )
            self.assertEqual(service.read_asset(source.id)[1], source_bytes)

            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            snapshot = await api.handle("GET", "/structured-director")
            source_view = next(item for item in snapshot.body["assets"] if item["id"] == source.id)
            self.assertIn("audio_editor", source_view["allowed_actions"])

            response = await api.handle(
                "POST",
                f"/structured-director/assets/{source.id}/audio-remix",
                json.dumps(
                    {
                        "expected_revision": final.revision,
                        "voice_asset_id": processed_voice_id,
                        "background_asset_id": background_id,
                        "voice_gain_db": -4,
                        "background_gain_db": -8,
                        "voice_gain_start_seconds": 0.02,
                        "voice_gain_end_seconds": 0.2,
                        "background_gain_start_seconds": 0.04,
                        "background_gain_end_seconds": 0.22,
                    }
                ).encode(),
            )
            self.assertEqual(response.status, 202)
            self.assertEqual(remix.requests[-1].voice_gain_db, -4)
            self.assertEqual(remix.requests[-1].voice_gain_start_seconds, 0.02)

    async def test_failed_stem_retry_preserves_batch_and_creates_new_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_id = "1" * 32
            project = Path(directory) / project_id
            project.mkdir()
            store = StructuredDirectorStore(project, project_id)
            stems = ImmediateStemProvider()
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                audio_separation_provider=stems,
            )
            create_project(store)
            prepared = await service.prepare_references()
            document, source = store._ingest_asset(
                prepared,
                "video/mp4",
                b"\x00\x00\x00\x18ftypmp42source-video",
                duration_seconds=0.25,
                directory="videos/segments",
                label="测试视频",
            )
            document = replace(document, revision=prepared.revision + 1)
            store._atomic_write(document)
            submitted = await service.separate_video_audio(
                source_asset_id=source.id,
                expected_revision=document.revision,
            )
            original = next(
                item
                for item in submitted.generations
                if item.kind is ReferenceGenerationKind.VIDEO_AUDIO_VOICE
            )
            store.update_generation(
                replace(
                    original,
                    phase=ReferenceGenerationPhase.FAILED,
                    error_code="runtime_failed",
                    message="分离失败",
                )
            )
            failed = service.snapshot_required()

            retried = await service.retry_generation(
                original.id,
                expected_revision=failed.revision,
            )

            retry = retried.generations[-1]
            self.assertEqual(retry.retry_of, original.id)
            self.assertEqual(retry.kind, ReferenceGenerationKind.VIDEO_AUDIO_VOICE)
            self.assertEqual(
                json.loads(retry.prompt_text)["batch_id"],
                json.loads(original.prompt_text)["batch_id"],
            )
            self.assertEqual(stems.requests[-1].stem, "voice")


if __name__ == "__main__":
    unittest.main()
