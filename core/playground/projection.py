"""Playground 快照与对象投影：把领域值对象转成 Web/Agent 消费的 wire 形状。

L4 读模型：只读取 Service 与 Store，不做任何写入，也不推断状态。
"""

from __future__ import annotations

from .capabilities import capability_spec
from .lifecycle import run_recovery
from .models import (
    TERMINAL_PHASES,
    PlaygroundAsset,
    PlaygroundDocument,
    PlaygroundRun,
    RunPhase,
)
from .parameters import recipe_input_labels
from .usage import UNFINISHED_RUN_INPUT, asset_usage

USAGE_LABELS = {UNFINISHED_RUN_INPUT: "未结束实验的输入"}


def _sort_key(created_at: str, identifier: str) -> tuple[str, str]:
    return (created_at, identifier)


def serialize_asset(
    asset: PlaygroundAsset, *, usage: tuple[str, ...], pano_source: bool
) -> dict[str, object]:
    actions = ["copy_to_project"]
    if asset.media_type == "video/mp4":
        actions.append("video_frame")
    if pano_source:
        actions.append("pano_view")
    if not usage:
        actions.append("delete")
    return {
        "id": asset.id,
        "media_type": asset.media_type,
        "byte_count": asset.byte_count,
        "sha256": asset.sha256,
        "relative_path": asset.relative_path,
        "duration_seconds": asset.duration_seconds,
        "origin": _serialize_origin(asset),
        "created_at": asset.created_at,
        "display_name": asset.display_name,
        "content_url": f"/api/playground/assets/{asset.id}/content",
        "is_in_use": bool(usage),
        "usage_reasons": [{"code": code, "label": USAGE_LABELS.get(code, code)} for code in usage],
        "allowed_actions": actions,
    }


def _serialize_origin(asset: PlaygroundAsset) -> dict[str, object]:
    origin = asset.origin
    if origin.kind == "imported":
        return {"kind": "imported"}
    if origin.kind == "run_output":
        return {"kind": "run_output", "run_id": origin.run_id}
    return {
        "kind": "copied_from_project",
        "project_id": origin.project_id,
        "asset_id": origin.asset_id,
    }


def run_allowed_actions(run: PlaygroundRun) -> list[str]:
    actions = ["set_note"]
    if run.phase not in TERMINAL_PHASES and not run.cancellation_requested:
        actions.append("cancel")
    if (
        run.phase in {RunPhase.FAILED, RunPhase.CANCELLED, RunPhase.SUBMISSION_UNCERTAIN}
        and not run.dismissed
    ):
        actions.append("retry")
    if run.phase in TERMINAL_PHASES and not run.dismissed:
        actions.append("dismiss")
    return actions


def serialize_run(run: PlaygroundRun, *, observed: PlaygroundRun) -> dict[str, object]:
    spec = capability_spec(run.capability, recipe=run.recipe)
    body: dict[str, object] = {
        "id": run.id,
        "capability": str(run.capability),
        "capability_label": spec.label,
        "phase": run.phase.value,
        "progress": observed.progress,
        "message": observed.message,
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
        "provider": (
            None
            if run.provider_snapshot is None
            else {
                "plugin_id": run.provider_snapshot.plugin_id,
                "recipe_id": run.provider_snapshot.recipe_id,
                "summary": run.provider_snapshot.summary,
            }
        ),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "recovery": run_recovery(run),
        "allowed_actions": run_allowed_actions(run),
    }
    if run.recipe is not None:
        body["input_labels"] = recipe_input_labels(run.recipe, run.parameters)
    return body


def capability_descriptors(service, *, include_schema: bool) -> list[dict[str, object]]:
    availability = service.capability_availability()
    descriptors: list[dict[str, object]] = []
    for capability, spec in service.capability_specs().items():
        descriptor: dict[str, object] = {
            "id": str(capability),
            "label": spec.label,
            "group": spec.group,
            "execution": spec.execution,
            "available": availability[capability],
            "notes": spec.notes,
        }
        recipe = service.capability_recipe(capability)
        descriptor["recipe"] = (
            None
            if recipe is None
            else {key: value for key, value in recipe.items() if key != "parameters_schema"}
        )
        if include_schema:
            descriptor["parameters_schema"] = (
                spec.parameters_schema if recipe is None else recipe["parameters_schema"]
            )
        descriptors.append(descriptor)
    return descriptors


def serialize_snapshot(service) -> dict[str, object]:
    document: PlaygroundDocument = service.snapshot()
    usage = asset_usage(document)
    runs = sorted(
        document.runs,
        key=lambda run: _sort_key(run.created_at, run.id),
        reverse=True,
    )
    assets = sorted(
        document.assets,
        key=lambda asset: _sort_key(asset.created_at, asset.id),
        reverse=True,
    )
    return {
        "schema_version": document.schema_version,
        "revision": document.revision,
        "capabilities": capability_descriptors(service, include_schema=False),
        "runs": [serialize_run(run, observed=service.observed_run(run)) for run in runs],
        "assets": [
            serialize_asset(
                asset,
                usage=usage.get(asset.id, ()),
                pano_source=service.is_pano_source(asset),
            )
            for asset in assets
        ],
    }


def asset_view(service, asset: PlaygroundAsset) -> dict[str, object]:
    """单 Asset 投影（上传、跨域复制与列表共用）。"""
    document = service.snapshot()
    usage = asset_usage(document)
    return serialize_asset(
        asset, usage=usage.get(asset.id, ()), pano_source=service.is_pano_source(asset)
    )
