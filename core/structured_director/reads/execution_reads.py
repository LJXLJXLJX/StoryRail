"""外部恢复与人类审核衔接的最小只读状态。"""

import base64
import json

from core.application.caller import current_caller
from core.director_proposals.professional_contracts import contract_hashes

from ..generation_lifecycle import _generation_recovery
from .batch_observation import batch_observation
from .common import _asset_summary, _exact_arguments, _id
from .proposal_observation import proposal_observation
from .snapshot_view import human_allowed_actions
from .workflow_state import workflow_state


def handoff_read(document, arguments):
    _exact_arguments(arguments, optional={"cursor", "limit"})
    return {
        "project_id": document.project_id,
        "revision": document.revision,
        "workflow": workflow_state(document),
        "contract_hashes": contract_hashes(),
        "web_path": f"/?project={document.project_id}",
        "allowed_actions": list(human_allowed_actions(document)),
        "allowed_actions_semantics": "human_ui_capabilities_not_next_steps",
        "human_only": [
            "reference.confirm_review",
            "script.confirm",
            "candidate_selection",
            "final.approve",
            "final.reopen_production",
        ],
        "instruction": (
            "下一步只按 workflow.required_next_actions 解析；"
            "workflow.recommended_next_actions 是不阻塞主流程的可选建议，"
            "先向用户提议，收到明确指令再执行；"
            "workflow.active_task 只表示主流程任务，并行 run/Generation 读取 task_discovery；"
            "not_current_stage 只表示主流程相关性，局部可写性读取 mutation_blocked；"
            "human_only 动作请用户在导演台执行，外部 Agent 不接收人类凭据。"
        ),
        "task_discovery": _task_discovery(document, arguments),
    }


def _task_discovery(document, arguments):
    """只投影已有 run/request/Generation；不创建恢复账本或读取其它 caller 正文。"""
    caller = current_caller.get()
    own_request_ids = {
        record.request_id
        for record in document.application_requests
        if caller is not None and record.caller_id == caller.id
    }
    receipt_data = {
        record.request_id: _receipt_data(record) for record in document.application_requests
    }
    run_record = {}
    generation_record = {}
    generation_run = {}
    run_batch = {}
    generation_batch = {}
    for record in document.application_requests:
        data = receipt_data[record.request_id]
        linked_run_id = _linked_run_id(data)
        if linked_run_id is not None:
            run_record.setdefault(linked_run_id, record)
        batch_id = data.get("batch_id") if isinstance(data, dict) else None
        if isinstance(batch_id, str):
            if linked_run_id is not None:
                run_batch.setdefault(linked_run_id, batch_id)
            for generation_id in record.generation_ids:
                generation_batch.setdefault(generation_id, batch_id)
        for generation_id in record.generation_ids:
            generation_record.setdefault(generation_id, record)
            if linked_run_id is not None:
                generation_run.setdefault(generation_id, linked_run_id)

    batch_observations = {
        batch_id: batch_observation(document, batch_id)
        for batch_id in set(run_batch.values()) | set(generation_batch.values())
    }

    generations = {item.id: item for item in document.generations}
    generation_run.update(
        {
            generation_id: run.id
            for run in document.director_runs
            for generation_id in run.cursor.waiting_generation_ids
        }
    )
    tasks = []
    for run in reversed(document.director_runs):
        record = run_record.get(run.id)
        own_record = record is not None and record.request_id in own_request_ids
        target_ids = list(
            dict.fromkeys(
                (
                    *run.cursor.pending_target_ids,
                    *(
                        generations[generation_id].target_id
                        for generation_id in run.cursor.waiting_generation_ids
                        if generation_id in generations
                    ),
                )
            )
        )
        tasks.append(
            {
                "task_type": "director_run",
                "id": run.id,
                "kind": run.kind.value,
                "status": run.status.value,
                "target_ids": target_ids,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
                "run_id": run.id,
                "application_request_id": record.request_id if own_record else None,
                "request_key": record.idempotency_key if own_record else None,
                "request_association": _request_association(record, own_record),
                "generation_ids": list(run.cursor.waiting_generation_ids),
                "batch_id": run_batch.get(run.id),
            }
        )
    for generation in reversed(document.generations):
        record = generation_record.get(generation.id)
        own_record = record is not None and record.request_id in own_request_ids
        run_id = generation_run.get(generation.id)
        tasks.append(
            {
                "task_type": "generation",
                "id": generation.id,
                "kind": generation.kind.value,
                "status": generation.phase.value,
                "target_ids": [generation.target_id],
                "created_at": generation.created_at,
                "updated_at": generation.updated_at,
                "timestamp_status": _generation_timestamp_status(generation),
                "run_id": run_id,
                "run_association": (
                    "linked_director_run"
                    if run_id is not None
                    else "not_applicable_single_generation"
                    if record is not None
                    else "unavailable_legacy_origin"
                ),
                "application_request_id": record.request_id if own_record else None,
                "request_key": record.idempotency_key if own_record else None,
                "request_association": _request_association(record, own_record),
                "origin_operation": None if record is None else record.operation,
                "generation_ids": [generation.id],
                "batch_id": generation_batch.get(generation.id),
                "message": generation.message,
                "error_code": generation.error_code,
                "cancellation_requested": generation.cancellation_requested,
                "retry_of": generation.retry_of,
                "output_asset_id": generation.output_asset_id,
                "recovery": _generation_recovery(generation),
            }
        )

    active_statuses = {
        "running",
        "waiting_user",
        "waiting_jobs",
        "submitting",
        "submission_uncertain",
        "queued",
    }

    def is_active(item):
        observation = batch_observations.get(item.get("batch_id"))
        batch_active = (
            item["task_type"] == "director_run"
            and isinstance(observation, dict)
            and not observation["is_terminal"]
            and item["id"] == observation["latest_execution_run_id"]
        )
        return item["status"] in active_statuses or batch_active

    tasks.sort(key=lambda item: not is_active(item))
    offset = _discovery_offset(arguments.get("cursor"), document.revision)
    limit = arguments.get("limit", 30)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("handoff limit 必须是 1 到 100 的整数。")
    if offset > len(tasks):
        raise ValueError("handoff cursor 超出结果范围。")
    page = tasks[offset : offset + limit]
    next_offset = offset + len(page)
    page_batch_ids = tuple(
        dict.fromkeys(item["batch_id"] for item in page if isinstance(item.get("batch_id"), str))
    )
    return {
        "observation_revision": document.revision,
        "semantics": {
            "active": "all_project_active_runs_and_generations",
            "recent": "all_project_terminal_runs_and_generations",
            "request_association": "current_caller_application_requests_only",
            "request_redaction": "other_caller_links_are_marked_but_ids_and_keys_are_hidden",
            "generation_timestamps": "persisted_generation_lifecycle_not_director_run_time",
            "run_association": "null_run_id_can_be_not_applicable_or_legacy_unavailable",
            "workflow_relation": "parallel_activity_not_primary_workflow",
        },
        "active_count": sum(is_active(item) for item in tasks),
        "recent_count": sum(not is_active(item) for item in tasks),
        "active": [item for item in page if is_active(item)],
        "recent": [item for item in page if not is_active(item)],
        "batches": [
            {
                key: batch_observations[batch_id][key]
                for key in (
                    "batch_id",
                    "batch_kind",
                    "observation_revision",
                    "root_execution_run_id",
                    "latest_execution_run_id",
                    "phase",
                    "is_terminal",
                    "all_succeeded",
                )
            }
            | {"target_count": len(batch_observations[batch_id]["target_ids"])}
            for batch_id in page_batch_ids
        ],
        "next_cursor": (
            _discovery_cursor(document.revision, next_offset) if next_offset < len(tasks) else None
        ),
    }


def _request_association(record, own_record):
    if record is None:
        return "none"
    return "current_caller" if own_record else "other_caller_redacted"


def _generation_timestamp_status(generation):
    if generation.created_at is not None and generation.updated_at is not None:
        return "complete"
    if generation.updated_at is not None:
        return "legacy_created_at_missing"
    return "legacy_missing"


def _receipt_data(record):
    if record.receipt_json is None:
        return None
    value = json.loads(record.receipt_json)
    return value.get("data") if isinstance(value, dict) else None


def _linked_run_id(data):
    if not isinstance(data, dict):
        return None
    for key in ("execution_run_id", "batch_run_id", "request_id", "run_id"):
        value = data.get(key)
        if isinstance(value, str) and len(value) == 32:
            return value
    return None


def _discovery_cursor(revision, offset):
    payload = json.dumps(
        {"revision": revision, "offset": offset, "query": "handoff_tasks_v1"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _discovery_offset(cursor, revision):
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or len(cursor) > 200:
        raise ValueError("handoff cursor 不合法。")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("handoff cursor 不合法。") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"revision", "offset", "query"}
        or value["query"] != "handoff_tasks_v1"
        or value["revision"] != revision
        or isinstance(value["offset"], bool)
        or not isinstance(value["offset"], int)
        or value["offset"] < 0
    ):
        raise ValueError("handoff cursor 与当前查询 revision 不匹配。")
    return value["offset"]


def request_read(document, arguments):
    _exact_arguments(arguments, required={"request_key"})
    key = arguments["request_key"]
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise ValueError("request_key 不合法。")
    caller = current_caller.get()
    record = next(
        (
            r
            for r in document.application_requests
            if r.idempotency_key == key and caller and r.caller_id == caller.id
        ),
        None,
    )
    if record is None:
        raise ValueError("当前 caller 的应用请求不存在。")
    receipt = json.loads(record.receipt_json) if record.receipt_json else None
    result = None if receipt is None else receipt["data"]
    if record.operation.endswith(".request_proposal") and isinstance(result, dict):
        run = next(
            (item for item in document.director_runs if item.id == result.get("request_id")),
            None,
        )
        if run is not None:
            observation = proposal_observation(document, run)
            request_arguments = result.get("request_arguments")
            request_arguments = request_arguments if isinstance(request_arguments, dict) else {}
            proposal_kind = record.operation.removesuffix(".request_proposal")
            capability = "reference_library" if proposal_kind == "reference" else proposal_kind
            result = {
                key: result[key]
                for key in (
                    "request_id",
                    "source_revision",
                    "raw_user_instruction",
                    "request_arguments",
                )
                if key in result
            }
            result.update(
                {
                    "proposal_observation": observation,
                    "workset_recovery": {
                        "included": False,
                        "reason": "通用请求查询不内联大型专业工作集。",
                        "tool": f"{proposal_kind}_proposal",
                        "action": "get",
                        "request_id": run.id,
                        "latest_workset_tool": "read_professional_workset",
                        "capability": capability,
                        "scope": request_arguments.get("scope"),
                        "target_ids": request_arguments.get("target_ids", []),
                    },
                }
            )
    if record.operation in {"keyframe.generate_batch", "keyframe.continue_batch"} and isinstance(
        result, dict
    ):
        batch_id = result.get("batch_id")
        if isinstance(batch_id, str):
            result = {**result, "batch_observation": batch_observation(document, batch_id)}
    return {
        "project_id": document.project_id,
        "revision": document.revision,
        "request_id": record.request_id,
        "operation": record.operation,
        "phase": record.phase,
        "generation_ids": list(record.generation_ids),
        "result": result,
    }


def external_run(document):
    run = document.active_director_run
    if run is None:
        return False
    for record in document.application_requests:
        if record.receipt_json is None:
            continue
        data = json.loads(record.receipt_json).get("data")
        if isinstance(data, dict) and run.id in (data.get("request_id"), data.get("batch_run_id")):
            return True
    return False


def asset_manifest(document, arguments):
    _exact_arguments(arguments, required={"asset_id"})
    asset_id = _id(arguments["asset_id"], "asset_id")
    asset = next((a for a in document.assets if a.id == asset_id), None)
    if asset is None:
        raise ValueError("Asset 不属于当前项目。")
    return {
        **_asset_summary(asset),
        "sha256": asset.sha256,
        "project_id": document.project_id,
        "source_revision": document.revision,
    }
