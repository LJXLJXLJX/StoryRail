from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.model_providers.boundary import GenerationPhase
from core.model_providers.breeze_tts2 import BreezeTTS2Provider, BreezeTTS2Request
from core.model_providers.http import UrllibTransport
from core.model_providers.mock import MockGenerateRequest, MockModelProvider
from default_model_providers_implement.request_builders import prepare_codex
from default_model_providers_implement.server import ModelApiServer, main
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskStore


class DefaultModelServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.token = "test-token-with-at-least-thirty-two-characters"
        self.server = ModelApiServer(
            ("127.0.0.1", 0),
            Path(self.temporary.name),
            enabled_services={"mock", "breeze_tts_2"},
            auth_token=self.token,
        )
        self.server.manager.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.endpoint = f"http://{host}:{port}"
        self.provider = MockModelProvider(
            self.endpoint,
            UrllibTransport({"Authorization": "Bearer " + self.token}),
        )
        self.voice_provider = BreezeTTS2Provider(
            self.endpoint,
            Path(self.temporary.name) / "breeze-spool",
            UrllibTransport({"Authorization": "Bearer " + self.token}),
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.manager.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.temporary.cleanup()

    def test_mock_vertical_provider_round_trip(self) -> None:
        handle = self.provider.submit(MockGenerateRequest("镜序", delay_ms=10))
        observation = self.provider.observe(handle)
        deadline = time.monotonic() + 5
        while observation.phase not in {
            GenerationPhase.SUCCEEDED,
            GenerationPhase.FAILED,
            GenerationPhase.CANCELLED,
        }:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
            observation = self.provider.observe(handle)
        self.assertIs(observation.phase, GenerationPhase.SUCCEEDED)
        content = self.provider.read_artifact(handle, observation.artifact.artifact_id)
        self.assertEqual(content.decode(), "StoryRail Mock Artifact\n镜序\n")

    def test_unknown_request_field_is_rejected(self) -> None:
        host, port = self.server.server_address
        response = UrllibTransport({"Authorization": "Bearer " + self.token}).request(
            "POST",
            f"http://{host}:{port}/mock/generate",
            json_body={"text": "x", "delay_ms": 0, "shell": "whoami"},
        )
        self.assertEqual(response.status, 422)

    def test_breeze_submit_contract_returns_recoverable_handle(self) -> None:
        handle = self.voice_provider.submit(
            BreezeTTS2Request(text="欢迎来到镜序。", instruction="年轻、清澈、语速舒缓")
        )

        self.assertEqual(handle.plugin_id, "breeze_tts_2.speech")
        self.assertEqual(self.server.store.get(handle.external_id).kind, "breeze_tts_2")

    def test_missing_bearer_token_is_rejected(self) -> None:
        response = UrllibTransport().request("GET", self.endpoint + "/not-found")
        self.assertEqual(response.status, 401)

    def test_disabled_model_interface_does_not_exist(self) -> None:
        response = UrllibTransport({"Authorization": "Bearer " + self.token}).request(
            "GET",
            self.endpoint + "/codex/image-generations/00000000000000000000000000000000",
        )
        self.assertEqual(response.status, 404)

    def test_controller_lease_interface_does_not_exist_when_disabled(self) -> None:
        response = UrllibTransport({"Authorization": "Bearer " + self.token}).request(
            "POST",
            self.endpoint + "/control/controller-lease/acquire",
            json_body={"session_id": "a" * 32},
        )
        self.assertEqual(response.status, 404)

    def test_codex_generate_and_edit_reject_the_wrong_source_shape(self) -> None:
        image = {"content_type": "image/png", "data_base64": "iVBORw0KGgo="}
        common = {
            "instruction": "测试",
            "model": "test",
            "aspect_ratio": "9:16",
            "reference_images": [],
        }

        with self.assertRaisesRegex(RequestError, "生成不能包含"):
            prepare_codex({**common, "source_image": image}, operation="generate")
        with self.assertRaisesRegex(RequestError, "编辑必须包含"):
            prepare_codex({**common, "source_image": None}, operation="edit")

    def test_foreign_model_route_cannot_cancel_mock_task(self) -> None:
        handle = self.provider.submit(MockGenerateRequest("boundary", delay_ms=10_000))
        response = UrllibTransport({"Authorization": "Bearer " + self.token}).request(
            "PATCH",
            self.endpoint + f"/breeze-tts2/speech/{handle.external_id}",
            json_body={"cancel": True},
        )

        self.assertEqual(response.status, 404)
        self.assertFalse(self.server.store.get(handle.external_id).cancel_requested)

    def test_foreign_model_route_cannot_read_mock_artifact(self) -> None:
        handle = self.provider.submit(MockGenerateRequest("boundary", delay_ms=10))
        observation = self.provider.observe(handle)
        deadline = time.monotonic() + 5
        while observation.phase is not GenerationPhase.SUCCEEDED:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
            observation = self.provider.observe(handle)
        response = UrllibTransport({"Authorization": "Bearer " + self.token}).request(
            "GET",
            self.endpoint
            + f"/codex/image-generations/{handle.external_id}/content/{handle.external_id}",
        )

        self.assertEqual(response.status, 404)

    def test_lane_cli_rejects_mixed_flags(self) -> None:
        with self.assertRaises(SystemExit):
            main(
                [
                    "--state-root",
                    self.temporary.name,
                    "--services",
                    "mock,breeze_tts_2",
                    "--lane",
                    "mock_lane:1:mock",
                    "--lane",
                    "tts_lane:1:breeze_tts_2",
                    "--max-concurrent-tasks",
                    "2",
                ]
            )
        with self.assertRaises(SystemExit):
            main(
                [
                    "--state-root",
                    self.temporary.name,
                    "--services",
                    "mock,breeze_tts_2",
                    "--lane",
                    "mock_lane:1:mock",
                    "--lane",
                    "tts_lane:1:breeze_tts_2",
                    "--resource-name",
                    "exclusive_gpu",
                ]
            )

    def test_lane_cli_requires_exact_service_cover(self) -> None:
        with self.assertRaises(SystemExit):
            main(
                [
                    "--state-root",
                    self.temporary.name,
                    "--services",
                    "mock,breeze_tts_2",
                    "--lane",
                    "mock_lane:1:mock",
                ]
            )
        with self.assertRaises(SystemExit):
            main(
                [
                    "--state-root",
                    self.temporary.name,
                    "--services",
                    "mock",
                    "--lane",
                    "mock_lane:1:breeze_tts_2",
                ]
            )

    def test_server_without_lanes_keeps_single_lane(self) -> None:
        server = ModelApiServer(
            ("127.0.0.1", 0),
            Path(self.temporary.name) / "single-lane-state",
            enabled_services={"mock"},
            resource_name="exclusive_gpu",
        )
        try:
            self.assertEqual(len(server.manager.lanes), 1)
            self.assertEqual(server.manager.lanes[0].name, "exclusive_gpu")
            self.assertEqual(server.manager.lanes[0].services, frozenset({"mock"}))
            self.assertEqual(server.manager.lanes[0].max_concurrent_tasks, 1)
        finally:
            server.server_close()

    def test_status_response_uses_queue_message_without_persisting(self) -> None:
        self.provider.submit(MockGenerateRequest("占位", delay_ms=10_000))
        queued = self.provider.submit(MockGenerateRequest("排队", delay_ms=0))

        response = UrllibTransport({"Authorization": "Bearer " + self.token}).request(
            "GET",
            self.endpoint + f"/mock/tickets/{queued.external_id}",
        )
        self.assertEqual(response.status, 200)
        self.assertIn("排队中", response.json_object()["note"])
        persisted = TaskStore(Path(self.temporary.name)).get(queued.external_id)
        self.assertEqual(persisted.message, "等待 exclusive_gpu。")


class ControllerLeaseServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.token = "test-token-with-at-least-thirty-two-characters"
        self.server = ModelApiServer(
            ("127.0.0.1", 0),
            Path(self.temporary.name),
            enabled_services={"mock"},
            auth_token=self.token,
            controller_lease_timeout_seconds=1,
        )
        self.server.manager.start()
        assert self.server.controller_lease is not None
        self.server.controller_lease.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.endpoint = f"http://{host}:{port}"
        self.transport = UrllibTransport({"Authorization": "Bearer " + self.token})

    def tearDown(self) -> None:
        self.server.shutdown()
        assert self.server.controller_lease is not None
        self.server.controller_lease.shutdown()
        self.server.manager.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.temporary.cleanup()

    def test_generation_requires_a_live_controller_lease(self) -> None:
        response = self.transport.request(
            "POST",
            self.endpoint + "/mock/generate",
            json_body={"text": "x", "delay_ms": 0},
        )
        self.assertEqual(response.status, 503)

        acquired = self.transport.request(
            "POST",
            self.endpoint + "/control/controller-lease/acquire",
            json_body={"session_id": "a" * 32},
        )
        self.assertEqual(acquired.status, 201)
        accepted = self.transport.request(
            "POST",
            self.endpoint + "/mock/generate",
            json_body={"text": "x", "delay_ms": 0},
        )
        self.assertEqual(accepted.status, 202)

        released = self.transport.request(
            "DELETE",
            self.endpoint + "/control/controller-leases/" + "a" * 32,
        )
        self.assertEqual(released.status, 202)
        rejected = self.transport.request(
            "POST",
            self.endpoint + "/mock/generate",
            json_body={"text": "x", "delay_ms": 0},
        )
        self.assertEqual(rejected.status, 503)

    def test_lease_schema_and_session_ownership_are_strict(self) -> None:
        invalid = self.transport.request(
            "POST",
            self.endpoint + "/control/controller-lease/acquire",
            json_body={"session_id": "a" * 32, "extra": True},
        )
        self.assertEqual(invalid.status, 422)
        acquired = self.transport.request(
            "POST",
            self.endpoint + "/control/controller-lease/acquire",
            json_body={"session_id": "a" * 32},
        )
        self.assertEqual(acquired.status, 201)
        conflict = self.transport.request(
            "POST",
            self.endpoint + "/control/controller-lease/acquire",
            json_body={"session_id": "b" * 32},
        )
        self.assertEqual(conflict.status, 409)
        foreign_heartbeat = self.transport.request(
            "POST",
            self.endpoint + "/control/controller-lease/heartbeat",
            json_body={"session_id": "b" * 32},
        )
        self.assertEqual(foreign_heartbeat.status, 409)


if __name__ == "__main__":
    unittest.main()
