"""领域模型：script 域（从 models.py 纯移动，语义不变）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING

from ._shared import _COMMAND_NAME, _require_id, _require_text, _validate_unique_ids

if TYPE_CHECKING:
    from .narration import NarrationCue


class SegmentBoundaryReason(StrEnum):
    MODEL_CONSTRAINT = "model_constraint"
    CONTINUITY_ANCHOR = "continuity_anchor"
    CONTROL_BOUNDARY = "control_boundary"
    FAILURE_COST = "failure_cost"


class CapabilityGapStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class CapabilityGapResult(StrEnum):
    SUCCEEDED = "succeeded"
    NOOP = "noop"


DIALOGUE_SPEAKER_LABEL_MAX = 60


@dataclass(frozen=True, slots=True)
class DialogueLine:
    # 说话者二选一：引用库角色（character_id），或引用库外的临时/画外说话者（speaker_label，
    # 只有称呼，没有造型和音色）。
    character_id: str | None
    text: str
    delivery: str
    speaker_label: str | None = None

    def __post_init__(self) -> None:
        if (self.character_id is None) == (self.speaker_label is None):
            raise ValueError("dialogue_line 必须且只能提供 character_id 或 speaker_label 之一。")
        if self.character_id is not None:
            _require_id(self.character_id, "dialogue_line.character_id")
        else:
            _require_text(
                self.speaker_label or "", "dialogue_line.speaker_label", DIALOGUE_SPEAKER_LABEL_MAX
            )
        _require_text(self.text, "dialogue_line.text", 2_000)
        if len(self.delivery) > 1_000:
            raise ValueError("dialogue_line.delivery 过长。")


@dataclass(frozen=True, slots=True)
class SegmentBoundary:
    reason: SegmentBoundaryReason
    continuity_instruction: str

    def __post_init__(self) -> None:
        _require_text(
            self.continuity_instruction,
            "boundary.continuity_instruction",
            2_000,
        )


@dataclass(frozen=True, slots=True)
class ShotSegment:
    id: str
    # 覆盖的 Shot（按顺序、非空）；与所在 Scene 的覆盖关系由 Scene 校验。
    shot_ids: tuple[str, ...]
    duration_estimate_seconds: float
    action: str
    dialogue_lines: tuple[DialogueLine, ...]
    boundary_from_previous: SegmentBoundary | None

    def __post_init__(self) -> None:
        _require_id(self.id, "segment.id")
        if not self.shot_ids:
            raise ValueError("Segment 必须覆盖至少一个 Shot。")
        for shot_id in self.shot_ids:
            _require_id(shot_id, "segment.shot_ids")
        if len(self.shot_ids) != len(set(self.shot_ids)):
            raise ValueError("segment.shot_ids 不能重复。")
        if (
            isinstance(self.duration_estimate_seconds, bool)
            or not isfinite(self.duration_estimate_seconds)
            or self.duration_estimate_seconds < 0.2
        ):
            raise ValueError("segment.duration_estimate_seconds 不合法。")
        _require_text(self.action, "segment.action", 4_000)


@dataclass(frozen=True, slots=True)
class Shot:
    id: str
    visible_character_ids: tuple[str, ...]
    composition: str
    camera_movement: str
    action: str
    audio_direction: str
    transition_in: str | None
    # 地点视图建议（软参考）；必须属于所在 Scene 的 Location。
    view_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "shot.id")
        if self.view_id is not None:
            _require_id(self.view_id, "shot.view_id")
        for character_id in self.visible_character_ids:
            _require_id(character_id, "shot.visible_character_ids")
        if len(self.visible_character_ids) != len(set(self.visible_character_ids)):
            raise ValueError("shot.visible_character_ids 不能重复。")
        _require_text(self.composition, "shot.composition", 4_000)
        _require_text(self.camera_movement, "shot.camera_movement", 2_000)
        _require_text(self.action, "shot.action", 4_000)
        if len(self.audio_direction) > 2_000:
            raise ValueError("shot.audio_direction 过长。")
        if self.transition_in is not None:
            _require_text(self.transition_in, "shot.transition_in", 500)


@dataclass(frozen=True, slots=True)
class Scene:
    id: str
    title: str
    summary: str
    setting: str
    shots: tuple[Shot, ...]
    segments: tuple[ShotSegment, ...]
    narration_cues: tuple[NarrationCue, ...] = ()
    driver: str = "drama"
    location_id: str | None = None
    # 地点状态变体；必须属于 location_id 指向的 Location。
    state_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "scene.id")
        if self.location_id is not None:
            _require_id(self.location_id, "scene.location_id")
        if self.state_id is not None:
            _require_id(self.state_id, "scene.state_id")
            if self.location_id is None:
                raise ValueError("Scene 未绑定地点时不能指定地点状态。")
        if self.location_id is None and any(shot.view_id is not None for shot in self.shots):
            raise ValueError("Scene 未绑定地点时 Shot 不能绑定地点视图。")
        _require_text(self.title, "scene.title", 300)
        _require_text(self.summary, "scene.summary", 4_000)
        _require_text(self.setting, "scene.setting", 4_000)
        if self.driver not in {"narration", "drama"}:
            raise ValueError("Scene driver 必须是 narration 或 drama。")
        if self.driver == "narration":
            if len(self.narration_cues) != 1:
                raise ValueError("Narration Scene 必须包含一个语义原子的旁白 Cue。")
            if any(segment.dialogue_lines for segment in self.segments):
                raise ValueError("Narration Scene 不能包含对白；需要对白的内容请使用 Drama Scene。")
        else:
            if self.narration_cues:
                raise ValueError("Drama Scene 不能包含旁白；需要旁白的内容请使用 Narration Scene。")
            if not self.shots:
                raise ValueError("Drama Scene 至少需要一个 Shot。")
        if len({cue.id for cue in self.narration_cues}) != len(self.narration_cues):
            raise ValueError("同一 Scene 的旁白 Cue ID 不能重复。")
        if len(self.narration_cues) > 1:
            raise ValueError("每个 Scene 最多只能有一段旁白。")
        _validate_segment_coverage(self)


def _validate_segment_coverage(scene: Scene) -> None:
    """Segment 按顺序恰好覆盖全部 Shot；相邻 Segment 只允许共享边界 Shot，共享即延续。"""
    label = f"Scene「{scene.title}」"
    if bool(scene.shots) != bool(scene.segments):
        raise ValueError(f"{label} 的 Shot 与 Segment 必须同时为空或同时非空。")
    positions = {shot.id: index for index, shot in enumerate(scene.shots)}
    previous_last: int | None = None
    for segment in scene.segments:
        if any(shot_id not in positions for shot_id in segment.shot_ids):
            raise ValueError(f"{label} 的 Segment 覆盖了不属于本 Scene 的 Shot。")
        indexes = [positions[shot_id] for shot_id in segment.shot_ids]
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise ValueError(f"{label} 的 Segment 必须覆盖按顺序连续的 Shot。")
        expected_new = 0 if previous_last is None else previous_last + 1
        shares = previous_last is not None and indexes[0] == previous_last
        if not shares and indexes[0] != expected_new:
            raise ValueError(
                f"{label} 的 Segment 必须按顺序覆盖全部 Shot，不能跳过、倒序或重复覆盖。"
            )
        if shares and segment.boundary_from_previous is None:
            raise ValueError(f"{label} 延续上一 Segment 镜头的 Segment 必须说明前置边界。")
        if not shares and segment.boundary_from_previous is not None:
            raise ValueError(f"{label} 不延续上一 Segment 镜头的 Segment 不能包含前置边界。")
        previous_last = indexes[-1]
    if previous_last is not None and previous_last != len(scene.shots) - 1:
        raise ValueError(f"{label} 的 Segment 必须覆盖全部 Shot。")


@dataclass(frozen=True, slots=True)
class DirectorScript:
    revision: int
    source_reference_revision: int
    production_baseline_revision: int | None
    production_baseline_scenes: tuple[Scene, ...] | None
    scenes: tuple[Scene, ...]

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("director_script.revision 必须是正整数。")
        if isinstance(self.source_reference_revision, bool) or self.source_reference_revision < 1:
            raise ValueError("director_script.source_reference_revision 必须是正整数。")
        if self.production_baseline_revision is not None and (
            isinstance(self.production_baseline_revision, bool)
            or not 1 <= self.production_baseline_revision <= self.revision
        ):
            raise ValueError("director_script.production_baseline_revision 不合法。")
        if (self.production_baseline_revision is None) != (self.production_baseline_scenes is None):
            raise ValueError("生产基线 revision 和完整脚本快照必须同时存在。")
        if not self.scenes:
            raise ValueError("结构化导演脚本至少需要一个 Scene。")
        if len(self.scenes) > 100:
            raise ValueError("结构化导演脚本 Scene 过多。")
        ids: list[str] = []
        shot_count = 0
        segment_count = 0
        for scene in self.scenes:
            ids.append(scene.id)
            ids.extend(cue.id for cue in scene.narration_cues)
            shot_count += len(scene.shots)
            segment_count += len(scene.segments)
            ids.extend(shot.id for shot in scene.shots)
            ids.extend(segment.id for segment in scene.segments)
        if shot_count > 1_000 or segment_count > 2_000:
            raise ValueError("结构化导演脚本规模过大。")
        if len(ids) != len(set(ids)):
            raise ValueError("Scene、Shot、Segment 和旁白 Cue ID 不能重复。")
        if self.production_baseline_scenes is not None:
            _validate_script_scenes(self.production_baseline_scenes, "生产基线")


@dataclass(frozen=True, slots=True)
class PendingScriptEdit:
    base_script_revision: int
    user_message: str

    def __post_init__(self) -> None:
        if isinstance(self.base_script_revision, bool) or self.base_script_revision < 1:
            raise ValueError("pending_script_edit.base_script_revision 不合法。")
        _require_text(self.user_message, "pending_script_edit.user_message", 20_000)


@dataclass(frozen=True, slots=True)
class CapabilityGapRepairOperation:
    entity_type: str
    entity_id: str
    fields: dict[str, str | float | None]

    def __post_init__(self) -> None:
        if self.entity_type not in {"scene", "shot", "segment"}:
            raise ValueError("capability gap operation entity_type 不合法。")
        _require_id(self.entity_id, "capability_gap.operation.entity_id")
        if not self.fields:
            raise ValueError("capability gap operation fields 不能为空。")
        allowed = {
            "scene": {"title", "summary", "setting"},
            "shot": {
                "composition",
                "camera_movement",
                "action",
                "audio_direction",
                "transition_in",
            },
            "segment": {"duration_estimate_seconds", "action"},
        }[self.entity_type]
        if not set(self.fields) <= allowed:
            raise ValueError("capability gap operation fields 不合法。")
        for name, value in self.fields.items():
            if name == "duration_estimate_seconds":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not isfinite(value)
                    or value <= 0
                ):
                    raise ValueError("capability gap duration 不合法。")
            elif name == "transition_in" and value is None:
                continue
            elif not isinstance(value, str):
                raise ValueError("capability gap 文本字段不合法。")


@dataclass(frozen=True, slots=True)
class CapabilityGapAlert:
    gap_id: str
    command_id: str
    command_ids: tuple[str, ...]
    run_id: str
    missing_command: str
    raw_user_request_summary: str
    target_ids: tuple[str, ...]
    scope_scene_ids: tuple[str, ...]
    operations: tuple[CapabilityGapRepairOperation, ...]
    reverse_operations: tuple[CapabilityGapRepairOperation, ...]
    operation_summary: str
    old_revision: int
    new_revision: int
    result: CapabilityGapResult
    first_occurred_at: str
    last_occurred_at: str
    occurrence_count: int
    closed_revision: int | None = None
    closed_by_command: str | None = None
    status: CapabilityGapStatus = CapabilityGapStatus.OPEN

    def __post_init__(self) -> None:
        _require_id(self.gap_id, "capability_gap.gap_id")
        _require_id(self.command_id, "capability_gap.command_id")
        _validate_unique_ids(self.command_ids, "capability_gap.command_ids")
        if not self.command_ids or self.command_id not in self.command_ids:
            raise ValueError("capability gap command_ids 不完整。")
        _require_text(self.run_id, "capability_gap.run_id", 200)
        if _COMMAND_NAME.fullmatch(self.missing_command) is None:
            raise ValueError("capability_gap.missing_command 不合法。")
        _require_text(
            self.raw_user_request_summary,
            "capability_gap.raw_user_request_summary",
            500,
        )
        _validate_unique_ids(self.target_ids, "capability_gap.target_ids")
        _validate_unique_ids(self.scope_scene_ids, "capability_gap.scope_scene_ids")
        if not self.scope_scene_ids or not self.operations or not self.reverse_operations:
            raise ValueError("capability gap 的 scope 和 repair operations 不能为空。")
        _require_text(self.operation_summary, "capability_gap.operation_summary", 2_000)
        if (
            isinstance(self.old_revision, bool)
            or isinstance(self.new_revision, bool)
            or self.old_revision < 1
            or self.new_revision < self.old_revision
        ):
            raise ValueError("capability gap revision 不合法。")
        for value in (self.first_occurred_at, self.last_occurred_at):
            try:
                datetime.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("capability gap 时间不合法。") from exc
        if self.last_occurred_at < self.first_occurred_at:
            raise ValueError("capability gap 时间顺序不合法。")
        if isinstance(self.occurrence_count, bool) or self.occurrence_count < 1:
            raise ValueError("capability gap occurrence_count 不合法。")
        if self.status is CapabilityGapStatus.OPEN:
            if self.closed_revision is not None or self.closed_by_command is not None:
                raise ValueError("open capability gap 不能包含关闭信息。")
        elif (
            self.closed_revision is None
            or self.closed_revision < self.new_revision
            or self.closed_by_command is None
            or _COMMAND_NAME.fullmatch(self.closed_by_command) is None
        ):
            raise ValueError("closed capability gap 必须包含有效关闭审计。")


def _validate_script_scenes(scenes: tuple[Scene, ...], label: str) -> None:
    if not scenes:
        raise ValueError(f"{label}至少需要一个 Scene。")
    ids: list[str] = []
    for scene in scenes:
        ids.append(scene.id)
        ids.extend(shot.id for shot in scene.shots)
        ids.extend(segment.id for segment in scene.segments)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label}中的 Scene、Shot 和 Segment ID 不能重复。")
