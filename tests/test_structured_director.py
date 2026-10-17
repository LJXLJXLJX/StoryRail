from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from script_helpers import editable_scene_payload
from structured_director_fixtures import (
    RecordingProposer,
    RecordingScriptProposer,
    create_project,
)

from core.structured_director import (
    StructuredDirectorHttpApi,
    StructuredDirectorStatus,
    StructuredDirectorStore,
)


class StructuredDirectorWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_api_inserts_modifies_and_deletes_scene_with_core_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("c" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "c" * 32)
            service = StructuredDirectorService(
                store,
                RecordingProposer(),
                script_proposer=RecordingScriptProposer(),
            )
            create_project(store)
            references = await service.prepare_references()
            scripted = await service.prepare_script(expected_revision=references.revision)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            snapshot = await api.handle("GET", "/structured-director")
            original = editable_scene_payload(snapshot.body["director_script"]["scenes"][0])
            inserted = json.loads(json.dumps(original, ensure_ascii=False))
            inserted["id"] = None
            inserted["title"] = "雨停后的站台"
            inserted["summary"] = "雨停后，小满发现末班车的灯光终于出现。"
            for shot in inserted["shots"]:
                shot["id"] = None
            for segment in inserted["segments"]:
                segment["id"] = None

            created = await api.handle(
                "PUT",
                "/structured-director/director-script",
                json.dumps(
                    {
                        "expected_revision": scripted.revision,
                        "scenes": [original, inserted],
                    }
                ).encode(),
            )
            self.assertEqual(created.status, 200)
            created_scenes = created.body["director_script"]["scenes"]
            new_scene_id = created_scenes[1]["id"]
            self.assertRegex(new_scene_id, r"^[0-9a-f]{32}$")

            created_scenes[1]["title"] = "雨后的末班车"
            reduced = await api.handle(
                "PUT",
                "/structured-director/director-script",
                json.dumps(
                    {
                        "expected_revision": created.body["revision"],
                        "scenes": [editable_scene_payload(created_scenes[1])],
                    }
                ).encode(),
            )

            self.assertEqual(reduced.status, 200)
            self.assertEqual(reduced.body["director_script"]["scenes"][0]["id"], new_scene_id)
            self.assertEqual(
                reduced.body["director_script"]["scenes"][0]["title"],
                "雨后的末班车",
            )

    async def test_create_then_prepare_persists_cards_in_project_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("a" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "a" * 32)
            proposer = RecordingProposer()
            service = StructuredDirectorService(store, proposer)

            entered = create_project(store)
            prepared = await service.prepare_references()
            restored = StructuredDirectorStore(project, "a" * 32).read()

            self.assertEqual(entered.revision, 1)
            self.assertIs(entered.status, StructuredDirectorStatus.AWAITING_PROPOSAL)
            self.assertEqual(prepared.revision, 3)
            self.assertIs(prepared.status, StructuredDirectorStatus.REVIEWING)
            self.assertEqual(restored.reference_library.characters[0].name, "小满")
            self.assertEqual(proposer.restart_values, [False])
            saved = json.loads((project / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["aspect_ratio"], "16:9")
            self.assertEqual(saved["structured_director"]["status"], "reviewing_references")

    async def test_card_edits_require_revision_and_delete_only_removes_library_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("c" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "c" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            prepared = await service.prepare_references()
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
            card = prepared.reference_library.characters[0]
            request = {
                "expected_revision": prepared.revision,
                "name": card.name,
                "visual_description": f"{card.visual_description}，红色围巾",
                "voice_description": card.voice_description,
                "voice_reference_asset_id": None,
                "looks": [],
            }

            updated = await api.handle(
                "PUT",
                f"/structured-director/characters/{card.id}",
                json.dumps(request).encode(),
            )
            stale = await api.handle(
                "PUT",
                f"/structured-director/characters/{card.id}",
                json.dumps(request).encode(),
            )
            bad_delete = await api.handle(
                "DELETE",
                f"/structured-director/characters/{card.id}",
                json.dumps(
                    {"expected_revision": updated.body["revision"], "reason": "remove_from_video"}
                ).encode(),
            )
            deleted = await api.handle(
                "DELETE",
                f"/structured-director/characters/{card.id}",
                json.dumps({"expected_revision": updated.body["revision"]}).encode(),
            )

            self.assertIn(
                "红色围巾",
                updated.body["reference_library"]["characters"][0]["visual_description"],
            )
            self.assertEqual(stale.body["error"]["code"], "revision_conflict")
            self.assertEqual(bad_delete.status, 400)
            self.assertEqual(deleted.body["reference_library"]["characters"], [])

    async def test_http_schema_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("d" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "d" * 32)
            service = StructuredDirectorService(store, RecordingProposer())
            create_project(store)
            api = StructuredDirectorHttpApi(service, resource_path="/structured-director")

            response = await api.handle(
                "POST",
                "/structured-director/reference-proposal",
                b'{"unexpected":true}',
            )

            self.assertEqual(response.status, 404)
            self.assertEqual(response.body["error"]["code"], "not_found")

    async def test_project_json_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("e" * 32)
            project.mkdir()
            store = StructuredDirectorStore(project, "e" * 32)
            create_project(store)
            value = json.loads(store.path.read_text(encoding="utf-8"))
            value["database_id"] = "not-allowed"
            store.path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "未声明"):
                store.read()

    async def test_old_project_json_schema_is_rejected_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / ("5" * 32)
            project.mkdir()
            value = {"schema_version": 16}
            (project / "project.json").write_text(json.dumps(value), encoding="utf-8")
            before = (project / "project.json").read_bytes()

            with self.assertRaisesRegex(ValueError, "schema_version 不受支持"):
                StructuredDirectorStore(project, "5" * 32).read()
            self.assertEqual((project / "project.json").read_bytes(), before)
            self.assertEqual({item.name for item in project.iterdir()}, {"project.json"})
