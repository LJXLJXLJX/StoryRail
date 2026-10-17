"""playground.json 的严格编解码（schema v2）。

包内自己实现严格对象解析，不 import 项目 codec：Playground 与项目互不依赖。
"""

from __future__ import annotations

from typing import Any

from core.model_providers.manifest import ProviderSnapshot, recipe_from_json

from .models import (
    PLAYGROUND_SCHEMA_VERSION,
    AssetOrigin,
    PlaygroundAsset,
    PlaygroundDocument,
    PlaygroundRequestRecord,
    PlaygroundRun,
    canonical_json,
)
from .parameters import validate_run_parameters

_DOCUMENT_FIELDS = {"schema_version", "revision", "assets", "runs", "application_requests"}
_ASSET_FIELDS = {
    "id",
    "media_type",
    "byte_count",
    "sha256",
    "relative_path",
    "duration_seconds",
    "origin",
    "created_at",
}
_ORIGIN_FIELDS = {
    "imported": {"kind"},
    "run_output": {"kind", "run_id"},
    "copied_from_project": {"kind", "project_id", "asset_id"},
}
_RUN_FIELDS = {
    "id",
    "capability",
    "phase",
    "progress",
    "message",
    "parameters",
    "input_asset_ids",
    "seed",
    "plugin_id",
    "plugin_version",
    "external_id",
    "output_asset_id",
    "result",
    "error_code",
    "cancellation_requested",
    "retry_of",
    "note",
    "dismissed",
    "created_at",
    "updated_at",
    "provider_snapshot",
    "recipe",
}
_REQUEST_FIELDS = {
    "request_id",
    "caller_id",
    "idempotency_key",
    "request_digest",
    "operation",
    "receipt_json",
    "created_at",
}


def _exact_object(value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("playground.json 包含缺失或未声明的字段。")
    return value


def _object_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("playground.json 的列表字段必须是数组。")
    return value


def _json_object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"playground.json 的 {field} 必须是对象。")
    return value


def _parse_origin(value: object) -> AssetOrigin:
    if not isinstance(value, dict):
        raise ValueError("playground.json 的 asset.origin 必须是对象。")
    fields = _ORIGIN_FIELDS.get(value.get("kind"))  # type: ignore[arg-type]
    if fields is None:
        raise ValueError("playground.json 的 asset.origin.kind 不受支持。")
    item = _exact_object(value, fields)
    return AssetOrigin(
        kind=item["kind"],
        run_id=item.get("run_id"),
        project_id=item.get("project_id"),
        asset_id=item.get("asset_id"),
    )


def _serialize_origin(origin: AssetOrigin) -> dict[str, Any]:
    if origin.kind == "imported":
        return {"kind": "imported"}
    if origin.kind == "run_output":
        return {"kind": "run_output", "run_id": origin.run_id}
    return {
        "kind": "copied_from_project",
        "project_id": origin.project_id,
        "asset_id": origin.asset_id,
    }


def _parse_asset(value: object) -> PlaygroundAsset:
    item = _exact_object(value, _ASSET_FIELDS)
    return PlaygroundAsset(
        id=item["id"],
        media_type=item["media_type"],
        byte_count=item["byte_count"],
        sha256=item["sha256"],
        relative_path=item["relative_path"],
        duration_seconds=item["duration_seconds"],
        origin=_parse_origin(item["origin"]),
        created_at=item["created_at"],
    )


def _serialize_asset(asset: PlaygroundAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "media_type": asset.media_type,
        "byte_count": asset.byte_count,
        "sha256": asset.sha256,
        "relative_path": asset.relative_path,
        "duration_seconds": asset.duration_seconds,
        "origin": _serialize_origin(asset.origin),
        "created_at": asset.created_at,
    }


def _parse_run(value: object) -> PlaygroundRun:
    item = _exact_object(value, _RUN_FIELDS)
    parameters = _json_object(item["parameters"], "run.parameters")
    result = item["result"]
    if result is not None:
        result = _json_object(result, "run.result")
    input_asset_ids = _object_list(item["input_asset_ids"])
    run = PlaygroundRun(
        id=item["id"],
        capability=item["capability"],
        phase=item["phase"],
        progress=item["progress"],
        message=item["message"],
        parameters_json=canonical_json(parameters),
        input_asset_ids=tuple(input_asset_ids),
        seed=item["seed"],
        plugin_id=item["plugin_id"],
        plugin_version=item["plugin_version"],
        external_id=item["external_id"],
        output_asset_id=item["output_asset_id"],
        result_json=None if result is None else canonical_json(result),
        error_code=item["error_code"],
        cancellation_requested=item["cancellation_requested"],
        retry_of=item["retry_of"],
        note=item["note"],
        dismissed=item["dismissed"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        recipe=None if item["recipe"] is None else recipe_from_json(item["recipe"]),
        provider_snapshot=(
            None
            if item["provider_snapshot"] is None
            else ProviderSnapshot.from_json(item["provider_snapshot"])
        ),
    )
    validate_run_parameters(run)
    return run


def _serialize_run(run: PlaygroundRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "capability": str(run.capability),
        "phase": run.phase.value,
        "progress": run.progress,
        "message": run.message,
        "parameters": run.parameters,
        "input_asset_ids": list(run.input_asset_ids),
        "seed": run.seed,
        "plugin_id": run.plugin_id,
        "plugin_version": run.plugin_version,
        "external_id": run.external_id,
        "output_asset_id": run.output_asset_id,
        "result": run.result,
        "error_code": run.error_code,
        "cancellation_requested": run.cancellation_requested,
        "retry_of": run.retry_of,
        "note": run.note,
        "dismissed": run.dismissed,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "recipe": None if run.recipe is None else run.recipe.to_json(),
        "provider_snapshot": (
            None if run.provider_snapshot is None else run.provider_snapshot.to_json()
        ),
    }


def _parse_request(value: object) -> PlaygroundRequestRecord:
    item = _exact_object(value, _REQUEST_FIELDS)
    return PlaygroundRequestRecord(
        request_id=item["request_id"],
        caller_id=item["caller_id"],
        idempotency_key=item["idempotency_key"],
        request_digest=item["request_digest"],
        operation=item["operation"],
        receipt_json=item["receipt_json"],
        created_at=item["created_at"],
    )


def _serialize_request(record: PlaygroundRequestRecord) -> dict[str, Any]:
    return {
        "request_id": record.request_id,
        "caller_id": record.caller_id,
        "idempotency_key": record.idempotency_key,
        "request_digest": record.request_digest,
        "operation": record.operation,
        "receipt_json": record.receipt_json,
        "created_at": record.created_at,
    }


def serialize_document(document: PlaygroundDocument) -> dict[str, Any]:
    return {
        "schema_version": document.schema_version,
        "revision": document.revision,
        "assets": [_serialize_asset(asset) for asset in document.assets],
        "runs": [_serialize_run(run) for run in document.runs],
        "application_requests": [
            _serialize_request(record) for record in document.application_requests
        ],
    }


def parse_document(value: object) -> PlaygroundDocument:
    root = _exact_object(value, _DOCUMENT_FIELDS)
    if root["schema_version"] != PLAYGROUND_SCHEMA_VERSION:
        raise ValueError("playground.json schema 版本不受支持。")
    return PlaygroundDocument(
        schema_version=root["schema_version"],
        revision=root["revision"],
        assets=tuple(_parse_asset(item) for item in _object_list(root["assets"])),
        runs=tuple(_parse_run(item) for item in _object_list(root["runs"])),
        application_requests=tuple(
            _parse_request(item) for item in _object_list(root["application_requests"])
        ),
    )
