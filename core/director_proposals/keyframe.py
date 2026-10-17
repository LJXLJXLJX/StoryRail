from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.director_commands import KeyframeOperation
from core.structured_director.models import normalize_environment_none_reason

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
class KeyframeSegmentInput:
    id: str
    action: str
    dialogue_lines: tuple[str, ...] = ()
    start_keyframe_id: str | None = None
    end_keyframe_id: str | None = None
    start_locked: bool = False
    end_locked: bool = False

    def __post_init__(self) -> None:
        if (self.start_keyframe_id is None) != (self.end_keyframe_id is None):
            raise ValueError("当前 Segment 必须同时提供首尾 Keyframe ID。")
        for keyframe_id in (self.start_keyframe_id, self.end_keyframe_id):
            if keyframe_id is not None and not _ID.fullmatch(keyframe_id):
                raise ValueError("当前 Segment 的 Keyframe ID 不合法。")
        if type(self.start_locked) is not bool or type(self.end_locked) is not bool:
            raise ValueError("当前 Segment 的 Keyframe 锁定状态不合法。")


@dataclass(frozen=True, slots=True)
class KeyframeShotInput:
    id: str
    composition: str
    camera_movement: str
    action: str
    visible_characters: tuple[KeyframeCharacterInput, ...]
    segments: tuple[KeyframeSegmentInput, ...]
    audio_direction: str = ""
    planning_enabled: bool = True
    view_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.planning_enabled) is not bool:
            raise ValueError("Shot 关键帧规划范围标记不合法。")


@dataclass(frozen=True, slots=True)
class KeyframeSceneInput:
    id: str
    title: str
    setting: str
    shots: tuple[KeyframeShotInput, ...]
    summary: str = ""
    location_id: str | None = None
    # 项目内全部地点视图 ID；Keyframe 只能引用其中之一。
    available_view_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KeyframeSegmentProposal:
    segment_id: str
    frame_strategy: str
    end_prompt_text: str
    end_visible_character_ids: tuple[str, ...]
    # null 表示未声明：Core 按所属 Shot 的视图填继承默认值（有视图 reference，无视图 none）。
    end_environment_mode: str | None = None
    end_environment_view_id: str | None = None
    end_environment_none_reason: str | None = None
    end_character_references: tuple[KeyframeCharacterReferenceProposal, ...] = ()

    def __post_init__(self) -> None:
        if self.frame_strategy not in {"start", "end", "both"}:
            raise ValueError("Segment 关键帧策略必须是 start、end 或 both。")
        if not self.end_prompt_text.strip() or len(self.end_prompt_text) > 18_000:
            raise ValueError("Segment 尾帧提示词不能为空或过长。")
        _validate_character_ids(self.end_visible_character_ids)
        _validate_character_references(
            self.end_character_references, self.end_visible_character_ids
        )
        object.__setattr__(
            self,
            "end_environment_none_reason",
            _validate_environment(
                self.end_environment_mode,
                self.end_environment_view_id,
                self.end_environment_none_reason,
            ),
        )


@dataclass(frozen=True, slots=True)
class KeyframeShotProposal:
    shot_id: str
    continues_from_previous_shot: bool
    start_prompt_text: str
    start_visible_character_ids: tuple[str, ...]
    segments: tuple[KeyframeSegmentProposal, ...]
    # null 表示未声明：Core 按所属 Shot 的视图填继承默认值（有视图 reference，无视图 none）。
    start_environment_mode: str | None = None
    start_environment_view_id: str | None = None
    start_environment_none_reason: str | None = None
    start_character_references: tuple[KeyframeCharacterReferenceProposal, ...] = ()

    def __post_init__(self) -> None:
        if not self.start_prompt_text.strip() or len(self.start_prompt_text) > 18_000:
            raise ValueError("Shot 首帧提示词不能为空或过长。")
        _validate_character_ids(self.start_visible_character_ids)
        _validate_character_references(
            self.start_character_references, self.start_visible_character_ids
        )
        object.__setattr__(
            self,
            "start_environment_none_reason",
            _validate_environment(
                self.start_environment_mode,
                self.start_environment_view_id,
                self.start_environment_none_reason,
            ),
        )
        if not self.segments:
            raise ValueError("每个 Shot 必须包含 Segment 尾帧计划。")
        ids = [item.segment_id for item in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("Segment 计划不能重复。")


@dataclass(frozen=True, slots=True)
class KeyframePlanProposal:
    shots: tuple[KeyframeShotProposal, ...]

    def __post_init__(self) -> None:
        ids = [item.shot_id for item in self.shots]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("关键帧计划必须包含不重复的 Shot。")


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


def _validate_environment(
    mode: str | None, view_id: str | None, none_reason: str | None
) -> str | None:
    """校验地点视图三项并返回归一后的 none 理由；三项均为 null 表示未声明，由 Core 继承 Shot 视图。

    none 不指定视图、理由可选（空白归一为 null）；edit/reference 必须指定视图且不写理由。
    """
    if mode is None:
        if view_id is not None or none_reason is not None:
            raise ValueError(
                "未声明地点视图使用方式时由 Core 继承 Shot 视图，不能单独给出视图 ID 或 none 理由。"
            )
        return None
    if mode not in {"edit", "reference", "none"}:
        raise ValueError("地点视图使用方式必须是 edit、reference 或 none。")
    if (mode == "none") != (view_id is None):
        raise ValueError("地点视图使用方式与视图 ID 不一致。")
    if view_id is not None and not _ID.fullmatch(view_id):
        raise ValueError("地点视图 ID 不合法。")
    none_reason = normalize_environment_none_reason(none_reason)
    if mode != "none" and none_reason is not None:
        raise ValueError("使用地点视图时不能填写 none 理由。")
    return none_reason
