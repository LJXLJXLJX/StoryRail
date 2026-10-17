"""Core HTTP 快照与设置响应的 JSON Schema。

枚举来自领域 StrEnum 或本文件里的唯一词表。`x-ts-*` 只指导 TypeScript 生成，
不会进入运行时校验。`x-ts-optional` 表示线协议必填、既有 TS 表面仍标成可选，
以便手写测试对象继续类型检查；解析器仍拒绝缺键。
"""

from __future__ import annotations

from core.model_providers.manifest import IMAGE_ASPECT_RATIOS, Capability, Role, Widget
from core.playground.models import RunPhase
from core.project_settings.models import ProjectAspectRatio
from core.structured_director.models import (
    AssetUsageReason,
    CapabilityGapResult,
    CapabilityGapStatus,
    DirectorRunKind,
    GenerationOperation,
    ImageAssetCategory,
    KeyframeEnvironmentMode,
    LocationKind,
    NarrationLanguage,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    SegmentBoundaryReason,
    StructuredDirectorStatus,
)

ID = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
NULL_ID = {"anyOf": [ID, {"type": "null"}]}
POSITIVE = {"type": "integer", "minimum": 1}
TEXT = {"type": "string", "minLength": 1, "x-trimmed-nonempty": True}
BOOL = {"type": "boolean"}

# Web 接受的动作词表。服务端只返回其中子集；这里不从 snapshot_view 反推，
# 以免把内部动作泄漏成前端允许值。
STRUCTURED_DIRECTOR_ACTIONS = (
    "confirm_reference_review",
    "edit_reference_library",
    "import_image_asset",
    "import_media_asset",
    "extract_video_frame",
    "generate_audio",
    "trim_audio",
    "apply_audio_effect",
    "separate_video_audio",
    "remix_video_audio",
    "delete_asset",
    "attach_reference_image",
    "upload_reference_voice",
    "observe_reference_generations",
    "edit_script",
    "confirm_script",
    "edit_narration",
    "generate_narration",
    "generate_narration_batch",
    "select_narration_audio",
    "unlock_visual_production",
    "edit_keyframe_references",
    "generate_keyframe",
    "generate_keyframe_batch",
    "select_keyframe",
    "generate_scene_animatic",
    "generate_scene_final",
    "edit_segment_video_plan",
    "generate_segment_video",
    "attach_segment_video_candidate",
    "select_segment_video",
    "upscale_segment_video",
    "generate_final_video",
    "select_final_video",
    "clear_final_selection",
    "approve_final_video",
    "reopen_video_production",
)
GENERATION_ACTIONS = (
    "attach_output",
    "select_look_sheet",
    "select_output",
    "select_narration_audio",
    "select_segment_video",
    "attach_upscaled_video",
    "select_final_video",
    "dismiss_history",
    "cancel",
    "retry",
)
ASSET_ACTIONS = ("audio_trim", "audio_effect", "audio_editor", "video_frame", "delete")
AUDIO_EFFECT_PRESETS = (
    "walkie_talkie",
    "military_radio",
    "weak_signal",
    "bad_signal",
    "dying_transmission",
)
MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp", "audio/wav", "video/mp4")
WORKSPACE_CAPABILITIES = ("narration", "keyframe", "video", "final")
ACTIVE_RUN_STATUSES = ("running", "waiting_user", "waiting_jobs")
AGENT_MESSAGE_ROLES = ("user", "agent", "system")
PROJECT_STATUSES = ("active", "needs_recovery")
# Playground 只返回这些动作；Web 不推断 run/Asset 还能做什么。
PLAYGROUND_RUN_ACTIONS = ("cancel", "retry", "dismiss", "set_note")
PLAYGROUND_ASSET_ACTIONS = ("delete", "copy_to_project", "video_frame", "pano_view")
PLAYGROUND_ASSET_ORIGIN_KINDS = ("imported", "run_output", "copied_from_project")
# 参数与 result 的形状由 capability 决定，这里只声明为任意 JSON 对象。
FREE_OBJECT = {"type": "object", "properties": {}, "additionalProperties": True}
# 插件设置值与 manifest 默认值：Core 已按 manifest 校验，Web 只渲染这些 JSON 标量。
SETTING_VALUE = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
        {"type": "array", "items": {"type": "number"}},
    ]
}


def _enum(values, alias: str | None = None, *, guard: str | None = None) -> dict:
    schema: dict = {"enum": [getattr(item, "value", item) for item in values]}
    if alias:
        schema["x-ts-alias"] = alias
    if guard:
        schema["x-guard"] = guard
    return schema


def _obj(properties: dict, required: list[str], **markers) -> dict:
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    schema.update(markers)
    return schema


def _ref(name: str) -> dict:
    return {"$ref": name}


def _array(items: dict, **kwargs) -> dict:
    return {"type": "array", "items": items, **kwargs}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def snapshot_schemas() -> dict[str, dict]:
    """名字 → schema。$ref 使用这些名字。"""
    schemas: dict[str, dict] = {
        "Id": ID,
        "AgentMessageRole": _enum(AGENT_MESSAGE_ROLES, "AgentMessageRole"),
        "ProjectStatus": _enum(PROJECT_STATUSES, "ProjectStatus"),
        "ProjectAspectRatio": _enum(ProjectAspectRatio, "ProjectAspectRatio"),
        "ProviderCapabilityId": _enum(Capability, "ProviderCapabilityId"),
        "ManifestWidget": _enum(Widget, "ManifestWidget"),
        "ManifestRole": _enum(Role, "ManifestRole"),
        "NarrationLanguage": _enum(NarrationLanguage, "NarrationLanguage"),
        "StructuredDirectorAction": _enum(
            STRUCTURED_DIRECTOR_ACTIONS,
            "StructuredDirectorAction",
            guard="isStructuredDirectorAction",
        ),
        "StructuredDirectorStatus": _enum(StructuredDirectorStatus, "StructuredDirectorStatus"),
        "DirectorRunKind": _enum(DirectorRunKind, "DirectorRunKind"),
        "ActiveDirectorRunStatus": _enum(ACTIVE_RUN_STATUSES),
        "SegmentBoundaryReason": _enum(SegmentBoundaryReason, "SegmentBoundaryReason"),
        "ImageOperation": _enum(("generate", "edit"), "ImageOperation"),
        "ImageAspectRatio": _enum(IMAGE_ASPECT_RATIOS, "ImageAspectRatio"),
        "AssetUsageReasonCode": _enum(AssetUsageReason, "AssetUsageReasonCode"),
        "ImageAssetCategory": _enum(ImageAssetCategory, "ImageAssetCategory"),
        "AssetAction": _enum(ASSET_ACTIONS, "AssetAction"),
        "AudioEffectPreset": _enum(AUDIO_EFFECT_PRESETS, "AudioEffectPreset"),
        "ReferenceGenerationKind": _enum(ReferenceGenerationKind, "ReferenceGenerationKind"),
        "GenerationOperation": _enum(GenerationOperation, "GenerationOperation"),
        "ReferenceGenerationPhase": _enum(
            ReferenceGenerationPhase,
            "ReferenceGenerationPhase",
            guard="isGenerationPhase",
        ),
        "ReferenceGenerationAction": _enum(
            GENERATION_ACTIONS,
            "ReferenceGenerationAction",
            guard="isReferenceGenerationAction",
        ),
        "MediaType": _enum(MEDIA_TYPES),
        "WorkspaceCapability": _enum(WORKSPACE_CAPABILITIES),
        "KeyframeEnvironmentMode": _enum(KeyframeEnvironmentMode, "KeyframeEnvironmentMode"),
        "LocationKind": _enum(LocationKind, "LocationKind"),
    }
    schemas.update(
        {
            "ProjectSummary": _obj(
                {
                    "id": ID,
                    "title": TEXT,
                    "aspect_ratio": _ref("ProjectAspectRatio"),
                    "updated_at": {"type": "string", "x-datetime": True},
                    "status": _ref("ProjectStatus"),
                },
                ["id", "title", "aspect_ratio", "updated_at", "status"],
                **{"x-ts-name": "ProjectSummary", "x-guard": "isProjectSummary"},
            ),
            "ProjectBootstrap": _obj(
                {"projects": _array(_ref("ProjectSummary"))},
                ["projects"],
                **{"x-ts-name": "ProjectBootstrap"},
            ),
            "ManifestOption": _obj(
                {"id": {"type": "string"}, "label": {"type": "string"}},
                ["id", "label"],
                **{"x-ts-name": "ManifestOption"},
            ),
            "ManifestField": _obj(
                {
                    "key": {"type": "string"},
                    "widget": _ref("ManifestWidget"),
                    "label": {"type": "string"},
                    "default": SETTING_VALUE,
                    "nullable": BOOL,
                    "advanced": BOOL,
                    "options": _array(_ref("ManifestOption")),
                    "minimum": _nullable({"type": "number"}),
                    "maximum": _nullable({"type": "number"}),
                    "max_length": _nullable({"type": "integer"}),
                    "min_length": _nullable({"type": "integer"}),
                    "dimension": _nullable({"type": "integer"}),
                    "component_labels": _array({"type": "string"}),
                    "role": _nullable(_ref("ManifestRole")),
                    "help": {"type": "string"},
                },
                [
                    "key",
                    "widget",
                    "label",
                    "default",
                    "nullable",
                    "advanced",
                    "options",
                    "minimum",
                    "maximum",
                    "max_length",
                    "min_length",
                    "dimension",
                    "component_labels",
                    "role",
                    "help",
                ],
                **{"x-ts-name": "ManifestField"},
            ),
            "ManifestSlot": _obj(
                {
                    "key": {"type": "string"},
                    "role": _ref("ManifestRole"),
                    "label": {"type": "string"},
                    "minimum": {"type": "integer", "minimum": 0},
                    "maximum": {"type": "integer", "minimum": 0},
                    "media_types": _array({"type": "string"}),
                    "duration_seconds": _nullable(_array({"type": "number"})),
                    "describe": {"enum": ["required", "optional", "none"]},
                    "unique": BOOL,
                    "namespace": _nullable({"type": "string"}),
                },
                [
                    "key",
                    "role",
                    "label",
                    "minimum",
                    "maximum",
                    "media_types",
                    "duration_seconds",
                    "describe",
                    "unique",
                    "namespace",
                ],
                **{"x-ts-name": "ManifestSlot"},
            ),
            "ManifestRecipe": _obj(
                {
                    "id": {"type": "string"},
                    "capability": _ref("ProviderCapabilityId"),
                    "label": {"type": "string"},
                    "slots": _array(_ref("ManifestSlot")),
                    "params": _array(_ref("ManifestField")),
                    "require_any": _array({"type": "string"}),
                    "label_namespaces": FREE_OBJECT,
                    "skills": _array({"type": "string"}),
                    "distinct_slots": _array({"type": "string"}),
                },
                [
                    "id",
                    "capability",
                    "label",
                    "slots",
                    "params",
                    "require_any",
                    "label_namespaces",
                    "skills",
                    "distinct_slots",
                ],
                **{"x-ts-name": "ManifestRecipe"},
            ),
            "ImagePromptConvention": _obj(
                {
                    "namespace": {"type": "string"},
                    "single_image_label": _nullable({"type": "string"}),
                    "aspect_ratio_in_prompt": {"type": "boolean"},
                },
                ["namespace", "single_image_label", "aspect_ratio_in_prompt"],
                **{"x-ts-name": "ImagePromptConvention"},
            ),
            "PluginManifest": _obj(
                {
                    "plugin_id": {"type": "string"},
                    "plugin_version": POSITIVE,
                    "label": {"type": "string"},
                    "settings": _array(_ref("ManifestField")),
                    "hints": FREE_OBJECT,
                    "recipes": _array(_ref("ManifestRecipe")),
                    "defaults": FREE_OBJECT,
                    "image_prompt": _nullable(_ref("ImagePromptConvention")),
                },
                [
                    "plugin_id",
                    "plugin_version",
                    "label",
                    "settings",
                    "hints",
                    "recipes",
                    "defaults",
                    "image_prompt",
                ],
                **{"x-ts-name": "PluginManifest"},
            ),
            "ProviderRecipeView": _obj(
                {
                    "capability": _ref("ProviderCapabilityId"),
                    "plugin_id": {"type": "string"},
                    "plugin_label": {"type": "string"},
                    "recipe": _ref("ManifestRecipe"),
                    "editable_params": _array(_ref("ManifestField")),
                    "settings_summary": {"type": "string"},
                    "hints": FREE_OBJECT,
                },
                [
                    "capability",
                    "plugin_id",
                    "plugin_label",
                    "recipe",
                    "editable_params",
                    "settings_summary",
                    "hints",
                ],
                **{"x-ts-name": "ProviderRecipeView"},
            ),
            "ProviderCandidate": _obj(
                {"plugin_id": {"type": "string"}, "label": {"type": "string"}},
                ["plugin_id", "label"],
                **{"x-ts-name": "ProviderCandidate"},
            ),
            "ProviderCapabilityView": _obj(
                {
                    "id": _ref("ProviderCapabilityId"),
                    "label": {"type": "string"},
                    "bound_plugin_id": _nullable({"type": "string"}),
                    "candidates": _array(_ref("ProviderCandidate")),
                    "message": _nullable({"type": "string"}),
                },
                ["id", "label", "bound_plugin_id", "candidates", "message"],
                **{"x-ts-name": "ProviderCapabilityView"},
            ),
            "ProviderPluginView": _obj(
                {
                    "plugin_id": {"type": "string"},
                    "plugin_version": POSITIVE,
                    "label": {"type": "string"},
                    "endpoint": _nullable({"type": "string"}),
                    "manifest": _ref("PluginManifest"),
                    "settings": FREE_OBJECT,
                    "settings_summary": {"type": "string"},
                    "settings_error": _nullable({"type": "string"}),
                },
                [
                    "plugin_id",
                    "plugin_version",
                    "label",
                    "endpoint",
                    "manifest",
                    "settings",
                    "settings_summary",
                    "settings_error",
                ],
                **{"x-ts-name": "ProviderPluginView"},
            ),
            "ProviderToolView": _obj(
                {"id": {"type": "string"}, "label": {"type": "string"}, "available": BOOL},
                ["id", "label", "available"],
                **{"x-ts-name": "ProviderToolView"},
            ),
            "ProviderSettingsView": _obj(
                {
                    "capabilities": _array(_ref("ProviderCapabilityView")),
                    "plugins": _array(_ref("ProviderPluginView")),
                    "tools": _array(_ref("ProviderToolView")),
                },
                ["capabilities", "plugins", "tools"],
                **{"x-ts-name": "ProviderSettingsView", "x-guard": "isProviderSettingsView"},
            ),
            "ProjectDetail": _obj(
                {
                    "project": _ref("ProjectSummary"),
                    "structured_director": _ref("StructuredDirectorSnapshot"),
                },
                ["project", "structured_director"],
                **{"x-ts-name": "ProjectDetail"},
            ),
            "ActiveDirectorRun": _obj(
                {
                    "id": ID,
                    "kind": _ref("DirectorRunKind"),
                    "status": _ref("ActiveDirectorRunStatus"),
                    "waiting_reason": _nullable({"type": "string", "minLength": 1}),
                    "created_at": {"type": "string"},
                    "updated_at": {"type": "string"},
                },
                ["id", "kind", "status", "waiting_reason", "created_at", "updated_at"],
                **{
                    "x-ts-name": "ActiveDirectorRun",
                    "x-guard": "isActiveDirectorRun",
                    "x-refine": "refineActiveDirectorRun",
                },
            ),
            "CharacterLook": _obj(
                {
                    "id": ID,
                    "name": TEXT,
                    "appearance": TEXT,
                    "usage": TEXT,
                    "selected_asset_id": NULL_ID,
                },
                ["id", "name", "appearance", "usage", "selected_asset_id"],
                **{"x-ts-name": "CharacterLook"},
            ),
            "DialogueLine": _obj(
                {
                    "character_id": NULL_ID,
                    "speaker_label": _nullable(TEXT),
                    "text": TEXT,
                    "delivery": {"type": "string"},
                },
                ["character_id", "speaker_label", "text", "delivery"],
                **{"x-ts-name": "DialogueLine", "x-guard": "isDialogueLine"},
            ),
            "DialogueTimingWarning": _obj(
                {
                    "segment_id": ID,
                    "estimated_seconds": {"type": "number"},
                    "duration_seconds": {"type": "number"},
                },
                ["segment_id", "estimated_seconds", "duration_seconds"],
                **{"x-ts-name": "DialogueTimingWarning"},
            ),
            "SegmentBoundary": _obj(
                {
                    "reason": _ref("SegmentBoundaryReason"),
                    "continuity_instruction": TEXT,
                },
                ["reason", "continuity_instruction"],
                **{"x-ts-name": "SegmentBoundary", "x-guard": "isSegmentBoundary"},
            ),
            "ShotSegment": _obj(
                {
                    "id": ID,
                    "duration_estimate_seconds": {
                        "type": "number",
                        "minimum": 0.2,
                        "x-finite": True,
                    },
                    "action": TEXT,
                    "dialogue_lines": _array(_ref("DialogueLine")),
                    "boundary_from_previous": _nullable(_ref("SegmentBoundary")),
                },
                [
                    "id",
                    "duration_estimate_seconds",
                    "action",
                    "dialogue_lines",
                    "boundary_from_previous",
                ],
                **{"x-ts-name": "ShotSegment", "x-guard": "isShotSegment"},
            ),
            "Shot": _obj(
                {
                    "id": ID,
                    "visible_character_ids": _array(ID, uniqueItems=True),
                    "composition": TEXT,
                    "camera_movement": TEXT,
                    "action": TEXT,
                    "audio_direction": {"type": "string"},
                    "transition_in": _nullable(TEXT),
                    "segments": _array(_ref("ShotSegment"), minItems=1),
                    "view_id": NULL_ID,
                },
                [
                    "id",
                    "visible_character_ids",
                    "composition",
                    "camera_movement",
                    "action",
                    "audio_direction",
                    "transition_in",
                    "segments",
                    "view_id",
                ],
                **{"x-ts-name": "Shot", "x-guard": "isShot", "x-refine": "refineShot"},
            ),
            "SceneAnimaticState": _obj(
                {
                    "reason": {"type": "string"},
                    "provider_available": BOOL,
                    "ready": BOOL,
                    "active_generation_id": NULL_ID,
                    "latest_succeeded_generation_id": NULL_ID,
                },
                [
                    "reason",
                    "provider_available",
                    "ready",
                    "active_generation_id",
                    "latest_succeeded_generation_id",
                ],
                **{"x-ts-name": "SceneAnimaticState", "x-guard": "isSceneAnimaticState"},
            ),
            "SceneFinalLanguageState": _obj(
                {
                    "active_generation_id": NULL_ID,
                    "latest_succeeded_generation_id": NULL_ID,
                    "current_asset_id": NULL_ID,
                    "outdated": BOOL,
                },
                [
                    "active_generation_id",
                    "latest_succeeded_generation_id",
                    "current_asset_id",
                    "outdated",
                ],
                **{"x-ts-name": "SceneFinalLanguageState"},
            ),
            "SceneFinalState": _obj(
                {
                    "reason": {"type": "string"},
                    "provider_available": BOOL,
                    "ready": BOOL,
                    "zh": _nullable(_ref("SceneFinalLanguageState")),
                    "en": _nullable(_ref("SceneFinalLanguageState")),
                },
                ["reason", "provider_available", "ready", "zh", "en"],
                **{"x-ts-name": "SceneFinalState", "x-guard": "isSceneFinalState"},
            ),
            "Scene": _obj(
                {
                    "location_id": NULL_ID,
                    "state_id": NULL_ID,
                    "driver": _enum(("narration", "drama")),
                    "id": ID,
                    "title": TEXT,
                    "summary": TEXT,
                    "setting": TEXT,
                    "shots": _array(_ref("Shot")),
                    "narration_cues": _array(_ref("NarrationCue")),
                    "animatic": _ref("SceneAnimaticState"),
                    "scene_final": _ref("SceneFinalState"),
                },
                [
                    "location_id",
                    "state_id",
                    "driver",
                    "id",
                    "title",
                    "summary",
                    "setting",
                    "shots",
                    "narration_cues",
                ],
                **{"x-ts-name": "Scene", "x-guard": "isScene", "x-refine": "refineScene"},
            ),
            "NarrationTrack": _obj(
                {
                    "text": TEXT,
                    "seed": {"type": "integer"},
                    "selected_audio_asset_id": NULL_ID,
                    "recipe_params": {
                        **FREE_OBJECT,
                        "x-ts-type": "Record<string, Record<string, unknown>>",
                    },
                    "selected_duration_seconds": _nullable({"type": "number"}),
                },
                [
                    "text",
                    "seed",
                    "selected_audio_asset_id",
                    "recipe_params",
                    "selected_duration_seconds",
                ],
                **{"x-ts-name": "NarrationTrack", "x-guard": "isNarrationTrack"},
            ),
            "NarrationCue": _obj(
                {
                    "id": ID,
                    "start_shot_id": NULL_ID,
                    "end_shot_id": NULL_ID,
                    "zh": _nullable(_ref("NarrationTrack")),
                    "en": _nullable(_ref("NarrationTrack")),
                    "timing_language": _nullable(_ref("NarrationLanguage")),
                    "timing_seconds": _nullable({"type": "number"}),
                },
                [
                    "id",
                    "start_shot_id",
                    "end_shot_id",
                    "zh",
                    "en",
                    "timing_language",
                    "timing_seconds",
                ],
                **{"x-ts-name": "NarrationCue", "x-guard": "isNarrationCue"},
            ),
            "DirectorScript": _obj(
                {
                    "revision": POSITIVE,
                    "source_reference_revision": POSITIVE,
                    "production_baseline_revision": _nullable(POSITIVE),
                    "production_baseline_scenes": _nullable(_array(_ref("Scene"), minItems=1)),
                    "scenes": _array(_ref("Scene"), minItems=1),
                },
                [
                    "revision",
                    "source_reference_revision",
                    "production_baseline_revision",
                    "production_baseline_scenes",
                    "scenes",
                ],
                **{
                    "x-ts-name": "DirectorScript",
                    "x-guard": "isDirectorScript",
                    "x-refine": "refineDirectorScript",
                },
            ),
            "LocationProduction": _obj(
                {
                    "status": TEXT,
                    "status_label": TEXT,
                    "reason": _nullable({"type": "string"}),
                    "generation_step": _enum(("master", "crop", "refine", "turn")),
                    "generate_label": TEXT,
                    "active_generation_id": NULL_ID,
                    "candidate_generation_ids": _array(ID),
                    "selectable_generation_ids": _array(ID),
                    "allowed_actions": _array(
                        _enum(("generate", "select", "edit", "delete", "clear_selection"))
                    ),
                },
                [
                    "status",
                    "status_label",
                    "reason",
                    "generation_step",
                    "generate_label",
                    "active_generation_id",
                    "candidate_generation_ids",
                    "selectable_generation_ids",
                    "allowed_actions",
                ],
                **{"x-ts-name": "LocationProduction"},
            ),
            "LocationFixture": _obj(
                {
                    "allowed_actions": {**_array(_enum(("edit", "delete"))), "x-ts-optional": True},
                    "id": ID,
                    "name": TEXT,
                    "description": {"type": "string"},
                    "azimuth_deg": _nullable({"type": "number"}),
                },
                ["id", "name", "description", "azimuth_deg", "allowed_actions"],
                **{"x-ts-name": "LocationFixture"},
            ),
            "LocationKeyLight": _obj(
                {"description": TEXT, "azimuth_deg": _nullable({"type": "number"})},
                ["description", "azimuth_deg"],
                **{"x-ts-name": "LocationKeyLight"},
            ),
            "LocationMaster": _obj(
                {
                    "production": {**_ref("LocationProduction"), "x-ts-optional": True},
                    "prompt_text": {"type": "string", "maxLength": 19000},
                    "reference_asset_ids": _array(ID, uniqueItems=True, maxItems=5),
                    "selected_asset_id": NULL_ID,
                },
                ["prompt_text", "reference_asset_ids", "selected_asset_id", "production"],
                **{"x-ts-name": "LocationMaster"},
            ),
            "LocationState": _obj(
                {
                    "id": ID,
                    "name": TEXT,
                    "description": TEXT,
                    "allowed_actions": {**_array(_enum(("edit", "delete"))), "x-ts-optional": True},
                },
                ["id", "name", "description", "allowed_actions"],
                **{"x-ts-name": "LocationState"},
            ),
            "LocationView": _obj(
                {
                    "production": {**_ref("LocationProduction"), "x-ts-optional": True},
                    "has_valid_crop": {**BOOL, "x-ts-optional": True},
                    "id": ID,
                    "name": TEXT,
                    "purpose": TEXT,
                    "azimuth_deg": _nullable({"type": "number"}),
                    "look_at_fixture_id": NULL_ID,
                    "yaw_offset_deg": _nullable({"type": "number"}),
                    "pitch_deg": {"type": "number"},
                    "hfov_deg": {"type": "number"},
                    "state_id": NULL_ID,
                    "refine_prompt_text": {"type": "string", "maxLength": 19000},
                    "reference_view_ids": _array(ID, uniqueItems=True),
                    "crop_asset_id": NULL_ID,
                    "selected_asset_id": NULL_ID,
                },
                [
                    "id",
                    "name",
                    "purpose",
                    "azimuth_deg",
                    "look_at_fixture_id",
                    "yaw_offset_deg",
                    "pitch_deg",
                    "hfov_deg",
                    "state_id",
                    "refine_prompt_text",
                    "reference_view_ids",
                    "crop_asset_id",
                    "selected_asset_id",
                    "production",
                    "has_valid_crop",
                ],
                **{"x-ts-name": "LocationView"},
            ),
            "Location": _obj(
                {
                    "allowed_actions": {
                        **_array(
                            _enum(
                                ("edit", "delete", "create_view", "create_fixture", "create_state")
                            )
                        ),
                        "x-ts-optional": True,
                    },
                    "id": ID,
                    "name": TEXT,
                    "kind": _ref("LocationKind"),
                    "description": {"type": "string", "maxLength": 4000},
                    "fixtures": _array(_ref("LocationFixture"), maxItems=40),
                    "key_light": _nullable(_ref("LocationKeyLight")),
                    "master": _ref("LocationMaster"),
                    "calibrated_master_asset_id": NULL_ID,
                    "states": _array(_ref("LocationState"), maxItems=10),
                    "views": _array(_ref("LocationView"), maxItems=30),
                },
                [
                    "id",
                    "name",
                    "kind",
                    "description",
                    "fixtures",
                    "key_light",
                    "master",
                    "calibrated_master_asset_id",
                    "states",
                    "views",
                    "allowed_actions",
                ],
                **{"x-ts-name": "Location"},
            ),
            "LocationLibrary": _obj(
                {
                    "locations": _array(_ref("Location"), maxItems=200),
                    "allowed_actions": {
                        **_array(_enum(("create_location", "bind_scene", "bind_shot"))),
                        "x-ts-optional": True,
                    },
                },
                ["locations", "allowed_actions"],
                **{"x-ts-name": "LocationLibrary", "x-guard": "isLocationLibrary"},
            ),
            "Keyframe": _obj(
                {
                    "id": ID,
                    "owner_segment_id": ID,
                    "predecessor_keyframe_id": NULL_ID,
                    "prompt_text": {"type": "string", "maxLength": 18000},
                    "visible_character_ids": _array(ID, uniqueItems=True),
                    "character_references": _array(_ref("KeyframeCharacterReference")),
                    "selected_asset_id": NULL_ID,
                    "environment_mode": _ref("KeyframeEnvironmentMode"),
                    "environment_view_id": NULL_ID,
                    "environment_none_reason": _nullable({"type": "string", "maxLength": 500}),
                },
                [
                    "id",
                    "owner_segment_id",
                    "predecessor_keyframe_id",
                    "prompt_text",
                    "visible_character_ids",
                    "character_references",
                    "selected_asset_id",
                    "environment_mode",
                    "environment_view_id",
                    "environment_none_reason",
                ],
                **{"x-ts-name": "Keyframe"},
            ),
            "KeyframeCharacterReference": _obj(
                {
                    "character_id": ID,
                    "look_id": NULL_ID,
                },
                ["character_id", "look_id"],
                **{"x-ts-name": "KeyframeCharacterReference"},
            ),
            "StartFrameExtraction": _obj(
                {
                    "source_segment_id": NULL_ID,
                    "source_video_asset_id": NULL_ID,
                    "state": {
                        "enum": [
                            "ready",
                            "unavailable",
                            "shared_boundary",
                            "waiting_source_video",
                            "source_not_current",
                        ]
                    },
                    "message": TEXT,
                },
                ["source_segment_id", "source_video_asset_id", "state", "message"],
                **{"x-ts-name": "StartFrameExtraction"},
            ),
            "SegmentKeyframes": _obj(
                {
                    "segment_id": ID,
                    "start_keyframe_id": ID,
                    "end_keyframe_id": ID,
                    "start_enabled": BOOL,
                    "end_enabled": BOOL,
                    "reference_asset_ids": _array(ID),
                    "start_frame_extraction": _ref("StartFrameExtraction"),
                },
                [
                    "segment_id",
                    "start_keyframe_id",
                    "end_keyframe_id",
                    "start_enabled",
                    "end_enabled",
                    "reference_asset_ids",
                    "start_frame_extraction",
                ],
                **{"x-ts-name": "SegmentKeyframes"},
            ),
            "KeyframePlan": _obj(
                {
                    "source_script_revision": POSITIVE,
                    "keyframes": _array(_ref("Keyframe"), minItems=1),
                    "segments": _array(_ref("SegmentKeyframes"), minItems=1),
                },
                ["source_script_revision", "keyframes", "segments"],
                **{"x-ts-name": "KeyframePlan", "x-guard": "isKeyframePlan"},
            ),
            "RecipeBinding": _obj(
                {"asset_id": ID, "description": _nullable({"type": "string", "maxLength": 2000})},
                ["asset_id", "description"],
                **{"x-ts-name": "RecipeBinding"},
            ),
            "RecipeInputs": _obj(
                {
                    "bindings": {
                        "type": "object",
                        "additionalProperties": _array(_ref("RecipeBinding")),
                        "x-ts-type": "Record<string, RecipeBinding[]>",
                    },
                    "params": FREE_OBJECT,
                },
                ["bindings", "params"],
                **{"x-ts-name": "RecipeInputs"},
            ),
            "VideoRecipeOption": _obj(
                {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "allowed": BOOL,
                    "reason": _nullable({"type": "string"}),
                },
                ["id", "label", "allowed", "reason"],
                **{"x-ts-name": "VideoRecipeOption"},
            ),
            "RecipeInputLabel": _obj(
                {
                    "slot": {"type": "string"},
                    "role": _ref("ManifestRole"),
                    "index": {"type": "integer"},
                    "asset_id": ID,
                    "description": _nullable({"type": "string"}),
                    "label": _nullable({"type": "string"}),
                },
                ["slot", "role", "index", "asset_id", "description", "label"],
                **{"x-ts-name": "RecipeInputLabel"},
            ),
            "VideoRecipeState": _obj(
                {
                    "available": BOOL,
                    "ready": BOOL,
                    "reason": _nullable({"type": "string"}),
                    "options": _array(_ref("VideoRecipeOption")),
                    "duration_seconds": {"type": "number"},
                    "soft_duration_limit_seconds": _nullable({"type": "number"}),
                    "bindings": _array(_ref("RecipeInputLabel")),
                    "slot_labels": {
                        "type": "object",
                        "additionalProperties": _array(_nullable({"type": "string"})),
                        "x-ts-type": "Record<string, (string | null)[]>",
                    },
                },
                [
                    "available",
                    "ready",
                    "reason",
                    "options",
                    "duration_seconds",
                    "soft_duration_limit_seconds",
                    "bindings",
                    "slot_labels",
                ],
                **{"x-ts-name": "VideoRecipeState", "x-guard": "isVideoRecipeState"},
            ),
            "SegmentVideo": _obj(
                {
                    "segment_id": ID,
                    "prompt_text": {"type": "string", "maxLength": 20000},
                    "active_recipe": _nullable({"type": "string"}),
                    "recipe_state": {**_ref("VideoRecipeState"), "x-ts-optional": True},
                    "recipes": {
                        "type": "object",
                        "additionalProperties": _ref("RecipeInputs"),
                        "x-ts-type": "Record<string, RecipeInputs>",
                    },
                    "selected_asset_id": NULL_ID,
                    "upscaled_asset_id": NULL_ID,
                },
                [
                    "segment_id",
                    "prompt_text",
                    "active_recipe",
                    "recipe_state",
                    "recipes",
                    "selected_asset_id",
                    "upscaled_asset_id",
                ],
                **{"x-ts-name": "SegmentVideo"},
            ),
            "VideoPlan": _obj(
                {
                    "source_script_revision": POSITIVE,
                    "segments": _array(_ref("SegmentVideo"), minItems=1),
                },
                ["source_script_revision", "segments"],
                **{"x-ts-name": "VideoPlan", "x-guard": "isVideoPlan"},
            ),
            "FinalAssemblyClip": _obj(
                {
                    "scene_id": ID,
                    "zh_asset_id": NULL_ID,
                    "en_asset_id": NULL_ID,
                    "transition_from_previous": {
                        "anyOf": [{"type": "null"}, {"const": "seam_blend"}]
                    },
                },
                ["scene_id", "zh_asset_id", "en_asset_id", "transition_from_previous"],
                **{"x-ts-name": "FinalAssemblyClip"},
            ),
            "FinalAssemblyPlan": _obj(
                {
                    "source_script_revision": POSITIVE,
                    "clips": _array(_ref("FinalAssemblyClip"), minItems=1),
                    "selected_zh_asset_id": NULL_ID,
                    "selected_en_asset_id": NULL_ID,
                },
                [
                    "source_script_revision",
                    "clips",
                    "selected_zh_asset_id",
                    "selected_en_asset_id",
                ],
                **{
                    "x-ts-name": "FinalAssemblyPlan",
                    "x-guard": "isFinalAssemblyPlan",
                    "x-refine": "refineFinalAssembly",
                },
            ),
            "FinalApproval": _obj(
                {
                    "zh_asset_id": NULL_ID,
                    "zh_generation_id": NULL_ID,
                    "en_asset_id": NULL_ID,
                    "en_generation_id": NULL_ID,
                    "source_script_revision": POSITIVE,
                    "approved_project_revision": POSITIVE,
                },
                [
                    "zh_asset_id",
                    "zh_generation_id",
                    "en_asset_id",
                    "en_generation_id",
                    "source_script_revision",
                    "approved_project_revision",
                ],
                **{"x-ts-name": "FinalApproval", "x-guard": "isFinalApproval"},
            ),
            "AssetUsageReason": _obj(
                {"code": _ref("AssetUsageReasonCode"), "label": TEXT},
                ["code", "label"],
                **{"x-ts-name": "AssetUsageReason", "x-guard": "isAssetUsageReason"},
            ),
            "ProjectAsset": _obj(
                {
                    "id": ID,
                    "media_type": _ref("MediaType"),
                    "image_category": _nullable(_ref("ImageAssetCategory")),
                    "byte_count": {"type": "integer", "minimum": 1},
                    "duration_seconds": _nullable({"type": "number", "exclusiveMinimum": 0}),
                    "display_name": {"type": "string"},
                    "content_url": {"type": "string"},
                    "is_in_use": BOOL,
                    "usage_reasons": _array(_ref("AssetUsageReason")),
                    "retains_derived_assets_on_delete": BOOL,
                    "allowed_actions": _array(_ref("AssetAction"), uniqueItems=True),
                },
                [
                    "id",
                    "media_type",
                    "image_category",
                    "byte_count",
                    "duration_seconds",
                    "content_url",
                    "is_in_use",
                    "usage_reasons",
                    "retains_derived_assets_on_delete",
                    "allowed_actions",
                ],
                **{
                    "x-ts-name": "ProjectAsset",
                    "x-guard": "isProjectAsset",
                    "x-refine": "refineAsset",
                },
            ),
            "SubmissionAttachment": _obj(
                {
                    "asset_id": ID,
                    "display_name": {"type": "string"},
                    "content_url": {"type": "string"},
                    "role": _enum(("source_image", "reference_image")),
                    # 本图在实际输入中的角色名（地点视图、角色参考、前置帧、辅助参考）与用途说明。
                    "input_roles": _array({"type": "string"}),
                    "purpose": {"type": "string"},
                },
                ["asset_id", "display_name", "content_url", "role", "input_roles", "purpose"],
                **{"x-ts-name": "SubmissionAttachment"},
            ),
            "ImageSubmissionPreview": _obj(
                {
                    "reference_prompt": {"type": "string"},
                    "instruction": _nullable({"type": "string"}),
                    "ready": BOOL,
                    "operation": _ref("ImageOperation"),
                    "attachments": _array(_ref("SubmissionAttachment")),
                },
                ["reference_prompt", "instruction", "ready", "operation", "attachments"],
                **{
                    "x-ts-name": "ImageSubmissionPreview",
                    "x-guard": "isImageSubmissionPreview",
                },
            ),
            "GenerationProvider": _obj(
                {
                    "plugin_id": {"type": "string"},
                    "recipe_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                ["plugin_id", "recipe_id", "summary"],
                **{"x-ts-name": "GenerationProvider", "x-guard": "isGenerationProvider"},
            ),
            "ReferenceGeneration": _obj(
                {
                    "id": ID,
                    "kind": _ref("ReferenceGenerationKind"),
                    "operation": _ref("GenerationOperation"),
                    "target_id": ID,
                    "phase": _ref("ReferenceGenerationPhase"),
                    "progress": {"type": "number", "minimum": 0, "maximum": 1},
                    "message": {"type": "string"},
                    "prompt_text": {"type": "string"},
                    "input_asset_ids": _array(ID),
                    "sample_text": _nullable({"type": "string"}),
                    "language": _nullable(_ref("NarrationLanguage")),
                    "aspect_ratio": {**_nullable(_ref("ImageAspectRatio")), "x-ts-optional": True},
                    "seed": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string", "pattern": "^[0-9]{1,19}$"},
                            {"type": "null"},
                        ]
                    },
                    "duration_seconds": {**_nullable({"type": "number"}), "x-ts-optional": True},
                    "output_asset_id": NULL_ID,
                    "error_code": _nullable({"type": "string"}),
                    "cancellation_requested": BOOL,
                    "retry_of": NULL_ID,
                    "dismissed": BOOL,
                    "provider": {**_nullable(_ref("GenerationProvider")), "x-ts-optional": True},
                    "inputs_outdated": {**BOOL, "x-ts-optional": True},
                    "allowed_actions": _array(_ref("ReferenceGenerationAction"), uniqueItems=True),
                },
                [
                    "id",
                    "kind",
                    "operation",
                    "target_id",
                    "phase",
                    "progress",
                    "message",
                    "prompt_text",
                    "input_asset_ids",
                    "sample_text",
                    "language",
                    "seed",
                    "duration_seconds",
                    "output_asset_id",
                    "error_code",
                    "cancellation_requested",
                    "retry_of",
                    "dismissed",
                    "provider",
                    "allowed_actions",
                ],
                **{
                    "x-ts-name": "ReferenceGeneration",
                    "x-guard": "isReferenceGeneration",
                    "x-refine": "refineGeneration",
                },
            ),
            "WorkspaceLayers": _obj(
                {
                    "narration_unlocked": BOOL,
                    "keyframes_unlocked": BOOL,
                    "videos_unlocked": BOOL,
                    "final_assembly_unlocked": BOOL,
                },
                [
                    "narration_unlocked",
                    "keyframes_unlocked",
                    "videos_unlocked",
                    "final_assembly_unlocked",
                ],
                **{
                    "x-ts-name": "WorkspaceLayers",
                    "x-guard": "isWorkspaceLayers",
                    "x-refine": "refineWorkspaceLayers",
                },
            ),
            "ProviderAvailability": _obj(
                {
                    "image_generation": BOOL,
                    "voice_design": BOOL,
                    "speech_synthesis": BOOL,
                    "speech_recognition": BOOL,
                    "video_generation": {**BOOL, "x-ts-optional": True},
                    "video_upscale": {**BOOL, "x-ts-optional": True},
                    "final_assembly": {**BOOL, "x-ts-optional": True},
                    "scene_animatic": {**BOOL, "x-ts-optional": True},
                    "audio_separation": {**BOOL, "x-ts-optional": True},
                    "audio_remix": {**BOOL, "x-ts-optional": True},
                },
                [
                    "image_generation",
                    "voice_design",
                    "speech_synthesis",
                    "video_generation",
                    "video_upscale",
                    "final_assembly",
                    "scene_animatic",
                    "audio_separation",
                    "audio_remix",
                ],
                **{"x-ts-name": "ProviderAvailability", "x-guard": "isProviderAvailability"},
            ),
            "ReferenceLibraryView": _obj(
                {
                    "reviewed": BOOL,
                    "characters": _array(_ref("CharacterCard")),
                    "narrator": _nullable(_ref("NarratorProfile")),
                },
                ["characters", "narrator"],
                **{"x-ts-name": "ReferenceLibraryView"},
            ),
            "CharacterCard": _obj(
                {
                    "id": ID,
                    "name": {"type": "string"},
                    "visual_description": _nullable({"type": "string"}),
                    "voice_description": {"type": "string"},
                    "voice_reference_asset_id": NULL_ID,
                    "voice_reference_transcript": _nullable({"type": "string"}),
                    "looks": _array(_ref("CharacterLook")),
                },
                [
                    "id",
                    "name",
                    "visual_description",
                    "voice_description",
                    "voice_reference_asset_id",
                    "looks",
                ],
                **{"x-ts-name": "CharacterCard", "x-guard": "isCharacterCard"},
            ),
            "NarratorProfile": _obj(
                {
                    "id": ID,
                    "name": TEXT,
                    "zh": _nullable(_ref("NarratorVoice")),
                    "en": _nullable(_ref("NarratorVoice")),
                },
                ["id", "name", "zh", "en"],
                **{"x-ts-name": "NarratorProfile", "x-guard": "isNarratorProfile"},
            ),
            "NarratorVoice": _obj(
                {
                    "voice_description": TEXT,
                    "voice_reference_asset_id": NULL_ID,
                    "voice_reference_transcript": _nullable({"type": "string"}),
                },
                ["voice_description", "voice_reference_asset_id", "voice_reference_transcript"],
                **{"x-ts-name": "NarratorVoice"},
            ),
            "ProductionAvailabilityEntry": _obj(
                {
                    "unlocked": BOOL,
                    "reason": {"type": "string"},
                    "next_location": {"const": "project"},
                    "action": _nullable({"type": "string"}),
                },
                ["unlocked", "reason", "next_location", "action"],
                **{"x-ts-name": "ProductionAvailabilityEntry"},
            ),
            "ProductionAvailability": _obj(
                {
                    "narration": _ref("ProductionAvailabilityEntry"),
                    "keyframes": _ref("ProductionAvailabilityEntry"),
                    "videos": _ref("ProductionAvailabilityEntry"),
                    "final": _ref("ProductionAvailabilityEntry"),
                },
                ["narration", "keyframes", "videos", "final"],
                **{"x-ts-name": "ProductionAvailability", "x-guard": "isProductionAvailability"},
            ),
            "WorkflowAction": _obj(
                {
                    "action": TEXT,
                    "tool": _nullable({"type": "string"}),
                    "target_ids": _array(ID, uniqueItems=True),
                    "human_only": BOOL,
                    "requires_explicit_user_request": BOOL,
                },
                ["action", "tool", "target_ids", "human_only", "requires_explicit_user_request"],
                **{
                    "x-ts-name": "WorkflowAction",
                    "x-guard": "isWorkflowAction",
                    "additionalProperties": True,
                },
            ),
            "WorkflowSemantics": _obj(
                {
                    "current_stage": {"const": "primary_workflow_focus_not_capability_lock"},
                    "active_task": {
                        "const": "primary_workflow_task_only_parallel_activity_uses_task_discovery"
                    },
                    "required_next_actions": {"const": "primary_workflow_actions_only"},
                },
                ["current_stage", "active_task", "required_next_actions"],
                **{"x-ts-name": "WorkflowSemantics"},
            ),
            "WorkspaceCapabilities": _obj(
                {
                    "semantics": {"const": "cumulative_unlocked_layers_not_primary_workflow"},
                    "unlocked": _array(_ref("WorkspaceCapability"), uniqueItems=True),
                },
                ["semantics", "unlocked"],
                **{"x-ts-name": "WorkspaceCapabilities"},
            ),
            "ActivitySummary": _obj(
                {
                    "active_generation_count": {"type": "integer", "minimum": 0},
                    "has_active_generations": BOOL,
                    "task_discovery_tool": {"const": "read_workflow"},
                    "semantics": {"const": "parallel_project_activity_not_primary_workflow"},
                },
                [
                    "active_generation_count",
                    "has_active_generations",
                    "task_discovery_tool",
                    "semantics",
                ],
                **{"x-ts-name": "ActivitySummary"},
            ),
            "BlockedActionReason": _obj(
                {"reason": {"type": "string"}},
                ["reason"],
                **{"x-ts-name": "BlockedActionReason"},
            ),
            "WorkflowState": _obj(
                {
                    "current_stage": {"type": "string"},
                    "stage_status": {"type": "string"},
                    "semantics": _ref("WorkflowSemantics"),
                    "required_next_actions": {"type": "array", "x-ts-type": "WorkflowAction[]"},
                    "recommended_next_actions": {
                        "type": "array",
                        "x-ts-type": "WorkflowAction[]",
                        "x-ts-optional": True,
                    },
                    "blocking_prerequisites": _array({"type": "string"}),
                    "blocked_actions": {
                        "type": "object",
                        "additionalProperties": _ref("BlockedActionReason"),
                        "properties": {},
                    },
                    "workspace_capabilities": _ref("WorkspaceCapabilities"),
                    "activity_summary": _ref("ActivitySummary"),
                    "requires_explicit_user_request": BOOL,
                    "active_task": _nullable(
                        {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {},
                        }
                    ),
                },
                [
                    "current_stage",
                    "stage_status",
                    "semantics",
                    "required_next_actions",
                    "recommended_next_actions",
                    "blocking_prerequisites",
                    "blocked_actions",
                    "workspace_capabilities",
                    "activity_summary",
                    "requires_explicit_user_request",
                    "active_task",
                ],
                **{"x-ts-name": "WorkflowState", "x-guard": "isWorkflowEnvelope"},
            ),
            "CapabilityGapAlert": _obj(
                {
                    "gap_id": ID,
                    "run_id": {"type": "string"},
                    "missing_command": {"type": "string"},
                    "raw_user_request_summary": {"type": "string"},
                    "target_ids": _array(ID),
                    "scope_scene_ids": _array(ID),
                    "operation_summary": {"type": "string"},
                    "old_revision": POSITIVE,
                    "new_revision": POSITIVE,
                    "result": _enum(CapabilityGapResult),
                    "first_occurred_at": {"type": "string"},
                    "last_occurred_at": {"type": "string"},
                    "occurrence_count": POSITIVE,
                    "closed_revision": _nullable(POSITIVE),
                    "closed_by_command": _nullable({"type": "string"}),
                    "status": _enum(CapabilityGapStatus),
                },
                [
                    "gap_id",
                    "run_id",
                    "missing_command",
                    "raw_user_request_summary",
                    "target_ids",
                    "scope_scene_ids",
                    "operation_summary",
                    "old_revision",
                    "new_revision",
                    "result",
                    "first_occurred_at",
                    "last_occurred_at",
                    "occurrence_count",
                    "status",
                    "closed_revision",
                    "closed_by_command",
                ],
                **{"x-ts-name": "CapabilityGapAlert", "x-guard": "isCapabilityGapAlert"},
            ),
            "StructuredDirectorSnapshot": _obj(
                {
                    "status": _ref("StructuredDirectorStatus"),
                    "active_director_run": _nullable(_ref("ActiveDirectorRun")),
                    "revision": POSITIVE,
                    "aspect_ratio": _ref("ProjectAspectRatio"),
                    "director_plan_markdown": TEXT,
                    "narration_languages": {
                        "type": "array",
                        "items": _ref("NarrationLanguage"),
                        "minItems": 1,
                        "maxItems": 2,
                        "uniqueItems": True,
                    },
                    "workspace_layers": _ref("WorkspaceLayers"),
                    "allowed_actions": _array(_ref("StructuredDirectorAction"), uniqueItems=True),
                    "workflow": _ref("WorkflowState"),
                    "dialogue_timing_warnings": _array(_ref("DialogueTimingWarning")),
                    "provider_availability": _ref("ProviderAvailability"),
                    "assets": _array(_ref("ProjectAsset")),
                    "generations": _array(_ref("ReferenceGeneration")),
                    "reference_library": _ref("ReferenceLibraryView"),
                    "director_script": _nullable(_ref("DirectorScript")),
                    "production_availability": _ref("ProductionAvailability"),
                    "location_library": _ref("LocationLibrary"),
                    "keyframe_plan": _nullable(_ref("KeyframePlan")),
                    "video_plan": {**_nullable(_ref("VideoPlan")), "x-ts-optional": True},
                    "final_assembly": {
                        **_nullable(_ref("FinalAssemblyPlan")),
                        "x-ts-optional": True,
                    },
                    "final_approval": _nullable(_ref("FinalApproval")),
                    "capability_gap_alerts": _array(_ref("CapabilityGapAlert")),
                    "provider_recipes": {
                        **_array(_ref("ProviderRecipeView")),
                        "x-ts-optional": True,
                    },
                },
                [
                    "status",
                    "active_director_run",
                    "revision",
                    "aspect_ratio",
                    "director_plan_markdown",
                    "narration_languages",
                    "workspace_layers",
                    "allowed_actions",
                    "workflow",
                    "dialogue_timing_warnings",
                    "provider_availability",
                    "assets",
                    "generations",
                    "reference_library",
                    "director_script",
                    "production_availability",
                    "location_library",
                    "keyframe_plan",
                    "video_plan",
                    "final_assembly",
                    "final_approval",
                    "capability_gap_alerts",
                    "provider_recipes",
                ],
                **{"x-ts-name": "StructuredDirectorSnapshot"},
            ),
            "ApiErrorBody": _obj(
                {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "recoverable": BOOL,
                    "origin": {"type": "string"},
                    "state_changed": {"anyOf": [BOOL, {"const": "unknown"}]},
                    "retry_policy": {"type": "string"},
                    "automatic_retry_allowed": BOOL,
                    "expected_revision": POSITIVE,
                    "current_revision": POSITIVE,
                },
                [
                    "code",
                    "message",
                    "recoverable",
                    "origin",
                    "state_changed",
                    "retry_policy",
                    "automatic_retry_allowed",
                ],
                **{"x-ts-name": "ApiErrorBody"},
            ),
            "ApiErrorPayload": _obj(
                {"error": _ref("ApiErrorBody")},
                ["error"],
                **{"x-ts-name": "ApiErrorPayload", "x-guard": "isApiErrorPayload"},
            ),
            "AudioTrimSettings": _obj(
                {"start_seconds": {"type": "number"}, "end_seconds": {"type": "number"}},
                ["start_seconds", "end_seconds"],
                **{"x-ts-name": "AudioTrimSettings", "x-ts-only": True},
            ),
            "AudioEffectSettings": _obj(
                {
                    "effect": {"const": "radio"},
                    "preset": _ref("AudioEffectPreset"),
                    "strength": {"type": "number"},
                    "seed": {"type": "number"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                ["effect", "preset", "strength", "seed"],
                **{"x-ts-name": "AudioEffectSettings", "x-ts-only": True},
            ),
            "AudioGainSettings": _obj(
                {
                    "gain_db": {"type": "number"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                ["gain_db"],
                **{"x-ts-name": "AudioGainSettings", "x-ts-only": True},
            ),
            "AudioGenerationSettings": _obj(
                {
                    "operation": _enum(("voice_design", "synthesize")),
                    "text": {"type": "string"},
                    "voice_description": {"type": "string"},
                    "voice_asset_id": {"type": "string"},
                    "reference_transcript": {"type": "string"},
                    "recipe_params": {
                        **FREE_OBJECT,
                        "x-ts-type": "Record<string, Record<string, unknown>>",
                    },
                    "seed": {"type": "number"},
                },
                ["operation", "text", "seed"],
                **{"x-ts-name": "AudioGenerationSettings", "x-ts-only": True},
            ),
        }
    )
    schemas.update(
        {
            "PlaygroundCapabilityId": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "x-ts-alias": "PlaygroundCapabilityId",
            },
            "PlaygroundRunPhase": _enum(RunPhase, "PlaygroundRunPhase"),
            "PlaygroundRunAction": _enum(
                PLAYGROUND_RUN_ACTIONS,
                "PlaygroundRunAction",
                guard="isPlaygroundRunAction",
            ),
            "PlaygroundAssetAction": _enum(
                PLAYGROUND_ASSET_ACTIONS,
                "PlaygroundAssetAction",
                guard="isPlaygroundAssetAction",
            ),
            "PlaygroundAssetOriginKind": _enum(
                PLAYGROUND_ASSET_ORIGIN_KINDS,
                "PlaygroundAssetOriginKind",
            ),
            "PlaygroundRecipe": _obj(
                {
                    "plugin_id": {"type": "string"},
                    "plugin_label": {"type": "string"},
                    "recipe": _ref("ManifestRecipe"),
                },
                ["plugin_id", "plugin_label", "recipe"],
                **{"x-ts-name": "PlaygroundRecipe"},
            ),
            "PlaygroundCapabilityInfo": _obj(
                {
                    "id": _ref("PlaygroundCapabilityId"),
                    "label": {"type": "string"},
                    "execution": _enum(("async", "sync")),
                    "group": _enum(("image", "speech", "video", "audio")),
                    "available": BOOL,
                    "notes": {"type": "string"},
                    # recipe 能力：当前绑定插件的 recipe 声明，Web 按它渲染通用表单。
                    "recipe": {**_nullable(_ref("PlaygroundRecipe")), "x-ts-optional": True},
                    # 快照不带 schema；只有 list_capabilities 命令才返回它。
                    "parameters_schema": FREE_OBJECT,
                },
                ["id", "label", "execution", "group", "available", "notes", "recipe"],
                **{
                    "x-ts-name": "PlaygroundCapabilityInfo",
                    "x-guard": "isPlaygroundCapabilityInfo",
                },
            ),
            "PlaygroundAssetOrigin": {
                "anyOf": [
                    _obj(
                        {"kind": {"const": "imported", "x-ts-type": "PlaygroundAssetOriginKind"}},
                        ["kind"],
                    ),
                    _obj(
                        {
                            "kind": {
                                "const": "run_output",
                                "x-ts-type": "PlaygroundAssetOriginKind",
                            },
                            "run_id": ID,
                        },
                        ["kind", "run_id"],
                    ),
                    _obj(
                        {
                            "kind": {
                                "const": "copied_from_project",
                                "x-ts-type": "PlaygroundAssetOriginKind",
                            },
                            "project_id": ID,
                            "asset_id": ID,
                        },
                        ["kind", "project_id", "asset_id"],
                    ),
                ],
                "x-ts-name": "PlaygroundAssetOrigin",
                "x-guard": "isPlaygroundAssetOrigin",
            },
            "PlaygroundAssetUsageReason": _obj(
                {"code": {"type": "string"}, "label": {"type": "string"}},
                ["code", "label"],
                **{"x-ts-name": "PlaygroundAssetUsageReason"},
            ),
            "PlaygroundAsset": _obj(
                {
                    "id": ID,
                    "media_type": _ref("MediaType"),
                    "byte_count": {"type": "integer", "minimum": 1},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "relative_path": {"type": "string"},
                    "duration_seconds": _nullable({"type": "number", "exclusiveMinimum": 0}),
                    "origin": _ref("PlaygroundAssetOrigin"),
                    "created_at": {"type": "string"},
                    "display_name": {"type": "string"},
                    "content_url": {"type": "string"},
                    "is_in_use": BOOL,
                    "usage_reasons": _array(_ref("PlaygroundAssetUsageReason")),
                    "allowed_actions": _array(_ref("PlaygroundAssetAction"), uniqueItems=True),
                },
                [
                    "id",
                    "media_type",
                    "byte_count",
                    "sha256",
                    "relative_path",
                    "duration_seconds",
                    "origin",
                    "created_at",
                    "display_name",
                    "content_url",
                    "is_in_use",
                    "usage_reasons",
                    "allowed_actions",
                ],
                **{"x-ts-name": "PlaygroundAsset", "x-guard": "isPlaygroundAsset"},
            ),
            "PlaygroundRunRecovery": _obj(
                {
                    "failure_origin": _nullable({"type": "string"}),
                    "retry_policy": {"type": "string"},
                    "automatic_retry_allowed": BOOL,
                },
                ["failure_origin", "retry_policy", "automatic_retry_allowed"],
                **{
                    "x-ts-name": "PlaygroundRunRecovery",
                    "x-guard": "isPlaygroundRunRecovery",
                },
            ),
            "PlaygroundInputLabel": _obj(
                {
                    "label": {"type": "string"},
                    "provider_input": {"type": "string"},
                    "asset_id": ID,
                    "description": _nullable({"type": "string"}),
                },
                ["label", "provider_input", "asset_id", "description"],
                **{
                    "x-ts-name": "PlaygroundInputLabel",
                    "x-guard": "isPlaygroundInputLabel",
                },
            ),
            "PlaygroundRecipePreview": _obj(
                {
                    "ready": BOOL,
                    "reason": _nullable({"type": "string"}),
                    "input_labels": _array(_ref("PlaygroundInputLabel")),
                },
                ["ready", "reason", "input_labels"],
                **{"x-ts-name": "PlaygroundRecipePreview", "x-guard": "isPlaygroundRecipePreview"},
            ),
            "PlaygroundRun": _obj(
                {
                    "id": ID,
                    "capability": _ref("PlaygroundCapabilityId"),
                    "capability_label": {"type": "string"},
                    "phase": _ref("PlaygroundRunPhase"),
                    "progress": {"type": "number", "minimum": 0, "maximum": 1},
                    "message": {"type": "string"},
                    "parameters": FREE_OBJECT,
                    "input_asset_ids": _array(ID, uniqueItems=True),
                    "seed": _nullable({"type": "integer"}),
                    "plugin_id": _nullable({"type": "string"}),
                    "plugin_version": _nullable({"type": "integer"}),
                    "external_id": _nullable({"type": "string"}),
                    "output_asset_id": NULL_ID,
                    "result": _nullable(FREE_OBJECT),
                    "error_code": _nullable({"type": "string"}),
                    "cancellation_requested": BOOL,
                    "retry_of": NULL_ID,
                    "note": _nullable({"type": "string"}),
                    "dismissed": BOOL,
                    "provider": {**_nullable(_ref("GenerationProvider")), "x-ts-optional": True},
                    "created_at": {"type": "string"},
                    "updated_at": {"type": "string"},
                    "recovery": _ref("PlaygroundRunRecovery"),
                    "allowed_actions": _array(_ref("PlaygroundRunAction"), uniqueItems=True),
                    # 只有 video.ref2va 有 input_labels。
                    "input_labels": _array(_ref("PlaygroundInputLabel")),
                },
                [
                    "id",
                    "capability",
                    "capability_label",
                    "phase",
                    "progress",
                    "message",
                    "parameters",
                    "input_asset_ids",
                    "seed",
                    "plugin_id",
                    "plugin_version",
                    "external_id",
                    "output_asset_id",
                    "result",
                    "error_code",
                    "cancellation_requested",
                    "retry_of",
                    "note",
                    "dismissed",
                    "provider",
                    "created_at",
                    "updated_at",
                    "recovery",
                    "allowed_actions",
                ],
                **{"x-ts-name": "PlaygroundRun", "x-guard": "isPlaygroundRun"},
            ),
            "PlaygroundSnapshot": _obj(
                {
                    "schema_version": {"type": "integer"},
                    "revision": POSITIVE,
                    "capabilities": _array(_ref("PlaygroundCapabilityInfo")),
                    "runs": _array(_ref("PlaygroundRun")),
                    "assets": _array(_ref("PlaygroundAsset")),
                },
                ["schema_version", "revision", "capabilities", "runs", "assets"],
                **{
                    "x-ts-name": "PlaygroundSnapshot",
                    "x-guard": "isPlaygroundSnapshot",
                },
            ),
            "PlaygroundCommandReceipt": _obj(
                {
                    "command_id": {"type": "string"},
                    "status": _enum(("succeeded", "noop")),
                    "old_revision": POSITIVE,
                    "new_revision": POSITIVE,
                    "decision_summary": {"type": "string"},
                },
                [
                    "command_id",
                    "status",
                    "old_revision",
                    "new_revision",
                    "decision_summary",
                ],
                **{
                    "x-ts-name": "PlaygroundCommandReceipt",
                    "x-guard": "isPlaygroundCommandReceipt",
                },
            ),
            "PlaygroundCopyToProjectResult": _obj(
                {"asset_id": ID, "project_revision": POSITIVE},
                ["asset_id", "project_revision"],
                **{
                    "x-ts-name": "PlaygroundCopyToProjectResult",
                    "x-guard": "isPlaygroundCopyToProjectResult",
                },
            ),
            "PlaygroundAssetResult": _obj(
                {"asset": _ref("PlaygroundAsset")},
                ["asset"],
                **{
                    "x-ts-name": "PlaygroundAssetResult",
                    "x-guard": "isPlaygroundAssetResult",
                },
            ),
        }
    )
    return schemas


TYPE_ALIASES = (
    ("KeyframeSubmissionPreview", "ImageSubmissionPreview"),
    ("StructuredDirectorDetail", "ProjectDetail"),
)
