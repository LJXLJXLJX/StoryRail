"""角色造型（角色图唯一单位）：模型约束、proposal、编辑命令、设定图编译、生成与人类选择。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from proposal_fixture_service import ProposalFixtureService
from structured_director_fixtures import RecordingProposer, create_project
from test_keyframe_character_references import _apply, _project_with_costumes
from test_qwen_image_provider import _qwen_service

from core.application.caller import _AGENT_OPERATIONS
from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals.reference_library_codec import parse_reference_library_proposal
from core.model_providers.codex_image.manifest import MANIFEST as CODEX_MANIFEST
from core.model_providers.qwen_image.manifest import MANIFEST as QWEN_MANIFEST
from core.structured_director.character_look_requests import look_sheet_plan, look_sheet_prompt
from core.structured_director.codec.reference import _parse_character, _serialize_character
from core.structured_director.http_api import StructuredDirectorHttpApi
from core.structured_director.image_prompt_style import ImagePromptStyle
from core.structured_director.keyframe_requests import _keyframe_generation_inputs
from core.structured_director.models import (
    CharacterCard,
    CharacterLook,
    ImageAssetCategory,
    KeyframeCharacterReference,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    transition_generation,
)
from core.structured_director.store import StructuredDirectorStore
from integrations.storyrail_mcp.production_tools import Generate, LookEdit, translate

A, B, C, D = "a" * 32, "b" * 32, "c" * 32, "d" * 32


def _look(look_id=B, name="日常", asset_id=None):
    return CharacterLook(look_id, name, "蓝色外套", "全片日常", asset_id)


def test_card_look_rules() -> None:
    with pytest.raises(ValueError, match="非出镜声音身份不能有造型"):
        CharacterCard(A, "广播", None, voice_description="低沉", looks=(_look(),))
    with pytest.raises(ValueError, match="造型名称不能重复"):
        CharacterCard(A, "甲", "短发", looks=(_look(B), _look(C)))
    with pytest.raises(ValueError, match="最多 8 套"):
        CharacterCard(A, "甲", "短发", looks=tuple(_look(f"{i:032x}", str(i)) for i in range(9)))
    with pytest.raises(ValueError, match="造型 ID 不能重复"):
        ReferenceLibrary(
            (
                CharacterCard(A, "甲", "短发", looks=(_look(B),)),
                CharacterCard(C, "乙", "长发", looks=(_look(B),)),
            )
        )
    card = CharacterCard(A, "甲", "短发", looks=(_look(B, asset_id=D), _look(C, "受伤")))
    assert card.look_asset_ids == (D,)


def test_card_codec_round_trips_looks_with_selected_image() -> None:
    card = CharacterCard(A, "甲", "短发", looks=(_look(asset_id=D),))
    raw = json.loads(json.dumps(_serialize_character(card)))
    assert "reference_images" not in raw
    assert raw["looks"][0] == {
        "id": B,
        "name": "日常",
        "appearance": "蓝色外套",
        "usage": "全片日常",
        "selected_asset_id": D,
    }
    assert _parse_character(raw) == card


def test_reference_proposal_carries_looks_and_rejects_voice_only_looks() -> None:
    proposal = parse_reference_library_proposal(
        json.dumps(
            {
                "characters": [
                    {
                        "name": "甲",
                        "visual_description": "短发",
                        "voice_description": "",
                        "looks": [{"name": "校服", "appearance": "蓝白校服", "usage": "第一幕"}],
                    }
                ],
                "narrator": None,
            }
        )
    )
    assert proposal.characters[0].looks[0].usage == "第一幕"
    with pytest.raises(ValueError):
        parse_reference_library_proposal(
            json.dumps(
                {
                    "characters": [
                        {
                            "name": "广播",
                            "visual_description": None,
                            "voice_description": "低沉",
                            "looks": [{"name": "x", "appearance": "y", "usage": "z"}],
                        }
                    ],
                    "narrator": None,
                }
            )
        )


def _look_ops(store, document, operations, key="looks"):
    return DirectorCommandRegistry(store).execute(
        DirectorCommand(
            "reference.apply_look_operations",
            document.revision,
            f"{key}-{document.revision}",
            {"operations": operations},
        )
    )


def test_look_operations_add_update_and_reject_voice_only(tmp_path) -> None:
    store, _service, document, _keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    card = document.reference_library.characters[0]
    added = _look_ops(
        store,
        document,
        [
            {
                "op": "add_look",
                "character_id": card.id,
                "name": "受伤",
                "appearance": "破损战斗服，左臂绷带",
                "usage": "第三幕战斗之后",
            }
        ],
    )
    look_id = added.receipt.changed_ids[0]
    assert store.read().reference_library.look_owner(look_id)[1].name == "受伤"
    updated = _look_ops(
        store,
        added.document,
        [{"op": "update_look", "look_id": look_id, "fields": {"usage": "第三幕之后全部场景"}}],
    )
    assert updated.document.reference_library.look_owner(look_id)[1].usage == "第三幕之后全部场景"
    noop = _look_ops(
        store,
        updated.document,
        [{"op": "update_look", "look_id": look_id, "fields": {"usage": "第三幕之后全部场景"}}],
    )
    assert noop.receipt.status == "noop"
    voice = CharacterCard(C, "广播", None, voice_description="低沉")
    document = store.read()
    store._atomic_write(
        replace(
            document,
            revision=document.revision + 1,
            reference_library=replace(
                document.reference_library,
                characters=(*document.reference_library.characters, voice),
            ),
        )
    )
    with pytest.raises(ValueError, match="非出镜声音身份"):
        _look_ops(
            store,
            store.read(),
            [
                {
                    "op": "add_look",
                    "character_id": C,
                    "name": "x",
                    "appearance": "y",
                    "usage": "z",
                }
            ],
        )


def test_agent_can_edit_and_generate_looks_but_not_select() -> None:
    assert {"reference.apply_look_operations", "reference.generate_look_sheet"} <= _AGENT_OPERATIONS
    assert not any("select" in name and "look" in name for name in _AGENT_OPERATIONS)


def _project_with_look(tmp_path):
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    card = document.reference_library.characters[0]
    execution = _look_ops(
        store,
        document,
        [
            {
                "op": "add_look",
                "character_id": card.id,
                "name": "日常",
                "appearance": "灰色连帽衫，牛仔裤",
                "usage": "全片日常场景",
            }
        ],
    )
    return store, execution.document, keyframe_id, execution.receipt.changed_ids[0]


def test_sheet_prompt_layout_and_canvas_sentence_follow_plugin_convention(tmp_path) -> None:
    _store, document, _keyframe_id, look_id = _project_with_look(tmp_path)
    identity = document.reference_library.characters[0].looks[0].selected_asset_id
    plan = look_sheet_plan(document, look_id, (identity,))
    qwen = look_sheet_prompt(plan, ImagePromptStyle(QWEN_MANIFEST, "qwen_image.generate"))
    codex = look_sheet_prompt(plan, ImagePromptStyle(CODEX_MANIFEST, "codex_image.generate"))
    for prompt in (qwen, codex):
        assert "输入图对应关系" not in prompt and "身份依据" not in prompt
        assert (
            "浅灰色" in prompt
            and "纯白色（#FFFFFF）" not in prompt
            and "头部的正面特写" in prompt
            and "背面" in prompt
        )
        assert "灰色连帽衫，牛仔裤" in prompt
        assert "全片日常场景" not in prompt
        # 主体描述在版式之前：先确定画什么，版式只约束构图。
        assert prompt.index("主体「") < prompt.index("设定图硬约束")
    assert "4K" not in qwen and "2:1" not in qwen
    assert "4K" in codex and "2:1" in codex


def test_single_layout_constrains_non_human_subjects_by_wording_only(tmp_path) -> None:
    _store, document, _keyframe_id, look_id = _project_with_look(tmp_path)
    card = document.reference_library.characters[0]
    spider = replace(card, visual_description="深褐近黑的大蜘蛛，八足多节")
    document = replace(
        document,
        reference_library=replace(
            document.reference_library,
            characters=(spider, *document.reference_library.characters[1:]),
        ),
    )
    prompt = look_sheet_prompt(look_sheet_plan(document, look_id, ()))
    assert prompt.index("主体「") < prompt.index("设定图硬约束") and "八足多节" in prompt
    assert "不得画成人、人形或拟人化形象" in prompt and "不画巢穴、蛛网" in prompt
    assert "正上方俯视" in prompt
    # 版式不出现只属于人的措辞，避免把生物拉成人形。
    for humanoid in ("站姿", "双臂", "头肩", "妆容", "发型", "五官"):
        assert humanoid not in prompt


def test_human_can_preview_edit_and_submit_full_prompt_and_retry_keeps_it(tmp_path) -> None:
    store, document, _keyframe_id, look_id = _project_with_look(tmp_path)
    service, provider, _registry = _qwen_service(store)
    preview = service.preview_look_sheet(look_id=look_id, identity_asset_ids=())
    assert preview == look_sheet_prompt(
        look_sheet_plan(document, look_id, ()),
        ImagePromptStyle(QWEN_MANIFEST, "qwen_image.generate"),
    )
    edited = preview + "\n额外要求：袖口有补丁。"
    provider.reject = True
    document = asyncio.run(
        service.generate_look_sheet(
            look_id=look_id,
            identity_asset_ids=(),
            prompt_text=f"  {edited}  ",
            expected_revision=document.revision,
        )
    )
    failed = _sheets(document)[0]
    assert failed.prompt_text == edited and provider.requests[0].param("prompt") == edited
    provider.reject = False
    document = asyncio.run(service.retry_generation(failed.id, expected_revision=document.revision))
    assert _sheets(document)[1].prompt_text == edited
    assert provider.requests[1].param("prompt") == edited
    with pytest.raises(ValueError, match="请填写设定图提示词"):
        asyncio.run(
            service.generate_look_sheet(
                look_id=look_id,
                identity_asset_ids=(),
                prompt_text="   ",
                expected_revision=document.revision,
            )
        )


@pytest.mark.parametrize(
    ("identity", "message"),
    [(("e" * 32,), "项目内图片"), (tuple(f"{i:032x}" for i in range(5)), "最多使用 4 张")],
)
def test_sheet_plan_rejects_invalid_identity(tmp_path, identity, message) -> None:
    _store, document, _keyframe_id, look_id = _project_with_look(tmp_path)
    with pytest.raises(ValueError, match=message):
        look_sheet_plan(document, look_id, identity)


def _sheets(document):
    return [
        item
        for item in document.generations
        if item.kind is ReferenceGenerationKind.CHARACTER_LOOK_SHEET
    ]


def _succeed(store, service, generation, content):
    document = asyncio.run(
        service.import_image_asset(
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + content,
            category=ImageAssetCategory.CHARACTER_REFERENCE,
            expected_revision=store.read().revision,
        )
    )
    asset_id = document.assets[-1].id
    store.update_generation(
        transition_generation(
            transition_generation(generation, ReferenceGenerationPhase.RUNNING),
            ReferenceGenerationPhase.SUCCEEDED,
            progress=1.0,
            output_asset_id=asset_id,
        )
    )
    return asset_id


def test_generate_and_select_sheet_keeps_keyframe_look_choice(tmp_path) -> None:
    store, document, keyframe_id, look_id = _project_with_look(tmp_path)
    service, provider, _registry = _qwen_service(store)
    card = document.reference_library.characters[0]
    document = _apply(
        store,
        document,
        [
            {
                "op": "update_frame_fields",
                "keyframe_id": keyframe_id,
                "fields": {"character_references": [{"character_id": card.id, "look_id": look_id}]},
            }
        ],
        key="pick-look",
    )
    with pytest.raises(ValueError, match="尚未选定造型图"):
        _keyframe_generation_inputs(document, keyframe_id)
    document = asyncio.run(
        service.generate_look_sheet(
            look_id=look_id, identity_asset_ids=(), expected_revision=document.revision
        )
    )
    first = _sheets(document)[0]
    assert (first.target_id, first.aspect_ratio) == (look_id, "2:1")
    assert provider.requests[0].param("aspect_ratio") == "2:1"
    first_asset = _succeed(store, service, first, b"sheet-1")
    document = asyncio.run(
        service.select_look_sheet(
            card_id=card.id,
            look_id=look_id,
            generation_id=first.id,
            expected_revision=store.read().revision,
        )
    )
    assert document.reference_library.look_owner(look_id)[1].selected_asset_id == first_asset
    assert _keyframe_generation_inputs(document, keyframe_id).asset_ids == (first_asset,)

    document = asyncio.run(
        service.generate_look_sheet(
            look_id=look_id, identity_asset_ids=(first_asset,), expected_revision=document.revision
        )
    )
    second = _sheets(document)[1]
    assert second.input_asset_ids == (first_asset,)
    second_asset = _succeed(store, service, second, b"sheet-2")
    document = asyncio.run(
        service.select_look_sheet(
            card_id=card.id,
            look_id=look_id,
            generation_id=second.id,
            expected_revision=store.read().revision,
        )
    )
    keyframe = next(item for item in document.keyframe_plan.keyframes if item.id == keyframe_id)
    assert keyframe.character_references == (KeyframeCharacterReference(card.id, look_id),)
    assert _keyframe_generation_inputs(document, keyframe_id).asset_ids == (second_asset,)
    with pytest.raises(ValueError, match="已经是这套造型的造型图"):
        asyncio.run(
            service.select_look_sheet(
                card_id=card.id,
                look_id=look_id,
                generation_id=second.id,
                expected_revision=document.revision,
            )
        )
    with pytest.raises(ValueError, match="图片 Asset"):
        asyncio.run(
            service.select_look_asset(
                card_id=card.id,
                look_id=look_id,
                asset_id="f" * 32,
                expected_revision=document.revision,
            )
        )


def test_retry_keeps_identity_and_ratio(tmp_path) -> None:
    store, document, _keyframe_id, look_id = _project_with_look(tmp_path)
    service, provider, _registry = _qwen_service(store)
    identity = document.reference_library.characters[0].looks[0].selected_asset_id
    provider.reject = True
    document = asyncio.run(
        service.generate_look_sheet(
            look_id=look_id, identity_asset_ids=(identity,), expected_revision=document.revision
        )
    )
    failed = _sheets(document)[0]
    provider.reject = False
    document = asyncio.run(service.retry_generation(failed.id, expected_revision=document.revision))
    retried = _sheets(document)[1]
    assert (retried.retry_of, retried.input_asset_ids, retried.aspect_ratio) == (
        failed.id,
        (identity,),
        "2:1",
    )


def test_mcp_look_tools_translate_to_core_commands() -> None:
    target = A
    request = Generate(
        kind="look_sheet",
        target_id=target,
        identity_asset_ids=[B],
        project_id=target,
        expected_revision=3,
        idempotency_key="k",
    )
    assert translate("generate_media", request) == (
        "reference.generate_look_sheet",
        {"look_id": target, "identity_asset_ids": [B]},
    )
    for bad in ({"kind": "look_sheet"}, {"kind": "character_image", "identity_asset_ids": []}):
        with pytest.raises(ValueError):
            Generate(
                **bad, target_id=target, project_id=target, expected_revision=3, idempotency_key="k"
            )
    edit = LookEdit(
        operations=[{"op": "update_look", "look_id": B, "fields": {"usage": "第二幕"}}],
        project_id=target,
        expected_revision=3,
        idempotency_key="k",
    )
    assert translate("edit_looks", edit)[0] == "reference.apply_look_operations"


def _card_body(card, revision, looks):
    return json.dumps(
        {
            "expected_revision": revision,
            "name": card.name,
            "visual_description": card.visual_description,
            "voice_description": card.voice_description,
            "voice_reference_asset_id": card.voice_reference_asset_id,
            "looks": looks,
        }
    ).encode()


@pytest.mark.parametrize("removal", ["character", "look", "look_with_other_selection"])
def test_removed_look_sheet_candidates_release_asset_usage(tmp_path, removal) -> None:
    store = StructuredDirectorStore(tmp_path, A)
    create_project(store)
    fixture_service = ProposalFixtureService(store, RecordingProposer())
    document = asyncio.run(fixture_service.prepare_references())
    card = document.reference_library.characters[0]
    added = _look_ops(
        store,
        document,
        [
            {
                "op": "add_look",
                "character_id": card.id,
                "name": "原造型",
                "appearance": "蓝衣",
                "usage": "全片",
            }
        ],
    )
    look_id = added.receipt.changed_ids[0]
    service, _provider, _registry = _qwen_service(store)
    api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
    asset_ids, generation_ids = [], []
    for index in range(2):
        document = asyncio.run(
            service.generate_look_sheet(
                look_id=look_id, identity_asset_ids=(), expected_revision=store.read().revision
            )
        )
        generation = _sheets(document)[-1]
        generation_ids.append(generation.id)
        asset_ids.append(_succeed(store, service, generation, f"orphan-sheet-{index}".encode()))

    snapshot = asyncio.run(api.handle("GET", "/structured-director"))
    for asset in snapshot.body["assets"]:
        assert asset["is_in_use"]
        assert asset["usage_reasons"] == [{"code": "visible_candidate", "label": "可见生成候选"}]
    with pytest.raises(ValueError, match="可见生成候选"):
        store.delete_assets(tuple(asset_ids), expected_revision=store.read().revision)

    if removal == "look_with_other_selection":
        added = _look_ops(
            store,
            store.read(),
            [
                {
                    "op": "add_look",
                    "character_id": card.id,
                    "name": "新造型",
                    "appearance": "蓝衣",
                    "usage": "后半片",
                }
            ],
        )
        document = asyncio.run(
            service.select_look_asset(
                card_id=card.id,
                look_id=added.receipt.changed_ids[0],
                asset_id=asset_ids[0],
                expected_revision=added.document.revision,
            )
        )
    document = store.read()
    card = document.reference_library.characters[0]
    path = f"/structured-director/characters/{card.id}"
    if removal == "character":
        response = asyncio.run(
            api.handle(
                "DELETE", path, json.dumps({"expected_revision": document.revision}).encode()
            )
        )
    else:
        looks = [
            {"id": look.id, "name": look.name, "appearance": look.appearance, "usage": look.usage}
            for look in card.looks
            if look.id != look_id
        ]
        response = asyncio.run(api.handle("PUT", path, _card_body(card, document.revision, looks)))
    assert response.status == 200, response.body
    document = store.read()
    assert {item.id for item in document.generations} == set(generation_ids)
    assert {item.id for item in document.assets} == set(asset_ids)
    assets = {item["id"]: item for item in response.body["assets"]}
    for asset_id in asset_ids:
        assert all(
            reason["code"] != "visible_candidate" for reason in assets[asset_id]["usage_reasons"]
        )
    if removal == "look_with_other_selection":
        assert assets[asset_ids[0]]["usage_reasons"] == [
            {"code": "character_reference_image", "label": "角色造型图"}
        ]
        with pytest.raises(ValueError, match="角色造型图"):
            store.delete_asset(asset_ids[0], expected_revision=document.revision)
        asset_ids = asset_ids[1:]
    for asset_id in asset_ids:
        assert not assets[asset_id]["is_in_use"]
        document = store.delete_asset(asset_id, expected_revision=document.revision)
        assert all(item.id != asset_id for item in document.assets)
        assert all(item.output_asset_id != asset_id for item in document.generations)
    assert store.read() == document


def test_human_card_update_assigns_ids_keeps_images_and_rejects_invented_ids(tmp_path) -> None:
    store, document, _keyframe_id, _look_id = _project_with_look(tmp_path)
    service, _provider, _registry = _qwen_service(store)
    api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
    card = document.reference_library.characters[0]
    path = f"/structured-director/characters/{card.id}"
    first = card.looks[0]
    kept = {"id": first.id, "name": first.name, "appearance": "改过的外观", "usage": first.usage}
    added = asyncio.run(
        api.handle(
            "PUT",
            path,
            _card_body(
                card,
                document.revision,
                [kept, {"id": None, "name": "礼服", "appearance": "黑色西装", "usage": "婚礼"}],
            ),
        )
    )
    assert added.status == 200, added.body
    card = store.read().reference_library.characters[0]
    assert [look.name for look in card.looks] == [first.name, "礼服"]
    # 整卡保存只改文字：已有造型图沿用，新造型没有图。
    assert card.looks[0].selected_asset_id == first.selected_asset_id
    assert card.looks[0].appearance == "改过的外观" and card.looks[1].selected_asset_id is None
    invented = asyncio.run(
        api.handle(
            "PUT",
            path,
            _card_body(
                card,
                store.read().revision,
                [{"id": "e" * 32, "name": "x", "appearance": "y", "usage": "z"}],
            ),
        )
    )
    assert invented.status == 400 and "新造型的 id 必须为 null" in json.dumps(
        invented.body, ensure_ascii=False
    )
