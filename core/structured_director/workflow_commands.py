"""既有工作流方法的确定性命令入口；人类审核权限由可信 caller 门禁决定。"""

from core.director_commands.models import (
    CommandExecution,
    CommandReceipt,
    InvalidArgumentsError,
    director_command_id,
)

from .models import SegmentVideo
from .reads.impact import location_unlock_advisory
from .reads.workflow_state import reference_fingerprint

OPERATIONS = {
    "reference.confirm_review",
    "script.confirm",
    "visual_production.unlock",
}


def execute(store, command):
    if command.arguments:
        raise InvalidArgumentsError("工作流动作不接受额外参数。")
    if command.name == "reference.confirm_review":
        document = store._editable_document(command.expected_revision)
        if document.active_director_run is not None:
            raise ValueError("请等待当前任务结束后审核。")
        return CommandExecution(
            document,
            CommandReceipt(
                director_command_id(command), "succeeded", document.revision, document.revision
            ),
            {"reference_fingerprint": reference_fingerprint(document)},
        )
    if command.name == "visual_production.unlock":
        document = store._editable_document(command.expected_revision)
        exists = document.workspace_layers.videos_unlocked
        if exists:
            return CommandExecution(
                document,
                CommandReceipt(
                    director_command_id(command), "noop", document.revision, document.revision
                ),
                {"location_advisory": location_unlock_advisory(document)},
            )
    if command.name == "script.confirm":
        updated = store.confirm_director_script(expected_revision=command.expected_revision)
    else:
        document = store.read()
        if document.director_script is None:
            raise ValueError("导演脚本尚未建立。")
        segments = tuple(
            SegmentVideo(
                s.id,
                "",
            )
            for scene in document.director_script.scenes
            for shot in scene.shots
            for s in shot.segments
        )
        updated = store.unlock_visual_production(
            segments, expected_revision=command.expected_revision
        )
    data = (
        {"location_advisory": location_unlock_advisory(updated)}
        if command.name == "visual_production.unlock"
        else None
    )
    return CommandExecution(
        updated,
        CommandReceipt(
            director_command_id(command), "succeeded", command.expected_revision, updated.revision
        ),
        data,
    )
