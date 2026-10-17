"""地点规划的外部 proposal 入口：项目级工作集、增补式 proposal 与原子落库。

落库编译成 `location.apply_operations` 的同一组操作，复用地点库唯一 mutation 与失效级联。
"""

from core.director_proposals.location_codec import (
    compile_location_proposal,
)
from core.director_proposals.location_codec import (
    parse_location_plan as parse_proposal,
)
from core.director_proposals.schema_gen import ProposalError

from .errors import RevisionConflictError
from .models import DirectorRunKind
from .planning_inputs import location_inputs
from .reads.professional_worksets import workset_read


def begin(store, *, expected_revision, raw_user_instruction, recovery=False):
    document = store.read()
    if document.revision != expected_revision:
        raise RevisionConflictError("项目已变化，请重新读取地点规划请求。")
    if not recovery and document.active_director_run is not None:
        raise ValueError("已有任务正在执行，请恢复原请求。")
    updated = store.begin_location_plan(
        expected_revision=expected_revision, user_message=raw_user_instruction
    )
    return updated, False


def workset(document, raw):
    data = workset_read(
        document, {"capability": "location", "scope": {"project_id": document.project_id}}
    )
    # 请求回执不携带插件写法资源；当前图片插件的 image_prompt 以 read_professional_workset 为准。
    del data["core_facts"]["image_prompt"]
    return {**data, "request_id": document.active_director_run.id, "raw_user_instruction": raw}


def submit(store, proposal, *, request_id, expected_revision):
    document = store.read()
    if document.revision != expected_revision:
        raise RevisionConflictError("项目已变化，请重新读取地点规划请求。")
    run = document.active_director_run
    if run is None or run.id != request_id or run.kind is not DirectorRunKind.LOCATION_PLAN:
        raise ValueError("地点规划请求不存在或已经结束。")
    if run.last_project_revision != expected_revision:
        raise RevisionConflictError("地点规划工作集已变化，请结束原请求并重新申请。")
    scenes, existing = location_inputs(document)
    patch = compile_location_proposal(proposal, scenes, existing)
    try:
        return store.apply_location_plan(patch, expected_revision=expected_revision)
    except RevisionConflictError:
        raise
    except ValueError as exc:
        # 领域模型（上限、角度、朝向二选一、无环）与失效冲突的拒绝原样交回 Agent 修正。
        raise ProposalError("location", "invalid_proposal", str(exc)) from exc


__all__ = ["begin", "parse_proposal", "submit", "workset"]
