from __future__ import annotations

import asyncio
import json
import threading
import unittest
from http.client import HTTPConnection

from core.structured_director import JsonResponse
from server.http import StoryRailHttpServer


class SlowApi:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    async def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        media_type: str | None = None,
    ) -> JsonResponse:
        del body, media_type
        if method == "POST" and path == "/slow":
            self.started.set()
            while not self.release.is_set():
                await asyncio.sleep(0.01)
            return JsonResponse(200, {"completed": True})
        return JsonResponse(200, {"readable": True})


class StoryRailHttpServerTests(unittest.TestCase):
    def test_parser_error_uses_complete_error_contract(self) -> None:
        event_loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=event_loop.run_forever, daemon=True)
        loop_thread.start()
        server = StoryRailHttpServer(("127.0.0.1", 0), SlowApi(), event_loop)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection(*server.server_address, timeout=2)
        try:
            connection.request("POST", "/slow", body=b"{}")
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 415)
            self.assertEqual(
                payload["error"],
                {
                    "code": "unsupported_media_type",
                    "message": "请求必须使用 application/json。",
                    "recoverable": True,
                    "origin": "core_parser",
                    "state_changed": False,
                    "retry_policy": "fix_arguments_and_retry",
                    "automatic_retry_allowed": False,
                },
            )
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            event_loop.call_soon_threadsafe(event_loop.stop)
            loop_thread.join(timeout=2)
            event_loop.close()

    def test_read_request_is_served_while_agent_request_is_still_running(self) -> None:
        event_loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=event_loop.run_forever, daemon=True)
        loop_thread.start()
        api = SlowApi()
        server = StoryRailHttpServer(("127.0.0.1", 0), api, event_loop)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        host, port = server.server_address
        slow_result: list[dict[str, bool]] = []

        def request_slow() -> None:
            connection = HTTPConnection(host, port, timeout=2)
            try:
                connection.request(
                    "POST",
                    "/slow",
                    body=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                slow_result.append(json.loads(response.read()))
            finally:
                connection.close()

        slow_thread = threading.Thread(target=request_slow)
        slow_thread.start()
        try:
            self.assertTrue(api.started.wait(timeout=1))
            connection = HTTPConnection(host, port, timeout=1)
            try:
                connection.request("GET", "/projects")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {"readable": True})
            finally:
                connection.close()
        finally:
            api.release.set()
            slow_thread.join(timeout=2)
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            event_loop.call_soon_threadsafe(event_loop.stop)
            loop_thread.join(timeout=2)
            event_loop.close()

        self.assertEqual(slow_result, [{"completed": True}])


if __name__ == "__main__":
    unittest.main()
