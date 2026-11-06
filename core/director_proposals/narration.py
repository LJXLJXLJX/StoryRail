from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.model_providers.recipe import RecipeParams


def validate_recipe_params_shape(value: object, label: str) -> None:
    """只校验 recipe_params 的结构；参数是否符合当前 recipe 由 Core 写入时按 manifest 校验。"""
    RecipeParams.from_json(value, label)


NARRATION_LANGUAGE_VALUES = ("zh", "en")


@dataclass(frozen=True, slots=True)
class NarrationTrackContext:
    language: str
    text: str
    recipe_params: dict[str, Any]
    seed: int
    has_selected_audio: bool


@dataclass(frozen=True, slots=True)
class NarrationCueContext:
    id: str
    scene_title: str
    coverage: str
    tracks: tuple[NarrationTrackContext, ...]


@dataclass(frozen=True, slots=True)
class NarrationCueUpdate:
    """更新单条 Cue 某一语言（zh / en）的 seed 与按 recipe 的合成参数（逐 recipe 合并）。"""

    cue_id: str
    language: str
    seed: int
    regenerate: bool
    recipe_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.language not in NARRATION_LANGUAGE_VALUES:
            raise ValueError("cue_updates[].language 只允许 zh 或 en。")
        validate_recipe_params_shape(self.recipe_params, "cue_updates[].recipe_params")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= 2**63 - 1
        ):
            raise ValueError("seed 不合法。")


@dataclass(frozen=True, slots=True)
class NarrationReviewProposal:
    reply_markdown: str
    cue_updates: tuple[NarrationCueUpdate, ...]

    def __post_init__(self) -> None:
        if not self.reply_markdown.strip() or len(self.reply_markdown) > 10_000:
            raise ValueError("reply_markdown 不合法。")
        ids = [(item.cue_id, item.language) for item in self.cue_updates]
        if len(ids) != len(set(ids)):
            raise ValueError("同一 Cue 的同一语言不能重复更新。")
