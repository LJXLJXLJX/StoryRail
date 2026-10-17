from __future__ import annotations

import unittest
from pathlib import Path

from core.director_proposals import (
    KeyframeSceneInput,
    KeyframeSegmentInput,
    KeyframeShotInput,
)
from core.director_proposals.keyframe_codec import parse_keyframe_plan
from core.director_proposals.schema_gen import ProposalError


class KeyframePlannerTests(unittest.IsolatedAsyncioTestCase):
    def test_standard_skill_package_is_exported_for_runtime_discovery(self) -> None:
        self.assertTrue(
            (
                Path("core/director_proposals/skills/storyrail-keyframe-planner") / "SKILL.md"
            ).is_file()
        )
        self.assertTrue(
            (
                Path("core/director_proposals/skills/storyrail-keyframe-planner")
                / "references"
                / "cinematic-keyframe-design.md"
            ).is_file()
        )
        self.assertTrue(
            (
                Path("core/director_proposals/skills/storyrail-keyframe-planner")
                / "references"
                / "cinematic-frame-prompting.md"
            ).is_file()
        )

    def test_rejects_unknown_fields_and_non_boolean_continuity(self) -> None:
        shot_id = "1" * 32
        segment_id = "2" * 32
        with self.assertRaisesRegex(ProposalError, "未声明"):
            parse_keyframe_plan(
                f'''{{"shots":[{{"shot_id":"{shot_id}",
                "continues_from_previous_shot":false,"start_prompt_text":"起始状态。",
                "start_visible_character_ids":[],"start_character_references":[],
                "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
                "segments":[{{"segment_id":"{segment_id}",
                "frame_strategy":"both",
                "end_prompt_text":"结束状态。","end_visible_character_ids":[],"end_character_references":[],
                "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null,
                "model":"video_prompt"}}]}}]}}'''
            )
        with self.assertRaisesRegex(ProposalError, "类型"):
            parse_keyframe_plan(
                f'''{{"shots":[{{"shot_id":"{shot_id}",
                "continues_from_previous_shot":1,"start_prompt_text":"起始状态。",
                "start_visible_character_ids":[],"start_character_references":[],
                "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
                "segments":[{{"segment_id":"{segment_id}",
                "frame_strategy":"both",
                "end_prompt_text":"结束状态.","end_visible_character_ids":[],"end_character_references":[],
                "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}}]}}'''
            )


def _one_shot_response(shot_id: str, segment_id: str) -> str:
    return f'''{{"shots":[{{"shot_id":"{shot_id}",
    "continues_from_previous_shot":false,"start_prompt_text":"起始状态。",
    "start_visible_character_ids":[],"start_character_references":[],"start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
    "segments":[{{"segment_id":"{segment_id}",
    "frame_strategy":"start",
    "end_prompt_text":"结束状态。","end_visible_character_ids":[],"end_character_references":[],
    "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}}]}}'''


def _one_shot_scene(scene_id: str, shot_id: str, segment_id: str) -> KeyframeSceneInput:
    return KeyframeSceneInput(
        scene_id,
        "Scene",
        "安静的空间。",
        (
            KeyframeShotInput(
                shot_id,
                "中景。",
                "固定。",
                "环境变化。",
                (),
                (KeyframeSegmentInput(segment_id, "环境变化。"),),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
