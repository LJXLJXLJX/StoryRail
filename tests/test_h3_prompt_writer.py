from __future__ import annotations

import json
import unittest

import pytest

from core.director_proposals.schema_gen import ProposalError
from core.model_providers.minimax_h3.prompt_codec import parse_h3_prompt_proposal
from core.model_providers.minimax_h3.prompt_context import skill_resources
from core.model_providers.minimax_h3.prompt_contract import H3PromptMode


class H3PromptWriterTests(unittest.IsolatedAsyncioTestCase):
    def test_full_mode_contracts_do_not_override_user_prompt_language(self) -> None:
        # Real Kimi FL2VA ignored Chinese while embedded references mandated English.
        for mode in H3PromptMode:
            with self.subTest(mode=mode):
                instructions = "\n".join(r["text"] for r in skill_resources())
                self.assertIn("Follow the user-specified prompt language", instructions)
                for conflict in (
                    "Write rewrite sections in English",
                    "Write all six rewrite sections in English",
                    "Write the body in English",
                    "natural English",
                    "1–4 English sentences",
                    "1–3 English sentences",
                ):
                    self.assertNotIn(conflict, instructions)

    def test_independent_narration_is_never_written_into_video_prompt(self) -> None:
        instructions = "\n".join(r["text"] for r in skill_resources())
        for required in (
            "独立 TTS 音频资产承载",
            "绝不把剧本旁白、解说词或 narrator 文本写入",
            "全片无人类语音，保持纯净环境音",
            "预留后期主旁白音频叠加通道",
        ):
            self.assertIn(required, instructions)

    def test_sound_policy_requires_effects_and_disables_bgm_by_default(self) -> None:
        instructions = "\n".join(r["text"] for r in skill_resources())
        for required in (
            "默认禁止生成非画内背景音乐",
            "non_diegetic_music` 必须为 `N/A`",
            "必须根据画面动作和环境写出具体音效",
            "只有画内角色演奏、收音机、电视或手机播放的音乐",
        ):
            self.assertIn(required, instructions)

    def test_storyrail_shot_directing_rules_are_in_the_contract(self) -> None:
        instructions = "\n".join(r["text"] for r in skill_resources())
        for required in (
            "不新增字段、不新增时间戳语法",
            "4 秒以上的单镜写 2~3 个连续阶段",
            "不虚构段内切镜",
            "节拍与 `duration_seconds` 匹配",
        ):
            self.assertIn(required, instructions)


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize(
    "text",
    [
        "scene_description: sea ice",
        "scene_description: 冰海，保持对白原文。",
        "完整动作与声音。" * 1500,
    ],
)
def test_pure_h3_preserves_language_and_detailed_prompt(text):
    assert parse_h3_prompt_proposal(json.dumps({"prompt_text": text})).prompt_text == text


@pytest.mark.parametrize(
    "value",
    [
        {"prompt_text": "正文", "model": "forbidden"},
        {"prompt_text": ""},
        {"prompt_text": 1},
        {"prompt_text": "x" * 20001},
    ],
)
def test_pure_h3_rejects_unknown_fields_and_invalid_body(value):
    with pytest.raises(ProposalError):
        parse_h3_prompt_proposal(json.dumps(value))
