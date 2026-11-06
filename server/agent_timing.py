"""外部 Agent 命令的轻量计时日志：区分 Core 处理耗时与 Agent 两次调用之间的自身耗时。

只记录元数据（调用方 ID、命令名、读取能力、字节数、状态与耗时），不记录参数正文、响应正文或凭据。
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_COMMAND_PATH = re.compile(
    r"^/api/(?:projects/(?P<project_id>[0-9a-f]{32})/structured-director/application"
    r"|playground)/commands$"
)
_LIMIT_BYTES = 8 * 1024 * 1024


class AgentTimingLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        # 每个调用方上一次响应完成的单调时钟；用于计算 Agent 自身耗时。
        self._last_finished: dict[str, float] = {}

    @staticmethod
    def applies(path: str) -> bool:
        return _COMMAND_PATH.match(path) is not None

    def record(
        self,
        *,
        caller_id: str,
        path: str,
        body: bytes,
        status: int,
        response_body: Any,
        started: float,
        finished: float,
    ) -> None:
        match = _COMMAND_PATH.match(path)
        if match is None:
            return
        command, detail = _command(body)
        with self._lock:
            previous = self._last_finished.get(caller_id)
            self._last_finished[caller_id] = finished
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "caller_id": caller_id,
                "project_id": match.group("project_id"),
                "command": command,
                "detail": detail,
                "status": status,
                "request_bytes": len(body),
                "response_bytes": _size(response_body),
                "core_ms": round((finished - started) * 1000),
                # 上一次响应完成到本次请求到达：Agent 思考、生成与传输，不含 Core 处理。
                "agent_ms": None if previous is None else round((started - previous) * 1000),
            }
            self._append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))

    def _append(self, line: str) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists() and self._path.stat().st_size > _LIMIT_BYTES:
                self._path.replace(self._path.with_suffix(".prev.jsonl"))
            with self._path.open("a", encoding="utf-8") as log:
                log.write(line + "\n")
        except OSError:
            # 计时日志只用于诊断，写入失败不影响业务请求。
            return


def _command(body: bytes) -> tuple[str | None, str | None]:
    try:
        value = json.loads(body)
    except ValueError:
        return None, None
    if not isinstance(value, dict):
        return None, None
    name = value.get("name") if isinstance(value.get("name"), str) else None
    arguments = value.get("arguments")
    detail = None
    if isinstance(arguments, dict):
        for key in ("capability", "kind", "level", "action"):
            if isinstance(arguments.get(key), str):
                detail = arguments[key]
                break
    return name, detail


def _size(value: Any) -> int | None:
    if isinstance(value, bytes):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return None
