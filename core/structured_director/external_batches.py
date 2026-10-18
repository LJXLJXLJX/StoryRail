"""精确授权的外部批次；沿用 DirectorRun scope/cursor 和共用执行波次。

Keyframe 批次（keyframe.generate_batch / continue_batch）与地点成套批次
（location.generate_set，target_ids 或 run_id 二选一）共用同一段
run/回执/观察骨架；范围解析、波次执行与状态分类各自实现。
"""

from __future__ import annotations

from core.application.requests import current_request
from core.director_commands.models import (
    CommandExecution,
    CommandReceipt,
    director_command_id,
)

from .keyframe_batches import execute_keyframe_wave
from .keyframe_requests import (
    _find_keyframe,
    _resolve_keyframe_generation_targets,
)
from .location_batches import execute_location_wave
from .location_requests import find_location
from .reads.batch_observation import (
    KEYFRAME_OPERATIONS,
    LOCATION_SET_OPERATIONS,
    BatchExecutionContext,
    _batch_records,
    _owned_batch,
    batch_observation,
    current_batch_execution,
)
from .reads.read_tools import _exact_arguments, _id, _ids

# 地点成套批次里“本轮条件不满足、未来轮次可提交”的聚合状态。
_LOCATION_DEFERRED_STATUSES = {
    "ready",
    "awaiting_master",
    "awaiting_calibration",
    "awaiting_reference_view",
    "blocked",
}


async def execute(service, command):
    async with service._lock:
        document = service._store.read()
        if document.active_director_run is not None:
            raise ValueError("原 run 尚未结束；先读取状态并显式取消中断的 run，再继续同一批次。")
        location_batch = command.name in LOCATION_SET_OPERATIONS
        operations = LOCATION_SET_OPERATIONS if location_batch else KEYFRAME_OPERATIONS
        scope_prefix = "location" if location_batch else "keyframe"
        previous_run_id = None
        if command.name == "keyframe.generate_batch" or (
            location_batch and set(command.arguments) == {"target_ids"}
        ):
            _exact_arguments(command.arguments, required={"target_ids"})
            targets = _ids(command.arguments["target_ids"], "target_ids")
            batch_id = None
            root_run_id = None
            if location_batch:
                # 地点范围在开始时固定且必须现存；继续时被删除的地点只报告“已不存在”。
                for location_id in targets:
                    find_location(document, location_id)
        else:
            _exact_arguments(command.arguments, required={"run_id"})
            identity = _id(command.arguments["run_id"], "run_id")
            batch_id, root_run_id, previous_run_id, targets = _owned_batch(
                document, identity, operations, scope_prefix
            )
        if not location_batch:
            # 同一原始范围解析为当前激活帧，不允许空范围兜底；开始时即固定。
            targets = _resolve_keyframe_generation_targets(document, targets)
            if any(not _find_keyframe(document, target).prompt_text.strip() for target in targets):
                raise ValueError(
                    "批次中有空提示词；必须显式编写后重新提交，不能调用内置 Agent 补写。"
                )
        document, _ = service._store.begin_production_instruction(
            "执行明确授权的地点成套生成批次" if location_batch else "执行明确授权的 Keyframe 批次",
            expected_revision=command.expected_revision,
        )
        execution_run_id = document.active_director_run.id
        request = current_request.get()
        if batch_id is None:
            batch_id = request.request_id[:32] if request is not None else execution_run_id
        if root_run_id is None:
            root_run_id = execution_run_id
        context = BatchExecutionContext(
            batch_id,
            execution_run_id,
            root_run_id,
            previous_run_id,
            targets,
            command.expected_revision,
        )
        messages = []
        issues = []

        def record_reply(message, **metadata):
            messages.append(message)
            failure = metadata.get("failure")
            if isinstance(failure, dict):
                issues.append(failure)

        token = current_batch_execution.set(context)
        try:
            if location_batch:
                updated = await execute_location_wave(
                    store=service._store,
                    media=service._media,
                    document=document,
                    location_ids=targets,
                    record_reply=record_reply,
                )
            else:
                updated = await execute_keyframe_wave(
                    store=service._store,
                    registry=service._command_registry,
                    production=service,
                    document=document,
                    target_ids=targets,
                    record_reply=record_reply,
                )
        finally:
            current_batch_execution.reset(token)
        observation = batch_observation(updated, batch_id)
        records = _batch_records(updated, batch_id, operations)
        current_record = next(
            (
                record
                for record, _ in reversed(records)
                if record.request_id == (request.request_id if request is not None else None)
            ),
            None,
        )
        current_generation_ids = () if current_record is None else current_record.generation_ids
        current_generation_targets = {
            generation.target_id
            for generation in updated.generations
            if generation.id in current_generation_ids
        }
        deferred_statuses = (
            _LOCATION_DEFERRED_STATUSES
            if location_batch
            else {"dependency_blocked", "input_blocked", "unsubmitted"}
        )
        deferred_target_ids = [
            item["target_id"]
            for item in observation["targets"]
            if item["status"] in deferred_statuses
        ]
        if location_batch:
            # 地点批次的目标是一个地点，本轮可能只提交其中一部分独立图片。
            submitted_target_ids = [
                item["target_id"]
                for item in observation["targets"]
                if any(
                    generation.id in current_generation_ids
                    for generation in updated.generations
                    if generation.target_id
                    in {
                        item["target_id"],
                        *(image["target_id"] for image in item["images"]),
                    }
                )
            ]
        else:
            submitted_target_ids = [
                target_id for target_id in targets if target_id in current_generation_targets
            ]
        skipped_target_ids = [
            target_id
            for target_id in targets
            if target_id not in submitted_target_ids and target_id not in deferred_target_ids
        ]
        execution_summary = {
            "submitted_target_ids": submitted_target_ids,
            "deferred_target_ids": deferred_target_ids,
            "skipped_target_ids": skipped_target_ids,
        }
        observation["executions"][-1].update(execution_summary)
        return CommandExecution(
            updated,
            CommandReceipt(
                director_command_id(command),
                "succeeded",
                command.expected_revision,
                updated.revision,
            ),
            {
                **context.data(),
                **execution_summary,
                "result_revision": updated.revision,
                "generation_ids": list(
                    dict.fromkeys(
                        generation_id
                        for record, _ in records
                        for generation_id in record.generation_ids
                    )
                ),
                "messages": messages,
                "issues": issues,
                "batch_observation": observation,
            },
        )
