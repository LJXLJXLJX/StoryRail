from __future__ import annotations

import re
import threading
import time
from typing import Protocol

SESSION_ID = re.compile(r"^[0-9a-f]{32}$")


class LeaseControlledResource(Protocol):
    def activate(self) -> None: ...

    def revoke(self, *, message: str, error_code: str) -> threading.Event: ...


class ControllerLease:
    """私有默认部署的单 Core 活性租约。"""

    def __init__(
        self,
        manager: LeaseControlledResource,
        *,
        timeout_seconds: float,
        check_interval_seconds: float = 1.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("租约超时必须大于零。")
        if not 0 < check_interval_seconds <= timeout_seconds:
            raise ValueError("租约检查间隔不合法。")
        self._manager = manager
        self._timeout_seconds = timeout_seconds
        self._check_interval_seconds = check_interval_seconds
        self._lock = threading.RLock()
        self._session_id: str | None = None
        self._deadline = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._watch,
            name="core-controller-lease",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def acquire(self, session_id: str) -> bool:
        _validate_session_id(session_id)
        with self._lock:
            if self._session_id not in {None, session_id}:
                return False
            first_acquisition = self._session_id is None
            self._session_id = session_id
            self._deadline = time.monotonic() + self._timeout_seconds
            if first_acquisition:
                self._manager.activate()
            return True

    def heartbeat(self, session_id: str) -> bool:
        _validate_session_id(session_id)
        with self._lock:
            if self._session_id != session_id:
                return False
            self._deadline = time.monotonic() + self._timeout_seconds
            return True

    def release(self, session_id: str) -> threading.Event | None:
        _validate_session_id(session_id)
        with self._lock:
            if self._session_id != session_id:
                return None
            self._session_id = None
            self._deadline = 0.0
            return self._manager.revoke(
                message="Mac Core 已关闭，模型调用已取消。",
                error_code="controller_lease_released",
            )

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(max(2.0, self._check_interval_seconds * 2))

    def _watch(self) -> None:
        while not self._stop.wait(self._check_interval_seconds):
            with self._lock:
                if self._session_id is None or time.monotonic() < self._deadline:
                    continue
                self._session_id = None
                self._deadline = 0.0
                self._manager.revoke(
                    message="Mac Core 心跳超时，模型调用已取消并释放 GPU。",
                    error_code="controller_lease_expired",
                )


def _validate_session_id(session_id: str) -> None:
    if SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("session_id 必须是 32 位小写十六进制字符串。")
