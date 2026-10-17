"""在现有 Store 提交点附加原子回执；不另建持久层或领域 validator。"""

from __future__ import annotations

from dataclasses import asdict, replace

from core.application.caller import PROPOSAL_KINDS, authorize_command, request_identity
from core.application.requests import ApplicationRequest, canonical, current_request
from core.director_commands import DirectorCommandRegistry
from core.director_commands.models import (
    CommandExecution,
    CommandReceipt,
    InvalidArgumentsError,
    RepairOperation,
    RepairReceipt,
)

from .errors import RevisionConflictError
from .proposal_request_guard import owned_request
from .reads.batch_observation import current_batch_execution
from .reads.workflow_state import require_workflow_action


def prune_generation_references(records, deleted_generation_ids):
    """Remove hard-deleted Generation links while preserving request identity.

    The command receipt remains an audit record, but its current result payload
    must not advertise Generation IDs that were explicitly purged later.
    """

    deleted = set(deleted_generation_ids)
    if not deleted:
        return tuple(records)
    updated = []
    for record in records:
        generation_ids = tuple(item for item in record.generation_ids if item not in deleted)
        if generation_ids == record.generation_ids:
            updated.append(record)
            continue
        receipt_json = record.receipt_json
        if receipt_json is not None:
            import json

            receipt = json.loads(receipt_json)
            data = receipt.get("data") if isinstance(receipt, dict) else None
            if isinstance(data, dict) and isinstance(data.get("generation_ids"), list):
                receipt = {
                    **receipt,
                    "data": {
                        **data,
                        "generation_ids": [
                            item for item in data["generation_ids"] if item not in deleted
                        ],
                    },
                }
                receipt_json = canonical(receipt)
        updated.append(replace(record, generation_ids=generation_ids, receipt_json=receipt_json))
    return tuple(updated)


def request_for(caller, command, project_id):
    namespace, digest = request_identity(
        caller,
        project_id,
        command.idempotency_key,
        command.name,
        command.arguments,
        command.expected_revision,
    )
    return ApplicationRequest(
        namespace,
        caller.id,
        project_id,
        command.idempotency_key,
        digest,
        command.name,
        command.expected_revision,
        canonical(
            {
                "caller_id": caller.id,
                "role": caller.role,
                "project_ids": sorted(caller.project_ids),
                "capabilities": sorted(caller.capabilities),
                "grants": [asdict(g) for g in caller.grants],
            }
        ),
    )


def existing_request(document, request):
    previous = next(
        (item for item in document.application_requests if item.request_id == request.request_id),
        None,
    )
    if previous is not None and previous.request_digest != request.request_digest:
        raise RevisionConflictError("幂等键已用于不同请求，请使用新的键。")
    return previous


def execution_from(document, record, *, replay):
    import json

    if record.receipt_json is None:
        receipt = CommandReceipt(
            record.request_id[:32],
            "noop",
            record.expected_revision,
            document.revision,
            warnings=("提交结果待恢复；禁止自动重复提交。",),
        )
        return CommandExecution(
            document,
            receipt,
            data={"phase": record.phase, "generation_ids": list(record.generation_ids)},
            application_request_id=record.request_id,
            replay=replay,
        )
    value = json.loads(record.receipt_json)
    receipt = value["receipt"]
    for key in (
        "changed_ids",
        "invalidated",
        "preserved",
        "assumptions",
        "next_allowed_actions",
        "warnings",
    ):
        receipt[key] = tuple(receipt[key])
    repair = value["repair_receipt"]
    if repair is not None:
        repair = RepairReceipt(
            repair["gap_id"],
            repair["missing_command"],
            tuple(RepairOperation(**item) for item in repair["normalized_operations"]),
            tuple(RepairOperation(**item) for item in repair["reverse_operations"]),
        )
    return CommandExecution(
        document, CommandReceipt(**receipt), value["data"], repair, record.request_id, replay
    )


def execute_atomic_request(store, command, caller):
    document = store.read()
    request = request_for(caller, command, document.project_id)
    previous = existing_request(document, request)
    if previous is not None:
        return execution_from(document, previous, replay=True)
    if document.revision != command.expected_revision:
        raise RevisionConflictError(
            "项目已被更新，请重新读取。",
            expected_revision=command.expected_revision,
            current_revision=document.revision,
        )
    if store._application_capture is not None:
        raise RuntimeError("不允许嵌套应用事务。")
    require_workflow_action(document, command.name)
    captured = []
    store._application_capture = captured
    try:
        result = DirectorCommandRegistry(store).execute(command)
    finally:
        store._application_capture = None
    if len(captured) > 1:
        raise RuntimeError("同步命令必须只有一个 Store 提交。")
    changed = captured[0] if captured else document
    revision = document.revision + 1
    receipt = replace(result.receipt, new_revision=revision)
    record = replace(
        request,
        phase="committed",
        result_revision=revision,
        receipt_json=canonical(
            {
                "receipt": asdict(receipt),
                "data": result.data,
                "repair_receipt": None
                if result.repair_receipt is None
                else asdict(result.repair_receipt),
            }
        ),
    )
    changed = replace(
        changed, revision=revision, application_requests=(*changed.application_requests, record)
    )
    store._atomic_write(changed)
    return execution_from(changed, record, replay=False)


def attach_submission_request(store, document):
    import json

    request = current_request.get()
    if request is None or request.project_id != document.project_id:
        return document
    previous_doc = store.read()
    previous = existing_request(previous_doc, request)
    batch = request.operation in {
        "keyframe.generate_batch",
        "keyframe.continue_batch",
        "location.generate_set",
    }
    if previous is not None and previous.phase == "committed" and not batch:
        return document
    old_ids = {item.id for item in previous_doc.generations}
    ids = tuple(
        dict.fromkeys(
            (
                *(previous.generation_ids if previous else ()),
                *(item.id for item in document.generations if item.id not in old_ids),
            )
        )
    )
    generations = [item for item in document.generations if item.id in ids]
    phase = "pending"
    if generations and all(item.external_id is not None for item in generations):
        phase = "committed"
    elif any(item.phase.value in {"submission_uncertain", "failed"} for item in generations):
        phase = "uncertain"
    record = replace(
        request, generation_ids=ids, phase="pending" if phase == "committed" else phase
    )
    if phase == "committed":
        receipt = CommandReceipt(
            request.request_id[:32],
            "succeeded",
            request.expected_revision,
            document.revision,
            changed_ids=ids,
        )
        record = replace(
            record,
            phase="committed",
            result_revision=document.revision,
            receipt_json=canonical(
                {
                    "receipt": asdict(receipt),
                    "data": {"phase": phase, "generation_ids": list(ids)},
                    "repair_receipt": None,
                }
            ),
        )
    if batch:
        batch_context = current_batch_execution.get()
        previous_data = (
            json.loads(previous.receipt_json)["data"] if previous and previous.receipt_json else {}
        )
        batch_data = (
            batch_context.data()
            if batch_context is not None
            else {
                key: previous_data.get(key)
                for key in (
                    "batch_id",
                    "execution_run_id",
                    "batch_run_id",
                    "root_execution_run_id",
                    "previous_execution_run_id",
                    "target_ids",
                    "source_revision",
                )
            }
        )
        record = replace(
            record,
            phase="uncertain" if phase == "uncertain" else "pending",
            result_revision=document.revision,
            receipt_json=canonical(
                {
                    "receipt": asdict(
                        CommandReceipt(
                            request.request_id[:32],
                            "noop",
                            request.expected_revision,
                            document.revision,
                        )
                    ),
                    "data": {
                        **batch_data,
                        "generation_ids": list(ids),
                        "phase": "pending",
                    },
                    "repair_receipt": None,
                }
            ),
        )
    records = tuple(
        item for item in document.application_requests if item.request_id != record.request_id
    )
    return replace(document, application_requests=(*records, record))


def _look_sheet_arguments(arguments):
    """造型设定图只接受造型 ID 与显式身份参考；版式、比例与提示词由 Core 编译。"""
    assets = arguments["identity_asset_ids"]
    if (
        not isinstance(arguments["look_id"], str)
        or not isinstance(assets, list)
        or not all(isinstance(item, str) for item in assets)
    ):
        raise InvalidArgumentsError("造型设定图生成参数不合法。")
    return {"look_id": arguments["look_id"], "identity_asset_ids": tuple(assets)}


async def execute_application_command(service, caller, command):
    project_id = service._store.read().project_id
    authorize_command(caller, project_id, asdict(command))
    if command.name == "generation.wait":
        # wait 是当前 Provider 观察，不是应被幂等键冻结的写回执，也不校验 revision：
        # Generation 回调本身会推进 revision。真实 phase/Asset 变化仍由
        # GenerationObserver 经同一 Store 原子持久化。
        async with service._application_lock:
            require_workflow_action(service._store.read(), command.name)
            return await service.execute_generation_command(command)
    if command.name in {
        f"{kind}.{action}_proposal"
        for kind in PROPOSAL_KINDS
        for action in ("submit", "reject", "cancel")
    }:
        owned_request(
            service._store.read(), command.arguments.get("request_id"), command.name.split(".")[0]
        )
    generation_methods = {
        "keyframe.generate": (service.generate_keyframe, {"keyframe_id"}),
        "video.generate": (service._media.generate_segment_video, {"segment_id"}),
        "location.generate_master": (service.generate_location_master, {"location_id"}),
        "location.generate_view": (service.generate_location_view, {"view_id"}),
        "video.upscale": (service._media.upscale_segment_video, {"segment_id"}),
        "narration.generate": (service.generate_narration, {"cue_id", "language"}),
        "reference.generate_look_sheet": (
            service.generate_look_sheet,
            {"look_id", "identity_asset_ids"},
        ),
    }
    if (
        command.name not in generation_methods
        and not command.name.startswith("generation.")
        and command.name
        not in {
            "keyframe.generate_batch",
            "keyframe.continue_batch",
            "location.generate_set",
            "animatic.generate_scene",
            "final.assemble_scene",
            "final.assemble",
        }
    ):
        async with service._lock:
            return execute_atomic_request(service._store, command, caller)
    async with service._application_lock:
        document = service._store.read()
        request = request_for(caller, command, project_id)
        previous = existing_request(document, request)
        if previous is not None:
            if previous.phase == "pending":
                # 被中断的请求只恢复观察，不重复提交。提交窗口事实由 Generation 保留。
                previous = replace(previous, phase="uncertain")
                document = replace(
                    document,
                    revision=document.revision + 1,
                    application_requests=tuple(
                        previous if r.request_id == previous.request_id else r
                        for r in document.application_requests
                    ),
                )
                service._store._atomic_write(document)
            return execution_from(document, previous, replay=True)
        if document.revision != command.expected_revision:
            raise RevisionConflictError(
                "项目已被更新，请重新读取。",
                expected_revision=command.expected_revision,
                current_revision=document.revision,
            )
        require_workflow_action(document, command.name)
        context = current_request.set(request)
        try:
            if command.name in generation_methods:
                method, fields = generation_methods[command.name]
                if set(command.arguments) != fields:
                    raise InvalidArgumentsError("生成命令只接受明确目标 ID。")
                if command.name == "reference.generate_look_sheet":
                    arguments = _look_sheet_arguments(command.arguments)
                elif any(not isinstance(v, str) for v in command.arguments.values()):
                    raise InvalidArgumentsError("生成命令只接受明确目标 ID。")
                else:
                    arguments = command.arguments
                await method(**arguments, expected_revision=command.expected_revision)
                result = None
            else:
                result = await service._execute_internal_director_command(command)
        finally:
            current_request.reset(context)
        document = service._store.read()
        record = existing_request(document, request)
        if (
            record is None
            or (record.phase == "pending" and not record.generation_ids)
            or command.name
            in {"keyframe.generate_batch", "keyframe.continue_batch", "location.generate_set"}
        ):
            # 无新 Generation 的 cancel/dismiss 用例保存稳定返回；wait 已走动态观察分支。
            revision = document.revision + 1
            receipt = (
                replace(result.receipt, new_revision=revision)
                if result is not None
                else CommandReceipt(
                    request.request_id[:32], "noop", command.expected_revision, revision
                )
            )
            record = replace(
                request,
                generation_ids=() if record is None else record.generation_ids,
                phase="uncertain" if record and record.phase == "uncertain" else "committed",
                result_revision=revision,
                receipt_json=canonical(
                    {
                        "receipt": asdict(receipt),
                        "data": None if result is None else result.data,
                        "repair_receipt": None,
                    }
                ),
            )
            document = replace(
                document,
                revision=revision,
                application_requests=(
                    *(
                        r
                        for r in document.application_requests
                        if r.request_id != record.request_id
                    ),
                    record,
                ),
            )
            service._store._atomic_write(document)
        return execution_from(document, record, replay=False)
