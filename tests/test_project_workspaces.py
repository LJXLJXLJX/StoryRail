from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from video_recipes import video_slot

from core.director_commands import CommandReceipt
from core.project_settings import ProjectAspectRatio
from core.project_workspaces import ProjectWorkspaceStatus, ProjectWorkspaceStore
from core.structured_director import (
    PROJECT_SCHEMA_VERSION,
    DirectorAuthorization,
    DirectorCandidateSelectionPolicy,
    DirectorDirective,
    DirectorRun,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
)
from core.structured_director.models import NarrationLanguage

DIRECTOR_PLAN = "# 完整导演方案\n\n小满带着红色行李箱，在雨夜等待末班车。"


class ProjectWorkspaceStoreTests(unittest.TestCase):
    def test_create_list_and_restore_authoritative_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectWorkspaceStore(Path(directory))
            created = store.create(
                "雨夜末班车",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.PORTRAIT,
                narration_languages=tuple(NarrationLanguage),
            )
            restarted = ProjectWorkspaceStore(Path(directory))
            listed = restarted.list()
            document = restarted.structured_director_store(created.id).read()
            self.assertEqual(
                restarted.structured_director_store(created.id).path.parent.name,
                f"雨夜末班车-{created.id}",
            )

        self.assertEqual(len(created.id), 32)
        self.assertEqual(listed, (created,))
        self.assertEqual(created.title, "雨夜末班车")
        self.assertIs(created.aspect_ratio, ProjectAspectRatio.PORTRAIT)
        self.assertIs(created.status, ProjectWorkspaceStatus.ACTIVE)
        self.assertEqual(document.schema_version, PROJECT_SCHEMA_VERSION)
        self.assertEqual(document.director_plan_markdown, DIRECTOR_PLAN)
        self.assertEqual(document.director_runs, ())
        self.assertEqual(document.director_directives, ())

    def test_wide_aspect_ratio_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            created = ProjectWorkspaceStore(Path(directory)).create(
                "宽银幕",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.WIDE,
                narration_languages=tuple(NarrationLanguage),
            )
            restarted = ProjectWorkspaceStore(Path(directory))
            listed = restarted.list()
            document = restarted.structured_director_store(created.id).read()

        self.assertEqual(ProjectAspectRatio.WIDE.value, "2:1")
        self.assertEqual(listed, (created,))
        self.assertIs(document.aspect_ratio, ProjectAspectRatio.WIDE)

    def test_director_run_and_directive_round_trip_as_project_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_store = ProjectWorkspaceStore(Path(directory))
            project = workspace_store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            store = workspace_store.structured_director_store(project.id)
            current = store.read()
            run = DirectorRun(
                id="1" * 32,
                kind=DirectorRunKind.DIRECTOR,
                goal="完成 Scene 1 的视频候选",
                status=DirectorRunStatus.RUNNING,
                waiting_reason=None,
                authorization=DirectorAuthorization(
                    edit_scopes=("scene:*",),
                    generation_scopes=("segment:*",),
                    candidate_selection=DirectorCandidateSelectionPolicy.EXPLICIT_ONLY,
                    final_approval=False,
                ),
                cursor=DirectorRunCursor(0, (), ()),
                completed_command_ids=(),
                command_receipts=(),
                last_project_revision=current.revision + 1,
                created_at="2026-09-08T10:00:00+08:00",
                updated_at="2026-09-08T10:01:00+08:00",
            )
            directive = DirectorDirective(
                id="2" * 32,
                run_id=run.id,
                raw_user_request="完成 Scene 1 的连续关键帧和三个视频候选",
                created_at="2026-09-08T10:00:00+08:00",
            )
            store._atomic_write(
                replace(
                    current,
                    revision=current.revision + 1,
                    director_runs=(run,),
                    director_directives=(directive,),
                )
            )

            restored = (
                ProjectWorkspaceStore(Path(directory)).structured_director_store(project.id).read()
            )
            raw = json.loads(store.path.read_text(encoding="utf-8"))["structured_director"]

        self.assertEqual(restored.director_runs, (run,))
        self.assertEqual(restored.director_directives, (directive,))
        self.assertEqual(raw["director_runs"][0]["id"], run.id)
        self.assertEqual(raw["director_directives"][0]["run_id"], run.id)

    def test_director_directive_must_reference_unique_persisted_run(self) -> None:
        run = DirectorRun(
            id="1" * 32,
            kind=DirectorRunKind.DIRECTOR,
            goal="完成 Scene 1 的视频候选",
            status=DirectorRunStatus.RUNNING,
            waiting_reason=None,
            authorization=DirectorAuthorization(
                edit_scopes=("scene:*",),
                generation_scopes=("segment:*",),
                candidate_selection=DirectorCandidateSelectionPolicy.EXPLICIT_ONLY,
                final_approval=False,
            ),
            cursor=DirectorRunCursor(0, (), ()),
            completed_command_ids=(),
            command_receipts=(),
            last_project_revision=1,
            created_at="2026-09-08T10:00:00+08:00",
            updated_at="2026-09-08T10:00:00+08:00",
        )
        directive = DirectorDirective(
            id="2" * 32,
            run_id="3" * 32,
            raw_user_request="继续完成当前范围内尚未执行的步骤",
            created_at="2026-09-08T10:00:00+08:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace_store = ProjectWorkspaceStore(Path(directory))
            project = workspace_store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            current = workspace_store.structured_director_store(project.id).read()

        with self.assertRaisesRegex(ValueError, "Director run ID 不能重复"):
            replace(current, director_runs=(run, run))
        with self.assertRaisesRegex(ValueError, "不存在的 run"):
            replace(current, director_runs=(run,), director_directives=(directive,))

    def test_director_run_schema_rejects_missing_or_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_store = ProjectWorkspaceStore(Path(directory))
            project = workspace_store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            store = workspace_store.structured_director_store(project.id)
            original = json.loads(store.path.read_text(encoding="utf-8"))
            for run in (
                {
                    "id": "1" * 32,
                    "kind": "director",
                    "status": "running",
                    "waiting_reason": None,
                    "created_at": "2026-09-08T10:00:00+08:00",
                },
                {
                    "id": "1" * 32,
                    "kind": "director",
                    "status": "running",
                    "waiting_reason": None,
                    "created_at": "2026-09-08T10:00:00+08:00",
                    "updated_at": "2026-09-08T10:00:00+08:00",
                    "legacy_status": "running",
                },
            ):
                changed = json.loads(json.dumps(original))
                changed["structured_director"]["director_runs"] = [run]
                store.path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "缺少字段|不接受字段"):
                    store.read()

    def test_director_run_progress_and_receipt_survive_restart_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_store = ProjectWorkspaceStore(Path(directory))
            project = workspace_store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            store = workspace_store.structured_director_store(project.id)
            started, _ = store.begin_reference_proposal()
            assert started.active_director_run is not None
            run_id = started.active_director_run.id
            cursor = DirectorRunCursor(1, ("4" * 32,), ())
            receipt = CommandReceipt(
                command_id="run-step:1",
                status="noop",
                old_revision=started.revision,
                new_revision=started.revision,
                decision_summary="引用库事实读取完成。",
            )

            progressed, replayed = store.record_director_run_progress(
                run_id=run_id,
                cursor=cursor,
                receipt=receipt,
                expected_revision=started.revision,
            )
            replay, replayed_again = store.record_director_run_progress(
                run_id=run_id,
                cursor=cursor,
                receipt=receipt,
                expected_revision=progressed.revision,
            )
            restored = (
                ProjectWorkspaceStore(Path(directory)).structured_director_store(project.id).read()
            )
            _, read_receipt, run_status = store.execute_director_read(
                "run.get_status",
                {"run_id": run_id},
                command_id="read-run-status",
            )

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(replay.revision, progressed.revision)
        self.assertEqual(read_receipt.status, "noop")
        self.assertEqual(run_status["run"]["cursor"]["step"], 1)
        self.assertEqual(run_status["directives"][0]["run_id"], run_id)
        assert restored.active_director_run is not None
        self.assertEqual(restored.active_director_run.cursor, cursor)
        self.assertEqual(restored.active_director_run.completed_command_ids, ("run-step:1",))
        self.assertEqual(
            restored.active_director_run.command_receipts[0].decision_summary,
            "引用库事实读取完成。",
        )
        self.assertEqual(
            restored.active_director_run.last_project_revision,
            progressed.revision,
        )

    def test_invalid_input_does_not_leave_empty_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectWorkspaceStore(Path(directory))
            for title, plan in (("", DIRECTOR_PLAN), ("项目", "  ")):
                with self.assertRaisesRegex(ValueError, "不能为空"):
                    store.create(
                        title,
                        plan,
                        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                        narration_languages=tuple(NarrationLanguage),
                    )
            self.assertEqual(store.list(), ())

    def test_directory_names_are_safe_and_same_titles_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectWorkspaceStore(root)
            title = "../雨夜:末班车\\镜头/" + "雨" * 40
            projects = [
                store.create(
                    title,
                    DIRECTOR_PLAN,
                    aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                    narration_languages=tuple(NarrationLanguage),
                )
                for _ in range(2)
            ]
            for project in projects:
                path = store.structured_director_store(project.id).path
                self.assertEqual(path.parent.parent, root.resolve())
                self.assertLessEqual(len(path.parent.name.encode()), 255)
                self.assertNotIn(":", path.parent.name)
                self.assertNotIn("\\", path.parent.name)
                self.assertEqual(store.get(project.id).title, title)
            self.assertEqual(len(store.list()), 2)

    def test_id_lookup_rejects_duplicate_directories_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectWorkspaceStore(root)
            project = store.create(
                "原名",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            source = store.structured_director_store(project.id).path.parent
            alias = root / f"别名-{project.id}"
            alias.symlink_to(source, target_is_directory=True)
            self.assertEqual(store.get(project.id).title, "原名")
            alias.unlink()
            alias.mkdir()
            with self.assertRaisesRegex(ValueError, "多个目录"):
                store.get(project.id)
            self.assertEqual(store.list(), ())

    def test_existing_id_directory_is_read_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectWorkspaceStore(root)
            project = store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            source = store.structured_director_store(project.id).path.parent
            before = (source / "project.json").read_bytes()
            source.rename(root / project.id)
            self.assertEqual(store.get(project.id).title, "项目")
            self.assertEqual(store.structured_director_store(project.id).path.read_bytes(), before)

    def test_pending_reference_proposal_is_marked_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectWorkspaceStore(Path(directory))
            project = store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            store.structured_director_store(project.id).begin_reference_proposal()
            self.assertIs(store.get(project.id).status, ProjectWorkspaceStatus.NEEDS_RECOVERY)

    def test_delete_moves_project_to_internal_trash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectWorkspaceStore(root)
            project = store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            source = store.structured_director_store(project.id).path.parent
            deleted = store.move_to_trash(project.id)

            self.assertEqual(deleted.id, project.id)
            self.assertFalse(source.exists())
            self.assertTrue(next((root / ".trash").iterdir()).name.startswith(source.name + "-"))
            self.assertEqual(len(tuple((root / ".trash").iterdir())), 1)
            with self.assertRaisesRegex(KeyError, "项目不存在"):
                store.get(project.id)

    def test_arbitrary_path_is_never_accepted_as_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectWorkspaceStore(Path(directory))
            with self.assertRaisesRegex(KeyError, "项目不存在"):
                store.get("../outside")

    def test_list_skips_unsupported_schema_without_rewriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectWorkspaceStore(root)
            project = store.create(
                "项目",
                DIRECTOR_PLAN,
                aspect_ratio=ProjectAspectRatio.LANDSCAPE,
                narration_languages=tuple(NarrationLanguage),
            )
            path = store.structured_director_store(project.id).path
            content = path.read_text(encoding="utf-8").replace(
                f'"schema_version": {PROJECT_SCHEMA_VERSION}',
                f'"schema_version": {PROJECT_SCHEMA_VERSION - 1}',
            )
            path.write_text(content, encoding="utf-8")

            self.assertEqual(store.list(), ())
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schema_version 不受支持"):
                store.structured_director_store(project.id).read()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual({item.name for item in path.parent.iterdir()}, {"project.json"})

    def test_list_accepts_current_video_recipe_empty_book_without_writing(self) -> None:
        from test_director_commands import _visual_project

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            structured_store, _service, document, _route = asyncio.run(_visual_project(directory))
            assert document.video_plan is not None
            value = json.loads(structured_store.path.read_text(encoding="utf-8"))
            for segment in value["structured_director"]["video_plan"]["segments"]:
                segment["recipes"] = {}
            structured_store.path.write_text(json.dumps(value), encoding="utf-8")
            before = structured_store.path.read_bytes()

            workspaces = ProjectWorkspaceStore(root)
            listed = workspaces.list()
            restored = workspaces.structured_director_store(document.project_id).read()

            self.assertEqual([item.id for item in listed], [document.project_id])
            assert restored.video_plan is not None
            self.assertTrue(
                all(
                    not video_slot(item, "additional_images")
                    for item in restored.video_plan.segments
                )
            )
            self.assertTrue(
                all(
                    not video_slot(item, "reference_audios")
                    for item in restored.video_plan.segments
                )
            )
            self.assertTrue(
                all(
                    not video_slot(item, "reference_videos")
                    for item in restored.video_plan.segments
                )
            )
            self.assertEqual(structured_store.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
