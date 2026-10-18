"""地点成套生成批次（location.generate_set）的单轮执行。

范围在批次开始时固定为明确的 location_ids；每轮重新分类全部独立图片条目，
只提交本轮条件已满足的普通生成或全景取景。回调都不续提交，推进需要新的
显式 `location.generate_set`（携带原 batch_id 或 execution_run_id）。
提交本身复用单项入口共用的内部提交函数（`media_submission.image`），
不另写提交、seed 或 provider_snapshot 逻辑。
"""

from __future__ import annotations

from .location_requests import location_set_items
from .models import DirectorRunCursor, DirectorRunKind

_WAITING_SUMMARY = {
    "in_progress": "进行中",
    "submission_uncertain": "提交状态不确定",
    "awaiting_selection": "等待选择",
    "failed": "此前任务失败",
    "cancelled": "此前任务已取消",
    "blocked": "被阻止",
    "target_missing": "已不存在",
}


async def execute_location_wave(
    *,
    store,
    media,
    document,
    location_ids,
    record_reply,
):
    """在生产对话持有写锁期间分类本轮可提交项，并记录真实提交结果。"""
    outcomes: list[str] = []
    try:
        if not location_ids:
            raise ValueError("地点成套生成必须明确指定地点。")
        document = store.scope_location_generation(
            tuple(dict.fromkeys(location_ids)), expected_revision=document.revision
        )
        items = location_set_items(document, location_ids)
        ready = [item for item in items if item.status == "ready"]
        active = document.active_director_run
        if active is None:
            raise RuntimeError("地点成套生成缺少持久化批次。")
        pending_ids = [item.target_id for item in ready]
        updated = store.set_director_run_cursor(
            run_id=active.id,
            cursor=DirectorRunCursor(active.cursor.step, tuple(pending_ids), ()),
            expected_revision=document.revision,
        )
        submitted_labels: list[str] = []
        for item in ready:
            assert item.image_id is not None
            if item.step == "capture":
                updated = await media._submit_location_capture(updated, image_id=item.image_id)
            else:
                updated = await media._submit_location_image(updated, image_id=item.image_id)
            generation = updated.generations[-1]
            pending_ids.remove(item.target_id)
            current_run = updated.active_director_run
            assert current_run is not None
            updated = store.set_director_run_cursor(
                run_id=current_run.id,
                cursor=DirectorRunCursor(current_run.cursor.step + 1, tuple(pending_ids), ()),
                expected_revision=updated.revision,
            )
            submitted_labels.append(item.label)
            outcomes.append(f"{item.label}：{generation.message}")
        if submitted_labels:
            outcomes.insert(
                0,
                f"已先提交 {len(submitted_labels)} 个当前可以直接生成的地点任务："
                + "、".join(submitted_labels)
                + "。",
            )
        waiting = [item for item in items if item.status not in {"ready", "already_selected"}]
        if waiting:
            waiting_lines = [
                f"- {item.label or item.location_id}："
                + _WAITING_SUMMARY.get(item.status, item.status)
                + (f"（{item.reason}）" if item.reason else "")
                for item in waiting
            ]
            outcomes.append(
                f"另有 {len(waiting)} 项本轮未提交：\n"
                + "\n".join(waiting_lines)
                + "\n\n本次批次范围已保存。条件满足后需要新的显式继续"
                + "（location.generate_set 携带原 batch_id 或 execution_run_id）；"
                + "Core 只提交该批次中条件已满足的项，不重复生成已有候选，回调不自动推进下一轮。"
            )
        if not outcomes:
            outcomes.append("本轮没有需要提交的地点生成任务。")
        record_reply("\n\n".join(outcomes))
        return store.finish_production_instruction()
    except Exception as exc:
        current = store.read()
        if (
            current.active_director_run is not None
            and current.active_director_run.kind is DirectorRunKind.DIRECTOR
        ):
            current = store.finish_production_instruction()
        outcomes.append(f"地点成套生成未完成：{exc}")
        provider_failure = isinstance(exc, RuntimeError)
        record_reply(
            "\n\n".join(outcomes),
            failure={
                "code": "provider_unavailable" if provider_failure else "batch_step_rejected",
                "origin": "provider_boundary" if provider_failure else "core_domain",
                "state_changed": current.revision != document.revision,
                "retry_policy": (
                    "restore_dependency_then_explicit_batch_continue"
                    if provider_failure
                    else "change_business_state_or_request"
                ),
                "automatic_retry_allowed": False,
            },
        )
        return current
