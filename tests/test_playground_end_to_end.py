"""真实 loopback HTTP 上跑通「导入 → 音频截取 → 音频后处理 → 复制到项目」。

这四步都是 Core 本地能力，不需要真机 Provider，因此可以在没有媒体部署的环境里
作为 PG6-T2 的可自动化部分。真机 Provider 项见卡片验收记录。
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import wave
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode

from provider_factory import provider_registry
from test_director_commands import _visual_project

from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director.schema import PROJECT_SCHEMA_VERSION
from server.api import StoryRailApi
from server.http import StoryRailHttpServer


def wav_bytes(duration_seconds: float = 3.0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(b"\x00\x00" * int(duration_seconds * 8_000))
    return output.getvalue()


class Client:
    def __init__(self, host: str, port: int) -> None:
        self.connection = HTTPConnection(host, port, timeout=15)

    def json_request(self, method: str, path: str, body: object | None = None):
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        self.connection.request(
            method,
            path,
            body=payload,
            headers={"Content-Type": "application/json"} if payload else {},
        )
        response = self.connection.getresponse()
        return response.status, json.loads(response.read().decode())

    def upload(self, filename: str, content: bytes, media_type: str):
        self.connection.request(
            "POST",
            "/api/playground/assets/media?" + urlencode({"filename": filename}),
            body=content,
            headers={"Content-Type": media_type},
        )
        response = self.connection.getresponse()
        return response.status, json.loads(response.read().decode())

    def bytes_request(self, path: str):
        self.connection.request("GET", path)
        response = self.connection.getresponse()
        return response.status, response.read(), response.getheader("Content-Type")

    def close(self) -> None:
        self.connection.close()


def test_local_capability_chain_over_real_http(tmp_path: Path) -> None:
    async def prepare():
        store, service, document, _route = await _visual_project(str(tmp_path / "stories"))
        return store, service, document

    stories_root = tmp_path / "stories"
    stories_root.mkdir()
    store, service, document = asyncio.run(prepare())
    playground = PlaygroundService(
        PlaygroundStore(stories_root / ".playground"), provider_registry()
    )
    api = StoryRailApi(
        ProjectWorkspaceStore(stories_root),
        lambda project_id: service,
        playground_service=playground,
    )
    loop = asyncio.new_event_loop()
    worker = threading.Thread(target=loop.run_forever, daemon=True)
    worker.start()
    server = StoryRailHttpServer(("127.0.0.1", 0), api, loop)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    client = Client(host, port)
    try:
        # 1. 导入
        content = wav_bytes()
        status, uploaded = client.upload("旁白草稿.wav", content, "audio/wav")
        assert status == 200, uploaded
        source_id = uploaded["asset"]["id"]
        status, again = client.upload("旁白草稿.wav", content, "audio/wav")
        assert status == 200
        assert again["asset"]["id"] == source_id

        # 2. 音频截取
        status, trimmed = client.json_request(
            "POST",
            "/api/playground/commands",
            {
                "name": "playground.submit_run",
                "idempotency_key": "ui:trim-1",
                "arguments": {
                    "capability": "audio.trim",
                    "parameters": {
                        "audio_asset_id": source_id,
                        "start_seconds": 0.5,
                        "end_seconds": 2.0,
                    },
                    "note": "截取中段",
                },
            },
        )
        assert status == 200, trimmed
        trim_run = trimmed["data"]["run"]
        assert trim_run["phase"] == "succeeded"
        assert trim_run["result"]["metadata"]["output_duration_seconds"] == 1.5

        # 3. 音频后处理（用截取产物作为输入）
        status, processed = client.json_request(
            "POST",
            "/api/playground/commands",
            {
                "name": "playground.submit_run",
                "idempotency_key": "ui:effect-1",
                "arguments": {
                    "capability": "audio.effect",
                    "parameters": {
                        "audio_asset_id": trim_run["output_asset_id"],
                        "preset": "weak_signal",
                        "strength": 0.7,
                        "seed": 42,
                        "start_seconds": None,
                        "end_seconds": None,
                    },
                    "note": None,
                },
            },
        )
        assert status == 200, processed
        effect_run = processed["data"]["run"]
        assert effect_run["phase"] == "succeeded"
        assert effect_run["result"]["schema"] == "storyrail_audio_effect_v1"

        # 快照里能看到三条资产（导入 + 两个产物）与两条 run
        status, snapshot = client.json_request("GET", "/api/playground")
        assert status == 200
        assert len(snapshot["assets"]) == 3
        assert len(snapshot["runs"]) == 2

        # 4. 复制到项目
        status, copied = client.json_request(
            "POST",
            f"/api/projects/{document.project_id}/structured-director/assets/copy-from-playground",
            {
                "asset_id": effect_run["output_asset_id"],
                "expected_revision": store.read().revision,
                "image_category": None,
            },
        )
        assert status == 200, copied
        updated = store.read()
        assert copied["project_revision"] == updated.revision
        copied_asset = next(item for item in updated.assets if item.id == copied["asset_id"])
        assert copied_asset.relative_path.startswith("assets/audio/imported/")
        assert updated.schema_version == PROJECT_SCHEMA_VERSION
        assert "playground" not in store.path.read_text(encoding="utf-8")

        # 素材内容可读
        status, binary, media_type = client.bytes_request(
            f"/api/playground/assets/{source_id}/content"
        )
        assert status == 200
        assert binary == content
        assert media_type == "audio/wav"
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        worker.join(timeout=5)
        loop.close()
