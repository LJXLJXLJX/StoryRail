"""Core 本机确定性媒体工具：成片装配、Animatic、抽帧、全景取景与音轨重混。"""

from __future__ import annotations

from pathlib import Path

from core.model_providers.registry import ProviderRegistry

from .executor import LocalMediaExecutor
from .ffmpeg import FFmpeg
from .providers import local_media_tools


def install_local_media_tools(
    registry: ProviderRegistry, work_root: Path
) -> LocalMediaExecutor | None:
    """找到 ffmpeg/ffprobe 时注册五个工具端口并返回执行器；找不到时不注册，返回 None。"""
    ff = FFmpeg.discover()
    if ff is None:
        return None
    executor = LocalMediaExecutor(work_root)
    for tool, provider in local_media_tools(executor, ff).items():
        registry.register(tool, provider)
    return executor


__all__ = ["FFmpeg", "LocalMediaExecutor", "install_local_media_tools", "local_media_tools"]
