"""impact_preview characterization tests（P2-A2）。

在重构把 impact_preview 下沉进 reads/ 包之前，锁定它对 script / narration /
keyframe / video / generation / final 各域的逐字段预览输出：
真实 document 快照 + 正式命令 → 影响摘要 dict。重构只允许移动与委托，
这些断言逐字校验行为保持。
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from structured_director_fixtures import add_image_asset, install_location
from test_director_commands import _visual_project
from video_recipes import video_wire_dict

from core.director_commands import parse_director_command
from core.structured_director import Asset
from core.structured_director.models import (
    NarrationCue,
    NarrationTrack,
    Scene,
)
from core.structured_director.reads.impact import preview_command_impact
from core.structured_director.script_index import shot_segments


class ImpactPreviewCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def _document_with_cue(self, directory: str):
        store, service, document, _route = await _visual_project(directory)
        assert document.director_script is not None
        scene = document.director_script.scenes[0]
        shot = scene.shots[0]
        segment = shot_segments(scene, shot.id)[0]
        binding = document.keyframe_plan.segments[0]
        video = document.video_plan.segments[0]
        # 旁白只属于 Narration Scene：另附一个尚未规划 Shot 的旁白场景，视觉 Scene 保持 Drama。
        cue = NarrationCue(
            "d" * 32,
            NarrationTrack("夜色渐深，甲缓慢抬头望向窗外。", 1),
            NarrationTrack("Night deepens as A slowly looks out the window.", 1),
        )
        narration_scene = Scene(
            id="e" * 32,
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
        return store, service, document, scene, segment, binding, video, cue

    def _preview(self, document, name: str, arguments: dict, key: str) -> dict:
        command = parse_director_command(
            {
                "name": name,
                "expected_revision": document.revision,
                "idempotency_key": key,
                "arguments": arguments,
            }
        )
        return preview_command_impact(document, command)

    async def test_script_operations_preview_locks_changed_and_noop_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                scene,
                segment,
                _binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            scope = {"scene_ids": [scene.id]}

            changed = self._preview(
                document,
                "script.apply_operations",
                {
                    "scope": scope,
                    "operations": [
                        {
                            "op": "update_segment_fields",
                            "segment_id": segment.id,
                            "fields": {"action": "甲缓慢抬头。"},
                        }
                    ],
                },
                "char-script-changed",
            )
            self.assertEqual(
                changed,
                {
                    "revision": document.revision,
                    "command_name": "script.apply_operations",
                    "will_write": True,
                    "changed_ids": sorted([segment.id, scene.id]),
                    "invalidated": [],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": False,
                },
            )

            noop = self._preview(
                document,
                "script.apply_operations",
                {
                    "scope": scope,
                    "operations": [
                        {
                            "op": "update_segment_fields",
                            "segment_id": segment.id,
                            "fields": {"action": segment.action},
                        }
                    ],
                },
                "char-script-noop",
            )
            self.assertEqual(
                noop,
                {
                    "revision": document.revision,
                    "command_name": "script.apply_operations",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": [],
                    "high_impact": False,
                },
            )

    async def test_repair_patch_preview_locks_scope_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                scene,
                _segment,
                _binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            result = self._preview(
                document,
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
                "char-repair-noop",
            )
            self.assertEqual(
                result,
                {
                    "revision": document.revision,
                    "command_name": "project.apply_repair_patch",
                    "will_write": True,
                    "changed_ids": [scene.id],
                    "invalidated": [],
                    "preserved": [],
                    "high_impact": False,
                },
            )

    async def test_narration_previews_lock_update_and_clear_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                _scene,
                _segment,
                _binding,
                _video,
                cue,
            ) = await self._document_with_cue(directory)
            scene = document.director_script.scenes[-1]
            scope = {"scene_ids": [scene.id]}

            updated = self._preview(
                document,
                "narration.update_cue",
                {
                    "scope": scope,
                    "cue_id": cue.id,
                    "fields": {"zh": {"text": "天色渐暗，甲缓慢抬头。"}},
                },
                "char-cue-changed",
            )
            self.assertEqual(
                updated,
                {
                    "revision": document.revision,
                    "command_name": "narration.update_cue",
                    "will_write": True,
                    "changed_ids": sorted([scene.id, cue.id]),
                    "invalidated": [],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": False,
                },
            )

            noop = self._preview(
                document,
                "narration.update_cue",
                {"scope": scope, "cue_id": cue.id, "fields": {"zh": {"text": cue.zh.text}}},
                "char-cue-noop",
            )
            self.assertEqual(
                noop,
                {
                    "revision": document.revision,
                    "command_name": "narration.update_cue",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": ["narration_selection"],
                    "high_impact": False,
                },
            )

            clear = self._preview(
                document,
                "narration.clear_selection",
                {"scope": scope, "cue_id": cue.id, "language": "en"},
                "char-cue-clear",
            )
            self.assertEqual(
                clear,
                {
                    "revision": document.revision,
                    "command_name": "narration.clear_selection",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": [],
                    "high_impact": False,
                },
            )

    async def test_keyframe_operations_preview_locks_noop_and_changed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                _scene,
                _segment,
                binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            assert not binding.start_enabled and not binding.end_enabled

            noop = self._preview(
                document,
                "keyframe.apply_operations",
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
                "char-keyframe-noop",
            )
            self.assertEqual(
                noop,
                {
                    "revision": document.revision,
                    "command_name": "keyframe.apply_operations",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": [],
                    "high_impact": False,
                },
            )

            changed = self._preview(
                document,
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
                "char-keyframe-changed",
            )
            self.assertEqual(
                changed,
                {
                    "revision": document.revision,
                    "command_name": "keyframe.apply_operations",
                    "will_write": True,
                    "changed_ids": [binding.segment_id],
                    "invalidated": [],
                    "preserved": [],
                    "high_impact": False,
                },
            )

    async def test_video_previews_lock_prompt_mode_and_clear_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                scene,
                segment,
                _binding,
                video,
                _cue,
            ) = await self._document_with_cue(directory)
            self.assertEqual(video.prompt_text, "")
            scope = {"scene_ids": [scene.id]}

            prompt_changed = self._preview(
                document,
                "video.set_prompt",
                {"scope": scope, "segment_id": segment.id, "prompt_text": "保持动作。"},
                "char-video-prompt-changed",
            )
            self.assertEqual(
                prompt_changed,
                {
                    "revision": document.revision,
                    "command_name": "video.set_prompt",
                    "will_write": True,
                    "changed_ids": [segment.id],
                    "invalidated": [],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": False,
                },
            )

            prompt_noop = self._preview(
                document,
                "video.set_prompt",
                {"scope": scope, "segment_id": segment.id, "prompt_text": video.prompt_text},
                "char-video-prompt-noop",
            )
            self.assertEqual(
                prompt_noop,
                {
                    "revision": document.revision,
                    "command_name": "video.set_prompt",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": ["video_selection", "video_upscale_selection"],
                    "high_impact": False,
                },
            )

            inputs_changed = self._preview(
                document,
                "video.update_recipe_inputs",
                {
                    "scope": scope,
                    "segment_id": segment.id,
                    "prompt_text": "保持动作。",
                    "bindings": {},
                    "params": {},
                },
                "char-video-inputs-changed",
            )
            self.assertEqual(
                inputs_changed,
                {**prompt_changed, "command_name": "video.update_recipe_inputs"},
            )
            inputs_noop = self._preview(
                document,
                "video.update_recipe_inputs",
                {
                    "scope": scope,
                    "segment_id": segment.id,
                    "prompt_text": video.prompt_text,
                    **video.recipe_inputs.to_json(),
                },
                "char-video-inputs-noop",
            )
            self.assertEqual(
                inputs_noop,
                {**prompt_noop, "command_name": "video.update_recipe_inputs"},
            )

            mode_changed = self._preview(
                document,
                "video.set_recipe",
                video_wire_dict(
                    {"scope": scope, "segment_id": segment.id, "generation_mode": "fl2va"}
                ),
                "char-video-mode-changed",
            )
            self.assertEqual(
                mode_changed,
                {
                    "revision": document.revision,
                    "command_name": "video.set_recipe",
                    "will_write": True,
                    "changed_ids": [segment.id],
                    "invalidated": [],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": False,
                },
            )

            clear = self._preview(
                document,
                "video.clear_selection",
                {"scope": scope, "segment_id": segment.id},
                "char-video-clear",
            )
            self.assertEqual(
                clear,
                {
                    "revision": document.revision,
                    "command_name": "video.clear_selection",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": [],
                    "high_impact": False,
                },
            )

    async def test_generation_and_final_previews_lock_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                scene,
                _segment,
                _binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            generation_id = "f" * 32
            expected = {
                "generation.cancel": (
                    {"generation_id": generation_id},
                    {
                        "will_write": True,
                        "changed_ids": [generation_id],
                        "invalidated": [],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "generation.retry": (
                    {"generation_id": generation_id},
                    {
                        "will_write": True,
                        "changed_ids": [generation_id],
                        "invalidated": ["new_generation"],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "generation.dismiss": (
                    {"generation_id": generation_id},
                    {
                        "will_write": True,
                        "changed_ids": [generation_id],
                        "invalidated": [],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "generation.wait": (
                    {"generation_ids": [generation_id]},
                    {
                        "will_write": False,
                        "changed_ids": [generation_id],
                        "invalidated": [],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "animatic.generate_scene": (
                    {"scene_id": scene.id},
                    {
                        "will_write": True,
                        "changed_ids": [scene.id],
                        "invalidated": ["new_generation"],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "final.assemble_scene": (
                    {"scene_id": scene.id},
                    {
                        "will_write": True,
                        "changed_ids": [scene.id],
                        "invalidated": ["new_generation"],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "final.assemble": (
                    {},
                    {
                        "will_write": True,
                        "changed_ids": [],
                        "invalidated": ["new_generation"],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "final.select_candidate": (
                    {"generation_id": generation_id},
                    {
                        "will_write": True,
                        "changed_ids": [generation_id],
                        "invalidated": [],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "final.clear_selection": (
                    {},
                    {
                        "will_write": False,
                        "changed_ids": [],
                        "invalidated": [],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
                "final.approve": (
                    {"zh_asset_id": "e" * 32, "en_asset_id": "f" * 32},
                    {
                        "will_write": True,
                        "changed_ids": ["e" * 32, "f" * 32],
                        "invalidated": ["workflow_status"],
                        "preserved": [],
                        "high_impact": True,
                    },
                ),
                "final.reopen_production": (
                    {},
                    {
                        "will_write": False,
                        "changed_ids": [],
                        "invalidated": [],
                        "preserved": [],
                        "high_impact": False,
                    },
                ),
            }
            for index, (name, (arguments, fields)) in enumerate(expected.items()):
                result = self._preview(document, name, arguments, f"char-gen-final-{index}")
                self.assertEqual(result["revision"], document.revision)
                self.assertEqual(result["command_name"], name)
                self.assertEqual(
                    {
                        key: value
                        for key, value in result.items()
                        if key not in {"revision", "command_name"}
                    },
                    fields,
                )

    async def test_video_and_keyframe_previews_with_selections_lock_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                scene,
                segment,
                binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            assets = (
                Asset(
                    "e" * 32, "video/mp4", 24, "e" * 64, "assets/videos/segments/clip-e.mp4", 4.0
                ),
                Asset("c" * 32, "image/png", 12, "c" * 64, "assets/images/library/still-c.png"),
                Asset(
                    "b" * 32, "video/mp4", 24, "b" * 64, "assets/videos/segments/clip-b.mp4", 4.0
                ),
            )
            document = replace(
                document,
                revision=document.revision + 1,
                assets=(*document.assets, *assets),
                video_plan=replace(
                    document.video_plan,
                    segments=tuple(
                        replace(item, selected_asset_id="e" * 32, upscaled_asset_id="b" * 32)
                        if item.segment_id == segment.id
                        else item
                        for item in document.video_plan.segments
                    ),
                ),
                keyframe_plan=replace(
                    document.keyframe_plan,
                    keyframes=tuple(
                        replace(item, selected_asset_id="c" * 32)
                        for item in document.keyframe_plan.keyframes
                    ),
                ),
            )
            scope = {"scene_ids": [scene.id]}

            prompt = self._preview(
                document,
                "video.set_prompt",
                {"scope": scope, "segment_id": segment.id, "prompt_text": "保持动作。"},
                "char-seed-prompt",
            )
            self.assertEqual(
                prompt,
                {
                    "revision": document.revision,
                    "command_name": "video.set_prompt",
                    "will_write": True,
                    "changed_ids": [segment.id],
                    "invalidated": [
                        f"video_selection:{segment.id}",
                        f"video_upscale:{segment.id}",
                    ],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": True,
                },
            )

            clear = self._preview(
                document,
                "video.clear_selection",
                {"scope": scope, "segment_id": segment.id},
                "char-seed-clear",
            )
            self.assertEqual(
                clear,
                {
                    "revision": document.revision,
                    "command_name": "video.clear_selection",
                    "will_write": True,
                    "changed_ids": [segment.id],
                    "invalidated": [
                        f"video_selection:{segment.id}",
                        f"video_upscale:{segment.id}",
                    ],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": True,
                },
            )

            keyframe = self._preview(
                document,
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
                "char-seed-keyframe",
            )
            self.assertEqual(
                keyframe,
                {
                    "revision": document.revision,
                    "command_name": "keyframe.apply_operations",
                    "will_write": True,
                    "changed_ids": [segment.id],
                    "invalidated": [
                        f"segment_video_selection:{segment.id}",
                        f"video_upscale_selection:{segment.id}",
                    ],
                    "preserved": [],
                    "high_impact": True,
                },
            )

            script = self._preview(
                document,
                "script.apply_operations",
                {
                    "scope": scope,
                    "operations": [
                        {
                            "op": "update_segment_fields",
                            "segment_id": segment.id,
                            "fields": {"action": "甲缓慢抬头。"},
                        }
                    ],
                },
                "char-seed-script",
            )
            self.assertEqual(
                script,
                {
                    "revision": document.revision,
                    "command_name": "script.apply_operations",
                    "will_write": True,
                    "changed_ids": sorted([segment.id, scene.id]),
                    "invalidated": [
                        f"video_selection:{segment.id}",
                        f"video_upscale:{segment.id}",
                    ],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": True,
                },
            )

    async def test_location_previews_lock_noop_rename_and_image_reselect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            image = add_image_asset(store)
            document = install_location(store, view_asset_id=image)
            location = document.location_library.locations[0]
            location_image = location.images[0]
            scope = {"location_ids": [location.id], "scene_ids": []}

            noop = self._preview(
                document,
                "location.apply_operations",
                {
                    "scope": scope,
                    "operations": [
                        {
                            "op": "update_image",
                            "image_id": location_image.id,
                            "fields": {"description": location_image.description},
                        }
                    ],
                },
                "char-location-noop",
            )
            self.assertEqual(
                noop,
                {
                    "revision": document.revision,
                    "command_name": "location.apply_operations",
                    "will_write": False,
                    "changed_ids": [],
                    "invalidated": [],
                    "preserved": ["location_selection"],
                    "high_impact": False,
                    "soft_reference_clears": [],
                },
            )

            rename = self._preview(
                document,
                "location.apply_operations",
                {
                    "scope": scope,
                    "operations": [
                        {
                            "op": "update_image",
                            "image_id": location_image.id,
                            "fields": {"name": "新图片名"},
                        }
                    ],
                },
                "char-location-rename",
            )
            self.assertEqual(
                rename,
                {
                    "revision": document.revision,
                    "command_name": "location.apply_operations",
                    "will_write": True,
                    "changed_ids": [location_image.id],
                    "invalidated": [],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": False,
                    "soft_reference_clears": [],
                },
            )

            clear = self._preview(
                document,
                "location.apply_operations",
                {
                    "scope": scope,
                    "operations": [{"op": "clear_image_selection", "image_id": location_image.id}],
                },
                "char-location-clear-view",
            )
            self.assertEqual(
                clear,
                {
                    "revision": document.revision,
                    "command_name": "location.apply_operations",
                    "will_write": True,
                    "changed_ids": [location_image.id],
                    "invalidated": [f"location_image_selection:{location_image.id}"],
                    "preserved": ["asset_history", "generation_history"],
                    "high_impact": True,
                    "soft_reference_clears": [],
                },
            )

            select = self._preview(
                document,
                "location.select_image",
                {"image_id": location_image.id, "asset_id": image},
                "char-location-select-same",
            )
            self.assertFalse(select["will_write"])

    async def test_delete_image_preview_has_no_shot_or_keyframe_reference_clears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _service, document, _route = await _visual_project(directory)
            assert document.director_script is not None
            scene = document.director_script.scenes[0]
            image = add_image_asset(store)
            document = install_location(store, view_asset_id=image, scene_ids=(scene.id,))
            location = document.location_library.locations[0]
            location_image = location.images[0]
            preview = self._preview(
                document,
                "location.apply_operations",
                {
                    "scope": {
                        "location_ids": [location.id],
                        "scene_ids": [],
                    },
                    "operations": [{"op": "delete_image", "image_id": location_image.id}],
                },
                "char-location-delete-view",
            )
            self.assertEqual(preview["soft_reference_clears"], [])
            self.assertEqual(
                preview["invalidated"],
                [f"location_image_selection:{location_image.id}"],
            )
            self.assertTrue(preview["high_impact"])

    async def test_read_only_and_unsupported_commands_raise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                _scene,
                _segment,
                _binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            with self.assertRaisesRegex(ValueError, "只读命令不需要影响预览。"):
                self._preview(document, "project.read", {}, "char-readonly")
            with self.assertRaisesRegex(
                ValueError, "project.preview_impact 尚不支持命令：video.start_source。"
            ):
                self._preview(
                    document,
                    "video.start_source",
                    {
                        "scope": {"scene_ids": []},
                        "segment_id": "a" * 32,
                        "source": {"kind": "keyframe", "source_segment_id": None},
                    },
                    "char-unsupported",
                )

    async def test_revision_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                _store,
                _service,
                document,
                scene,
                _segment,
                _binding,
                _video,
                _cue,
            ) = await self._document_with_cue(directory)
            command = parse_director_command(
                {
                    "name": "script.apply_operations",
                    "expected_revision": document.revision + 1,
                    "idempotency_key": "char-bad-revision",
                    "arguments": {"scope": {"scene_ids": [scene.id]}, "operations": []},
                }
            )
            with self.assertRaisesRegex(
                ValueError, "待预览 command 的 expected_revision 与当前项目不一致。"
            ):
                preview_command_impact(document, command)
