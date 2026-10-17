from __future__ import annotations

from dataclasses import replace

from core.director_commands import (
    DirectorCommand,
    director_command_id,
    parse_animatic_scene_target,
    parse_empty_arguments,
    parse_final_approval,
    parse_final_candidate_selection,
    parse_final_scene_target,
    parse_generation_target,
    parse_generation_wait,
    parse_keyframe_operations,
    parse_location_master_selection,
    parse_location_operations_patch,
    parse_location_view_selection,
    parse_narration_cue_update,
    parse_narration_selection_clear,
    parse_repair_patch,
    parse_script_operations_patch,
    parse_video_inputs_update,
    parse_video_prompt_update,
    parse_video_recipe_update,
    parse_video_selection_clear,
)

from ..keyframe_mutations import _apply_keyframe_operations
from ..location_mutations import (
    apply_location_operations,
    select_location_master,
    select_location_view,
)
from ..models import StructuredDirectorDocument
from ..mutations.narration import clear_narration_selection, update_narration_cue
from ..repair_mutations import _apply_repair_operations, _repair_invalidated_items
from ..script_mutations import (
    _apply_script_operations,
    _invalidate_production_after_script_revision,
    _validate_script_references,
)
from ..video_mutations import (
    _prepare_segment_video_plan_update,
    _reject_active_segment_video_generation,
    _require_video_command_target,
)
from .workflow_state import location_binding_gaps


def preview_command_impact(
    document: StructuredDirectorDocument,
    command: DirectorCommand,
) -> dict[str, object]:
    """严格解析正式命令并返回不写项目的保守影响上界。"""
    if command.expected_revision != document.revision:
        raise ValueError("待预览 command 的 expected_revision 与当前项目不一致。")
    changed_ids: set[str] = set()
    invalidated: set[str] = set()
    preserved: set[str] = set()
    name = command.name

    if name == "script.apply_operations":
        patch = parse_script_operations_patch(command.arguments)
        if document.director_script is None:
            raise ValueError("结构化导演脚本尚未建立。")

        scenes, actual_changed_ids = _apply_script_operations(
            document.director_script.scenes,
            patch,
            command_id=director_command_id(command),
        )
        if scenes != document.director_script.scenes:
            _validate_script_references(
                scenes,
                document.reference_library,
                previous_scenes=document.director_script.scenes,
            )
            projected = _invalidate_production_after_script_revision(document, scenes)
            invalidated.update(_repair_invalidated_items(document, projected))
            changed_ids.update(actual_changed_ids)
            preserved.update(("asset_history", "generation_history"))
    elif name == "project.apply_repair_patch":
        patch = parse_repair_patch(command.arguments)
        if document.director_script is None:
            raise ValueError("repair patch 只能修改已经建立的导演脚本。")

        scenes, _reverse, target_ids = _apply_repair_operations(
            document.director_script.scenes,
            patch,
        )
        changed_ids.update(target_ids)
        if scenes != document.director_script.scenes:
            projected = _invalidate_production_after_script_revision(document, scenes)
            invalidated.update(_repair_invalidated_items(document, projected))
            preserved.update(("asset_history", "generation_history"))
    elif name in {"narration.update_cue", "narration.clear_selection"}:
        # 旁白预览直接复用纯函数 mutation 的回执，避免与写入语义分叉。
        result = (
            update_narration_cue(
                document, parse_narration_cue_update(command.arguments), "impact-preview"
            )
            if name == "narration.update_cue"
            else clear_narration_selection(
                document, parse_narration_selection_clear(command.arguments), "impact-preview"
            )
        )
        if result.write:
            changed_ids.update(result.receipt.changed_ids)
            invalidated.update(result.receipt.invalidated)
        preserved.update(result.receipt.preserved)
    elif name == "keyframe.apply_operations":
        if set(command.arguments) != {"operations"}:
            raise ValueError("keyframe.apply_operations.arguments 包含缺失或未声明字段。")
        operations = parse_keyframe_operations(command.arguments["operations"])

        result = _apply_keyframe_operations(document, operations)
        changed_ids.update(result.changed_ids)
        invalidated.update(result.invalidated)
        if result.document != document:
            preserved.update(result.preserved)
    elif name in {"location.apply_operations", "location.select_master", "location.select_view"}:
        # 与写入共用纯函数 mutation 与失效级联，预览即实际影响。
        if name == "location.apply_operations":
            result = apply_location_operations(
                document, parse_location_operations_patch(command.arguments)
            )
        elif name == "location.select_master":
            result = select_location_master(
                document, parse_location_master_selection(command.arguments)
            )
        else:
            result = select_location_view(
                document, parse_location_view_selection(command.arguments)
            )
        if result.document == document:
            preserved.add("location_selection")
        else:
            changed_ids.update(result.changed_ids)
            invalidated.update(_repair_invalidated_items(document, result.document))
            preserved.update(("asset_history", "generation_history"))
    elif name == "video.update_recipe_inputs":
        update = parse_video_inputs_update(command.arguments)
        projected, _receipt = _prepare_segment_video_plan_update(
            document, update, director_command_id(command)
        )
        if projected is document:
            preserved.update(("video_selection", "video_upscale_selection"))
        else:
            changed_ids.add(update.segment_id)
            invalidated.update(_repair_invalidated_items(document, projected))
            preserved.update(("asset_history", "generation_history"))
    elif name in {"video.set_prompt", "video.set_recipe", "video.clear_selection"}:
        item = {
            "video.set_prompt": parse_video_prompt_update,
            "video.set_recipe": parse_video_recipe_update,
            "video.clear_selection": parse_video_selection_clear,
        }[name](command.arguments)

        plan, _scene, segment, current = _require_video_command_target(
            document, item.scope_scene_ids, item.segment_id
        )
        if name != "video.clear_selection":
            _reject_active_segment_video_generation(document, item.segment_id)
        if name == "video.set_prompt":
            is_noop = current.prompt_text == item.prompt_text
            replacement = replace(
                current,
                prompt_text=item.prompt_text,
                selected_asset_id=None,
                upscaled_asset_id=None,
            )
        elif name == "video.set_recipe":
            is_noop = current.active_recipe == item.recipe_id
            replacement = replace(
                current,
                active_recipe=item.recipe_id,
                selected_asset_id=None,
                upscaled_asset_id=None,
            )
        else:
            is_noop = current.selected_asset_id is None and current.upscaled_asset_id is None
            replacement = replace(current, selected_asset_id=None, upscaled_asset_id=None)
        if is_noop:
            if name != "video.clear_selection":
                preserved.update(("video_selection", "video_upscale_selection"))
        else:
            projected = replace(
                document,
                revision=document.revision + 1,
                video_plan=replace(
                    plan,
                    segments=tuple(
                        replacement if current_item.segment_id == item.segment_id else current_item
                        for current_item in plan.segments
                    ),
                ),
                final_assembly=None,
            )
            changed_ids.add(item.segment_id)
            invalidated.update(_repair_invalidated_items(document, projected))
            preserved.update(("asset_history", "generation_history"))
    elif name in {"generation.cancel", "generation.retry", "generation.dismiss"}:
        target = parse_generation_target(command.arguments, name)
        changed_ids.add(target.generation_id)
        if name == "generation.retry":
            invalidated.add("new_generation")
    elif name == "generation.wait":
        wait = parse_generation_wait(command.arguments)
        changed_ids.update(wait.generation_ids)
    elif name == "animatic.generate_scene":
        target = parse_animatic_scene_target(command.arguments)
        changed_ids.add(target.scene_id)
        invalidated.add("new_generation")
    elif name == "final.assemble_scene":
        target = parse_final_scene_target(command.arguments)
        changed_ids.add(target.scene_id)
        invalidated.add("new_generation")
    elif name == "final.assemble":
        parse_empty_arguments(command.arguments, name)
        invalidated.add("new_generation")
    elif name == "final.select_candidate":
        selection = parse_final_candidate_selection(command.arguments)
        changed_ids.add(selection.generation_id)
        if document.final_assembly is not None and _has_final_selection(document):
            invalidated.add("final_selection")
    elif name == "final.clear_selection":
        parse_empty_arguments(command.arguments, name)
        if document.final_assembly is not None and _has_final_selection(document):
            invalidated.add("final_selection")
    elif name == "final.approve":
        approval = parse_final_approval(command.arguments)
        changed_ids.update(
            asset_id
            for asset_id in (approval.zh_asset_id, approval.en_asset_id)
            if asset_id is not None
        )
        invalidated.add("workflow_status")
    elif name == "final.reopen_production":
        parse_empty_arguments(command.arguments, name)
        if document.final_assembly is not None:
            invalidated.add("final_assembly")
        if document.final_approval is not None:
            invalidated.add("final_approval")
    elif name == "visual_production.unlock":
        parse_empty_arguments(command.arguments, name)
        if document.director_script is None:
            raise ValueError("结构化导演脚本尚未建立。")
        if not document.workspace_layers.videos_unlocked:
            changed_ids.update(("workspace_layers", "keyframe_plan", "video_plan"))
        preserved.update(("asset_history", "generation_history"))
    elif name.startswith("project."):
        raise ValueError("只读命令不需要影响预览。")
    else:
        raise ValueError(f"project.preview_impact 尚不支持命令：{name}。")

    writes = name != "generation.wait" and bool(changed_ids or invalidated)
    result: dict[str, object] = {
        "revision": document.revision,
        "command_name": name,
        "will_write": writes,
        "changed_ids": sorted(changed_ids),
        "invalidated": sorted(invalidated),
        "preserved": sorted(preserved),
        "high_impact": bool(invalidated - {"new_generation"}),
    }
    if name == "visual_production.unlock":
        result["location_advisory"] = location_unlock_advisory(document)
    return result


def location_unlock_advisory(document) -> dict[str, object]:
    """解锁视觉生产前的地点绑定提示：不阻塞解锁，只列出尚未绑定的 Scene 与 Shot。"""
    scenes_without_location, shots_without_view = location_binding_gaps(document)
    if scenes_without_location or shots_without_view:
        message = (
            f"{len(scenes_without_location)} 个 Scene 尚未绑定地点、"
            f"{len(shots_without_view)} 个 Shot 尚未绑定机位视图；"
            "解锁不受影响，可稍后再规划地点以提升背景一致性。"
        )
    else:
        message = "全部 Scene 已绑定地点、已绑定地点的 Shot 均有机位视图。"
    return {
        "scenes_without_location": list(scenes_without_location),
        "shots_without_view": list(shots_without_view),
        "message": message,
    }


def _has_final_selection(document) -> bool:
    plan = document.final_assembly
    return plan is not None and (
        plan.selected_zh_asset_id is not None or plan.selected_en_asset_id is not None
    )
