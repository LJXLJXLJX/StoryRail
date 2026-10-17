"""领域模型：narration 域。旁白按项目所选语言建立，每种语言独立合成、审核与选择。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.model_providers.recipe import RecipeParams

from ._shared import NARRATION_LANGUAGES, NarrationLanguage, _require_id, _require_text

__all__ = [
    "NARRATION_LANGUAGES",
    "NarrationCue",
    "NarrationLanguage",
    "NarrationTrack",
    "PendingNarrationEdit",
]


@dataclass(frozen=True, slots=True)
class NarrationTrack:
    """单一语言的旁白正文、seed、按 recipe 保存的合成机制参数与已选音频。"""

    text: str
    seed: int
    selected_audio_asset_id: str | None = None
    recipe_params: RecipeParams = RecipeParams()

    def __post_init__(self) -> None:
        _require_text(self.text, "narration_track.text", 4_000)
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= 2**63 - 1
        ):
            raise ValueError("narration_track.seed 不合法。")
        if self.selected_audio_asset_id is not None:
            _require_id(self.selected_audio_asset_id, "narration_track.selected_audio_asset_id")
        if not isinstance(self.recipe_params, RecipeParams):
            raise ValueError("narration_track.recipe_params 不合法。")


@dataclass(frozen=True, slots=True)
class NarrationCue:
    id: str
    zh: NarrationTrack | None
    en: NarrationTrack | None

    def __post_init__(self) -> None:
        _require_id(self.id, "narration_cue.id")
        if not self.tracks or any(
            track is not None and not isinstance(track, NarrationTrack)
            for track in (self.zh, self.en)
        ):
            raise ValueError("narration_cue 至少包含一种有效语言的旁白。")

    def track(self, language: NarrationLanguage) -> NarrationTrack:
        track = self.zh if language is NarrationLanguage.ZH else self.en
        if track is None:
            raise ValueError("项目未启用该旁白语言。")
        return track

    def with_track(self, language: NarrationLanguage, track: NarrationTrack) -> NarrationCue:
        self.track(language)
        return replace(self, **{language.value: track})

    @property
    def tracks(self) -> tuple[tuple[NarrationLanguage, NarrationTrack], ...]:
        return tuple(
            (language, track)
            for language, track in (
                (NarrationLanguage.ZH, self.zh),
                (NarrationLanguage.EN, self.en),
            )
            if track is not None
        )

    @property
    def selected_audio_asset_ids(self) -> tuple[str, ...]:
        return tuple(
            track.selected_audio_asset_id
            for _, track in self.tracks
            if track.selected_audio_asset_id is not None
        )

    @property
    def fully_selected(self) -> bool:
        return all(track.selected_audio_asset_id is not None for _, track in self.tracks)


@dataclass(frozen=True, slots=True)
class PendingNarrationEdit:
    base_script_revision: int
    user_message: str

    def __post_init__(self) -> None:
        if isinstance(self.base_script_revision, bool) or self.base_script_revision < 1:
            raise ValueError("pending_narration_edit.base_script_revision 不合法。")
        _require_text(self.user_message, "pending_narration_edit.user_message", 20_000)
