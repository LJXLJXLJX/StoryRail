from __future__ import annotations

import threading
import unittest

from core.model_providers.http import HttpResponse
from default_model_providers_implement.controller_lease import ControllerLease
from server.windows_runtime_lease import WindowsRuntimeLease

SESSION_A = "a" * 32
SESSION_B = "b" * 32


class FakeManager:
    def __init__(self) -> None:
        self.activations = 0
        self.revocations: list[tuple[str, str]] = []
        self.revoked = threading.Event()

    def activate(self) -> None:
        self.activations += 1

    def revoke(self, *, message: str, error_code: str) -> threading.Event:
        self.revocations.append((message, error_code))
        self.revoked.set()
        completed = threading.Event()
        completed.set()
        return completed


class ControllerLeaseTests(unittest.TestCase):
    def test_only_current_session_can_renew_or_release(self) -> None:
        manager = FakeManager()
        lease = ControllerLease(manager, timeout_seconds=1, check_interval_seconds=0.05)
        lease.start()
        try:
            self.assertTrue(lease.acquire(SESSION_A))
            self.assertFalse(lease.acquire(SESSION_B))
            self.assertFalse(lease.heartbeat(SESSION_B))
            self.assertIsNone(lease.release(SESSION_B))
            released = lease.release(SESSION_A)
            self.assertIsNotNone(released)
            self.assertEqual(manager.activations, 1)
            self.assertEqual(manager.revocations[-1][1], "controller_lease_released")
        finally:
            lease.shutdown()

    def test_missing_heartbeat_revokes_the_controller(self) -> None:
        manager = FakeManager()
        lease = ControllerLease(
            manager,
            timeout_seconds=0.08,
            check_interval_seconds=0.01,
        )
        lease.start()
        try:
            self.assertTrue(lease.acquire(SESSION_A))
            self.assertTrue(manager.revoked.wait(1))
            self.assertEqual(manager.revocations[-1][1], "controller_lease_expired")
            self.assertTrue(lease.acquire(SESSION_B))
        finally:
            lease.shutdown()


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []
        self.heartbeat_seen = threading.Event()

    def request(self, method, url, *, json_body=None, timeout=30.0):
        del timeout
        self.calls.append((method, url, json_body))
        if url.endswith("/heartbeat"):
            self.heartbeat_seen.set()
            return HttpResponse(200, {}, b"{}")
        if url.endswith("/acquire"):
            return HttpResponse(201, {}, b"{}")
        return HttpResponse(202, {}, b"{}")


class WindowsRuntimeLeaseTests(unittest.TestCase):
    def test_client_acquires_heartbeats_and_releases_one_session(self) -> None:
        transport = FakeTransport()
        lease = WindowsRuntimeLease(
            "http://192.0.2.1:8791",
            "x" * 32,
            heartbeat_interval_seconds=0.01,
            request_timeout_seconds=0.1,
            transport=transport,
            session_id=SESSION_A,
        )
        lease.start()
        self.assertTrue(transport.heartbeat_seen.wait(1))
        lease.close()

        self.assertEqual(
            transport.calls[0][0:2],
            ("POST", "http://192.0.2.1:8791/control/controller-lease/acquire"),
        )
        self.assertEqual(transport.calls[0][2], {"session_id": SESSION_A})
        self.assertEqual(transport.calls[-1][0], "DELETE")
        self.assertTrue(transport.calls[-1][1].endswith("/" + SESSION_A))


if __name__ == "__main__":
    unittest.main()
