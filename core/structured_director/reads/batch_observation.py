"""外部批次的纯读观察（batch_observation 一族）。

从 external_batches.py 下沉：只从 document 与既有回执/run/Generation 派生观察，
不提交或轮询 Provider；供 reads 包与 external_batches 模块级复用，
避免 reads ↔ external_batches 互相 import 成环。

两类批次共用回执/run/执行轮次骨架：Keyframe 批次（target = Keyframe）与地点图片批次
（`location.generate_set`，target = LocationImage）。
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass

from core.application.caller import current_caller

from ..keyframe_requests import (
    _find_keyframe,
    _keyframe_generation_inputs,
    unselected_reference_keyframes,
    unselected_reference_location_images,
)
from ..location_requests import LOCATION_SET_TERMINAL, location_set_items
from ..models import ReferenceGenerationKind, ReferenceGenerationPhase
from .common import _ids

KEYFRAME_OPERATIONS = {"keyframe.generate_batch", "keyframe.continue_batch"}
LOCATION_SET_OPERATIONS = {"location.generate_set"}
_ALL_OPERATIONS = KEYFRAME_OPERATIONS | LOCATION_SET_OPERATIONS
_ACTIVE_PHASES = {
    ReferenceGenerationPhase.SUBMITTING,
    ReferenceGenerationPhase.QUEUED,
    ReferenceGenerationPhase.RUNNING,
}


@dataclass(frozen=True, slots=True)
class BatchExecutionContext:
    batch_id: str
    execution_run_id: str
    root_execution_run_id: str
    previous_execution_run_id: str | None
    target_ids: tuple[str, ...]
    source_revision: int

    def data(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "execution_run_id": self.execution_run_id,
            "batch_run_id": self.execution_run_id,
            "root_execution_run_id": self.root_execution_run_id,
            "previous_execution_run_id": self.previous_execution_run_id,
            "target_ids": list(self.target_ids),
            "source_revision": self.source_revision,
        }


current_batch_execution: ContextVar[BatchExecutionContext | None] = ContextVar(
    "current_batch_execution", default=None
)


def _receipt_data(record) -> dict[str, object] | None:
    if record.receipt_json is None:
        return None
    value = json.loads(record.receipt_json)
    data = value.get("data") if isinstance(value, dict) else None
    return data if isinstance(data, dict) else None


def _run_targets(document, run_id: str, scope_prefix: str) -> tuple[str, ...]:
    run = next((item for item in document.director_runs if item.id == run_id), None)
    if run is None or not run.authorization.generation_scopes:
        raise ValueError("原批次 scope 丢失，不能扩大范围。")
    scopes = run.authorization.generation_scopes
    if any(not scope.startswith(f"{scope_prefix}:") for scope in scopes):
        raise ValueError("该 run 不是对应类型的批次。")
    return _ids([scope.split(":", 1)[1] for scope in scopes], "batch targets")


def _owned_batch(document, identity: str, operations, scope_prefix: str):
    caller = current_caller.get()
    candidates = []
    for record in document.application_requests:
        if record.operation not in operations or record.receipt_json is None:
            continue
        if caller is None or (record.caller_id != caller.id and caller.role != "human"):
            continue
        data = _receipt_data(record)
        if data is None:
            continue
        identities = {
            data.get("batch_id"),
            data.get("execution_run_id"),
            data.get("batch_run_id"),
        }
        if identity in identities:
            candidates.append((record, data))
    if not candidates:
        raise ValueError("批次不存在或不属于当前 caller。")

    matched_data = candidates[-1][1]
    batch_id = matched_data.get("batch_id")
    if not isinstance(batch_id, str):
        batch_id = matched_data.get("batch_run_id")
    if not isinstance(batch_id, str):
        raise ValueError("原批次身份丢失，不能扩大范围。")
    records = []
    for record in document.application_requests:
        if record.operation not in operations or record.receipt_json is None:
            continue
        data = _receipt_data(record)
        if (
            data is not None
            and data.get("batch_id", data.get("batch_run_id")) == batch_id
            and caller is not None
            and (record.caller_id == caller.id or caller.role == "human")
        ):
            records.append((record, data))
    latest = records[-1][1]
    root_run_id = latest.get("root_execution_run_id")
    if not isinstance(root_run_id, str):
        root_run_id = records[0][1].get("execution_run_id", records[0][1].get("batch_run_id"))
    latest_run_id = latest.get("execution_run_id", latest.get("batch_run_id"))
    if not isinstance(root_run_id, str) or not isinstance(latest_run_id, str):
        raise ValueError("原批次 run 关联丢失，不能扩大范围。")
    targets = latest.get("target_ids")
    if isinstance(targets, list):
        target_ids = _ids(targets, "batch targets")
    else:
        target_ids = _run_targets(document, root_run_id, scope_prefix)
    if _run_targets(document, root_run_id, scope_prefix) != target_ids:
        raise ValueError("原批次 scope 与 run 授权不一致，不能继续。")
    return batch_id, root_run_id, latest_run_id, target_ids


def _owned_any_batch(document, identity: str):
    errors = []
    for operations, prefix in (
        (KEYFRAME_OPERATIONS, "keyframe"),
        (LOCATION_SET_OPERATIONS, "location"),
    ):
        try:
            return _owned_batch(document, identity, operations, prefix)
        except ValueError as exc:
            errors.append(exc)
    raise errors[-1]


def owned_batch_id_for_run(document, run_id: str) -> str | None:
    try:
        return _owned_any_batch(document, run_id)[0]
    except ValueError:
        return None


def _batch_records(document, batch_id: str, operations):
    records = []
    for record in document.application_requests:
        if record.operation not in operations:
            continue
        data = _receipt_data(record)
        if data is not None and data.get("batch_id", data.get("batch_run_id")) == batch_id:
            records.append((record, data))
    return records


def batch_observations(document) -> tuple[dict[str, object], ...]:
    batch_ids = tuple(
        dict.fromkeys(
            data["batch_id"]
            for record in document.application_requests
            if record.operation in _ALL_OPERATIONS
            and (data := _receipt_data(record)) is not None
            and isinstance(data.get("batch_id"), str)
        )
    )
    return tuple(batch_observation(document, batch_id) for batch_id in batch_ids)


def batch_observation(document, batch_id: str) -> dict[str, object]:
    """从批次回执、现有 run 与 Generation 动态派生，不提交或轮询 Provider。"""
    if _batch_records(document, batch_id, KEYFRAME_OPERATIONS):
        return _keyframe_batch_observation(document, batch_id)
    return _location_set_observation(document, batch_id)


def _linked_generation_ids(document, records) -> set[str]:
    linked = set(
        dict.fromkeys(
            generation_id for record, _ in records for generation_id in record.generation_ids
        )
    )
    changed = True
    while changed:
        changed = False
        for generation in document.generations:
            if generation.retry_of in linked and generation.id not in linked:
                linked.add(generation.id)
                changed = True
    return linked


def _batch_executions(document, records) -> list[dict[str, object]]:
    executions = []
    for record, data in records:
        execution_run_id = data.get("execution_run_id", data.get("batch_run_id"))
        run = next((item for item in document.director_runs if item.id == execution_run_id), None)
        executions.append(
            {
                "execution_run_id": execution_run_id,
                "previous_execution_run_id": data.get("previous_execution_run_id"),
                "run_status": None if run is None else run.status.value,
                "application_request_id": record.request_id,
                "generation_ids": list(record.generation_ids),
                "submitted_target_ids": data.get("submitted_target_ids", []),
                "deferred_target_ids": data.get("deferred_target_ids", []),
                "skipped_target_ids": data.get("skipped_target_ids", []),
                "source_revision": data.get("source_revision", record.expected_revision),
                "result_revision": record.result_revision,
            }
        )
    return executions


def _keyframe_batch_observation(document, batch_id: str) -> dict[str, object]:
    records = _batch_records(document, batch_id, KEYFRAME_OPERATIONS)
    if not records:
        raise ValueError("批次不存在。")
    first_data = records[0][1]
    target_ids = _ids(first_data.get("target_ids"), "batch targets")
    root_run_id = first_data.get("root_execution_run_id", first_data.get("execution_run_id"))
    linked = _linked_generation_ids(document, records)

    asset_ids = {asset.id for asset in document.assets}
    target_results = []
    for target_id in target_ids:
        generations = [
            generation
            for generation in document.generations
            if generation.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
            and generation.target_id == target_id
            and (generation.id in linked or not generation.dismissed)
        ]
        linked_for_target = [generation for generation in generations if generation.id in linked]
        try:
            keyframe = _find_keyframe(document, target_id)
        except ValueError:
            target_results.append(
                {
                    "target_id": target_id,
                    "status": "target_missing",
                    "generation_ids": [generation.id for generation in linked_for_target],
                    "current_generation_id": None,
                    "dependency_kind": None,
                    "dependency_target_id": None,
                }
            )
            continue
        dependency_kind: str | None = None
        dependency_target_id: str | None = None
        if keyframe.selected_asset_id in asset_ids:
            status = "already_selected"
            current = None
        else:
            current = next(
                (generation for generation in reversed(generations) if not generation.dismissed),
                None,
            )
            if current is not None and (
                current.phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN
            ):
                status = "submission_uncertain"
            elif current is not None and current.phase in _ACTIVE_PHASES:
                status = current.phase.value
            elif current is not None and (current.phase is ReferenceGenerationPhase.SUCCEEDED):
                if current.output_asset_id in asset_ids:
                    status = "succeeded" if current.id in linked else "existing_result"
                else:
                    status = "invalid_result"
            elif current is not None and current.phase in {
                ReferenceGenerationPhase.FAILED,
                ReferenceGenerationPhase.CANCELLED,
            }:
                status = current.phase.value
            elif unselected_reference_location_images(document, keyframe):
                status = "dependency_blocked"
                dependency_kind = "reference_location_image"
                dependency_target_id = unselected_reference_location_images(document, keyframe)[0]
            elif unselected_reference_keyframes(document, keyframe):
                status = "dependency_blocked"
                dependency_kind = "reference_keyframe"
                dependency_target_id = unselected_reference_keyframes(document, keyframe)[0]
            else:
                try:
                    ready = _keyframe_generation_inputs(document, target_id) is not None
                except ValueError:
                    status = "input_blocked"
                else:
                    if ready:
                        status = "unsubmitted"
                    else:
                        status = "dependency_blocked"
                        dependency_kind = "predecessor_keyframe"
                        dependency_target_id = keyframe.predecessor_keyframe_id
        target_results.append(
            {
                "target_id": target_id,
                "status": status,
                "generation_ids": [generation.id for generation in linked_for_target],
                "current_generation_id": None if current is None else current.id,
                "dependency_kind": dependency_kind,
                "dependency_target_id": dependency_target_id,
            }
        )

    statuses = [item["status"] for item in target_results]
    successful = {"already_selected", "succeeded", "existing_result"}
    terminal = successful | {"failed", "cancelled", "target_missing", "invalid_result"}
    is_terminal = bool(statuses) and all(status in terminal for status in statuses)
    all_succeeded = bool(statuses) and all(status in successful for status in statuses)
    if is_terminal:
        phase = "completed" if all_succeeded else "completed_with_issues"
    elif "submission_uncertain" in statuses:
        phase = "needs_attention"
    elif any(status in {item.value for item in _ACTIVE_PHASES} for status in statuses):
        phase = "awaiting_generations"
    elif "unsubmitted" in statuses:
        phase = "awaiting_explicit_continue"
    else:
        phase = "blocked_on_dependency"

    executions = _batch_executions(document, records)
    return {
        "batch_id": batch_id,
        "batch_kind": "keyframe",
        "source_revision": first_data.get("source_revision", records[0][0].expected_revision),
        "observation_revision": document.revision,
        "root_execution_run_id": root_run_id,
        "latest_execution_run_id": executions[-1]["execution_run_id"],
        "target_ids": list(target_ids),
        "phase": phase,
        "is_terminal": is_terminal,
        "all_succeeded": all_succeeded,
        "executions": executions,
        "targets": target_results,
    }


_LOCATION_ITEM_KINDS = {
    ReferenceGenerationKind.LOCATION_IMAGE,
    ReferenceGenerationKind.PANORAMA_CAPTURE,
}
# 地点聚合状态的优先级：数值越小越优先代表该地点的当前状态。
_LOCATION_AGGREGATE_PRIORITY = (
    "submission_uncertain",
    "in_progress",
    "failed",
    "cancelled",
    "blocked",
    "awaiting_selection",
    "ready",
    "already_selected",
)


def _location_set_observation(document, batch_id: str) -> dict[str, object]:
    records = _batch_records(document, batch_id, LOCATION_SET_OPERATIONS)
    if not records:
        raise ValueError("批次不存在。")
    first_data = records[0][1]
    target_ids = _ids(first_data.get("target_ids"), "batch targets")
    root_run_id = first_data.get("root_execution_run_id", first_data.get("execution_run_id"))
    linked = _linked_generation_ids(document, records)

    items = location_set_items(document, target_ids)
    by_location: dict[str, list] = {location_id: [] for location_id in target_ids}
    for item in items:
        by_location[item.location_id].append(item)

    def detail(item):
        generations = [
            generation
            for generation in document.generations
            if generation.target_id == item.target_id
            and generation.kind in _LOCATION_ITEM_KINDS
            and (generation.id in linked or not generation.dismissed)
        ]
        current = next(
            (generation for generation in reversed(generations) if not generation.dismissed),
            None,
        )
        return {
            "target_id": item.target_id,
            "image_id": item.image_id,
            "label": item.label,
            "status": item.status,
            "reason": item.reason,
            "generation_ids": [
                generation.id for generation in generations if generation.id in linked
            ],
            "current_generation_id": None if current is None else current.id,
        }

    target_results = []
    for location_id in target_ids:
        location_items = by_location[location_id]
        status = min(
            (item.status for item in location_items),
            key=lambda value: _LOCATION_AGGREGATE_PRIORITY.index(value),
            default="already_selected",
        )
        target_results.append(
            {
                "target_id": location_id,
                "status": status,
                "images": [
                    detail(item) for item in location_items if item.status != "target_missing"
                ],
                "generation_ids": [
                    generation_id
                    for item in location_items
                    for generation_id in detail(item)["generation_ids"]
                ],
            }
        )

    statuses = [item.status for item in items]
    is_terminal = bool(statuses) and all(status in LOCATION_SET_TERMINAL for status in statuses)
    all_succeeded = bool(statuses) and all(status == "already_selected" for status in statuses)
    if is_terminal:
        phase = "completed" if all_succeeded else "completed_with_issues"
    elif "submission_uncertain" in statuses:
        phase = "needs_attention"
    elif "in_progress" in statuses:
        phase = "awaiting_generations"
    elif "ready" in statuses:
        phase = "awaiting_explicit_continue"
    elif "awaiting_selection" in statuses:
        phase = "awaiting_selection"
    else:
        phase = "blocked_on_dependency"

    executions = _batch_executions(document, records)
    return {
        "batch_id": batch_id,
        "batch_kind": "location",
        "source_revision": first_data.get("source_revision", records[0][0].expected_revision),
        "observation_revision": document.revision,
        "root_execution_run_id": root_run_id,
        "latest_execution_run_id": executions[-1]["execution_run_id"],
        "target_ids": list(target_ids),
        "phase": phase,
        "is_terminal": is_terminal,
        "all_succeeded": all_succeeded,
        "executions": executions,
        "targets": target_results,
    }
