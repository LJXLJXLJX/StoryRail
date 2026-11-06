import json

import pytest

from core.director_proposals.compiler_intent import context_value, parse_compiler_intent


def test_core_user_message_cannot_be_replaced_by_director_paraphrase():
    intent = parse_compiler_intent(
        "keyframe_plan",
        {
            "raw_user_request": "不可信转述",
            "target_ids": ["a" * 32],
            "user_constraints": ["只处理第一场。"],
            "director_hypotheses": ["冷色调或许更好。"],
            "scope_guard": {
                "kind": "shot",
                "required_shared_boundaries": [
                    {"left_segment_id": "b" * 32, "right_segment_id": "c" * 32},
                ],
            },
        },
        raw_user_request="相邻两段共用边界，但不要生成图片。",
    )
    context = json.loads(intent.context_json())
    assert context["raw_user_request"] == "相邻两段共用边界，但不要生成图片。"
    assert context["scope_guard"]["target_ids"] == ["a" * 32]
    assert len(intent.required_shared_boundaries) == 1
    assert context["director_hypotheses"] == ["冷色调或许更好。"]
    assert context_value(intent.context_json()) == context
    assert context_value("请写冷色调。") == "请写冷色调。"


@pytest.mark.parametrize(
    "arguments",
    [
        {"core_facts": {"selected_asset_id": "a" * 32}},
        {"scope_guard": {"authorized": True}},
        {"scope_guard": {"kind": "everything"}},
        {"target_ids": ["a" * 32, "a" * 32]},
        {"target_ids": ["made-up-id"]},
        {"user_constraints": [False]},
        {"user_constraints": [""]},
        {"director_hypotheses": [None]},
        {"user_instruction": "第二次转述"},
        {
            "scope_guard": {
                "required_shared_boundaries": [
                    {"left_segment_id": "a" * 32, "right_segment_id": "b" * 32},
                ]
            }
        },
    ],
)
def test_h3_rejects_untyped_facts_scope_or_keyframe_only_constraints(arguments):
    with pytest.raises(ValueError):
        parse_compiler_intent("video_prompt", arguments, raw_user_request="优化当前片段。")
