from __future__ import annotations

from .keyframe_requests import (
    _find_keyframe,
    _keyframe_existing_result,
    _keyframe_generation_inputs,
    _keyframe_label,
)
from .manual_commands import (
    keyframe_edit_command,
)
from .models import (
    DirectorRunCursor,
    DirectorRunKind,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from .production_context import (
    _TERMINAL_PHASES,
)


async def execute_keyframe_wave(
    *,
    store,
    registry,
    production,
    document,
    target_ids,
    record_reply,
    recovery=False,
    regenerate=False,
):
    """在生产对话持有写锁期间准备提示词，并记录真实提交结果。"""
    outcomes: list[str] = []
    try:
        if not target_ids:
            raise ValueError("生成 Keyframe 必须明确指定目标。")
        document = store.scope_keyframe_generation(
            tuple(dict.fromkeys(target_ids)), expected_revision=document.revision
        )
        prepared = []
        # 依赖未满足、本轮留作等待项的帧及其等待原因。
        deferred: list[tuple[str, str]] = []
        for target_id in dict.fromkeys(target_ids):
            keyframe = _find_keyframe(document, target_id)
            if any(
                item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                and item.target_id == target_id
                and item.phase not in _TERMINAL_PHASES
                for item in document.generations
            ):
                outcomes.append(
                    f"{_keyframe_label(document, target_id)} 已有进行中的任务，本轮未重复提交。"
                )
                continue
            if any(
                item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                and item.target_id == target_id
                and item.phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN
                for item in document.generations
            ):
                outcomes.append(
                    f"{_keyframe_label(document, target_id)} 此前提交状态不确定，"
                    "需要先核查原任务，本轮未重复提交。"
                )
                continue
            existing = _keyframe_existing_result(document, target_id)
            if existing is not None and not regenerate:
                outcomes.append(
                    f"{_keyframe_label(document, target_id)} {existing}，本轮跳过；"
                    "需要新增候选时请明确要求再生成一版。"
                )
                continue
            if not regenerate and any(
                item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
                and item.target_id == target_id
                and not item.dismissed
                and item.phase
                in {
                    ReferenceGenerationPhase.FAILED,
                    ReferenceGenerationPhase.CANCELLED,
                }
                for item in document.generations
            ):
                outcomes.append(
                    f"{_keyframe_label(document, target_id)} 此前任务失败或已取消，"
                    "本轮未自动重试；请明确重试对应 Generation。"
                )
                continue
            inputs = _keyframe_generation_inputs(document, target_id)
            if inputs is None:
                assert keyframe.predecessor_keyframe_id is not None
                deferred.append(
                    (
                        target_id,
                        f"等待 {_keyframe_label(document, keyframe.predecessor_keyframe_id)}"
                        " 的候选完成",
                    )
                )
                continue
            if not keyframe.prompt_text.strip():
                raise ValueError("请先通过外部 Agent 或手工保存关键帧提示词。")
            prepared.append((keyframe, inputs))
        active = document.active_director_run
        if active is None:
            raise RuntimeError("关键帧生成缺少持久化批次。")
        pending_ids = [item.id for item, _ in prepared] + [item for item, _ in deferred]
        updated = store.set_director_run_cursor(
            run_id=active.id,
            cursor=DirectorRunCursor(active.cursor.step, tuple(pending_ids), ()),
            expected_revision=document.revision,
        )
        submitted_labels: list[str] = []
        for keyframe, inputs in prepared:
            if keyframe.prompt_text != _find_keyframe(updated, keyframe.id).prompt_text:
                updated = registry.execute(
                    keyframe_edit_command(
                        updated,
                        keyframe,
                        expected_revision=updated.revision,
                    )
                ).document
            updated = await production._submit_keyframe_generation(updated, keyframe.id, inputs)
            generation = updated.generations[-1]
            pending_ids.remove(keyframe.id)
            current_run = updated.active_director_run
            assert current_run is not None
            updated = store.set_director_run_cursor(
                run_id=current_run.id,
                cursor=DirectorRunCursor(current_run.cursor.step + 1, tuple(pending_ids), ()),
                expected_revision=updated.revision,
            )
            submitted_labels.append(_keyframe_label(updated, keyframe.id))
            outcomes.append(f"{_keyframe_label(updated, keyframe.id)}：{generation.message}")
        if submitted_labels:
            outcomes.insert(
                0,
                f"已先提交 {len(submitted_labels)} 个当前可以直接生成的关键帧："
                + "、".join(submitted_labels)
                + "。",
            )
        if deferred:
            waiting_lines = [
                f"- {_keyframe_label(updated, target_id)}：{waiting}"
                for target_id, waiting in deferred
            ]
            next_step = (
                "本次批次范围已保存。前置候选或角色造型图等依赖就绪后，"
                "请明确说“继续生成关键帧”；"
                "Core 只检查该批次中尚未完成且依赖已满足的帧，不会重复生成已有结果。"
            )
            outcomes.append(
                f"另有 {len(deferred)} 个关键帧依赖未满足，暂未提交：\n"
                + "\n".join(waiting_lines)
                + "\n\n"
                + next_step
            )
        if not outcomes:
            outcomes.append("本轮没有需要提交的新关键帧任务。")
        record_reply("\n\n".join(outcomes), recovery=recovery)
        return store.finish_production_instruction()
    except Exception as exc:
        current = store.read()
        if (
            current.active_director_run is not None
            and current.active_director_run.kind is DirectorRunKind.DIRECTOR
        ):
            current = store.finish_production_instruction()
        outcomes.append(f"关键帧生成未完成：{exc}")
        provider_failure = isinstance(exc, RuntimeError)
        record_reply(
            "\n\n".join(outcomes),
            recovery=recovery,
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
