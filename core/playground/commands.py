"""Playground 命令信封、请求摘要与持久幂等。

L5 命令层：负责信封校验、caller 归属、幂等重放与分派；真正的业务变更仍由
Service 在锁内、在自己的 commit 里完成。请求记录和业务变更必须在同一次写入里
落盘，因此记录检查发生在 commit 的 mutate 内部（``stage_request``）。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from core.application.caller import Caller

from .errors import IdempotencyConflictError, RunNotFoundError
from .lifecycle import utc_timestamp
from .models import (
    TERMINAL_PHASES,
    PlaygroundDocument,
    PlaygroundRequestRecord,
    PlaygroundRun,
    canonical_json,
)
from .projection import capability_descriptors, serialize_asset, serialize_run
from .usage import asset_usage

READ_COMMANDS = frozenset(
    {
        "playground.list_capabilities",
        "playground.list_runs",
        "playground.get_runs",
        "playground.list_assets",
    }
)
OBSERVE_COMMANDS = frozenset({"playground.wait_runs"})
WRITE_COMMANDS = frozenset(
    {
        "playground.submit_run",
        "playground.cancel_run",
        "playground.retry_run",
        "playground.dismiss_run",
        "playground.set_note",
    }
)
ALL_COMMANDS = READ_COMMANDS | OBSERVE_COMMANDS | WRITE_COMMANDS

_ENVELOPE_FIELDS = {"name", "idempotency_key", "arguments"}

_ARGUMENT_FIELDS: dict[str, frozenset[str]] = {
    "playground.list_capabilities": frozenset(),
    "playground.list_runs": frozenset({"limit", "cursor", "capability", "include_dismissed"}),
    "playground.get_runs": frozenset({"run_ids"}),
    "playground.list_assets": frozenset({"limit", "cursor", "media_kind"}),
    "playground.submit_run": frozenset({"capability", "parameters", "note"}),
    "playground.wait_runs": frozenset({"run_ids"}),
    "playground.cancel_run": frozenset({"run_id"}),
    "playground.retry_run": frozenset({"run_id"}),
    "playground.dismiss_run": frozenset({"run_id"}),
    "playground.set_note": frozenset({"run_id", "note"}),
}

_ANONYMOUS = Caller("anonymous", "human", frozenset(), frozenset({"human.write"}), 2**62)

_READ_SUMMARY = "只读查询完成，Playground 没有发生修改。"


@dataclass(slots=True)
class RequestContext:
    request_id: str
    caller_id: str
    idempotency_key: str
    request_digest: str
    operation: str
    created_at: str
    receipt: dict[str, Any] | None = None


class ReplayedRequest(Exception):
    """同一个幂等键的请求已经执行过；携带首次保存的完整回执。"""

    def __init__(self, receipt_json: str) -> None:
        super().__init__("请求已执行过。")
        self.receipt_json = receipt_json


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def request_context(envelope: object, caller: Caller | None) -> RequestContext:
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_FIELDS:
        raise ValueError("命令信封必须只包含 name、idempotency_key 和 arguments。")
    name = envelope["name"]
    if name not in ALL_COMMANDS:
        raise ValueError(f"不支持的命令：{name}")
    key = envelope["idempotency_key"]
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise ValueError("idempotency_key 必须是 1 到 200 字符的文本。")
    arguments = envelope["arguments"]
    if not isinstance(arguments, dict) or set(arguments) != set(_ARGUMENT_FIELDS[name]):
        raise ValueError(f"{name} 的 arguments 字段不合法。")
    actor = caller or _ANONYMOUS
    return RequestContext(
        request_id=_digest([actor.id, "playground", key]),
        caller_id=actor.id,
        idempotency_key=key,
        request_digest=_digest([name, arguments, actor.role, sorted(actor.capabilities)]),
        operation=name,
        created_at=utc_timestamp(),
    )


def stage_request(
    document: PlaygroundDocument,
    context: RequestContext,
    *,
    build_receipt: Callable[[PlaygroundDocument], dict[str, Any]],
) -> PlaygroundDocument:
    """在业务变更的 mutate 内部登记请求记录；重放时抛出 ReplayedRequest。"""
    for record in document.application_requests:
        if record.request_id != context.request_id:
            continue
        if record.request_digest == context.request_digest:
            raise ReplayedRequest(record.receipt_json)
        raise IdempotencyConflictError("同一 idempotency_key 已用于不同请求。")
    receipt = build_receipt(document)
    context.receipt = receipt
    record = PlaygroundRequestRecord(
        request_id=context.request_id,
        caller_id=context.caller_id,
        idempotency_key=context.idempotency_key,
        request_digest=context.request_digest,
        operation=context.operation,
        receipt_json=canonical_json(receipt),
        created_at=context.created_at,
    )
    records = (*document.application_requests, record)
    if len(records) > 1000:
        records = records[-1000:]
    return replace(document, application_requests=records)


def write_envelope(
    context: RequestContext,
    document: PlaygroundDocument,
    *,
    status: str,
    old_revision: int,
    new_revision: int,
    decision_summary: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "receipt": {
            "command_id": context.request_id,
            "status": status,
            "old_revision": old_revision,
            "new_revision": new_revision,
            "decision_summary": decision_summary,
        },
        "data": data,
    }


def read_envelope(
    name: str, arguments: dict[str, Any], document: PlaygroundDocument, data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "receipt": {
            "command_id": _digest([name, arguments]),
            "status": "noop",
            "old_revision": document.revision,
            "new_revision": document.revision,
            "decision_summary": _READ_SUMMARY,
        },
        "data": data,
    }


def run_view(service, run: PlaygroundRun) -> dict[str, Any]:
    return serialize_run(run, observed=service.observed_run(run))


async def execute_command(service, envelope: object, caller: Caller | None) -> dict[str, Any]:
    context = request_context(envelope, caller)
    arguments = envelope["arguments"]  # type: ignore[index]
    name = context.operation
    if name in READ_COMMANDS:
        return _execute_read(service, name, arguments)
    if name in OBSERVE_COMMANDS:
        return await _execute_observe(service, name, arguments, context)
    try:
        return await _execute_write(service, name, arguments, context)
    except ReplayedRequest as replay:
        return json.loads(replay.receipt_json)


def _execute_read(service, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    document = service.snapshot()
    if name == "playground.list_capabilities":
        data: dict[str, Any] = {
            "capabilities": capability_descriptors(service, include_schema=True)
        }
    elif name == "playground.list_runs":
        runs = list(document.runs)
        if arguments["capability"] is not None:
            wanted = arguments["capability"]
            runs = [run for run in runs if run.capability == wanted]
        if not arguments["include_dismissed"]:
            runs = [run for run in runs if not run.dismissed]
        page, next_cursor = _paginate(
            runs, arguments["limit"], arguments["cursor"], lambda run: (run.created_at, run.id)
        )
        data = {
            "runs": [run_view(service, run) for run in page],
            "next_cursor": next_cursor,
        }
    elif name == "playground.get_runs":
        data = {
            "runs": [
                run_view(service, _find_run(document, run_id)) for run_id in arguments["run_ids"]
            ]
        }
    else:
        assets = list(document.assets)
        if arguments["media_kind"] is not None:
            assets = [asset for asset in assets if asset.media_kind == arguments["media_kind"]]
        page, next_cursor = _paginate(
            assets,
            arguments["limit"],
            arguments["cursor"],
            lambda asset: (asset.created_at, asset.id),
        )
        usage = asset_usage(document)
        data = {
            "assets": [
                serialize_asset(
                    asset,
                    usage=usage.get(asset.id, ()),
                    pano_source=service.is_pano_source(asset),
                )
                for asset in page
            ],
            "next_cursor": next_cursor,
        }
    return read_envelope(name, arguments, document, data)


async def _execute_observe(
    service, name: str, arguments: dict[str, Any], context: RequestContext
) -> dict[str, Any]:
    del name
    before = service.snapshot()
    runs = await service.wait_runs(tuple(arguments["run_ids"]))
    after = service.snapshot()
    status = "succeeded" if after.revision != before.revision else "noop"
    return write_envelope(
        context,
        after,
        status=status,
        old_revision=before.revision,
        new_revision=after.revision,
        decision_summary="已等待并读取指定实验的最新 Provider 状态。",
        data={
            "runs": [run_view(service, run) for run in runs],
            "all_terminal": all(run.phase in TERMINAL_PHASES for run in runs),
        },
    )


async def _execute_write(
    service, name: str, arguments: dict[str, Any], context: RequestContext
) -> dict[str, Any]:
    before = service.snapshot()
    if name == "playground.submit_run":
        run = await service.submit_run(
            arguments["capability"],
            arguments["parameters"],
            note=arguments["note"],
            request=context,
        )
        return _write_response(service, context, before, run)
    if name == "playground.retry_run":
        run = await service.retry_run(arguments["run_id"], request=context)
        return _write_response(service, context, before, run)
    if name == "playground.cancel_run":
        run = await service.cancel_run(arguments["run_id"], request=context)
        return _write_response(service, context, before, run)
    if name == "playground.dismiss_run":
        run = await service.dismiss_run(arguments["run_id"], request=context)
        return _write_response(service, context, before, run)
    run = await service.set_note(arguments["run_id"], arguments["note"], request=context)
    return _write_response(service, context, before, run)


def _write_response(service, context: RequestContext, before, run: PlaygroundRun) -> dict[str, Any]:
    if context.receipt is not None:
        return context.receipt
    after = service.snapshot()
    return write_envelope(
        context,
        after,
        status="noop",
        old_revision=before.revision,
        new_revision=after.revision,
        decision_summary="当前状态不需要修改，Playground 没有发生变更。",
        data={"run": run_view(service, run)},
    )


def _find_run(document: PlaygroundDocument, run_id: str) -> PlaygroundRun:
    for run in document.runs:
        if run.id == run_id:
            return run
    raise RunNotFoundError("实验不存在。")


def _paginate(
    items: list[Any], limit: int, cursor: str | None, key: Callable[[Any], tuple[str, str]]
) -> tuple[list[Any], str | None]:
    ordered = sorted(items, key=key, reverse=True)
    start = 0
    if cursor is not None:
        marker = _decode_cursor(cursor)
        for index, item in enumerate(ordered):
            if list(key(item)) == marker:
                start = index + 1
                break
        else:
            start = len(ordered)
    page = ordered[start : start + limit]
    if start + limit >= len(ordered) or not page:
        return page, None
    last = key(page[-1])
    return page, _encode_cursor(last)


def _encode_cursor(key: tuple[str, str]) -> str:
    encoded = base64.urlsafe_b64encode(canonical_json(list(key)).encode("utf-8"))
    return encoded.decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> list[str]:
    if not isinstance(cursor, str):
        raise ValueError("cursor 不合法。")
    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(cursor + padding)
        value = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("cursor 不合法。") from exc
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, str) for item in value)
    ):
        raise ValueError("cursor 不合法。")
    return value
