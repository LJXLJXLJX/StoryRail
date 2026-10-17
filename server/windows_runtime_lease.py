from __future__ import annotations

import threading
import uuid
from contextlib import suppress
from urllib.parse import urlsplit

from core.model_providers.boundary import ModelProviderError
from core.model_providers.http import HttpTransport, UrllibTransport


class WindowsRuntimeLease:
    """维持私有 Windows GPU 服务的 Core 活性租约；不属于模型 Provider 接口。"""

    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        heartbeat_interval_seconds: float = 5.0,
        request_timeout_seconds: float = 2.0,
        transport: HttpTransport | None = None,
        session_id: str | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Windows runtime endpoint 不合法。")
        if heartbeat_interval_seconds <= 0 or request_timeout_seconds <= 0:
            raise ValueError("租约时间参数必须大于零。")
        self._endpoint = endpoint.rstrip("/")
        self._session_id = session_id or uuid.uuid4().hex
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._transport = transport or UrllibTransport({"Authorization": "Bearer " + token})
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="windows-runtime-lease",
            daemon=True,
        )
        self._started = False
        self._closed = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("Windows runtime 租约已经启动。")
        self._started = True
        self._thread.start()

    def close(self) -> None:
        if not self._started or self._closed:
            return
        self._closed = True
        self._stop.set()
        self._thread.join(self._request_timeout_seconds + 1.0)
        with suppress(ModelProviderError):
            self._transport.request(
                "DELETE",
                f"{self._endpoint}/control/controller-leases/{self._session_id}",
                timeout=self._request_timeout_seconds,
            )

    def _run(self) -> None:
        acquired = False
        while not self._stop.is_set():
            route = "heartbeat" if acquired else "acquire"
            try:
                response = self._transport.request(
                    "POST",
                    f"{self._endpoint}/control/controller-lease/{route}",
                    json_body={"session_id": self._session_id},
                    timeout=self._request_timeout_seconds,
                )
                acquired = response.status in ({200} if acquired else {200, 201})
            except ModelProviderError:
                acquired = False
            self._stop.wait(self._heartbeat_interval_seconds)
