"""领域模型：final 域。Scene 成片与最终成片按项目所选旁白语言各出一版。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from ._shared import NarrationLanguage, _require_id


class FinalTransition(StrEnum):
    SEAM_BLEND = "seam_blend"


@dataclass(frozen=True, slots=True)
class SceneAssemblyClip:
    """Scene 成片内部的 Segment 片段；只在渲染 Scene 成片时临时构建，不进入 project.json。"""

    segment_id: str
    asset_id: str
    transition_from_previous: FinalTransition | None

    def __post_init__(self) -> None:
        _require_id(self.segment_id, "scene_assembly.clip.segment_id")
        _require_id(self.asset_id, "scene_assembly.clip.asset_id")


@dataclass(frozen=True, slots=True)
class FinalNarrationPlacement:
    cue_id: str
    asset_id: str
    start_segment_id: str
    # 画面对齐使用的时间基准：中英已选旁白中较长的真实时长。
    timing_seconds: float = 0.0
    # 旁白在 Scene 画面里居中：相对首个 Segment 起点的延迟秒数。
    start_offset_seconds: float = 0.0

    def __post_init__(self) -> None:
        _require_id(self.cue_id, "scene_assembly.narration.cue_id")
        _require_id(self.asset_id, "scene_assembly.narration.asset_id")
        _require_id(self.start_segment_id, "scene_assembly.narration.start_segment_id")


@dataclass(frozen=True, slots=True)
class SceneAssemblyPlan:
    """单个 Scene 某一语言的成片装配计划：Segment 视频加该语言旁白，不持久化。

    画面时间轴按中英较长的旁白对齐，因此两种语言的已选旁白都是该成片的输入
    （``timing_asset_ids``）；任一语言回改都会让两版 Scene 成片同时过期。
    """

    source_script_revision: int
    clips: tuple[SceneAssemblyClip, ...]
    narrations: tuple[FinalNarrationPlacement, ...]
    language: NarrationLanguage = NarrationLanguage.ZH
    timing_asset_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_script_revision, bool) or self.source_script_revision < 1:
            raise ValueError("scene_assembly.source_script_revision 不合法。")
        segment_ids = [item.segment_id for item in self.clips]
        if not segment_ids or len(segment_ids) != len(set(segment_ids)):
            raise ValueError("Scene 成片必须包含按时间排序且不重复的 Segment。")
        if self.clips[0].transition_from_previous is not None:
            raise ValueError("Scene 成片的首个片段不能包含入场转场。")
        cue_ids = [item.cue_id for item in self.narrations]
        if len(cue_ids) != len(set(cue_ids)):
            raise ValueError("同一旁白 Cue 不能在 Scene 成片中重复装配。")
        if not {item.start_segment_id for item in self.narrations} <= set(segment_ids):
            raise ValueError("旁白起点必须引用 Scene 成片中的 Segment。")


@dataclass(frozen=True, slots=True)
class FinalAssemblyClip:
    """最终成片的一个片段：同一 Scene 的中文版与英文版 Scene 成片 Asset。"""

    scene_id: str
    zh_asset_id: str | None
    en_asset_id: str | None
    transition_from_previous: FinalTransition | None

    def __post_init__(self) -> None:
        _require_id(self.scene_id, "final_assembly.clip.scene_id")
        if self.zh_asset_id is not None:
            _require_id(self.zh_asset_id, "final_assembly.clip.zh_asset_id")
        if self.en_asset_id is not None:
            _require_id(self.en_asset_id, "final_assembly.clip.en_asset_id")

    def asset_id(self, language: NarrationLanguage) -> str | None:
        return self.zh_asset_id if language is NarrationLanguage.ZH else self.en_asset_id


@dataclass(frozen=True, slots=True)
class FinalAssemblyPlan:
    """最终成片只拼接 Scene 成片；项目所选语言的单语成片共享画面，各自选择候选。"""

    source_script_revision: int
    clips: tuple[FinalAssemblyClip, ...]
    selected_zh_asset_id: str | None = None
    selected_en_asset_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_script_revision, bool) or self.source_script_revision < 1:
            raise ValueError("final_assembly.source_script_revision 不合法。")
        scene_ids = [item.scene_id for item in self.clips]
        if not scene_ids or len(scene_ids) != len(set(scene_ids)):
            raise ValueError("最终成片必须包含按脚本顺序且不重复的 Scene。")
        if self.clips[0].transition_from_previous is not None:
            raise ValueError("首个成片片段不能包含入场转场。")
        for label, value in (
            ("final_assembly.selected_zh_asset_id", self.selected_zh_asset_id),
            ("final_assembly.selected_en_asset_id", self.selected_en_asset_id),
        ):
            if value is not None:
                _require_id(value, label)

    def selected_asset_id(self, language: NarrationLanguage) -> str | None:
        return (
            self.selected_zh_asset_id
            if language is NarrationLanguage.ZH
            else self.selected_en_asset_id
        )

    def with_selection(
        self, language: NarrationLanguage, asset_id: str | None
    ) -> FinalAssemblyPlan:
        return replace(self, **{f"selected_{language.value}_asset_id": asset_id})


@dataclass(frozen=True, slots=True)
class FinalApproval:
    """一次 Approval 同时批准项目所选语言的单语成片的精确 Asset。"""

    zh_asset_id: str | None
    zh_generation_id: str | None
    en_asset_id: str | None
    en_generation_id: str | None
    source_script_revision: int
    approved_project_revision: int

    def __post_init__(self) -> None:
        if self.zh_asset_id is not None:
            _require_id(self.zh_asset_id, "final_approval.zh_asset_id")
        if self.zh_generation_id is not None:
            _require_id(self.zh_generation_id, "final_approval.zh_generation_id")
        if self.en_asset_id is not None:
            _require_id(self.en_asset_id, "final_approval.en_asset_id")
        if self.en_generation_id is not None:
            _require_id(self.en_generation_id, "final_approval.en_generation_id")
        if isinstance(self.source_script_revision, bool) or self.source_script_revision < 1:
            raise ValueError("final_approval.source_script_revision 不合法。")
        if isinstance(self.approved_project_revision, bool) or self.approved_project_revision < 1:
            raise ValueError("final_approval.approved_project_revision 不合法。")

    def asset_id(self, language: NarrationLanguage) -> str | None:
        return self.zh_asset_id if language is NarrationLanguage.ZH else self.en_asset_id

    def generation_id(self, language: NarrationLanguage) -> str | None:
        return self.zh_generation_id if language is NarrationLanguage.ZH else self.en_generation_id
