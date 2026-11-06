"""五个确定性工具端口的本机实现（满足 ``structured_director.provider_ports`` 的窄 Protocol）。

句柄的 ``plugin_id`` 沿用 ``ffmpeg.*``，Generation 记录里的工具身份保持不变。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.model_providers.boundary import GenerationObservation, ModelProviderError, ProviderHandle
from core.model_providers.contracts import (
    AnimaticRequest,
    AudioRemixRequest,
    FinalAssemblyRequest,
    PanoViewRequest,
    VideoFrameRequest,
)

from .executor import LocalMediaExecutor
from .ffmpeg import FFmpeg
from .timeline import Progress
from .tools import (
    render_animatic,
    render_audio_remix,
    render_final_assembly,
    render_pano_view,
    render_video_frame,
)

Render = Callable[[FFmpeg, Any, Path, threading.Event, Progress], Path]


class _LocalTool:
    plugin_id: str
    plugin_version = 1
    _request_type: type
    _render: Render
    _lane: str
    _media_type: str
    _failure_code: str
    _probe_duration: bool
    _label: str

    def __init__(self, executor: LocalMediaExecutor, ff: FFmpeg) -> None:
        self._executor = executor
        self._ff = ff

    def submit(self, request: Any) -> ProviderHandle:
        if not isinstance(request, self._request_type):
            raise TypeError(f"{self._label}只接受 {self._request_type.__name__}。")
        render = type(self)._render
        task_id = self._executor.submit(
            self._lane,
            lambda directory, cancel, progress: render(
                self._ff, request, directory, cancel, progress
            ),
            media_type=self._media_type,
            failure_code=self._failure_code,
            duration_probe=self._ff.duration_seconds if self._probe_duration else None,
        )
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        return self._executor.observe(self._task_id(handle))

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        return self._executor.cancel(self._task_id(handle))

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        return self._executor.read_artifact(self._task_id(handle), artifact_id)

    def _task_id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", f"调用句柄不属于{self._label}。")
        return handle.external_id


class LocalFinalAssemblyProvider(_LocalTool):
    plugin_id = "ffmpeg.final-assembly"
    _request_type = FinalAssemblyRequest
    _render = staticmethod(render_final_assembly)
    _lane = "heavy"
    _media_type = "video/mp4"
    _failure_code = "ffmpeg_assembly_failed"
    _probe_duration = True
    _label = "成片装配"


class LocalAnimaticProvider(_LocalTool):
    plugin_id = "ffmpeg.animatic"
    _request_type = AnimaticRequest
    _render = staticmethod(render_animatic)
    _lane = "heavy"
    _media_type = "video/mp4"
    _failure_code = "ffmpeg_animatic_failed"
    _probe_duration = True
    _label = "Animatic"


class LocalAudioRemixProvider(_LocalTool):
    plugin_id = "ffmpeg.audio-remix"
    _request_type = AudioRemixRequest
    _render = staticmethod(render_audio_remix)
    _lane = "heavy"
    _media_type = "video/mp4"
    _failure_code = "audio_remix_failed"
    _probe_duration = True
    _label = "音轨混音"


class LocalVideoFrameProvider(_LocalTool):
    plugin_id = "ffmpeg.video_frame"
    _request_type = VideoFrameRequest
    _render = staticmethod(render_video_frame)
    _lane = "light"
    _media_type = "image/png"
    _failure_code = "ffmpeg_video_frame_failed"
    _probe_duration = False
    _label = "抽帧"


class LocalPanoViewProvider(_LocalTool):
    plugin_id = "ffmpeg.pano_view"
    _request_type = PanoViewRequest
    _render = staticmethod(render_pano_view)
    _lane = "light"
    _media_type = "image/png"
    _failure_code = "ffmpeg_pano_view_failed"
    _probe_duration = False
    _label = "全景取景"


def local_media_tools(executor: LocalMediaExecutor, ff: FFmpeg) -> dict[str, _LocalTool]:
    """按 ``manifest.Tool`` 名称返回五个端口实现，供 ``ProviderRegistry.register`` 逐个注册。"""
    return {
        "final_assembly": LocalFinalAssemblyProvider(executor, ff),
        "animatic": LocalAnimaticProvider(executor, ff),
        "video_frame": LocalVideoFrameProvider(executor, ff),
        "pano_view": LocalPanoViewProvider(executor, ff),
        "audio_remix": LocalAudioRemixProvider(executor, ff),
    }
