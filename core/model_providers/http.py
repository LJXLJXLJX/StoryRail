"""具体模型插件共享的低级 HTTP 工具，不定义任何 Provider RPC。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any, Protocol

from .boundary import ModelProviderError


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json_object(self) -> dict[str, Any]:
        try:
            value = json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError("invalid_response", "外部服务没有返回合法 JSON。") from exc
        if not isinstance(value, dict):
            raise ModelProviderError("invalid_response", "外部服务 JSON 顶层必须是对象。")
        return value


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse: ...


class UrllibTransport:
    """无 SDK 依赖的默认传输；认证头由具体插件配置决定。"""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self._headers = dict(headers or {})

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        headers = {"Accept": "application/json", **self._headers}
        body = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=response.status,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            try:
                return HttpResponse(
                    status=exc.code,
                    headers={key.lower(): value for key, value in exc.headers.items()},
                    body=exc.read(),
                )
            finally:
                exc.close()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelProviderError(
                "transport_error", f"外部模型服务不可用：{exc}", retryable=True
            ) from exc


def require_keys(
    data: dict[str, Any],
    *,
    required: AbstractSet[str],
    optional: AbstractSet[str] = frozenset(),
) -> None:
    unknown = set(data) - required - optional
    missing = required - set(data)
    if unknown or missing:
        details = []
        if missing:
            details.append(f"缺少字段 {sorted(missing)}")
        if unknown:
            details.append(f"包含未知字段 {sorted(unknown)}")
        raise ModelProviderError("invalid_response", "外部响应 " + "；".join(details) + "。")


def require_success(response: HttpResponse, expected: set[int]) -> dict[str, Any]:
    data = response.json_object()
    if response.status not in expected:
        message = data.get("message")
        raise ModelProviderError(
            "external_error",
            str(message) if isinstance(message, str) else f"外部服务返回 HTTP {response.status}。",
            retryable=response.status >= 500,
        )
    return data
