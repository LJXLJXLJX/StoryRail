"""Keyframe 按帧选择角色造型：选择、默认规则、未选图阻塞、剪除、失效与 Agent 契约。"""

import asyncio
from dataclasses import replace

import pytest
from test_director_commands import _ScriptCompiler, _visual_project

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals import (
    KeyframeCharacterInput,
    KeyframeCharacterLookInput,
    KeyframeCharacterReferenceProposal,
    KeyframePlanProposal,
    KeyframeSceneInput,
    KeyframeSegmentInput,
    KeyframeSegmentProposal,
    KeyframeShotInput,
)
from core.director_proposals.keyframe_codec import compile_keyframe_proposal
from core.director_proposals.schema_gen import ProposalError
from core.structured_director.keyframe_requests import _keyframe_generation_inputs
from core.structured_director.models import (
    CharacterLook,
    ImageAssetCategory,
    Keyframe,
    KeyframeCharacterReference,
    KeyframeEnvironmentMode,
)
from core.structured_director.reads.read_tools import execute_project_read

_NOTES = ("青年征战军服", "加冕大典华服", "孤岛病榻便服")


class _SharedShotScript(_ScriptCompiler):
    """第一个 Shot 同时出现甲乙，用于多角色同框。"""

    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        scene = proposal.scenes[0]
        characters = kwargs["characters"]
        first = replace(scene.shots[0], visible_character_ids=tuple(item.id for item in characters))
        return replace(proposal, scenes=(replace(scene, shots=(first, *scene.shots[1:])),))


async def _give_looks(service, document, card, names, prefix):
    """给角色卡建造型并为每套导入一张造型图。"""
    looks = tuple(
        CharacterLook(f"{prefix}{index:031x}", name, f"{name}外观", f"{name}时期")
        for index, name in enumerate(names)
    )
    document = await service.update_character(
        replace(card, looks=looks),
        expected_revision=document.revision,
        created_look_ids=frozenset(item.id for item in looks),
    )
    for index, look in enumerate(looks):
        document = await service.import_image_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + f"{prefix}-{index}".encode(),
            category=ImageAssetCategory.CHARACTER_REFERENCE,
            expected_revision=document.revision,
        )
        document = await service.select_look_asset(
            card_id=card.id,
            look_id=look.id,
            asset_id=document.assets[-1].id,
            expected_revision=document.revision,
        )
    return document


async def _project_with_costumes(directory):
    """甲有三套造型、乙有一套造型（都已选定造型图）；第一个 Segment 首帧已激活且只让甲可见。"""
    store, service, document, _route = await _visual_project(
        directory, script_proposer=_SharedShotScript()
    )
    first, second = document.reference_library.characters
    document = await _give_looks(service, document, first, _NOTES, "a")
    document = await _give_looks(service, document, second, ("红外套",), "b")
    first = document.reference_library.characters[0]
    segment = document.director_script.scenes[0].segments[0]
    binding = next(x for x in document.keyframe_plan.segments if x.segment_id == segment.id)
    document = _apply(
        store,
        document,
        [
            {
                "op": "set_activation",
                "segment_id": segment.id,
                "start_enabled": True,
                "end_enabled": False,
            },
            {
                "op": "update_frame_fields",
                "keyframe_id": binding.start_keyframe_id,
                "fields": {"prompt_text": "甲站在窗边。", "visible_character_ids": [first.id]},
            },
        ],
    )
    return store, service, document, binding.start_keyframe_id


def _apply(store, document, operations, key="ops"):
    execution = DirectorCommandRegistry(store).execute(
        DirectorCommand(
            "keyframe.apply_operations",
            document.revision,
            f"{key}-{document.revision}",
            {"operations": operations},
        )
    )
    return execution.document


def _frame(document, keyframe_id) -> Keyframe:
    return next(x for x in document.keyframe_plan.keyframes if x.id == keyframe_id)


def _select(store, document, keyframe_id, character_id, look_id, **fields):
    return _apply(
        store,
        document,
        [
            {
                "op": "update_frame_fields",
                "keyframe_id": keyframe_id,
                "fields": {
                    **fields,
                    "character_references": [{"character_id": character_id, "look_id": look_id}],
                },
            }
        ],
    )


def test_multi_look_character_without_selection_is_blocked(tmp_path):
    _store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    with pytest.raises(ValueError, match="显式选择本帧使用的造型"):
        _keyframe_generation_inputs(document, keyframe_id)


def test_only_selected_look_image_is_submitted_with_its_name(tmp_path):
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    character = document.reference_library.characters[0]
    deathbed = character.looks[2]
    document = _select(store, document, keyframe_id, character.id, deathbed.id)
    inputs = _keyframe_generation_inputs(document, keyframe_id)
    assert inputs.asset_ids == (deathbed.selected_asset_id,)
    assert "孤岛病榻便服" in inputs.lines()[0]
    assert all("青年征战军服" not in line for line in inputs.lines())


def test_null_look_submits_no_character_image(tmp_path):
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    character = document.reference_library.characters[0]
    document = _select(store, document, keyframe_id, character.id, None)
    assert _keyframe_generation_inputs(document, keyframe_id).asset_ids == ()


def test_single_look_is_used_by_default(tmp_path):
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    first, second = document.reference_library.characters
    document = _select(
        store, document, keyframe_id, first.id, None, visible_character_ids=[first.id, second.id]
    )
    inputs = _keyframe_generation_inputs(document, keyframe_id)
    assert inputs.asset_ids == (second.looks[0].selected_asset_id,)


def test_look_without_image_blocks_generation(tmp_path):
    async def run():
        store, service, document, keyframe_id = await _project_with_costumes(tmp_path)
        character = document.reference_library.characters[0]
        bare = CharacterLook("c" * 32, "新造型", "外观", "场合")
        document = await service.update_character(
            replace(character, looks=(*character.looks, bare)),
            expected_revision=document.revision,
            created_look_ids=frozenset({bare.id}),
        )
        document = _select(store, document, keyframe_id, character.id, bare.id)
        with pytest.raises(ValueError, match="尚未选定造型图"):
            _keyframe_generation_inputs(document, keyframe_id)

    asyncio.run(run())


def test_selection_rules_are_validated(tmp_path):
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    first, second = document.reference_library.characters
    with pytest.raises(ValueError, match="该角色当前的造型"):
        _select(store, document, keyframe_id, first.id, second.looks[0].id)
    with pytest.raises(ValueError, match="本帧可见角色"):
        _select(store, document, keyframe_id, second.id, second.looks[0].id)
    with pytest.raises(ValueError, match="只能有一组|只能选择一套"):
        Keyframe(
            "1" * 32,
            "2" * 32,
            None,
            "",
            (first.id,),
            character_references=(
                KeyframeCharacterReference(first.id, None),
                KeyframeCharacterReference(first.id, None),
            ),
        )


def test_look_change_clears_frame_selection_and_hidden_character_is_pruned(tmp_path):
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    first, second = document.reference_library.characters
    document = _select(
        store,
        document,
        keyframe_id,
        first.id,
        first.looks[0].id,
        visible_character_ids=[first.id, second.id],
    )
    plan = document.keyframe_plan
    seeded = replace(
        document,
        revision=document.revision + 1,
        keyframe_plan=replace(
            plan,
            keyframes=tuple(
                replace(x, selected_asset_id=first.looks[0].selected_asset_id)
                if x.id == keyframe_id
                else x
                for x in plan.keyframes
            ),
        ),
    )
    store._atomic_write(seeded)
    # 改选造型改变实际生图输入：与辅助参考一样清除该帧已选图片。
    document = _select(store, seeded, keyframe_id, first.id, None)
    assert _frame(document, keyframe_id).selected_asset_id is None
    document = _apply(
        store,
        document,
        [
            {
                "op": "update_frame_fields",
                "keyframe_id": keyframe_id,
                "fields": {"visible_character_ids": [second.id]},
            }
        ],
    )
    assert _frame(document, keyframe_id).character_references == ()


def test_deleting_look_prunes_frame_selection_and_reselecting_image_keeps_it(tmp_path):
    async def run():
        store, service, document, keyframe_id = await _project_with_costumes(tmp_path)
        character = document.reference_library.characters[0]
        kept, removed = character.looks[0], character.looks[1]
        document = _select(store, document, keyframe_id, character.id, kept.id)
        document = await service.import_image_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\nnew-image",
            category=ImageAssetCategory.CHARACTER_REFERENCE,
            expected_revision=document.revision,
        )
        document = await service.select_look_asset(
            card_id=character.id,
            look_id=kept.id,
            asset_id=document.assets[-1].id,
            expected_revision=document.revision,
        )
        # Keyframe 引用造型而不是图片：改选造型图不需要改写选择。
        assert _frame(document, keyframe_id).character_references == (
            KeyframeCharacterReference(character.id, kept.id),
        )
        assert _keyframe_generation_inputs(document, keyframe_id).asset_ids == (
            document.assets[-1].id,
        )
        document = _select(store, document, keyframe_id, character.id, removed.id)
        character = document.reference_library.characters[0]
        document = await service.update_character(
            replace(character, looks=tuple(x for x in character.looks if x.id != removed.id)),
            expected_revision=document.revision,
        )
        # 造型被删时回到默认规则，而不是变成“显式不提交”。
        assert _frame(document, keyframe_id).character_references == ()
        assert store.read() == document

    asyncio.run(run())


def test_keyframe_workset_exposes_look_asset_ids_for_media_read(tmp_path):
    _store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    scene = document.director_script.scenes[0]
    result = execute_project_read(
        document,
        "project.get_workset",
        {"capability": "keyframe", "scope": {"scene_ids": [scene.id]}},
    )
    segment = result["core_facts"]["scenes"][0]["segments"][0]
    looks = segment["visible_characters"][0]["looks"]
    assert [item["name"] for item in looks] == list(_NOTES)
    assert looks[0]["usage"] == "青年征战军服时期" and looks[0]["has_image"] is True
    assert looks[0]["selected_asset_id"] == (
        document.reference_library.characters[0].looks[0].selected_asset_id
    )
    selected_asset_id = looks[0]["selected_asset_id"]
    assert any(asset.id == selected_asset_id for asset in document.assets)
    manifest = execute_project_read(
        document,
        "project.get_asset_manifest",
        {"asset_id": selected_asset_id},
    )
    assert manifest["id"] == selected_asset_id
    assert manifest["media_type"] == "image/png"
    saved = result["core_facts"]["saved_keyframe_plan"]["keyframes"]
    assert all("character_references" in item for item in saved)
    script = execute_project_read(
        document,
        "project.get_workset",
        {"capability": "script", "scope": {"project_id": document.project_id}},
    )
    assert script["core_facts"]["characters"][0]["looks"][0] == "青年征战军服：青年征战军服时期"
    assert keyframe_id


def _planner_scene(character_id, look_ids):
    character = KeyframeCharacterInput(
        character_id,
        "甲",
        tuple(KeyframeCharacterLookInput(x, "造型", "场合", "6" * 32) for x in look_ids),
    )
    shot = KeyframeShotInput(
        "2" * 32,
        "中景。",
        "固定。",
        "动作。",
        (character,),
    )
    segment = KeyframeSegmentInput(
        "3" * 32,
        "动作。",
        (shot,),
        start_keyframe_id="4" * 32,
        end_keyframe_id="5" * 32,
        visible_characters=(character,),
    )
    return KeyframeSceneInput("1" * 32, "场景", "室内。", (segment,))


def _planner_proposal(character_id, start_refs, end_refs):
    return KeyframePlanProposal(
        (
            KeyframeSegmentProposal(
                "3" * 32,
                False,
                "both",
                "甲站立。",
                (character_id,),
                "甲坐下。",
                (character_id,),
                start_character_references=start_refs,
                end_character_references=end_refs,
            ),
        )
    )


def test_planner_compiles_selection_and_rejects_foreign_looks():
    character_id, look, other = "a" * 32, "b" * 32, "c" * 32
    scene = _planner_scene(character_id, (look, other))
    chosen = (KeyframeCharacterReferenceProposal(character_id, look),)
    _proposal, operations = compile_keyframe_proposal(
        _planner_proposal(character_id, chosen, ()), (scene,)
    )
    updates = [x for x in operations if hasattr(x, "character_references")]
    start = next(x for x in updates if x.keyframe_id == "4" * 32)
    end = next(x for x in updates if x.keyframe_id == "5" * 32)
    assert [(x.character_id, x.look_id) for x in start.character_references] == [
        (character_id, look)
    ]
    assert end.character_references == ()
    foreign = (KeyframeCharacterReferenceProposal(character_id, "d" * 32),)
    with pytest.raises(ProposalError, match="looks"):
        compile_keyframe_proposal(_planner_proposal(character_id, foreign, ()), (scene,))
    with pytest.raises(ValueError, match="可见角色"):
        KeyframeSegmentProposal(
            "3" * 32,
            False,
            "both",
            "空镜。",
            (),
            "空镜结束。",
            (),
            start_character_references=chosen,
        )


def test_manual_dialog_save_and_preview_use_the_same_selection(tmp_path):
    async def run():
        _store, service, document, keyframe_id = await _project_with_costumes(tmp_path)
        character = document.reference_library.characters[0]
        segment = document.director_script.scenes[0].segments[0]
        chosen = (KeyframeCharacterReference(character.id, character.looks[1].id),)
        preview = await service.preview_keyframe(
            keyframe_id=keyframe_id,
            segment_id=segment.id,
            prompt_text="甲戴冠。",
            visible_character_ids=(character.id,),
            character_references=chosen,
            reference_asset_ids=(),
            environment_mode=KeyframeEnvironmentMode.NONE,
            environment_view_id=None,
            environment_none_reason="Shot 未绑定地点视图",
            expected_revision=document.revision,
        )
        assert [item.id for item in preview.input_assets] == [character.looks[1].selected_asset_id]
        assert "加冕大典华服" in preview.reference_prompt
        with pytest.raises(ValueError, match="该角色当前的造型"):
            await service.preview_keyframe(
                keyframe_id=keyframe_id,
                segment_id=segment.id,
                prompt_text="甲戴冠。",
                visible_character_ids=(character.id,),
                character_references=(KeyframeCharacterReference(character.id, "f" * 32),),
                reference_asset_ids=(),
                environment_mode=KeyframeEnvironmentMode.NONE,
                environment_view_id=None,
                environment_none_reason="Shot 未绑定地点视图",
                expected_revision=document.revision,
            )
        current = _frame(document, keyframe_id)
        document = await service.save_keyframe(
            replace(current, prompt_text="甲戴冠。", character_references=chosen),
            expected_revision=document.revision,
            segment_id=segment.id,
            reference_asset_ids=(),
        )
        assert _frame(document, keyframe_id).character_references == chosen

    asyncio.run(run())
