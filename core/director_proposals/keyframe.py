from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.director_commands import KeyframeOperation

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class KeyframeCharacterLookInput:
    """角色的一套造型：名称、使用场合与已选造型图；Planner 可读取原图后为每帧选造型。"""

    look_id: str
    name: str
    usage: str
    selected_asset_id: str | None
    has_image: bool = field(init=False)

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.look_id):
            raise ValueError("关键帧角色造型 ID 不合法。")
        if self.selected_asset_id is not None and not _ID.fullmatch(self.selected_asset_id):
            raise ValueError("关键帧角色造型图 Asset ID 不合法。")
        object.__setattr__(self, "has_image", self.selected_asset_id is not None)


@dataclass(frozen=True, slots=True)
class KeyframeCharacterInput:
    id: str
    name: str
    looks: tuple[KeyframeCharacterLookInput, ...] = ()

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.id) or not self.name.strip():
            raise ValueError("关键帧角色输入不合法。")


@dataclass(frozen=True, slots=True)
class KeyframeCharacterReferenceProposal:
    """本帧为一个可见角色选择的造型；look_id 为 null 表示不提交该角色的图。"""

    character_id: str
    look_id: str | None

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.character_id):
            raise ValueError("关键帧角色造型选择的角色 ID 不合法。")
        if self.look_id is not None and not _ID.fullmatch(self.look_id):
            raise ValueError("关键帧角色造型 ID 不合法。")


@dataclass(frozen=True, slots=True)
class KeyframeShotInput:
    """Segment 按顺序覆盖的一个 Shot 的创作描述；Shot 本身不持有生产状态。"""

    id: str
    composition: str
    camera_movement: str
    action: str
    visible_characters: tuple[KeyframeCharacterInput, ...]
    audio_direction: str = ""

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.id):
            raise ValueError("关键帧 Shot 输入 ID 不合法。")
        if not self.visible_characters:
            return
        ids = [item.id for item in self.visible_characters]
        if len(ids) != len(set(ids)):
            raise ValueError("关键帧 Shot 可见角色不能重复。")


@dataclass(frozen=True, slots=True)
class KeyframeSegmentInput:
    """Keyframe Planner 的 Segment 输入：覆盖 Shot 与派生可见角色。"""

    id: str
    action: str
    shots: tuple[KeyframeShotInput, ...]
    dialogue_lines: tuple[str, ...] = ()
    start_keyframe_id: str | None = None
    end_keyframe_id: str | None = None
    start_locked: bool = False
    end_locked: bool = False
    planning_enabled: bool = True
    # 覆盖 Shot 可见角色的并集，保序去重；Planner 只能从这里选本帧可见角色。
    visible_characters: tuple[KeyframeCharacterInput, ...] = ()
    # 与同 Scene 上一 Segment 共享边界 Shot：延续同一镜头，默认共享边界 Keyframe。
    continues_from_previous: bool = False

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.id):
            raise ValueError("当前 Segment 的 ID 不合法。")
        if not self.shots:
            raise ValueError("当前 Segment 必须至少覆盖一个 Shot。")
        shot_ids = [item.id for item in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("当前 Segment 覆盖的 Shot 不能重复。")
        if (self.start_keyframe_id is None) != (self.end_keyframe_id is None):
            raise ValueError("当前 Segment 必须同时提供首尾 Keyframe ID。")
        for keyframe_id in (self.start_keyframe_id, self.end_keyframe_id):
            if keyframe_id is not None and not _ID.fullmatch(keyframe_id):
                raise ValueError("当前 Segment 的 Keyframe ID 不合法。")
        for value in (self.start_locked, self.end_locked, self.planning_enabled):
            if type(value) is not bool:
                raise ValueError("当前 Segment 的 Keyframe 锁定或规划范围标记不合法。")


@dataclass(frozen=True, slots=True)
class KeyframeSceneInput:
    id: str
    title: str
    setting: str
    segments: tuple[KeyframeSegmentInput, ...]
    summary: str = ""
    location_id: str | None = None
    state_id: str | None = None


@dataclass(frozen=True, slots=True)
class KeyframeReferenceImageProposal:
    slot_index: int
    prompt_text: str
    description: str
    visible_character_ids: tuple[str, ...]
    character_references: tuple[KeyframeCharacterReferenceProposal, ...] = ()
    reference_asset_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.slot_index) is not int or not 0 <= self.slot_index < 4:
            raise ValueError("其他图片槽位必须为 0–3。")
        if not self.prompt_text.strip() or len(self.prompt_text) > 18000:
            raise ValueError("其他图片画面正文不能为空或过长。")
        if not self.description.strip() or len(self.description) > 2000:
            raise ValueError("其他图片说明不能为空或过长。")
        _validate_character_ids(self.visible_character_ids)
        _validate_character_references(self.character_references, self.visible_character_ids)
        _validate_character_ids(self.reference_asset_ids)
        if len(self.reference_asset_ids) > 5:
            raise ValueError("其他图片的生图输入最多 5 张。")


@dataclass(frozen=True, slots=True)
class KeyframeSegmentProposal:
    """一个 Segment 的首尾计划；承接上一 Segment 时首帧字段必须为空。"""

    segment_id: str
    continues_from_previous: bool
    frame_strategy: str
    start_prompt_text: str
    start_visible_character_ids: tuple[str, ...]
    end_prompt_text: str
    end_visible_character_ids: tuple[str, ...]
    start_character_references: tuple[KeyframeCharacterReferenceProposal, ...] = ()
    end_character_references: tuple[KeyframeCharacterReferenceProposal, ...] = ()
    reference_images: tuple[KeyframeReferenceImageProposal, ...] = ()
    # 生图时参考的其它 Keyframe（工作集 referenceable_keyframes 中已有选中图者）。
    start_reference_keyframe_ids: tuple[str, ...] = ()
    end_reference_keyframe_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for references in (self.start_reference_keyframe_ids, self.end_reference_keyframe_ids):
            if any(not _ID.fullmatch(item) for item in references):
                raise ValueError("参考关键帧 ID 不合法。")
            if len(references) != len(set(references)) or len(references) > 4:
                raise ValueError("每帧参考关键帧不能重复且最多 4 个。")
        positions = [item.slot_index for item in self.reference_images]
        if len(positions) > 4 or len(positions) != len(set(positions)):
            raise ValueError("其他图片规划最多 4 张且槽位不得重复。")
        if type(self.continues_from_previous) is not bool:
            raise ValueError("Segment 是否承接上一 Segment 必须是布尔值。")
        if self.frame_strategy not in {"none", "start", "end", "both"}:
            raise ValueError("Segment 关键帧策略必须是 none、start、end 或 both。")
        if len(self.end_prompt_text) > 18_000 or (
            self.frame_strategy in {"end", "both"} and not self.end_prompt_text.strip()
        ):
            raise ValueError("启用的尾帧提示词不能为空，正文不能过长。")
        _validate_character_ids(self.end_visible_character_ids)
        _validate_character_references(
            self.end_character_references, self.end_visible_character_ids
        )
        if self.continues_from_previous:
            # 承接时首帧就是上一 Segment 的尾帧：只允许空值，避免模型重复设计同一画面。
            if self.start_prompt_text.strip():
                raise ValueError(
                    "承接上一 Segment 时首帧沿用上一 Segment 的尾帧，"
                    "start_prompt_text 必须为空字符串。"
                )
            if self.start_visible_character_ids:
                raise ValueError(
                    "承接上一 Segment 时不能单独给出首帧可见角色；"
                    "请清空 start_visible_character_ids。"
                )
            if self.start_character_references:
                raise ValueError(
                    "承接上一 Segment 时不能单独给出首帧角色造型；"
                    "请清空 start_character_references。"
                )
            if self.start_reference_keyframe_ids:
                raise ValueError(
                    "承接上一 Segment 时不能单独给出首帧参考关键帧；"
                    "请清空 start_reference_keyframe_ids。"
                )
            return
        if len(self.start_prompt_text) > 18_000 or (
            self.frame_strategy in {"start", "both"} and not self.start_prompt_text.strip()
        ):
            raise ValueError("启用的首帧提示词不能为空，正文不能过长。")
        _validate_character_ids(self.start_visible_character_ids)
        _validate_character_references(
            self.start_character_references, self.start_visible_character_ids
        )


@dataclass(frozen=True, slots=True)
class KeyframePlanProposal:
    segments: tuple[KeyframeSegmentProposal, ...]

    def __post_init__(self) -> None:
        ids = [item.segment_id for item in self.segments]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("关键帧计划必须包含不重复的 Segment。")


@dataclass(frozen=True, slots=True)
class KeyframeOperationsProposal:
    operations: tuple[KeyframeOperation, ...]
    decision_summary: str
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.decision_summary.strip() or len(self.decision_summary) > 2_000:
            raise ValueError("关键帧 operations 决策摘要不能为空或过长。")
        if any(not item.strip() or len(item) > 500 for item in self.assumptions):
            raise ValueError("关键帧 operations 假设说明不合法。")


def _validate_character_ids(character_ids: tuple[str, ...]) -> None:
    if any(not _ID.fullmatch(item) for item in character_ids):
        raise ValueError("关键帧可见角色 ID 不合法。")
    if len(character_ids) != len(set(character_ids)):
        raise ValueError("关键帧可见角色 ID 不能重复。")


def _validate_character_references(
    references: tuple[KeyframeCharacterReferenceProposal, ...],
    visible_character_ids: tuple[str, ...],
) -> None:
    ids = [item.character_id for item in references]
    if len(ids) != len(set(ids)):
        raise ValueError("同一角色在一帧内只能选择一套造型。")
    if not set(ids) <= set(visible_character_ids):
        raise ValueError("关键帧角色造型选择只能针对该帧可见角色。")
