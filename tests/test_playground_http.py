"""PG3-T1：Playground HTTP 路由与 server 装配。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from provider_factory import provider_registry

from core.playground.models import PLAYGROUND_SCHEMA_VERSION
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from core.project_workspaces import ProjectWorkspaceStore
from server.api import StoryRailApi
from server.http import _MAX_ASSET_REQUEST_BYTES, _request_body_limit
from tests.conftest import SyntheticProvider
from tests.playground_fixtures import real_mp4_bytes
from tests.playground_recipes import recipe_for

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WAV = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 16


def _padded_wav(duration_seconds: float = 1.0) -> bytes:
    import io
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(b"\x00\x00" * int(duration_seconds * 8_000))
    return output.getvalue()


def make_api(root: Path, *, with_playground: bool = True) -> StoryRailApi:
    from core.structured_director import StructuredDirectorService

    workspaces = ProjectWorkspaceStore(root)

    def service(project_id: str) -> StructuredDirectorService:
        return StructuredDirectorService(workspaces.structured_director_store(project_id))

    playground = (
        PlaygroundService(
            PlaygroundStore(workspaces.root_directory / ".playground"),
            provider_registry(
                fl2va_provider=SyntheticProvider(
                    media_type="video/mp4",
                    content=b"\x00\x00\x00\x18ftypmp42out",
                    duration_seconds=6.0,
                    plugin_id="test.fl2va",
                )
            ),
        )
        if with_playground
        else None
    )
    return StoryRailApi(workspaces, service, playground_service=playground)


def test_get_snapshot_creates_playground_lazily(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        playground_directory = root / ".playground"
        # 没有装配 Playground 时不创建任何目录，路由按 404 处理。
        plain = make_api(root, with_playground=False)
        assert not playground_directory.exists()
        assert (await plain.handle("GET", "/api/playground")).status == 404
        assert not playground_directory.exists()

        api = make_api(root)
        assert (playground_directory / "playground.json").is_file()
        response = await api.handle("GET", "/api/playground")
        assert response.status == 200
        body = response.body
        assert body["schema_version"] == PLAYGROUND_SCHEMA_VERSION
        assert body["revision"] == 1
        assert len(body["capabilities"]) == 6
        assert body["runs"] == []
        assert body["assets"] == []
        assert (playground_directory / "playground.json").is_file()
        capability = next(item for item in body["capabilities"] if item["id"] == "minimax_h3.fl2va")
        assert capability["available"] is True
        assert capability["label"] == "FL2VA"
        assert "parameters_schema" not in capability

    asyncio.run(scenario())


def test_upload_and_read_content_roundtrip(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        for media_type, content, suffix in (
            ("image/png", PNG, ".png"),
            ("audio/wav", _padded_wav(), ".wav"),
            ("video/mp4", real_mp4_bytes(24, 2.0), ".mp4"),
        ):
            uploaded = await api.handle(
                "POST",
                f"/api/playground/assets/media?filename=素材{suffix}",
                content,
                media_type=media_type,
            )
            assert uploaded.status == 200
            asset = uploaded.body["asset"]
            assert asset["display_name"] == "素材"
            read = await api.handle("GET", asset["content_url"])
            assert read.status == 200
            assert read.body == content
            assert read.media_type == media_type

    asyncio.run(scenario())


def test_upload_rejects_unknown_query_field(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        response = await api.handle(
            "POST",
            "/api/playground/assets/media?name=x",
            PNG,
            media_type="image/png",
        )
        assert response.status == 400
        assert response.body["error"]["code"] == "invalid_request"

        missing_type = await api.handle(
            "POST", "/api/playground/assets/media", PNG, media_type=None
        )
        assert missing_type.status == 400

    asyncio.run(scenario())


def test_delete_assets_route_and_in_use_error_shape(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=首帧.png",
            PNG,
            media_type="image/png",
        )
        asset_id = uploaded.body["asset"]["id"]

        conflict = await api.handle(
            "DELETE", "/api/playground/assets", b'{"asset_ids": ["' + asset_id.encode() + b'"]}'
        )
        assert conflict.status == 200
        assert conflict.body["deleted_asset_ids"] == [asset_id]

        missing = await api.handle(
            "DELETE", "/api/playground/assets", b'{"asset_ids": ["' + b"f" * 32 + b'"]}'
        )
        assert missing.status == 404
        assert missing.body["error"]["code"] == "asset_not_found"

    asyncio.run(scenario())


def _queued_run(asset_id: str, timestamp: str):
    from core.playground.models import PlaygroundRun, RunPhase, canonical_json
    from tests.playground_recipes import PlaygroundCapability

    return PlaygroundRun(
        id="5c9e1a2b3c4d5e6f708192a3b4c5d6e7",
        capability=PlaygroundCapability.VIDEO_FL2VA,
        phase=RunPhase.QUEUED,
        progress=0.0,
        message="首尾帧视频任务已提交。",
        parameters_json=canonical_json(
            {
                "prompt": "推近",
                "aspect_ratio": "16:9",
                "duration_seconds": 6.0,
                "seed": 1,
                "first_frame_asset_id": asset_id,
                "last_frame_asset_id": None,
            }
        ),
        input_asset_ids=(asset_id,),
        seed=1,
        plugin_id="test.fl2va",
        plugin_version=1,
        external_id="external-1",
        output_asset_id=None,
        result_json=None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        note=None,
        dismissed=False,
        created_at=timestamp,
        updated_at=timestamp,
        recipe=recipe_for(PlaygroundCapability.VIDEO_FL2VA),
    )


def test_in_use_asset_error_shape(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=首帧.png",
            PNG,
            media_type="image/png",
        )
        asset_id = uploaded.body["asset"]["id"]

        store = api._playground_service.store  # noqa: SLF001
        from dataclasses import replace

        from core.playground.lifecycle import utc_timestamp

        run = _queued_run(asset_id, utc_timestamp())
        store.commit(
            lambda previous: replace(
                previous, revision=previous.revision + 1, runs=(*previous.runs, run)
            )
        )
        blocked = await api.handle(
            "DELETE",
            "/api/playground/assets",
            b'{"asset_ids": ["' + asset_id.encode() + b'"]}',
        )
        assert blocked.status == 409
        assert blocked.body["error"]["code"] == "asset_in_use"
        assert blocked.body["error"]["asset_ids"] == [asset_id]

        snapshot = await api.handle("GET", "/api/playground")
        asset = snapshot.body["assets"][0]
        assert asset["is_in_use"] is True
        assert asset["usage_reasons"] == [
            {"code": "unfinished_run_input", "label": "未结束实验的输入"}
        ]
        assert "delete" not in asset["allowed_actions"]

    asyncio.run(scenario())


def test_refresh_route_returns_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        response = await api.handle("POST", "/api/playground/runs/refresh", b"")
        assert response.status == 200
        assert response.body["runs"] == []
        assert response.body["revision"] == 1

    asyncio.run(scenario())


def test_video_frame_info_route(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=镜头.mp4",
            real_mp4_bytes(48, 2.0),
            media_type="video/mp4",
        )
        asset_id = uploaded.body["asset"]["id"]
        response = await api.handle("GET", f"/api/playground/assets/{asset_id}/video-frame-info")
        assert response.status == 200
        assert response.body == {"frame_count": 48, "duration_seconds": 2.0}

        uploaded_image = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=图.png",
            PNG,
            media_type="image/png",
        )
        rejected = await api.handle(
            "GET",
            f"/api/playground/assets/{uploaded_image.body['asset']['id']}/video-frame-info",
        )
        assert rejected.status == 400

    asyncio.run(scenario())


def test_playground_routes_404_when_service_missing(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root, with_playground=False)
        for method, path in (
            ("GET", "/api/playground"),
            ("POST", "/api/playground/runs/refresh"),
            ("GET", f"/api/playground/assets/{'a' * 32}/content"),
            ("POST", "/api/playground/assets/copy-from-project"),
        ):
            response = await api.handle(method, path, b"")
            assert response.status == 404, (method, path)
            assert response.body["error"]["code"] == "not_found"

    asyncio.run(scenario())


def test_other_playground_paths_reject_query(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        response = await api.handle("GET", "/api/playground?x=1")
        assert response.status == 400
        assert response.body["error"]["code"] == "invalid_request"

    asyncio.run(scenario())


def test_asset_capabilities_expose_copy_and_delete(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / ".stories"
        root.mkdir()
        api = make_api(root)
        uploaded = await api.handle(
            "POST",
            "/api/playground/assets/media?filename=镜头.mp4",
            real_mp4_bytes(24, 2.0),
            media_type="video/mp4",
        )
        asset = uploaded.body["asset"]
        assert asset["allowed_actions"] == ["copy_to_project", "video_frame", "delete"]
        assert asset["is_in_use"] is False
        assert asset["content_url"].endswith("/content")

    asyncio.run(scenario())


def test_media_upload_path_uses_large_body_limit() -> None:
    assert _request_body_limit("/api/playground/assets/media") == _MAX_ASSET_REQUEST_BYTES
    assert _request_body_limit("/api/playground/assets") != _MAX_ASSET_REQUEST_BYTES
    assert _request_body_limit("/api/playground") != _MAX_ASSET_REQUEST_BYTES
