from __future__ import annotations

import unittest
from pathlib import Path

from core.director_proposals import (
    KeyframeCharacterInput,
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
        segment_id = "2" * 32

        def raw(extra: str, continues: str) -> str:
            return f'''{{"segments":[{{"segment_id":"{segment_id}",
            "continues_from_previous":{continues},
            "frame_strategy":"both",
            "start_prompt_text":"起始状态。",
            "start_visible_character_ids":[],"start_character_references":[],
            "end_prompt_text":"结束状态。","end_visible_character_ids":[],"end_character_references":[]{extra}}}]}}'''

        with self.assertRaisesRegex(ProposalError, "未声明"):
            parse_keyframe_plan(raw(',"model":"video_prompt"', "false"))
        with self.assertRaisesRegex(ProposalError, "类型"):
            parse_keyframe_plan(raw("", "1"))


def _one_segment_response(segment_id: str) -> str:
    return f'''{{"segments":[{{"segment_id":"{segment_id}",
    "continues_from_previous":false,
    "frame_strategy":"start",
    "start_prompt_text":"起始状态。",
    "start_visible_character_ids":[],"start_character_references":[],
    "end_prompt_text":"结束状态。","end_visible_character_ids":[],"end_character_references":[]}}]}}'''


def _one_segment_scene(
    scene_id: str, shot_id: str, segment_ids: tuple[str, ...]
) -> KeyframeSceneInput:
    shot = KeyframeShotInput(
        shot_id,
        "中景。",
        "固定。",
        "环境变化。",
        (KeyframeCharacterInput("a" * 32, "Jack"),),
    )
    return KeyframeSceneInput(
        scene_id,
        "Scene",
        "安静的空间。",
        tuple(
            KeyframeSegmentInput(segment_id, "环境变化。", (shot,)) for segment_id in segment_ids
        ),
    )


if __name__ == "__main__":
    unittest.main()
