from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import (
    FailingSubmitProvider,
    InvalidObserveProvider,
    NarrationReferenceProposer,
    RecordingProposer,
    RecordingProvider,
    UnreachableObserveProvider,
    create_project,
    install_location,
    wav_bytes,
)
from test_director_commands import _visual_project
from video_recipes import (
    SegmentVideoAudioReference,
    SegmentVideoImageReference,
    SegmentVideoVideoReference,
    replace_video,
)

from core.application.requests import ApplicationRequest, canonical
from core.director_commands import (
    DirectorCommand,
    DirectorCommandRegistry,
)
from core.model_providers.boundary import (
    GenerationPhase,
    ModelProviderError,
)
from core.structured_director import (
    Asset,
    CharacterLook,
    GenerationOperation,
    ImageAssetCategory,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)
from core.structured_director.models import NarrationLanguage, transition_generation
from core.structured_director.reads.snapshot_view import _scene_final_state
from core.structured_director.service import (
    _link_retry,
    _next_generation_seed,
)


def _mp4_bytes(*, duration_seconds: float) -> bytes:
    def box(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I4s", len(payload) + 8, kind) + payload

    mvhd = box(
        b"mvhd",
        b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1_000, int(duration_seconds * 1_000)),
    )
    return box(b"ftyp", b"isom\x00\x00\x02\x00isom") + box(b"moov", mvhd)


class StructuredDirectorGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_imports_unbound_wav_and_mp4_assets_with_core_derived_durations(self) -> None:
        def box(kind: bytes, payload: bytes) -> bytes:
            return struct.pack(">I4s", len(payload) + 8, kind) + payload

        wav = wav_bytes(duration_seconds=1.25)
        mvhd = box(
            b"mvhd",
            b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1_000, 2_500),
        )
        mp4 = box(b"ftyp", b"isom\x00\x00\x02\x00isom") + box(b"moov", mvhd)
        with tempfile.TemporaryDirectory() as directory:
            store = StructuredDirectorStore(Path(directory), "2" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            audio_response = await api.handle(
                "POST",
                "/structured-director/assets/media?"
                + urlencode({"expected_revision": prepared.revision, "filename": "现场录音.wav"}),
                wav,
                media_type="audio/wav",
            )
            self.assertEqual(audio_response.status, 200)
            audio_asset = service.snapshot_required().assets[0]
            self.assertEqual(audio_asset.duration_seconds, 1.25)
            self.assertRegex(
                audio_asset.relative_path,
                r"^assets/audio/imported/现场录音-[0-9a-f]{10}\.wav$",
            )

            video_response = await api.handle(
                "POST",
                "/structured-director/assets/media?"
                + urlencode(
                    {
                        "expected_revision": service.snapshot_required().revision,
                        "filename": "现场素材.mp4",
                    }
                ),
                mp4,
                media_type="video/mp4",
            )
            self.assertEqual(video_response.status, 200)
            video_asset = service.snapshot_required().assets[1]
            self.assertEqual(video_asset.duration_seconds, 2.5)
            self.assertRegex(
                video_asset.relative_path,
                r"^assets/videos/imported/现场素材-[0-9a-f]{10}\.mp4$",
            )
            self.assertFalse(service.snapshot_required().generations)

    async def test_media_import_rejects_mismatched_or_durationless_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StructuredDirectorStore(Path(directory), "3" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            invalid = await api.handle(
                "POST",
                "/structured-director/assets/media?"
                + urlencode({"expected_revision": prepared.revision}),
                b"\x00\x00\x00\x18ftypisom",
                media_type="video/mp4",
            )
            self.assertEqual(invalid.status, 400)
            self.assertIn("MP4 Asset", invalid.body["error"]["message"])
            unsupported = await api.handle(
                "POST",
                "/structured-director/assets/media?"
                + urlencode({"expected_revision": prepared.revision}),
                b"not-an-mp3",
                media_type="audio/mpeg",
            )
            self.assertEqual(unsupported.status, 400)
            self.assertIn("只支持 WAV 音频或 MP4 视频", unsupported.body["error"]["message"])

    def test_scene_final_submission_uncertain_is_not_rendered_as_active(self) -> None:
        generation = SimpleNamespace(
            id="a" * 32,
            kind=ReferenceGenerationKind.SCENE_FINAL_VIDEO,
            target_id="b" * 32,
            phase=ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
            dismissed=False,
            language=NarrationLanguage.ZH,
        )
        document = SimpleNamespace(
            generations=(generation,), narration_languages=tuple(NarrationLanguage)
        )
        service = SimpleNamespace(final_assembly_available=True)
        with (
            patch("core.structured_director.reads.snapshot_view._build_scene_final_plan"),
            patch(
                "core.structured_director.reads.snapshot_view._current_scene_final_asset_id",
                return_value=None,
            ),
        ):
            state = _scene_final_state(document, generation.target_id, service)
        self.assertIsNone(state["zh"]["active_generation_id"])

    def test_asset_display_name_hides_internal_collision_hash(self) -> None:
        asset = Asset(
            "b" * 32,
            "image/png",
            1,
            "b" * 64,
            "assets/images/library/科内利斯-bc3772c643.png",
        )
        self.assertEqual(asset.display_name, "科内利斯.png")
        ordinary = replace(asset, relative_path="assets/images/library/coast-reference.png")
        self.assertEqual(ordinary.display_name, "coast-reference.png")

    def test_seed_increments_per_target_and_kind_including_failed_attempts(self) -> None:
        kind = ReferenceGenerationKind.NARRATION_AUDIO
        history = []
        document = SimpleNamespace(generations=history)
        self.assertEqual(_next_generation_seed(document, kind, "cue", 42), 42)
        for seed, phase in [
            (42, ReferenceGenerationPhase.SUCCEEDED),
            (43, ReferenceGenerationPhase.FAILED),
            (44, ReferenceGenerationPhase.CANCELLED),
        ]:
            history.append(
                SimpleNamespace(
                    kind=kind,
                    target_id="cue",
                    seed=seed,
                    phase=phase,
                    dismissed=True,
                    language=NarrationLanguage.ZH,
                )
            )
            self.assertEqual(
                _next_generation_seed(document, kind, "cue", 42, language=NarrationLanguage.ZH),
                seed + 1,
            )
        # 中英文 seed 各自递增：英文没有历史，仍从初始 seed 开始。
        self.assertEqual(
            _next_generation_seed(document, kind, "cue", 42, language=NarrationLanguage.EN), 42
        )
        self.assertEqual(_next_generation_seed(document, kind, "other", 42), 42)
        self.assertEqual(
            _next_generation_seed(document, ReferenceGenerationKind.CHARACTER_VOICE, "cue", 42), 42
        )
        self.assertEqual(
            _next_generation_seed(document, kind, "cue", 100, language=NarrationLanguage.ZH), 100
        )
        with self.assertRaisesRegex(ValueError, "上限"):
            _next_generation_seed(
                document, kind, "cue", 42, maximum=44, language=NarrationLanguage.ZH
            )

    def test_only_identical_request_after_failure_links_retry(self) -> None:
        failed = ReferenceGeneration(
            id="a" * 32,
            kind=ReferenceGenerationKind.FINAL_VIDEO,
            operation=GenerationOperation.ASSEMBLE,
            target_id="c" * 32,
            phase=ReferenceGenerationPhase.FAILED,
            progress=0.1,
            message="失败",
            prompt_text="装配成片",
            input_asset_ids=("d" * 32,),
            sample_text=None,
            seed=None,
            plugin_id="test.final",
            plugin_version=1,
            external_id="external-1",
            output_asset_id=None,
            error_code="failed",
            cancellation_requested=False,
            retry_of=None,
            duration_seconds=8.0,
            language=NarrationLanguage.ZH,
        )
        candidate = replace(
            failed,
            id="b" * 32,
            phase=ReferenceGenerationPhase.SUBMITTING,
            progress=0.0,
            message="提交中",
            plugin_id=None,
            plugin_version=None,
            external_id=None,
            error_code=None,
        )
        document = SimpleNamespace(generations=(failed,))

        linked = _link_retry(document, candidate)  # type: ignore[arg-type]
        changed = _link_retry(  # type: ignore[arg-type]
            document, replace(candidate, prompt_text="修改后重新装配")
        )
        after_success = _link_retry(  # type: ignore[arg-type]
            SimpleNamespace(
                generations=(
                    replace(
                        failed,
                        phase=ReferenceGenerationPhase.SUCCEEDED,
                        progress=1.0,
                        output_asset_id="e" * 32,
                        error_code=None,
                    ),
                )
            ),
            candidate,
        )

        self.assertEqual(linked.retry_of, failed.id)
        self.assertIsNone(changed.retry_of)
        self.assertIsNone(after_success.retry_of)

    def test_generation_state_machine_is_central_and_rejects_terminal_rewrites(self) -> None:
        queued = ReferenceGeneration(
            id="8" * 32,
            kind=ReferenceGenerationKind.KEYFRAME_IMAGE,
            operation=GenerationOperation.GENERATE,
            target_id="9" * 32,
            phase=ReferenceGenerationPhase.QUEUED,
            progress=0.0,
            message="排队中",
            prompt_text="角色设定图",
            input_asset_ids=(),
            sample_text=None,
            seed=None,
            plugin_id="test.image",
            plugin_version=1,
            external_id="external-1",
            output_asset_id=None,
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
        )
        cancelled = transition_generation(
            queued,
            ReferenceGenerationPhase.CANCELLED,
            message="已取消",
        )

        self.assertIs(cancelled.phase, ReferenceGenerationPhase.CANCELLED)
        with self.assertRaisesRegex(ValueError, "不能从 cancelled"):
            transition_generation(cancelled, ReferenceGenerationPhase.RUNNING)

    async def test_uploaded_image_and_look_sheet_keep_generation_lineage(self) -> None:
        png = b"\x89PNG\r\n\x1a\nmock-image"
        second_png = b"\x89PNG\r\n\x1a\nsecond-image"
        generated_png = b"\x89PNG\r\n\x1a\ngenerated-image"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("1" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "1" * 32)
            provider = RecordingProvider(media_type="image/png", content=generated_png)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                image_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            card = prepared.reference_library.characters[0]
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            missing_category = await api.handle(
                "POST",
                "/structured-director/assets/images?"
                + urlencode({"expected_revision": prepared.revision}),
                png,
                media_type="image/png",
            )
            self.assertEqual(missing_category.status, 400)
            upload_response = await api.handle(
                "POST",
                "/structured-director/assets/images?"
                + urlencode(
                    {
                        "expected_revision": prepared.revision,
                        "filename": "Comi 正面参考.png",
                        "category": "character_reference",
                    }
                ),
                png,
                media_type="image/png",
            )
            self.assertEqual(upload_response.status, 200)
            self.assertEqual(
                upload_response.body["assets"][0]["image_category"],
                "character_reference",
            )
            uploaded = service.snapshot_required()
            input_asset = uploaded.assets[0]
            self.assertRegex(
                input_asset.relative_path,
                r"^assets/images/characters/Comi-正面参考-[0-9a-f]{10}\.png$",
            )
            self.assertEqual(
                uploaded.reference_library.characters[0].look_asset_ids,
                (),
                "导入 Asset 不能自动加入卡片",
            )
            conflicting_category = await api.handle(
                "POST",
                "/structured-director/assets/images?"
                + urlencode(
                    {
                        "expected_revision": uploaded.revision,
                        "category": "location_image",
                    }
                ),
                png,
                media_type="image/png",
            )
            self.assertEqual(conflicting_category.status, 400)
            self.assertIn(
                "已经归入角色参考图",
                conflicting_category.body["error"]["message"],
            )
            second_upload = await api.handle(
                "POST",
                "/structured-director/assets/images?"
                + urlencode(
                    {
                        "expected_revision": uploaded.revision,
                        "category": "character_reference",
                    }
                ),
                second_png,
                media_type="image/png",
            )
            self.assertEqual(second_upload.status, 200)
            with_two_assets = service.snapshot_required()
            second_asset = with_two_assets.assets[1]
            look = CharacterLook("6" * 32, "日常", "蓝色外套，牛仔裤", "全片")
            with_look = await service.update_character(
                replace(card, looks=(look,)),
                expected_revision=with_two_assets.revision,
                created_look_ids=frozenset({look.id}),
            )
            attach_response = await api.handle(
                "POST",
                f"/structured-director/characters/{card.id}/looks/{look.id}/select-asset",
                json.dumps(
                    {"expected_revision": with_look.revision, "asset_id": second_asset.id}
                ).encode(),
            )
            self.assertEqual(attach_response.status, 200)
            attached_upload = service.snapshot_required()
            self.assertEqual(
                attached_upload.reference_library.characters[0].looks[0].selected_asset_id,
                second_asset.id,
            )
            submitted = await service.generate_look_sheet(
                look_id=look.id,
                identity_asset_ids=(input_asset.id,),
                expected_revision=attached_upload.revision,
            )
            generation = submitted.generations[0]

            self.assertEqual(generation.input_asset_ids, (input_asset.id,))
            self.assertEqual(len(provider.requests[0].slot("reference_image")), 1)
            running = await service._generation_observer.refresh_generation(generation.id)
            completed = await service._generation_observer.refresh_generation(generation.id)

            self.assertIs(
                running.generations[0].phase,
                ReferenceGenerationPhase.RUNNING,
            )
            candidate = completed.generations[0]
            self.assertIs(candidate.phase, ReferenceGenerationPhase.SUCCEEDED)
            generated_asset = next(
                item for item in completed.assets if item.id == candidate.output_asset_id
            )
            self.assertRegex(
                generated_asset.relative_path,
                r"^assets/images/characters/角色-小满-日常-设定图候选-[0-9a-f]{10}\.png$",
            )
            self.assertEqual(
                completed.reference_library.characters[0].looks[0].selected_asset_id,
                second_asset.id,
                "候选不能自动成为造型图",
            )
            attached = await service.select_look_sheet(
                card_id=card.id,
                look_id=look.id,
                generation_id=candidate.id,
                expected_revision=completed.revision,
            )
            self.assertEqual(
                attached.reference_library.characters[0].looks[0].selected_asset_id,
                candidate.output_asset_id,
            )
            restored = StructuredDirectorStore(project, "1" * 32).read()
            self.assertEqual(restored, attached)
            descriptor, content = service.read_asset(candidate.output_asset_id or "")
            self.assertEqual(descriptor.sha256, hashlib.sha256(generated_png).hexdigest())
            self.assertEqual(content, generated_png)

    async def test_asset_delete_requires_zero_project_and_generation_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("0" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "0" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            card = prepared.reference_library.characters[0]
            unreferenced = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nunreferenced",
                category=ImageAssetCategory.CHARACTER_REFERENCE,
                expected_revision=prepared.revision,
            )
            unreferenced_id = unreferenced.assets[0].id
            with_second = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nreferenced",
                category=ImageAssetCategory.CHARACTER_REFERENCE,
                expected_revision=unreferenced.revision,
            )
            referenced_id = with_second.assets[1].id
            attached = await _with_look_image(service, with_second, card, referenced_id)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            visible = await api.handle("GET", "/structured-director")
            actions = {item["id"]: item["allowed_actions"] for item in visible.body["assets"]}
            reasons = {item["id"]: item["usage_reasons"] for item in visible.body["assets"]}
            self.assertTrue(all(item["display_name"] for item in visible.body["assets"]))
            self.assertEqual(actions[unreferenced_id], ["delete"])
            self.assertEqual(actions[referenced_id], [])
            self.assertEqual(reasons[unreferenced_id], [])
            self.assertEqual(
                reasons[referenced_id],
                [{"code": "character_reference_image", "label": "角色造型图"}],
            )
            self.assertFalse(
                next(item for item in visible.body["assets"] if item["id"] == unreferenced_id)[
                    "is_in_use"
                ]
            )

            unknown_field = await api.handle(
                "DELETE",
                f"/structured-director/assets/{unreferenced_id}",
                json.dumps({"expected_revision": attached.revision, "unexpected": True}).encode(),
            )
            self.assertEqual(unknown_field.status, 400)
            blocked = await api.handle(
                "DELETE",
                f"/structured-director/assets/{referenced_id}",
                json.dumps({"expected_revision": attached.revision}).encode(),
            )
            self.assertEqual(blocked.status, 400)
            self.assertIn("正在被", blocked.body["error"]["message"])
            self.assertIn("使用原因：角色造型图", blocked.body["error"]["message"])

            deleted = await api.handle(
                "DELETE",
                f"/structured-director/assets/{unreferenced_id}",
                json.dumps({"expected_revision": attached.revision}).encode(),
            )
            self.assertEqual(deleted.status, 200)
            self.assertNotIn(unreferenced_id, {item["id"] for item in deleted.body["assets"]})
            with self.assertRaisesRegex(FileNotFoundError, "不存在"):
                service.read_asset(unreferenced_id)

    async def test_asset_usage_reasons_track_formal_bindings_not_generation_lineage(self) -> None:
        """正式项目字段产生明确原因；Generation 输出关系只保留血缘。"""

        with tempfile.TemporaryDirectory() as directory:
            store, service, document, _ = await _visual_project(directory)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            registry = DirectorCommandRegistry(store)
            imported: dict[str, str] = {}
            for name in ("keyframe-selected", "keyframe-aux", "location-view", "video-image"):
                document = await service.import_image_asset(
                    media_type="image/png",
                    content=b"\x89PNG\r\n\x1a\n" + name.encode(),
                    category=ImageAssetCategory.KEYFRAME,
                    expected_revision=document.revision,
                )
                imported[name] = document.assets[-1].id
            document = await service.import_media_asset(
                media_type="audio/wav",
                content=wav_bytes(duration_seconds=3.0),
                expected_revision=document.revision,
            )
            imported["video-audio"] = document.assets[-1].id
            document = await service.import_media_asset(
                media_type="video/mp4",
                content=_mp4_bytes(duration_seconds=3.0),
                expected_revision=document.revision,
            )
            imported["video-reference"] = document.assets[-1].id
            card = document.reference_library.characters[0]
            document = await _with_look_image(
                service, document, card, imported["keyframe-selected"]
            )
            document = install_location(store, view_asset_id=imported["location-view"])
            segment_id = document.keyframe_plan.segments[0].segment_id
            document = registry.execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "asset-usage",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": segment_id,
                                "start_enabled": True,
                                "end_enabled": False,
                            }
                        ]
                    },
                )
            ).document
            keyframe_id = next(
                item.start_keyframe_id
                for item in document.keyframe_plan.segments
                if item.segment_id == segment_id
            )
            document = store.select_keyframe_asset(
                keyframe_id=keyframe_id,
                asset_id=imported["keyframe-selected"],
                expected_revision=document.revision,
            )
            # 测试 fixture 直接构造辅助参考与 Ref2VA 输入；不写真实项目文件。
            document = replace(
                document,
                revision=document.revision + 1,
                keyframe_plan=replace(
                    document.keyframe_plan,
                    segments=tuple(
                        replace(item, reference_asset_ids=(imported["keyframe-aux"],))
                        if item.segment_id == segment_id
                        else item
                        for item in document.keyframe_plan.segments
                    ),
                ),
                video_plan=replace(
                    document.video_plan,
                    segments=tuple(
                        replace_video(
                            item,
                            additional_image_references=(
                                SegmentVideoImageReference(imported["video-image"], "附加画面"),
                            ),
                            audio_references=(
                                SegmentVideoAudioReference(imported["video-audio"], "音色参考"),
                            ),
                            video_references=(
                                SegmentVideoVideoReference(imported["video-reference"], "参考运镜"),
                            ),
                        )
                        if item.segment_id == segment_id
                        else item
                        for item in document.video_plan.segments
                    ),
                ),
            )
            store._atomic_write(document)

            snapshot = await api.handle("GET", "/structured-director")
            assets = {item["id"]: item for item in snapshot.body["assets"]}
            # 视图已选图同时是该视图的成功候选（候选选择只接受候选）。
            self.assertEqual(
                assets[imported["location-view"]]["usage_reasons"],
                [
                    {"code": "location_image", "label": "地点图片"},
                    {"code": "visible_candidate", "label": "可见生成候选"},
                ],
            )
            self.assertTrue(assets[imported["location-view"]]["is_in_use"])
            self.assertEqual(assets[imported["location-view"]]["allowed_actions"], [])
            self.assertEqual(
                assets[imported["video-image"]]["usage_reasons"],
                [{"code": "segment_video_input_image", "label": "Ref2VA 视频附加图片"}],
            )
            self.assertEqual(
                assets[imported["video-audio"]]["usage_reasons"],
                [{"code": "segment_video_input_audio", "label": "Ref2VA 视频参考音频"}],
            )
            self.assertEqual(
                assets[imported["video-reference"]]["usage_reasons"],
                [{"code": "segment_video_input_video", "label": "Ref2VA 视频参考视频"}],
            )
            selected_reasons = assets[imported["keyframe-selected"]]["usage_reasons"]
            self.assertEqual(
                {item["code"] for item in selected_reasons},
                {"character_reference_image", "keyframe_selected_asset"},
            )
            self.assertEqual(
                assets[imported["keyframe-aux"]]["usage_reasons"],
                [{"code": "keyframe_reference_image", "label": "Keyframe 辅助参考图"}],
            )
            for name in (
                "keyframe-selected",
                "keyframe-aux",
                "location-view",
                "video-image",
                "video-reference",
            ):
                with self.assertRaisesRegex(ValueError, "正在被"):
                    store.delete_asset(imported[name], expected_revision=document.revision)

    async def test_video_frame_category_is_core_owned_and_not_importable(self) -> None:
        """抽帧图由视频尾帧抽取产生；用户不能把它当作导入分类。"""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("5" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "5" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            with self.assertRaisesRegex(ValueError, "抽帧图不能由用户导入"):
                await service.import_image_asset(
                    media_type="image/png",
                    content=b"\x89PNG\r\n\x1a\nframe-import",
                    category=ImageAssetCategory.VIDEO_FRAME,
                    expected_revision=prepared.revision,
                )
            self.assertEqual(prepared.assets, ())
            imported = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nkeyframe-import",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=prepared.revision,
            )
            self.assertIs(imported.assets[-1].image_category, ImageAssetCategory.KEYFRAME)
            with self.assertRaisesRegex(ValueError, "已经归入Keyframe 图"):
                await service.import_image_asset(
                    media_type="image/png",
                    content=b"\x89PNG\r\n\x1a\nkeyframe-import",
                    category=ImageAssetCategory.CHARACTER_REFERENCE,
                    expected_revision=imported.revision,
                )

    async def test_reimporting_identical_bytes_is_noop(self) -> None:
        """重复导入相同字节（同分类）不写入、不推进 revision，也不报 revision 冲突。"""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("6" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "6" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            imported = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nduplicate-import",
                category=ImageAssetCategory.CHARACTER_REFERENCE,
                expected_revision=prepared.revision,
            )
            again = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nduplicate-import",
                category=ImageAssetCategory.CHARACTER_REFERENCE,
                expected_revision=imported.revision,
            )
            self.assertEqual(again.revision, imported.revision)
            self.assertEqual(again.assets, imported.assets)
            media = await service.import_media_asset(
                media_type="audio/wav",
                content=wav_bytes(duration_seconds=1.0),
                expected_revision=again.revision,
            )
            media_again = await service.import_media_asset(
                media_type="audio/wav",
                content=wav_bytes(duration_seconds=1.0),
                expected_revision=media.revision,
            )
            self.assertEqual(media_again.revision, media.revision)
            self.assertEqual(store.read().revision, media.revision)

    async def test_asset_delete_detaches_visible_derived_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("7" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "7" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            first = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nhidden-source",
                category=ImageAssetCategory.LOCATION_IMAGE,
                expected_revision=prepared.revision,
            )
            second = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nhidden-result",
                category=ImageAssetCategory.LOCATION_IMAGE,
                expected_revision=first.revision,
            )
            source_asset_id, result_asset_id = (item.id for item in second.assets)
            linked = replace(
                second,
                reference_library=replace(
                    second.reference_library,
                    characters=(
                        replace(
                            second.reference_library.characters[0],
                            looks=(
                                CharacterLook(
                                    "7" * 32, "保留派生结果", "外观", "全片", result_asset_id
                                ),
                            ),
                        ),
                    ),
                ),
            )
            source_generation = ReferenceGeneration(
                id="1" * 32,
                kind=ReferenceGenerationKind.LOCATION_IMAGE,
                operation=GenerationOperation.GENERATE,
                target_id="3" * 32,
                phase=ReferenceGenerationPhase.SUCCEEDED,
                progress=1.0,
                message="完成",
                prompt_text="生成废弃的地点主图候选。",
                input_asset_ids=(),
                sample_text=None,
                seed=None,
                plugin_id="test.image",
                plugin_version=1,
                external_id="source",
                output_asset_id=source_asset_id,
                error_code=None,
                cancellation_requested=False,
                retry_of=None,
                dismissed=True,
            )
            result_generation = replace(
                source_generation,
                id="2" * 32,
                operation=GenerationOperation.EDIT,
                input_asset_ids=(source_asset_id,),
                external_id="result",
                output_asset_id=result_asset_id,
                retry_of=source_generation.id,
                dismissed=False,
            )
            request_revision = second.revision + 1
            request = ApplicationRequest(
                request_id="a" * 64,
                caller_id="external-agent",
                project_id=second.project_id,
                idempotency_key="generate-discarded-assets",
                request_digest="b" * 64,
                operation="keyframe.generate",
                expected_revision=second.revision,
                authorization_scope="{}",
                phase="committed",
                result_revision=request_revision,
                receipt_json=canonical(
                    {
                        "receipt": {
                            "command_id": "c" * 32,
                            "status": "succeeded",
                            "old_revision": second.revision,
                            "new_revision": request_revision,
                            "changed_ids": [source_generation.id, result_generation.id],
                            "invalidated": [],
                            "preserved": [],
                            "assumptions": [],
                            "next_allowed_actions": [],
                            "warnings": [],
                        },
                        "data": {
                            "phase": "committed",
                            "generation_ids": [source_generation.id, result_generation.id],
                        },
                        "repair_receipt": None,
                    }
                ),
                generation_ids=(source_generation.id, result_generation.id),
            )
            store._atomic_write(
                replace(
                    linked,
                    revision=request_revision,
                    generations=(source_generation, result_generation),
                    application_requests=(request,),
                )
            )
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            visible = await api.handle("GET", "/structured-director")
            actions = {item["id"]: item["allowed_actions"] for item in visible.body["assets"]}
            self.assertEqual(actions[source_asset_id], ["delete"])
            self.assertEqual(actions[result_asset_id], [])
            deleted = await api.handle(
                "DELETE",
                f"/structured-director/assets/{source_asset_id}",
                json.dumps({"expected_revision": visible.body["revision"]}).encode(),
            )
            self.assertEqual(deleted.status, 200)
            self.assertEqual(
                {item["id"] for item in deleted.body["assets"]},
                {result_asset_id},
            )
            self.assertEqual(deleted.body["generations"], [])
            restored = store.read()
            self.assertEqual(
                restored.reference_library.characters[0].looks[0].selected_asset_id,
                result_asset_id,
            )
            self.assertEqual(len(restored.application_requests), 1)
            self.assertEqual(restored.application_requests[0].generation_ids, ())
            self.assertEqual(
                json.loads(restored.application_requests[0].receipt_json or "null")["data"][
                    "generation_ids"
                ],
                [],
            )
            with self.assertRaisesRegex(FileNotFoundError, "不存在"):
                service.read_asset(source_asset_id)
            _, result_content = service.read_asset(result_asset_id)
            self.assertEqual(result_content, b"\x89PNG\r\n\x1a\nhidden-result")

    async def test_asset_batch_delete_is_atomic_and_uses_one_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("6" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "6" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            first = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nbatch-one",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=prepared.revision,
            )
            second = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nbatch-two",
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=first.revision,
            )
            asset_ids = [item.id for item in second.assets]
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            deleted = await api.handle(
                "DELETE",
                "/structured-director/assets/batch-delete",
                json.dumps({"expected_revision": second.revision, "asset_ids": asset_ids}).encode(),
            )
            self.assertEqual(deleted.status, 200)
            self.assertEqual(deleted.body["revision"], second.revision + 1)
            self.assertEqual(deleted.body["assets"], [])
            for asset_id in asset_ids:
                with self.assertRaisesRegex(FileNotFoundError, "不存在"):
                    service.read_asset(asset_id)

            duplicate = await api.handle(
                "DELETE",
                "/structured-director/assets/batch-delete",
                json.dumps(
                    {
                        "expected_revision": deleted.body["revision"],
                        "asset_ids": ["a" * 32, "a" * 32],
                    }
                ).encode(),
            )
            self.assertEqual(duplicate.status, 400)

    async def test_dismissed_unused_candidate_can_be_purged_with_its_lineage(self) -> None:
        wav = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("8" * 32)
            project.mkdir()
            provider = RecordingProvider(media_type="audio/wav", content=wav)
            store = StructuredDirectorStore(project, "8" * 32)
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
                voice_description="年轻、温和",
                sample_text="测试声音。",
                seed=42,
                expected_revision=prepared.revision,
            )
            generation_id = submitted.generations[0].id
            await service._generation_observer.refresh_generation(generation_id)
            completed = await service._generation_observer.refresh_generation(generation_id)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            visible = await api.handle("GET", "/structured-director")
            self.assertEqual(
                visible.body["generations"][0]["allowed_actions"],
                ["attach_output", "dismiss_history"],
            )
            self.assertEqual(
                visible.body["assets"][0]["allowed_actions"],
                ["audio_trim", "audio_effect"],
            )
            dismissed = await api.handle(
                "POST",
                f"/structured-director/generations/{generation_id}/dismiss",
                json.dumps({"expected_revision": completed.revision}).encode(),
            )

            self.assertEqual(dismissed.status, 200)
            self.assertTrue(dismissed.body["generations"][0]["dismissed"])
            self.assertEqual(dismissed.body["generations"][0]["allowed_actions"], [])
            self.assertEqual(
                dismissed.body["assets"][0]["allowed_actions"],
                ["audio_trim", "audio_effect", "delete"],
            )
            restored = service.snapshot_required()
            generation = restored.generations[0]
            self.assertTrue(generation.dismissed)
            self.assertIsNotNone(generation.output_asset_id)
            output_asset_id = generation.output_asset_id or ""
            _, restored_wav = service.read_asset(output_asset_id)
            self.assertEqual(restored_wav, wav)
            with self.assertRaisesRegex(ValueError, "已删除"):
                await service.attach_generation_output(
                    kind="voice",
                    card_id=card.id,
                    generation_id=generation_id,
                    note="",
                    expected_revision=restored.revision,
                )
            deleted = await api.handle(
                "DELETE",
                f"/structured-director/assets/{output_asset_id}",
                json.dumps({"expected_revision": restored.revision}).encode(),
            )
            self.assertEqual(deleted.status, 200)
            self.assertEqual(deleted.body["assets"], [])
            self.assertEqual(deleted.body["generations"], [])
            with self.assertRaisesRegex(FileNotFoundError, "不存在"):
                service.read_asset(output_asset_id)

    async def test_selected_reference_cannot_be_dismissed_as_candidate(self) -> None:
        wav = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("9" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "9" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=RecordingProvider(media_type="audio/wav", content=wav),
            )
            create_project(store)
            prepared = await service.prepare_references()
            card = prepared.reference_library.characters[0]
            submitted = await service._media.design_voice(
                card_id=card.id,
                voice_description="年轻、温和",
                sample_text="测试声音。",
                seed=42,
                expected_revision=prepared.revision,
            )
            generation_id = submitted.generations[0].id
            await service._generation_observer.refresh_generation(generation_id)
            completed = await service._generation_observer.refresh_generation(generation_id)
            selected = await service.attach_generation_output(
                kind="voice",
                card_id=card.id,
                generation_id=generation_id,
                note="",
                expected_revision=completed.revision,
            )

            with self.assertRaisesRegex(ValueError, "先解除引用"):
                await service.dismiss_generation(
                    generation_id,
                    expected_revision=selected.revision,
                )

    async def test_invalid_submit_response_identifies_protocol_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("6" * 32)
            project.mkdir()
            provider = FailingSubmitProvider(
                ModelProviderError(
                    "invalid_response",
                    "外部响应缺少字段 ['design_id']。",
                )
            )
            store = StructuredDirectorStore(project, "6" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()

            result = await service._media.design_voice(
                card_id=prepared.reference_library.characters[0].id,
                voice_description="年轻、温和",
                sample_text="测试声音。",
                seed=42,
                expected_revision=prepared.revision,
            )

            generation = result.generations[0]
            self.assertIs(
                generation.phase,
                ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
            )
            self.assertEqual(generation.error_code, "invalid_response")
            self.assertIn("提交响应校验", generation.message)
            self.assertIn("不会自动重试", generation.message)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            visible = await api.handle("GET", "/structured-director")
            self.assertEqual(
                visible.body["generations"][0]["allowed_actions"],
                ["retry", "dismiss_history"],
            )
            dismissed = await api.handle(
                "POST",
                f"/structured-director/generations/{generation.id}/dismiss",
                json.dumps({"expected_revision": result.revision}).encode(),
            )
            self.assertEqual(dismissed.status, 200)
            self.assertTrue(dismissed.body["generations"][0]["dismissed"])

    async def test_generation_retry_creates_new_attempt_with_exact_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("4" * 32)
            project.mkdir()
            provider = FailingSubmitProvider(ModelProviderError("external_error", "服务拒绝请求。"))
            store = StructuredDirectorStore(project, "4" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            failed = await service._media.design_voice(
                card_id=prepared.reference_library.characters[0].id,
                voice_description="年轻、温和",
                sample_text="测试声音。",
                seed=42,
                expected_revision=prepared.revision,
            )
            original = failed.generations[0]

            execution = await service.execute_generation_command(
                DirectorCommand(
                    "generation.retry",
                    failed.revision,
                    "retry-original-request",
                    {"generation_id": original.id},
                )
            )

            self.assertEqual(len(execution.document.generations), 2)
            retried = execution.document.generations[-1]
            self.assertNotEqual(retried.id, original.id)
            self.assertEqual(retried.retry_of, original.id)
            self.assertEqual(retried.prompt_text, original.prompt_text)
            self.assertEqual(retried.seed, original.seed)
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(execution.receipt.changed_ids, (original.id, retried.id))

            replay = await service.execute_generation_command(
                DirectorCommand(
                    "generation.retry",
                    execution.document.revision,
                    "retry-original-request",
                    {"generation_id": original.id},
                )
            )
            self.assertEqual(replay.receipt.status, "noop")
            self.assertEqual(replay.receipt.changed_ids, ())
            self.assertEqual(len(replay.document.generations), 2)
            self.assertEqual(len(provider.requests), 2)

    async def test_generation_wait_observes_only_requested_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("5" * 32)
            project.mkdir()
            provider = RecordingProvider(media_type="audio/wav", content=wav_bytes())
            store = StructuredDirectorStore(project, "5" * 32)
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
            generation_id = submitted.generations[0].id

            with patch.dict(os.environ, {"STORYRAIL_GENERATION_WAIT_MAX_SECONDS": "0"}):
                execution = await service.execute_generation_command(
                    DirectorCommand(
                        "generation.wait",
                        submitted.revision,
                        "wait-for-one",
                        {"generation_ids": [generation_id]},
                    )
                )

            self.assertEqual(
                execution.data,
                {
                    "generations": [
                        {
                            "generation_id": generation_id,
                            "phase": "running",
                            "progress": 0.5,
                            "message": "生成中",
                            "error_code": None,
                            "cancellation_requested": False,
                            "dismissed": False,
                            "output_asset_id": None,
                            "created_at": execution.document.generations[0].created_at,
                            "updated_at": execution.document.generations[0].updated_at,
                            "retry_of": None,
                            "recovery": {
                                "failure_origin": None,
                                "retry_policy": "wait_same_generation",
                                "automatic_retry_allowed": False,
                            },
                        }
                    ],
                    "wait_again": True,
                },
            )

    async def test_generation_command_rejects_unknown_arguments_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("1" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "1" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            created = create_project(store)

            with self.assertRaisesRegex(ValueError, "缺少字段|不接受字段|未声明字段"):
                await service.execute_generation_command(
                    DirectorCommand(
                        "generation.dismiss",
                        created.revision,
                        "strict-generation-arguments",
                        {"generation_id": "a" * 32, "delete": True},
                    )
                )

            self.assertEqual(store.read(), created)

    async def test_refresh_active_generations_does_not_block_on_earlier_running_job(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("6" * 32)
            project.mkdir()
            image_provider = RecordingProvider(media_type="image/png", content=b"image")
            image_provider.observations = [GenerationPhase.RUNNING]
            voice_provider = RecordingProvider(
                media_type="audio/wav",
                content=wav_bytes(),
                duration_seconds=1.0,
            )
            voice_provider.observations = [GenerationPhase.SUCCEEDED]
            store = StructuredDirectorStore(project, "6" * 32)
            service = StructuredDirectorService(
                store,
                NarrationReferenceProposer(),
                image_provider=image_provider,
                voice_provider=voice_provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            narrator = prepared.reference_library.narrator
            assert narrator is not None
            prepared = await _with_look(service, prepared, prepared.reference_library.characters[0])
            image_submitted = await service.generate_look_sheet(
                look_id=prepared.reference_library.characters[0].looks[0].id,
                identity_asset_ids=(),
                expected_revision=prepared.revision,
            )
            voice_submitted = await service._media.design_voice(
                card_id=narrator.id,
                voice_description=narrator.zh.voice_description,
                sample_text="末班车即将到站。",
                seed=42,
                narrator_language=NarrationLanguage.ZH,
                expected_revision=image_submitted.revision,
            )
            image_generation_id = voice_submitted.generations[0].id
            voice_generation_id = voice_submitted.generations[1].id
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            rejected = await api.handle(
                "POST",
                "/structured-director/generations/refresh",
                json.dumps({"generation_ids": [voice_generation_id]}).encode(),
            )
            self.assertEqual(rejected.status, 400)
            self.assertTrue(
                all(
                    generation.phase is ReferenceGenerationPhase.QUEUED
                    for generation in store.read().generations
                )
            )

            response = await api.handle(
                "POST",
                "/structured-director/generations/refresh",
                b"{}",
            )

            self.assertEqual(response.status, 200)
            refreshed = store.read()
            generations = {item.id: item for item in refreshed.generations}
            self.assertIs(
                generations[image_generation_id].phase,
                ReferenceGenerationPhase.RUNNING,
            )
            self.assertIs(
                generations[voice_generation_id].phase,
                ReferenceGenerationPhase.SUCCEEDED,
            )
            self.assertIsNotNone(generations[voice_generation_id].output_asset_id)
            response_generations = {item["id"]: item for item in response.body["generations"]}
            self.assertEqual(response_generations[image_generation_id]["phase"], "running")
            self.assertEqual(response_generations[voice_generation_id]["phase"], "succeeded")

    async def test_refresh_active_generations_isolates_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("7" * 32)
            project.mkdir()
            image_provider = InvalidObserveProvider(
                media_type="image/png",
                content=b"image",
            )
            voice_provider = RecordingProvider(
                media_type="audio/wav",
                content=wav_bytes(),
                duration_seconds=1.0,
            )
            voice_provider.observations = [GenerationPhase.SUCCEEDED]
            store = StructuredDirectorStore(project, "7" * 32)
            service = StructuredDirectorService(
                store,
                NarrationReferenceProposer(),
                image_provider=image_provider,
                voice_provider=voice_provider,
            )
            create_project(store)
            prepared = await service.prepare_references()
            narrator = prepared.reference_library.narrator
            assert narrator is not None
            prepared = await _with_look(service, prepared, prepared.reference_library.characters[0])
            image_submitted = await service.generate_look_sheet(
                look_id=prepared.reference_library.characters[0].looks[0].id,
                identity_asset_ids=(),
                expected_revision=prepared.revision,
            )
            submitted = await service._media.design_voice(
                card_id=narrator.id,
                voice_description=narrator.zh.voice_description,
                sample_text="末班车即将到站。",
                seed=42,
                narrator_language=NarrationLanguage.ZH,
                expected_revision=image_submitted.revision,
            )
            image_generation_id = submitted.generations[0].id
            voice_generation_id = submitted.generations[1].id
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            response = await api.handle(
                "POST",
                "/structured-director/generations/refresh",
                b"{}",
            )

            self.assertEqual(response.status, 200)
            generations = {item.id: item for item in store.read().generations}
            self.assertIs(
                generations[image_generation_id].phase,
                ReferenceGenerationPhase.QUEUED,
            )
            self.assertIs(
                generations[voice_generation_id].phase,
                ReferenceGenerationPhase.SUCCEEDED,
            )
            self.assertIsNotNone(generations[voice_generation_id].output_asset_id)

    async def test_refresh_persists_provider_unreachable_without_losing_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("8" * 32)
            project.mkdir()
            provider = UnreachableObserveProvider(media_type="audio/wav", content=wav_bytes())
            store = StructuredDirectorStore(project, "8" * 32)
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

            refreshed = await service._generation_observer.refresh_generation(
                submitted.generations[0].id
            )

            generation = refreshed.generations[0]
            self.assertIs(generation.phase, ReferenceGenerationPhase.QUEUED)
            self.assertEqual(generation.external_id, "external-1")
            self.assertEqual(generation.error_code, "provider_unreachable")
            self.assertIn("任务句柄和最后进度已经保留", generation.message)
            self.assertEqual(store.read(), refreshed)

    async def test_explicit_provider_rejection_is_failed_not_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("7" * 32)
            project.mkdir()
            provider = FailingSubmitProvider(ModelProviderError("external_error", "服务拒绝请求。"))
            store = StructuredDirectorStore(project, "7" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                voice_provider=provider,
            )
            create_project(store)
            prepared = await service.prepare_references()

            result = await service._media.design_voice(
                card_id=prepared.reference_library.characters[0].id,
                voice_description="年轻、温和",
                sample_text="测试声音。",
                seed=42,
                expected_revision=prepared.revision,
            )

            generation = result.generations[0]
            self.assertIs(generation.phase, ReferenceGenerationPhase.FAILED)
            self.assertEqual(generation.error_code, "submission_rejected")
            self.assertIn("服务明确拒绝", generation.message)

    async def test_cancelled_generation_is_persisted(self) -> None:
        wav = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("a" * 32)
            project.mkdir()
            provider = RecordingProvider(media_type="audio/wav", content=wav)
            store = StructuredDirectorStore(project, "a" * 32)
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

            cancelled = await service._generation_observer.cancel_generation(
                submitted.generations[0].id
            )

            self.assertIs(
                cancelled.generations[0].phase,
                ReferenceGenerationPhase.CANCELLED,
            )
            self.assertEqual(store.read(), cancelled)


async def _with_look(service, document, card):
    look = CharacterLook("6" * 32, "日常", "蓝色外套", "全片")
    return await service.update_character(
        replace(card, looks=(look,)),
        expected_revision=document.revision,
        created_look_ids=frozenset({look.id}),
    )


async def _with_look_image(service, document, card, asset_id):
    document = await _with_look(service, document, card)
    return await service.select_look_asset(
        card_id=card.id,
        look_id="6" * 32,
        asset_id=asset_id,
        expected_revision=document.revision,
    )
