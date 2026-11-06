"""把各 codec 的输出 schema 标成可生成的 TypeScript 类型。"""

from __future__ import annotations

import copy
import dataclasses
import types
import typing
from typing import Any

from core.director_proposals import (
    keyframe_codec,
    location_codec,
    narration_codec,
    script_codec,
)
from core.director_proposals import reference_library_codec as reference
from core.director_proposals import (
    video_prompt as h3_codec,
)
from core.director_proposals.keyframe import KeyframePlanProposal
from core.director_proposals.location import LocationPlanProposal
from core.director_proposals.narration import NarrationReviewProposal
from core.director_proposals.reference_library import ReferenceLibraryProposal
from core.director_proposals.script import (
    StructuredDirectorScriptProposal,
    StructuredDirectorScriptRevisionProposal,
)
from core.director_proposals.video_prompt import VideoPromptProposal


def proposal_schemas() -> dict[str, dict]:
    pairs = (
        (reference.REFERENCE_LIBRARY_OUTPUT_SCHEMA, ReferenceLibraryProposal),
        (script_codec._OUTPUT_SCHEMA, StructuredDirectorScriptProposal),
        (script_codec._REVISION_OUTPUT_SCHEMA, StructuredDirectorScriptRevisionProposal),
        (narration_codec._OUTPUT_SCHEMA, NarrationReviewProposal),
        (keyframe_codec._STATIC_OUTPUT_SCHEMA, KeyframePlanProposal),
        (location_codec.output_schema(), LocationPlanProposal),
        (h3_codec.OUTPUT_SCHEMA, VideoPromptProposal),
    )
    schemas: dict[str, dict] = {}
    for schema, model in pairs:
        annotated = annotate(schema, model)
        annotated["x-ts-name"] = model.__name__
        annotated["x-proposal"] = True
        schemas[model.__name__] = annotated
    return schemas


def annotate(schema: dict, model: Any) -> dict:
    copied = copy.deepcopy(schema)
    _annotate(copied, model)
    return copied


def _annotate(schema: dict, tp: Any) -> None:
    if not isinstance(schema, dict):
        return
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in {typing.Union, types.UnionType}:
        non_none = [arg for arg in args if arg is not type(None)]
        nodes = schema.get("anyOf", [schema])
        for node in nodes:
            if not isinstance(node, dict) or node.get("type") == "null":
                continue
            target = non_none[0] if len(non_none) == 1 else _matching_target(node, non_none)
            if target is not None:
                _annotate(node, target)
        return
    if isinstance(tp, type) and dataclasses.is_dataclass(tp) and schema.get("type") == "object":
        schema["x-ts-name"] = tp.__name__
        hints = typing.get_type_hints(tp)
        for name, field_schema in schema.get("properties", {}).items():
            if name in hints:
                _annotate(field_schema, hints[name])
        return
    if origin in {list, tuple} and args and isinstance(schema.get("items"), dict):
        _annotate(schema["items"], args[0])


def _matching_target(node: dict, candidates: list[Any]) -> Any | None:
    for candidate in candidates:
        origin = typing.get_origin(candidate)
        node_type = node.get("type")
        if isinstance(candidate, type) and dataclasses.is_dataclass(candidate):
            if node_type == "object":
                return candidate
            continue
        array_match = origin in {list, tuple} and node_type == "array"
        primitive = node_type in {"string", "integer", "number", "boolean"}
        if array_match or primitive:
            return candidate
    return candidates[0] if candidates else None
