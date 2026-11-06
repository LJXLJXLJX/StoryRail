"""内置/外部脚本冷启动共用用例；复用现有 run、Store 与应用回执。"""

from dataclasses import asdict

from core.director_proposals.schema_gen import ProposalError
from core.director_proposals.script_codec import (
    parse_structured_director_script_proposal as parse_proposal,
)

from .errors import RevisionConflictError
from .models import DirectorRunKind
from .proposal_request_guard import owned_request as owned_request


def begin(store, *, expected_revision, raw_user_instruction="生成结构化导演脚本", recovery=True):
    document = store.read()
    if document.director_script is not None:
        raise ValueError("冷启动 proposal 不得覆盖已有脚本，请使用明确编辑操作。")
    if not recovery and document.active_director_run is not None:
        raise ValueError("已有任务正在执行，请恢复原请求。")
    return store.begin_script_proposal(
        expected_revision=expected_revision, raw_user_request=raw_user_instruction
    )


def submit(store, proposal, *, request_id, expected_revision):
    document = store.read()
    if document.revision != expected_revision:
        raise RevisionConflictError("项目已变化，请重新读取 proposal 请求。")
    run = document.active_director_run
    if run is None or run.id != request_id or run.kind is not DirectorRunKind.SCRIPT_PROPOSAL:
        raise ValueError("脚本 proposal 请求不存在或已经结束。")
    if document.director_script is not None:
        raise ValueError("冷启动 proposal 不得覆盖已有脚本。")
    if run.last_project_revision != expected_revision:
        raise RevisionConflictError("proposal 工作集已变化，请结束原请求并重新申请。")
    return store.apply_script_proposal(proposal)


def workset(document, raw):
    run = document.active_director_run
    return {
        "request_id": run.id,
        "scope": {"project_id": document.project_id, "operation": "initial_script"},
        "source_revision": document.revision,
        "core_facts": {
            "director_plan_markdown": document.director_plan_markdown,
            "narration_languages": [item.value for item in document.narration_languages],
            "reference_library": asdict(document.reference_library),
        },
        "raw_user_instruction": raw,
    }


__all__ = ["ProposalError", "parse_proposal", "owned_request"]
