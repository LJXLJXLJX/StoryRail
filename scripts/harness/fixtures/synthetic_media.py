"""合成媒体 Provider：持久 job/产物证据、确定性 phase、可注入故障。

`scripts/harness/real_agent/external_core.py` 复用本模块，不再各自维护第二份；
P6-T2 收编后 `real_agent` 直接从这里 import，不再各自维护第二份。
不读取任何项目语义文件、不调用真实媒体服务、不联网。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path
from uuid import uuid4

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.breeze_tts2.manifest import MANIFEST
from core.model_providers.codex_image.manifest import MANIFEST as IMAGE_MANIFEST
from core.model_providers.minimax_h3.manifest import MANIFEST as H3_MANIFEST
from core.model_providers.minimax_h3.prompt_context import format_prompt_workset, prompt_skills
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.model_providers.seedvr2_7b_sharp_fp8.manifest import MANIFEST as UPSCALE_MANIFEST

from .media import png, wav


def byte_evidence(value: object) -> dict[str, object]:
    if isinstance(value, bytes):
        return {"byte_count": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    raise TypeError("验收请求包含未知值")


class SyntheticMediaProvider:
    """按 ``kind``（image/audio/video/final/animatic/upscale）产出确定性媒体。

    - ``observe`` 每次调用恒返回 SUCCEEDED（幂等），因此 driver 无需编排 phase；
      长轮询只会观察到一次即可返回。
    - ``next-fault.txt`` 写入 ``submit_unknown`` / ``cancel_fail`` 可复现传输故障。
    """

    plugin_version = 1

    def __init__(self, root: Path, kind: str) -> None:
        self.root, self.kind = root / kind, kind
        self.root.mkdir(parents=True, exist_ok=True)
        self.plugin_id = self.generate_plugin_id = self.edit_plugin_id = "synthetic." + kind

    def fault(self, name: str) -> bool:
        path = self.root / "next-fault.txt"
        if path.exists() and path.read_text().strip() == name:
            path.unlink()
            return True
        return False

    def submit_recipe(self, request: object):
        if self.kind == "video":
            from core.model_providers.minimax_h3.requests import to_request

            request = to_request(request)
        return self.submit(request)

    def submit(self, request: object) -> ProviderHandle:
        job = uuid4().hex
        duration = 8 if self.kind == "audio" else getattr(request, "duration_seconds", None)
        if self.kind in {"final", "animatic"}:
            duration = sum(c.duration_seconds for c in request.clips)
            duration -= sum(c.transition_from_previous is not None for c in request.clips[1:]) * (
                request.transition_seconds
            )
        content = self.root / (job + ".artifact")
        if self.kind == "image":
            media, data = "image/png", png()
        elif self.kind == "audio":
            media, data = "audio/wav", wav(duration)
        elif self.kind == "upscale":
            media, data = "video/mp4", request.video.content
            content.write_bytes(data)
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(content),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            duration = float(probe.stdout.strip())
        else:
            media = "video/mp4"
            duration = duration or 8
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x6090b0:s=160x90:r=10",
                    "-t",
                    str(duration),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-f",
                    "mp4",
                    str(content),
                ],
                check=True,
                capture_output=True,
            )
            data = content.read_bytes()
        content.write_bytes(data)
        (self.root / (job + ".json")).write_text(
            json.dumps(
                {
                    "phase": "queued",
                    "media_type": media,
                    "duration_seconds": duration,
                    "request": json.loads(
                        json.dumps(
                            asdict(request) if is_dataclass(request) else vars(request),
                            default=byte_evidence,
                        )
                    ),
                    "byte_count": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        )
        if self.fault("submit_unknown"):
            raise ModelProviderError("transport_error", "合成提交已收下但响应丢失")
        return ProviderHandle(self.plugin_id, 1, job)

    submit_generate = submit_edit = submit

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        path = self.root / (handle.external_id + ".json")
        job = json.loads(path.read_text())
        if job["phase"] == "cancelled":
            return GenerationObservation(GenerationPhase.CANCELLED, 0, "合成任务已取消")
        job["phase"] = "succeeded"
        path.write_text(json.dumps(job))
        return GenerationObservation(
            GenerationPhase.SUCCEEDED,
            1,
            "合成媒体完成",
            ArtifactDescriptor(
                "output",
                job["media_type"],
                job["byte_count"],
                job["sha256"],
                job["duration_seconds"],
            ),
        )

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        if artifact_id != "output":
            raise ValueError("未知产物")
        return (self.root / (handle.external_id + ".artifact")).read_bytes()

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        if self.fault("cancel_fail"):
            raise ModelProviderError("transport_error", "合成取消响应中断")
        path = self.root / (handle.external_id + ".json")
        job = json.loads(path.read_text())
        job["phase"] = "cancelled"
        path.write_text(json.dumps(job))
        return GenerationObservation(GenerationPhase.CANCELLED, 0, "合成任务已取消")


def provider_set(root: Path) -> dict[str, SyntheticMediaProvider]:
    """按 Core Service 构造槽位返回一套合成 Provider（同一 video 实例供 fl2va/ref2va）。"""
    kinds = ("image", "audio", "video", "final", "animatic", "upscale")
    return {kind: SyntheticMediaProvider(root, kind) for kind in kinds}


def service_registry(providers: dict[str, SyntheticMediaProvider]) -> ProviderRegistry:
    """按 Core 媒体能力装配 registry；Service 只接受 registry 构造。"""
    registry = ProviderRegistry()
    registry.install(
        PluginInstance(
            IMAGE_MANIFEST,
            recipes={recipe.id: providers["image"] for recipe in IMAGE_MANIFEST.recipes},
        )
    )
    registry.install(
        PluginInstance(
            MANIFEST, recipes={recipe.id: providers["audio"] for recipe in MANIFEST.recipes}
        )
    )
    registry.install(
        PluginInstance(
            H3_MANIFEST,
            recipes={recipe.id: providers["video"] for recipe in H3_MANIFEST.recipes},
            prompt_formatter=format_prompt_workset,
            prompt_skills=prompt_skills,
        )
    )
    registry.register("final_assembly", providers["final"])
    registry.register("animatic", providers["animatic"])
    registry.install(
        PluginInstance(
            UPSCALE_MANIFEST,
            recipes={recipe.id: providers["upscale"] for recipe in UPSCALE_MANIFEST.recipes},
        )
    )
    return registry
