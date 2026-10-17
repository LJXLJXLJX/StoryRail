"""O5 · 权限边界 oracle。

ARRIVE   journey 驱动 drama 项目到关键帧已生成且有 succeeded 候选（规划 + 多轮
         批量生成，未选择）；随后以 agent 身份（capabilities 含 project.read /
         project.mutate / project.propose / project.execute 的受信外部 Agent）
         经真实 HTTP 尝试人类独占动作：选择关键帧候选、人类审核命令
         （reference.confirm_review / script.confirm）、批准成片（final/approve、
         final/select）、修改 provider 设置、访问未授权项目。
ORACLE   断言每次拒绝：
         - HTTP 403，错误体逐字段符合 docs/error-contract.md 授权行
           （origin="authorization"、state_changed=false、
           retry_policy="obtain_authorization_or_user_action"、
           automatic_retry_allowed=false、recoverable=false）；
         - project.json revision 与动作前完全一致（无副作用）；
         - 正向对照：同一 keyframe select 以 human 身份成功，agent 只读
           project.get_handoff 成功——拒绝来自授权边界而非状态机。
覆盖领域规则：信任边界——Agent 只能提交类型化 proposal / 白名单 Agent 操作，
不能选择候选、批准、发布或改 Provider 设置；Core 校验 caller/role/capability/
scope，不以 Agent 自报正文授予能力；拒绝不产生业务副作用。
BUDGET   单场景 ≤20s（真实 loopback HTTP + 合成 Provider）。
"""

from __future__ import annotations

import pytest

_AUTHORIZATION_DENIAL = {
    "origin": "authorization",
    "state_changed": False,
    "retry_policy": "obtain_authorization_or_user_action",
    "automatic_retry_allowed": False,
    "recoverable": False,
}


def _assert_denied(status: int, body: dict, *, code: str) -> None:
    assert status == 403
    error = body["error"]
    assert error["code"] == code
    for field, value in _AUTHORIZATION_DENIAL.items():
        assert error[field] == value, f"error.{field}"


@pytest.mark.oracle
def test_oracle_agent_cannot_cross_human_authorization_boundary(journey, http_server):
    # ARRIVE：关键帧有 succeeded 候选（未选择）。
    journey.create_project(title="O5权限边界")
    journey.propose_references()
    journey.approve_references()
    journey.apply_script()
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    journey.plan_keyframes()
    journey.generate_keyframe_candidates()
    frame = journey.snapshot()["keyframe_plan"]["keyframes"][0]
    candidate = next(
        generation
        for generation in journey.snapshot()["generations"]
        if generation["kind"] == "keyframe_image"
        and generation["target_id"] == frame["id"]
        and generation["phase"] == "succeeded"
    )

    def revision() -> int:
        return journey.document()["revision"]

    # ORACLE：agent 走 human Web 入口选择关键帧候选 → 403 external_mutation_disabled。
    before = revision()
    status, body = http_server.request(
        "POST",
        f"{journey.resource}/keyframes/{frame['id']}/select",
        {"expected_revision": journey._revision(), "asset_id": candidate["output_asset_id"]},
        role="agent",
    )
    _assert_denied(status, body, code="external_mutation_disabled")
    assert revision() == before
    assert journey.snapshot()["keyframe_plan"]["keyframes"][0]["selected_asset_id"] is None

    # ORACLE：agent typed command 尝试人类审核命令 → 403 capability_denied。
    for name in ("reference.confirm_review", "script.confirm"):
        before = revision()
        status, body = http_server.request(
            "POST",
            f"{journey.resource}/application/commands",
            {
                "name": name,
                "idempotency_key": f"O5-agent-{name}",
                "arguments": {},
                "expected_revision": journey._revision(),
            },
            role="agent",
        )
        _assert_denied(status, body, code="capability_denied")
        assert revision() == before

    # ORACLE：agent 尝试批准/选择成片（human Web 入口，与项目所处阶段无关）→ 403。
    for path, payload in (
        ("final/approve", {"asset_id": "a" * 32}),
        ("final/select", {"generation_id": "b" * 32}),
    ):
        before = revision()
        status, body = http_server.request(
            "POST",
            f"{journey.resource}/{path}",
            {"expected_revision": journey._revision(), **payload},
            role="agent",
        )
        _assert_denied(status, body, code="external_mutation_disabled")
        assert revision() == before

    # ORACLE：agent 修改 provider 绑定或插件设置 → 403 scope_denied（拒绝发生在访问层，
    # 早于" harness 未装配 provider 设置"的 404，因此无需假实现）。
    before = revision()
    status, body = http_server.request(
        "PUT",
        "/api/settings/providers/bindings",
        {"capability": "image.generate", "plugin_id": "agy_image"},
        role="agent",
    )
    _assert_denied(status, body, code="scope_denied")
    assert revision() == before
    status, body = http_server.request(
        "PUT",
        "/api/settings/providers/plugins/minimax_h3",
        {"settings": {"preset": "turbo_v2"}},
        role="agent",
    )
    _assert_denied(status, body, code="scope_denied")
    # 正向：human 通过授权层后落到 404（harness 未装配 provider 设置，属预期）。
    status, _ = http_server.request(
        "PUT",
        "/api/settings/providers/bindings",
        {"capability": "image.generate", "plugin_id": "agy_image"},
        role="human",
    )
    assert status == 404

    # ORACLE：agent 访问不在其 project_ids 内的项目（未授权给任何 caller）→ 403。
    status, created = http_server.request(
        "POST",
        "/api/projects",
        {
            "title": "O5未授权项目",
            "aspect_ratio": "16:9",
            "director_plan_markdown": "# 旁立项目",
            "narration_languages": ["zh", "en"],
        },
        role="human",
    )
    assert status == 201
    other_id = created["project"]["id"]
    # 注意：故意不 authorize_project——该项目不在任何 caller 的 project_ids 内。
    status, body = http_server.request(
        "GET", f"/api/projects/{other_id}/structured-director", role="agent"
    )
    _assert_denied(status, body, code="scope_denied")
    status, body = http_server.request(
        "POST",
        f"/api/projects/{other_id}/structured-director/application/commands",
        {
            "name": "project.get_handoff",
            "idempotency_key": "O5-cross-project",
            "arguments": {},
        },
        role="agent",
    )
    _assert_denied(status, body, code="scope_denied")

    # 正向对照：agent 只读（正式读取入口）成功——拒绝不是状态机或读能力问题。
    status, body = http_server.request(
        "POST",
        f"{journey.resource}/application/commands",
        {
            "name": "project.get_handoff",
            "idempotency_key": "O5-agent-read",
            "arguments": {},
        },
        role="agent",
    )
    assert status == 200
    assert body["data"]["project_id"] == journey.project_id

    # 正向对照：同一 keyframe select 以 human 身份成功（候选生成与选择分离）。
    selected = journey._post(
        "O5.human_select",
        f"{journey.resource}/keyframes/{frame['id']}/select",
        {"expected_revision": journey._revision(), "asset_id": candidate["output_asset_id"]},
    )
    assert (
        next(item for item in selected["keyframe_plan"]["keyframes"] if item["id"] == frame["id"])[
            "selected_asset_id"
        ]
        == candidate["output_asset_id"]
    )
