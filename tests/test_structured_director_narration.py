from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from script_helpers import shot_segments_at
from structured_director_fixtures import (
    ContinuousKeyframePlanner,
    NarrationReferenceProposer,
    NarrationScriptProposer,
    RecordingProposer,
    RecordingProvider,
    create_project,
    plan_narration_shots,
    synthesize_and_select_narration,
    synthesize_narration,
    upload_narrator_voice,
    wav_bytes,
)

from core.director_commands import (
    DirectorCommand,
    DirectorCommandRegistry,
)
from core.model_providers.boundary import (
    GenerationPhase,
)
from core.model_providers.contracts import AnimaticRequest
from core.structured_director import (
    DirectorScript,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    Shot,
    ShotSegment,
    StructuredDirectorHttpApi,
    StructuredDirectorStatus,
    StructuredDirectorStore,
)
from core.structured_director.models import WorkspaceLayers
from core.structured_director.service import (
    _align_duration_ranges,
    _clip_starts,
)


class StructuredDirectorNarrationTests(unittest.IsolatedAsyncioTestCase):
    def test_final_timeline_exactly_aligns_narration_after_transition_overlap(self) -> None:
        durations = _align_duration_ranges(
            [4.75, 4.75, 3.0],
            [(0, 1, 9.5)],
            0.35,
            [None, "seam_blend", None],
        )

        starts = _clip_starts(durations, 0.35, [None, "seam_blend", None])
        self.assertAlmostEqual(starts[1] + durations[1] - starts[0], 9.5, places=6)
        self.assertAlmostEqual(durations[1], 5.1, places=6)

    def test_final_timeline_rejects_impossible_narration_alignment(self) -> None:
        with self.assertRaisesRegex(ValueError, "无法与旁白覆盖区间精确对齐"):
            _align_duration_ranges([5.0, 0.5], [(0, 1, 1.0)], 0.35, [None, "seam_blend"])

    async def test_narration_cue_ids_are_unique_across_the_script(self) -> None:
        cue_id = "a" * 32

        def scene(index: int) -> Scene:
            shot_id = f"{index:032x}"
            shot = Shot(
                id=shot_id,
                visible_character_ids=(),
                composition="中景。",
                camera_movement="固定。",
                action="环境保持安静。",
                audio_direction="",
                transition_in=None,
            )
            segment = ShotSegment(
                id=f"{index + 10:032x}",
                shot_ids=(shot_id,),
                duration_estimate_seconds=2.5,
                action="环境保持安静。",
                dialogue_lines=(),
                boundary_from_previous=None,
            )
            return Scene(
                id=f"{index + 20:032x}",
                title=f"Scene {index}",
                summary="一段场景。",
                setting="室内。",
                driver="narration",
                shots=(shot,),
                segments=(segment,),
                narration_cues=(
                    NarrationCue(
                        id=cue_id,
                        zh=NarrationTrack("同一个 Cue ID 不应跨 Scene 复用。", 42),
                        en=NarrationTrack("A cue ID must not repeat across scenes.", 42),
                    ),
                ),
            )

        with self.assertRaisesRegex(ValueError, "旁白 Cue ID 不能重复"):
            DirectorScript(
                revision=1,
                source_reference_revision=1,
                production_baseline_revision=None,
                production_baseline_scenes=None,
                scenes=(scene(1), scene(2)),
            )

    async def test_narration_commands_update_exact_fields_and_clear_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("e" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "e" * 32)
            provider = RecordingProvider(
                media_type="audio/wav",
                content=wav_bytes(duration_seconds=3),
            )
            service = StructuredDirectorService(
                store,
                NarrationReferenceProposer(),
                script_proposer=NarrationScriptProposer(),
                speech_provider=provider,
            )
            create_project(store)
            references = await service.prepare_references()
            narrator = references.reference_library.narrator
            assert narrator is not None
            references = await upload_narrator_voice(service, references)
            scripted = await service.prepare_script(expected_revision=references.revision)
            review = await service.confirm_script(expected_revision=scripted.revision)
            assert review.director_script is not None
            scene = review.director_script.scenes[0]
            cue = scene.narration_cues[0]
            selected, generation_ids = await synthesize_and_select_narration(
                service, cue.id, review.revision
            )
            generation = next(
                item for item in selected.generations if item.id == generation_ids["zh"]
            )
            registry = DirectorCommandRegistry(store)
            unchanged = registry.execute(
                DirectorCommand(
                    "narration.update_cue",
                    selected.revision,
                    "narration-update-noop",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "cue_id": cue.id,
                        "fields": {"zh": {"text": cue.zh.text}},
                    },
                )
            )
            self.assertEqual(unchanged.receipt.status, "noop")
            assert unchanged.document.director_script is not None
            self.assertEqual(
                unchanged.document.director_script.scenes[0]
                .narration_cues[0]
                .zh.selected_audio_asset_id,
                generation.output_asset_id,
            )
            cleared = registry.execute(
                DirectorCommand(
                    "narration.clear_selection",
                    unchanged.document.revision,
                    "narration-clear",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "cue_id": cue.id,
                        "language": "zh",
                    },
                )
            )
            assert cleared.document.director_script is not None
            cleared_cue = cleared.document.director_script.scenes[0].narration_cues[0]
            self.assertIsNone(cleared_cue.zh.selected_audio_asset_id)
            # 只清除指定语言；英文选择保留。
            self.assertIsNotNone(cleared_cue.en.selected_audio_asset_id)
            self.assertIn(
                f"narration_selection:{cue.id}:zh",
                cleared.receipt.invalidated,
            )
            self.assertEqual(cleared.document.assets, selected.assets)
            self.assertEqual(cleared.document.generations, selected.generations)
            replay = registry.execute(
                DirectorCommand(
                    "narration.clear_selection",
                    cleared.document.revision,
                    "narration-clear-replay",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "cue_id": cue.id,
                        "language": "zh",
                    },
                )
            )
            self.assertEqual(replay.receipt.status, "noop")
            reselected = await service.select_narration_audio(
                cue_id=cue.id,
                generation_id=generation.id,
                expected_revision=replay.document.revision,
            )
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            response = await api.handle(
                "POST",
                (f"/structured-director/scenes/{scene.id}/narration-cues/{cue.id}/clear-selection"),
                json.dumps({"expected_revision": reselected.revision, "language": "zh"}).encode(),
            )
            self.assertEqual(response.status, 200, response.body)
            self.assertIsNone(
                response.body["director_script"]["scenes"][0]["narration_cues"][0]["zh"][
                    "selected_audio_asset_id"
                ]
            )
            # 测试 Provider 为中英返回相同字节，两条选择共用同一 Asset；清掉英文后才不再被引用。
            response = await api.handle(
                "POST",
                (f"/structured-director/scenes/{scene.id}/narration-cues/{cue.id}/clear-selection"),
                json.dumps(
                    {"expected_revision": response.body["revision"], "language": "en"}
                ).encode(),
            )
            self.assertEqual(response.status, 200, response.body)
            response_generation = next(
                item for item in response.body["generations"] if item["id"] == generation.id
            )
            self.assertIn("dismiss_history", response_generation["allowed_actions"])
            reselected = await service.select_narration_audio(
                cue_id=cue.id,
                generation_id=generation.id,
                expected_revision=response.body["revision"],
            )
            reselected = await service.select_narration_audio(
                cue_id=cue.id,
                generation_id=generation_ids["en"],
                expected_revision=reselected.revision,
            )
            updated = registry.execute(
                DirectorCommand(
                    "narration.update_cue",
                    reselected.revision,
                    "narration-update",
                    {
                        "scope": {"scene_ids": [scene.id]},
                        "cue_id": cue.id,
                        "fields": {"zh": {"seed": 7}},
                    },
                )
            )
            assert updated.document.director_script is not None
            updated_cue = updated.document.director_script.scenes[0].narration_cues[0]
            self.assertEqual(updated_cue.zh.text, cue.zh.text)
            self.assertEqual(updated_cue.zh.seed, 7)
            self.assertIsNone(updated_cue.zh.selected_audio_asset_id)
            self.assertIsNotNone(updated_cue.en.selected_audio_asset_id)
            self.assertIn(
                f"narration_selection:{cue.id}:zh",
                updated.receipt.invalidated,
            )
            before = store.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "未声明字段"):
                registry.execute(
                    DirectorCommand(
                        "narration.update_cue",
                        updated.document.revision,
                        "narration-invalid",
                        {
                            "scope": {"scene_ids": [scene.id]},
                            "cue_id": cue.id,
                            "fields": {"selected_audio_asset_id": "f" * 32},
                        },
                    )
                )
            self.assertEqual(store.path.read_bytes(), before)

    async def test_narration_spans_shots_and_real_audio_exactly_retimes_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("a" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "a" * 32)
            provider = RecordingProvider(
                media_type="audio/wav", content=wav_bytes(duration_seconds=8)
            )
            service = StructuredDirectorService(
                store,
                NarrationReferenceProposer(),
                script_proposer=NarrationScriptProposer(),
                speech_provider=provider,
            )
            create_project(store)
            references = await service.prepare_references()
            narrator = references.reference_library.narrator
            assert narrator is not None
            references = await upload_narrator_voice(
                service, references, wav_bytes(duration_seconds=2)
            )
            scripted = await service.prepare_script(expected_revision=references.revision)
            assert scripted.director_script is not None
            cue = scripted.director_script.scenes[0].narration_cues[0]
            self.assertEqual(scripted.director_script.scenes[0].segments, ())
            review = await service.confirm_script(expected_revision=scripted.revision)
            self.assertIs(review.status, StructuredDirectorStatus.REVIEWING_NARRATION)
            completed, generation_id = await synthesize_narration(
                service, cue.id, review.revision, "zh"
            )
            narration_asset = next(
                item
                for item in completed.assets
                if item.id == completed.generations[-1].output_asset_id
            )
            self.assertRegex(
                narration_asset.relative_path,
                r"^assets/audio/narration/Scene-01-末班车-Cue-01-旁白-中文-[0-9a-f]{10}\.wav$",
            )
            changed = await service.save_narration_cue(
                scene_id=scripted.director_script.scenes[0].id,
                cue=replace(cue, zh=replace(cue.zh, text="这是已经修改过的新版本旁白。")),
                expected_revision=completed.revision,
            )
            with self.assertRaisesRegex(ValueError, "旧版旁白正文"):
                await service.select_narration_audio(
                    cue_id=cue.id,
                    generation_id=generation_id,
                    expected_revision=changed.revision,
                )
            restored_cue = await service.save_narration_cue(
                scene_id=scripted.director_script.scenes[0].id,
                cue=cue,
                expected_revision=changed.revision,
            )
            selected = await service.select_narration_audio(
                cue_id=cue.id,
                generation_id=generation_id,
                expected_revision=restored_cue.revision,
            )
            selected, _ = await synthesize_and_select_narration(
                service, cue.id, selected.revision, ("en",)
            )
            # 选定真实音频后再规划 Shot；Core 在同一次写入里按音频校准。
            conformed = plan_narration_shots(store, selected)

            assert conformed.director_script is not None
            scene = conformed.director_script.scenes[0]
            scene_duration = sum(segment.duration_estimate_seconds for segment in scene.segments)
            self.assertAlmostEqual(scene_duration, 8.0, places=6)
            self.assertAlmostEqual(
                sum(segment.duration_estimate_seconds for segment in shot_segments_at(scene, 0)),
                4.0,
                places=6,
            )
            self.assertEqual(
                conformed.director_script.production_baseline_revision,
                conformed.director_script.revision,
            )
            self.assertIs(conformed.status, StructuredDirectorStatus.REVIEWING_NARRATION)
            restored = StructuredDirectorStore(project, "a" * 32).read()
            self.assertEqual(restored, conformed)
            # 重建 Service 后仍从持久化历史续接。
            restarted = StructuredDirectorService(
                StructuredDirectorStore(project, "a" * 32),
                NarrationReferenceProposer(),
                speech_provider=provider,
            )
            regenerated = await restarted.generate_narration(
                cue_id=cue.id,
                language="zh",
                expected_revision=restored.revision,
            )
            # 中文与英文的 seed 各自递增：中文已消耗一次，英文也只消耗过一次。
            self.assertEqual(regenerated.generations[-1].seed, cue.zh.seed + 1)
            self.assertEqual(provider.requests[-1].param("seed"), cue.zh.seed + 1)

    async def test_manual_narration_save_persists_in_script_and_narration_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("c" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "c" * 32)
            service = StructuredDirectorService(
                store, NarrationReferenceProposer(), script_proposer=NarrationScriptProposer()
            )
            create_project(store)
            references = await service.prepare_references()
            await service.prepare_script(expected_revision=references.revision)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            for narration_review in (False, True):
                if narration_review:
                    await service.confirm_script(expected_revision=store.read().revision)
                before = await api.handle("GET", "/structured-director")
                self.assertIn("edit_narration", before.body["allowed_actions"])
                scene = before.body["director_script"]["scenes"][0]
                cue = scene["narration_cues"][0]
                text = f"用户手动保存的旁白正文：{narration_review}。"
                payload = {
                    **{
                        language: {
                            key: cue[language][key] for key in ("text", "seed", "recipe_params")
                        }
                        for language in ("zh", "en")
                    },
                }
                payload["zh"]["text"] = text
                payload.update(expected_revision=before.body["revision"])
                path = f"/structured-director/scenes/{scene['id']}/narration-cues/{cue['id']}"
                saved = await api.handle("PUT", path, json.dumps(payload).encode())
                self.assertEqual(saved.status, 200, saved.body)
                self.assertEqual(saved.body["status"], before.body["status"])
                refreshed = await api.handle("GET", "/structured-director")
                actual = refreshed.body["director_script"]["scenes"][0]["narration_cues"][0]
                self.assertEqual(actual["zh"]["text"], text)
                restored = StructuredDirectorStore(project, "c" * 32).read()
                assert restored.director_script is not None
                self.assertEqual(restored.director_script.scenes[0].narration_cues[0].zh.text, text)
                stale = await api.handle("PUT", path, json.dumps(payload).encode())
                self.assertEqual(stale.status, 409)

    async def test_unlocked_narration_survives_every_later_review_stage(self) -> None:
        stages = (
            StructuredDirectorStatus.REVIEWING_NARRATION,
            StructuredDirectorStatus.REVIEWING_KEYFRAMES,
            StructuredDirectorStatus.REVIEWING_VIDEOS,
            StructuredDirectorStatus.REVIEWING_FINAL,
        )
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                project = Path(directory) / ("c" * 32)
                project.mkdir()
                store = StructuredDirectorStore(project, "c" * 32)
                provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
                service = StructuredDirectorService(
                    store,
                    NarrationReferenceProposer(),
                    script_proposer=NarrationScriptProposer(),
                    speech_provider=provider,
                )
                create_project(store)
                references = await service.prepare_references()
                narrator = references.reference_library.narrator
                assert narrator is not None
                voiced = await upload_narrator_voice(service, references)
                scripted = await service.prepare_script(expected_revision=voiced.revision)
                layers = WorkspaceLayers(
                    narration_unlocked=True,
                    keyframes_unlocked=index >= 1,
                    videos_unlocked=index >= 2,
                    final_assembly_unlocked=index >= 3,
                )
                # 表示高层计划已失效，但已解锁能力仍保留。
                store._atomic_write(
                    replace(
                        scripted,
                        status=stage,
                        workspace_layers=layers,
                        revision=scripted.revision + 1,
                    )
                )
                scripted = store.read()
                assert scripted.director_script is not None
                scene = scripted.director_script.scenes[0]
                cue = scene.narration_cues[0]
                saved = await service.save_narration_cue(
                    scene_id=scene.id,
                    cue=replace(cue, zh=replace(cue.zh, text="手动修改后仍能继续生成。")),
                    expected_revision=scripted.revision,
                )
                self.assertIs(saved.status, stage)
                self.assertEqual(saved.workspace_layers, layers)
                api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
                snapshot = await api.handle("GET", "/structured-director")
                for action in (
                    "edit_script",
                    "edit_narration",
                    "generate_narration",
                    "select_narration_audio",
                ):
                    self.assertIn(action, snapshot.body["allowed_actions"])
                self.assertNotIn("request_narration_edit", snapshot.body["allowed_actions"])
                assert saved.director_script is not None
                # 旁白正文变化清除音频选择，Core 无法校准，生产基线保持失效。
                self.assertNotEqual(
                    saved.director_script.production_baseline_revision,
                    saved.director_script.revision,
                )
                reviewed, _ = await synthesize_and_select_narration(service, cue.id, saved.revision)
                # 旁白驱动：选定音频后才规划 Shot，Core 在这次写入里校准并建立基线。
                reviewed = plan_narration_shots(store, reviewed)
                assert reviewed.director_script is not None
                # 选齐音频的同一次写入里 Core 自动校准并建立生产基线，无需人工确认时序。
                self.assertEqual(
                    reviewed.director_script.production_baseline_revision,
                    reviewed.director_script.revision,
                )
                self.assertIs(reviewed.status, saved.status)
                self.assertEqual(store.read().workspace_layers, layers)
                changed = await service.save_script(
                    (replace(reviewed.director_script.scenes[0], title="再次修改脚本"),),
                    expected_revision=reviewed.revision,
                )
                self.assertIs(changed.status, saved.status)
                self.assertEqual(changed.workspace_layers, layers)
                self.assertEqual(changed.assets, reviewed.assets)
                self.assertEqual(changed.generations, reviewed.generations)

    async def test_voice_design_candidate_requires_explicit_selection(self) -> None:
        wav = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("2" * 32)
            project.mkdir()
            provider = RecordingProvider(media_type="audio/wav", content=wav)
            store = StructuredDirectorStore(project, "2" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            card = prepared.reference_library.characters[0]
            submitted = await service._media.design_voice(
                card_id=card.id,
                voice_description="年轻、温和、气息稳定",
                sample_text="我们从这里开始。",
                seed=42,
                expected_revision=prepared.revision,
            )
            generation_id = submitted.generations[0].id
            await service._generation_observer.refresh_generation(generation_id)
            completed = await service._generation_observer.refresh_generation(generation_id)

            self.assertIsNone(completed.reference_library.characters[0].voice_reference_asset_id)
            attached = await service.attach_generation_output(
                kind="voice",
                card_id=card.id,
                generation_id=generation_id,
                note="",
                expected_revision=completed.revision,
            )
            self.assertIsNotNone(attached.reference_library.characters[0].voice_reference_asset_id)
            self.assertEqual(provider.requests[0].param("text"), "我们从这里开始。")

    async def test_narration_clones_only_the_same_language_narrator_voice(self) -> None:
        zh_voice = wav_bytes(duration_seconds=1)
        en_voice = wav_bytes(duration_seconds=2)
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("e" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "e" * 32)
            provider = RecordingProvider(
                media_type="audio/wav", content=wav_bytes(duration_seconds=3)
            )
            service = StructuredDirectorService(
                store,
                NarrationReferenceProposer(),
                script_proposer=NarrationScriptProposer(),
                speech_provider=provider,
            )
            create_project(store)
            references = await service.prepare_references()
            narrator = references.reference_library.narrator
            assert narrator is not None
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            upload = "/structured-director/narrator/voice-reference/upload?"
            missing_language = await api.handle(
                "POST",
                upload
                + urlencode({"expected_revision": references.revision, "narrator_id": narrator.id}),
                zh_voice,
                media_type="audio/wav",
            )
            self.assertEqual(missing_language.status, 400)
            uploaded = await api.handle(
                "POST",
                upload
                + urlencode(
                    {
                        "expected_revision": references.revision,
                        "narrator_id": narrator.id,
                        "language": "zh",
                    }
                ),
                zh_voice,
                media_type="audio/wav",
            )
            self.assertEqual(uploaded.status, 200)
            voiced = store.read()
            narrator = voiced.reference_library.narrator
            self.assertIsNotNone(narrator.zh.voice_reference_asset_id)
            self.assertIsNone(narrator.en.voice_reference_asset_id)
            zh_asset = next(
                item for item in voiced.assets if item.id == narrator.zh.voice_reference_asset_id
            )
            self.assertIn("中文参考音色", zh_asset.relative_path)
            voiced = await service.update_narrator(
                narrator.with_voice(
                    NarrationLanguage.ZH,
                    replace(narrator.zh, voice_reference_transcript="中文参考文字稿。"),
                ),
                expected_revision=voiced.revision,
            )
            scripted = await service.prepare_script(expected_revision=voiced.revision)
            review = await service.confirm_script(expected_revision=scripted.revision)
            cue = review.director_script.scenes[0].narration_cues[0]

            with self.assertRaisesRegex(ValueError, "英文参考音色"):
                await service.generate_narration(
                    cue_id=cue.id, language="en", expected_revision=review.revision
                )
            with_en = await service.upload_narrator_voice(
                narrator_id=narrator.id,
                language=NarrationLanguage.EN,
                media_type="audio/wav",
                content=en_voice,
                expected_revision=review.revision,
            )
            narrator = with_en.reference_library.narrator
            self.assertEqual(narrator.zh.voice_reference_transcript, "中文参考文字稿。")
            self.assertNotEqual(
                narrator.zh.voice_reference_asset_id, narrator.en.voice_reference_asset_id
            )
            with self.assertRaisesRegex(ValueError, "英文参考音色填写完整文字稿"):
                await service.generate_narration(
                    cue_id=cue.id, language="en", expected_revision=with_en.revision
                )
            ready = await service.update_narrator(
                narrator.with_voice(
                    NarrationLanguage.EN,
                    replace(narrator.en, voice_reference_transcript="English reference script."),
                ),
                expected_revision=with_en.revision,
            )
            zh_done, zh_generation_id = await synthesize_narration(
                service, cue.id, ready.revision, "zh"
            )
            en_done, en_generation_id = await synthesize_narration(
                service, cue.id, zh_done.revision, "en"
            )

            generations = {item.id: item for item in en_done.generations}
            self.assertEqual(
                generations[zh_generation_id].input_asset_ids,
                (narrator.zh.voice_reference_asset_id,),
            )
            self.assertEqual(
                generations[en_generation_id].input_asset_ids,
                (narrator.en.voice_reference_asset_id,),
            )
            zh_request, en_request = provider.requests
            self.assertEqual(zh_request.single("voice").content, zh_voice)
            self.assertEqual(zh_request.param("reference_transcript"), "中文参考文字稿。")
            self.assertEqual(en_request.single("voice").content, en_voice)
            self.assertEqual(en_request.param("reference_transcript"), "English reference script.")

    async def test_designed_narrator_voice_attaches_only_to_its_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("e" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "e" * 32)
            provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
            service = StructuredDirectorService(
                store, NarrationReferenceProposer(), voice_provider=provider
            )
            create_project(store)
            prepared = await service.prepare_references()
            narrator = prepared.reference_library.narrator
            assert narrator is not None
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            designed = await api.handle(
                "POST",
                "/structured-director/narrator/voice-generations",
                json.dumps(
                    {
                        "expected_revision": prepared.revision,
                        "narrator_id": narrator.id,
                        "language": "en",
                        "voice_description": "British RP, low and measured.",
                        "sample_text": "For the future of France.",
                        "seed": 7,
                    }
                ).encode(),
            )
            self.assertEqual(designed.status, 202)
            generation = store.read().generations[-1]
            self.assertIs(generation.kind, ReferenceGenerationKind.NARRATOR_VOICE)
            self.assertIs(generation.language, NarrationLanguage.EN)
            await service._generation_observer.refresh_generation(generation.id)
            completed = await service._generation_observer.refresh_generation(generation.id)
            asset = next(
                item
                for item in completed.assets
                if item.id == completed.generations[-1].output_asset_id
            )
            self.assertIn("英文参考音色候选", asset.relative_path)

            attached = await service.attach_generation_output(
                kind="narrator_voice",
                card_id=narrator.id,
                generation_id=generation.id,
                note="",
                expected_revision=completed.revision,
            )
            updated = attached.reference_library.narrator
            self.assertEqual(updated.zh, narrator.zh)
            self.assertEqual(updated.en.voice_description, "British RP, low and measured.")
            self.assertEqual(updated.en.voice_reference_asset_id, asset.id)
            self.assertEqual(updated.en.voice_reference_transcript, "For the future of France.")

    async def test_uploaded_wav_becomes_explicit_voice_reference_asset(self) -> None:
        wav = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("a" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "a" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            card = prepared.reference_library.characters[0]
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            upload_path = (
                f"/structured-director/characters/{card.id}/voice-reference/upload?"
                + urlencode(
                    {
                        "expected_revision": prepared.revision,
                        "filename": "studio take 01.wav",
                    }
                )
            )

            uploaded = await api.handle(
                "POST",
                upload_path,
                wav,
                media_type="audio/wav",
            )

            self.assertEqual(uploaded.status, 200)
            selected_id = uploaded.body["reference_library"]["characters"][0][
                "voice_reference_asset_id"
            ]
            self.assertIsNotNone(selected_id)
            self.assertEqual(uploaded.body["assets"][0]["media_type"], "audio/wav")
            descriptor, content = service.read_asset(selected_id)
            self.assertEqual(descriptor.sha256, hashlib.sha256(wav).hexdigest())
            self.assertRegex(
                descriptor.relative_path,
                r"^assets/audio/voice-references/studio-take-01-[0-9a-f]{10}\.wav$",
            )
            self.assertEqual(content, wav)

            unknown_field = await api.handle(
                "POST",
                upload_path + "&path=C%3A%2Fvoice.wav",
                wav,
                media_type="audio/wav",
            )
            self.assertEqual(unknown_field.status, 400)

            wrong_type = await api.handle(
                "POST",
                f"/structured-director/characters/{card.id}/voice-reference/upload?"
                + urlencode({"expected_revision": uploaded.body["revision"]}),
                wav,
                media_type="audio/mpeg",
            )
            self.assertEqual(wrong_type.status, 400)

    async def test_scene_animatic_splits_fl2va_clips_and_aligns_narration(self) -> None:
        generated_png = b"\x89PNG\r\n\x1a\nkeyframe"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("e" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "e" * 32)
            image_provider = RecordingProvider(media_type="image/png", content=generated_png)
            speech_provider = RecordingProvider(
                media_type="audio/wav", content=wav_bytes(duration_seconds=8)
            )
            animatic_provider = RecordingProvider(
                media_type="video/mp4",
                content=b"\x00\x00\x00\x18ftypmp42animatic",
                duration_seconds=8.0,
            )
            service = StructuredDirectorService(
                store,
                NarrationReferenceProposer(),
                script_proposer=NarrationScriptProposer(),
                keyframe_planner=ContinuousKeyframePlanner(),
                image_provider=image_provider,
                speech_provider=speech_provider,
                animatic_provider=animatic_provider,
            )
            create_project(store)
            references = await service.prepare_references()
            narrator = references.reference_library.narrator
            assert narrator is not None
            references = await upload_narrator_voice(
                service, references, wav_bytes(duration_seconds=2)
            )
            scripted = await service.prepare_script(expected_revision=references.revision)
            review = await service.confirm_script(expected_revision=scripted.revision)
            assert review.director_script is not None
            scene_id = review.director_script.scenes[0].id
            cue = review.director_script.scenes[0].narration_cues[0]
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            selected_audio, _ = await synthesize_and_select_narration(
                service, cue.id, review.revision
            )
            baseline = plan_narration_shots(store, selected_audio)

            early_snapshot = await api.handle("GET", "/structured-director", b"")
            early_scene = next(
                item
                for item in early_snapshot.body["director_script"]["scenes"]
                if item["id"] == scene_id
            )
            self.assertFalse(early_scene["animatic"]["ready"])
            self.assertTrue(early_scene["animatic"]["provider_available"])
            early = await api.handle(
                "POST",
                f"/structured-director/scenes/{scene_id}/animatic",
                json.dumps({"expected_revision": baseline.revision}).encode(),
            )
            self.assertEqual(early.status, 400)

            visual = await service.unlock_visual_production(expected_revision=baseline.revision)
            planned = await service.prepare_keyframes(expected_revision=visual.revision)
            image_provider.observations = [GenerationPhase.SUCCEEDED] * 6
            document = await service.generate_keyframe_batch(expected_revision=planned.revision)
            terminal = {
                ReferenceGenerationPhase.SUCCEEDED,
                ReferenceGenerationPhase.FAILED,
                ReferenceGenerationPhase.CANCELLED,
            }
            while True:
                pending = [
                    item
                    for item in document.generations
                    if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                    and item.phase not in terminal
                ]
                if pending:
                    document = await service._generation_observer.refresh_generation(pending[0].id)
                    continue
                assert document.keyframe_plan is not None
                active_ids = {
                    keyframe_id
                    for binding in document.keyframe_plan.segments
                    for enabled, keyframe_id in (
                        (binding.start_enabled, binding.start_keyframe_id),
                        (binding.end_enabled, binding.end_keyframe_id),
                    )
                    if enabled
                }
                submitted_ids = {
                    item.target_id
                    for item in document.generations
                    if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                }
                if active_ids <= submitted_ids:
                    break
                document = await service.generate_keyframe_batch(
                    expected_revision=document.revision
                )
            assert document.keyframe_plan is not None
            generation_by_target = {
                item.target_id: item
                for item in document.generations
                if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                and item.phase is ReferenceGenerationPhase.SUCCEEDED
            }
            for keyframe in document.keyframe_plan.keyframes:
                generation = generation_by_target[keyframe.id]
                document = await service.select_keyframe(
                    keyframe_id=keyframe.id,
                    asset_id=generation.output_asset_id or "",
                    expected_revision=document.revision,
                )

            ready_snapshot = await api.handle("GET", "/structured-director", b"")
            self.assertIn("generate_scene_animatic", ready_snapshot.body["allowed_actions"])
            ready_scene = next(
                item
                for item in ready_snapshot.body["director_script"]["scenes"]
                if item["id"] == scene_id
            )
            self.assertTrue(ready_scene["animatic"]["ready"])
            self.assertIsNone(ready_scene["animatic"]["active_generation_id"])

            response = await api.handle(
                "POST",
                f"/structured-director/scenes/{scene_id}/animatic",
                json.dumps({"expected_revision": document.revision}).encode(),
            )
            self.assertEqual(response.status, 202, response.body)
            self.assertEqual(len(animatic_provider.requests), 1)
            request = animatic_provider.requests[0]
            self.assertIsInstance(request, AnimaticRequest)
            self.assertEqual(request.aspect_ratio, "16:9")
            self.assertEqual(len(request.clips), 4)
            self.assertEqual(
                [item.transition_from_previous for item in request.clips],
                [None, None, "seam_blend", None],
            )
            self.assertEqual(
                [item.duration_seconds for item in request.clips[:3]],
                [2.0, 2.0, 2.0],
            )
            self.assertAlmostEqual(request.clips[3].duration_seconds, 2.1, places=6)
            self.assertEqual(len(request.narrations), 1)
            self.assertEqual(request.narrations[0].start_clip_index, 0)

            duplicate = await api.handle(
                "POST",
                f"/structured-director/scenes/{scene_id}/animatic",
                json.dumps({"expected_revision": response.body["revision"]}).encode(),
            )
            self.assertEqual(duplicate.status, 400)
            # 落后的 revision 期间只新增了 Generation，与该 Scene 不相交：按当前状态判定，
            # 被“已有进行中的 Animatic”这一业务规则拒绝，而不是笼统的 revision 冲突。
            stale = await api.handle(
                "POST",
                f"/structured-director/scenes/{scene_id}/animatic",
                json.dumps({"expected_revision": response.body["revision"] - 1}).encode(),
            )
            self.assertEqual(stale.status, 400)
            self.assertEqual(stale.body["error"]["message"], duplicate.body["error"]["message"])

            animatic_generation_id = next(
                item["id"]
                for item in response.body["generations"]
                if item["kind"] == "scene_animatic"
            )
            busy_scene = next(
                item
                for item in response.body["director_script"]["scenes"]
                if item["id"] == scene_id
            )
            self.assertEqual(busy_scene["animatic"]["active_generation_id"], animatic_generation_id)
            animatic_provider.observations = [GenerationPhase.SUCCEEDED]
            completed_animatic = await service._generation_observer.refresh_generation(
                animatic_generation_id
            )
            completed_generation = next(
                item for item in completed_animatic.generations if item.id == animatic_generation_id
            )
            self.assertIs(completed_generation.phase, ReferenceGenerationPhase.SUCCEEDED)
            animatic_asset = next(
                item
                for item in completed_animatic.assets
                if item.id == completed_generation.output_asset_id
            )
            self.assertEqual(animatic_asset.duration_seconds, 8.0)
            self.assertEqual(
                animatic_asset.relative_path,
                "assets/videos/animatics/Scene-01-末班车-Animatic预览.mp4",
            )

            final_snapshot = await api.handle("GET", "/structured-director", b"")
            animatic_payload = next(
                item
                for item in final_snapshot.body["generations"]
                if item["id"] == animatic_generation_id
            )
            self.assertEqual(animatic_payload["allowed_actions"], ["dismiss_history"])
            final_scene = next(
                item
                for item in final_snapshot.body["director_script"]["scenes"]
                if item["id"] == scene_id
            )
            self.assertIsNone(final_scene["animatic"]["active_generation_id"])
            self.assertEqual(
                final_scene["animatic"]["latest_succeeded_generation_id"],
                animatic_generation_id,
            )

            second = await api.handle(
                "POST",
                f"/structured-director/scenes/{scene_id}/animatic",
                json.dumps({"expected_revision": final_snapshot.body["revision"]}).encode(),
            )
            self.assertEqual(second.status, 202, second.body)
            self.assertEqual(len(animatic_provider.requests), 2)
