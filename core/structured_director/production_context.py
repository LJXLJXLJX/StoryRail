from __future__ import annotations

import json
import re

from core.director_commands.context_scope import _relevant_scene_indexes

from .codec.keyframe import serialize_character_references
from .keyframe_requests import _keyframe_batch_ids
from .models import (
    Keyframe,
    ReferenceGenerationPhase,
    Scene,
    SegmentKeyframes,
    StructuredDirectorDocument,
)
from .narration_timing import (
    narration_visual_duration_seconds,
    narration_visual_tail_seconds,
)
from .reads.read_tools import _json_value
from .reads.semantic_projection import PROJECTION_VERSION, build_semantic_tree

_TERMINAL_PHASES = {
    ReferenceGenerationPhase.SUCCEEDED,
    ReferenceGenerationPhase.FAILED,
    ReferenceGenerationPhase.CANCELLED,
    ReferenceGenerationPhase.SUBMISSION_UNCERTAIN,
}


def _script_json(scenes: tuple[Scene, ...], document: StructuredDirectorDocument) -> str:
    tree = build_semantic_tree(document, tuple(scene.id for scene in scenes), full_text=True)
    by_id = {scene.id: scene for scene in scenes}
    all_scenes = document.director_script.scenes if document.director_script is not None else ()
    for scene in tree["scenes"]:
        source = by_id[scene["id"]]
        visual_tail_seconds = narration_visual_tail_seconds(all_scenes, source.id)
        scene["narration_timing"] = [
            _narration_timing(cue, all_scenes, source, visual_tail_seconds)
            for cue in scene["narration_cues"]
        ]
        cues = {cue.id: cue for cue in source.narration_cues}
        for cue in scene["narration_cues"]:
            original = cues[cue["id"]]
            cue.clear()
            cue.update(zh=None, en=None)
            cue.update(
                id=original.id,
                **{
                    language.value: {
                        "text": track.text,
                        "seed": track.seed,
                        "recipe_params": track.recipe_params.to_json(),
                    }
                    for language, track in original.tracks
                },
            )
    # 专业脚本契约保留精确字段；元数据留在 envelope，不混入可回传的 entity。
    tree["provenance"] = {item["id"]: item["provenance"] for item in tree["scenes"]}
    scene_fields = {
        "id",
        "title",
        "summary",
        "setting",
        "driver",
        "narration_cues",
        "narration_timing",
        "shots",
        "segments",
    }
    shot_fields = {
        "id",
        "visible_character_ids",
        "composition",
        "camera_movement",
        "action",
        "audio_direction",
        "transition_in",
    }
    segment_fields = {
        "id",
        "shot_ids",
        "duration_estimate_seconds",
        "action",
        "dialogue_lines",
        "boundary_from_previous",
    }
    cue_fields = {"id", "zh", "en"}
    for scene in tree["scenes"]:
        for shot in scene["shots"]:
            for key in set(shot) - shot_fields:
                del shot[key]
        for segment in scene["segments"]:
            for key in set(segment) - segment_fields:
                del segment[key]
        for cue in scene["narration_cues"]:
            for key in set(cue) - cue_fields:
                del cue[key]
        for key in set(scene) - scene_fields:
            del scene[key]
    return json.dumps(tree, ensure_ascii=False, separators=(",", ":"))


def _narration_timing(cue: dict, all_scenes, source: Scene, visual_tail_seconds: float) -> dict:
    """双语旁白的规划时长：两种语言已选音频都就绪时取较长的一条。"""
    durations = {
        language: cue[language]["duration_seconds"]
        for language in ("zh", "en")
        if cue.get(language) is not None
    }
    ready = all(value is not None for value in durations.values())
    duration = max(durations.values()) if ready else None
    return {
        "cue_id": cue["id"],
        **{
            language: None
            if language not in durations
            else {
                "selected_audio_asset_id": cue[language]["selected_audio_asset_id"],
                "duration_seconds": durations[language],
            }
            for language in ("zh", "en")
        },
        "timing_language": (None if not ready else max(durations, key=durations.get)),
        "duration_seconds": duration,
        "visual_tail_seconds": visual_tail_seconds,
        "minimum_duration_seconds": (
            None
            if source.driver != "narration" or duration is None
            else narration_visual_duration_seconds(all_scenes, source.id, duration)
        ),
    }


def _director_recent_scene_ids(
    document: StructuredDirectorDocument,
) -> tuple[str, ...]:
    """Resolve the latest conversation Scene mention against current Core facts."""
    script = document.director_script
    if script is None:
        return ()
    scenes = script.scenes
    scene_ids = {scene.id for scene in scenes}
    for directive in reversed(document.director_directives):
        message = directive.raw_user_request
        resolved: set[str] = set(re.findall(r"[0-9a-f]{32}", message.casefold())) & scene_ids
        ordinals = [
            int(match.group(1))
            for pattern in (
                r"(?:scene|场景)\s*[-_#]?\s*0*(\d+)",
                r"第\s*0*(\d+)\s*个?\s*场景",
            )
            for match in re.finditer(pattern, message, re.IGNORECASE)
        ]
        resolved.update(
            scenes[ordinal - 1].id for ordinal in ordinals if 1 <= ordinal <= len(scenes)
        )
        if scenes and re.search(
            r"(?:最后(?:一个|个)?|最末(?:一个|个)?)\s*(?:scene|场景)",
            message,
            re.IGNORECASE,
        ):
            resolved.add(scenes[-1].id)
        lowered = message.casefold()
        resolved.update(
            scene.id for scene in scenes if scene.title and scene.title.casefold() in lowered
        )
        if resolved:
            return tuple(scene.id for scene in scenes if scene.id in resolved)
    return ()


def _production_state_json(document: StructuredDirectorDocument) -> str:
    """显式全项目生产检查；在线 Director 使用带消息 scope 的入口。"""
    return _director_state_json(document)


def _director_state_json(
    document: StructuredDirectorDocument,
    *,
    user_message: str | None = None,
) -> str:
    """先用轻量 ID 索引定位，再从共源投影构造相关 Scene，避免全量正文/历史展开。"""
    script = document.director_script
    scenes = () if script is None else script.scenes
    bindings = (
        {}
        if document.keyframe_plan is None
        else {item.segment_id: item for item in document.keyframe_plan.segments}
    )
    frames = (
        {}
        if document.keyframe_plan is None
        else {item.id: item for item in document.keyframe_plan.keyframes}
    )
    videos = (
        {}
        if document.video_plan is None
        else {item.segment_id: item for item in document.video_plan.segments}
    )
    locations = {item.id: item for item in document.location_library.locations}
    index = [
        {
            "id": scene.id,
            "title": scene.title,
            "shots": [{"id": shot.id} for shot in scene.shots],
            "segments": [
                {
                    "id": segment.id,
                    "frames": [
                        {"id": frame_id}
                        for frame_id in (
                            (
                                bindings[segment.id].start_keyframe_id,
                                bindings[segment.id].end_keyframe_id,
                            )
                            if segment.id in bindings
                            else ()
                        )
                    ],
                }
                for segment in scene.segments
            ],
            "cues": [{"id": cue.id} for cue in scene.narration_cues],
        }
        for scene in scenes
    ]
    generations = [{"id": item.id, "target_id": item.target_id} for item in document.generations]
    indexes = (
        tuple(range(len(scenes)))
        if user_message is None
        else _relevant_scene_indexes(
            user_message,
            index,
            generations,
            list(_director_recent_scene_ids(document)),
        )
    )
    if (
        not indexes
        and user_message is not None
        and re.search(
            r"全部|全项目|所有|\ball\b",
            user_message,
            re.IGNORECASE,
        )
    ):
        indexes = tuple(range(len(scenes)))
    target_ids = tuple(scenes[i].id for i in indexes)
    tree = build_semantic_tree(document, target_ids) if target_ids else {"scenes": []}
    by_id = {scene["id"]: scene for scene in tree["scenes"]}
    include_text = user_message is None or bool(
        re.search(
            r"提示词|prompt|h3|正文",
            user_message,
            re.IGNORECASE,
        )
    )
    relevant_targets = set()
    result_scenes = []
    for ordinal, scene in enumerate(scenes, 1):
        if scene.id not in by_id:
            # 非目标 Scene 只提供导航，不带正文、子节点或生产历史。
            result_scenes.append(
                {
                    "id": scene.id,
                    "title": scene.title,
                    "driver": scene.driver,
                    "ordinal": ordinal,
                    "shots": index[ordinal - 1]["shots"],
                    "segments": index[ordinal - 1]["segments"],
                    "shot_count": len(scene.shots),
                }
            )
            continue
        item = by_id[scene.id]
        item["ordinal"] = ordinal
        relevant_targets.add(scene.id)
        relevant_targets.update(cue.id for cue in scene.narration_cues)
        location = None if scene.location_id is None else locations.get(scene.location_id)
        item["location"] = (
            None
            if location is None
            else {
                "id": location.id,
                "name": location.name,
                "state_id": scene.state_id,
                "images": [
                    {
                        "id": image.id,
                        "name": image.name,
                        "kind": image.kind.value,
                        "description": image.description,
                        "selected_asset_id": image.selected_asset_id,
                    }
                    for image in location.images
                ],
                **({"description": location.description} if include_text else {}),
            }
        )
        relevant_targets.update(shot["id"] for shot in item["shots"])
        for segment in item["segments"]:
            segment_id = segment["id"]
            relevant_targets.add(segment_id)
            if segment_id in bindings:
                binding = bindings[segment_id]
                state = _production_keyframe_state(binding, frames)
                for slot in ("start", "end"):
                    if state[slot] is None:
                        continue
                    relevant_targets.add(state[slot]["id"])
                    if not include_text:
                        state[slot].pop("prompt_text", None)
                segment["keyframes"] = state
            video = videos.get(segment_id)
            if video is not None:
                segment["video"] = {
                    "active_recipe": video.active_recipe,
                    "recipes": video.recipes.to_json(),
                    "selected_asset_id": video.selected_asset_id,
                    "upscaled_asset_id": video.upscaled_asset_id,
                    **({"prompt_text": video.prompt_text} if include_text else {}),
                }
        result_scenes.append(item)
    run = document.active_director_run
    waiting_ids = set(() if run is None else run.cursor.waiting_generation_ids)
    value = {
        "projection_version": PROJECTION_VERSION,
        "project_id": document.project_id,
        "scope": {"scene_ids": list(target_ids)},
        "scope_source": "explicit_full_read"
        if user_message is None
        else "current_message_or_recent_directive",
        "text_mode": "preview",
        "text_preview_characters": 240,
        "aspect_ratio": document.aspect_ratio.value,
        "script_revision": None if script is None else script.revision,
        "workflow_status": document.status.value,
        "agent_run_status": None if run is None else run.status.value,
        "recent_scene_ids": list(_director_recent_scene_ids(document)),
        "keyframe_batch_target_ids": list(_keyframe_batch_ids(document) or ()),
        "workspace_layers": _json_value(document.workspace_layers),
        "final_assembly": None
        if document.final_assembly is None
        else {
            "source_script_revision": document.final_assembly.source_script_revision,
            "selected_zh_asset_id": document.final_assembly.selected_zh_asset_id,
            "selected_en_asset_id": document.final_assembly.selected_en_asset_id,
        },
        "reference_library": {
            "characters": [
                {
                    "id": item.id,
                    "name": item.name,
                    "voice_reference_asset_id": item.voice_reference_asset_id,
                }
                for item in document.reference_library.characters
            ]
        },
        "asset_count": len(document.assets),
        "scenes": result_scenes,
        "generations": [
            {
                "id": item.id,
                "kind": item.kind.value,
                "operation": item.operation.value,
                "target_id": item.target_id,
                "phase": item.phase.value,
                "output_asset_id": item.output_asset_id,
                "retry_of": item.retry_of,
            }
            for item in document.generations
            if item.id in waiting_ids
            or item.phase not in _TERMINAL_PHASES
            or (item.target_id in relevant_targets and not item.dismissed)
        ],
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _production_keyframe_state(
    binding: SegmentKeyframes,
    keyframe_by_id: dict[str, Keyframe],
) -> dict[str, object]:
    def frame(keyframe_id: str) -> dict[str, object]:
        item = keyframe_by_id[keyframe_id]
        return {
            "id": item.id,
            "owner_segment_id": item.owner_segment_id,
            "predecessor_keyframe_id": item.predecessor_keyframe_id,
            "prompt_text": item.prompt_text,
            "visible_character_ids": list(item.visible_character_ids),
            "character_references": serialize_character_references(item),
            "selected_asset_id": item.selected_asset_id,
        }

    return {
        "start_enabled": binding.start_enabled,
        "end_enabled": binding.end_enabled,
        "start": frame(binding.start_keyframe_id) if binding.start_enabled else None,
        "end": frame(binding.end_keyframe_id) if binding.end_enabled else None,
        "reference_asset_ids": list(binding.reference_asset_ids),
    }
