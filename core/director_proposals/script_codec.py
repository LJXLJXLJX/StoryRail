from __future__ import annotations

import json

from core.director_proposals.schema_gen import (
    RECIPE_PARAMS_SCHEMA,
    ProposalError,
    generate_schema,
    parse_proposal,
)
from core.director_proposals.script import (
    StructuredDirectorScriptProposal,
    StructuredDirectorScriptRevisionProposal,
    StructuredReferenceCharacter,
)

_ID_SCHEMA = {
    "anyOf": [
        {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        {"type": "null"},
    ]
}
# 对白说话者二选一：引用库角色 ID，或 character_id=null 加引用库外说话者称呼。
_DIALOGUE_CHARACTER_SCHEMA = _ID_SCHEMA
_DIALOGUE_SPEAKER_SCHEMA = {
    "anyOf": [{"type": "string", "minLength": 1, "maxLength": 60}, {"type": "null"}]
}
_BOUNDARY_REASONS = [
    "model_constraint",
    "continuity_anchor",
    "control_boundary",
    "failure_cost",
]


def _content_overrides(prefix: str) -> dict[str, dict[str, object]]:
    p = f"{prefix}." if prefix else ""
    segment = f"{p}shots[].segments[]"
    cue = f"{p}narration_cues[]"
    return {
        f"{p}driver": {"enum": ["narration", "drama"], "__required__": True},
        f"{p}title": {"minLength": 1, "maxLength": 300},
        f"{p}summary": {"minLength": 1, "maxLength": 4_000},
        f"{p}setting": {"minLength": 1, "maxLength": 4_000},
        f"{p}shots[].visible_character_ids": {
            "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"}
        },
        f"{p}shots[].composition": {"minLength": 1, "maxLength": 4_000},
        f"{p}shots[].camera_movement": {"minLength": 1, "maxLength": 2_000},
        f"{p}shots[].action": {"minLength": 1, "maxLength": 4_000},
        f"{p}shots[].audio_direction": {"maxLength": 2_000},
        f"{p}shots[].segments": {"minItems": 1},
        f"{segment}.duration_estimate_seconds": {"minimum": 0.2},
        f"{segment}.action": {"minLength": 1, "maxLength": 4_000},
        f"{segment}.dialogue_lines[].character_id": _DIALOGUE_CHARACTER_SCHEMA,
        f"{segment}.dialogue_lines[].speaker_label": _DIALOGUE_SPEAKER_SCHEMA,
        f"{segment}.dialogue_lines[].text": {"minLength": 1, "maxLength": 2_000},
        f"{segment}.dialogue_lines[].delivery": {"maxLength": 1_000},
        f"{segment}.boundary_from_previous.reason": {"enum": _BOUNDARY_REASONS},
        f"{segment}.boundary_from_previous.continuity_instruction": {
            "minLength": 1,
            "maxLength": 2_000,
        },
        f"{p}narration_cues": {"maxItems": 1},
        f"{cue}.text": {"minLength": 1, "maxLength": 4_000},
        f"{cue}.start_shot_index": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        f"{cue}.end_shot_index": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        f"{cue}.seed": {"minimum": 0, "maximum": 2**63 - 1},
        f"{cue}.zh.recipe_params": RECIPE_PARAMS_SCHEMA,
        f"{cue}.en.recipe_params": RECIPE_PARAMS_SCHEMA,
    }


_OUTPUT_OVERRIDES = {"scenes": {"minItems": 1}, **_content_overrides("scenes[]")}
_OUTPUT_SCHEMA = generate_schema(StructuredDirectorScriptProposal, _OUTPUT_OVERRIDES)

_REVISION_OVERRIDES: dict[str, dict[str, object]] = {
    "reply_markdown": {"minLength": 1, "maxLength": 10_000},
    "scenes": {"__exclude__": True},
    "operations": {"__required__": True},
    "operations[].operation": {
        "enum": [
            "replace_scene",
            "insert_scene",
            "delete_scene",
            "move_scene",
            "replace_segment",
        ]
    },
}
for _field in ("scene_id", "after_scene_id", "shot_id"):
    _REVISION_OVERRIDES[f"operations[].{_field}"] = {
        **_ID_SCHEMA,
        "__required__": True,
    }
for _field in ("scene", "segment"):
    _REVISION_OVERRIDES[f"operations[].{_field}"] = {"__required__": True}
for _prefix in ("operations[].scene",):
    _REVISION_OVERRIDES.update(_content_overrides(_prefix))
for _path in (
    "operations[].scene.id",
    "operations[].scene.shots[].id",
    "operations[].scene.shots[].segments[].id",
    "operations[].scene.narration_cues[].id",
    "operations[].segment.id",
):
    _REVISION_OVERRIDES[_path] = _ID_SCHEMA
_REVISION_OVERRIDES.update(
    {
        "operations[].segment.duration_estimate_seconds": {"minimum": 0.2},
        "operations[].segment.action": {"minLength": 1, "maxLength": 4_000},
        "operations[].segment.dialogue_lines[].character_id": _DIALOGUE_CHARACTER_SCHEMA,
        "operations[].segment.dialogue_lines[].speaker_label": _DIALOGUE_SPEAKER_SCHEMA,
        "operations[].segment.dialogue_lines[].text": {"minLength": 1, "maxLength": 2_000},
        "operations[].segment.dialogue_lines[].delivery": {"maxLength": 1_000},
        "operations[].segment.boundary_from_previous.reason": {"enum": _BOUNDARY_REASONS},
        "operations[].segment.boundary_from_previous.continuity_instruction": {
            "minLength": 1,
            "maxLength": 2_000,
        },
    }
)
_REVISION_OUTPUT_SCHEMA = generate_schema(
    StructuredDirectorScriptRevisionProposal, _REVISION_OVERRIDES
)


def parse_structured_director_script_proposal(
    raw_response: str,
) -> StructuredDirectorScriptProposal:
    try:
        return parse_proposal(
            raw_response,
            _OUTPUT_SCHEMA,
            StructuredDirectorScriptProposal,
            domain="script",
        )
    except ProposalError as exc:
        if "narration_cues" in exc.message and "最多允许 1 个元素" in exc.message:
            raise ProposalError("script", exc.code, "每个 Scene 最多只能有一段旁白。") from exc
        raise ProposalError("script", exc.code, exc.message) from exc


def parse_structured_director_script_revision(
    raw_response: str,
) -> StructuredDirectorScriptRevisionProposal:
    try:
        return parse_proposal(
            raw_response,
            _REVISION_OUTPUT_SCHEMA,
            StructuredDirectorScriptRevisionProposal,
            domain="script",
        )
    except ProposalError as exc:
        raise ProposalError("script", exc.code, exc.message) from exc


def _script_revision_context(
    *,
    director_plan_markdown: str,
    characters: tuple[StructuredReferenceCharacter, ...],
    current_script_json: str,
    target_scene_ids: tuple[str, ...],
    project_revision: int,
    script_revision: int,
) -> dict[str, object]:
    try:
        state = json.loads(current_script_json)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("结构化导演脚本状态不是合法 JSON。") from exc
    if (
        not isinstance(state, dict)
        or set(state) != {"scenes"}
        or not isinstance(state["scenes"], list)
    ):
        raise ValueError("结构化导演脚本状态缺少 scenes。")
    scenes = [item for item in state["scenes"] if isinstance(item, dict)]
    scene_ids = {item.get("id") for item in scenes}
    if not set(target_scene_ids) <= scene_ids:
        raise ValueError("结构化导演脚本局部修改包含不存在的目标 Scene。")
    target_set = set(target_scene_ids)
    scoped_scenes = (
        [scene for scene in scenes if scene.get("id") in target_set] if target_scene_ids else scenes
    )
    context: dict[str, object] = {
        "project_revision": project_revision,
        "script_revision": script_revision,
        "scope": {
            "target_scene_ids": list(target_scene_ids),
            "must_not_modify_other_scenes": bool(target_scene_ids),
        },
        "outline": [
            {
                "ordinal": scene_number,
                "id": scene.get("id"),
                "title": scene.get("title"),
                "shots": [
                    {
                        "ordinal": shot_number,
                        "id": shot.get("id"),
                        "segment_ids": [
                            segment.get("id")
                            for segment in shot.get("segments", [])
                            if isinstance(segment, dict)
                        ],
                    }
                    for shot_number, shot in enumerate(scene.get("shots", []), start=1)
                    if isinstance(shot, dict)
                ],
            }
            for scene_number, scene in enumerate(scenes, start=1)
        ],
        "scenes": scoped_scenes,
        "characters": _serialize_references(characters),
    }
    if not target_scene_ids:
        context["director_plan_markdown"] = director_plan_markdown
    return context


def _serialize_references(
    characters: tuple[StructuredReferenceCharacter, ...],
) -> dict[str, list[dict[str, object]]]:
    return {
        "characters": [
            {
                "id": item.id,
                "name": item.name,
                "visual_description": item.visual_description,
                "looks": list(item.looks),
            }
            for item in characters
        ],
    }
