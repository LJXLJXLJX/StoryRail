from __future__ import annotations

from importlib import import_module

from .models import (
    Asset,
    CapabilityGapAlert,
    CapabilityGapRepairOperation,
    CapabilityGapResult,
    CapabilityGapStatus,
    CharacterCard,
    CharacterLook,
    DialogueLine,
    DirectorAuthorization,
    DirectorCandidateSelectionPolicy,
    DirectorCommandReceipt,
    DirectorDirective,
    DirectorRun,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
    DirectorScript,
    FinalApproval,
    FinalAssemblyClip,
    FinalAssemblyPlan,
    FinalNarrationPlacement,
    FinalTransition,
    GenerationOperation,
    ImageAssetCategory,
    Keyframe,
    KeyframePlan,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    NarratorProfile,
    NarratorVoice,
    PendingNarrationEdit,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    Scene,
    SceneAssemblyClip,
    SceneAssemblyPlan,
    SegmentBoundary,
    SegmentBoundaryReason,
    SegmentKeyframes,
    SegmentVideo,
    Shot,
    ShotSegment,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    VideoPlan,
)
from .schema import PROJECT_SCHEMA_VERSION

# JsonResponse / StructuredDirectorHttpApi / StructuredDirectorService /
# StructuredDirectorStore 属 L6/L7 装配与 HTTP 边缘；包内改为按名懒加载
# （PEP 562），避免 core.director_commands.registry 模块级引用 L5 proposal
# 工作流时与 service/store 发生包初始化环。首次属性访问即完成原 eager import。
_LAZY_EXPORTS = {
    "JsonResponse": ".http_api",
    "StructuredDirectorHttpApi": ".http_api",
    "StructuredDirectorService": ".service",
    "StructuredDirectorStore": ".store",
}


def __getattr__(name: str):
    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


__all__ = [
    "Asset",
    "CapabilityGapAlert",
    "CapabilityGapRepairOperation",
    "CapabilityGapResult",
    "CapabilityGapStatus",
    "CharacterCard",
    "CharacterLook",
    "DialogueLine",
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
    "Keyframe",
    "KeyframePlan",
    "JsonResponse",
    "NarrationCue",
    "NarrationLanguage",
    "NarrationTrack",
    "NarratorProfile",
    "NarratorVoice",
    "PendingNarrationEdit",
    "PROJECT_SCHEMA_VERSION",
    "ReferenceGeneration",
    "ReferenceGenerationKind",
    "ReferenceGenerationPhase",
    "ReferenceLibrary",
    "Scene",
    "SceneAssemblyClip",
    "SceneAssemblyPlan",
    "SegmentKeyframes",
    "SegmentVideo",
    "SegmentBoundary",
    "SegmentBoundaryReason",
    "Shot",
    "ShotSegment",
    "StructuredDirectorDocument",
    "StructuredDirectorStatus",
    "StructuredDirectorHttpApi",
    "StructuredDirectorService",
    "StructuredDirectorStore",
    "VideoPlan",
]
