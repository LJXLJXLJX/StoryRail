"""导演台网页验收：正式 Core/HTTP/dist + 隔离合成 Provider，不接真实作品。

PYTHONPATH=.:tests .venv/bin/python scripts/harness/real_agent/workspace_browser_fixture.py \
    --directory /tmp/storyrail-workspace-browser --port 18766
"""

import argparse
import asyncio
import json
import mimetypes
import threading
import time
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService
from structured_director_fixtures import (
    NarrationReferenceProposer,
    NarrationScriptProposer,
    wav_bytes,
)
from test_director_commands import _ReferenceCompiler, _TwoSceneScriptCompiler

from core.model_providers.boundary import GenerationObservation, GenerationPhase
from core.project_settings import ProjectAspectRatio
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService
from core.structured_director.models import NARRATION_LANGUAGES, NarrationLanguage
from scripts.harness.fixtures.media import png
from scripts.harness.fixtures.synthetic_media import byte_evidence, service_registry
from scripts.harness.real_agent.external_core import SyntheticProvider
from server.api import StoryRailApi
from server.http import BinaryResponse, StoryRailHttpServer
from server.writer import SingleWriterLease

ROOT = Path(__file__).resolve().parents[3]


class BrowserProvider(SyntheticProvider):
    def submit(self, request):
        handle = super().submit(request)
        path = self.root / (handle.external_id + ".json")
        job = json.loads(path.read_text())
        if (
            self.kind == "image"
            and dict(getattr(request, "params", ())).get("aspect_ratio") == "2:1"
        ):
            content = png(2048, 1024)
            (self.root / (handle.external_id + ".artifact")).write_bytes(content)
            job.update(byte_evidence(content))
        job["submitted_at"] = time.time()
        job["fail"] = "模拟失败" in json.dumps(job["request"], ensure_ascii=False)
        path.write_text(json.dumps(job))
        return handle

    submit_generate = submit_edit = submit

    def observe(self, handle):
        job = json.loads((self.root / (handle.external_id + ".json")).read_text())
        elapsed = time.time() - job["submitted_at"]
        if job["phase"] == "cancelled":
            return super().observe(handle)
        if elapsed < 15:
            return GenerationObservation(
                GenerationPhase.RUNNING, min(elapsed / 15, 0.95), "合成生成中"
            )
        if job["fail"]:
            return GenerationObservation(
                GenerationPhase.FAILED, 0.5, "合成失败：输入已保留", error_code="synthetic_failure"
            )
        return super().observe(handle)


class WebApi:
    def __init__(self, api):
        self.api = api

    async def handle(self, method, path, body=b"", *, media_type=None):
        if path.startswith("/api/"):
            return await self.api.handle(method, path, body, media_type=media_type)
        requested = path.split("?", 1)[0]
        target = (ROOT / "web/dist" / requested.lstrip("/")).resolve()
        if not target.is_relative_to(ROOT / "web/dist"):
            return BinaryResponse(404, b"", "text/plain")
        if not target.is_file():
            target = ROOT / "web/dist/index.html"
        return BinaryResponse(
            200,
            target.read_bytes(),
            mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", "--stories-directory", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--add-narration", action="store_true")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    root = args.directory.resolve()
    if root.is_relative_to(ROOT) or (root.exists() and not args.resume):
        raise ValueError("验收必须使用仓库外全新隔离目录。")
    if args.resume and not (root / "projects.json").is_file():
        raise ValueError("只允许恢复本验收工具已建立的隔离项目目录。")
    workspaces = ProjectWorkspaceStore(root / "projects")
    providers = {
        kind: BrowserProvider(root / "providers", kind)
        for kind in ("image", "audio", "video", "upscale", "final", "animatic")
    }

    registry = service_registry(providers)
    registry.register("pano_view", BrowserProvider(root / "crop", "image"))

    def factory(pid):
        return StructuredDirectorService(
            workspaces.structured_director_store(pid),
            registry,
        )

    async def seed():
        result = {}
        for label in ("空项目", "未解锁制作", "空卡制作"):
            project = workspaces.create(
                "合成验收 · " + label,
                "# 合成导演方案\n\n两个空站台的连续场景。",
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            result[label] = project.id
            if label == "空项目":
                continue
            service = ProposalFixtureService(
                workspaces.structured_director_store(project.id),
                _ReferenceCompiler(),
                script_proposer=_TwoSceneScriptCompiler(),
            )
            doc = await service.prepare_references()
            doc = await service.prepare_script(expected_revision=doc.revision)
            if label == "空卡制作":
                doc = await service.confirm_script(expected_revision=doc.revision)
                await service.unlock_visual_production(expected_revision=doc.revision)
        (root / "projects.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)

    async def add_narration():
        project = workspaces.create(
            "合成验收 · 旁白制作",
            "# 旁白方案\n\n安静的站台。",
            aspect_ratio=ProjectAspectRatio.LANDSCAPE,
            narration_languages=tuple(NarrationLanguage),
        )
        service = ProposalFixtureService(
            workspaces.structured_director_store(project.id),
            NarrationReferenceProposer(),
            script_proposer=NarrationScriptProposer(),
        )
        doc = await service.prepare_references()
        for language in NARRATION_LANGUAGES:
            doc = await service.upload_narrator_voice(
                narrator_id=doc.reference_library.narrator.id,
                language=language,
                media_type="audio/wav",
                content=wav_bytes(),
                expected_revision=doc.revision,
            )
        doc = await service.prepare_script(expected_revision=doc.revision)
        scenes = tuple(
            replace(
                scene,
                segments=tuple(
                    replace(segment, duration_estimate_seconds=6.0) for segment in scene.segments
                ),
            )
            for scene in doc.director_script.scenes
        )
        doc = await service.save_script(scenes, expected_revision=doc.revision)
        await service.confirm_script(expected_revision=doc.revision)
        print("narration_project=" + project.id, flush=True)

    with SingleWriterLease(root / "projects"):
        loop = asyncio.new_event_loop()
        if not args.resume:
            loop.run_until_complete(seed())
        if args.add_narration:
            loop.run_until_complete(add_narration())
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        server = StoryRailHttpServer(
            ("127.0.0.1", args.port), WebApi(StoryRailApi(workspaces, factory)), loop
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            loop.call_soon_threadsafe(loop.stop)
            thread.join()
            loop.close()


if __name__ == "__main__":
    main()
