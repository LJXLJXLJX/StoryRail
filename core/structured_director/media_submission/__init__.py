"""按媒体能力拆开的提交用例。服务仍通过 MediaSubmissionUseCases 调用。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from core.model_providers.registry import ProviderRegistry

from ..provider_ports import (
    AnimaticProvider,
    FinalAssemblyProvider,
    PanoViewProvider,
    VideoFrameProvider,
)
from ..store import StructuredDirectorStore
from .animatic import AnimaticSubmission
from .assembly import AssemblySubmission
from .audio import AudioSubmission
from .dialogue import DialogueSubmission
from .frames import FrameSubmission
from .image import ImageSubmission
from .narration import NarrationSubmission
from .pano_view import PanoViewSubmission
from .video import VideoSubmission


@dataclass(slots=True)
class MediaSubmissionUseCases(
    AudioSubmission,
    NarrationSubmission,
    DialogueSubmission,
    ImageSubmission,
    VideoSubmission,
    FrameSubmission,
    PanoViewSubmission,
    AssemblySubmission,
    AnimaticSubmission,
):
    """Core use cases with explicitly injected ports; no independent authority."""

    _store: StructuredDirectorStore
    _lock: asyncio.Lock
    _registry: ProviderRegistry
    _final_assembly_provider: FinalAssemblyProvider | None
    _animatic_provider: AnimaticProvider | None
    _video_frame_provider: VideoFrameProvider | None
    _pano_view_provider: PanoViewProvider | None
