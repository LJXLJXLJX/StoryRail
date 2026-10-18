"""对白 TTS 生产计划：逐句选择、合成参数与 Segment 内发声起点。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from core.model_providers.recipe import RecipeParams

from ._shared import _require_id


@dataclass(frozen=True, slots=True)
class DialogueAudio:
    dialogue_line_id: str
    seed: int
    recipe_params: RecipeParams = RecipeParams()
    selected_audio_asset_id: str | None = None
    start_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_id(self.dialogue_line_id, "dialogue_audio.dialogue_line_id")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= 2**32 - 1
        ):
            raise ValueError("dialogue_audio.seed 不合法。")
        if not isinstance(self.recipe_params, RecipeParams):
            raise ValueError("dialogue_audio.recipe_params 不合法。")
        if self.selected_audio_asset_id is not None:
            _require_id(self.selected_audio_asset_id, "dialogue_audio.selected_audio_asset_id")
        if self.start_seconds is not None and (
            isinstance(self.start_seconds, bool)
            or not isinstance(self.start_seconds, int | float)
            or not isfinite(self.start_seconds)
            or self.start_seconds < 0
        ):
            raise ValueError("dialogue_audio.start_seconds 必须是非负有限数值。")
        if self.start_seconds is not None and self.selected_audio_asset_id is None:
            raise ValueError("对白未选择音频时不能保存发声起点。")


@dataclass(frozen=True, slots=True)
class DialoguePlan:
    source_script_revision: int
    items: tuple[DialogueAudio, ...]

    def __post_init__(self) -> None:
        if isinstance(self.source_script_revision, bool) or self.source_script_revision < 1:
            raise ValueError("dialogue_plan.source_script_revision 不合法。")
        ids = [item.dialogue_line_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("对白生产计划不能包含重复 DialogueLine。")
