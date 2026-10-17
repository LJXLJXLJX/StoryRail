from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.director_proposals import (
    CharacterCardProposal,
    ReferenceLibraryProposal,
)
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import (
    StructuredDirectorService,
)
from server.api import StoryRailApi
from server.http import _accepts_gzip, _parse_byte_range, _request_body_limit

DIRECTOR_PLAN = "# 完整导演方案\n\n小满带着红色行李箱，在雨夜等待末班车。"


class RecordingReferenceProposer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def propose(self, *, director_plan_markdown: str, **_kwargs: object):
        self.calls.append(director_plan_markdown)
        return ReferenceLibraryProposal(
            characters=(CharacterCardProposal("小满", "短发，蓝色外套", "年轻、克制"),)
        )


class DebugRuntime:
    async def read_thread(self, thread_id: str):
        return SimpleNamespace(
            thread={
                "id": thread_id,
                "status": {"type": "idle"},
                "turns": [],
            }
        )


class StoryRailApiTests(unittest.IsolatedAsyncioTestCase):
    def make_api(self, root: Path, proposer: RecordingReferenceProposer):
        workspaces = ProjectWorkspaceStore(root)

        def service(project_id: str) -> StructuredDirectorService:
            return StructuredDirectorService(workspaces.structured_director_store(project_id))

        return workspaces, StoryRailApi(workspaces, service)

    async def test_create_is_atomic_does_not_wait_for_agent_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposer = RecordingReferenceProposer()
            workspaces, api = self.make_api(Path(directory), proposer)
            created = await api.handle(
                "POST",
                "/api/projects",
                json.dumps(
                    {
                        "title": "雨夜末班车",
                        "aspect_ratio": "9:16",
                        "director_plan_markdown": DIRECTOR_PLAN,
                        "narration_languages": ["zh", "en"],
                    }
                ).encode(),
            )
            project_id = created.body["project"]["id"]

            self.assertEqual(created.status, 201)
            self.assertEqual(proposer.calls, [])
            self.assertEqual(created.body["project"]["title"], "雨夜末班车")
            self.assertNotIn("stage", created.body["project"])
            self.assertEqual(
                created.body["structured_director"]["status"],
                "awaiting_reference_proposal",
            )

            restarted = StoryRailApi(
                ProjectWorkspaceStore(Path(directory)),
                lambda candidate: StructuredDirectorService(
                    workspaces.structured_director_store(candidate)
                ),
            )
            opened = await restarted.handle(
                "GET", f"/api/projects/{project_id}/structured-director"
            )
            self.assertEqual(opened.body["director_plan_markdown"], DIRECTOR_PLAN)
            self.assertEqual((await restarted.handle("GET", "/api/projects")).status, 200)

    async def test_create_schema_is_strict(self) -> None:
        invalid_requests = (
            {},
            {"title": "项目", "aspect_ratio": "16:9"},
            {
                "title": "项目",
                "aspect_ratio": "16:9",
                "director_plan_markdown": DIRECTOR_PLAN,
                "extra": True,
                "narration_languages": ["zh", "en"],
            },
            {
                "title": "",
                "aspect_ratio": "16:9",
                "director_plan_markdown": DIRECTOR_PLAN,
                "narration_languages": ["zh", "en"],
            },
            {
                "title": "项目",
                "aspect_ratio": "1:1",
                "director_plan_markdown": DIRECTOR_PLAN,
                "narration_languages": ["zh", "en"],
            },
            {
                "title": "项目",
                "aspect_ratio": "16:9",
                "director_plan_markdown": "",
                "narration_languages": ["zh", "en"],
            },
            {
                "title": "项目",
                "aspect_ratio": "16:9",
                "director_plan_markdown": "a" * 50_001,
                "narration_languages": ["zh", "en"],
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            _, api = self.make_api(Path(directory), RecordingReferenceProposer())
            for request in invalid_requests:
                response = await api.handle("POST", "/api/projects", json.dumps(request).encode())
                self.assertEqual(response.status, 400, request)

    async def test_removed_stage_routes_return_404(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, api = self.make_api(Path(directory), RecordingReferenceProposer())
            created = await api.handle(
                "POST",
                "/api/projects",
                json.dumps(
                    {
                        "title": "项目",
                        "aspect_ratio": "16:9",
                        "director_plan_markdown": DIRECTOR_PLAN,
                        "narration_languages": ["zh", "en"],
                    }
                ).encode(),
            )
            project_id = created.body["project"]["id"]
            for suffix in ("creative-intake", "story-development", "director-plan"):
                response = await api.handle("GET", f"/api/projects/{project_id}/{suffix}")
                self.assertEqual(response.status, 404)

    async def test_delete_moves_project_to_trash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, api = self.make_api(root, RecordingReferenceProposer())
            created = await api.handle(
                "POST",
                "/api/projects",
                json.dumps(
                    {
                        "title": "项目",
                        "aspect_ratio": "16:9",
                        "director_plan_markdown": DIRECTOR_PLAN,
                        "narration_languages": ["zh", "en"],
                    }
                ).encode(),
            )
            project_id = created.body["project"]["id"]
            deleted = await api.handle("DELETE", f"/api/projects/{project_id}")
            self.assertEqual(deleted.body, {"deleted_project_id": project_id})
            self.assertEqual(len(tuple((root / ".trash").iterdir())), 1)

    def test_project_creation_uses_json_request_limit(self) -> None:
        self.assertEqual(_request_body_limit("/api/projects"), 256 * 1024)

    def test_http_content_encoding_negotiates_gzip(self) -> None:
        self.assertTrue(_accepts_gzip("gzip, deflate, br"))
        self.assertTrue(_accepts_gzip("br, *;q=0.5"))
        self.assertFalse(_accepts_gzip("br"))
        self.assertFalse(_accepts_gzip("gzip; q=0, br"))

    def test_http_byte_range_supports_media_streaming(self) -> None:
        self.assertEqual(_parse_byte_range("bytes=0-1023", 10_000), (0, 1023))
        self.assertEqual(_parse_byte_range("bytes=9000-", 10_000), (9000, 9999))
        self.assertEqual(_parse_byte_range("bytes=-500", 10_000), (9500, 9999))
        with self.assertRaises(ValueError):
            _parse_byte_range("bytes=10000-", 10_000)
        with self.assertRaises(ValueError):
            _parse_byte_range("bytes=0-1,3-4", 10_000)


if __name__ == "__main__":
    unittest.main()
