"""PG3-T4：项目与 Playground 之间的跨域资产复制。"""

from __future__ import annotations

import asyncio
import io
import json
import wave
from pathlib import Path

from provider_factory import provider_registry
from test_director_commands import _visual_project

from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import StructuredDirectorService
from core.structured_director.models import ImageAssetCategory
from core.structured_director.schema import PROJECT_SCHEMA_VERSION
from server.api import StoryRailApi

PNG = b"\x89PNG\r\n\x1a\n" + b"project-reference"


def wav_bytes(duration_seconds: float = 1.0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(b"\x00\x00" * int(duration_seconds * 8_000))
    return output.getvalue()


def make_api(directory: str, service: StructuredDirectorService) -> StoryRailApi:
    root = Path(directory)
    workspaces = ProjectWorkspaceStore(root)
    playground = PlaygroundService(PlaygroundStore(root / ".playground"), provider_registry())
    return StoryRailApi(
        workspaces,
        lambda project_id: service,
        playground_service=playground,
    )


def project_document(directory: str, project_id: str):
    return ProjectWorkspaceStore(Path(directory)).structured_director_store(project_id).read()


def test_copy_project_image_to_playground_records_origin(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = str(tmp_path)
        _store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        document = await service.import_image_asset(
            media_type="image/png",
            content=PNG,
            category=ImageAssetCategory.CHARACTER_REFERENCE,
            filename="小满.png",
            expected_revision=document.revision,
        )
        source = document.assets[-1]

        response = await api.handle(
            "POST",
            "/api/playground/assets/copy-from-project",
            json.dumps({"project_id": document.project_id, "asset_id": source.id}).encode(),
        )
        assert response.status == 200, response.body
        asset = response.body["asset"]
        assert asset["origin"]["kind"] == "copied_from_project"
        assert asset["origin"]["project_id"] == document.project_id
        assert asset["origin"]["asset_id"] == source.id
        assert asset["relative_path"].startswith("assets/images/from-projects/")
        # 项目侧 display_name 带扩展名（Studio 现状），Playground 按卡片规格原样用作 label。
        assert asset["display_name"] == "小满.png"

        playground_asset, content = api._playground_service.read_asset(asset["id"])  # noqa: SLF001
        assert content == PNG
        assert playground_asset.sha256 == source.sha256

    asyncio.run(scenario())


def test_copy_project_asset_twice_is_idempotent_by_bytes(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = str(tmp_path)
        _store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        document = await service.import_image_asset(
            media_type="image/png",
            content=PNG,
            category=ImageAssetCategory.CHARACTER_REFERENCE,
            expected_revision=document.revision,
        )
        source = document.assets[-1]
        body = json.dumps({"project_id": document.project_id, "asset_id": source.id}).encode()
        first = await api.handle("POST", "/api/playground/assets/copy-from-project", body)
        revision = api._playground_service.snapshot().revision  # noqa: SLF001
        second = await api.handle("POST", "/api/playground/assets/copy-from-project", body)
        assert second.body == first.body
        assert api._playground_service.snapshot().revision == revision  # noqa: SLF001
        assert first.body["asset"]["origin"]["kind"] == "copied_from_project"

    asyncio.run(scenario())


def test_copy_playground_wav_to_project_as_imported_media(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = str(tmp_path)
        store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        content = wav_bytes()
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=旁白草稿.wav",
            content,
            media_type="audio/wav",
        )
        assert uploaded.status == 200
        asset_id = uploaded.body["asset"]["id"]

        response = await api.handle(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            json.dumps(
                {
                    "asset_id": asset_id,
                    "expected_revision": document.revision,
                    "image_category": None,
                }
            ).encode(),
        )
        assert response.status == 200, response.body
        assert response.body["asset_id"] == asset_id
        updated = store.read()
        assert response.body["project_revision"] == updated.revision
        copied = next(item for item in updated.assets if item.id == asset_id)
        assert copied.relative_path.startswith("assets/audio/imported/")
        assert updated.schema_version == PROJECT_SCHEMA_VERSION
        assert "playground" not in json.dumps(store.path.read_text(encoding="utf-8"))

    asyncio.run(scenario())


def test_copy_playground_image_requires_importable_category(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = str(tmp_path)
        _store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=抽帧.png",
            PNG,
            media_type="image/png",
        )
        asset_id = uploaded.body["asset"]["id"]
        for category in ("video_frame", None):
            response = await api.handle(
                "POST",
                f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
                json.dumps(
                    {
                        "asset_id": asset_id,
                        "expected_revision": document.revision,
                        "image_category": category,
                    }
                ).encode(),
            )
            assert response.status == 400, category
            assert response.body["error"]["code"] == "invalid_request"

        accepted = await api.handle(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            json.dumps(
                {
                    "asset_id": asset_id,
                    "expected_revision": document.revision,
                    "image_category": "keyframe",
                }
            ).encode(),
        )
        assert accepted.status == 200, accepted.body

    asyncio.run(scenario())


def test_copy_to_project_revision_conflict(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = str(tmp_path)
        _store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=参考.wav",
            wav_bytes(),
            media_type="audio/wav",
        )
        response = await api.handle(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            json.dumps(
                {
                    "asset_id": uploaded.body["asset"]["id"],
                    "expected_revision": document.revision + 5,
                    "image_category": None,
                }
            ).encode(),
        )
        assert response.status == 409
        assert response.body["error"]["code"] == "revision_conflict"
        assert response.body["error"]["recoverable"] is True

    asyncio.run(scenario())


def test_copy_to_project_rejected_by_project_core(tmp_path: Path) -> None:
    """项目 Core 拒绝导入时返回 409 project_write_rejected 并透传中文原因。

    卡片原本设想「awaiting_reference_proposal 阶段拒绝导入」，但项目侧的导入门禁
    只拒绝 APPROVED 状态与 Director 运行中；真实可复现的项目侧拒绝是分类冲突。
    """

    async def scenario() -> None:
        directory = str(tmp_path)
        _store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=同一张图.png",
            PNG,
            media_type="image/png",
        )
        asset_id = uploaded.body["asset"]["id"]
        first = await api.handle(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            json.dumps(
                {
                    "asset_id": asset_id,
                    "expected_revision": document.revision,
                    "image_category": "keyframe",
                }
            ).encode(),
        )
        assert first.status == 200, first.body

        current = service.snapshot()
        conflict = await api.handle(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            json.dumps(
                {
                    "asset_id": asset_id,
                    "expected_revision": current.revision,
                    "image_category": "character_reference",
                }
            ).encode(),
        )
        assert conflict.status == 409
        assert conflict.body["error"]["code"] == "project_write_rejected"
        assert "不能重复归入其它分类" in conflict.body["error"]["message"]

    asyncio.run(scenario())


def test_copy_unknown_project_or_asset_404(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = str(tmp_path)
        _store, service, document, _route = await _visual_project(directory)
        api = make_api(directory, service)
        unknown_project = await api.handle(
            "POST",
            "/api/playground/assets/copy-from-project",
            json.dumps({"project_id": "f" * 32, "asset_id": "a" * 32}).encode(),
        )
        assert unknown_project.status == 404
        assert unknown_project.body["error"]["code"] == "project_not_found"

        unknown_asset = await api.handle(
            "POST",
            "/api/playground/assets/copy-from-project",
            json.dumps({"project_id": document.project_id, "asset_id": "a" * 32}).encode(),
        )
        assert unknown_asset.status == 404
        assert unknown_asset.body["error"]["code"] == "asset_not_found"

        missing = await api.handle(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            json.dumps(
                {
                    "asset_id": "a" * 32,
                    "expected_revision": document.revision,
                    "image_category": None,
                }
            ).encode(),
        )
        assert missing.status == 404
        assert missing.body["error"]["code"] == "asset_not_found"

        malformed = await api.handle(
            "POST",
            "/api/playground/assets/copy-from-project",
            json.dumps({"project_id": document.project_id}).encode(),
        )
        assert malformed.status == 400
        assert malformed.body["error"]["code"] == "invalid_request"

    asyncio.run(scenario())


def test_boundary_only_transfer_module_imports_both_sides() -> None:
    import ast

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "server" / "asset_transfer.py").read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
    assert any(module.startswith("core.playground") for module in modules)
    assert any(module.startswith("core.structured_director") for module in modules)
