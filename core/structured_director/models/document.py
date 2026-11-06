"""领域模型：document 域（从 models.py 纯移动，校验已抽至 models/validation）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._shared import NarrationLanguage, StructuredDirectorStatus
from .location import LocationLibrary
from .run import DirectorRunStatus

if TYPE_CHECKING:
    from core.application.requests import ApplicationRequest
    from core.project_settings import ProjectAspectRatio

    from .asset import Asset
    from .dialogue import DialoguePlan
    from .final import FinalApproval, FinalAssemblyPlan
    from .generation import ReferenceGeneration
    from .keyframe import KeyframePlan
    from .narration import PendingNarrationEdit
    from .reference import ReferenceLibrary
    from .run import DirectorDirective, DirectorRun
    from .script import CapabilityGapAlert, DirectorScript, PendingScriptEdit
    from .video import VideoPlan


@dataclass(frozen=True, slots=True)
class WorkspaceLayers:
    narration_unlocked: bool = False
    keyframes_unlocked: bool = False
    videos_unlocked: bool = False
    final_assembly_unlocked: bool = False

    def __post_init__(self) -> None:
        values = (
            self.narration_unlocked,
            self.keyframes_unlocked,
            self.videos_unlocked,
            self.final_assembly_unlocked,
        )
        if not all(isinstance(value, bool) for value in values):
            raise ValueError("workspace_layers 字段必须是布尔值。")
        if self.keyframes_unlocked and not self.narration_unlocked:
            raise ValueError("Keyframe 层不能早于旁白层解锁。")
        if self.videos_unlocked and not self.keyframes_unlocked:
            raise ValueError("视频层不能早于 Keyframe 层解锁。")
        if self.final_assembly_unlocked and not self.videos_unlocked:
            raise ValueError("成片层不能早于视频层解锁。")


@dataclass(frozen=True, slots=True)
class StructuredDirectorDocument:
    schema_version: int
    project_id: str
    revision: int
    title: str
    aspect_ratio: ProjectAspectRatio
    director_plan_markdown: str
    narration_languages: tuple[NarrationLanguage, ...]
    status: StructuredDirectorStatus
    workspace_layers: WorkspaceLayers
    reference_library: ReferenceLibrary
    assets: tuple[Asset, ...] = ()
    generations: tuple[ReferenceGeneration, ...] = ()
    director_script: DirectorScript | None = None
    pending_script_edit: PendingScriptEdit | None = None
    pending_narration_edit: PendingNarrationEdit | None = None
    dialogue_plan: DialoguePlan | None = None
    location_library: LocationLibrary = field(default_factory=LocationLibrary)
    keyframe_plan: KeyframePlan | None = None
    video_plan: VideoPlan | None = None
    final_assembly: FinalAssemblyPlan | None = None
    final_approval: FinalApproval | None = None
    capability_gap_alerts: tuple[CapabilityGapAlert, ...] = ()
    director_runs: tuple[DirectorRun, ...] = ()
    director_directives: tuple[DirectorDirective, ...] = ()
    application_requests: tuple[ApplicationRequest, ...] = ()

    @property
    def active_director_run(self) -> DirectorRun | None:
        active = [
            item
            for item in self.director_runs
            if item.status
            in {
                DirectorRunStatus.RUNNING,
                DirectorRunStatus.WAITING_USER,
                DirectorRunStatus.WAITING_JOBS,
            }
        ]
        return active[0] if active else None

    @property
    def is_reviewing(self) -> bool:
        return self.status in {
            StructuredDirectorStatus.REVIEWING,
            StructuredDirectorStatus.REVIEWING_SCRIPT,
            StructuredDirectorStatus.REVIEWING_NARRATION,
            StructuredDirectorStatus.REVIEWING_KEYFRAMES,
            StructuredDirectorStatus.REVIEWING_VIDEOS,
            StructuredDirectorStatus.REVIEWING_FINAL,
        }

    @property
    def review_status(self) -> StructuredDirectorStatus:
        """临时任务结束后回到最深已解锁层，不以产物是否有效推断能力。"""
        for unlocked, status in (
            (
                self.workspace_layers.final_assembly_unlocked,
                StructuredDirectorStatus.REVIEWING_FINAL,
            ),
            (self.workspace_layers.videos_unlocked, StructuredDirectorStatus.REVIEWING_VIDEOS),
            (
                self.workspace_layers.keyframes_unlocked,
                StructuredDirectorStatus.REVIEWING_KEYFRAMES,
            ),
            (
                self.workspace_layers.narration_unlocked,
                StructuredDirectorStatus.REVIEWING_NARRATION,
            ),
        ):
            if unlocked:
                return status
        return (
            StructuredDirectorStatus.REVIEWING_SCRIPT
            if self.director_script is not None
            else StructuredDirectorStatus.REVIEWING
        )

    def __post_init__(self) -> None:
        validate_document(self)


def _set_validator(validate) -> None:
    """由 models/__init__ 在包加载末尾注入校验函数（避免静态 import 环）。"""
    global validate_document
    validate_document = validate
