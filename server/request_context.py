"""HTTP 请求上下文：只放传输层需要传给应用管线的只读信息。"""

from __future__ import annotations

from contextvars import ContextVar

current_http_origin: ContextVar[str | None] = ContextVar("slatehand_http_origin", default=None)
