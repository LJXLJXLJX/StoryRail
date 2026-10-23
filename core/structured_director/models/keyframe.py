"""领域模型：keyframe 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ._shared import _require_id
from .location import LocationLibrary
from .reference import ReferenceLibrary

MAX_REFERENCE_KEYFRAMES = 4


@dataclass(frozen=True, slots=True)
class KeyframeCharacterReference:
    """本帧为一个可见角色选择的造型；look_id 为 None 表示不提交该角色的图。"""

    character_id: str
    look_id: str | None

    def __post_init__(self) -> None:
        _require_id(self.character_id, "keyframe.character_references.character_id")
        if self.look_id is not None:
            _require_id(self.look_id, "keyframe.character_references.look_id")


@dataclass(frozen=True, slots=True)
class Keyframe:
    id: str
    owner_segment_id: str
    predecessor_keyframe_id: str | None
    prompt_text: str
    visible_character_ids: tuple[str, ...]
    selected_asset_id: str | None = None
    # 未列出的可见角色按默认规则：角色只有一套造型时使用它，多套造型必须显式选择。
    character_references: tuple[KeyframeCharacterReference, ...] = ()
    # 生图时参考的其它 Keyframe；提交时解析为它们当前的已选图，未选定时不能生成。
    reference_keyframe_ids: tuple[str, ...] = ()
    # 生图时参考的地点库普通图片条目；提交时取其当前已选图并附带图片说明。
    reference_location_image_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.id, "keyframe.id")
        _require_id(self.owner_segment_id, "keyframe.owner_segment_id")
        if self.predecessor_keyframe_id is not None:
            _require_id(self.predecessor_keyframe_id, "keyframe.predecessor_keyframe_id")
            if self.predecessor_keyframe_id == self.id:
                raise ValueError("Keyframe 不能依赖自身。")
        if len(self.prompt_text) > 18_000:
            raise ValueError("keyframe.prompt_text 过长。")
        for character_id in self.visible_character_ids:
            _require_id(character_id, "keyframe.visible_character_ids")
        if len(self.visible_character_ids) != len(set(self.visible_character_ids)):
            raise ValueError("Keyframe 可见角色不能重复。")
        reference_character_ids = [item.character_id for item in self.character_references]
        if len(reference_character_ids) != len(set(reference_character_ids)):
            raise ValueError("Keyframe 同一角色只能有一组参考图选择。")
        if not set(reference_character_ids) <= set(self.visible_character_ids):
            raise ValueError("Keyframe 角色参考图选择只能针对本帧可见角色。")
        if self.selected_asset_id is not None:
            _require_id(self.selected_asset_id, "keyframe.selected_asset_id")
        for reference_id in self.reference_keyframe_ids:
            _require_id(reference_id, "keyframe.reference_keyframe_ids")
        if len(self.reference_keyframe_ids) != len(set(self.reference_keyframe_ids)):
            raise ValueError("Keyframe 参考关键帧不能重复。")
        if len(self.reference_keyframe_ids) > MAX_REFERENCE_KEYFRAMES:
            raise ValueError(f"Keyframe 最多参考 {MAX_REFERENCE_KEYFRAMES} 个其它关键帧。")
        if self.id in self.reference_keyframe_ids:
            raise ValueError("Keyframe 不能参考自身。")
        for image_id in self.reference_location_image_ids:
            _require_id(image_id, "keyframe.reference_location_image_ids")
        if len(self.reference_location_image_ids) != len(set(self.reference_location_image_ids)):
            raise ValueError("Keyframe 参考地点图片不能重复。")
        if len(self.reference_location_image_ids) > MAX_REFERENCE_KEYFRAMES:
            raise ValueError(f"Keyframe 最多参考 {MAX_REFERENCE_KEYFRAMES} 张地点图片。")


def blank_keyframe(
    keyframe_id: str,
    owner_segment_id: str,
    predecessor_keyframe_id: str | None,
) -> Keyframe:
    """新建空 Keyframe；地点图片只在具体生成调用中显式选择。"""
    return Keyframe(keyframe_id, owner_segment_id, predecessor_keyframe_id, "", ())


@dataclass(frozen=True, slots=True)
class SegmentKeyframes:
    segment_id: str
    start_keyframe_id: str
    end_keyframe_id: str
    start_enabled: bool = False
    end_enabled: bool = False
    reference_asset_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.segment_id, "segment_keyframes.segment_id")
        _require_id(self.start_keyframe_id, "segment_keyframes.start_keyframe_id")
        _require_id(self.end_keyframe_id, "segment_keyframes.end_keyframe_id")
        if self.start_keyframe_id == self.end_keyframe_id:
            raise ValueError("Segment 首尾关键帧不能相同。")
        if type(self.start_enabled) is not bool or type(self.end_enabled) is not bool:
            raise ValueError("Segment 首尾关键帧激活状态不合法。")
        for asset_id in self.reference_asset_ids:
            _require_id(asset_id, "segment_keyframes.reference_asset_ids")
        if len(self.reference_asset_ids) != len(set(self.reference_asset_ids)):
            raise ValueError("Segment 辅助参考图不能重复。")
        if len(self.reference_asset_ids) > 4:
            raise ValueError("单个 Segment 最多添加 4 张辅助参考图。")


@dataclass(frozen=True, slots=True)
class KeyframePlan:
    source_script_revision: int
    keyframes: tuple[Keyframe, ...]
    segments: tuple[SegmentKeyframes, ...]

    def __post_init__(self) -> None:
        if isinstance(self.source_script_revision, bool) or self.source_script_revision < 1:
            raise ValueError("keyframe_plan.source_script_revision 不合法。")
        keyframe_ids = [item.id for item in self.keyframes]
        segment_ids = [item.segment_id for item in self.segments]
        if not keyframe_ids or len(keyframe_ids) != len(set(keyframe_ids)):
            raise ValueError("Keyframe ID 不能为空或重复。")
        if not segment_ids or len(segment_ids) != len(set(segment_ids)):
            raise ValueError("Segment 关键帧绑定不能为空或重复。")
        keyframe_id_set = set(keyframe_ids)
        for item in self.keyframes:
            if (
                item.predecessor_keyframe_id is not None
                and item.predecessor_keyframe_id not in keyframe_id_set
            ):
                raise ValueError("Keyframe 前置依赖不存在。")
        for item in self.segments:
            if (
                item.start_keyframe_id not in keyframe_id_set
                or item.end_keyframe_id not in keyframe_id_set
            ):
                raise ValueError("Segment 引用了未知 Keyframe。")
        _validate_keyframe_graph(self.keyframes)


def _validate_keyframe_graph(keyframes: tuple[Keyframe, ...]) -> None:
    item_by_id = {item.id: item for item in keyframes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(keyframe_id: str) -> None:
        if keyframe_id in visited:
            return
        if keyframe_id in visiting:
            raise ValueError("Keyframe 依赖不能形成环。")
        visiting.add(keyframe_id)
        predecessor = item_by_id[keyframe_id].predecessor_keyframe_id
        if predecessor is not None:
            visit(predecessor)
        visiting.remove(keyframe_id)
        visited.add(keyframe_id)

    for item in keyframes:
        visit(item.id)


def prune_character_references(
    plan: KeyframePlan | None, library: ReferenceLibrary
) -> KeyframePlan | None:
    """造型被删除（或角色卡被删除）后剪除指向它的选择，该角色回到默认规则。

    不清除 Keyframe 已选图片：与其它角色卡编辑一致，已生成候选与历史保留。
    文档构造即校验，调用方必须把结果与新引用库放进同一次 replace。
    """
    if plan is None:
        return None
    card_looks = {card.id: {look.id for look in card.looks} for card in library.characters}
    keyframes: list[Keyframe] = []
    for keyframe in plan.keyframes:
        references = tuple(
            reference
            for reference in keyframe.character_references
            if reference.character_id in card_looks
            and (
                reference.look_id is None or reference.look_id in card_looks[reference.character_id]
            )
        )
        keyframes.append(
            keyframe
            if references == keyframe.character_references
            else replace(keyframe, character_references=references)
        )
    if tuple(keyframes) == plan.keyframes:
        return plan
    return replace(plan, keyframes=tuple(keyframes))


def prune_reference_keyframes(plan: KeyframePlan | None) -> KeyframePlan | None:
    """剪除指向已不在计划中的 Keyframe 的参考；脚本回改或拆并边界都可能移除被参考帧。"""
    if plan is None:
        return None
    known = {item.id for item in plan.keyframes}
    keyframes = tuple(
        item
        if set(item.reference_keyframe_ids) <= known
        else replace(
            item,
            reference_keyframe_ids=tuple(
                reference_id
                for reference_id in item.reference_keyframe_ids
                if reference_id in known
            ),
        )
        for item in plan.keyframes
    )
    if keyframes == plan.keyframes:
        return plan
    return replace(plan, keyframes=keyframes)


def prune_reference_location_images(
    plan: KeyframePlan | None, library: LocationLibrary
) -> KeyframePlan | None:
    """剪除指向已删除地点图片条目的参考；地点库编辑不级联失效 Keyframe。"""
    if plan is None:
        return None
    keyframes = tuple(
        item
        if all(library.image_owner(image_id) for image_id in item.reference_location_image_ids)
        else replace(
            item,
            reference_location_image_ids=tuple(
                image_id
                for image_id in item.reference_location_image_ids
                if library.image_owner(image_id) is not None
            ),
        )
        for item in plan.keyframes
    )
    if keyframes == plan.keyframes:
        return plan
    return replace(plan, keyframes=keyframes)


def require_known_reference_location_images(
    plan: KeyframePlan | None, library: LocationLibrary
) -> None:
    if plan is not None and any(
        library.image_owner(image_id) is None
        for item in plan.keyframes
        for image_id in item.reference_location_image_ids
    ):
        raise ValueError("Keyframe 参考了不存在的地点图片。")


def require_known_reference_keyframes(plan: KeyframePlan) -> None:
    known = {item.id for item in plan.keyframes}
    if any(not set(item.reference_keyframe_ids) <= known for item in plan.keyframes):
        raise ValueError("Keyframe 参考了不存在的关键帧。")
