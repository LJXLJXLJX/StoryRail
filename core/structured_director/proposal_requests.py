"""引用库/脚本/Keyframe/地点的外部请求生命周期；复用领域 run 和应用原子回执。"""

import json

from core.application.caller import PROPOSAL_KINDS, AccessDenied, current_caller
from core.director_commands.models import (
    CommandExecution,
    CommandReceipt,
    director_command_id,
)
from core.director_proposals.schema_gen import ProposalError

from . import location_proposals, reference_proposals, script_proposals
from .errors import InvalidArgumentsError, RevisionConflictError
from .planning_proposals import PlanningProposalHandler
from .proposal_request_guard import owned_request
from .reads.professional_worksets import speech_recipe
from .reads.proposal_observation import proposal_observation

OPERATIONS = {
    f"{kind}.{action}_proposal"
    for kind in PROPOSAL_KINDS
    for action in ("request", "get", "submit", "reject", "cancel")
}


def execute(store, command):
    if current_caller.get() is None:
        raise AccessDenied("caller_required", "外部 proposal 入口需要受信 caller。")
    document = store.read()
    if document.revision != command.expected_revision:
        raise RevisionConflictError("项目已变化，请重新读取。")
    args = command.arguments
    op = command.name
    prefix = op.split(".")[0]
    planning = prefix == "keyframe"
    handler = (
        PlanningProposalHandler()
        if planning
        else {
            "reference": reference_proposals,
            "script": script_proposals,
            "location": location_proposals,
        }[prefix]
    )
    required = {"raw_user_instruction"} if op == f"{prefix}.request_proposal" else {"request_id"}
    if planning and op == f"{prefix}.request_proposal":
        required = handler.request_fields()
    if op == f"{prefix}.submit_proposal":
        required.add("proposal")
    if op == f"{prefix}.reject_proposal":
        required.add("reason")
    if set(args) != required:
        raise InvalidArgumentsError("proposal 命令包含缺失或未声明字段。")
    if any(
        not isinstance(args[k], str) or not args[k].strip() or len(args[k]) > 20000
        for k in required & {"raw_user_instruction", "request_id", "reason"}
    ):
        raise InvalidArgumentsError("proposal 文本或 ID 不合法。")
    if op == f"{prefix}.request_proposal":
        if planning:
            try:
                updated, _ = handler.begin(
                    store,
                    expected_revision=document.revision,
                    **args,
                    recovery=False,
                )
                data = handler.workset(
                    updated,
                    args["raw_user_instruction"],
                    request_arguments=args,
                )
            except RevisionConflictError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise InvalidArgumentsError(str(exc)) from exc
        else:
            updated, _ = handler.begin(
                store,
                expected_revision=document.revision,
                **args,
                recovery=False,
            )
            data = handler.workset(
                updated,
                args["raw_user_instruction"],
            )
        if prefix == "script":
            data["core_facts"]["speech_recipe"] = speech_recipe(store.provider_recipe_views())
        data["request_arguments"] = args
        data["proposal_observation"] = proposal_observation(
            updated,
            updated.active_director_run,
            prefix=prefix,
            request_data=data,
        )
    else:
        data = owned_request(document, args["request_id"], prefix)
        run = next(item for item in document.director_runs if item.id == args["request_id"])
        if op == f"{prefix}.get_proposal":
            return CommandExecution(
                document,
                CommandReceipt(
                    director_command_id(command), "noop", document.revision, document.revision
                ),
                {
                    **data,
                    "status": run.status.value,
                    "proposal_observation": proposal_observation(
                        document, run, prefix=prefix, request_data=data
                    ),
                },
            )
        if op == f"{prefix}.submit_proposal":
            try:
                proposal = handler.parse_proposal(
                    json.dumps(args["proposal"], ensure_ascii=False, allow_nan=False)
                )
                updated = handler.submit(
                    store,
                    proposal,
                    request_id=run.id,
                    expected_revision=document.revision,
                    **({"request_data": data} if planning else {}),
                )
            except ProposalError as exc:
                raise InvalidArgumentsError(str(exc)) from exc
        else:
            updated = store.cancel_director_run(run_id=run.id, expected_revision=document.revision)
        # 拒绝原因作为原子回执保存；run 使用既有 CANCELLED 终态，不新增状态机。
        data = {
            "request_id": run.id,
            "outcome": op.split(".")[1],
            **({"reason": args["reason"]} if "reason" in args else {}),
        }
    return CommandExecution(
        updated,
        CommandReceipt(
            director_command_id(command),
            "succeeded",
            document.revision,
            updated.revision,
            decision_summary="已处理专业 proposal；后续审核仍需人类显式操作。",
        ),
        data,
    )
