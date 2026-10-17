from __future__ import annotations

import re
from dataclasses import dataclass

_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class RunTarget:
    run_id: str


@dataclass(frozen=True, slots=True)
class RunResume:
    run_id: str
    raw_user_request: str | None


def parse_run_target(value: object, command_name: str) -> RunTarget:
    item = _exact(value, {"run_id"}, command_name)
    return RunTarget(_id(item["run_id"], "run_id"))


def parse_run_resume(value: object) -> RunResume:
    item = _exact(value, {"run_id", "raw_user_request"}, "run.resume")
    raw_user_request = item["raw_user_request"]
    if raw_user_request is not None:
        if not isinstance(raw_user_request, str) or not raw_user_request.strip():
            raise ValueError("run.resume.raw_user_request 必须是非空字符串或 null。")
        if len(raw_user_request) > 20_000:
            raise ValueError("run.resume.raw_user_request 不能超过 20000 字符。")
        raw_user_request = raw_user_request.strip()
    return RunResume(_id(item["run_id"], "run_id"), raw_user_request)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label}.arguments 包含缺失或未声明字段。")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} 必须是 32 位小写十六进制 ID。")
    return value
