"""确定性生产命令分发；不包含模型、会话或自然语言执行。"""

from .director_steps import (
    _production_command_options,
    _production_command_target_ids,
    _production_command_user_instruction,
    _ProductionCommandOutcome,
    _ProductionCommandRequest,
)
from .models import StructuredDirectorDocument


async def _execute_production_command_handler(
    service, document: StructuredDirectorDocument, request: _ProductionCommandRequest
) -> _ProductionCommandOutcome:
    command = request.command
    target_ids = _production_command_target_ids(command)
    _production_command_user_instruction(command)
    options = _production_command_options(command)
    updated = document
    reply_markdown: str | None = request.reply_markdown
    if command.name == "script.confirm":
        updated = await service.confirm_script(expected_revision=updated.revision)
    elif command.name == "narration.generate":
        language = options.get("language")
        if language is not None and language not in {"zh", "en"}:
            raise ValueError("narration.generate options.language 只允许 zh 或 en。")
        if target_ids:
            # 未指定语言时同一 Cue 的中英文各提交一次合成。
            languages = document.narration_languages if language is None else (language,)
            for cue_id in target_ids:
                for item in languages:
                    updated = await service.generate_narration(
                        cue_id=cue_id, language=item, expected_revision=updated.revision
                    )
        else:
            updated = await service.generate_narration_batch(expected_revision=updated.revision)
    elif command.name == "narration.select_candidate":
        updated = await service.select_narration_audio(
            cue_id=target_ids[0], generation_id=target_ids[1], expected_revision=updated.revision
        )
    elif command.name == "visual_production.unlock":
        updated = await service.unlock_visual_production(expected_revision=updated.revision)
    elif command.name == "keyframe.generate":
        if target_ids:
            for keyframe_id in target_ids:
                updated = await service.generate_keyframe(
                    keyframe_id=keyframe_id, expected_revision=updated.revision
                )
        else:
            updated = await service.generate_keyframe_batch(expected_revision=updated.revision)
    elif command.name in {"location.generate_master", "location.generate_view"}:
        if not target_ids:
            raise ValueError(f"{command.name} 必须指定目标 ID。")
        for target_id in target_ids:
            updated = await (
                service.generate_location_master(
                    location_id=target_id, expected_revision=updated.revision
                )
                if command.name == "location.generate_master"
                else service.generate_location_view(
                    view_id=target_id, expected_revision=updated.revision
                )
            )
    elif command.name == "video.generate":
        seed = options.get("seed")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise ValueError("seed 必须是整数或 null。")
        if seed is not None and len(target_ids) != 1:
            raise ValueError("指定 seed 时必须且只能生成一个 Segment。")
        targets = target_ids or tuple(
            item.segment_id
            for item in (updated.video_plan.segments if updated.video_plan else ())
            if item.selected_asset_id is None
        )
        for segment_id in targets:
            updated = await service._media.generate_segment_video(
                segment_id=segment_id, expected_revision=updated.revision, seed=seed
            )
    elif command.name == "video.upscale":
        targets = target_ids or tuple(
            item.segment_id
            for item in (updated.video_plan.segments if updated.video_plan else ())
            if item.selected_asset_id is not None and item.upscaled_asset_id is None
        )
        for segment_id in targets:
            updated = await service._media.upscale_segment_video(
                segment_id=segment_id, expected_revision=updated.revision
            )
    elif command.name == "keyframe.select_candidate":
        updated = await service.select_keyframe(
            keyframe_id=target_ids[0], asset_id=target_ids[1], expected_revision=updated.revision
        )
    elif command.name == "video.select_candidate":
        updated = await service.select_segment_video(
            segment_id=target_ids[0], asset_id=target_ids[1], expected_revision=updated.revision
        )
    elif command.name == "final.assemble":
        updated = await service.generate_final_video(expected_revision=updated.revision)
    elif command.name == "final.select_candidate":
        updated = await service.select_final_video(
            asset_id=target_ids[0], expected_revision=updated.revision
        )
    elif command.name == "final.approve":
        updated = await service.approve_final_video(expected_revision=updated.revision)
    else:
        raise ValueError(f"尚未注册生产 command handler：{command.name}。")
    return _ProductionCommandOutcome(updated, reply_markdown)
