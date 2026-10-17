"""Keyframe 使用地点视图：建帧继承、Planner 默认值、名额优先级与提示词（design D4、D5、§5）。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from conftest import make_service
from structured_director_fixtures import RecordingProvider, add_image_asset
from test_director_commands import _location_project, _script_segment_payload
from test_external_script_proposals import agent, http

from core.director_commands import (
    DirectorCommand,
    DirectorCommandRegistry,
    LocationViewSelection,
    UpdateKeyframeFields,
    parse_location_operations_patch,
)
from core.director_proposals import (
    KeyframePlanProposal,
    KeyframeSceneInput,
    KeyframeSegmentInput,
    KeyframeSegmentProposal,
    KeyframeShotInput,
    KeyframeShotProposal,
)
from core.director_proposals.keyframe_codec import compile_keyframe_proposal, parse_keyframe_plan
from core.model_providers.boundary import GenerationPhase
from core.model_providers.qwen_image import MANIFEST as QWEN_MANIFEST
from core.structured_director import StructuredDirectorStore
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.image_prompt_style import ImagePromptStyle
from core.structured_director.keyframe_mutations import _apply_keyframe_operations
from core.structured_director.keyframe_requests import (
    _keyframe_effective_prompt,
    _keyframe_generation_inputs,
)
from core.structured_director.models import (
    MAX_IMAGE_INPUTS,
    CharacterCard,
    CharacterLook,
    GenerationOperation,
    KeyframeEnvironmentMode,
)
from core.structured_director.planning_inputs import keyframe_inputs
from core.structured_director.reads.read_tools import execute_project_read

VIEW = "7" * 32


async def _unlocked(directory):
    """两个 Scene 各绑定一个已选图视图（Shot 全部绑定），然后解锁视觉生产。"""
    store, service, document, _route = await _location_project(directory)
    document = service.snapshot_required()
    document = await service.unlock_visual_production(expected_revision=document.revision)
    return store, service, document


def _frames(document):
    return {item.id: item for item in document.keyframe_plan.keyframes}


def _binding(document, segment_id):
    return next(x for x in document.keyframe_plan.segments if x.segment_id == segment_id)


def _bind_shot(store, shot_id, view_id):
    patch = parse_location_operations_patch(
        {
            "scope": {"location_ids": [], "scene_ids": [], "shot_ids": [shot_id]},
            "operations": [{"op": "bind_shot", "shot_id": shot_id, "view_id": view_id}],
        }
    )
    store.apply_location_operations(
        patch, expected_revision=store.read().revision, command_id=uuid4().hex
    )
    return store.read()


def _insert_segment(store, document, shot, character_id):
    scene = next(s for s in document.director_script.scenes if shot in s.shots)
    return (
        DirectorCommandRegistry(store)
        .execute(
            DirectorCommand(
                "script.apply_operations",
                document.revision,
                f"insert-{uuid4().hex}",
                {
                    "scope": {"scene_ids": [scene.id]},
                    "operations": [
                        {
                            "op": "insert_segment",
                            "shot_id": shot.id,
                            "after_segment_id": shot.segments[-1].id,
                            "segment": _script_segment_payload(
                                character_id, "新增动作。", boundary=True
                            ),
                        }
                    ],
                },
            )
        )
        .document
    )


# --- 建帧继承与改绑不回写 ---


def test_unlock_inherits_shot_view_as_explicit_reference(tmp_path):
    _store, _service, document = asyncio.run(_unlocked(tmp_path))
    frames = _frames(document)
    for scene in document.director_script.scenes:
        for shot in scene.shots:
            assert shot.view_id is not None
            for segment in shot.segments:
                binding = _binding(document, segment.id)
                for frame_id in (binding.start_keyframe_id, binding.end_keyframe_id):
                    frame = frames[frame_id]
                    assert frame.environment_mode is KeyframeEnvironmentMode.REFERENCE
                    assert frame.environment_view_id == shot.view_id
                    assert frame.environment_none_reason is None


def test_unlock_without_shot_view_writes_none_without_reason(tmp_path):
    async def run():
        store, service, document, _route = await _location_project(tmp_path)
        shot = document.director_script.scenes[0].shots[0]
        _bind_shot(store, shot.id, None)
        document = service.snapshot_required()
        document = await service.unlock_visual_production(expected_revision=document.revision)
        return document, shot

    document, shot = asyncio.run(run())
    binding = _binding(document, shot.segments[0].id)
    for frame_id in (binding.start_keyframe_id, binding.end_keyframe_id):
        frame = _frames(document)[frame_id]
        assert frame.environment_mode is KeyframeEnvironmentMode.NONE
        assert frame.environment_view_id is None
        assert frame.environment_none_reason is None


def test_rebinding_keeps_frames_and_rebuild_gives_new_segments_current_default(tmp_path):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    first_scene, second_scene = document.director_script.scenes
    unbound, bound = first_scene.shots[0], second_scene.shots[0]
    old_view = unbound.view_id
    before = _frames(document)
    old_binding = _binding(document, unbound.segments[0].id)

    # Shot 改绑不改写已建立的帧，级联因此只看帧上显式的视图 ID。
    document = _bind_shot(store, unbound.id, None)
    assert _frames(document) == before

    character_id = document.reference_library.characters[0].id
    unbound = document.director_script.scenes[0].shots[0]
    document = _insert_segment(store, document, unbound, character_id)
    document = _insert_segment(
        store, document, document.director_script.scenes[1].shots[0], character_id
    )
    frames = _frames(document)
    # 已有帧在重建中保持原值。
    assert frames[old_binding.start_keyframe_id] == before[old_binding.start_keyframe_id]
    assert frames[old_binding.start_keyframe_id].environment_view_id == old_view
    # 新 Segment 按所属 Shot 当前绑定取默认值。
    unbound_new = document.director_script.scenes[0].shots[0].segments[-1]
    bound_new = document.director_script.scenes[1].shots[0].segments[-1]
    for segment, mode, view_id in (
        (unbound_new, KeyframeEnvironmentMode.NONE, None),
        (bound_new, KeyframeEnvironmentMode.REFERENCE, bound.view_id),
    ):
        binding = _binding(document, segment.id)
        for frame_id in (binding.start_keyframe_id, binding.end_keyframe_id):
            assert frame_id not in before
            assert (frames[frame_id].environment_mode, frames[frame_id].environment_view_id) == (
                mode,
                view_id,
            )
    assert (
        frames[_binding(document, unbound_new.id).start_keyframe_id].environment_none_reason is None
    )


# --- Planner proposal：未声明继承、none 理由可选、锁定节点不改写 ---


def _scene(view_id, *, locked=False):
    return KeyframeSceneInput(
        "5" * 32,
        "客厅",
        "室内。",
        (
            KeyframeShotInput(
                "1" * 32,
                "中景。",
                "固定。",
                "角色坐下。",
                (),
                (
                    KeyframeSegmentInput(
                        "2" * 32,
                        "角色坐下。",
                        start_keyframe_id="3" * 32,
                        end_keyframe_id="4" * 32,
                        start_locked=locked,
                    ),
                ),
                view_id=view_id,
            ),
        ),
        available_view_ids=(VIEW, "8" * 32),
    )


def _proposal(**environment):
    return KeyframePlanProposal(
        (
            KeyframeShotProposal(
                "1" * 32,
                False,
                "角色站在沙发旁。",
                (),
                (KeyframeSegmentProposal("2" * 32, "both", "角色坐在沙发上。", (), **environment),),
            ),
        )
    )


def _field_updates(operations):
    return {
        item.keyframe_id: (
            item.environment_mode,
            item.environment_view_id,
            item.environment_none_reason,
        )
        for item in operations
        if isinstance(item, UpdateKeyframeFields)
    }


@pytest.mark.parametrize(
    ("shot_view", "expected"),
    [
        (VIEW, ("reference", VIEW, None)),
        (None, ("none", None, None)),
    ],
)
def test_planner_omitted_environment_inherits_shot_view(shot_view, expected):
    _proposal_out, operations = compile_keyframe_proposal(_proposal(), (_scene(shot_view),))
    # 继承与 blank_keyframe 同一规则：Shot 无视图时 none、无理由。
    assert _field_updates(operations) == {"3" * 32: expected, "4" * 32: expected}


def test_planner_explicit_environment_overrides_inheritance():
    proposal = _proposal(
        end_environment_mode="reference",
        end_environment_view_id="8" * 32,
    )
    _out, operations = compile_keyframe_proposal(proposal, (_scene(VIEW),))
    updates = _field_updates(operations)
    assert updates["4" * 32] == ("reference", "8" * 32, None)
    assert updates["3" * 32] == ("reference", VIEW, None)


def test_planner_explicit_none_reason_is_optional():
    for reason in (None, "", "   "):
        proposal = _proposal(end_environment_mode="none", end_environment_none_reason=reason)
        _out, operations = compile_keyframe_proposal(proposal, (_scene(VIEW),))
        assert _field_updates(operations)["4" * 32] == ("none", None, None)
    with pytest.raises(ValueError, match="不能超过 500 字符"):
        _proposal(end_environment_mode="none", end_environment_none_reason="理" * 501)
    with pytest.raises(ValueError, match="不能单独给出视图 ID"):
        _proposal(end_environment_view_id=VIEW)
    proposal = _proposal(end_environment_mode="none", end_environment_none_reason="特写只拍手部")
    _out, operations = compile_keyframe_proposal(proposal, (_scene(VIEW),))
    assert _field_updates(operations)["4" * 32] == ("none", None, "特写只拍手部")


def test_planner_wire_schema_accepts_none_without_reason():
    def raw(mode, reason):
        return (
            '{"shots":[{"shot_id":"' + "1" * 32 + '","continues_from_previous_shot":false,'
            '"start_prompt_text":"站着。","start_visible_character_ids":[],'
            '"start_character_references":[],"start_environment_mode":null,'
            '"start_environment_view_id":null,"start_environment_none_reason":null,'
            '"segments":[{"segment_id":"' + "2" * 32 + '","frame_strategy":"both",'
            '"end_prompt_text":"坐下。","end_visible_character_ids":[],'
            f'"end_character_references":[],"end_environment_mode":{mode},'
            f'"end_environment_view_id":null,"end_environment_none_reason":{reason}}}]}}]}}'
        )

    parsed = parse_keyframe_plan(raw("null", "null"))
    assert parsed.shots[0].segments[0].end_environment_mode is None
    assert parse_keyframe_plan(raw('"none"', '"空镜"')).shots[0].segments[0].end_environment_mode
    for reason in ("null", '""'):
        segment = parse_keyframe_plan(raw('"none"', reason)).shots[0].segments[0]
        assert (segment.end_environment_mode, segment.end_environment_none_reason) == ("none", None)


def test_planner_keeps_environment_of_locked_frames():
    _out, operations = compile_keyframe_proposal(
        _proposal(end_environment_mode="none", end_environment_none_reason="特写"),
        (_scene(VIEW, locked=True),),
    )
    assert _field_updates(operations) == {}


def test_planner_proposal_end_to_end_inherits_none_without_reason(tmp_path):
    async def run():
        store, service, document = await _unlocked(tmp_path)
        shot = document.director_script.scenes[0].shots[0]
        _bind_shot(store, shot.id, None)
        return store.read(), shot

    document, shot = asyncio.run(run())
    proposal = KeyframePlanProposal(
        (
            KeyframeShotProposal(
                shot.id,
                False,
                "甲抬头。",
                (),
                (KeyframeSegmentProposal(shot.segments[0].id, "both", "甲看向门口。", ()),),
            ),
        )
    )
    scenes, _targets, _ = keyframe_inputs(document, (shot.id,))
    _out, operations = compile_keyframe_proposal(proposal, scenes)
    execution = _apply_keyframe_operations(document, operations).document
    binding = _binding(execution, shot.segments[0].id)
    for frame_id in (binding.start_keyframe_id, binding.end_keyframe_id):
        frame = _frames(execution)[frame_id]
        assert frame.environment_mode is KeyframeEnvironmentMode.NONE
        assert frame.environment_none_reason is None


# --- 生成：未选图拒绝、名额优先级与超额拒绝、提示词文案 ---


def _frame_with_inputs(store, document, *, mode, characters=1, aux=0, predecessor=True):
    """首帧已选图作为前置帧；尾帧按 mode 使用 Scene 1 的视图，并带角色参考与辅助图。"""
    shot = document.director_script.scenes[0].shots[0]
    segment = shot.segments[0]
    binding = _binding(document, segment.id)
    image_ids = [add_image_asset(store, width=1600, height=900) for _ in range(characters)]
    aux_ids = [add_image_asset(store, width=1600, height=900) for _ in range(aux)]
    predecessor_id = add_image_asset(store, width=1600, height=900)
    document = store.read()
    # 每个可见角色一套造型、一张造型图；多张角色图意味着多个同框角色。
    cards = tuple(
        CharacterCard(
            f"{index + 1:x}" * 32,
            f"角色{index}",
            "外形",
            (
                CharacterLook(
                    f"{index + 10:x}".rjust(32, "e"), f"服装{index}", "外观", "场合", item
                ),
            ),
        )
        for index, item in enumerate(image_ids)
    )
    library = replace(
        document.reference_library,
        characters=(*document.reference_library.characters, *cards),
    )
    keyframes = tuple(
        replace(item, selected_asset_id=predecessor_id)
        if item.id == binding.start_keyframe_id
        else replace(
            item,
            prompt_text="甲坐下。",
            visible_character_ids=tuple(card.id for card in cards),
            environment_mode=mode,
            environment_view_id=None if mode is KeyframeEnvironmentMode.NONE else shot.view_id,
            environment_none_reason=("特写" if mode is KeyframeEnvironmentMode.NONE else None),
        )
        if item.id == binding.end_keyframe_id
        else item
        for item in document.keyframe_plan.keyframes
    )
    segments = tuple(
        replace(
            item, start_enabled=predecessor, end_enabled=True, reference_asset_ids=tuple(aux_ids)
        )
        if item.segment_id == segment.id
        else item
        for item in document.keyframe_plan.segments
    )
    document = replace(
        document,
        reference_library=library,
        keyframe_plan=replace(document.keyframe_plan, keyframes=keyframes, segments=segments),
    )
    view = document.location_library.view_owner(shot.view_id)[1]
    return (
        document,
        binding.end_keyframe_id,
        {
            "view": view.selected_asset_id,
            "characters": image_ids,
            "predecessor": predecessor_id,
            "aux": aux_ids,
        },
    )


def test_edit_view_is_source_then_characters_predecessor_aux(tmp_path):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    document, frame_id, ids = _frame_with_inputs(
        store, document, mode=KeyframeEnvironmentMode.EDIT, characters=2, aux=1
    )
    inputs = _keyframe_generation_inputs(document, frame_id)
    assert inputs.operation is GenerationOperation.EDIT
    assert inputs.asset_ids == (ids["view"], *ids["characters"], ids["predecessor"], *ids["aux"])


def test_reference_view_keeps_predecessor_as_source(tmp_path):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    document, frame_id, ids = _frame_with_inputs(
        store, document, mode=KeyframeEnvironmentMode.REFERENCE
    )
    inputs = _keyframe_generation_inputs(document, frame_id)
    assert inputs.operation is GenerationOperation.EDIT
    assert inputs.asset_ids == (ids["predecessor"], ids["view"], *ids["characters"])


def test_over_quota_rejects_and_lists_squeezed_inputs_in_priority_order(tmp_path):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    document, frame_id, ids = _frame_with_inputs(
        store, document, mode=KeyframeEnvironmentMode.EDIT, characters=4, aux=2
    )
    names = {item.id: item.display_name for item in document.assets}
    with pytest.raises(ValueError) as error:
        _keyframe_generation_inputs(document, frame_id)
    message = str(error.value)
    assert f"合计 8 张输入图，超过上限 {MAX_IMAGE_INPUTS} 张" in message
    # 视图 + 4 张角色参考占满 5 个名额；前置帧与两张辅助图依次被挤掉。
    squeezed = (
        f"会被挤掉的输入：「{names[ids['predecessor']]}」（前置帧）、"
        f"「{names[ids['aux'][0]]}」（辅助参考）、「{names[ids['aux'][1]]}」（辅助参考）。"
    )
    assert squeezed in message
    assert names[ids["view"]] not in message
    assert message.startswith("Scene 1 Shot 1 Segment 1 尾帧的地点视图、角色参考、前置帧与辅助参考")


def test_unselected_view_allows_planning_but_rejects_generation(tmp_path):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    location = document.location_library.locations[0]
    view = location.views[0]
    patch = parse_location_operations_patch(
        {
            "scope": {"location_ids": [location.id], "scene_ids": [], "shot_ids": []},
            "operations": [{"op": "clear_view_selection", "view_id": view.id}],
        }
    )
    store.apply_location_operations(patch, expected_revision=document.revision, command_id="c")
    document = store.read()
    shot = document.director_script.scenes[0].shots[0]
    binding = _binding(document, shot.segments[0].id)
    # 规划（写入引用未选图视图的字段）允许。
    document = (
        DirectorCommandRegistry(store)
        .execute(
            DirectorCommand(
                "keyframe.apply_operations",
                document.revision,
                "plan-unselected",
                {
                    "operations": [
                        {
                            "op": "set_activation",
                            "segment_id": shot.segments[0].id,
                            "start_enabled": True,
                            "end_enabled": False,
                        },
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": binding.start_keyframe_id,
                            "fields": {
                                "prompt_text": "甲抬头。",
                                "environment_mode": "edit",
                                "environment_view_id": view.id,
                                "environment_none_reason": None,
                            },
                        },
                    ]
                },
            )
        )
        .document
    )
    with pytest.raises(ValueError, match="请先选择视图图片，或把本帧改为 none"):
        _keyframe_generation_inputs(document, binding.start_keyframe_id)


@pytest.mark.parametrize("qwen", [False, True])
def test_prompt_text_for_edit_and_reference(tmp_path, qwen):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    # Qwen 约定：输入图写 <imageN>，画幅由画布保证、不写画幅句；默认写法写一次画幅。
    style = ImagePromptStyle(QWEN_MANIFEST, "qwen_image.edit") if qwen else ImagePromptStyle()
    for mode, expected, absent in (
        (
            KeyframeEnvironmentMode.EDIT,
            "同一地点该机位的空环境，这是本次图片编辑的底图；保持其中陈设、材质与光线不变，"
            "只加入本帧的人物与动作。",
            "仅作空间与环境参考",
        ),
        (
            KeyframeEnvironmentMode.REFERENCE,
            "同一地点的空间参考；只参考固定陈设的方位关系、空间布局、材质与主光方向；"
            "不照搬该图的机位、视角与构图，按本帧画面目标重新构图，"
            "人物与环境须融为同一光照与透视。",
            "这是本次图片编辑的底图",
        ),
    ):
        current, frame_id, _ids = _frame_with_inputs(store, document, mode=mode)
        inputs = _keyframe_generation_inputs(current, frame_id)
        frame = _frames(current)[frame_id]
        prompt = _keyframe_effective_prompt(current, frame, inputs, style)
        first_label = "<image1>" if qwen else "第 1 张输入图"
        assert prompt.startswith(f"输入图对应关系（按实际传入顺序，禁止混淆身份）：\n{first_label}")
        assert expected in prompt
        assert absent not in prompt
        assert prompt.count("16:9") == (0 if qwen else 1)
        if mode is KeyframeEnvironmentMode.REFERENCE:
            view_description = next(
                description for _name, description in inputs.mapping if "空间参考" in description
            )
            assert "不照搬" in view_description
            assert "空间" in view_description
            assert "底图" not in view_description


# --- 工作集 ---


def test_keyframe_workset_exposes_shot_view_and_location_views(tmp_path):
    _store, _service, document = asyncio.run(_unlocked(tmp_path))
    scene = document.director_script.scenes[0]
    facts = execute_project_read(
        document,
        "project.get_workset",
        {"capability": "keyframe", "scope": {"scene_ids": [scene.id]}},
    )["core_facts"]
    assert facts["scenes"][0]["shots"][0]["view_id"] == scene.shots[0].view_id
    assert "location_library" not in facts
    expected = []
    for location in document.location_library.locations:
        for view in location.views:
            expected.append(
                {
                    "view_id": view.id,
                    "name": view.name,
                    "purpose": view.purpose,
                    "location_id": location.id,
                    "location_name": location.name,
                    "location_kind": location.kind.value,
                    "state_id": None,
                    "state_name": None,
                    "selected_asset_id": view.selected_asset_id,
                }
            )
    assert facts["location_views"] == expected
    assert all(item["selected_asset_id"] is not None for item in expected)


# --- 批次：视图未选图按未满足依赖等待 ---


def test_batch_defers_frame_with_unselected_view_and_continues_after_selection(tmp_path):
    async def run():
        store, _service, document = await _unlocked(tmp_path)
        scene_a, scene_b = document.director_script.scenes[:2]
        frame_ids = []
        operations = []
        for scene in (scene_a, scene_b):
            segment = scene.shots[0].segments[0]
            frame_id = _binding(document, segment.id).start_keyframe_id
            frame_ids.append(frame_id)
            operations += [
                {
                    "op": "set_activation",
                    "segment_id": segment.id,
                    "start_enabled": True,
                    "end_enabled": False,
                },
                {
                    "op": "update_frame_fields",
                    "keyframe_id": frame_id,
                    "fields": {"prompt_text": f"{scene.title}的人物抬头。"},
                },
            ]
        DirectorCommandRegistry(store).execute(
            DirectorCommand(
                "keyframe.apply_operations",
                store.read().revision,
                "plan-batch",
                {"operations": operations},
            )
        )
        waiting_frame, ready_frame = frame_ids
        location, view = store.read().location_library.view_owner(scene_a.shots[0].view_id)
        asset_id = view.selected_asset_id
        patch = parse_location_operations_patch(
            {
                "scope": {"location_ids": [location.id], "scene_ids": [], "shot_ids": []},
                "operations": [{"op": "clear_view_selection", "view_id": view.id}],
            }
        )
        store.apply_location_operations(
            patch, expected_revision=store.read().revision, command_id=uuid4().hex
        )
        # 单帧入口与批次共用同一判定：单帧直接拒绝。
        with pytest.raises(ValueError, match="请先选择视图图片，或把本帧改为 none"):
            _keyframe_generation_inputs(store.read(), waiting_frame)

        provider = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nkf")

        def service():
            return make_service(
                StructuredDirectorStore(store.path.parent, store.read().project_id),
                image_provider=provider,
            )

        async def call(name, key, arguments):
            command = DirectorCommand(name, store.read().revision, key, arguments)
            result = await http(service(), agent(store.read(), command), command)
            assert result.status == 200, result.body
            return result.body

        first = await call("keyframe.generate_batch", "view-batch", {"target_ids": frame_ids})
        assert len(provider.requests) == 1
        data = first["data"]
        assert data["submitted_target_ids"] == [ready_frame]
        assert data["deferred_target_ids"] == [waiting_frame]
        reply = "\n".join(data["messages"])
        assert f"等待地点「{location.name}」视图「{view.name}」选图" in reply
        assert "请明确说“继续生成关键帧”" in reply
        targets = {item["target_id"]: item for item in data["batch_observation"]["targets"]}
        assert targets[waiting_frame]["status"] == "dependency_blocked"
        assert targets[waiting_frame]["dependency_kind"] == "location_view_unselected"
        assert targets[waiting_frame]["dependency_target_id"] == view.id
        assert targets[ready_frame]["dependency_kind"] is None

        observer = service()
        for generation in store.read().generations:
            if generation.phase.value == "queued":
                provider.observations = [GenerationPhase.SUCCEEDED]
                await observer._generation_observer.refresh_generation(generation.id)
        lookup = DirectorCommand(
            "project.get_request", store.read().revision, "view-read", {"request_key": "view-batch"}
        )
        observed = await http(service(), agent(store.read(), lookup), lookup)
        assert observed.body["data"]["result"]["batch_observation"]["phase"] == (
            "blocked_on_dependency"
        )

        # 选图不会自动推进批次；用户再次明确要求继续后才提交剩余帧。
        store.select_location_view(
            LocationViewSelection(view.id, asset_id),
            expected_revision=store.read().revision,
            command_id=uuid4().hex,
        )
        assert len(provider.requests) == 1
        lookup = DirectorCommand(
            "project.get_request",
            store.read().revision,
            "view-read-2",
            {"request_key": "view-batch"},
        )
        observed = await http(service(), agent(store.read(), lookup), lookup)
        assert observed.body["data"]["result"]["batch_observation"]["phase"] == (
            "awaiting_explicit_continue"
        )
        continuation = observed.body["workflow"]["required_next_actions"][0]
        assert continuation["action"] == "keyframe.continue_batch"
        resumed = await call(
            "keyframe.continue_batch", "view-continue", {"run_id": data["batch_id"]}
        )
        assert len(provider.requests) == 2
        assert resumed["data"]["submitted_target_ids"] == [waiting_frame]
        assert resumed["data"]["deferred_target_ids"] == []

    asyncio.run(run())


# --- 人工入口与 keyframe.apply_operations：显式 none 理由可选；预览附件带角色与用途 ---


def _activate_start(store, segment_id):
    DirectorCommandRegistry(store).execute(
        DirectorCommand(
            "keyframe.apply_operations",
            store.read().revision,
            f"activate-{uuid4().hex}",
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
    )
    return store.read()


def _http_body(document, keyframe_id, segment_id, *, mode, view_id, reason):
    frame = _frames(document)[keyframe_id]
    return {
        "expected_revision": document.revision,
        "segment_id": segment_id,
        "prompt_text": frame.prompt_text or "甲抬头。",
        "visible_character_ids": list(frame.visible_character_ids),
        "character_references": [],
        "reference_asset_ids": [],
        "environment_mode": mode,
        "environment_view_id": view_id,
        "environment_none_reason": reason,
    }


def test_apply_operations_explicit_none_reason_is_optional(tmp_path):
    store, _service, document = asyncio.run(_unlocked(tmp_path))
    segment = document.director_script.scenes[0].shots[0].segments[0]
    frame_id = _binding(document, segment.id).start_keyframe_id

    def update(key, reason):
        return DirectorCommandRegistry(store).execute(
            DirectorCommand(
                "keyframe.apply_operations",
                store.read().revision,
                key,
                {
                    "operations": [
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": frame_id,
                            "fields": {
                                "environment_mode": "none",
                                "environment_view_id": None,
                                "environment_none_reason": reason,
                            },
                        }
                    ]
                },
            )
        )

    for key, reason in (("none-without-reason", None), ("none-blank-reason", "  ")):
        frame = _frames(update(key, reason).document)[frame_id]
        assert frame.environment_mode is KeyframeEnvironmentMode.NONE
        assert frame.environment_none_reason is None
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="不能超过 500 字符"):
        update("none-long-reason", "理" * 501)
    assert store.path.read_bytes() == before
    updated = update("none-with-reason", " 黑场过渡 ").document
    assert _frames(updated)[frame_id].environment_none_reason == "黑场过渡"


def test_http_save_and_preview_accept_none_without_reason(tmp_path):
    async def run():
        store, service, document = await _unlocked(tmp_path)
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        segment = document.director_script.scenes[0].shots[0].segments[0]
        frame_id = _binding(document, segment.id).start_keyframe_id
        _activate_start(store, segment.id)
        path = f"/structured-director/keyframes/{frame_id}"

        def body(**environment):
            return json.dumps(
                _http_body(store.read(), frame_id, segment.id, **environment)
            ).encode()

        preview = await api.handle(
            "POST", f"{path}/preview", body(mode="none", view_id=None, reason=None)
        )
        assert preview.status == 200, preview.body
        for reason in (None, ""):
            saved = await api.handle("PUT", path, body(mode="none", view_id=None, reason=reason))
            assert saved.status == 200, saved.body
            frame = _frames(store.read())[frame_id]
            assert frame.environment_mode is KeyframeEnvironmentMode.NONE
            assert frame.environment_none_reason is None
        saved = await api.handle("PUT", path, body(mode="none", view_id=None, reason="天空空镜"))
        assert saved.status == 200, saved.body
        frame = _frames(store.read())[frame_id]
        assert frame.environment_none_reason == "天空空镜"

    asyncio.run(run())


def test_http_preview_attachments_carry_roles_and_purposes(tmp_path):
    async def run():
        store, service, document = await _unlocked(tmp_path)
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        shot = document.director_script.scenes[0].shots[0]
        segment = shot.segments[0]
        frame_id = _binding(document, segment.id).start_keyframe_id
        document = _activate_start(store, segment.id)
        preview = await api.handle(
            "POST",
            f"/structured-director/keyframes/{frame_id}/preview",
            json.dumps(
                _http_body(
                    document, frame_id, segment.id, mode="edit", view_id=shot.view_id, reason=None
                )
            ).encode(),
        )
        assert preview.status == 200, preview.body
        location, view = document.location_library.view_owner(shot.view_id)
        first = preview.body["attachments"][0]
        assert first["asset_id"] == view.selected_asset_id
        assert first["role"] == "source_image"
        assert first["input_roles"] == ["地点视图"]
        assert first["purpose"].startswith(
            f"地点「{location.name}」的视图「{view.name}」：同一地点该机位的空环境"
        )
        reference = await api.handle(
            "POST",
            f"/structured-director/keyframes/{frame_id}/preview",
            json.dumps(
                _http_body(
                    document,
                    frame_id,
                    segment.id,
                    mode="reference",
                    view_id=shot.view_id,
                    reason=None,
                )
            ).encode(),
        )
        assert reference.status == 200, reference.body
        assert [item["role"] for item in reference.body["attachments"]][:1] == ["reference_image"]
        assert reference.body["attachments"][0]["input_roles"] == ["地点视图"]

    asyncio.run(run())
