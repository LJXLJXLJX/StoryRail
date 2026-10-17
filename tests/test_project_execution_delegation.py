"""受信项目委托只放开有限 Agent 命令，不改变默认精确 grant 或人类边界。"""

from dataclasses import replace

import pytest

from core.application.caller import AccessDenied, Caller, authorize_command


def test_project_delegation_keeps_scope_expiry_switch_and_human_boundaries():
    pid = "a" * 32
    caller = Caller(
        "local-agent",
        "agent",
        frozenset({pid}),
        frozenset({"project.read", "project.mutate", "project.propose", "project.execute"}),
        4102444800,
        (),
        True,
    )
    for name in (
        "script.request_proposal",
        "script.apply_operations",
        "keyframe.request_proposal",
        "video.set_prompt",
        "video.generate",
        "keyframe.continue_batch",
        "run.cancel",
    ):
        command = {"name": name, "arguments": {}, "expected_revision": 1}
        authorize_command(caller, pid, command)
        for denied in (
            replace(caller, expires_at=1),
            replace(caller, mutations_enabled=False),
            replace(caller, project_ids=frozenset({"b" * 32})),
            replace(caller, capabilities=caller.capabilities - {"project.execute"}),
            replace(caller, capabilities=caller.capabilities - {"project.mutate"}),
        ):
            with pytest.raises(AccessDenied):
                authorize_command(denied, pid, command)
    for name in (
        "final.approve",
        "final.select_candidate",
        "script.confirm",
        "project.apply_repair_patch",
        "unknown.action",
    ):
        with pytest.raises(AccessDenied):
            authorize_command(caller, pid, {"name": name})
