"""角色造型：新增、修改与选定造型图；纯函数，Core 分配造型 ID。

改造型文字不失效已选造型图；Keyframe 引用造型而不是图片，改选图不需要改写 Keyframe。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from core.director_commands import CommandReceipt
from core.director_commands.reference_commands import AddLook, LookOperationsPatch

from ..models import CharacterLook, StructuredDirectorDocument


@dataclass(frozen=True, slots=True)
class LookOperationsResult:
    document: StructuredDirectorDocument
    receipt: CommandReceipt
    write: bool


def apply_look_operations(
    document: StructuredDirectorDocument, patch: LookOperationsPatch, command_id: str
) -> LookOperationsResult:
    cards = {card.id: card for card in document.reference_library.characters}
    changed: list[str] = []
    for operation in patch.operations:
        if isinstance(operation, AddLook):
            card = cards.get(operation.character_id)
            if card is None:
                raise ValueError("角色卡不存在。")
            if card.visual_description is None:
                raise ValueError(f"「{card.name}」是非出镜声音身份，不能有造型。")
            look = CharacterLook(uuid4().hex, operation.name, operation.appearance, operation.usage)
            cards[card.id] = replace(card, looks=(*card.looks, look))
            changed.append(look.id)
            continue
        owner = next(
            (card for card in cards.values() if card.look(operation.look_id) is not None), None
        )
        if owner is None:
            raise ValueError("造型不存在。")
        looks = tuple(
            replace(look, **operation.fields) if look.id == operation.look_id else look
            for look in owner.looks
        )
        if looks != owner.looks:
            cards[owner.id] = replace(owner, looks=looks)
            changed.append(operation.look_id)
    library = replace(document.reference_library, characters=tuple(cards.values()))
    if not changed:
        return LookOperationsResult(
            document,
            CommandReceipt(
                command_id=command_id,
                status="noop",
                old_revision=document.revision,
                new_revision=document.revision,
                decision_summary="造型内容未变化。",
            ),
            write=False,
        )
    updated = replace(document, revision=document.revision + 1, reference_library=library)
    return LookOperationsResult(
        updated,
        CommandReceipt(
            command_id=command_id,
            status="succeeded",
            old_revision=document.revision,
            new_revision=updated.revision,
            changed_ids=tuple(changed),
            preserved=("look_sheets", "asset_history", "generation_history"),
            decision_summary="已保存造型；设定图需要用户显式要求后生成，选择由用户完成。",
            next_allowed_actions=("reference.generate_look_sheet",),
        ),
        write=True,
    )


def set_look_asset(
    document: StructuredDirectorDocument, *, card_id: str, look_id: str, asset_id: str
) -> StructuredDirectorDocument:
    """把已登记图片设为造型图（不加 revision，由调用方统一 bump）。"""
    asset = next((item for item in document.assets if item.id == asset_id), None)
    if asset is None or not asset.media_type.startswith("image/"):
        raise ValueError("造型图必须引用已登记的图片 Asset。")
    card = next(
        (item for item in document.reference_library.characters if item.id == card_id), None
    )
    look = None if card is None else card.look(look_id)
    if card is None or look is None:
        raise ValueError("造型不存在。")
    if look.selected_asset_id == asset_id:
        raise ValueError("该图片已经是这套造型的造型图。")
    updated = replace(
        card,
        looks=tuple(
            replace(item, selected_asset_id=asset_id) if item.id == look_id else item
            for item in card.looks
        ),
    )
    return replace(
        document,
        reference_library=replace(
            document.reference_library,
            characters=tuple(
                updated if item.id == card_id else item
                for item in document.reference_library.characters
            ),
        ),
    )
