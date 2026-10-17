"""从旧执行器测试迁入的 Keyframe 领域语义；直接验证正式纯编译器。"""

import json
import unittest
from dataclasses import replace

from test_keyframe_planner import _one_shot_response, _one_shot_scene

from core.director_commands import (
    SetKeyframeActivation,
    ShareKeyframeBoundary,
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


def compile_fixture(raw, *, scenes, required_shared_boundaries=(), **unused):
    proposal, operations = compile_keyframe_proposal(
        parse_keyframe_plan(raw), scenes, required_shared_boundaries
    )
    return (
        proposal if operations is None else KeyframeOperationsProposal(operations, "测试纯编译结果")
    )


class PureKeyframeSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_pure_single_anchor_must_cover_characters_at_both_endpoints(self) -> None:
        character = KeyframeCharacterInput("a" * 32, "Jack")
        base = _one_shot_scene("1" * 32, "2" * 32, "3" * 32)
        scene = replace(
            base,
            shots=(
                replace(
                    base.shots[0],
                    visible_characters=(character,),
                    composition="电台局部与人物所在房间。",
                    camera_movement="沿原轴线推近或拉远。",
                ),
            ),
        )
        for strategy, start_ids, end_ids, expected in (
            ("start", [], [character.id], "both"),
            ("end", [character.id], [], "both"),
            ("start", [character.id], [character.id], "start"),
            ("end", [character.id], [character.id], "end"),
            ("start", [], [], "start"),
        ):
            with self.subTest(strategy=strategy, start=start_ids, end=end_ids):
                value = json.loads(_one_shot_response("2" * 32, "3" * 32))
                shot = value["shots"][0]
                shot["start_visible_character_ids"] = start_ids
                segment = shot["segments"][0]
                segment["end_visible_character_ids"] = end_ids
                segment["frame_strategy"] = strategy
                adapter = json.dumps(value)
                result = compile_fixture(adapter, scenes=(scene,))
                actual = result.shots[0]
                self.assertEqual(actual.segments[0].frame_strategy, expected)
                self.assertEqual(list(actual.start_visible_character_ids), start_ids)
                self.assertEqual(list(actual.segments[0].end_visible_character_ids), end_ids)

    async def test_pure_internal_boundaries_follow_planner_strategy(self) -> None:
        """Shot 内边界不再被强制两侧启用；独立首帧继承上一段尾帧描述作为连续性起点。"""
        base = _one_shot_scene("1" * 32, "2" * 32, "3" * 32)
        for strategy in ("start", "end"):
            for with_slots in (False, True):
                with self.subTest(strategy=strategy, with_slots=with_slots):
                    inputs, outputs = ([], [])
                    for index in range(3):
                        segment_id = f"{index + 3:032x}"
                        inputs.append(
                            KeyframeSegmentInput(
                                segment_id,
                                "沿同一镜头继续运动。",
                                start_keyframe_id=(
                                    f"{index * 2 + 10:032x}" if with_slots else None
                                ),
                                end_keyframe_id=f"{index * 2 + 11:032x}" if with_slots else None,
                            )
                        )
                        output = json.loads(_one_shot_response("2" * 32, segment_id))
                        segment = output["shots"][0]["segments"][0]
                        segment["frame_strategy"] = strategy
                        outputs.append(segment)
                    value = json.loads(_one_shot_response("2" * 32, "3" * 32))
                    value["shots"][0]["segments"] = outputs
                    scene = replace(base, shots=(replace(base.shots[0], segments=tuple(inputs)),))
                    result = compile_fixture(json.dumps(value), scenes=(scene,))
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
                                isinstance(item, ShareKeyframeBoundary)
                                for item in result.operations
                            )
                        )
                        start_updates = {
                            item.keyframe_id: item
                            for item in result.operations
                            if isinstance(item, UpdateKeyframeFields)
                            and item.keyframe_id
                            in {segment.start_keyframe_id for segment in inputs[1:]}
                        }
                        self.assertEqual(
                            set(start_updates),
                            {segment.start_keyframe_id for segment in inputs[1:]},
                        )
                        for previous, current in zip(outputs, inputs[1:], strict=False):
                            self.assertEqual(
                                start_updates[current.start_keyframe_id].prompt_text,
                                previous["end_prompt_text"].strip(),
                            )
                    else:
                        self.assertEqual(
                            [
                                (
                                    item.frame_strategy in {"start", "both"},
                                    item.frame_strategy in {"end", "both"},
                                )
                                for item in result.shots[0].segments
                            ],
                            expected,
                        )

    async def test_pure_coverage_normalization_preserves_locked_segments(
        self,
    ) -> None:
        character = KeyframeCharacterInput("a" * 32, "Jack")
        base = _one_shot_scene("1" * 32, "2" * 32, "3" * 32)
        value = json.loads(_one_shot_response("2" * 32, "3" * 32))
        value["shots"][0]["segments"][0]["end_visible_character_ids"] = [character.id]
        scene = replace(
            base,
            shots=(
                replace(
                    base.shots[0],
                    visible_characters=(character,),
                    segments=(
                        replace(
                            base.shots[0].segments[0],
                            start_keyframe_id="4" * 32,
                            end_keyframe_id="5" * 32,
                            start_locked=True,
                        ),
                    ),
                ),
            ),
        )
        result = compile_fixture(json.dumps(value), scenes=(scene,))
        self.assertIsInstance(result, KeyframeOperationsProposal)
        self.assertEqual(result.operations, ())

    async def test_pure_compiles_creative_plan_to_existing_slot_operations(self) -> None:
        shot_id = "1" * 32
        segment_id = "2" * 32
        start_id = "3" * 32
        end_id = "4" * 32
        adapter = _one_shot_response(shot_id, segment_id)
        scene = KeyframeSceneInput(
            "5" * 32,
            "Scene",
            "安静的空间。",
            (
                KeyframeShotInput(
                    shot_id,
                    "中景。",
                    "固定。",
                    "环境变化。",
                    (),
                    (
                        KeyframeSegmentInput(
                            segment_id,
                            "环境变化。",
                            start_keyframe_id=start_id,
                            end_keyframe_id=end_id,
                        ),
                    ),
                ),
            ),
        )
        proposal = compile_fixture(adapter, scenes=(scene,))
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        assert isinstance(proposal, KeyframeOperationsProposal)
        updates = [item for item in proposal.operations if isinstance(item, UpdateKeyframeFields)]
        activations = [
            item for item in proposal.operations if isinstance(item, SetKeyframeActivation)
        ]
        self.assertEqual([item.keyframe_id for item in updates], [start_id, end_id])
        self.assertEqual([item.segment_id for item in activations], [segment_id])
        self.assertTrue(activations[0].start_enabled)
        self.assertFalse(activations[0].end_enabled)

    async def test_pure_compiler_preserves_segment_when_either_slot_is_locked(self) -> None:
        shot_id = "1" * 32
        segment_id = "2" * 32
        adapter = _one_shot_response(shot_id, segment_id)
        scene = KeyframeSceneInput(
            "5" * 32,
            "Scene",
            "安静的空间。",
            (
                KeyframeShotInput(
                    shot_id,
                    "中景。",
                    "固定。",
                    "环境变化。",
                    (),
                    (
                        KeyframeSegmentInput(
                            segment_id,
                            "环境变化。",
                            start_keyframe_id="3" * 32,
                            end_keyframe_id="4" * 32,
                            start_locked=True,
                        ),
                    ),
                ),
            ),
        )
        proposal = compile_fixture(adapter, scenes=(scene,))
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        assert isinstance(proposal, KeyframeOperationsProposal)
        self.assertEqual(proposal.operations, ())

    async def test_pure_compiles_creative_plan_to_current_keyframe_operations(self) -> None:
        shot_id = "1" * 32
        segment_id = "2" * 32
        start_id = "3" * 32
        end_id = "4" * 32
        adapter = _one_shot_response(shot_id, segment_id)
        scene = KeyframeSceneInput(
            "5" * 32,
            "Scene",
            "安静的空间。",
            (
                KeyframeShotInput(
                    shot_id,
                    "中景。",
                    "固定。",
                    "环境变化。",
                    (),
                    (
                        KeyframeSegmentInput(
                            segment_id,
                            "环境变化。",
                            start_keyframe_id=start_id,
                            end_keyframe_id=end_id,
                        ),
                    ),
                ),
            ),
        )
        proposal = compile_fixture(adapter, scenes=(scene,))
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        assert isinstance(proposal, KeyframeOperationsProposal)
        self.assertEqual(len(proposal.operations), 3)
        self.assertIsInstance(proposal.operations[0], UpdateKeyframeFields)
        self.assertEqual(proposal.operations[0].keyframe_id, start_id)
        self.assertIsInstance(proposal.operations[1], UpdateKeyframeFields)
        self.assertEqual(proposal.operations[1].keyframe_id, end_id)
        self.assertIsInstance(proposal.operations[2], SetKeyframeActivation)

    async def test_pure_rejects_character_id_outside_owning_shot(self) -> None:
        shot_id = "1" * 32
        segment_id = "2" * 32
        allowed_id = "3" * 32
        unknown_id = "4" * 32
        adapter = f'''{{"shots":[{{"shot_id":"{shot_id}",
            "continues_from_previous_shot":false,
            "start_prompt_text":"角色站在门边。",
            "start_visible_character_ids":["{unknown_id}"],"start_character_references":[],
            "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
            "segments":[{{"segment_id":"{segment_id}",
            "frame_strategy":"start",
            "end_prompt_text":"角色离开画面。","end_visible_character_ids":[],"end_character_references":[],
            "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}}]}}'''
        scene = KeyframeSceneInput(
            "5" * 32,
            "门厅",
            "空门厅。",
            (
                KeyframeShotInput(
                    shot_id,
                    "中景。",
                    "固定。",
                    "角色离开。",
                    (KeyframeCharacterInput(allowed_id, "Comi"),),
                    (KeyframeSegmentInput(segment_id, "角色离开。"),),
                ),
            ),
        )
        with self.assertRaisesRegex(ProposalError, "不属于该 Shot"):
            compile_fixture(adapter, scenes=(scene,))

    async def test_pure_shared_start_uses_previous_shot_character_scope(self) -> None:
        first_shot_id = "1" * 32
        second_shot_id = "2" * 32
        first_segment_id = "3" * 32
        second_segment_id = "4" * 32
        character_id = "5" * 32
        shared_prompt = "角色的手仍停在桌上的文件旁。"
        adapter = f'''{{"shots":[
              {{"shot_id":"{first_shot_id}",
               "continues_from_previous_shot":false,
               "start_prompt_text":"角色站在桌边。",
               "start_visible_character_ids":["{character_id}"],"start_character_references":[],
               "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
               "segments":[{{"segment_id":"{first_segment_id}",
                 "frame_strategy":"both",
                 "end_prompt_text":"{shared_prompt}",
                 "end_visible_character_ids":["{character_id}"],"end_character_references":[],
                 "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}},
              {{"shot_id":"{second_shot_id}",
               "continues_from_previous_shot":true,
               "start_prompt_text":"{shared_prompt}",
               "start_visible_character_ids":["{character_id}"],"start_character_references":[],
               "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
               "segments":[{{"segment_id":"{second_segment_id}",
                 "frame_strategy":"end",
                 "end_prompt_text":"桌面上只剩文件。",
                 "end_visible_character_ids":[],"end_character_references":[],
                 "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}}
            ]}}'''
        scene = KeyframeSceneInput(
            "6" * 32,
            "办公室",
            "安静的办公室。",
            (
                KeyframeShotInput(
                    first_shot_id,
                    "中景。",
                    "固定。",
                    "角色放下文件。",
                    (KeyframeCharacterInput(character_id, "Jack"),),
                    (KeyframeSegmentInput(first_segment_id, "角色放下文件。"),),
                ),
                KeyframeShotInput(
                    second_shot_id,
                    "文件特写。",
                    "固定。",
                    "角色的手离开画面。",
                    (),
                    (KeyframeSegmentInput(second_segment_id, "手离开画面。"),),
                ),
            ),
        )
        proposal = compile_fixture(adapter, scenes=(scene,))
        self.assertTrue(proposal.shots[1].continues_from_previous_shot)
        self.assertEqual(proposal.shots[1].start_visible_character_ids, (character_id,))

    async def test_pure_core_required_boundary_is_enforced_when_model_returns_false(self) -> None:
        first_shot_id = "1" * 32
        second_shot_id = "2" * 32
        first_segment_id = "3" * 32
        second_segment_id = "4" * 32
        first_start_id = "5" * 32
        first_end_id = "6" * 32
        second_start_id = "7" * 32
        second_end_id = "8" * 32
        adapter = f'''{{"shots":[
              {{"shot_id":"{first_shot_id}",
               "continues_from_previous_shot":false,
               "start_prompt_text":"角色走向控制台。","start_visible_character_ids":[],"start_character_references":[],
               "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
               "segments":[{{"segment_id":"{first_segment_id}",
                 "frame_strategy":"start",
                 "end_prompt_text":"角色停在控制台前，指示灯熄灭。",
                 "end_visible_character_ids":[],"end_character_references":[],"end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}},
              {{"shot_id":"{second_shot_id}",
               "continues_from_previous_shot":false,
               "start_prompt_text":"控制台的另一幅近景。","start_visible_character_ids":[],"start_character_references":[],
               "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
               "segments":[{{"segment_id":"{second_segment_id}",
                 "frame_strategy":"end",
                 "end_prompt_text":"指示灯亮起。",
                 "end_visible_character_ids":[],"end_character_references":[],"end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}}
            ]}}'''
        scene = KeyframeSceneInput(
            "9" * 32,
            "控制室",
            "昏暗控制室。",
            (
                KeyframeShotInput(
                    first_shot_id,
                    "全景。",
                    "固定。",
                    "角色抵达控制台。",
                    (),
                    (
                        KeyframeSegmentInput(
                            first_segment_id,
                            "抵达。",
                            start_keyframe_id=first_start_id,
                            end_keyframe_id=first_end_id,
                        ),
                    ),
                ),
                KeyframeShotInput(
                    second_shot_id,
                    "近景。",
                    "固定。",
                    "指示灯亮起。",
                    (),
                    (
                        KeyframeSegmentInput(
                            second_segment_id,
                            "亮灯。",
                            start_keyframe_id=second_start_id,
                            end_keyframe_id=second_end_id,
                        ),
                    ),
                ),
            ),
        )
        proposal = compile_fixture(
            adapter,
            scenes=(scene,),
            required_shared_boundaries=((first_segment_id, second_segment_id),),
        )
        self.assertIsInstance(proposal, KeyframeOperationsProposal)
        assert isinstance(proposal, KeyframeOperationsProposal)
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

    async def test_pure_adopted_long_take_keeps_cuts_and_activates_shared_boundaries(self) -> None:
        for already_shared in (False, True):
            with self.subTest(already_shared=already_shared):
                shots, output = ([], [])
                for index in range(5):
                    shot_id, segment_id = (f"{index + 1:032x}", f"{index + 11:032x}")
                    start_id, end_id = (f"{index + 21:032x}", f"{index + 31:032x}")
                    continuous = index >= 3
                    if already_shared and continuous:
                        start_id = shots[-1].segments[-1].end_keyframe_id
                    shots.append(
                        KeyframeShotInput(
                            shot_id,
                            "近景。",
                            "缓慢拉开后绕至肩后。",
                            "倾听无线电。",
                            (),
                            (
                                KeyframeSegmentInput(
                                    segment_id,
                                    "倾听。",
                                    start_keyframe_id=start_id,
                                    end_keyframe_id=end_id,
                                ),
                            ),
                        )
                    )
                    output.append(
                        {
                            "start_environment_view_id": None,
                            "shot_id": shot_id,
                            "continues_from_previous_shot": already_shared and continuous,
                            "start_prompt_text": "无线电亮灯。",
                            "start_visible_character_ids": [],
                            "start_character_references": [],
                            "start_environment_mode": None,
                            "start_environment_none_reason": None,
                            "segments": [
                                {
                                    "end_environment_view_id": None,
                                    "segment_id": segment_id,
                                    "frame_strategy": "start",
                                    "end_prompt_text": "无线电亮灯。",
                                    "end_visible_character_ids": [],
                                    "end_character_references": [],
                                    "end_environment_mode": None,
                                    "end_environment_none_reason": None,
                                }
                            ],
                        }
                    )
                scene = KeyframeSceneInput("f" * 32, "空站呼叫", "控制室。", tuple(shots))
                boundaries = tuple(
                    (shots[i].segments[0].id, shots[i + 1].segments[0].id) for i in (2, 3)
                )
                adapter = json.dumps({"shots": output})
                proposal = compile_fixture(
                    adapter,
                    scenes=(scene,),
                    user_message="规划一下关键帧；本轮采用上一轮 Shot 3–5 一镜到底建议。",
                    required_shared_boundaries=() if already_shared else boundaries,
                )
                self.assertIsInstance(proposal, KeyframeOperationsProposal)
                activations = {
                    item.segment_id: item
                    for item in proposal.operations
                    if isinstance(item, SetKeyframeActivation)
                }
                for index, shot in enumerate(shots):
                    self.assertEqual(activations[shot.segments[0].id].end_enabled, index in (2, 3))
                    self.assertTrue(activations[shot.segments[0].id].start_enabled)
                shares = tuple(
                    (item.left_segment_id, item.right_segment_id)
                    for item in proposal.operations
                    if isinstance(item, ShareKeyframeBoundary)
                )
                self.assertEqual(shares, () if already_shared else boundaries)

    async def test_pure_rejects_shared_start_that_differs_from_previous_end(self) -> None:
        first_shot_id = "1" * 32
        second_shot_id = "2" * 32
        first_segment_id = "3" * 32
        second_segment_id = "4" * 32
        adapter = f'''{{"shots":[
              {{"shot_id":"{first_shot_id}",
               "continues_from_previous_shot":false,
               "start_prompt_text":"空桌面。","start_visible_character_ids":[],"start_character_references":[],
               "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
               "segments":[{{"segment_id":"{first_segment_id}",
                 "frame_strategy":"both",
                 "end_prompt_text":"文件落在桌面。","end_visible_character_ids":[],"end_character_references":[],
                 "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}},
              {{"shot_id":"{second_shot_id}",
               "continues_from_previous_shot":true,
               "start_prompt_text":"文件已经被拿走。","start_visible_character_ids":[],"start_character_references":[],
               "start_environment_mode":null,"start_environment_view_id":null,"start_environment_none_reason":null,
               "segments":[{{"segment_id":"{second_segment_id}",
                 "frame_strategy":"both",
                 "end_prompt_text":"空桌面。","end_visible_character_ids":[],"end_character_references":[],
                 "end_environment_mode":null,"end_environment_view_id":null,"end_environment_none_reason":null}}]}}
            ]}}'''
        scene = KeyframeSceneInput(
            "6" * 32,
            "办公室",
            "安静的办公室。",
            (
                KeyframeShotInput(
                    first_shot_id,
                    "特写。",
                    "固定。",
                    "文件落下。",
                    (),
                    (KeyframeSegmentInput(first_segment_id, "文件落下。"),),
                ),
                KeyframeShotInput(
                    second_shot_id,
                    "特写。",
                    "固定。",
                    "文件被拿走。",
                    (),
                    (KeyframeSegmentInput(second_segment_id, "文件被拿走。"),),
                ),
            ),
        )
        with self.assertRaisesRegex(ProposalError, "完全一致"):
            compile_fixture(adapter, scenes=(scene,))
