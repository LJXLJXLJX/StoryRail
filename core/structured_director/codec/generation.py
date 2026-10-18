"""文档编解码：generation 域的 parse/serialize 函数对。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.model_providers.manifest import ProviderSnapshot
from core.model_providers.recipe import RecipeParams

from ..models import (
    GenerationOperation,
    NarrationLanguage,
    PanoramaCaptureRequest,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from ..video_contracts import VideoFrameRequest, VideoInputSnapshot, parse_video_value
from ._shared import (
    _boolean,
    _number,
    _optional_integer,
    _optional_number,
    _optional_string,
    _string,
    _string_list,
)

_GENERATION_FIELDS = {
    "id",
    "kind",
    "operation",
    "target_id",
    "phase",
    "message",
    "prompt_text",
    "input_asset_ids",
    "sample_text",
    "seed",
    "duration_seconds",
    "plugin_id",
    "plugin_version",
    "external_id",
    "output_asset_id",
    "error_code",
    "cancellation_requested",
    "retry_of",
    "dismissed",
    "video_frame_request",
    "video_input_snapshot",
    "language",
    "provider_snapshot",
    "recipe_params",
}

_GENERATION_AUDIT_FIELDS = {"created_at", "updated_at"}
# 只在有值时写出的可选键。
_GENERATION_OPTIONAL_FIELDS = {"aspect_ratio", "panorama_capture_request"}


def _serialize_generation(generation: ReferenceGeneration) -> dict[str, Any]:
    value = {
        "id": generation.id,
        "kind": generation.kind.value,
        "operation": generation.operation.value,
        "target_id": generation.target_id,
        "phase": generation.phase.value,
        "message": generation.message,
        "prompt_text": generation.prompt_text,
        "input_asset_ids": list(generation.input_asset_ids),
        "sample_text": generation.sample_text,
        "seed": generation.seed,
        "duration_seconds": generation.duration_seconds,
        "plugin_id": generation.plugin_id,
        "plugin_version": generation.plugin_version,
        "external_id": generation.external_id,
        "output_asset_id": generation.output_asset_id,
        "error_code": generation.error_code,
        "cancellation_requested": generation.cancellation_requested,
        "retry_of": generation.retry_of,
        "dismissed": generation.dismissed,
        "video_frame_request": asdict(generation.video_frame_request)
        if generation.video_frame_request
        else None,
        "video_input_snapshot": asdict(generation.video_input_snapshot)
        if generation.video_input_snapshot
        else None,
        "language": None if generation.language is None else generation.language.value,
        "provider_snapshot": (
            None if generation.provider_snapshot is None else generation.provider_snapshot.to_json()
        ),
        "recipe_params": generation.recipe_params.to_json(),
    }
    # 只有指定了非项目画幅的图片 Generation 才写出该键；未写出即跟随项目画幅。
    if generation.aspect_ratio is not None:
        value["aspect_ratio"] = generation.aspect_ratio
    if generation.panorama_capture_request is not None:
        value["panorama_capture_request"] = asdict(generation.panorama_capture_request)
    if generation.created_at is not None or generation.updated_at is not None:
        value.update(
            {
                "created_at": generation.created_at,
                "updated_at": generation.updated_at,
            }
        )
    return value


def _parse_generation(value: object) -> ReferenceGeneration:
    if not isinstance(value, dict) or set(value) - _GENERATION_OPTIONAL_FIELDS not in {
        frozenset(_GENERATION_FIELDS),
        frozenset(_GENERATION_FIELDS | _GENERATION_AUDIT_FIELDS),
    }:
        raise ValueError("project.json 包含缺失或未声明的字段。")
    fields = value
    return ReferenceGeneration(
        id=_string(fields["id"], "generation.id"),
        kind=ReferenceGenerationKind(_string(fields["kind"], "generation.kind")),
        video_frame_request=parse_video_value(VideoFrameRequest, fields["video_frame_request"]),
        video_input_snapshot=parse_video_value(VideoInputSnapshot, fields["video_input_snapshot"]),
        operation=GenerationOperation(_string(fields["operation"], "generation.operation")),
        target_id=_string(fields["target_id"], "generation.target_id"),
        phase=ReferenceGenerationPhase(_string(fields["phase"], "generation.phase")),
        progress=1.0 if fields["phase"] == "succeeded" else 0.0,
        message=_string(fields["message"], "generation.message"),
        prompt_text=_string(fields["prompt_text"], "generation.prompt_text"),
        input_asset_ids=_string_list(fields["input_asset_ids"], "generation.input_asset_ids"),
        sample_text=_optional_string(fields["sample_text"], "generation.sample_text"),
        seed=_optional_integer(fields["seed"], "generation.seed"),
        duration_seconds=_optional_number(
            fields["duration_seconds"], "generation.duration_seconds"
        ),
        plugin_id=_optional_string(fields["plugin_id"], "generation.plugin_id"),
        plugin_version=_optional_integer(fields["plugin_version"], "generation.plugin_version"),
        external_id=_optional_string(fields["external_id"], "generation.external_id"),
        output_asset_id=_optional_string(fields["output_asset_id"], "generation.output_asset_id"),
        error_code=_optional_string(fields["error_code"], "generation.error_code"),
        cancellation_requested=_boolean(
            fields["cancellation_requested"], "generation.cancellation_requested"
        ),
        retry_of=_optional_string(fields["retry_of"], "generation.retry_of"),
        dismissed=_boolean(fields["dismissed"], "generation.dismissed"),
        created_at=_optional_string(fields.get("created_at"), "generation.created_at"),
        updated_at=_optional_string(fields.get("updated_at"), "generation.updated_at"),
        language=(
            None
            if fields["language"] is None
            else NarrationLanguage(_string(fields["language"], "generation.language"))
        ),
        provider_snapshot=(
            None
            if fields["provider_snapshot"] is None
            else ProviderSnapshot.from_json(fields["provider_snapshot"])
        ),
        recipe_params=RecipeParams.from_json(fields["recipe_params"], "generation.recipe_params"),
        aspect_ratio=_string(fields["aspect_ratio"], "generation.aspect_ratio")
        if "aspect_ratio" in fields
        else None,
        panorama_capture_request=_parse_capture_request(fields.get("panorama_capture_request")),
    )


def _parse_capture_request(value: object) -> PanoramaCaptureRequest | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(
        PanoramaCaptureRequest.__dataclass_fields__
    ):
        raise ValueError("generation.panorama_capture_request 包含缺失或未声明字段。")
    return PanoramaCaptureRequest(
        panorama_asset_id=_string(
            value["panorama_asset_id"], "panorama_capture_request.panorama_asset_id"
        ),
        yaw_deg=_number(value["yaw_deg"], "panorama_capture_request.yaw_deg"),
        pitch_deg=_number(value["pitch_deg"], "panorama_capture_request.pitch_deg"),
        hfov_deg=_number(value["hfov_deg"], "panorama_capture_request.hfov_deg"),
        aspect_ratio=_string(value["aspect_ratio"], "panorama_capture_request.aspect_ratio"),
    )
