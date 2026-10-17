"""真实 Agent 验收 Core：只有合成媒体 Provider，没有任何 Agent 执行器。

合成 Provider 实现在 `scripts/harness/fixtures/synthetic_media.py`（与探针共用）。
"""

import asyncio
import threading
from pathlib import Path

from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService
from scripts.harness.fixtures.media import png, wav
from scripts.harness.fixtures.synthetic_media import (
    SyntheticMediaProvider as SyntheticProvider,
)
from scripts.harness.fixtures.synthetic_media import byte_evidence, service_registry
from server.api import StoryRailApi
from server.http import StoryRailHttpServer
from server.writer import SingleWriterLease

__all__ = ["SyntheticProvider", "byte_evidence", "main", "png", "wav"]


def main():
    root = Path("/state")
    workspaces = ProjectWorkspaceStore(root / "projects")
    providers = {
        kind: SyntheticProvider(root / "provider", kind)
        for kind in ("image", "audio", "video", "final", "animatic", "upscale")
    }
    services = {}

    def service(pid):
        if pid not in services:
            services[pid] = StructuredDirectorService(
                workspaces.structured_director_store(pid),
                service_registry(providers),
            )
            assert not hasattr(services[pid], "built_in_assistant_available")
        return services[pid]

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    with SingleWriterLease(root / "projects"):
        server = StoryRailHttpServer(
            ("0.0.0.0", 8765),
            StoryRailApi(workspaces, service),
            loop,
            access_policy_file=root / "policy.json",
        )
        print("R08_CORE_READY", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
