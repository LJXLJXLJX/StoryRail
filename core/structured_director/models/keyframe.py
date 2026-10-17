"""领域模型：keyframe 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from ._shared import _require_id, _require_text
from .reference import ReferenceLibrary


class KeyframeEnvironmentMode(StrEnum):
    """Keyframe 使用地点视图的方式：edit 作为编辑底图，reference 仅作参考，none 不提交。"""

    EDIT = "edit"
    REFERENCE = "reference"
    NONE = "none"


# Shot 没有地点视图时的默认退出理由；只用于 Core 建立的空白帧与 Planner 未声明时的继承。
DEFAULT_ENVIRONMENT_NONE_REASON = "Shot 未绑定地点视图"
# 人工入口与 keyframe.apply_operations 显式设为 none 却没有理由时的拒绝信息。
ENVIRONMENT_NONE_REASON_REQUIRED = (
    "不使用地点视图（none）时必须写明理由（environment_none_reason，1–500 字）。"
)


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
    environment_mode: KeyframeEnvironmentMode = KeyframeEnvironmentMode.NONE
    environment_view_id: str | None = None
    # none 时必填（1–500 字），edit/reference 时必须为 None。
    environment_none_reason: str | None = DEFAULT_ENVIRONMENT_NONE_REASON
    # 未列出的可见角色按默认规则：角色只有一套造型时使用它，多套造型必须显式选择。
    character_references: tuple[KeyframeCharacterReference, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.id, "keyframe.id")
        if self.environment_view_id is not None:
            _require_id(self.environment_view_id, "keyframe.environment_view_id")
        if (self.environment_mode is KeyframeEnvironmentMode.NONE) != (
            self.environment_view_id is None
        ):
            raise ValueError("Keyframe none 必须不指定地点视图；edit/reference 必须显式指定视图。")
        if self.environment_mode is KeyframeEnvironmentMode.NONE:
            if self.environment_none_reason is None:
                raise ValueError("Keyframe 不使用地点视图时必须说明理由。")
            _require_text(self.environment_none_reason, "keyframe.environment_none_reason", 500)
        elif self.environment_none_reason is not None:
            raise ValueError("Keyframe 使用地点视图时不能保存 none 理由。")
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


def blank_keyframe(
    keyframe_id: str,
    owner_segment_id: str,
    predecessor_keyframe_id: str | None,
    *,
    shot_view_id: str | None,
) -> Keyframe:
    """新建空 Keyframe，环境字段按所属 Shot 的视图写成显式值。

    Shot 有视图 → `edit` + 该视图；无视图 → `none` + 默认理由。只在建立和重建帧时调用；
    之后 Shot 改绑不回写已有帧，失效级联因此只需看帧上显式的 `environment_view_id`。
    """
    if shot_view_id is None:
        return Keyframe(keyframe_id, owner_segment_id, predecessor_keyframe_id, "", ())
    return Keyframe(
        keyframe_id,
        owner_segment_id,
        predecessor_keyframe_id,
        "",
        (),
        environment_mode=KeyframeEnvironmentMode.EDIT,
        environment_view_id=shot_view_id,
        environment_none_reason=None,
    )


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
