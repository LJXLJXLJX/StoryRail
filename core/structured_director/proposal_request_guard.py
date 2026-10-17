"""proposal 请求的 caller 所有权与授权校验（owned_request）。

从 proposal_requests.py 下沉：读取 document.application_requests 并校验当前 caller，
不持有请求生命周期状态；proposal_requests 与 script_proposals/application_requests
模块级复用，避免 handler 与生命周期模块互相 import 成环。
"""

from __future__ import annotations

import json

from core.application.caller import AccessDenied, authorize_command, current_caller


def owned_request(document, request_id, prefix="script"):
    caller = current_caller.get()
    for record in document.application_requests:
        if record.operation != f"{prefix}.request_proposal" or record.receipt_json is None:
            continue
        data = json.loads(record.receipt_json)["data"]
        if data["request_id"] != request_id:
            continue
        if caller is None or (caller.id != record.caller_id and caller.role != "human"):
            raise AccessDenied("scope_denied", "该 proposal 不属于当前 caller。")
        authorize_command(
            caller,
            document.project_id,
            {
                "name": f"{prefix}.request_proposal",
                "arguments": data.get(
                    "request_arguments", {"raw_user_instruction": data["raw_user_instruction"]}
                ),
                "expected_revision": record.expected_revision,
            },
        )
        return data
    raise ValueError("proposal request ID 不存在。")
