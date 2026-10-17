from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from .narration import validate_recipe_params_shape

_BOUNDARY_REASONS = {
    "model_constraint",
    "continuity_anchor",
    "control_boundary",
    "failure_cost",
}


@dataclass(frozen=True, slots=True)
class StructuredReferenceCharacter:
    id: str
    name: str
    visual_description: str | None
    # 角色各套造型的“名称：使用场合”，按卡片顺序；脚本据此知道角色在哪些时期换装。
    looks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DialogueLineProposal:
    # 引用库角色写 character_id；引用库外的临时/画外说话者写 character_id=null 与 speaker_label。
    character_id: str | None
    text: str
    delivery: str
    speaker_label: str | None = None

    def __post_init__(self) -> None:
        if (self.character_id is None) == (self.speaker_label is None):
            raise ValueError("dialogue_line 必须且只能提供 character_id 或 speaker_label 之一。")
        if self.character_id is not None:
            _require_text(self.character_id, "dialogue_line.character_id", 32)
        else:
            _require_text(self.speaker_label or "", "dialogue_line.speaker_label", 60)
        _require_text(self.text, "dialogue_line.text", 2_000)
        if len(self.delivery) > 1_000:
            raise ValueError("dialogue_line.delivery 过长。")


@dataclass(frozen=True, slots=True)
class SegmentBoundaryProposal:
    reason: str
    continuity_instruction: str

    def __post_init__(self) -> None:
        if self.reason not in _BOUNDARY_REASONS:
            raise ValueError("boundary.reason 不合法。")
        _require_text(
            self.continuity_instruction,
            "boundary.continuity_instruction",
            2_000,
        )


@dataclass(frozen=True, slots=True)
class ShotSegmentProposal:
    duration_estimate_seconds: float
    action: str
    dialogue_lines: tuple[DialogueLineProposal, ...]
    boundary_from_previous: SegmentBoundaryProposal | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.duration_estimate_seconds, bool)
            or not isfinite(self.duration_estimate_seconds)
            or self.duration_estimate_seconds < 0.2
        ):
            raise ValueError("segment.duration_estimate_seconds 不合法。")
        _require_text(self.action, "segment.action", 4_000)


@dataclass(frozen=True, slots=True)
class ShotProposal:
    visible_character_ids: tuple[str, ...]
    composition: str
    camera_movement: str
    action: str
    audio_direction: str
    transition_in: str | None
    segments: tuple[ShotSegmentProposal, ...]

    def __post_init__(self) -> None:
        if len(self.visible_character_ids) != len(set(self.visible_character_ids)):
            raise ValueError("shot.visible_character_ids 不能重复。")
        for character_id in self.visible_character_ids:
            _require_text(character_id, "shot.visible_character_ids", 32)
        _require_text(self.composition, "shot.composition", 4_000)
        _require_text(self.camera_movement, "shot.camera_movement", 2_000)
        _require_text(self.action, "shot.action", 4_000)
        if len(self.audio_direction) > 2_000:
            raise ValueError("shot.audio_direction 过长。")
        if self.transition_in is not None:
            _require_text(self.transition_in, "shot.transition_in", 500)
        if not self.segments:
            raise ValueError("每个 Shot 至少需要一个 Segment。")
        if self.segments[0].boundary_from_previous is not None:
            raise ValueError("Shot 的第一个 Segment 不能包含前置边界。")
        if any(item.boundary_from_previous is None for item in self.segments[1:]):
            raise ValueError("Shot 的后续 Segment 必须说明前置边界。")


@dataclass(frozen=True, slots=True)
class NarrationTrackProposal:
    """单一语言的旁白正文、seed 与按 recipe 的合成参数。英文是适合朗读的意译，不是逐字翻译。"""

    text: str
    seed: int
    recipe_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.text, "narration_track.text", 4_000)
        validate_recipe_params_shape(self.recipe_params, "narration_track.recipe_params")
        _validate_seed(self.seed)


@dataclass(frozen=True, slots=True)
class NarrationCueProposal:
    """旁白固定中英双语：zh 与 en 各自合成，时间以较长的一条为准。"""

    start_shot_index: int | None
    end_shot_index: int | None
    zh: NarrationTrackProposal | None
    en: NarrationTrackProposal | None

    def __post_init__(self) -> None:
        if self.zh is None and self.en is None:
            raise ValueError("旁白至少需要一种语言的正文。")
        if self.start_shot_index is None and self.end_shot_index is None:
            return
        if (
            self.start_shot_index is None
            or self.end_shot_index is None
            or isinstance(self.start_shot_index, bool)
            or isinstance(self.end_shot_index, bool)
            or self.start_shot_index < 0
            or self.end_shot_index < self.start_shot_index
        ):
            raise ValueError("narration_cue Shot 范围不合法。")


@dataclass(frozen=True, slots=True)
class SceneProposal:
    title: str
    summary: str
    setting: str
    shots: tuple[ShotProposal, ...]
    narration_cues: tuple[NarrationCueProposal, ...]
    driver: str = "drama"

    def __post_init__(self) -> None:
        _require_text(self.title, "scene.title", 300)
        _require_text(self.summary, "scene.summary", 4_000)
        _require_text(self.setting, "scene.setting", 4_000)
        _validate_scene_driver(self.driver, self.shots, self.narration_cues)
        _validate_scene_narration(self.shots, self.narration_cues)


@dataclass(frozen=True, slots=True)
class StructuredDirectorScriptProposal:
    scenes: tuple[SceneProposal, ...]

    def __post_init__(self) -> None:
        if not self.scenes:
            raise ValueError("结构化导演脚本至少需要一个 Scene。")


@dataclass(frozen=True, slots=True)
class EditableShotSegmentProposal:
    id: str | None
    duration_estimate_seconds: float
    action: str
    dialogue_lines: tuple[DialogueLineProposal, ...]
    boundary_from_previous: SegmentBoundaryProposal | None


@dataclass(frozen=True, slots=True)
class EditableShotProposal:
    id: str | None
    visible_character_ids: tuple[str, ...]
    composition: str
    camera_movement: str
    action: str
    audio_direction: str
    transition_in: str | None
    segments: tuple[EditableShotSegmentProposal, ...]


@dataclass(frozen=True, slots=True)
class EditableNarrationCueProposal:
    id: str | None
    start_shot_index: int | None
    end_shot_index: int | None
    zh: NarrationTrackProposal | None
    en: NarrationTrackProposal | None


@dataclass(frozen=True, slots=True)
class EditableSceneProposal:
    id: str | None
    title: str
    summary: str
    setting: str
    shots: tuple[EditableShotProposal, ...]
    narration_cues: tuple[EditableNarrationCueProposal, ...]
    driver: str = "drama"


@dataclass(frozen=True, slots=True)
class ScriptRevisionOperationProposal:
    """Agent 对脚本提出的显式局部操作。"""

    operation: str
    scene_id: str | None = None
    after_scene_id: str | None = None
    scene: EditableSceneProposal | None = None
    shot_id: str | None = None
    segment: EditableShotSegmentProposal | None = None

    def __post_init__(self) -> None:
        if self.operation not in {
            "replace_scene",
            "insert_scene",
            "delete_scene",
            "move_scene",
            "replace_segment",
        }:
            raise ValueError("脚本 Scene 操作不合法。")
        if self.scene_id is not None:
            _require_text(self.scene_id, "operation.scene_id", 32)
        if self.after_scene_id is not None:
            _require_text(self.after_scene_id, "operation.after_scene_id", 32)
        if self.shot_id is not None:
            _require_text(self.shot_id, "operation.shot_id", 32)
        if self.segment is not None:
            ShotSegmentProposal(
                self.segment.duration_estimate_seconds,
                self.segment.action,
                self.segment.dialogue_lines,
                self.segment.boundary_from_previous,
            )
        if self.operation == "replace_scene":
            if (
                self.scene_id is None
                or self.scene is None
                or self.scene.id != self.scene_id
                or self.shot_id is not None
                or self.segment is not None
            ):
                raise ValueError("replace_scene 必须携带 ID 一致的已有 Scene。")
        elif self.operation == "insert_scene":
            if (
                self.scene_id is not None
                or self.scene is None
                or self.scene.id is not None
                or self.shot_id is not None
                or self.segment is not None
            ):
                raise ValueError("insert_scene 的新 Scene 必须使用 null ID。")
        elif self.operation == "delete_scene":
            if (
                self.scene_id is None
                or self.scene is not None
                or self.after_scene_id is not None
                or self.shot_id is not None
                or self.segment is not None
            ):
                raise ValueError("delete_scene 只能指定已有 Scene ID。")
        elif self.operation == "move_scene" and (
            self.scene_id is None
            or self.scene is not None
            or self.scene_id == self.after_scene_id
            or self.shot_id is not None
            or self.segment is not None
        ):
            raise ValueError("move_scene 必须指定不同的 Scene 与锚点。")
        elif self.operation == "replace_segment" and (
            self.scene_id is None
            or self.shot_id is None
            or self.segment is None
            or self.segment.id is None
            or self.scene is not None
            or self.after_scene_id is not None
        ):
            raise ValueError("replace_segment 必须指定 Scene、Shot 和已有 Segment。")


@dataclass(frozen=True, slots=True)
class StructuredDirectorScriptRevisionProposal:
    reply_markdown: str
    scenes: tuple[EditableSceneProposal, ...] = ()
    operations: tuple[ScriptRevisionOperationProposal, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.reply_markdown, "reply_markdown", 10_000)
        if self.scenes and self.operations:
            raise ValueError("完整脚本替换与局部操作不能混用。")
        if self.scenes:
            _validate_optional_ids(self.scenes)
        for operation in self.operations:
            if operation.scene is not None:
                _validate_optional_ids((operation.scene,))


def _require_text(value: str, field: str, maximum: int) -> None:
    if not value.strip():
        raise ValueError(f"{field} 不能为空。")
    if len(value) > maximum:
        raise ValueError(f"{field} 过长。")


def _validate_optional_ids(scenes: tuple[EditableSceneProposal, ...]) -> None:
    ids: list[str] = []
    for scene in scenes:
        if scene.id is not None:
            _require_text(scene.id, "scene.id", 32)
            ids.append(scene.id)
        _require_text(scene.title, "scene.title", 300)
        _require_text(scene.summary, "scene.summary", 4_000)
        _require_text(scene.setting, "scene.setting", 4_000)
        _validate_scene_driver(scene.driver, scene.shots, scene.narration_cues)
        for shot in scene.shots:
            if shot.id is not None:
                _require_text(shot.id, "shot.id", 32)
                ids.append(shot.id)
            _require_text(shot.composition, "shot.composition", 4_000)
            _require_text(shot.camera_movement, "shot.camera_movement", 2_000)
            _require_text(shot.action, "shot.action", 4_000)
            if not shot.segments:
                raise ValueError("每个 Shot 至少需要一个 Segment。")
            for index, segment in enumerate(shot.segments):
                if segment.id is not None:
                    _require_text(segment.id, "segment.id", 32)
                    ids.append(segment.id)
                if (
                    not isfinite(segment.duration_estimate_seconds)
                    or segment.duration_estimate_seconds < 0.2
                ):
                    raise ValueError("segment.duration_estimate_seconds 不合法。")
                _require_text(segment.action, "segment.action", 4_000)
                if index == 0 and segment.boundary_from_previous is not None:
                    raise ValueError("Shot 的第一个 Segment 不能包含前置边界。")
                if index > 0 and segment.boundary_from_previous is None:
                    raise ValueError("Shot 的后续 Segment 必须说明前置边界。")
        for cue in scene.narration_cues:
            if cue.id is not None:
                _require_text(cue.id, "narration_cue.id", 32)
                ids.append(cue.id)
            for track in (track for track in (cue.zh, cue.en) if track is not None):
                _require_text(track.text, "narration_track.text", 4_000)
                _validate_seed(track.seed)
                validate_recipe_params_shape(track.recipe_params, "narration_track.recipe_params")
            if scene.shots and (
                cue.start_shot_index is None
                or cue.end_shot_index is None
                or isinstance(cue.start_shot_index, bool)
                or isinstance(cue.end_shot_index, bool)
                or cue.start_shot_index < 0
                or cue.end_shot_index < cue.start_shot_index
                or cue.end_shot_index >= len(scene.shots)
            ):
                raise ValueError("旁白 Cue 的 Shot 范围不合法。")
        _validate_scene_narration(scene.shots, scene.narration_cues)
    if len(ids) != len(set(ids)):
        raise ValueError("Agent 脚本 proposal 中的已有 ID 不能重复。")


def _validate_scene_narration(
    shots: tuple[ShotProposal | EditableShotProposal, ...],
    cues: tuple[NarrationCueProposal | EditableNarrationCueProposal, ...],
) -> None:
    if len(cues) > 1:
        raise ValueError("每个 Scene 最多只能有一段旁白。")
    if not cues:
        return
    cue = cues[0]
    if not shots:
        if cue.start_shot_index is not None or cue.end_shot_index is not None:
            raise ValueError("未规划 Shot 的旁白必须使用 null 锚点。")
        return
    if cue.start_shot_index != 0 or cue.end_shot_index != len(shots) - 1:
        raise ValueError("Scene 旁白必须覆盖本 Scene 的全部 Shot。")


def _validate_seed(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise ValueError("seed 不合法。")


def _validate_scene_driver(driver: str, shots: tuple, cues: tuple) -> None:
    if driver not in {"narration", "drama"}:
        raise ValueError("Scene driver 必须是 narration 或 drama。")
    if driver == "narration":
        if len(cues) != 1:
            raise ValueError("Narration Scene 必须包含一个语义原子的旁白 Cue。")
        if any(segment.dialogue_lines for shot in shots for segment in shot.segments):
            raise ValueError("Narration Scene 不能包含对白；需要对白的内容请使用 Drama Scene。")
        return
    if cues:
        raise ValueError("Drama Scene 不能包含旁白；需要旁白的内容请使用 Narration Scene。")
    if not shots:
        raise ValueError("Drama Scene 至少需要一个 Shot。")
