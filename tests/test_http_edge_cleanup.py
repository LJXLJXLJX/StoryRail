"""P5-A3 server 边缘清理回归：共享判定、服务缓存、超时与有界线程。"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from http.client import HTTPConnection

from core.structured_director import JsonResponse
from server.__main__ import main
from server.api import StoryRailApi
from server.http import StoryRailHttpServer
from storyrail_contracts.http_edge import is_media_upload_path, query_is_allowed


class _Workspaces:
    def get(self, project_id: str) -> object:
        del project_id
        return object()


def test_http_edge_shared_query_and_media_upload_decisions() -> None:
    assert is_media_upload_path("/api/projects/x/structured-director/assets/media")
    assert is_media_upload_path("http://example.test/structured-director/assets/images?x=1")
    assert not is_media_upload_path("/api/projects/x/structured-director/final/generate")
    assert query_is_allowed("/assets/media", "expected_revision=1")
    assert not query_is_allowed("/final/generate", "expected_revision=1")


def test_structured_director_service_cache_evicts_lru() -> None:
    calls: list[str] = []

    def factory(project_id: str) -> object:
        calls.append(project_id)
        return object()

    api = StoryRailApi(
        _Workspaces(),
        factory,
        structured_director_service_cache_size=2,
    )
    first, second, third = ("a" * 32, "b" * 32, "c" * 32)
    api._structured_director_service(first)
    api._structured_director_service(second)
    api._structured_director_service(first)
    api._structured_director_service(third)

    assert list(api._structured_director_services) == [first, third]
    assert calls == [first, second, third]


def test_structured_director_service_cache_is_single_flight_under_threads() -> None:
    project_id = "d" * 32
    calls = 0
    lock = threading.Lock()

    def factory(value: str) -> object:
        nonlocal calls
        assert value == project_id
        time.sleep(0.02)
        with lock:
            calls += 1
        return object()

    api = StoryRailApi(_Workspaces(), factory, structured_director_service_cache_size=2)
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            api._structured_director_service(project_id)
        except BaseException as exc:  # pragma: no cover - 失败时由主线程重抛
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert calls == 1


class _SlowApi:
    async def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        media_type: str | None = None,
    ) -> JsonResponse:
        del method, path, body, media_type
        await asyncio.sleep(5.0)
        return JsonResponse(200, {"completed": True})


def test_handler_future_result_default_timeout_is_enforced() -> None:
    event_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=event_loop.run_forever, daemon=True)
    loop_thread.start()
    server = StoryRailHttpServer(
        ("127.0.0.1", 0),
        _SlowApi(),
        event_loop,
        request_timeout_seconds=0.05,
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    connection = HTTPConnection(*server.server_address, timeout=2)
    try:
        connection.request(
            "POST",
            "/slow",
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 504
        assert body["error"]["code"] == "request_timeout"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        event_loop.call_soon_threadsafe(event_loop.stop)
        loop_thread.join(timeout=2)
        event_loop.close()


def test_main_accepts_port_zero(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "server.__main__._serve",
        lambda arguments, parser: captured.update(port=arguments.port, parser=parser),
    )
    monkeypatch.setattr(
        sys, "argv", ["server", "--stories-directory", str(tmp_path), "--port", "0"]
    )
    main()
    assert captured["port"] == 0
