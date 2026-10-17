"""只用于独立 synthetic volume 的 Core 服务，不加载任何宿主作品或 Provider。"""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from test_director_commands import _visual_project

from core.application.caller import command_digest
from core.application.requests import canonical
from core.director_commands import DirectorCommand
from core.structured_director import StructuredDirectorHttpApi
from server.http import StoryRailHttpServer
from server.writer import SingleWriterLease


async def prepare():
    root = Path("/state/stories")
    root.mkdir(exist_ok=True)
    store, service, document, _ = await _visual_project(str(root))
    scene = document.director_script.scenes[0]
    command = DirectorCommand(
        "script.apply_operations",
        document.revision,
        "isolated-edit",
        {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "update_shot_fields",
                    "shot_id": scene.shots[0].id,
                    "fields": {"action": "隔离 Agent 的明确授权动作"},
                }
            ],
        },
    )
    policy_path = Path("/state/policy.json")
    policy = json.loads(policy_path.read_text())
    agent = next(c for c in policy["callers"] if c["role"] == "agent")
    agent["grants"] = [
        {
            "id": "isolated-explicit-edit",
            "project_id": document.project_id,
            "command_digest": command_digest(asdict(command)),
            "expires_at": 4102444800,
        }
    ]
    policy_path.write_text(canonical(policy))
    Path("/state/public-command.json").write_text(canonical(asdict(command)))
    return service


def main():
    loop = asyncio.new_event_loop()
    with SingleWriterLease(Path("/state/stories")):
        service = loop.run_until_complete(prepare())
        import threading

        worker = threading.Thread(target=loop.run_forever, daemon=True)
        worker.start()
        server = StoryRailHttpServer(
            ("0.0.0.0", 8765),
            StructuredDirectorHttpApi(
                service, resource_path="/api/projects/" + "a" * 32 + "/structured-director"
            ),
            loop,
            access_policy_file=Path("/state/policy.json"),
        )
        print("SYNTHETIC_CORE_READY", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            loop.call_soon_threadsafe(loop.stop)
            worker.join()
            loop.close()


if __name__ == "__main__":
    main()
