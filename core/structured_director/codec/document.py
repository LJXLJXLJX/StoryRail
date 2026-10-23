"""文档编解码：document 域的 parse/serialize 函数对（纯移动，语义/JSON key/错误消息不变）。"""

from __future__ import annotations

from typing import Any

from core.application.requests import ApplicationRequest
from core.project_settings import ProjectAspectRatio

from ..models import (
    ReferenceLibrary,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
    require_known_reference_location_images,
)
from ..models._shared import parse_narration_languages
from ..schema import (
    PROJECT_SCHEMA_VERSION,
)
from ._shared import _boolean, _exact_object, _integer, _object_list, _string
from .asset import _parse_asset, _serialize_asset
from .dialogue import _parse_dialogue_plan, _serialize_dialogue_plan
from .final import (
    _parse_final_approval,
    _parse_final_assembly,
    _serialize_final_approval,
    _serialize_final_assembly,
)
from .generation import _parse_generation, _serialize_generation
from .keyframe import _parse_keyframe_plan, _serialize_keyframe_plan
from .location import _parse_location_library, serialize_location_library
from .reference import _parse_character, _parse_narrator, _serialize_character, _serialize_narrator
from .run import (
    _parse_director_directive,
    _parse_director_run,
    _serialize_director_directive,
    _serialize_director_run,
)
from .script import (
    _parse_capability_gap_alert,
    _parse_director_script,
    _parse_pending_narration_edit,
    _parse_pending_script_edit,
    _serialize_capability_gap_alert,
    _serialize_director_script,
)
from .video import _parse_video_plan, _serialize_video_plan


def serialize_document(document: StructuredDirectorDocument) -> dict[str, Any]:
    return {
        "schema_version": document.schema_version,
        "project_id": document.project_id,
        "revision": document.revision,
        "title": document.title,
        "aspect_ratio": document.aspect_ratio.value,
        "director_plan_markdown": document.director_plan_markdown,
        "narration_languages": [language.value for language in document.narration_languages],
        "assets": [_serialize_asset(item) for item in document.assets],
        "generations": [_serialize_generation(item) for item in document.generations],
        "application_requests": [item.to_dict() for item in document.application_requests],
        "structured_director": {
            "status": document.status.value,
            "workspace_layers": {
                "narration_unlocked": document.workspace_layers.narration_unlocked,
                "keyframes_unlocked": document.workspace_layers.keyframes_unlocked,
                "videos_unlocked": document.workspace_layers.videos_unlocked,
                "final_assembly_unlocked": (document.workspace_layers.final_assembly_unlocked),
            },
            "reference_library": {
                "characters": [
                    _serialize_character(item) for item in document.reference_library.characters
                ],
                "narrator": (
                    None
                    if document.reference_library.narrator is None
                    else _serialize_narrator(document.reference_library.narrator)
                ),
            },
            "director_script": (
                None
                if document.director_script is None
                else _serialize_director_script(document.director_script)
            ),
            "pending_script_edit": (
                None
                if document.pending_script_edit is None
                else {
                    "base_script_revision": document.pending_script_edit.base_script_revision,
                    "user_message": document.pending_script_edit.user_message,
                }
            ),
            "pending_narration_edit": (
                None
                if document.pending_narration_edit is None
                else {
                    "base_script_revision": document.pending_narration_edit.base_script_revision,
                    "user_message": document.pending_narration_edit.user_message,
                }
            ),
            "dialogue_plan": (
                None
                if document.dialogue_plan is None
                else _serialize_dialogue_plan(document.dialogue_plan)
            ),
            "location_library": serialize_location_library(document.location_library),
            "keyframe_plan": (
                None
                if document.keyframe_plan is None
                else _serialize_keyframe_plan(document.keyframe_plan)
            ),
            "video_plan": (
                None if document.video_plan is None else _serialize_video_plan(document.video_plan)
            ),
            "final_assembly": (
                None
                if document.final_assembly is None
                else _serialize_final_assembly(document.final_assembly)
            ),
            "final_approval": (
                None
                if document.final_approval is None
                else _serialize_final_approval(document.final_approval)
            ),
            "capability_gap_alerts": [
                _serialize_capability_gap_alert(item) for item in document.capability_gap_alerts
            ],
            "director_runs": [_serialize_director_run(item) for item in document.director_runs],
            "director_directives": [
                _serialize_director_directive(item) for item in document.director_directives
            ],
        },
    }


def _parse_document(value: object) -> StructuredDirectorDocument:
    if not isinstance(value, dict) or value.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise ValueError("project.json schema_version 不受支持，请新建项目。")
    root = _exact_object(
        value,
        {
            "schema_version",
            "project_id",
            "revision",
            "title",
            "aspect_ratio",
            "director_plan_markdown",
            "narration_languages",
            "assets",
            "generations",
            "application_requests",
            "structured_director",
        },
    )
    structured = _exact_object(
        root["structured_director"],
        {
            "status",
            "workspace_layers",
            "reference_library",
            "director_script",
            "pending_script_edit",
            "pending_narration_edit",
            "dialogue_plan",
            "location_library",
            "keyframe_plan",
            "video_plan",
            "final_assembly",
            "final_approval",
            "capability_gap_alerts",
            "director_runs",
            "director_directives",
        },
    )
    library = _exact_object(structured["reference_library"], {"characters", "narrator"})
    layers = _exact_object(
        structured["workspace_layers"],
        {
            "narration_unlocked",
            "keyframes_unlocked",
            "videos_unlocked",
            "final_assembly_unlocked",
        },
    )
    loaded_status = StructuredDirectorStatus(_string(structured["status"], "status"))
    try:
        document = StructuredDirectorDocument(
            schema_version=PROJECT_SCHEMA_VERSION,
            project_id=_string(root["project_id"], "project_id"),
            revision=_integer(root["revision"], "revision"),
            title=_string(root["title"], "title"),
            aspect_ratio=ProjectAspectRatio(_string(root["aspect_ratio"], "aspect_ratio")),
            director_plan_markdown=_string(
                root["director_plan_markdown"], "director_plan_markdown"
            ),
            narration_languages=parse_narration_languages(root["narration_languages"]),
            status=loaded_status,
            workspace_layers=WorkspaceLayers(
                narration_unlocked=_boolean(
                    layers["narration_unlocked"], "workspace_layers.narration_unlocked"
                ),
                keyframes_unlocked=_boolean(
                    layers["keyframes_unlocked"], "workspace_layers.keyframes_unlocked"
                ),
                videos_unlocked=_boolean(
                    layers["videos_unlocked"], "workspace_layers.videos_unlocked"
                ),
                final_assembly_unlocked=_boolean(
                    layers["final_assembly_unlocked"],
                    "workspace_layers.final_assembly_unlocked",
                ),
            ),
            reference_library=ReferenceLibrary(
                _object_list(library["characters"], _parse_character),
                None if library["narrator"] is None else _parse_narrator(library["narrator"]),
            ),
            assets=_object_list(root["assets"], _parse_asset),
            generations=_object_list(root["generations"], _parse_generation),
            director_script=(
                None
                if structured["director_script"] is None
                else _parse_director_script(structured["director_script"])
            ),
            pending_script_edit=(
                None
                if structured["pending_script_edit"] is None
                else _parse_pending_script_edit(structured["pending_script_edit"])
            ),
            pending_narration_edit=(
                None
                if structured["pending_narration_edit"] is None
                else _parse_pending_narration_edit(structured["pending_narration_edit"])
            ),
            dialogue_plan=(
                None
                if structured["dialogue_plan"] is None
                else _parse_dialogue_plan(structured["dialogue_plan"])
            ),
            location_library=_parse_location_library(structured["location_library"]),
            keyframe_plan=(
                None
                if structured["keyframe_plan"] is None
                else _parse_keyframe_plan(structured["keyframe_plan"])
            ),
            video_plan=(
                None
                if structured["video_plan"] is None
                else _parse_video_plan(structured["video_plan"])
            ),
            final_assembly=(
                None
                if structured["final_assembly"] is None
                else _parse_final_assembly(structured["final_assembly"])
            ),
            final_approval=(
                None
                if structured["final_approval"] is None
                else _parse_final_approval(structured["final_approval"])
            ),
            application_requests=_object_list(
                root["application_requests"], ApplicationRequest.parse
            ),
            capability_gap_alerts=_object_list(
                structured["capability_gap_alerts"],
                _parse_capability_gap_alert,
            ),
            director_runs=_object_list(structured["director_runs"], _parse_director_run),
            director_directives=_object_list(
                structured["director_directives"], _parse_director_directive
            ),
        )
        require_known_reference_location_images(document.keyframe_plan, document.location_library)
        return document
    except ValueError as exc:
        raise ValueError(f"project.json schema 不合法：{exc}") from exc
