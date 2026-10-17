"""仅持有6个合成项目的受信Core进程；无模型/媒体Provider。"""

import asyncio
import hashlib
import json
import threading
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from core.application.caller import command_digest
from core.director_proposals.reference_library import (
    CharacterCardProposal,
    NarratorProfileProposal,
    ReferenceLibraryProposal,
)
from core.project_settings import ProjectAspectRatio
from core.structured_director import (
    StructuredDirectorHttpApi,
    StructuredDirectorService,
    StructuredDirectorStore,
)
from core.structured_director.models import NarrationLanguage
from server.http import StoryRailHttpServer
from server.writer import SingleWriterLease


def main():
    base = Path("/state")
    spec = json.loads((base / "spec.json").read_text())
    callers, apis, exports = [], {}, {}
    for trial, value in spec.items():
        pid = uuid4().hex
        directory = base / "stories" / pid
        directory.mkdir(parents=True)
        store = StructuredDirectorStore(directory, pid)
        store.create_project(
            title=trial,
            aspect_ratio=ProjectAspectRatio(value["aspect_ratio"]),
            director_plan_markdown=value["plan"],
            narration_languages=tuple(NarrationLanguage),
        )
        store.begin_reference_proposal()
        doc = store.apply_reference_proposal(
            ReferenceLibraryProposal(
                tuple(
                    CharacterCardProposal(n, desc, "自然普通话") for n, desc in value["characters"]
                ),
                NarratorProfileProposal("讲述者", "自然平静的普通话", "Natural, calm English")
                if value["narrator"]
                else None,
            )
        )
        request = {
            "name": "script.request_proposal",
            "expected_revision": doc.revision,
            "idempotency_key": "initial-request",
            "arguments": {"raw_user_instruction": "严格按完整导演方案生成初次脚本"},
        }
        prompt_public = None
        if value.get("prompt_fixture"):
            from scripts.harness.real_agent.prompt_fixture import prepare

            prompt_public = asyncio.run(prepare(store, value))
        role = "human" if trial.endswith("builtin") else "agent"
        callers.append(
            {
                "id": trial,
                "role": role,
                "project_ids": [pid],
                "capabilities": ["project.read", "human.write"]
                if role == "human"
                else ["project.read", "project.mutate", "project.propose"],
                "expires_at": 4102444800,
                "token_sha256": hashlib.sha256(value["core_token"].encode()).hexdigest(),
                "grants": []
                if role == "human" or prompt_public is not None
                else [
                    {
                        "id": trial,
                        "project_id": pid,
                        "command_digest": command_digest(request),
                        "expires_at": 4102444800,
                    }
                ],
            }
        )
        exports[trial] = {
            "project_id": pid,
            "initial_request": request,
            "director_plan_markdown": doc.director_plan_markdown,
            "characters": [
                {"id": c.id, "name": c.name, "visual_description": c.visual_description}
                for c in doc.reference_library.characters
            ],
            "reference_library": asdict(doc.reference_library),
        }
        if prompt_public is not None:
            exports[trial].update(prompt_public)
        route = f"/api/projects/{pid}/structured-director"
        apis[route] = StructuredDirectorHttpApi(
            StructuredDirectorService(store), resource_path=route
        )
    policy = base / "policy.json"
    policy.write_text(json.dumps({"version": 2, "external_mutations": True, "callers": callers}))
    policy.chmod(0o600)
    (base / "exports.json").write_text(json.dumps(exports, ensure_ascii=False))

    class Api:
        async def handle(self, method, path, body=b"", **kwargs):
            for route, api in apis.items():
                if path == route or path.startswith(route + "/"):
                    return await api.handle(method, path, body, **kwargs)
            raise ValueError("未知合成项目")

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    with SingleWriterLease(base / "stories"):
        server = StoryRailHttpServer(("0.0.0.0", 8765), Api(), loop, access_policy_file=policy)
        print("EVALUATION_CORE_READY", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
