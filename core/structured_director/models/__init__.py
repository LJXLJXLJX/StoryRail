"""StoryRail 结构化导演领域模型（L0）。

原 models.py 按域拆包；本模块再导出全部名字，
`from core.structured_director.models import X` 路径不变。
"""

from ._shared import MAX_IMAGE_INPUTS as MAX_IMAGE_INPUTS
from ._shared import GenerationOperation as GenerationOperation
from ._shared import ReferenceGenerationKind as ReferenceGenerationKind
from ._shared import ReferenceGenerationPhase as ReferenceGenerationPhase
from ._shared import StructuredDirectorStatus as StructuredDirectorStatus
from .asset import Asset as Asset
from .asset import AssetDeletionClosure as AssetDeletionClosure
from .asset import AssetUsageReason as AssetUsageReason
from .asset import ImageAssetCategory as ImageAssetCategory
from .asset import asset_deletion_closure as asset_deletion_closure
from .asset import asset_has_project_reference as asset_has_project_reference
from .asset import asset_project_usage_reasons as asset_project_usage_reasons
from .asset import asset_usage_reasons as asset_usage_reasons
from .asset import discarded_asset_deletion_closure as discarded_asset_deletion_closure
from .dialogue import DialogueAudio as DialogueAudio
from .dialogue import DialoguePlan as DialoguePlan
from .document import StructuredDirectorDocument as StructuredDirectorDocument
from .document import WorkspaceLayers as WorkspaceLayers
from .final import FinalApproval as FinalApproval
from .final import FinalAssemblyClip as FinalAssemblyClip
from .final import FinalAssemblyPlan as FinalAssemblyPlan
from .final import FinalNarrationPlacement as FinalNarrationPlacement
from .final import FinalTransition as FinalTransition
from .final import SceneAssemblyClip as SceneAssemblyClip
from .final import SceneAssemblyPlan as SceneAssemblyPlan
from .generation import ReferenceGeneration as ReferenceGeneration
from .generation import transition_generation as transition_generation
from .keyframe import Keyframe as Keyframe
from .keyframe import KeyframeCharacterReference as KeyframeCharacterReference
from .keyframe import KeyframeEnvironmentMode as KeyframeEnvironmentMode
from .keyframe import KeyframePlan as KeyframePlan
from .keyframe import SegmentKeyframes as SegmentKeyframes
from .keyframe import blank_keyframe as blank_keyframe
from .keyframe import (
    normalize_environment_none_reason as normalize_environment_none_reason,
)
from .keyframe import prune_character_references as prune_character_references
from .location import Location as Location
from .location import LocationCropRequest as LocationCropRequest
from .location import LocationFixture as LocationFixture
from .location import LocationKeyLight as LocationKeyLight
from .location import LocationKind as LocationKind
from .location import LocationLibrary as LocationLibrary
from .location import LocationMaster as LocationMaster
from .location import LocationState as LocationState
from .location import LocationView as LocationView
from .narration import NARRATION_LANGUAGES as NARRATION_LANGUAGES
from .narration import NarrationCue as NarrationCue
from .narration import NarrationLanguage as NarrationLanguage
from .narration import NarrationTrack as NarrationTrack
from .narration import PendingNarrationEdit as PendingNarrationEdit
from .reference import MAX_CHARACTER_LOOKS as MAX_CHARACTER_LOOKS
from .reference import CharacterCard as CharacterCard
from .reference import CharacterLook as CharacterLook
from .reference import NarratorProfile as NarratorProfile
from .reference import NarratorVoice as NarratorVoice
from .reference import ReferenceLibrary as ReferenceLibrary
from .run import DirectorAuthorization as DirectorAuthorization
from .run import DirectorCandidateSelectionPolicy as DirectorCandidateSelectionPolicy
from .run import DirectorCommandReceipt as DirectorCommandReceipt
from .run import DirectorDirective as DirectorDirective
from .run import DirectorRun as DirectorRun
from .run import DirectorRunCursor as DirectorRunCursor
from .run import DirectorRunKind as DirectorRunKind
from .run import DirectorRunStatus as DirectorRunStatus
from .script import CapabilityGapAlert as CapabilityGapAlert
from .script import CapabilityGapRepairOperation as CapabilityGapRepairOperation
from .script import CapabilityGapResult as CapabilityGapResult
from .script import CapabilityGapStatus as CapabilityGapStatus
from .script import DialogueLine as DialogueLine
from .script import DirectorScript as DirectorScript
from .script import PendingScriptEdit as PendingScriptEdit
from .script import Scene as Scene
from .script import SegmentBoundary as SegmentBoundary
from .script import SegmentBoundaryReason as SegmentBoundaryReason
from .script import Shot as Shot
from .script import ShotSegment as ShotSegment
from .video import SegmentVideo as SegmentVideo
from .video import VideoPlan as VideoPlan

__all__ = [
    "Asset",
    "AssetDeletionClosure",
    "AssetUsageReason",
    "CapabilityGapAlert",
    "CapabilityGapRepairOperation",
    "CapabilityGapResult",
    "CapabilityGapStatus",
    "CharacterCard",
    "CharacterLook",
    "MAX_CHARACTER_LOOKS",
    "DialogueLine",
    "DialogueAudio",
    "DialoguePlan",
    "DirectorAuthorization",
    "DirectorCandidateSelectionPolicy",
    "DirectorCommandReceipt",
    "DirectorDirective",
    "DirectorRun",
    "DirectorRunCursor",
    "DirectorRunKind",
    "DirectorRunStatus",
    "DirectorScript",
    "FinalApproval",
    "FinalAssemblyClip",
    "FinalAssemblyPlan",
    "FinalNarrationPlacement",
    "FinalTransition",
    "GenerationOperation",
    "ImageAssetCategory",
    "blank_keyframe",
    "Keyframe",
    "KeyframeCharacterReference",
    "KeyframeEnvironmentMode",
    "KeyframePlan",
    "Location",
    "LocationCropRequest",
    "LocationFixture",
    "LocationKeyLight",
    "LocationKind",
    "LocationLibrary",
    "LocationMaster",
    "LocationState",
    "LocationView",
    "MAX_IMAGE_INPUTS",
    "NARRATION_LANGUAGES",
    "NarrationCue",
    "NarrationLanguage",
    "NarrationTrack",
    "NarratorProfile",
    "NarratorVoice",
    "PendingNarrationEdit",
    "PendingScriptEdit",
    "ReferenceGeneration",
    "ReferenceGenerationKind",
    "ReferenceGenerationPhase",
    "ReferenceLibrary",
    "Scene",
    "SceneAssemblyClip",
    "SceneAssemblyPlan",
    "SegmentBoundary",
    "SegmentBoundaryReason",
    "SegmentKeyframes",
    "SegmentVideo",
    "Shot",
    "ShotSegment",
    "StructuredDirectorDocument",
    "StructuredDirectorStatus",
    "VideoPlan",
    "WorkspaceLayers",
    "asset_deletion_closure",
    "asset_has_project_reference",
    "asset_project_usage_reasons",
    "asset_usage_reasons",
    "discarded_asset_deletion_closure",
    "transition_generation",
    "prune_character_references",
    "normalize_environment_none_reason",
]

# 校验函数注入（P2-C1）：validation 需要 models 的类做 isinstance，models 的
# __post_init__ 又需要校验函数——静态双向依赖无解。包初始化在全部子模块
# 加载完成后导入 validation 并注入两个模型模块的全局；任何实例化路径都
# 先完成父包初始化，注入必然已发生。
from . import document as _document_module
from . import generation as _generation_module
from .validation import validate_document as validate_document
from .validation import validate_reference_generation as validate_reference_generation

_document_module._set_validator(validate_document)
_generation_module._set_validator(validate_reference_generation)
