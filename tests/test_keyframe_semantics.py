"""从旧执行器测试迁入的 Keyframe 领域语义；直接验证正式纯编译器。"""

import json
import unittest

from core.director_commands import (
    SetKeyframeActivation,
    ShareKeyframeBoundary,
    SplitKeyframeBoundary,
    UpdateKeyframeFields,
)
from core.director_proposals import (
    KeyframeCharacterInput,
    KeyframeOperationsProposal,
    KeyframeSceneInput,
    KeyframeSegmentInput,
    KeyframeShotInput,
)
from core.director_proposals.keyframe_codec import (
    compile_keyframe_proposal,
    parse_keyframe_plan,
)
from core.director_proposals.schema_gen import ProposalError

CHARACTER = KeyframeCharacterInput("a" * 32, "Jack")


def compile_fixture(raw, *, scenes, required_shared_boundaries=(), **unused):
    proposal, operations = compile_keyframe_proposal(
        parse_keyframe_plan(raw), scenes, required_shared_boundaries
    )
    return (
        proposal if operations is None else KeyframeOperationsProposal(operations, "测试纯编译结果")
    )


def _shot(shot_id: str, characters=()) -> KeyframeShotInput:
    return KeyframeShotInput(shot_id, "中景。", "固定。", "环境变化。", tuple(characters))


def _scene(
    segments: tuple[KeyframeSegmentInput, ...],
) -> KeyframeSceneInput:
    return KeyframeSceneInput("9" * 32, "Scene", "安静的空间。", segments)


def _plan(segments: list[dict]) -> str:
    return json.dumps({"segments": segments})


def _segment_plan(
    segment_id: str,
    *,
    continues: bool = False,
    strategy: str = "both",
    start_prompt: str = "起始状态。",
    start_ids: tuple[str, ...] = (),
    end_prompt: str = "结束状态。",
    end_ids: tuple[str, ...] = (),
) -> dict:
    return {
        "segment_id": segment_id,
        "continues_from_previous": continues,
        "frame_strategy": strategy,
        "start_prompt_text": "" if continues else start_prompt,
        "start_visible_character_ids": [] if continues else list(start_ids),
        "start_character_references": [],
        "end_prompt_text": end_prompt,
        "end_visible_character_ids": list(end_ids),
        "end_character_references": [],
    }


class PureKeyframeSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_character_changes_do_not_override_planner_strategy(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "环境变化。",
                    (_shot("1" * 32, (CHARACTER,)),),
                    visible_characters=(CHARACTER,),
                ),
            )
        )
        for strategy, start_ids, end_ids, expected in (
            ("start", [], [CHARACTER.id], "start"),
            ("end", [CHARACTER.id], [], "end"),
            ("start", [CHARACTER.id], [CHARACTER.id], "start"),
            ("end", [CHARACTER.id], [CHARACTER.id], "end"),
            ("start", [], [], "start"),
        ):
            with self.subTest(strategy=strategy, start=start_ids, end=end_ids):
                plan = _segment_plan(
                    "2" * 32,
                    strategy=strategy,
                    start_ids=tuple(start_ids),
                    end_ids=tuple(end_ids),
                )
                result = compile_fixture(_plan([plan]), scenes=(scene,))
                actual = result.segments[0]
                self.assertEqual(actual.frame_strategy, expected)
                self.assertEqual(list(actual.start_visible_character_ids), start_ids)
                self.assertEqual(list(actual.end_visible_character_ids), end_ids)

    async def test_unused_endpoints_can_be_empty_and_do_not_overwrite_saved_plans(self):
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "小幅动作",
                    (_shot("1" * 32),),
                    start_keyframe_id="3" * 32,
                    end_keyframe_id="4" * 32,
                ),
            )
        )
        for strategy, start_prompt, end_prompt, expected in (
            ("none", "", "", []),
            ("start", "起点", "", ["3" * 32]),
            ("end", "", "终点", ["4" * 32]),
        ):
            proposal = _segment_plan(
                "2" * 32, strategy=strategy, start_prompt=start_prompt, end_prompt=end_prompt
            )
            result = compile_fixture(_plan([proposal]), scenes=(scene,))
            self.assertEqual(
                [
                    item.keyframe_id
                    for item in result.operations
                    if isinstance(item, UpdateKeyframeFields)
                ],
                expected,
            )
            activation = next(
                item for item in result.operations if isinstance(item, SetKeyframeActivation)
            )
            self.assertEqual(
                (activation.start_enabled, activation.end_enabled),
                (strategy == "start", strategy == "end"),
            )

    async def test_independent_segments_follow_planner_strategy(self) -> None:
        """相邻 Segment 独立边界时按各自策略启用，不强制共享。"""
        for strategy in ("start", "end"):
            for with_slots in (False, True):
                with self.subTest(strategy=strategy, with_slots=with_slots):
                    segments, plans = ([], [])
                    for index in range(3):
                        segment_id = f"{index + 3:032x}"
                        segments.append(
                            KeyframeSegmentInput(
                                segment_id,
                                "沿同一镜头继续运动。",
                                (_shot(f"{index + 1:032x}"),),
                                start_keyframe_id=(
                                    f"{index * 2 + 10:032x}" if with_slots else None
                                ),
                                end_keyframe_id=(f"{index * 2 + 11:032x}" if with_slots else None),
                            )
                        )
                        plans.append(
                            _segment_plan(segment_id, strategy=strategy, end_prompt="结束状态。")
                        )
                    result = compile_fixture(_plan(plans), scenes=(_scene(tuple(segments)),))
                    expected = [(True, False)] * 3 if strategy == "start" else [(False, True)] * 3
                    if with_slots:
                        activations = [
                            item
                            for item in result.operations
                            if isinstance(item, SetKeyframeActivation)
                        ]
                        self.assertEqual(
                            [(item.start_enabled, item.end_enabled) for item in activations],
                            expected,
                        )
                        self.assertFalse(
                            any(
                                isinstance(item, (ShareKeyframeBoundary, SplitKeyframeBoundary))
                                for item in result.operations
                            )
                        )
                        updates = {
                            item.keyframe_id
                            for item in result.operations
                            if isinstance(item, UpdateKeyframeFields)
                        }
                        self.assertEqual(
                            updates,
                            {
                                keyframe_id
                                for segment in segments
                                for keyframe_id in (
                                    segment.start_keyframe_id
                                    if strategy == "start"
                                    else segment.end_keyframe_id,
                                )
                            },
                        )
                    else:
                        self.assertEqual(
                            [
                                (
                                    item.frame_strategy in {"start", "both"},
                                    item.frame_strategy in {"end", "both"},
                                )
                                for item in result.segments
                            ],
                            expected,
                        )

    async def test_coverage_normalization_preserves_locked_segments(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "环境变化。",
                    (_shot("1" * 32, (CHARACTER,)),),
                    start_keyframe_id="4" * 32,
                    end_keyframe_id="5" * 32,
                    start_locked=True,
                    visible_characters=(CHARACTER,),
                ),
            )
        )
        result = compile_fixture(
            _plan([_segment_plan("2" * 32, end_ids=(CHARACTER.id,))]), scenes=(scene,)
        )
        self.assertIsInstance(result, KeyframeOperationsProposal)
        self.assertEqual(result.operations, ())

    async def test_compiles_creative_plan_to_existing_slot_operations(self) -> None:
        start_id, end_id, segment_id = "3" * 32, "4" * 32, "2" * 32
        scene = _scene(
            (
                KeyframeSegmentInput(
                    segment_id,
                    "环境变化。",
                    (_shot("1" * 32),),
                    start_keyframe_id=start_id,
                    end_keyframe_id=end_id,
                ),
            )
        )
        proposal = compile_fixture(
            _plan([_segment_plan(segment_id, strategy="start")]), scenes=(scene,)
        )
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        updates = [item for item in proposal.operations if isinstance(item, UpdateKeyframeFields)]
        activations = [
            item for item in proposal.operations if isinstance(item, SetKeyframeActivation)
        ]
        self.assertEqual([item.keyframe_id for item in updates], [start_id])
        self.assertEqual([item.segment_id for item in activations], [segment_id])
        self.assertTrue(activations[0].start_enabled)
        self.assertFalse(activations[0].end_enabled)

    async def test_compiler_preserves_segment_when_either_slot_is_locked(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "环境变化。",
                    (_shot("1" * 32),),
                    start_keyframe_id="3" * 32,
                    end_keyframe_id="4" * 32,
                    start_locked=True,
                ),
            )
        )
        proposal = compile_fixture(_plan([_segment_plan("2" * 32)]), scenes=(scene,))
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        self.assertEqual(proposal.operations, ())

    async def test_compiles_creative_plan_to_current_keyframe_operations(self) -> None:
        start_id, end_id, segment_id = "3" * 32, "4" * 32, "2" * 32
        scene = _scene(
            (
                KeyframeSegmentInput(
                    segment_id,
                    "环境变化。",
                    (_shot("1" * 32),),
                    start_keyframe_id=start_id,
                    end_keyframe_id=end_id,
                ),
            )
        )
        proposal = compile_fixture(_plan([_segment_plan(segment_id)]), scenes=(scene,))
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        self.assertEqual(len(proposal.operations), 3)
        self.assertIsInstance(proposal.operations[0], UpdateKeyframeFields)
        self.assertEqual(proposal.operations[0].keyframe_id, start_id)
        self.assertIsInstance(proposal.operations[1], UpdateKeyframeFields)
        self.assertEqual(proposal.operations[1].keyframe_id, end_id)
        self.assertIsInstance(proposal.operations[2], SetKeyframeActivation)

    async def test_rejects_character_id_outside_owning_segment(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "角色离开。",
                    (_shot("1" * 32, (KeyframeCharacterInput("3" * 32, "Comi"),)),),
                    visible_characters=(KeyframeCharacterInput("3" * 32, "Comi"),),
                ),
            )
        )
        with self.assertRaisesRegex(ProposalError, "不属于该 Segment"):
            compile_fixture(
                _plan(
                    [
                        _segment_plan(
                            "2" * 32,
                            strategy="start",
                            start_ids=("4" * 32,),
                            start_prompt="角色站在门边。",
                        )
                    ]
                ),
                scenes=(scene,),
            )

    async def test_shared_start_uses_boundary_character_union(self) -> None:
        character_id = CHARACTER.id
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "3" * 32,
                    "角色放下文件。",
                    (_shot("1" * 32, (CHARACTER,)),),
                    start_keyframe_id="5" * 32,
                    end_keyframe_id="6" * 32,
                    visible_characters=(CHARACTER,),
                ),
                KeyframeSegmentInput(
                    "4" * 32,
                    "手离开画面。",
                    (_shot("2" * 32),),
                    start_keyframe_id="6" * 32,
                    end_keyframe_id="7" * 32,
                    visible_characters=(),
                    continues_from_previous=True,
                ),
            )
        )
        parsed, operations = compile_keyframe_proposal(
            parse_keyframe_plan(
                _plan(
                    [
                        _segment_plan(
                            "3" * 32,
                            end_prompt="角色的手仍停在桌上的文件旁。",
                            end_ids=(character_id,),
                        ),
                        _segment_plan(
                            "4" * 32,
                            continues=True,
                            strategy="end",
                            end_prompt="桌面上只剩文件。",
                            end_ids=(),
                        ),
                    ]
                )
            ),
            (scene,),
        )
        assert operations is not None
        self.assertTrue(parsed.segments[1].continues_from_previous)
        self.assertEqual(parsed.segments[1].start_visible_character_ids, ())
        self.assertEqual(parsed.segments[1].end_visible_character_ids, ())
        self.assertFalse(any(isinstance(item, ShareKeyframeBoundary) for item in operations))

    async def test_core_required_boundary_is_enforced_when_model_returns_false(self) -> None:
        first_segment_id, second_segment_id = "3" * 32, "4" * 32
        scene = _scene(
            (
                KeyframeSegmentInput(
                    first_segment_id,
                    "抵达。",
                    (_shot("1" * 32),),
                    start_keyframe_id="5" * 32,
                    end_keyframe_id="6" * 32,
                ),
                KeyframeSegmentInput(
                    second_segment_id,
                    "亮灯。",
                    (_shot("2" * 32),),
                    start_keyframe_id="7" * 32,
                    end_keyframe_id="8" * 32,
                ),
            )
        )
        parsed, operations = compile_keyframe_proposal(
            parse_keyframe_plan(
                _plan(
                    [
                        _segment_plan(
                            first_segment_id,
                            strategy="start",
                            end_prompt="角色停在控制台前，指示灯熄灭。",
                        ),
                        _segment_plan(
                            second_segment_id,
                            strategy="end",
                            end_prompt="指示灯亮起。",
                        ),
                    ]
                )
            ),
            (scene,),
            ((first_segment_id, second_segment_id),),
        )
        assert operations is not None
        proposal = KeyframeOperationsProposal(operations, "测试纯编译结果")
        shares = [item for item in proposal.operations if isinstance(item, ShareKeyframeBoundary)]
        self.assertEqual(
            [(item.left_segment_id, item.right_segment_id) for item in shares],
            [(first_segment_id, second_segment_id)],
        )
        activations = {
            item.segment_id: item
            for item in proposal.operations
            if isinstance(item, SetKeyframeActivation)
        }
        self.assertTrue(activations[first_segment_id].end_enabled)
        self.assertTrue(activations[second_segment_id].start_enabled)
        self.assertTrue(parsed.segments[1].continues_from_previous)
        self.assertEqual(parsed.segments[1].start_prompt_text, "")

    async def test_adopted_long_take_keeps_cuts_and_activates_shared_boundaries(self) -> None:
        for already_shared in (False, True):
            with self.subTest(already_shared=already_shared):
                segments, plans = ([], [])
                for index in range(5):
                    segment_id = f"{index + 11:032x}"
                    start_id, end_id = (f"{index + 21:032x}", f"{index + 31:032x}")
                    continuous = index >= 3
                    if already_shared and continuous:
                        start_id = segments[-1].end_keyframe_id
                    segments.append(
                        KeyframeSegmentInput(
                            segment_id,
                            "倾听。",
                            (_shot(f"{index + 1:032x}"),),
                            start_keyframe_id=start_id,
                            end_keyframe_id=end_id,
                            continues_from_previous=already_shared and continuous,
                        )
                    )
                    plans.append(
                        _segment_plan(
                            segment_id,
                            continues=already_shared and continuous,
                            strategy="start",
                            end_prompt="无线电亮灯。",
                        )
                    )
                scene = _scene(tuple(segments))
                boundaries = tuple((segments[i].id, segments[i + 1].id) for i in (2, 3))
                proposal = compile_fixture(
                    _plan(plans),
                    scenes=(scene,),
                    required_shared_boundaries=() if already_shared else boundaries,
                )
                self.assertIsInstance(proposal, KeyframeOperationsProposal)
                activations = {
                    item.segment_id: item
                    for item in proposal.operations
                    if isinstance(item, SetKeyframeActivation)
                }
                for index, segment in enumerate(segments):
                    self.assertEqual(activations[segment.id].end_enabled, index in (2, 3))
                    self.assertTrue(activations[segment.id].start_enabled)
                shares = tuple(
                    (item.left_segment_id, item.right_segment_id)
                    for item in proposal.operations
                    if isinstance(item, ShareKeyframeBoundary)
                )
                self.assertEqual(shares, () if already_shared else boundaries)

    async def test_rejects_continues_from_previous_with_non_empty_start(self) -> None:
        plan = _segment_plan("2" * 32, continues=True)
        plan["start_prompt_text"] = "上一段尾帧之外的另一种画面。"
        with self.assertRaisesRegex(ProposalError, "必须为空"):
            parse_keyframe_plan(_plan([plan]))

    async def test_rejects_first_scene_segment_continuing(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "环境变化。",
                    (_shot("1" * 32),),
                    start_keyframe_id="3" * 32,
                    end_keyframe_id="4" * 32,
                ),
            )
        )
        with self.assertRaisesRegex(ProposalError, "第一个 Segment 不能承接"):
            compile_fixture(_plan([_segment_plan("2" * 32, continues=True)]), scenes=(scene,))

    async def test_continues_into_context_segment_requires_existing_shared_slot(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "上下文段落。",
                    (_shot("1" * 32),),
                    start_keyframe_id="3" * 32,
                    end_keyframe_id="4" * 32,
                    planning_enabled=False,
                ),
                KeyframeSegmentInput(
                    "5" * 32,
                    "授权段落。",
                    (_shot("2" * 32),),
                    start_keyframe_id="6" * 32,
                    end_keyframe_id="7" * 32,
                ),
            )
        )
        with self.assertRaisesRegex(ProposalError, "请至少扩大到相邻 Segment"):
            compile_fixture(_plan([_segment_plan("5" * 32, continues=True)]), scenes=(scene,))

    async def test_unsharing_context_boundary_requires_expanded_scope(self) -> None:
        scene = _scene(
            (
                KeyframeSegmentInput(
                    "2" * 32,
                    "上下文段落。",
                    (_shot("1" * 32),),
                    start_keyframe_id="3" * 32,
                    end_keyframe_id="4" * 32,
                    planning_enabled=False,
                ),
                KeyframeSegmentInput(
                    "5" * 32,
                    "授权段落。",
                    (_shot("2" * 32),),
                    start_keyframe_id="4" * 32,
                    end_keyframe_id="7" * 32,
                ),
            )
        )
        with self.assertRaisesRegex(ProposalError, "请至少扩大到相邻 Segment"):
            compile_fixture(_plan([_segment_plan("5" * 32, strategy="end")]), scenes=(scene,))


if __name__ == "__main__":
    unittest.main()
