"""外部规划复用原 Store run 与纯专业编译，不能调用内置执行器。"""

from dataclasses import dataclass

from core.director_proposals import KeyframeOperationsProposal
from core.director_proposals import keyframe_codec as keyframe

from .errors import RevisionConflictError
from .models import DirectorRunKind
from .planning_inputs import keyframe_inputs
from .reads.professional_worksets import workset_read
from .reads.read_tools import _json_value


@dataclass(frozen=True)
class PlanningProposalHandler:
    """Keyframe 规划请求：scope 随请求持久化，恢复时不能扩大。"""

    capability: str = "keyframe"

    def parse_proposal(self, raw):
        return keyframe.parse_keyframe_plan(raw)

    def request_fields(self):
        return {"raw_user_instruction", "scope", "target_ids"}

    def _workset(self, document, args):
        # 这是 proposal 写事务的 scope/事实校验，不是 read-tool 响应。
        # 大范围规划允许超过通用读取对象上限；对外专业读取另由分页协议控制。
        request = {
            "capability": self.capability,
            "scope": args["scope"],
            "target_ids": args["target_ids"],
        }
        data = workset_read(document, request)
        _, _, boundaries = keyframe_inputs(
            document, tuple(args["target_ids"]), args["raw_user_instruction"]
        )
        data["core_facts"]["required_shared_boundaries"] = _json_value(boundaries)
        return data

    def begin(self, store, *, expected_revision, recovery=False, **args):
        document = store.read()
        if document.active_director_run is not None:
            raise ValueError("已有任务，请读取原请求；不能隐式接管规划。")
        self._workset(document, args)  # scope 丢失/越界在任何写入前拒绝。
        return store.begin_keyframe_plan(
            expected_revision=expected_revision,
            target_ids=tuple(args["target_ids"]),
            user_message=args["raw_user_instruction"],
        )

    def workset(self, document, raw, request_arguments):
        return {
            **self._workset(document, request_arguments),
            "request_id": document.active_director_run.id,
            "raw_user_instruction": raw,
        }

    def submit(self, store, proposal, *, request_id, expected_revision, request_data):
        document = store.read()
        run = document.active_director_run
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已变化，请重新读取请求。")
        if run is None or run.id != request_id or run.kind is not DirectorRunKind.KEYFRAME_PLAN:
            raise ValueError("规划请求不存在或已经结束。")
        if request_data["source_revision"] != expected_revision:
            raise RevisionConflictError("规划工作集已过期，请取消并重新请求。")
        args = request_data.get("request_arguments")
        if not isinstance(args, dict) or set(args) != self.request_fields():
            raise ValueError("规划恢复缺少原始 scope，不能扩大为全部。")
        self._workset(document, args)
        scenes, segments, boundaries = keyframe_inputs(
            document, tuple(args["target_ids"]), args["raw_user_instruction"]
        )
        proposal, operations = keyframe.compile_keyframe_proposal(proposal, scenes, boundaries)
        if operations is None:
            raise ValueError("当前 Keyframe 槽位缺失，不能重新分配替代恢复。")
        return store.apply_keyframe_operation_plan(
            KeyframeOperationsProposal(operations, "已按原始外部规划 scope 编译。"),
            target_segment_ids=segments,
            required_shared_boundaries=boundaries,
        )
