"""O3 · 不确定提交 oracle。

ARRIVE   drama 旅程驱动到关键帧规划完成；在共享 image provider 实例上安装提交
         闸门（fail_submits=True 时 submit* 抛 ModelProviderError
         ("transport_error", ..., retryable=True)），经真实 HTTP 批量提交——
         提交传输失败使 Generation 持久化为 submission_uncertain
         （依据 core/structured_director/generation_lifecycle.py
         ``_submission_failure``：transport_error → SUBMISSION_UNCERTAIN，
         error_code="transport_error"）；随后 OracleHttpServer.restart()
         模拟进程死再重建，经 task_discovery 读取恢复分类，关闭闸门后经真实
         HTTP ``POST /generations/{id}/retry`` 显式重试，继续旅程到 Approval。
         注：观察期 transport_error 是另一语义（generation_observer 保留句柄、
         error_code="provider_unreachable"，不进入 submission_uncertain）；
         本场景驱动的是提交期不确定，与 error-contract.md 的
         submission_uncertain 行一致。
ORACLE   断言可达状态谓词（project.json、API snapshot 与错误响应体）：
         - 不确定提交被正确分类：task_discovery 的 recovery 为
           failure_origin="provider_submission"、
           retry_policy="inspect_then_explicit_generation_retry"、
           automatic_retry_allowed=False（generation_lifecycle
           ``_generation_recovery`` + error-contract.md「先检查后显式
           generation.retry，不自动重提」）；
         - 重启不重放已提交任务：provider 提交次数不增长，Generation 身份
           （id/phase/error_code）原样保留；
         - 显式重试创建新 Generation 并保留 retry_of 链，原不确定
           Generation 作为历史保留（不作废、不删除）；
         - 领域不变量拒绝（重试 succeeded Generation）的错误响应逐字段符合
           error-contract.md：409 business_rule_rejected / core_domain /
           state_changed=false / retry_policy=change_business_state_or_request /
           automatic_retry_allowed=false；
         - 终态与 O1 等价：status approved、final_approval 非空、
           workspace_layers 全解锁。
覆盖领域规则：提交结果未知不自动重试、重试创建新 Generation 并保留 retry_of、
历史 Generation 保留、错误契约字段、中断恢复不重放。
BUDGET   单场景 ≤20s（真实 loopback HTTP + 合成 Provider）。
"""

from __future__ import annotations

import pytest

from core.model_providers.boundary import ModelProviderError

_UNCERTAIN_TERMINAL = {"succeeded", "submission_uncertain", "failed", "cancelled"}


class SubmitGate:
    """在共享 provider 实例上安装提交闸门，让提交期 transport_error 可开关。

    直接包装实例方法（实例属性遮蔽类方法），provider 对象在 restart()
    前后共享，闸门状态因此对重建后的 service 同样生效。
    """

    def __init__(self, provider) -> None:
        self.provider = provider
        self.fail_submits = False
        self.attempts = 0
        for name in ("submit", "submit_generate", "submit_edit"):
            original = getattr(provider, name)
            setattr(provider, name, self._guarded(original))

    def _guarded(self, original):
        def guarded(request):
            self.attempts += 1
            if self.fail_submits:
                raise ModelProviderError("transport_error", "模型节点离线", retryable=True)
            return original(request)

        return guarded


def _generation_task(handoff: dict, generation_id: str) -> dict:
    discovery = handoff["data"]["task_discovery"]
    tasks = [*discovery["active"], *discovery["recent"]]
    return next(
        task for task in tasks if task["task_type"] == "generation" and task["id"] == generation_id
    )


@pytest.mark.oracle
def test_oracle_uncertain_submission_recovers_via_explicit_retry(journey, http_server):
    journey.create_project(title="O3不确定提交")
    journey.propose_references()
    journey.approve_references()
    journey.apply_script()
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    journey.plan_keyframes()

    # ARRIVE：提交闸门打开；批量提交使首帧 Generation 进入 submission_uncertain。
    gate = SubmitGate(http_server.providers.image)
    gate.fail_submits = True
    journey._post(
        "O3.first_wave",
        f"{journey.resource}/keyframes/generate-batch",
        {"expected_revision": journey._revision()},
    )
    snap = journey.snapshot()
    uncertain = next(
        generation for generation in snap["generations"] if generation["kind"] == "keyframe_image"
    )
    assert uncertain["phase"] == "submission_uncertain"
    assert uncertain["error_code"] == "transport_error"
    attempts_before_restart = gate.attempts

    # ORACLE：task_discovery 给出错误契约的恢复分类（先检查后显式重试，不自动）。
    status, handoff = http_server.request(
        "POST",
        f"{journey.resource}/application/commands",
        {
            "name": "project.get_handoff",
            "idempotency_key": "O3-handoff-uncertain",
            "arguments": {},
        },
        role="agent",
    )
    assert status == 200
    task = _generation_task(handoff, uncertain["id"])
    assert task["status"] == "submission_uncertain"
    assert task["error_code"] == "transport_error"
    assert task["recovery"] == {
        "failure_origin": "provider_submission",
        "retry_policy": "inspect_then_explicit_generation_retry",
        "automatic_retry_allowed": False,
    }

    # ARRIVE：进程死并重建。
    http_server.restart()

    # ORACLE：恢复不重放提交，不确定 Generation 原样保留、分类不变。
    snap = journey.snapshot()
    recovered = next(
        generation for generation in snap["generations"] if generation["id"] == uncertain["id"]
    )
    assert recovered["phase"] == "submission_uncertain"
    assert recovered["error_code"] == "transport_error"
    assert gate.attempts == attempts_before_restart
    _, handoff = http_server.request(
        "POST",
        f"{journey.resource}/application/commands",
        {
            "name": "project.get_handoff",
            "idempotency_key": "O3-handoff-after-restart",
            "arguments": {},
        },
        role="agent",
    )
    assert _generation_task(handoff, uncertain["id"])["recovery"] == {
        "failure_origin": "provider_submission",
        "retry_policy": "inspect_then_explicit_generation_retry",
        "automatic_retry_allowed": False,
    }

    # ARRIVE：节点恢复；经真实 HTTP 显式重试，创建新 Generation 并保留 retry_of。
    gate.fail_submits = False
    retried_snap = journey._post(
        "O3.retry",
        f"{journey.resource}/generations/{uncertain['id']}/retry",
        {"expected_revision": journey._revision()},
    )
    retry = next(
        generation
        for generation in retried_snap["generations"]
        if generation.get("retry_of") == uncertain["id"]
    )
    # 同一目标上旧不确定 Generation 仍在等待集合里，把它视为终态一起等待。
    snap = journey.wait_generations(
        kind="keyframe_image",
        target_ids={uncertain["target_id"]},
        phases={"succeeded", "submission_uncertain"},
    )
    retry = next(
        generation for generation in snap["generations"] if generation["id"] == retry["id"]
    )
    assert retry["phase"] == "succeeded"
    assert retry["output_asset_id"] is not None

    # ORACLE：错误契约——对 succeeded Generation 重试被领域不变量拒绝。
    status, error_body = http_server.request(
        "POST",
        f"{journey.resource}/commands",
        {
            "name": "generation.retry",
            "idempotency_key": "O3-retry-succeeded",
            "arguments": {"generation_id": retry["id"]},
            "expected_revision": journey._revision(),
        },
        role="human",
    )
    assert status == 409
    error = error_body["error"]
    assert error["code"] == "business_rule_rejected"
    assert error["origin"] == "core_domain"
    assert error["state_changed"] is False
    assert error["retry_policy"] == "change_business_state_or_request"
    assert error["automatic_retry_allowed"] is False
    assert error["recoverable"] is False

    # ARRIVE：剩余帧续走（原不确定 Generation 作为历史保留，不被批量重放）。
    journey._post(
        "O3.second_wave",
        f"{journey.resource}/keyframes/generate-batch",
        {"expected_revision": journey._revision()},
    )
    journey.wait_generations(kind="keyframe_image", phases=_UNCERTAIN_TERMINAL)
    journey.select_keyframe_candidates()
    journey.generate_videos()
    journey.assemble_scene_finals()
    journey.assemble_final()
    journey.approve_final()

    # ORACLE：retry_of 链与历史保留；终态与 O1 等价。
    document = journey.document()
    structured = document["structured_director"]
    original = next(g for g in document["generations"] if g["id"] == uncertain["id"])
    assert original["phase"] == "submission_uncertain"
    assert not original["dismissed"]
    retried = next(g for g in document["generations"] if g.get("retry_of") == uncertain["id"])
    assert retried["phase"] == "succeeded"
    assert structured["status"] == "approved"
    assert structured["final_approval"] is not None
    assert all(structured["workspace_layers"].values())
