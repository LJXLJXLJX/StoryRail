from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from core.director_commands.video_commands import (
    parse_video_reference_image_selection,
    parse_video_reference_image_update,
)

if TYPE_CHECKING:
    from core.structured_director.models import DirectorRunCursor, StructuredDirectorDocument

# 外部 proposal/workflow 命令注册表（D10 延迟挂载机制 P3-T? 再统一，本卡仅提升为模块级 import）。
from core.structured_director.proposal_requests import (
    OPERATIONS as _PROPOSAL_OPERATIONS,
)
from core.structured_director.proposal_requests import (
    execute as _execute_proposal_request,
)
from core.structured_director.workflow_commands import (
    OPERATIONS as _WORKFLOW_OPERATIONS,
)
from core.structured_director.workflow_commands import (
    execute as _execute_workflow_command,
)

from .dialogue_commands import DialogueTimingUpdate, parse_dialogue_timing_update
from .final_commands import (
    FinalApprovalRequest,
    FinalCandidateSelection,
    parse_empty_arguments,
    parse_final_approval,
    parse_final_candidate_selection,
)
from .generation_commands import GenerationTarget, parse_generation_target
from .location_operations import (
    LocationImageSelection,
    LocationOperationsPatch,
    parse_location_image_selection,
    parse_location_operations_patch,
)
from .models import (
    CommandExecution,
    CommandReceipt,
    DirectorCommand,
    InvalidArgumentsError,
    KeyframeCandidateSelection,
    RepairPatch,
    RepairReceipt,
    director_command_id,
    parse_keyframe_candidate_selection,
    parse_keyframe_operations,
    parse_repair_patch,
)
from .narration_commands import (
    NarrationCueUpdate,
    NarrationSelectionClear,
    parse_narration_cue_update,
    parse_narration_selection_clear,
)
from .reference_commands import LookOperationsPatch, parse_look_operations_patch
from .run_commands import RunResume, RunTarget, parse_run_resume, parse_run_target
from .script_operations import ScriptOperationsPatch, parse_script_operations_patch
from .video_commands import (
    VideoInputsUpdate,
    VideoPromptUpdate,
    VideoRecipeUpdate,
    VideoSelectionClear,
    parse_video_inputs_update,
    parse_video_prompt_update,
    parse_video_recipe_update,
    parse_video_selection_clear,
)


class DirectorCommandStore(Protocol):
    def execute_director_read(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, dict[str, object]]: ...

    def apply_keyframe_operations(
        self,
        operations: tuple[object, ...],
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def apply_repair_patch(
        self,
        patch: RepairPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, RepairReceipt]: ...

    def apply_script_operations(
        self,
        patch: ScriptOperationsPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def apply_location_operations(
        self,
        patch: LocationOperationsPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, dict[str, object]]: ...

    def select_keyframe_candidate(
        self,
        selection: KeyframeCandidateSelection,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def select_location_image(
        self,
        selection: LocationImageSelection,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def update_narration_cue(
        self,
        update: NarrationCueUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def clear_narration_selection(
        self,
        clear: NarrationSelectionClear,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def set_dialogue_timing_command(
        self,
        update: DialogueTimingUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def set_segment_video_prompt(
        self,
        update: VideoPromptUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def set_segment_video_inputs(
        self,
        update: VideoInputsUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def set_segment_video_prompt_with_run_progress(
        self,
        update: VideoPromptUpdate,
        *,
        expected_revision: int,
        command_id: str,
        run_id: str,
        cursor: DirectorRunCursor,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def set_segment_video_recipe(
        self,
        update: VideoRecipeUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def clear_segment_video_selection(
        self,
        clear: VideoSelectionClear,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def dismiss_generation_command(
        self,
        target: GenerationTarget,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def select_final_candidate_command(
        self,
        selection: FinalCandidateSelection,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def clear_final_selection_command(
        self,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def approve_final_command(
        self,
        approval: FinalApprovalRequest,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def reopen_final_production_command(
        self,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def apply_look_operations(
        self,
        patch: LookOperationsPatch,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def cancel_director_run_command(
        self,
        target: RunTarget,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...

    def resume_director_run_command(
        self,
        resume: RunResume,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]: ...


def _parse_arguments(parser, *values):
    try:
        return parser(*values)
    except InvalidArgumentsError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from exc


_NO_ARGUMENT = object()


@dataclass(frozen=True, slots=True)
class _CommandSpec:
    parser: Callable[[dict[str, object], str], object] | None
    handler: str | Callable[[DirectorCommandStore, DirectorCommand], CommandExecution]
    scope_rule: str = "exact"


def _parse(parser: Callable[[object], object]):
    return lambda arguments, _name: _parse_arguments(parser, arguments)


def _parse_named(parser: Callable[[object, str], object]):
    return lambda arguments, name: _parse_arguments(parser, arguments, name)


def _parse_empty(arguments: dict[str, object], name: str) -> object:
    _parse_arguments(parse_empty_arguments, arguments, name)
    return _NO_ARGUMENT


def _parse_keyframe_command(arguments: dict[str, object], _name: str) -> object:
    if set(arguments) != {"operations"}:
        raise InvalidArgumentsError("keyframe.apply_operations.arguments 包含缺失或未声明字段。")
    return _parse_arguments(parse_keyframe_operations, arguments["operations"])


def _delegate_proposal(store: DirectorCommandStore, command: DirectorCommand) -> CommandExecution:
    return _execute_proposal_request(store, command)


def _delegate_workflow(store: DirectorCommandStore, command: DirectorCommand) -> CommandExecution:
    return _execute_workflow_command(store, command)


def _execute_read(store: DirectorCommandStore, command: DirectorCommand) -> CommandExecution:
    document, receipt, data = store.execute_director_read(
        command.name,
        command.arguments,
        expected_revision=command.expected_revision,
        command_id=director_command_id(command),
    )
    return CommandExecution(document, receipt, data)


def _execute_location_operations(
    store: DirectorCommandStore, command: DirectorCommand
) -> CommandExecution:
    patch = _parse_arguments(parse_location_operations_patch, command.arguments)
    document, receipt, data = store.apply_location_operations(
        patch,
        expected_revision=command.expected_revision,
        command_id=director_command_id(command),
    )
    return CommandExecution(document, receipt, data)


def translate_repair_to_script_operations(patch: RepairPatch) -> dict[str, object] | None:
    """将仅含 Shot/Segment 字段修正的 repair 纯翻译为正式脚本操作。"""
    if not all(operation.entity_type in {"shot", "segment"} for operation in patch.operations):
        return None
    return {
        "scope": {"scene_ids": list(patch.scope_scene_ids)},
        "operations": [
            {
                "op": (
                    "update_shot_fields"
                    if operation.entity_type == "shot"
                    else "update_segment_fields"
                ),
                (
                    "shot_id" if operation.entity_type == "shot" else "segment_id"
                ): operation.entity_id,
                "fields": operation.fields,
            }
            for operation in patch.operations
        ],
    }


def _execute_repair(store: DirectorCommandStore, command: DirectorCommand) -> CommandExecution:
    patch = _parse_arguments(parse_repair_patch, command.arguments)
    translated_arguments = translate_repair_to_script_operations(patch)
    if translated_arguments is not None:
        translated_command = DirectorCommand(
            "script.apply_operations",
            command.expected_revision,
            command.idempotency_key,
            translated_arguments,
        )
        translated_patch = _parse_arguments(
            parse_script_operations_patch, translated_command.arguments
        )
        document, receipt = store.apply_script_operations(
            translated_patch,
            expected_revision=translated_command.expected_revision,
            command_id=director_command_id(translated_command),
        )
        return CommandExecution(document, receipt)
    document, receipt, repair_receipt = store.apply_repair_patch(
        patch,
        expected_revision=command.expected_revision,
        command_id=director_command_id(command),
    )
    return CommandExecution(document, receipt, repair_receipt=repair_receipt)


_COMMAND_SPECS: dict[str, _CommandSpec] = {
    **{name: _CommandSpec(None, _delegate_proposal, "proposal") for name in _PROPOSAL_OPERATIONS},
    **{name: _CommandSpec(None, _delegate_workflow, "workflow") for name in _WORKFLOW_OPERATIONS},
    "run.cancel": _CommandSpec(_parse_named(parse_run_target), "cancel_director_run_command"),
    "run.resume": _CommandSpec(_parse(parse_run_resume), "resume_director_run_command"),
    "project.apply_repair_patch": _CommandSpec(None, _execute_repair, "repair"),
    "script.apply_operations": _CommandSpec(
        _parse(parse_script_operations_patch), "apply_script_operations"
    ),
    "narration.update_cue": _CommandSpec(
        _parse(parse_narration_cue_update), "update_narration_cue"
    ),
    "narration.clear_selection": _CommandSpec(
        _parse(parse_narration_selection_clear), "clear_narration_selection"
    ),
    "dialogue.set_timing": _CommandSpec(
        _parse(parse_dialogue_timing_update), "set_dialogue_timing_command"
    ),
    "video.save_reference_image_plan": _CommandSpec(
        _parse(parse_video_reference_image_update), "save_video_reference_image_plan"
    ),
    "video.select_reference_image": _CommandSpec(
        _parse(parse_video_reference_image_selection), "select_video_reference_image"
    ),
    "video.set_prompt": _CommandSpec(_parse(parse_video_prompt_update), "set_segment_video_prompt"),
    "video.update_recipe_inputs": _CommandSpec(
        _parse(parse_video_inputs_update), "set_segment_video_inputs"
    ),
    "video.set_recipe": _CommandSpec(_parse(parse_video_recipe_update), "set_segment_video_recipe"),
    "video.clear_selection": _CommandSpec(
        _parse(parse_video_selection_clear), "clear_segment_video_selection"
    ),
    "generation.dismiss": _CommandSpec(
        _parse_named(parse_generation_target), "dismiss_generation_command"
    ),
    "final.select_candidate": _CommandSpec(
        _parse(parse_final_candidate_selection), "select_final_candidate_command"
    ),
    "final.clear_selection": _CommandSpec(_parse_empty, "clear_final_selection_command"),
    "final.approve": _CommandSpec(_parse(parse_final_approval), "approve_final_command"),
    "final.reopen_production": _CommandSpec(_parse_empty, "reopen_final_production_command"),
    "keyframe.apply_operations": _CommandSpec(_parse_keyframe_command, "apply_keyframe_operations"),
    "keyframe.select_candidate": _CommandSpec(
        _parse(parse_keyframe_candidate_selection), "select_keyframe_candidate"
    ),
    "location.apply_operations": _CommandSpec(None, _execute_location_operations),
    "reference.apply_look_operations": _CommandSpec(
        _parse(parse_look_operations_patch), "apply_look_operations"
    ),
    # 地点图片选择只开放给人类：不在 Agent 操作白名单（core.application.caller）。
    "location.select_image": _CommandSpec(
        _parse(parse_location_image_selection), "select_location_image"
    ),
}

_READ_SPEC = _CommandSpec(None, _execute_read, "project_read")


class DirectorCommandRegistry:
    """按稳定 command name 分派严格参数；不持有 Agent 或 Provider 能力。"""

    def __init__(self, store: DirectorCommandStore) -> None:
        self._store = store

    def execute(self, command: DirectorCommand) -> CommandExecution:
        spec = _COMMAND_SPECS.get(command.name)
        if spec is None and (
            command.name.startswith("project.") or command.name == "run.get_status"
        ):
            spec = _READ_SPEC
        if spec is None:
            raise InvalidArgumentsError(f"尚未注册 Director command：{command.name}。")
        if callable(spec.handler):
            return spec.handler(self._store, command)
        parsed = (
            _NO_ARGUMENT if spec.parser is None else spec.parser(command.arguments, command.name)
        )
        method = getattr(self._store, spec.handler)
        kwargs: dict[str, Any] = {
            "expected_revision": command.expected_revision,
            "command_id": director_command_id(command),
        }
        result = method(**kwargs) if parsed is _NO_ARGUMENT else method(parsed, **kwargs)
        document, receipt = result
        return CommandExecution(document, receipt)

    def execute_with_run_progress(
        self,
        command: DirectorCommand,
        *,
        run_id: str,
        cursor: DirectorRunCursor,
    ) -> CommandExecution:
        """将一个 H3 正文 command 与其 DirectorRun 进度原子提交。"""
        if command.name != "video.set_prompt":
            raise ValueError("只有 video.set_prompt 支持与 DirectorRun 进度原子提交。")
        command_id = director_command_id(command)
        update = _parse_arguments(parse_video_prompt_update, command.arguments)
        document, receipt = self._store.set_segment_video_prompt_with_run_progress(
            update,
            expected_revision=command.expected_revision,
            command_id=command_id,
            run_id=run_id,
            cursor=cursor,
        )
        return CommandExecution(document, receipt)
