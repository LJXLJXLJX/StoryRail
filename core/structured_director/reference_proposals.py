"""首次引用库的无 runtime 业务入口；ID 与审核状态仍由原 Store 管理。"""

from core.director_proposals.reference_library_codec import (
    REFERENCE_LIBRARY_OUTPUT_SCHEMA,
)
from core.director_proposals.reference_library_codec import (
    parse_reference_library_proposal as parse_proposal,
)
from core.director_proposals.schema_gen import ProposalError, narration_language_schema

from .errors import RevisionConflictError
from .models import DirectorRunKind, StructuredDirectorStatus


def begin(store, *, expected_revision, raw_user_instruction, recovery=False):
    document = store.read()
    if document.revision != expected_revision:
        raise RevisionConflictError("项目已变化，请重新读取引用库请求。")
    if document.status is not StructuredDirectorStatus.AWAITING_PROPOSAL:
        raise ValueError("首次引用库 proposal 不得覆盖已有引用库。")
    if not recovery and document.active_director_run is not None:
        raise ValueError("已有任务正在执行，请恢复原请求。")
    return store.begin_reference_proposal(raw_user_request=raw_user_instruction)


def submit(store, proposal, *, request_id, expected_revision):
    document = store.read()
    if document.revision != expected_revision:
        raise RevisionConflictError("项目已变化，请重新读取引用库请求。")
    run = document.active_director_run
    if run is None or run.id != request_id or run.kind is not DirectorRunKind.REFERENCE_PROPOSAL:
        raise ValueError("引用库 proposal 请求不存在或已经结束。")
    if run.last_project_revision != expected_revision:
        raise RevisionConflictError("proposal 工作集已变化，请结束原请求并重新申请。")
    return store.apply_reference_proposal(proposal)


def workset(document, raw):
    return {
        "request_id": document.active_director_run.id,
        "scope": {"project_id": document.project_id, "operation": "initial_reference_library"},
        "source_revision": document.revision,
        "core_facts": {
            "director_plan_markdown": document.director_plan_markdown,
            "narration_languages": [item.value for item in document.narration_languages],
        },
        "raw_user_instruction": raw,
        "output_schema": narration_language_schema(
            REFERENCE_LIBRARY_OUTPUT_SCHEMA, document.narration_languages
        ),
        "constraints": [
            "仅提取完整导演方案中需要跨镜头一致的角色卡；画外旁白独立为 narrator。",
            "仅提交卡片字段，不分配 ID、不选择候选、不调用 Provider；提交后等待人类审核。",
        ],
    }


__all__ = ["ProposalError", "parse_proposal"]
