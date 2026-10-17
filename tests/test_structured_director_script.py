from __future__ import annotations

import json
import unittest

from core.director_proposals.schema_gen import ProposalError
from core.director_proposals.script_codec import (
    parse_structured_director_script_proposal,
)


def proposal_json() -> str:
    return """{
      "scenes": [{
        "title": "末班车",
        "summary": "小满在停用前的车站等最后一班车。",
        "setting": "傍晚，空旷站台，冷蓝色天光。",
        "driver": "drama",
        "narration_cues": [],
        "shots": [{
          "visible_character_ids": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
          "composition": "中远景，人物位于画面右侧。",
          "camera_movement": "缓慢推近。",
          "action": "小满握住行李箱拉杆，抬头看向站牌。",
          "audio_direction": "远处风声和站内电流声。",
          "transition_in": null,
          "segments": [{
            "duration_estimate_seconds": 6.0,
            "action": "小满保持站立，抬头看向站牌。",
            "dialogue_lines": [],
            "boundary_from_previous": null
          }]
        }]
      }]
    }"""


def narrated_proposal_json(
    *, text: str = "末班车到来以前，站台仍旧保持安静。", duration: float = 3.0
) -> str:
    proposal = json.loads(proposal_json())
    scene = proposal["scenes"][0]
    scene["driver"] = "narration"
    scene["shots"][0]["segments"][0]["duration_estimate_seconds"] = duration
    scene["narration_cues"] = [
        {
            "start_shot_index": 0,
            "end_shot_index": 0,
            "zh": {"text": text, "seed": 42},
            "en": {"text": "Before the last train arrives, the platform stays quiet.", "seed": 42},
        }
    ]
    return json.dumps(proposal, ensure_ascii=False)


class StructuredDirectorScriptAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_scene_cue_scope_is_strict_without_punctuation_or_estimated_timing_rules(self) -> None:
        parsed = parse_structured_director_script_proposal(narrated_proposal_json())
        self.assertEqual(len(parsed.scenes[0].narration_cues), 1)

        two_cues = json.loads(narrated_proposal_json())
        cue = two_cues["scenes"][0]["narration_cues"][0]
        two_cues["scenes"][0]["narration_cues"].append(cue.copy())
        with self.assertRaisesRegex(ProposalError, "最多只能有一段"):
            parse_structured_director_script_proposal(json.dumps(two_cues, ensure_ascii=False))

        partial = json.loads(narrated_proposal_json())
        partial["scenes"][0]["shots"].append(partial["scenes"][0]["shots"][0].copy())
        with self.assertRaisesRegex(ProposalError, "全部 Shot"):
            parse_structured_director_script_proposal(json.dumps(partial, ensure_ascii=False))

        for text in (
            "这是一段非常长且仍然持续展开的完整旁白" * 12 + "。",
            "他说：‘真的吗？’她点头，这才是他最后的希望。",
            "一个完整的意图可以不带句末标点",
        ):
            parsed = parse_structured_director_script_proposal(
                narrated_proposal_json(text=text, duration=10)
            )
            self.assertEqual(parsed.scenes[0].narration_cues[0].zh.text, text)

    def test_drama_rejects_narration_and_narration_rejects_dialogue(self) -> None:
        drama_with_cue = json.loads(narrated_proposal_json())
        drama_with_cue["scenes"][0]["driver"] = "drama"
        with self.assertRaisesRegex(ProposalError, "Drama Scene 不能包含旁白"):
            parse_structured_director_script_proposal(
                json.dumps(drama_with_cue, ensure_ascii=False)
            )

        narration_with_dialogue = json.loads(narrated_proposal_json())
        narration_with_dialogue["scenes"][0]["shots"][0]["segments"][0]["dialogue_lines"] = [
            {
                "character_id": "a" * 32,
                "text": "还会来吗？",
                "delivery": "轻声",
            }
        ]
        with self.assertRaisesRegex(ProposalError, "Narration Scene 不能包含对白"):
            parse_structured_director_script_proposal(
                json.dumps(narration_with_dialogue, ensure_ascii=False)
            )

        drama_with_dialogue = json.loads(proposal_json())
        drama_with_dialogue["scenes"][0]["shots"][0]["segments"][0]["dialogue_lines"] = (
            narration_with_dialogue["scenes"][0]["shots"][0]["segments"][0]["dialogue_lines"]
        )
        parsed = parse_structured_director_script_proposal(
            json.dumps(drama_with_dialogue, ensure_ascii=False)
        )
        self.assertEqual(parsed.scenes[0].narration_cues, ())

    def test_agent_rejects_unknown_and_invalid_boundary_fields(self) -> None:
        unknown = proposal_json().replace(
            '"setting": "傍晚，空旷站台，冷蓝色天光。",',
            '"setting": "傍晚，空旷站台，冷蓝色天光。", "prompt": "cinematic",',
        )
        with self.assertRaisesRegex(ProposalError, "未声明"):
            parse_structured_director_script_proposal(unknown)

        invalid_boundary = proposal_json().replace(
            '"boundary_from_previous": null',
            '"boundary_from_previous": {"reason":"control_boundary",'
            '"continuity_instruction":"保持构图"}',
        )
        with self.assertRaisesRegex(ProposalError, "第一个 Segment"):
            parse_structured_director_script_proposal(invalid_boundary)

    def test_agent_rejects_duplicate_visible_character_ids_in_core(self) -> None:
        character_id = "a" * 32
        duplicate = proposal_json().replace(
            f'"visible_character_ids": ["{character_id}"]',
            f'"visible_character_ids": ["{character_id}", "{character_id}"]',
        )

        with self.assertRaisesRegex(ProposalError, "不能重复"):
            parse_structured_director_script_proposal(duplicate)


if __name__ == "__main__":
    unittest.main()
