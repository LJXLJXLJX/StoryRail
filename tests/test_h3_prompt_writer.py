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

    def test_narration_and_voice_declaration_rules(self) -> None:
        # 旁白不能写进视频提示词；人声声明按 Scene driver 与 Segment 对白区分。
        instructions = "\n".join(r["text"] for r in skill_resources())
        for required in (
            "独立 TTS 音频资产承载",
            "绝不把剧本旁白、解说词或 narrator 文本写入",
            "全片无人类语音，保持纯净环境音",
            "预留后期主旁白音频叠加通道",
            "除 `<d>` 中的台词外无其它人类语音",
            "只有 `scene.driver` 为 `narration` 时再加“预留后期主旁白音频叠加通道”",
            "drama Scene 不写这句",
            "逐字照抄 `dialogue[].text`",
            "`null` 是引用库外的临时说话者",
            "`on_screen` 是 Segment 覆盖的全部 Shot 的并集",
        ):
            self.assertIn(required, instructions)
        self.assertNotIn(
            '末尾明确声明："全片无人类语音，保持纯净环境音，预留后期主旁白', instructions
        )

    def test_sound_policy_requires_effects_and_disables_bgm_by_default(self) -> None:
        instructions = "\n".join(r["text"] for r in skill_resources())
        for required in (
            "默认禁止生成非画内背景音乐",
            "non_diegetic_music` 必须为 `N/A`",
            "只有 `user_direction` 或 Shot `audio_direction` 明确写出配乐或音乐入点时",
            "必须根据画面动作和环境写出具体音效",
            "只有画内角色演奏、收音机、电视或手机播放的音乐",
        ):
            self.assertIn(required, instructions)

    def test_storyrail_timestamp_grammar_is_in_the_contract(self) -> None:
        instructions = "\n".join(r["text"] for r in skill_resources())
        self.assertIn("不新增字段、不新增时间戳语法", instructions)

    def test_multi_shot_segment_contract_is_soft_and_bounded(self) -> None:
        # 单 Shot 不虚构切镜；多 Shot 按官方语法顺序写，切点是软约束，段内上限 3 个。
        instructions = "\n".join(r["text"] for r in skill_resources())
        for required in (
            "`context.shots` 只有一项时不要写切镜",
            "[Shot 1]",
            "[Shot 2] At MM:SS.mmm",
            "软约束",
            "切点漂移仍是合格候选",
            "不超过 3 个",
            "<scenetrans>",
            "首尾 Picture 只锚定第一个 Shot 的开头与最后一个 Shot 的结尾",
        ):
            self.assertIn(required, instructions)
        # 旧的“Segment 永远是连续单镜”说法不能与新规则并存。
        self.assertNotIn("StoryRail 的 Segment 是连续镜头", instructions)


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
