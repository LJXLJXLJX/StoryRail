"""外部 proposal 请求的纯读观察（proposal_observation）。

从 proposal_requests.py 下沉：只从原 request 与当前 run 派生观察语义，
不持久化第二状态机；供 reads 包与 proposal 生命周期模块级复用，
避免 L5 生命周期模块与 reads 包互相 import 成环。
"""

from __future__ import annotations

import json


def proposal_observation(document, run, *, prefix=None, request_data=None):
    """从原 request 与当前 run 派生观察语义；不持久化第二状态机。"""
    if prefix is None or request_data is None:
        match = None
        for record in document.application_requests:
            if not record.operation.endswith(".request_proposal") or record.receipt_json is None:
                continue
            data = json.loads(record.receipt_json).get("data")
            if isinstance(data, dict) and data.get("request_id") == run.id:
                match = (record.operation.split(".")[0], data)
                break
        if match is None:
            return None
        prefix, request_data = match
    source_revision = request_data.get("source_revision")
    request_arguments = request_data.get("request_arguments")
    request_arguments = request_arguments if isinstance(request_arguments, dict) else {}
    stale = run.status.value == "running" and source_revision != document.revision
    outcome = None
    for record in reversed(document.application_requests):
        if record.receipt_json is None or record.operation not in {
            f"{prefix}.submit_proposal",
            f"{prefix}.cancel_proposal",
            f"{prefix}.reject_proposal",
        }:
            continue
        data = json.loads(record.receipt_json).get("data")
        if isinstance(data, dict) and data.get("request_id") == run.id:
            outcome = data.get("outcome")
            break
    phase = {
        "completed": "completed",
        "cancelled": "rejected" if outcome == "reject_proposal" else "cancelled",
        "failed": "failed",
    }.get(run.status.value, "workset_stale" if stale else "awaiting_agent_submission")
    tool = f"{prefix}_proposal"
    target_ids = request_arguments.get("target_ids", [])
    actions = [
        {
            "action": f"{prefix}.get_proposal",
            "tool": tool,
            "tool_action": "get",
            "request_id": run.id,
            "target_ids": target_ids,
            "human_only": False,
            "requires_explicit_user_request": False,
        }
    ]
    if phase == "awaiting_agent_submission":
        actions = [
            {
                "action": f"{prefix}.submit_proposal",
                "tool": tool,
                "tool_action": "submit",
                "request_id": run.id,
                "target_ids": target_ids,
                "human_only": False,
                "requires_explicit_user_request": False,
            },
            *actions,
            {
                "action": f"{prefix}.cancel_proposal",
                "tool": tool,
                "tool_action": "cancel",
                "request_id": run.id,
                "target_ids": target_ids,
                "human_only": False,
                "requires_explicit_user_request": True,
            },
        ]
    elif phase == "workset_stale":
        actions.append(
            {
                "action": f"{prefix}.cancel_proposal",
                "tool": tool,
                "tool_action": "cancel",
                "request_id": run.id,
                "target_ids": target_ids,
                "human_only": False,
                "requires_explicit_user_request": True,
            }
        )
    return {
        "phase": phase,
        "execution_responsibility": "external_agent"
        if phase == "awaiting_agent_submission"
        else None,
        "request_id": run.id,
        "proposal_kind": prefix,
        "source_revision": source_revision,
        "observation_revision": document.revision,
        "scope": request_data.get("scope", request_arguments.get("scope")),
        "target_ids": target_ids,
        "actions": actions,
        "instruction": (
            "当前外部 Agent 应基于原始不可变工作集编写 proposal，并显式调用 submit；"
            "Core 没有后台模型任务可轮询。"
            if phase == "awaiting_agent_submission"
            else "原工作集已过期；先取消原请求，再按最新 revision 显式重新申请。"
            if phase == "workset_stale"
            else "proposal 请求已结束；get 仍可读取原工作集与当前结果。"
        ),
    }
