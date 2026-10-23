// 勿手改，由 scripts/gen_web_contracts.py 生成。
// @ts-nocheck
import {
  checkSchema,
  hasExactKeys,
  isId,
  isRecord,
  type JsonSchema,
} from "./schema_check";
import {
  refineActiveDirectorRun,
  refineAsset,
  refineDirectorScript,
  refineFinalAssembly,
  refineGeneration,
  refineScene,
  refineWorkflow,
  refineWorkspaceLayers,
  editableScenePayload,
  snapshotConsistencyError,
} from "./refine";
import type {
  ActiveDirectorRun,
  ActivitySummary,
  AgentMessageRole,
  ApiErrorBody,
  ApiErrorPayload,
  AssetAction,
  AssetUsageReason,
  AssetUsageReasonCode,
  AudioEffectPreset,
  AudioEffectSettings,
  AudioGainSettings,
  AudioGenerationSettings,
  AudioTrimSettings,
  BlockedActionReason,
  CapabilityGapAlert,
  CharacterCard,
  CharacterLook,
  DialogueAudio,
  DialogueLine,
  DialoguePlan,
  DirectorRunKind,
  DirectorScript,
  FinalApproval,
  FinalAssemblyClip,
  FinalAssemblyPlan,
  GenerationOperation,
  GenerationProvider,
  ImageAspectRatio,
  ImageAssetCategory,
  ImageOperation,
  ImagePromptConvention,
  ImageSubmissionPreview,
  Keyframe,
  KeyframeCharacterReference,
  KeyframePlan,
  KeyframePlanProposal,
  KeyframeSubmissionPreview,
  Location,
  LocationFixture,
  LocationImage,
  LocationImageKind,
  LocationKeyLight,
  LocationLibrary,
  LocationPlanProposal,
  LocationProduction,
  LocationState,
  ManifestField,
  ManifestOption,
  ManifestRecipe,
  ManifestRole,
  ManifestSlot,
  ManifestWidget,
  NarrationCue,
  NarrationLanguage,
  NarrationReviewProposal,
  NarrationTrack,
  NarratorProfile,
  NarratorVoice,
  PanoramaCaptureSource,
  PlaygroundAsset,
  PlaygroundAssetAction,
  PlaygroundAssetOrigin,
  PlaygroundAssetOriginKind,
  PlaygroundAssetResult,
  PlaygroundAssetUsageReason,
  PlaygroundCapabilityId,
  PlaygroundCapabilityInfo,
  PlaygroundCommandReceipt,
  PlaygroundCopyToProjectResult,
  PlaygroundInputLabel,
  PlaygroundRecipe,
  PlaygroundRecipePreview,
  PlaygroundRun,
  PlaygroundRunAction,
  PlaygroundRunPhase,
  PlaygroundRunRecovery,
  PlaygroundSnapshot,
  PluginManifest,
  ProductionAvailability,
  ProductionAvailabilityEntry,
  ProjectAspectRatio,
  ProjectAsset,
  ProjectBootstrap,
  ProjectDetail,
  ProjectStatus,
  ProjectSummary,
  ProviderAvailability,
  ProviderCandidate,
  ProviderCapabilityId,
  ProviderCapabilityView,
  ProviderPluginView,
  ProviderRecipeView,
  ProviderSettingsView,
  ProviderToolView,
  RecipeBinding,
  RecipeInputLabel,
  RecipeInputs,
  ReferenceGeneration,
  ReferenceGenerationAction,
  ReferenceGenerationKind,
  ReferenceGenerationPhase,
  ReferenceLibraryProposal,
  ReferenceLibraryView,
  Scene,
  SceneAnimaticState,
  SceneFinalLanguageState,
  SceneFinalState,
  SegmentBoundary,
  SegmentBoundaryReason,
  SegmentKeyframes,
  SegmentVideo,
  Shot,
  ShotSegment,
  StartFrameExtraction,
  StructuredDirectorAction,
  StructuredDirectorDetail,
  StructuredDirectorScriptProposal,
  StructuredDirectorScriptRevisionProposal,
  StructuredDirectorSnapshot,
  StructuredDirectorStatus,
  SubmissionAttachment,
  VideoPlan,
  VideoPromptProposal,
  VideoRecipeOption,
  VideoRecipeState,
  VideoReferenceImagePlan,
  WorkflowAction,
  WorkflowSemantics,
  WorkflowState,
  WorkspaceCapabilities,
  WorkspaceLayers,
} from "./types";

export {
  hasExactKeys,
  isId,
  isIdArray,
  isNonEmptyString,
  isNonNegativeInteger,
  isNullableNonNegativeInteger,
  isPositiveInteger,
  isRecord,
  isStringFields,
  isThreadId,
  isVideoSeed,
} from "./schema_check";
export { editableScenePayload } from "./refine";

const schemas: Record<string, JsonSchema> = {
  "Id": {
    "type": "string",
    "pattern": "^[0-9a-f]{32}$"
  },
  "AgentMessageRole": {
    "enum": [
      "user",
      "agent",
      "system"
    ]
  },
  "ProjectStatus": {
    "enum": [
      "active",
      "needs_recovery"
    ]
  },
  "ProjectAspectRatio": {
    "enum": [
      "16:9",
      "9:16",
      "2:1"
    ]
  },
  "ProviderCapabilityId": {
    "enum": [
      "image.generate",
      "image.edit",
      "voice.design",
      "speech.synthesize",
      "speech.recognize",
      "video.generate",
      "video.upscale",
      "audio.generate",
      "audio.separate"
    ]
  },
  "ManifestWidget": {
    "enum": [
      "text",
      "prompt",
      "number",
      "slider",
      "enum",
      "preset",
      "toggle",
      "seed",
      "audio_stem",
      "vector",
      "asset_slot",
      "asset_list"
    ]
  },
  "ManifestRole": {
    "enum": [
      "first_frame",
      "last_frame",
      "reference_image",
      "reference_audio",
      "reference_video",
      "voice_reference",
      "voice_transcript",
      "edit_source",
      "source_video",
      "source_audio",
      "prompt",
      "speech_text",
      "language",
      "duration",
      "aspect_ratio",
      "seed",
      "audio_stem"
    ]
  },
  "NarrationLanguage": {
    "enum": [
      "zh",
      "en"
    ]
  },
  "StructuredDirectorAction": {
    "enum": [
      "edit_director_plan",
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
      "edit_dialogue_audio",
      "generate_dialogue",
      "generate_dialogue_batch",
      "select_dialogue_audio",
      "set_dialogue_timing",
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
      "reopen_video_production"
    ]
  },
  "StructuredDirectorStatus": {
    "enum": [
      "awaiting_reference_proposal",
      "reviewing_references",
      "reviewing_script",
      "reviewing_narration",
      "reviewing_keyframes",
      "reviewing_videos",
      "reviewing_final",
      "approved"
    ]
  },
  "DirectorRunKind": {
    "enum": [
      "reference_proposal",
      "script_proposal",
      "script_edit",
      "narration_edit",
      "keyframe_plan",
      "location_plan",
      "director"
    ]
  },
  "ActiveDirectorRunStatus": {
    "enum": [
      "running",
      "waiting_user",
      "waiting_jobs"
    ]
  },
  "SegmentBoundaryReason": {
    "enum": [
      "model_constraint",
      "continuity_anchor",
      "control_boundary",
      "failure_cost"
    ]
  },
  "ImageOperation": {
    "enum": [
      "generate",
      "edit"
    ]
  },
  "ImageAspectRatio": {
    "enum": [
      "16:9",
      "9:16",
      "2:1",
      "1:2",
      "1:1",
      "3:2",
      "2:3",
      "4:3",
      "3:4",
      "5:4",
      "4:5",
      "21:9",
      "9:21",
      "3:1",
      "1:3"
    ]
  },
  "AssetUsageReasonCode": {
    "enum": [
      "character_reference_image",
      "character_voice_reference",
      "narrator_voice_reference",
      "narration_audio",
      "dialogue_audio",
      "location_image",
      "keyframe_reference_image",
      "keyframe_selected_asset",
      "segment_video_selected",
      "segment_video_upscaled",
      "segment_video_input_image",
      "segment_video_input_audio",
      "segment_video_input_video",
      "final_assembly",
      "visible_candidate",
      "unfinished_generation_input",
      "director_wait"
    ]
  },
  "ImageAssetCategory": {
    "enum": [
      "character_reference",
      "location_image",
      "panorama_capture",
      "keyframe",
      "video_frame"
    ]
  },
  "AssetAction": {
    "enum": [
      "audio_trim",
      "audio_effect",
      "audio_editor",
      "video_frame",
      "delete"
    ]
  },
  "AudioEffectPreset": {
    "enum": [
      "walkie_talkie",
      "military_radio",
      "weak_signal",
      "bad_signal",
      "dying_transmission"
    ]
  },
  "ReferenceGenerationKind": {
    "enum": [
      "character_look_sheet",
      "character_voice",
      "narrator_voice",
      "narration_audio",
      "dialogue_audio",
      "generated_audio",
      "audio_effect",
      "audio_trim",
      "video_audio_voice",
      "video_audio_background",
      "video_audio_remix",
      "location_image",
      "panorama_capture",
      "keyframe_image",
      "video_reference_image",
      "segment_video",
      "video_frame",
      "video_upscale",
      "final_video",
      "scene_final_video",
      "scene_animatic"
    ]
  },
  "GenerationOperation": {
    "enum": [
      "generate",
      "edit",
      "attach",
      "voice_design",
      "synthesize",
      "render",
      "upscale",
      "assemble",
      "process",
      "separate",
      "remix"
    ]
  },
  "ReferenceGenerationPhase": {
    "enum": [
      "submitting",
      "submission_uncertain",
      "queued",
      "running",
      "succeeded",
      "failed",
      "cancelled"
    ]
  },
  "ReferenceGenerationAction": {
    "enum": [
      "attach_output",
      "select_look_sheet",
      "select_output",
      "select_narration_audio",
      "select_dialogue_audio",
      "select_segment_video",
      "attach_upscaled_video",
      "select_final_video",
      "dismiss_history",
      "cancel",
      "retry"
    ]
  },
  "MediaType": {
    "enum": [
      "image/png",
      "image/jpeg",
      "image/webp",
      "audio/wav",
      "video/mp4"
    ]
  },
  "WorkspaceCapability": {
    "enum": [
      "narration",
      "keyframe",
      "video",
      "final"
    ]
  },
  "LocationImageKind": {
    "enum": [
      "image",
      "panorama"
    ]
  },
  "ProjectSummary": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "title": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "aspect_ratio": {
        "$ref": "ProjectAspectRatio"
      },
      "updated_at": {
        "type": "string",
        "x-datetime": true
      },
      "status": {
        "$ref": "ProjectStatus"
      }
    },
    "required": [
      "id",
      "title",
      "aspect_ratio",
      "updated_at",
      "status"
    ],
    "additionalProperties": false
  },
  "ProjectBootstrap": {
    "type": "object",
    "properties": {
      "projects": {
        "type": "array",
        "items": {
          "$ref": "ProjectSummary"
        }
      }
    },
    "required": [
      "projects"
    ],
    "additionalProperties": false
  },
  "ManifestOption": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "label": {
        "type": "string"
      }
    },
    "required": [
      "id",
      "label"
    ],
    "additionalProperties": false
  },
  "ManifestField": {
    "type": "object",
    "properties": {
      "key": {
        "type": "string"
      },
      "widget": {
        "$ref": "ManifestWidget"
      },
      "label": {
        "type": "string"
      },
      "default": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "number"
          },
          {
            "type": "boolean"
          },
          {
            "type": "null"
          },
          {
            "type": "array",
            "items": {
              "type": "number"
            }
          }
        ]
      },
      "nullable": {
        "type": "boolean"
      },
      "advanced": {
        "type": "boolean"
      },
      "options": {
        "type": "array",
        "items": {
          "$ref": "ManifestOption"
        }
      },
      "minimum": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "null"
          }
        ]
      },
      "maximum": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "null"
          }
        ]
      },
      "max_length": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ]
      },
      "min_length": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ]
      },
      "dimension": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ]
      },
      "component_labels": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "role": {
        "anyOf": [
          {
            "$ref": "ManifestRole"
          },
          {
            "type": "null"
          }
        ]
      },
      "help": {
        "type": "string"
      }
    },
    "required": [
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
      "help"
    ],
    "additionalProperties": false
  },
  "ManifestSlot": {
    "type": "object",
    "properties": {
      "key": {
        "type": "string"
      },
      "role": {
        "$ref": "ManifestRole"
      },
      "label": {
        "type": "string"
      },
      "minimum": {
        "type": "integer",
        "minimum": 0
      },
      "maximum": {
        "type": "integer",
        "minimum": 0
      },
      "media_types": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "duration_seconds": {
        "anyOf": [
          {
            "type": "array",
            "items": {
              "type": "number"
            }
          },
          {
            "type": "null"
          }
        ]
      },
      "describe": {
        "enum": [
          "required",
          "optional",
          "none"
        ]
      },
      "unique": {
        "type": "boolean"
      },
      "namespace": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "key",
      "role",
      "label",
      "minimum",
      "maximum",
      "media_types",
      "duration_seconds",
      "describe",
      "unique",
      "namespace"
    ],
    "additionalProperties": false
  },
  "ManifestRecipe": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "capability": {
        "$ref": "ProviderCapabilityId"
      },
      "label": {
        "type": "string"
      },
      "slots": {
        "type": "array",
        "items": {
          "$ref": "ManifestSlot"
        }
      },
      "params": {
        "type": "array",
        "items": {
          "$ref": "ManifestField"
        }
      },
      "require_any": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "label_namespaces": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "skills": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "distinct_slots": {
        "type": "array",
        "items": {
          "type": "string"
        }
      }
    },
    "required": [
      "id",
      "capability",
      "label",
      "slots",
      "params",
      "require_any",
      "label_namespaces",
      "skills",
      "distinct_slots"
    ],
    "additionalProperties": false
  },
  "ImagePromptConvention": {
    "type": "object",
    "properties": {
      "namespace": {
        "type": "string"
      },
      "single_image_label": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "aspect_ratio_in_prompt": {
        "type": "boolean"
      }
    },
    "required": [
      "namespace",
      "single_image_label",
      "aspect_ratio_in_prompt"
    ],
    "additionalProperties": false
  },
  "PluginManifest": {
    "type": "object",
    "properties": {
      "plugin_id": {
        "type": "string"
      },
      "plugin_version": {
        "type": "integer",
        "minimum": 1
      },
      "label": {
        "type": "string"
      },
      "settings": {
        "type": "array",
        "items": {
          "$ref": "ManifestField"
        }
      },
      "hints": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "recipes": {
        "type": "array",
        "items": {
          "$ref": "ManifestRecipe"
        }
      },
      "defaults": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "image_prompt": {
        "anyOf": [
          {
            "$ref": "ImagePromptConvention"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "plugin_id",
      "plugin_version",
      "label",
      "settings",
      "hints",
      "recipes",
      "defaults",
      "image_prompt"
    ],
    "additionalProperties": false
  },
  "ProviderRecipeView": {
    "type": "object",
    "properties": {
      "capability": {
        "$ref": "ProviderCapabilityId"
      },
      "plugin_id": {
        "type": "string"
      },
      "plugin_label": {
        "type": "string"
      },
      "recipe": {
        "$ref": "ManifestRecipe"
      },
      "editable_params": {
        "type": "array",
        "items": {
          "$ref": "ManifestField"
        }
      },
      "settings_summary": {
        "type": "string"
      },
      "hints": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      }
    },
    "required": [
      "capability",
      "plugin_id",
      "plugin_label",
      "recipe",
      "editable_params",
      "settings_summary",
      "hints"
    ],
    "additionalProperties": false
  },
  "ProviderCandidate": {
    "type": "object",
    "properties": {
      "plugin_id": {
        "type": "string"
      },
      "label": {
        "type": "string"
      }
    },
    "required": [
      "plugin_id",
      "label"
    ],
    "additionalProperties": false
  },
  "ProviderCapabilityView": {
    "type": "object",
    "properties": {
      "id": {
        "$ref": "ProviderCapabilityId"
      },
      "label": {
        "type": "string"
      },
      "bound_plugin_id": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "candidates": {
        "type": "array",
        "items": {
          "$ref": "ProviderCandidate"
        }
      },
      "message": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "label",
      "bound_plugin_id",
      "candidates",
      "message"
    ],
    "additionalProperties": false
  },
  "ProviderPluginView": {
    "type": "object",
    "properties": {
      "plugin_id": {
        "type": "string"
      },
      "plugin_version": {
        "type": "integer",
        "minimum": 1
      },
      "label": {
        "type": "string"
      },
      "endpoint": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "manifest": {
        "$ref": "PluginManifest"
      },
      "settings": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "settings_summary": {
        "type": "string"
      },
      "settings_error": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "plugin_id",
      "plugin_version",
      "label",
      "endpoint",
      "manifest",
      "settings",
      "settings_summary",
      "settings_error"
    ],
    "additionalProperties": false
  },
  "ProviderToolView": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "label": {
        "type": "string"
      },
      "available": {
        "type": "boolean"
      }
    },
    "required": [
      "id",
      "label",
      "available"
    ],
    "additionalProperties": false
  },
  "ProviderSettingsView": {
    "type": "object",
    "properties": {
      "capabilities": {
        "type": "array",
        "items": {
          "$ref": "ProviderCapabilityView"
        }
      },
      "plugins": {
        "type": "array",
        "items": {
          "$ref": "ProviderPluginView"
        }
      },
      "tools": {
        "type": "array",
        "items": {
          "$ref": "ProviderToolView"
        }
      }
    },
    "required": [
      "capabilities",
      "plugins",
      "tools"
    ],
    "additionalProperties": false
  },
  "ProjectDetail": {
    "type": "object",
    "properties": {
      "project": {
        "$ref": "ProjectSummary"
      },
      "structured_director": {
        "$ref": "StructuredDirectorSnapshot"
      }
    },
    "required": [
      "project",
      "structured_director"
    ],
    "additionalProperties": false
  },
  "ActiveDirectorRun": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "kind": {
        "$ref": "DirectorRunKind"
      },
      "status": {
        "$ref": "ActiveDirectorRunStatus"
      },
      "waiting_reason": {
        "anyOf": [
          {
            "type": "string",
            "minLength": 1
          },
          {
            "type": "null"
          }
        ]
      },
      "created_at": {
        "type": "string"
      },
      "updated_at": {
        "type": "string"
      }
    },
    "required": [
      "id",
      "kind",
      "status",
      "waiting_reason",
      "created_at",
      "updated_at"
    ],
    "additionalProperties": false
  },
  "CharacterLook": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "appearance": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "usage": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "selected_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "name",
      "appearance",
      "usage",
      "selected_asset_id"
    ],
    "additionalProperties": false
  },
  "DialogueLine": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "character_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "speaker_label": {
        "anyOf": [
          {
            "type": "string",
            "minLength": 1,
            "x-trimmed-nonempty": true
          },
          {
            "type": "null"
          }
        ]
      },
      "voice_description": {
        "anyOf": [
          {
            "type": "string",
            "minLength": 1,
            "x-trimmed-nonempty": true
          },
          {
            "type": "null"
          }
        ]
      },
      "text": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "delivery": {
        "type": "string"
      }
    },
    "required": [
      "id",
      "character_id",
      "speaker_label",
      "voice_description",
      "text",
      "delivery"
    ],
    "additionalProperties": false
  },
  "DialogueAudio": {
    "type": "object",
    "properties": {
      "dialogue_line_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "seed": {
        "type": "integer",
        "minimum": 0,
        "maximum": 4294967295
      },
      "recipe_params": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "selected_audio_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "start_seconds": {
        "anyOf": [
          {
            "type": "number",
            "minimum": 0,
            "x-finite": true
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "dialogue_line_id",
      "seed",
      "recipe_params",
      "selected_audio_asset_id",
      "start_seconds"
    ],
    "additionalProperties": false
  },
  "DialoguePlan": {
    "type": "object",
    "properties": {
      "source_script_revision": {
        "type": "integer",
        "minimum": 1
      },
      "items": {
        "type": "array",
        "items": {
          "$ref": "DialogueAudio"
        }
      }
    },
    "required": [
      "source_script_revision",
      "items"
    ],
    "additionalProperties": false
  },
  "SegmentBoundary": {
    "type": "object",
    "properties": {
      "reason": {
        "$ref": "SegmentBoundaryReason"
      },
      "continuity_instruction": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      }
    },
    "required": [
      "reason",
      "continuity_instruction"
    ],
    "additionalProperties": false
  },
  "ShotSegment": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "shot_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "minItems": 1,
        "uniqueItems": true
      },
      "duration_estimate_seconds": {
        "type": "number",
        "minimum": 0.2,
        "x-finite": true
      },
      "action": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "dialogue_lines": {
        "type": "array",
        "items": {
          "$ref": "DialogueLine"
        }
      },
      "boundary_from_previous": {
        "anyOf": [
          {
            "$ref": "SegmentBoundary"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "shot_ids",
      "duration_estimate_seconds",
      "action",
      "dialogue_lines",
      "boundary_from_previous"
    ],
    "additionalProperties": false
  },
  "Shot": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "visible_character_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "uniqueItems": true
      },
      "composition": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "camera_movement": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "action": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "audio_direction": {
        "type": "string"
      },
      "transition_in": {
        "anyOf": [
          {
            "type": "string",
            "minLength": 1,
            "x-trimmed-nonempty": true
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "visible_character_ids",
      "composition",
      "camera_movement",
      "action",
      "audio_direction",
      "transition_in"
    ],
    "additionalProperties": false
  },
  "SceneAnimaticState": {
    "type": "object",
    "properties": {
      "reason": {
        "type": "string"
      },
      "provider_available": {
        "type": "boolean"
      },
      "ready": {
        "type": "boolean"
      },
      "active_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "latest_succeeded_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "reason",
      "provider_available",
      "ready",
      "active_generation_id",
      "latest_succeeded_generation_id"
    ],
    "additionalProperties": false
  },
  "SceneFinalLanguageState": {
    "type": "object",
    "properties": {
      "active_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "latest_succeeded_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "current_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "outdated": {
        "type": "boolean"
      }
    },
    "required": [
      "active_generation_id",
      "latest_succeeded_generation_id",
      "current_asset_id",
      "outdated"
    ],
    "additionalProperties": false
  },
  "SceneFinalState": {
    "type": "object",
    "properties": {
      "reason": {
        "type": "string"
      },
      "provider_available": {
        "type": "boolean"
      },
      "ready": {
        "type": "boolean"
      },
      "zh": {
        "anyOf": [
          {
            "$ref": "SceneFinalLanguageState"
          },
          {
            "type": "null"
          }
        ]
      },
      "en": {
        "anyOf": [
          {
            "$ref": "SceneFinalLanguageState"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "reason",
      "provider_available",
      "ready",
      "zh",
      "en"
    ],
    "additionalProperties": false
  },
  "Scene": {
    "type": "object",
    "properties": {
      "location_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "state_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "driver": {
        "enum": [
          "narration",
          "drama"
        ]
      },
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "title": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "summary": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "setting": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "shots": {
        "type": "array",
        "items": {
          "$ref": "Shot"
        }
      },
      "segments": {
        "type": "array",
        "items": {
          "$ref": "ShotSegment"
        }
      },
      "narration_cues": {
        "type": "array",
        "items": {
          "$ref": "NarrationCue"
        }
      },
      "animatic": {
        "$ref": "SceneAnimaticState"
      },
      "scene_final": {
        "$ref": "SceneFinalState"
      }
    },
    "required": [
      "location_id",
      "state_id",
      "driver",
      "id",
      "title",
      "summary",
      "setting",
      "shots",
      "segments",
      "narration_cues"
    ],
    "additionalProperties": false
  },
  "NarrationTrack": {
    "type": "object",
    "properties": {
      "text": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "seed": {
        "type": "integer"
      },
      "selected_audio_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "recipe_params": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "selected_duration_seconds": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "text",
      "seed",
      "selected_audio_asset_id",
      "recipe_params",
      "selected_duration_seconds"
    ],
    "additionalProperties": false
  },
  "NarrationCue": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "zh": {
        "anyOf": [
          {
            "$ref": "NarrationTrack"
          },
          {
            "type": "null"
          }
        ]
      },
      "en": {
        "anyOf": [
          {
            "$ref": "NarrationTrack"
          },
          {
            "type": "null"
          }
        ]
      },
      "timing_language": {
        "anyOf": [
          {
            "$ref": "NarrationLanguage"
          },
          {
            "type": "null"
          }
        ]
      },
      "timing_seconds": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "zh",
      "en",
      "timing_language",
      "timing_seconds"
    ],
    "additionalProperties": false
  },
  "DirectorScript": {
    "type": "object",
    "properties": {
      "revision": {
        "type": "integer",
        "minimum": 1
      },
      "source_reference_revision": {
        "type": "integer",
        "minimum": 1
      },
      "production_baseline_revision": {
        "anyOf": [
          {
            "type": "integer",
            "minimum": 1
          },
          {
            "type": "null"
          }
        ]
      },
      "production_baseline_scenes": {
        "anyOf": [
          {
            "type": "array",
            "items": {
              "$ref": "Scene"
            },
            "minItems": 1
          },
          {
            "type": "null"
          }
        ]
      },
      "scenes": {
        "type": "array",
        "items": {
          "$ref": "Scene"
        },
        "minItems": 1
      }
    },
    "required": [
      "revision",
      "source_reference_revision",
      "production_baseline_revision",
      "production_baseline_scenes",
      "scenes"
    ],
    "additionalProperties": false
  },
  "LocationProduction": {
    "type": "object",
    "properties": {
      "status": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "status_label": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "reason": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "generation_step": {
        "enum": [
          "image",
          "capture"
        ]
      },
      "generate_label": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "active_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "candidate_generation_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "selectable_generation_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "enum": [
            "generate",
            "select",
            "select_asset",
            "edit",
            "delete",
            "clear_selection",
            "preview_panorama"
          ]
        }
      }
    },
    "required": [
      "status",
      "status_label",
      "reason",
      "generation_step",
      "generate_label",
      "active_generation_id",
      "candidate_generation_ids",
      "selectable_generation_ids",
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "LocationFixture": {
    "type": "object",
    "properties": {
      "allowed_actions": {
        "type": "array",
        "items": {
          "enum": [
            "edit",
            "delete"
          ]
        }
      },
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "description": {
        "type": "string"
      }
    },
    "required": [
      "id",
      "name",
      "description",
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "LocationKeyLight": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      }
    },
    "required": [
      "description"
    ],
    "additionalProperties": false
  },
  "PanoramaCaptureSource": {
    "type": "object",
    "properties": {
      "panorama_image_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "yaw_deg": {
        "type": "number"
      },
      "pitch_deg": {
        "type": "number"
      },
      "hfov_deg": {
        "type": "number"
      }
    },
    "required": [
      "panorama_image_id",
      "yaw_deg",
      "pitch_deg",
      "hfov_deg"
    ],
    "additionalProperties": false
  },
  "LocationImage": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "kind": {
        "$ref": "LocationImageKind"
      },
      "description": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "prompt_text": {
        "type": "string",
        "maxLength": 19000
      },
      "reference_asset_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "uniqueItems": true,
        "maxItems": 5
      },
      "selected_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "source": {
        "anyOf": [
          {
            "$ref": "PanoramaCaptureSource"
          },
          {
            "type": "null"
          }
        ]
      },
      "production": {
        "$ref": "LocationProduction"
      }
    },
    "required": [
      "id",
      "name",
      "kind",
      "description",
      "prompt_text",
      "reference_asset_ids",
      "selected_asset_id",
      "source",
      "production"
    ],
    "additionalProperties": false
  },
  "LocationState": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "description": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "enum": [
            "edit",
            "delete"
          ]
        }
      }
    },
    "required": [
      "id",
      "name",
      "description",
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "Location": {
    "type": "object",
    "properties": {
      "allowed_actions": {
        "type": "array",
        "items": {
          "enum": [
            "edit",
            "delete",
            "create_image",
            "create_fixture",
            "create_state"
          ]
        }
      },
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "description": {
        "type": "string",
        "maxLength": 4000
      },
      "fixtures": {
        "type": "array",
        "items": {
          "$ref": "LocationFixture"
        },
        "maxItems": 40
      },
      "key_light": {
        "anyOf": [
          {
            "$ref": "LocationKeyLight"
          },
          {
            "type": "null"
          }
        ]
      },
      "states": {
        "type": "array",
        "items": {
          "$ref": "LocationState"
        },
        "maxItems": 10
      },
      "images": {
        "type": "array",
        "items": {
          "$ref": "LocationImage"
        },
        "maxItems": 200
      }
    },
    "required": [
      "id",
      "name",
      "description",
      "fixtures",
      "key_light",
      "states",
      "images",
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "LocationLibrary": {
    "type": "object",
    "properties": {
      "locations": {
        "type": "array",
        "items": {
          "$ref": "Location"
        },
        "maxItems": 200
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "enum": [
            "create_location",
            "bind_scene"
          ]
        }
      }
    },
    "required": [
      "locations",
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "Keyframe": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "owner_segment_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "predecessor_keyframe_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "prompt_text": {
        "type": "string",
        "maxLength": 18000
      },
      "visible_character_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "uniqueItems": true
      },
      "character_references": {
        "type": "array",
        "items": {
          "$ref": "KeyframeCharacterReference"
        }
      },
      "selected_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "owner_segment_id",
      "predecessor_keyframe_id",
      "prompt_text",
      "visible_character_ids",
      "character_references",
      "selected_asset_id"
    ],
    "additionalProperties": false
  },
  "KeyframeCharacterReference": {
    "type": "object",
    "properties": {
      "character_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "look_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "character_id",
      "look_id"
    ],
    "additionalProperties": false
  },
  "StartFrameExtraction": {
    "type": "object",
    "properties": {
      "source_segment_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "source_video_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "state": {
        "enum": [
          "ready",
          "unavailable",
          "shared_boundary",
          "waiting_source_video",
          "source_not_current"
        ]
      },
      "message": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      }
    },
    "required": [
      "source_segment_id",
      "source_video_asset_id",
      "state",
      "message"
    ],
    "additionalProperties": false
  },
  "SegmentKeyframes": {
    "type": "object",
    "properties": {
      "segment_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "start_keyframe_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "end_keyframe_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "start_enabled": {
        "type": "boolean"
      },
      "end_enabled": {
        "type": "boolean"
      },
      "reference_asset_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "start_frame_extraction": {
        "$ref": "StartFrameExtraction"
      }
    },
    "required": [
      "segment_id",
      "start_keyframe_id",
      "end_keyframe_id",
      "start_enabled",
      "end_enabled",
      "reference_asset_ids",
      "start_frame_extraction"
    ],
    "additionalProperties": false
  },
  "KeyframePlan": {
    "type": "object",
    "properties": {
      "source_script_revision": {
        "type": "integer",
        "minimum": 1
      },
      "keyframes": {
        "type": "array",
        "items": {
          "$ref": "Keyframe"
        },
        "minItems": 1
      },
      "segments": {
        "type": "array",
        "items": {
          "$ref": "SegmentKeyframes"
        },
        "minItems": 1
      }
    },
    "required": [
      "source_script_revision",
      "keyframes",
      "segments"
    ],
    "additionalProperties": false
  },
  "RecipeBinding": {
    "type": "object",
    "properties": {
      "asset_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "description": {
        "anyOf": [
          {
            "type": "string",
            "maxLength": 2000
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "asset_id",
      "description"
    ],
    "additionalProperties": false
  },
  "RecipeInputs": {
    "type": "object",
    "properties": {
      "bindings": {
        "type": "object",
        "additionalProperties": {
          "type": "array",
          "items": {
            "$ref": "RecipeBinding"
          }
        }
      },
      "params": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      }
    },
    "required": [
      "bindings",
      "params"
    ],
    "additionalProperties": false
  },
  "VideoRecipeOption": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "label": {
        "type": "string"
      },
      "allowed": {
        "type": "boolean"
      },
      "reason": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "label",
      "allowed",
      "reason"
    ],
    "additionalProperties": false
  },
  "RecipeInputLabel": {
    "type": "object",
    "properties": {
      "slot": {
        "type": "string"
      },
      "role": {
        "$ref": "ManifestRole"
      },
      "index": {
        "type": "integer"
      },
      "asset_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "description": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "label": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "slot",
      "role",
      "index",
      "asset_id",
      "description",
      "label"
    ],
    "additionalProperties": false
  },
  "VideoRecipeState": {
    "type": "object",
    "properties": {
      "available": {
        "type": "boolean"
      },
      "ready": {
        "type": "boolean"
      },
      "reason": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "options": {
        "type": "array",
        "items": {
          "$ref": "VideoRecipeOption"
        }
      },
      "duration_seconds": {
        "type": "number"
      },
      "soft_duration_limit_seconds": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "null"
          }
        ]
      },
      "bindings": {
        "type": "array",
        "items": {
          "$ref": "RecipeInputLabel"
        }
      },
      "dialogue_audio": {
        "anyOf": [
          {
            "type": "object",
            "properties": {
              "slot": {
                "type": "string",
                "minLength": 1,
                "x-trimmed-nonempty": true
              },
              "bindings": {
                "type": "array",
                "items": {
                  "$ref": "RecipeBinding"
                }
              },
              "replace_asset_ids": {
                "type": "array",
                "items": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                }
              },
              "error": {
                "anyOf": [
                  {
                    "type": "string"
                  },
                  {
                    "type": "null"
                  }
                ]
              }
            },
            "required": [
              "slot",
              "bindings",
              "replace_asset_ids",
              "error"
            ],
            "additionalProperties": false
          },
          {
            "type": "null"
          }
        ]
      },
      "slot_labels": {
        "type": "object",
        "additionalProperties": {
          "type": "array",
          "items": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          }
        }
      }
    },
    "required": [
      "available",
      "ready",
      "reason",
      "options",
      "duration_seconds",
      "soft_duration_limit_seconds",
      "bindings",
      "slot_labels",
      "dialogue_audio"
    ],
    "additionalProperties": false
  },
  "VideoReferenceImagePlan": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "recipe_id": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "slot_index": {
        "type": "integer",
        "minimum": 0,
        "maximum": 3
      },
      "prompt_text": {
        "type": "string",
        "maxLength": 18000
      },
      "description": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "visible_character_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "character_references": {
        "type": "array",
        "items": {
          "$ref": "KeyframeCharacterReference"
        }
      },
      "reference_asset_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "maxItems": 5
      }
    },
    "required": [
      "id",
      "recipe_id",
      "slot_index",
      "prompt_text",
      "description",
      "visible_character_ids",
      "character_references",
      "reference_asset_ids"
    ],
    "additionalProperties": false
  },
  "SegmentVideo": {
    "type": "object",
    "properties": {
      "segment_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "prompt_text": {
        "type": "string",
        "maxLength": 20000
      },
      "active_recipe": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "recipe_state": {
        "$ref": "VideoRecipeState"
      },
      "reference_images": {
        "type": "array",
        "items": {
          "$ref": "VideoReferenceImagePlan"
        }
      },
      "recipes": {
        "type": "object",
        "additionalProperties": {
          "$ref": "RecipeInputs"
        }
      },
      "selected_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "upscaled_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "segment_id",
      "prompt_text",
      "active_recipe",
      "recipe_state",
      "recipes",
      "selected_asset_id",
      "upscaled_asset_id"
    ],
    "additionalProperties": false
  },
  "VideoPlan": {
    "type": "object",
    "properties": {
      "source_script_revision": {
        "type": "integer",
        "minimum": 1
      },
      "segments": {
        "type": "array",
        "items": {
          "$ref": "SegmentVideo"
        },
        "minItems": 1
      }
    },
    "required": [
      "source_script_revision",
      "segments"
    ],
    "additionalProperties": false
  },
  "FinalAssemblyClip": {
    "type": "object",
    "properties": {
      "scene_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "zh_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "en_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "transition_from_previous": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "const": "seam_blend"
          }
        ]
      }
    },
    "required": [
      "scene_id",
      "zh_asset_id",
      "en_asset_id",
      "transition_from_previous"
    ],
    "additionalProperties": false
  },
  "FinalAssemblyPlan": {
    "type": "object",
    "properties": {
      "source_script_revision": {
        "type": "integer",
        "minimum": 1
      },
      "clips": {
        "type": "array",
        "items": {
          "$ref": "FinalAssemblyClip"
        },
        "minItems": 1
      },
      "selected_zh_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "selected_en_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "source_script_revision",
      "clips",
      "selected_zh_asset_id",
      "selected_en_asset_id"
    ],
    "additionalProperties": false
  },
  "FinalApproval": {
    "type": "object",
    "properties": {
      "zh_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "zh_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "en_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "en_generation_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "source_script_revision": {
        "type": "integer",
        "minimum": 1
      },
      "approved_project_revision": {
        "type": "integer",
        "minimum": 1
      }
    },
    "required": [
      "zh_asset_id",
      "zh_generation_id",
      "en_asset_id",
      "en_generation_id",
      "source_script_revision",
      "approved_project_revision"
    ],
    "additionalProperties": false
  },
  "AssetUsageReason": {
    "type": "object",
    "properties": {
      "code": {
        "$ref": "AssetUsageReasonCode"
      },
      "label": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      }
    },
    "required": [
      "code",
      "label"
    ],
    "additionalProperties": false
  },
  "ProjectAsset": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "media_type": {
        "$ref": "MediaType"
      },
      "image_category": {
        "anyOf": [
          {
            "$ref": "ImageAssetCategory"
          },
          {
            "type": "null"
          }
        ]
      },
      "byte_count": {
        "type": "integer",
        "minimum": 1
      },
      "duration_seconds": {
        "anyOf": [
          {
            "type": "number",
            "exclusiveMinimum": 0
          },
          {
            "type": "null"
          }
        ]
      },
      "display_name": {
        "type": "string"
      },
      "content_url": {
        "type": "string"
      },
      "is_in_use": {
        "type": "boolean"
      },
      "usage_reasons": {
        "type": "array",
        "items": {
          "$ref": "AssetUsageReason"
        }
      },
      "retains_derived_assets_on_delete": {
        "type": "boolean"
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "$ref": "AssetAction"
        },
        "uniqueItems": true
      }
    },
    "required": [
      "id",
      "media_type",
      "image_category",
      "byte_count",
      "duration_seconds",
      "content_url",
      "is_in_use",
      "usage_reasons",
      "retains_derived_assets_on_delete",
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "SubmissionAttachment": {
    "type": "object",
    "properties": {
      "asset_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "display_name": {
        "type": "string"
      },
      "content_url": {
        "type": "string"
      },
      "role": {
        "enum": [
          "source_image",
          "reference_image"
        ]
      },
      "input_roles": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "purpose": {
        "type": "string"
      }
    },
    "required": [
      "asset_id",
      "display_name",
      "content_url",
      "role",
      "input_roles",
      "purpose"
    ],
    "additionalProperties": false
  },
  "ImageSubmissionPreview": {
    "type": "object",
    "properties": {
      "reference_prompt": {
        "type": "string"
      },
      "instruction": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "ready": {
        "type": "boolean"
      },
      "operation": {
        "$ref": "ImageOperation"
      },
      "attachments": {
        "type": "array",
        "items": {
          "$ref": "SubmissionAttachment"
        }
      }
    },
    "required": [
      "reference_prompt",
      "instruction",
      "ready",
      "operation",
      "attachments"
    ],
    "additionalProperties": false
  },
  "GenerationProvider": {
    "type": "object",
    "properties": {
      "plugin_id": {
        "type": "string"
      },
      "recipe_id": {
        "type": "string"
      },
      "summary": {
        "type": "string"
      }
    },
    "required": [
      "plugin_id",
      "recipe_id",
      "summary"
    ],
    "additionalProperties": false
  },
  "ReferenceGeneration": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "kind": {
        "$ref": "ReferenceGenerationKind"
      },
      "operation": {
        "$ref": "GenerationOperation"
      },
      "target_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "phase": {
        "$ref": "ReferenceGenerationPhase"
      },
      "progress": {
        "type": "number",
        "minimum": 0,
        "maximum": 1
      },
      "message": {
        "type": "string"
      },
      "prompt_text": {
        "type": "string"
      },
      "input_asset_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "sample_text": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "language": {
        "anyOf": [
          {
            "$ref": "NarrationLanguage"
          },
          {
            "type": "null"
          }
        ]
      },
      "aspect_ratio": {
        "anyOf": [
          {
            "$ref": "ImageAspectRatio"
          },
          {
            "type": "null"
          }
        ]
      },
      "seed": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "string",
            "pattern": "^[0-9]{1,19}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "duration_seconds": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "null"
          }
        ]
      },
      "output_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "error_code": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "cancellation_requested": {
        "type": "boolean"
      },
      "retry_of": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "dismissed": {
        "type": "boolean"
      },
      "provider": {
        "anyOf": [
          {
            "$ref": "GenerationProvider"
          },
          {
            "type": "null"
          }
        ]
      },
      "inputs_outdated": {
        "type": "boolean"
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "$ref": "ReferenceGenerationAction"
        },
        "uniqueItems": true
      }
    },
    "required": [
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
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "WorkspaceLayers": {
    "type": "object",
    "properties": {
      "narration_unlocked": {
        "type": "boolean"
      },
      "keyframes_unlocked": {
        "type": "boolean"
      },
      "videos_unlocked": {
        "type": "boolean"
      },
      "final_assembly_unlocked": {
        "type": "boolean"
      }
    },
    "required": [
      "narration_unlocked",
      "keyframes_unlocked",
      "videos_unlocked",
      "final_assembly_unlocked"
    ],
    "additionalProperties": false
  },
  "ProviderAvailability": {
    "type": "object",
    "properties": {
      "image_generation": {
        "type": "boolean"
      },
      "voice_design": {
        "type": "boolean"
      },
      "speech_synthesis": {
        "type": "boolean"
      },
      "speech_recognition": {
        "type": "boolean"
      },
      "video_generation": {
        "type": "boolean"
      },
      "video_upscale": {
        "type": "boolean"
      },
      "final_assembly": {
        "type": "boolean"
      },
      "scene_animatic": {
        "type": "boolean"
      },
      "audio_separation": {
        "type": "boolean"
      },
      "audio_remix": {
        "type": "boolean"
      }
    },
    "required": [
      "image_generation",
      "voice_design",
      "speech_synthesis",
      "video_generation",
      "video_upscale",
      "final_assembly",
      "scene_animatic",
      "audio_separation",
      "audio_remix"
    ],
    "additionalProperties": false
  },
  "ReferenceLibraryView": {
    "type": "object",
    "properties": {
      "reviewed": {
        "type": "boolean"
      },
      "characters": {
        "type": "array",
        "items": {
          "$ref": "CharacterCard"
        }
      },
      "narrator": {
        "anyOf": [
          {
            "$ref": "NarratorProfile"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "characters",
      "narrator"
    ],
    "additionalProperties": false
  },
  "CharacterCard": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string"
      },
      "visual_description": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "voice_description": {
        "type": "string"
      },
      "voice_reference_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "voice_reference_transcript": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "looks": {
        "type": "array",
        "items": {
          "$ref": "CharacterLook"
        }
      }
    },
    "required": [
      "id",
      "name",
      "visual_description",
      "voice_description",
      "voice_reference_asset_id",
      "looks"
    ],
    "additionalProperties": false
  },
  "NarratorProfile": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "name": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "zh": {
        "anyOf": [
          {
            "$ref": "NarratorVoice"
          },
          {
            "type": "null"
          }
        ]
      },
      "en": {
        "anyOf": [
          {
            "$ref": "NarratorVoice"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "id",
      "name",
      "zh",
      "en"
    ],
    "additionalProperties": false
  },
  "NarratorVoice": {
    "type": "object",
    "properties": {
      "voice_description": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "voice_reference_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "voice_reference_transcript": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "voice_description",
      "voice_reference_asset_id",
      "voice_reference_transcript"
    ],
    "additionalProperties": false
  },
  "ProductionAvailabilityEntry": {
    "type": "object",
    "properties": {
      "unlocked": {
        "type": "boolean"
      },
      "reason": {
        "type": "string"
      },
      "next_location": {
        "const": "project"
      },
      "action": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "unlocked",
      "reason",
      "next_location",
      "action"
    ],
    "additionalProperties": false
  },
  "ProductionAvailability": {
    "type": "object",
    "properties": {
      "narration": {
        "$ref": "ProductionAvailabilityEntry"
      },
      "keyframes": {
        "$ref": "ProductionAvailabilityEntry"
      },
      "videos": {
        "$ref": "ProductionAvailabilityEntry"
      },
      "final": {
        "$ref": "ProductionAvailabilityEntry"
      }
    },
    "required": [
      "narration",
      "keyframes",
      "videos",
      "final"
    ],
    "additionalProperties": false
  },
  "WorkflowAction": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "tool": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "target_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "uniqueItems": true
      },
      "human_only": {
        "type": "boolean"
      },
      "requires_explicit_user_request": {
        "type": "boolean"
      }
    },
    "required": [
      "action",
      "tool",
      "target_ids",
      "human_only",
      "requires_explicit_user_request"
    ],
    "additionalProperties": true
  },
  "WorkflowSemantics": {
    "type": "object",
    "properties": {
      "current_stage": {
        "const": "primary_workflow_focus_not_capability_lock"
      },
      "active_task": {
        "const": "primary_workflow_task_only_parallel_activity_uses_task_discovery"
      },
      "required_next_actions": {
        "const": "primary_workflow_actions_only"
      }
    },
    "required": [
      "current_stage",
      "active_task",
      "required_next_actions"
    ],
    "additionalProperties": false
  },
  "WorkspaceCapabilities": {
    "type": "object",
    "properties": {
      "semantics": {
        "const": "cumulative_unlocked_layers_not_primary_workflow"
      },
      "unlocked": {
        "type": "array",
        "items": {
          "$ref": "WorkspaceCapability"
        },
        "uniqueItems": true
      }
    },
    "required": [
      "semantics",
      "unlocked"
    ],
    "additionalProperties": false
  },
  "ActivitySummary": {
    "type": "object",
    "properties": {
      "active_generation_count": {
        "type": "integer",
        "minimum": 0
      },
      "has_active_generations": {
        "type": "boolean"
      },
      "task_discovery_tool": {
        "const": "read_workflow"
      },
      "semantics": {
        "const": "parallel_project_activity_not_primary_workflow"
      }
    },
    "required": [
      "active_generation_count",
      "has_active_generations",
      "task_discovery_tool",
      "semantics"
    ],
    "additionalProperties": false
  },
  "BlockedActionReason": {
    "type": "object",
    "properties": {
      "reason": {
        "type": "string"
      }
    },
    "required": [
      "reason"
    ],
    "additionalProperties": false
  },
  "WorkflowState": {
    "type": "object",
    "properties": {
      "current_stage": {
        "type": "string"
      },
      "stage_status": {
        "type": "string"
      },
      "semantics": {
        "$ref": "WorkflowSemantics"
      },
      "required_next_actions": {
        "type": "array"
      },
      "recommended_next_actions": {
        "type": "array"
      },
      "blocking_prerequisites": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "blocked_actions": {
        "type": "object",
        "additionalProperties": {
          "$ref": "BlockedActionReason"
        },
        "properties": {}
      },
      "workspace_capabilities": {
        "$ref": "WorkspaceCapabilities"
      },
      "activity_summary": {
        "$ref": "ActivitySummary"
      },
      "requires_explicit_user_request": {
        "type": "boolean"
      },
      "active_task": {
        "anyOf": [
          {
            "type": "object",
            "additionalProperties": true,
            "properties": {}
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
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
      "active_task"
    ],
    "additionalProperties": false
  },
  "CapabilityGapAlert": {
    "type": "object",
    "properties": {
      "gap_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "run_id": {
        "type": "string"
      },
      "missing_command": {
        "type": "string"
      },
      "raw_user_request_summary": {
        "type": "string"
      },
      "target_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "scope_scene_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        }
      },
      "operation_summary": {
        "type": "string"
      },
      "old_revision": {
        "type": "integer",
        "minimum": 1
      },
      "new_revision": {
        "type": "integer",
        "minimum": 1
      },
      "result": {
        "enum": [
          "succeeded",
          "noop"
        ]
      },
      "first_occurred_at": {
        "type": "string"
      },
      "last_occurred_at": {
        "type": "string"
      },
      "occurrence_count": {
        "type": "integer",
        "minimum": 1
      },
      "closed_revision": {
        "anyOf": [
          {
            "type": "integer",
            "minimum": 1
          },
          {
            "type": "null"
          }
        ]
      },
      "closed_by_command": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "status": {
        "enum": [
          "open",
          "closed"
        ]
      }
    },
    "required": [
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
      "closed_by_command"
    ],
    "additionalProperties": false
  },
  "StructuredDirectorSnapshot": {
    "type": "object",
    "properties": {
      "status": {
        "$ref": "StructuredDirectorStatus"
      },
      "active_director_run": {
        "anyOf": [
          {
            "$ref": "ActiveDirectorRun"
          },
          {
            "type": "null"
          }
        ]
      },
      "revision": {
        "type": "integer",
        "minimum": 1
      },
      "aspect_ratio": {
        "$ref": "ProjectAspectRatio"
      },
      "director_plan_markdown": {
        "type": "string",
        "minLength": 1,
        "x-trimmed-nonempty": true
      },
      "narration_languages": {
        "type": "array",
        "items": {
          "$ref": "NarrationLanguage"
        },
        "minItems": 1,
        "maxItems": 2,
        "uniqueItems": true
      },
      "workspace_layers": {
        "$ref": "WorkspaceLayers"
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "$ref": "StructuredDirectorAction"
        },
        "uniqueItems": true
      },
      "workflow": {
        "$ref": "WorkflowState"
      },
      "provider_availability": {
        "$ref": "ProviderAvailability"
      },
      "assets": {
        "type": "array",
        "items": {
          "$ref": "ProjectAsset"
        }
      },
      "generations": {
        "type": "array",
        "items": {
          "$ref": "ReferenceGeneration"
        }
      },
      "reference_library": {
        "$ref": "ReferenceLibraryView"
      },
      "director_script": {
        "anyOf": [
          {
            "$ref": "DirectorScript"
          },
          {
            "type": "null"
          }
        ]
      },
      "dialogue_plan": {
        "anyOf": [
          {
            "$ref": "DialoguePlan"
          },
          {
            "type": "null"
          }
        ]
      },
      "production_availability": {
        "$ref": "ProductionAvailability"
      },
      "location_library": {
        "$ref": "LocationLibrary"
      },
      "keyframe_plan": {
        "anyOf": [
          {
            "$ref": "KeyframePlan"
          },
          {
            "type": "null"
          }
        ]
      },
      "video_plan": {
        "anyOf": [
          {
            "$ref": "VideoPlan"
          },
          {
            "type": "null"
          }
        ]
      },
      "final_assembly": {
        "anyOf": [
          {
            "$ref": "FinalAssemblyPlan"
          },
          {
            "type": "null"
          }
        ]
      },
      "final_approval": {
        "anyOf": [
          {
            "$ref": "FinalApproval"
          },
          {
            "type": "null"
          }
        ]
      },
      "capability_gap_alerts": {
        "type": "array",
        "items": {
          "$ref": "CapabilityGapAlert"
        }
      },
      "provider_recipes": {
        "type": "array",
        "items": {
          "$ref": "ProviderRecipeView"
        }
      }
    },
    "required": [
      "status",
      "active_director_run",
      "revision",
      "aspect_ratio",
      "director_plan_markdown",
      "narration_languages",
      "workspace_layers",
      "allowed_actions",
      "workflow",
      "provider_availability",
      "assets",
      "generations",
      "reference_library",
      "director_script",
      "dialogue_plan",
      "production_availability",
      "location_library",
      "keyframe_plan",
      "video_plan",
      "final_assembly",
      "final_approval",
      "capability_gap_alerts",
      "provider_recipes"
    ],
    "additionalProperties": false
  },
  "ApiErrorBody": {
    "type": "object",
    "properties": {
      "code": {
        "type": "string"
      },
      "message": {
        "type": "string"
      },
      "recoverable": {
        "type": "boolean"
      },
      "origin": {
        "type": "string"
      },
      "state_changed": {
        "anyOf": [
          {
            "type": "boolean"
          },
          {
            "const": "unknown"
          }
        ]
      },
      "retry_policy": {
        "type": "string"
      },
      "automatic_retry_allowed": {
        "type": "boolean"
      },
      "expected_revision": {
        "type": "integer",
        "minimum": 1
      },
      "current_revision": {
        "type": "integer",
        "minimum": 1
      }
    },
    "required": [
      "code",
      "message",
      "recoverable",
      "origin",
      "state_changed",
      "retry_policy",
      "automatic_retry_allowed"
    ],
    "additionalProperties": false
  },
  "ApiErrorPayload": {
    "type": "object",
    "properties": {
      "error": {
        "$ref": "ApiErrorBody"
      }
    },
    "required": [
      "error"
    ],
    "additionalProperties": false
  },
  "PlaygroundCapabilityId": {
    "type": "string",
    "minLength": 1,
    "maxLength": 128
  },
  "PlaygroundRunPhase": {
    "enum": [
      "submitting",
      "submission_uncertain",
      "queued",
      "running",
      "succeeded",
      "failed",
      "cancelled"
    ]
  },
  "PlaygroundRunAction": {
    "enum": [
      "cancel",
      "retry",
      "dismiss",
      "set_note"
    ]
  },
  "PlaygroundAssetAction": {
    "enum": [
      "delete",
      "copy_to_project",
      "video_frame",
      "pano_view"
    ]
  },
  "PlaygroundAssetOriginKind": {
    "enum": [
      "imported",
      "run_output",
      "copied_from_project"
    ]
  },
  "PlaygroundRecipe": {
    "type": "object",
    "properties": {
      "plugin_id": {
        "type": "string"
      },
      "plugin_label": {
        "type": "string"
      },
      "recipe": {
        "$ref": "ManifestRecipe"
      }
    },
    "required": [
      "plugin_id",
      "plugin_label",
      "recipe"
    ],
    "additionalProperties": false
  },
  "PlaygroundCapabilityInfo": {
    "type": "object",
    "properties": {
      "id": {
        "$ref": "PlaygroundCapabilityId"
      },
      "label": {
        "type": "string"
      },
      "execution": {
        "enum": [
          "async",
          "sync"
        ]
      },
      "group": {
        "enum": [
          "image",
          "speech",
          "video",
          "audio"
        ]
      },
      "available": {
        "type": "boolean"
      },
      "notes": {
        "type": "string"
      },
      "recipe": {
        "anyOf": [
          {
            "$ref": "PlaygroundRecipe"
          },
          {
            "type": "null"
          }
        ]
      },
      "parameters_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      }
    },
    "required": [
      "id",
      "label",
      "execution",
      "group",
      "available",
      "notes",
      "recipe"
    ],
    "additionalProperties": false
  },
  "PlaygroundAssetOrigin": {
    "anyOf": [
      {
        "type": "object",
        "properties": {
          "kind": {
            "const": "imported"
          }
        },
        "required": [
          "kind"
        ],
        "additionalProperties": false
      },
      {
        "type": "object",
        "properties": {
          "kind": {
            "const": "run_output"
          },
          "run_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          }
        },
        "required": [
          "kind",
          "run_id"
        ],
        "additionalProperties": false
      },
      {
        "type": "object",
        "properties": {
          "kind": {
            "const": "copied_from_project"
          },
          "project_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          "asset_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          }
        },
        "required": [
          "kind",
          "project_id",
          "asset_id"
        ],
        "additionalProperties": false
      }
    ]
  },
  "PlaygroundAssetUsageReason": {
    "type": "object",
    "properties": {
      "code": {
        "type": "string"
      },
      "label": {
        "type": "string"
      }
    },
    "required": [
      "code",
      "label"
    ],
    "additionalProperties": false
  },
  "PlaygroundAsset": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "media_type": {
        "$ref": "MediaType"
      },
      "byte_count": {
        "type": "integer",
        "minimum": 1
      },
      "sha256": {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$"
      },
      "relative_path": {
        "type": "string"
      },
      "duration_seconds": {
        "anyOf": [
          {
            "type": "number",
            "exclusiveMinimum": 0
          },
          {
            "type": "null"
          }
        ]
      },
      "origin": {
        "$ref": "PlaygroundAssetOrigin"
      },
      "created_at": {
        "type": "string"
      },
      "display_name": {
        "type": "string"
      },
      "content_url": {
        "type": "string"
      },
      "is_in_use": {
        "type": "boolean"
      },
      "usage_reasons": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundAssetUsageReason"
        }
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundAssetAction"
        },
        "uniqueItems": true
      }
    },
    "required": [
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
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "PlaygroundRunRecovery": {
    "type": "object",
    "properties": {
      "failure_origin": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "retry_policy": {
        "type": "string"
      },
      "automatic_retry_allowed": {
        "type": "boolean"
      }
    },
    "required": [
      "failure_origin",
      "retry_policy",
      "automatic_retry_allowed"
    ],
    "additionalProperties": false
  },
  "PlaygroundInputLabel": {
    "type": "object",
    "properties": {
      "label": {
        "type": "string"
      },
      "provider_input": {
        "type": "string"
      },
      "asset_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "description": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "label",
      "provider_input",
      "asset_id",
      "description"
    ],
    "additionalProperties": false
  },
  "PlaygroundRecipePreview": {
    "type": "object",
    "properties": {
      "ready": {
        "type": "boolean"
      },
      "reason": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "input_labels": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundInputLabel"
        }
      }
    },
    "required": [
      "ready",
      "reason",
      "input_labels"
    ],
    "additionalProperties": false
  },
  "PlaygroundRun": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "capability": {
        "$ref": "PlaygroundCapabilityId"
      },
      "capability_label": {
        "type": "string"
      },
      "phase": {
        "$ref": "PlaygroundRunPhase"
      },
      "progress": {
        "type": "number",
        "minimum": 0,
        "maximum": 1
      },
      "message": {
        "type": "string"
      },
      "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": true
      },
      "input_asset_ids": {
        "type": "array",
        "items": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "uniqueItems": true
      },
      "seed": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ]
      },
      "plugin_id": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "plugin_version": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ]
      },
      "external_id": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "output_asset_id": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "result": {
        "anyOf": [
          {
            "type": "object",
            "properties": {},
            "additionalProperties": true
          },
          {
            "type": "null"
          }
        ]
      },
      "error_code": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "cancellation_requested": {
        "type": "boolean"
      },
      "retry_of": {
        "anyOf": [
          {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$"
          },
          {
            "type": "null"
          }
        ]
      },
      "note": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "dismissed": {
        "type": "boolean"
      },
      "provider": {
        "anyOf": [
          {
            "$ref": "GenerationProvider"
          },
          {
            "type": "null"
          }
        ]
      },
      "created_at": {
        "type": "string"
      },
      "updated_at": {
        "type": "string"
      },
      "recovery": {
        "$ref": "PlaygroundRunRecovery"
      },
      "allowed_actions": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundRunAction"
        },
        "uniqueItems": true
      },
      "input_labels": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundInputLabel"
        }
      }
    },
    "required": [
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
      "allowed_actions"
    ],
    "additionalProperties": false
  },
  "PlaygroundSnapshot": {
    "type": "object",
    "properties": {
      "schema_version": {
        "type": "integer"
      },
      "revision": {
        "type": "integer",
        "minimum": 1
      },
      "capabilities": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundCapabilityInfo"
        }
      },
      "runs": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundRun"
        }
      },
      "assets": {
        "type": "array",
        "items": {
          "$ref": "PlaygroundAsset"
        }
      }
    },
    "required": [
      "schema_version",
      "revision",
      "capabilities",
      "runs",
      "assets"
    ],
    "additionalProperties": false
  },
  "PlaygroundCommandReceipt": {
    "type": "object",
    "properties": {
      "command_id": {
        "type": "string"
      },
      "status": {
        "enum": [
          "succeeded",
          "noop"
        ]
      },
      "old_revision": {
        "type": "integer",
        "minimum": 1
      },
      "new_revision": {
        "type": "integer",
        "minimum": 1
      },
      "decision_summary": {
        "type": "string"
      }
    },
    "required": [
      "command_id",
      "status",
      "old_revision",
      "new_revision",
      "decision_summary"
    ],
    "additionalProperties": false
  },
  "PlaygroundCopyToProjectResult": {
    "type": "object",
    "properties": {
      "asset_id": {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$"
      },
      "project_revision": {
        "type": "integer",
        "minimum": 1
      }
    },
    "required": [
      "asset_id",
      "project_revision"
    ],
    "additionalProperties": false
  },
  "PlaygroundAssetResult": {
    "type": "object",
    "properties": {
      "asset": {
        "$ref": "PlaygroundAsset"
      }
    },
    "required": [
      "asset"
    ],
    "additionalProperties": false
  },
  "ReferenceLibraryProposal": {
    "type": "object",
    "properties": {
      "characters": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "minLength": 1
            },
            "visual_description": {
              "anyOf": [
                {
                  "type": "string",
                  "minLength": 1
                },
                {
                  "type": "null"
                }
              ]
            },
            "voice_description": {
              "type": "string"
            },
            "looks": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": {
                    "type": "string",
                    "minLength": 1
                  },
                  "appearance": {
                    "type": "string",
                    "minLength": 1
                  },
                  "usage": {
                    "type": "string",
                    "minLength": 1
                  }
                },
                "required": [
                  "name",
                  "appearance",
                  "usage"
                ],
                "additionalProperties": false
              },
              "maxItems": 8
            }
          },
          "required": [
            "name",
            "visual_description",
            "voice_description",
            "looks"
          ],
          "additionalProperties": false
        }
      },
      "narrator": {
        "anyOf": [
          {
            "type": "object",
            "properties": {
              "name": {
                "type": "string",
                "minLength": 1
              },
              "zh_voice_description": {
                "anyOf": [
                  {
                    "type": "string"
                  },
                  {
                    "type": "null"
                  }
                ],
                "minLength": 1
              },
              "en_voice_description": {
                "anyOf": [
                  {
                    "type": "string"
                  },
                  {
                    "type": "null"
                  }
                ],
                "minLength": 1
              }
            },
            "required": [
              "name",
              "zh_voice_description",
              "en_voice_description"
            ],
            "additionalProperties": false
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "characters",
      "narrator"
    ],
    "additionalProperties": false
  },
  "StructuredDirectorScriptProposal": {
    "type": "object",
    "properties": {
      "scenes": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string",
              "minLength": 1,
              "maxLength": 300
            },
            "summary": {
              "type": "string",
              "minLength": 1,
              "maxLength": 4000
            },
            "setting": {
              "type": "string",
              "minLength": 1,
              "maxLength": 4000
            },
            "shots": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "visible_character_ids": {
                    "type": "array",
                    "items": {
                      "type": "string",
                      "pattern": "^[0-9a-f]{32}$"
                    }
                  },
                  "composition": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4000
                  },
                  "camera_movement": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000
                  },
                  "action": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4000
                  },
                  "audio_direction": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "transition_in": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "visible_character_ids",
                  "composition",
                  "camera_movement",
                  "action",
                  "audio_direction",
                  "transition_in"
                ],
                "additionalProperties": false
              }
            },
            "segments": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "shot_indexes": {
                    "type": "array",
                    "items": {
                      "type": "integer",
                      "minimum": 0
                    },
                    "minItems": 1
                  },
                  "duration_estimate_seconds": {
                    "type": "number",
                    "minimum": 0.2
                  },
                  "action": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4000
                  },
                  "dialogue_lines": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "character_id": {
                          "anyOf": [
                            {
                              "type": "string",
                              "pattern": "^[0-9a-f]{32}$"
                            },
                            {
                              "type": "null"
                            }
                          ]
                        },
                        "text": {
                          "type": "string",
                          "minLength": 1,
                          "maxLength": 2000
                        },
                        "delivery": {
                          "type": "string",
                          "maxLength": 1000
                        },
                        "speaker_label": {
                          "anyOf": [
                            {
                              "type": "string",
                              "minLength": 1,
                              "maxLength": 60
                            },
                            {
                              "type": "null"
                            }
                          ]
                        },
                        "id": {
                          "anyOf": [
                            {
                              "type": "string",
                              "pattern": "^[0-9a-f]{32}$"
                            },
                            {
                              "type": "null"
                            }
                          ]
                        },
                        "voice_description": {
                          "anyOf": [
                            {
                              "type": "string",
                              "minLength": 1,
                              "maxLength": 500
                            },
                            {
                              "type": "null"
                            }
                          ]
                        }
                      },
                      "required": [
                        "character_id",
                        "text",
                        "delivery"
                      ],
                      "additionalProperties": false
                    }
                  },
                  "boundary_from_previous": {
                    "anyOf": [
                      {
                        "type": "object",
                        "properties": {
                          "reason": {
                            "type": "string",
                            "enum": [
                              "model_constraint",
                              "continuity_anchor",
                              "control_boundary",
                              "failure_cost"
                            ]
                          },
                          "continuity_instruction": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000
                          }
                        },
                        "required": [
                          "reason",
                          "continuity_instruction"
                        ],
                        "additionalProperties": false
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "shot_indexes",
                  "duration_estimate_seconds",
                  "action",
                  "dialogue_lines",
                  "boundary_from_previous"
                ],
                "additionalProperties": false
              }
            },
            "narration_cues": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "zh": {
                    "anyOf": [
                      {
                        "type": "object",
                        "properties": {
                          "text": {
                            "type": "string"
                          },
                          "seed": {
                            "type": "integer"
                          },
                          "recipe_params": {
                            "type": "object",
                            "additionalProperties": {
                              "type": "object",
                              "additionalProperties": {
                                "anyOf": [
                                  {
                                    "type": "string"
                                  },
                                  {
                                    "type": "number"
                                  },
                                  {
                                    "type": "boolean"
                                  },
                                  {
                                    "type": "null"
                                  },
                                  {
                                    "type": "array",
                                    "items": {
                                      "type": "number"
                                    }
                                  }
                                ]
                              }
                            }
                          }
                        },
                        "required": [
                          "text",
                          "seed"
                        ],
                        "additionalProperties": false
                      },
                      {
                        "type": "null"
                      }
                    ]
                  },
                  "en": {
                    "anyOf": [
                      {
                        "type": "object",
                        "properties": {
                          "text": {
                            "type": "string"
                          },
                          "seed": {
                            "type": "integer"
                          },
                          "recipe_params": {
                            "type": "object",
                            "additionalProperties": {
                              "type": "object",
                              "additionalProperties": {
                                "anyOf": [
                                  {
                                    "type": "string"
                                  },
                                  {
                                    "type": "number"
                                  },
                                  {
                                    "type": "boolean"
                                  },
                                  {
                                    "type": "null"
                                  },
                                  {
                                    "type": "array",
                                    "items": {
                                      "type": "number"
                                    }
                                  }
                                ]
                              }
                            }
                          }
                        },
                        "required": [
                          "text",
                          "seed"
                        ],
                        "additionalProperties": false
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "zh",
                  "en"
                ],
                "additionalProperties": false
              },
              "maxItems": 1
            },
            "driver": {
              "type": "string",
              "enum": [
                "narration",
                "drama"
              ]
            }
          },
          "required": [
            "title",
            "summary",
            "setting",
            "shots",
            "segments",
            "narration_cues",
            "driver"
          ],
          "additionalProperties": false
        },
        "minItems": 1
      }
    },
    "required": [
      "scenes"
    ],
    "additionalProperties": false
  },
  "StructuredDirectorScriptRevisionProposal": {
    "type": "object",
    "properties": {
      "reply_markdown": {
        "type": "string",
        "minLength": 1,
        "maxLength": 10000
      },
      "operations": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "operation": {
              "type": "string",
              "enum": [
                "replace_scene",
                "insert_scene",
                "delete_scene",
                "move_scene",
                "replace_segment"
              ]
            },
            "scene_id": {
              "anyOf": [
                {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                },
                {
                  "type": "null"
                }
              ]
            },
            "after_scene_id": {
              "anyOf": [
                {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                },
                {
                  "type": "null"
                }
              ]
            },
            "scene": {
              "anyOf": [
                {
                  "type": "object",
                  "properties": {
                    "id": {
                      "anyOf": [
                        {
                          "type": "string",
                          "pattern": "^[0-9a-f]{32}$"
                        },
                        {
                          "type": "null"
                        }
                      ]
                    },
                    "title": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 300
                    },
                    "summary": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 4000
                    },
                    "setting": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 4000
                    },
                    "shots": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "anyOf": [
                              {
                                "type": "string",
                                "pattern": "^[0-9a-f]{32}$"
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "visible_character_ids": {
                            "type": "array",
                            "items": {
                              "type": "string",
                              "pattern": "^[0-9a-f]{32}$"
                            }
                          },
                          "composition": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4000
                          },
                          "camera_movement": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000
                          },
                          "action": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4000
                          },
                          "audio_direction": {
                            "type": "string",
                            "maxLength": 2000
                          },
                          "transition_in": {
                            "anyOf": [
                              {
                                "type": "string"
                              },
                              {
                                "type": "null"
                              }
                            ]
                          }
                        },
                        "required": [
                          "id",
                          "visible_character_ids",
                          "composition",
                          "camera_movement",
                          "action",
                          "audio_direction",
                          "transition_in"
                        ],
                        "additionalProperties": false
                      }
                    },
                    "segments": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "anyOf": [
                              {
                                "type": "string",
                                "pattern": "^[0-9a-f]{32}$"
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "shot_indexes": {
                            "type": "array",
                            "items": {
                              "type": "integer",
                              "minimum": 0
                            },
                            "minItems": 1
                          },
                          "duration_estimate_seconds": {
                            "type": "number",
                            "minimum": 0.2
                          },
                          "action": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4000
                          },
                          "dialogue_lines": {
                            "type": "array",
                            "items": {
                              "type": "object",
                              "properties": {
                                "character_id": {
                                  "anyOf": [
                                    {
                                      "type": "string",
                                      "pattern": "^[0-9a-f]{32}$"
                                    },
                                    {
                                      "type": "null"
                                    }
                                  ]
                                },
                                "text": {
                                  "type": "string",
                                  "minLength": 1,
                                  "maxLength": 2000
                                },
                                "delivery": {
                                  "type": "string",
                                  "maxLength": 1000
                                },
                                "speaker_label": {
                                  "anyOf": [
                                    {
                                      "type": "string",
                                      "minLength": 1,
                                      "maxLength": 60
                                    },
                                    {
                                      "type": "null"
                                    }
                                  ]
                                },
                                "id": {
                                  "anyOf": [
                                    {
                                      "type": "string",
                                      "pattern": "^[0-9a-f]{32}$"
                                    },
                                    {
                                      "type": "null"
                                    }
                                  ]
                                },
                                "voice_description": {
                                  "anyOf": [
                                    {
                                      "type": "string",
                                      "minLength": 1,
                                      "maxLength": 500
                                    },
                                    {
                                      "type": "null"
                                    }
                                  ]
                                }
                              },
                              "required": [
                                "character_id",
                                "text",
                                "delivery"
                              ],
                              "additionalProperties": false
                            }
                          },
                          "boundary_from_previous": {
                            "anyOf": [
                              {
                                "type": "object",
                                "properties": {
                                  "reason": {
                                    "type": "string",
                                    "enum": [
                                      "model_constraint",
                                      "continuity_anchor",
                                      "control_boundary",
                                      "failure_cost"
                                    ]
                                  },
                                  "continuity_instruction": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 2000
                                  }
                                },
                                "required": [
                                  "reason",
                                  "continuity_instruction"
                                ],
                                "additionalProperties": false
                              },
                              {
                                "type": "null"
                              }
                            ]
                          }
                        },
                        "required": [
                          "id",
                          "shot_indexes",
                          "duration_estimate_seconds",
                          "action",
                          "dialogue_lines",
                          "boundary_from_previous"
                        ],
                        "additionalProperties": false
                      }
                    },
                    "narration_cues": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "anyOf": [
                              {
                                "type": "string",
                                "pattern": "^[0-9a-f]{32}$"
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "zh": {
                            "anyOf": [
                              {
                                "type": "object",
                                "properties": {
                                  "text": {
                                    "type": "string"
                                  },
                                  "seed": {
                                    "type": "integer"
                                  },
                                  "recipe_params": {
                                    "type": "object",
                                    "additionalProperties": {
                                      "type": "object",
                                      "additionalProperties": {
                                        "anyOf": [
                                          {
                                            "type": "string"
                                          },
                                          {
                                            "type": "number"
                                          },
                                          {
                                            "type": "boolean"
                                          },
                                          {
                                            "type": "null"
                                          },
                                          {
                                            "type": "array",
                                            "items": {
                                              "type": "number"
                                            }
                                          }
                                        ]
                                      }
                                    }
                                  }
                                },
                                "required": [
                                  "text",
                                  "seed"
                                ],
                                "additionalProperties": false
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "en": {
                            "anyOf": [
                              {
                                "type": "object",
                                "properties": {
                                  "text": {
                                    "type": "string"
                                  },
                                  "seed": {
                                    "type": "integer"
                                  },
                                  "recipe_params": {
                                    "type": "object",
                                    "additionalProperties": {
                                      "type": "object",
                                      "additionalProperties": {
                                        "anyOf": [
                                          {
                                            "type": "string"
                                          },
                                          {
                                            "type": "number"
                                          },
                                          {
                                            "type": "boolean"
                                          },
                                          {
                                            "type": "null"
                                          },
                                          {
                                            "type": "array",
                                            "items": {
                                              "type": "number"
                                            }
                                          }
                                        ]
                                      }
                                    }
                                  }
                                },
                                "required": [
                                  "text",
                                  "seed"
                                ],
                                "additionalProperties": false
                              },
                              {
                                "type": "null"
                              }
                            ]
                          }
                        },
                        "required": [
                          "id",
                          "zh",
                          "en"
                        ],
                        "additionalProperties": false
                      },
                      "maxItems": 1
                    },
                    "driver": {
                      "type": "string",
                      "enum": [
                        "narration",
                        "drama"
                      ]
                    }
                  },
                  "required": [
                    "id",
                    "title",
                    "summary",
                    "setting",
                    "shots",
                    "segments",
                    "narration_cues",
                    "driver"
                  ],
                  "additionalProperties": false
                },
                {
                  "type": "null"
                }
              ]
            },
            "segment": {
              "anyOf": [
                {
                  "type": "object",
                  "properties": {
                    "id": {
                      "anyOf": [
                        {
                          "type": "string",
                          "pattern": "^[0-9a-f]{32}$"
                        },
                        {
                          "type": "null"
                        }
                      ]
                    },
                    "shot_indexes": {
                      "type": "array",
                      "items": {
                        "type": "integer",
                        "minimum": 0
                      },
                      "minItems": 1
                    },
                    "duration_estimate_seconds": {
                      "type": "number",
                      "minimum": 0.2
                    },
                    "action": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 4000
                    },
                    "dialogue_lines": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "character_id": {
                            "anyOf": [
                              {
                                "type": "string",
                                "pattern": "^[0-9a-f]{32}$"
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000
                          },
                          "delivery": {
                            "type": "string",
                            "maxLength": 1000
                          },
                          "speaker_label": {
                            "anyOf": [
                              {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 60
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "id": {
                            "anyOf": [
                              {
                                "type": "string",
                                "pattern": "^[0-9a-f]{32}$"
                              },
                              {
                                "type": "null"
                              }
                            ]
                          },
                          "voice_description": {
                            "anyOf": [
                              {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 500
                              },
                              {
                                "type": "null"
                              }
                            ]
                          }
                        },
                        "required": [
                          "character_id",
                          "text",
                          "delivery"
                        ],
                        "additionalProperties": false
                      }
                    },
                    "boundary_from_previous": {
                      "anyOf": [
                        {
                          "type": "object",
                          "properties": {
                            "reason": {
                              "type": "string",
                              "enum": [
                                "model_constraint",
                                "continuity_anchor",
                                "control_boundary",
                                "failure_cost"
                              ]
                            },
                            "continuity_instruction": {
                              "type": "string",
                              "minLength": 1,
                              "maxLength": 2000
                            }
                          },
                          "required": [
                            "reason",
                            "continuity_instruction"
                          ],
                          "additionalProperties": false
                        },
                        {
                          "type": "null"
                        }
                      ]
                    }
                  },
                  "required": [
                    "id",
                    "shot_indexes",
                    "duration_estimate_seconds",
                    "action",
                    "dialogue_lines",
                    "boundary_from_previous"
                  ],
                  "additionalProperties": false
                },
                {
                  "type": "null"
                }
              ]
            }
          },
          "required": [
            "operation",
            "scene_id",
            "after_scene_id",
            "scene",
            "segment"
          ],
          "additionalProperties": false
        }
      }
    },
    "required": [
      "reply_markdown",
      "operations"
    ],
    "additionalProperties": false
  },
  "NarrationReviewProposal": {
    "type": "object",
    "properties": {
      "reply_markdown": {
        "type": "string",
        "minLength": 1,
        "maxLength": 10000
      },
      "cue_updates": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "cue_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "language": {
              "type": "string",
              "enum": [
                "zh",
                "en"
              ]
            },
            "seed": {
              "type": "integer",
              "minimum": 0,
              "maximum": 9223372036854775807
            },
            "regenerate": {
              "type": "boolean"
            },
            "recipe_params": {
              "type": "object",
              "additionalProperties": {
                "type": "object",
                "additionalProperties": {
                  "anyOf": [
                    {
                      "type": "string"
                    },
                    {
                      "type": "number"
                    },
                    {
                      "type": "boolean"
                    },
                    {
                      "type": "null"
                    },
                    {
                      "type": "array",
                      "items": {
                        "type": "number"
                      }
                    }
                  ]
                }
              }
            }
          },
          "required": [
            "cue_id",
            "language",
            "seed",
            "regenerate",
            "recipe_params"
          ],
          "additionalProperties": false
        }
      }
    },
    "required": [
      "reply_markdown",
      "cue_updates"
    ],
    "additionalProperties": false
  },
  "KeyframePlanProposal": {
    "type": "object",
    "properties": {
      "segments": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "segment_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "continues_from_previous": {
              "type": "boolean"
            },
            "frame_strategy": {
              "type": "string",
              "enum": [
                "none",
                "start",
                "end",
                "both"
              ]
            },
            "start_prompt_text": {
              "type": "string",
              "maxLength": 18000
            },
            "start_visible_character_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$"
              }
            },
            "end_prompt_text": {
              "type": "string",
              "maxLength": 18000
            },
            "end_visible_character_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$"
              }
            },
            "start_character_references": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "character_id": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{32}$"
                  },
                  "look_id": {
                    "anyOf": [
                      {
                        "type": "string",
                        "pattern": "^[0-9a-f]{32}$"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "character_id",
                  "look_id"
                ],
                "additionalProperties": false
              }
            },
            "end_character_references": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "character_id": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{32}$"
                  },
                  "look_id": {
                    "anyOf": [
                      {
                        "type": "string",
                        "pattern": "^[0-9a-f]{32}$"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "character_id",
                  "look_id"
                ],
                "additionalProperties": false
              }
            },
            "reference_images": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "slot_index": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 3
                  },
                  "prompt_text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 18000
                  },
                  "description": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000
                  },
                  "visible_character_ids": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    }
                  },
                  "character_references": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "character_id": {
                          "type": "string",
                          "pattern": "^[0-9a-f]{32}$"
                        },
                        "look_id": {
                          "anyOf": [
                            {
                              "type": "string",
                              "pattern": "^[0-9a-f]{32}$"
                            },
                            {
                              "type": "null"
                            }
                          ]
                        }
                      },
                      "required": [
                        "character_id",
                        "look_id"
                      ],
                      "additionalProperties": false
                    }
                  },
                  "reference_asset_ids": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    }
                  }
                },
                "required": [
                  "slot_index",
                  "prompt_text",
                  "description",
                  "visible_character_ids",
                  "character_references"
                ],
                "additionalProperties": false
              },
              "maxItems": 4
            },
            "start_reference_keyframe_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$"
              },
              "maxItems": 4
            },
            "end_reference_keyframe_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$"
              },
              "maxItems": 4
            },
            "start_reference_location_image_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$"
              },
              "maxItems": 4
            },
            "end_reference_location_image_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{32}$"
              },
              "maxItems": 4
            }
          },
          "required": [
            "segment_id",
            "continues_from_previous",
            "frame_strategy",
            "start_prompt_text",
            "start_visible_character_ids",
            "end_prompt_text",
            "end_visible_character_ids",
            "start_character_references",
            "end_character_references"
          ],
          "additionalProperties": false
        }
      }
    },
    "required": [
      "segments"
    ],
    "additionalProperties": false
  },
  "LocationPlanProposal": {
    "type": "object",
    "properties": {
      "locations": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string"
            },
            "description": {
              "type": "string"
            },
            "key_light": {
              "anyOf": [
                {
                  "type": "object",
                  "properties": {
                    "description": {
                      "type": "string"
                    }
                  },
                  "required": [
                    "description"
                  ],
                  "additionalProperties": false
                },
                {
                  "type": "null"
                }
              ]
            },
            "fixtures": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": {
                    "type": "string"
                  },
                  "description": {
                    "type": "string"
                  },
                  "id": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  },
                  "key": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "name",
                  "description"
                ],
                "additionalProperties": false
              }
            },
            "states": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": {
                    "type": "string"
                  },
                  "description": {
                    "type": "string"
                  },
                  "id": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  },
                  "key": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "name",
                  "description"
                ],
                "additionalProperties": false
              }
            },
            "images": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": {
                    "type": "string"
                  },
                  "kind": {
                    "type": "string"
                  },
                  "description": {
                    "type": "string"
                  },
                  "prompt_text": {
                    "type": "string"
                  },
                  "reference_asset_ids": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    }
                  },
                  "source": {
                    "anyOf": [
                      {
                        "type": "object",
                        "properties": {
                          "panorama_image_id": {
                            "type": "string"
                          },
                          "yaw_deg": {
                            "type": "number"
                          },
                          "pitch_deg": {
                            "type": "number"
                          },
                          "hfov_deg": {
                            "type": "number"
                          }
                        },
                        "required": [
                          "panorama_image_id",
                          "yaw_deg",
                          "pitch_deg",
                          "hfov_deg"
                        ],
                        "additionalProperties": false
                      },
                      {
                        "type": "null"
                      }
                    ]
                  },
                  "id": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ],
                    "pattern": "^[0-9a-f]{32}$"
                  },
                  "key": {
                    "anyOf": [
                      {
                        "type": "string"
                      },
                      {
                        "type": "null"
                      }
                    ]
                  }
                },
                "required": [
                  "name",
                  "kind",
                  "description",
                  "prompt_text",
                  "reference_asset_ids",
                  "source"
                ],
                "additionalProperties": false
              }
            },
            "id": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "pattern": "^[0-9a-f]{32}$"
            },
            "key": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ]
            }
          },
          "required": [
            "name",
            "description",
            "key_light",
            "fixtures",
            "states",
            "images"
          ],
          "additionalProperties": false
        }
      },
      "scene_bindings": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "scene_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "location_id": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ]
            },
            "state_id": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ]
            }
          },
          "required": [
            "scene_id",
            "location_id",
            "state_id"
          ],
          "additionalProperties": false
        }
      }
    },
    "required": [
      "locations",
      "scene_bindings"
    ],
    "additionalProperties": false
  },
  "VideoPromptProposal": {
    "type": "object",
    "properties": {
      "prompt_text": {
        "type": "string",
        "minLength": 1,
        "maxLength": 20000
      }
    },
    "required": [
      "prompt_text"
    ],
    "additionalProperties": false
  }
};

export function isStructuredDirectorAction(value: unknown): value is StructuredDirectorAction {
  return checkSchema(schemas.StructuredDirectorAction, value, schemas);
}
export function isGenerationPhase(value: unknown): value is ReferenceGenerationPhase {
  return checkSchema(schemas.ReferenceGenerationPhase, value, schemas);
}
export function isReferenceGenerationAction(value: unknown): value is ReferenceGenerationAction {
  return checkSchema(schemas.ReferenceGenerationAction, value, schemas);
}
export function isProjectSummary(value: unknown): value is ProjectSummary {
  return checkSchema(schemas.ProjectSummary, value, schemas);
}
export function isProviderSettingsView(value: unknown): value is ProviderSettingsView {
  return checkSchema(schemas.ProviderSettingsView, value, schemas);
}
export function isActiveDirectorRun(value: unknown): value is ActiveDirectorRun {
  return checkSchema(schemas.ActiveDirectorRun, value, schemas) && refineActiveDirectorRun(value);
}
export function isDialogueLine(value: unknown): value is DialogueLine {
  return checkSchema(schemas.DialogueLine, value, schemas);
}
export function isSegmentBoundary(value: unknown): value is SegmentBoundary {
  return checkSchema(schemas.SegmentBoundary, value, schemas);
}
export function isShotSegment(value: unknown): value is ShotSegment {
  return checkSchema(schemas.ShotSegment, value, schemas);
}
export function isShot(value: unknown): value is Shot {
  return checkSchema(schemas.Shot, value, schemas);
}
export function isSceneAnimaticState(value: unknown): value is SceneAnimaticState {
  return checkSchema(schemas.SceneAnimaticState, value, schemas);
}
export function isSceneFinalState(value: unknown): value is SceneFinalState {
  return checkSchema(schemas.SceneFinalState, value, schemas);
}
export function isScene(value: unknown): value is Scene {
  return checkSchema(schemas.Scene, value, schemas) && refineScene(value);
}
export function isNarrationTrack(value: unknown): value is NarrationTrack {
  return checkSchema(schemas.NarrationTrack, value, schemas);
}
export function isNarrationCue(value: unknown): value is NarrationCue {
  return checkSchema(schemas.NarrationCue, value, schemas);
}
export function isDirectorScript(value: unknown): value is DirectorScript {
  return checkSchema(schemas.DirectorScript, value, schemas) && refineDirectorScript(value);
}
export function isLocationLibrary(value: unknown): value is LocationLibrary {
  return checkSchema(schemas.LocationLibrary, value, schemas);
}
export function isKeyframePlan(value: unknown): value is KeyframePlan {
  return checkSchema(schemas.KeyframePlan, value, schemas);
}
export function isVideoRecipeState(value: unknown): value is VideoRecipeState {
  return checkSchema(schemas.VideoRecipeState, value, schemas);
}
export function isVideoPlan(value: unknown): value is VideoPlan {
  return checkSchema(schemas.VideoPlan, value, schemas);
}
export function isFinalAssemblyPlan(value: unknown): value is FinalAssemblyPlan {
  return checkSchema(schemas.FinalAssemblyPlan, value, schemas) && refineFinalAssembly(value);
}
export function isFinalApproval(value: unknown): value is FinalApproval {
  return checkSchema(schemas.FinalApproval, value, schemas);
}
export function isAssetUsageReason(value: unknown): value is AssetUsageReason {
  return checkSchema(schemas.AssetUsageReason, value, schemas);
}
export function isProjectAsset(value: unknown): value is ProjectAsset {
  return checkSchema(schemas.ProjectAsset, value, schemas) && refineAsset(value);
}
export function isImageSubmissionPreview(value: unknown): value is ImageSubmissionPreview {
  return checkSchema(schemas.ImageSubmissionPreview, value, schemas);
}
export function isGenerationProvider(value: unknown): value is GenerationProvider {
  return checkSchema(schemas.GenerationProvider, value, schemas);
}
export function isReferenceGeneration(value: unknown): value is ReferenceGeneration {
  return checkSchema(schemas.ReferenceGeneration, value, schemas) && refineGeneration(value);
}
export function isWorkspaceLayers(value: unknown): value is WorkspaceLayers {
  return checkSchema(schemas.WorkspaceLayers, value, schemas) && refineWorkspaceLayers(value);
}
export function isProviderAvailability(value: unknown): value is ProviderAvailability {
  return checkSchema(schemas.ProviderAvailability, value, schemas);
}
export function isCharacterCard(value: unknown): value is CharacterCard {
  return checkSchema(schemas.CharacterCard, value, schemas);
}
export function isNarratorProfile(value: unknown): value is NarratorProfile {
  return checkSchema(schemas.NarratorProfile, value, schemas);
}
export function isProductionAvailability(value: unknown): value is ProductionAvailability {
  return checkSchema(schemas.ProductionAvailability, value, schemas);
}
export function isWorkflowAction(value: unknown): value is WorkflowAction {
  return checkSchema(schemas.WorkflowAction, value, schemas);
}
export function isWorkflowEnvelope(value: unknown): value is WorkflowState {
  return checkSchema(schemas.WorkflowState, value, schemas);
}
export function isCapabilityGapAlert(value: unknown): value is CapabilityGapAlert {
  return checkSchema(schemas.CapabilityGapAlert, value, schemas);
}
export function isApiErrorPayload(value: unknown): value is ApiErrorPayload {
  return checkSchema(schemas.ApiErrorPayload, value, schemas);
}
export function isPlaygroundRunAction(value: unknown): value is PlaygroundRunAction {
  return checkSchema(schemas.PlaygroundRunAction, value, schemas);
}
export function isPlaygroundAssetAction(value: unknown): value is PlaygroundAssetAction {
  return checkSchema(schemas.PlaygroundAssetAction, value, schemas);
}
export function isPlaygroundCapabilityInfo(value: unknown): value is PlaygroundCapabilityInfo {
  return checkSchema(schemas.PlaygroundCapabilityInfo, value, schemas);
}
export function isPlaygroundAssetOrigin(value: unknown): value is PlaygroundAssetOrigin {
  return checkSchema(schemas.PlaygroundAssetOrigin, value, schemas);
}
export function isPlaygroundAsset(value: unknown): value is PlaygroundAsset {
  return checkSchema(schemas.PlaygroundAsset, value, schemas);
}
export function isPlaygroundRunRecovery(value: unknown): value is PlaygroundRunRecovery {
  return checkSchema(schemas.PlaygroundRunRecovery, value, schemas);
}
export function isPlaygroundInputLabel(value: unknown): value is PlaygroundInputLabel {
  return checkSchema(schemas.PlaygroundInputLabel, value, schemas);
}
export function isPlaygroundRecipePreview(value: unknown): value is PlaygroundRecipePreview {
  return checkSchema(schemas.PlaygroundRecipePreview, value, schemas);
}
export function isPlaygroundRun(value: unknown): value is PlaygroundRun {
  return checkSchema(schemas.PlaygroundRun, value, schemas);
}
export function isPlaygroundSnapshot(value: unknown): value is PlaygroundSnapshot {
  return checkSchema(schemas.PlaygroundSnapshot, value, schemas);
}
export function isPlaygroundCommandReceipt(value: unknown): value is PlaygroundCommandReceipt {
  return checkSchema(schemas.PlaygroundCommandReceipt, value, schemas);
}
export function isPlaygroundCopyToProjectResult(value: unknown): value is PlaygroundCopyToProjectResult {
  return checkSchema(schemas.PlaygroundCopyToProjectResult, value, schemas);
}
export function isPlaygroundAssetResult(value: unknown): value is PlaygroundAssetResult {
  return checkSchema(schemas.PlaygroundAssetResult, value, schemas);
}

export function parseProjectList(value: unknown): ProjectSummary[] {
  return parseProjectBootstrap(value).projects;
}
export function parseProjectBootstrap(value: unknown): ProjectBootstrap {
  if (!isRecord(value) || !Array.isArray(value.projects) || !hasExactKeys(value, ["projects"])) {
    throw new Error("服务端返回了无法识别的项目列表。");
  }
  return { projects: value.projects.map(parseProject) };
}
export function parseProject(value: unknown): ProjectSummary {
  if (!isProjectSummary(value)) throw new Error("服务端返回的项目摘要不合法。");
  return value;
}
export function parseProviderSettings(value: unknown): ProviderSettingsView {
  if (!isProviderSettingsView(value)) throw new Error("服务端返回了无法识别的 Provider 设置。");
  return value;
}
export function parseProjectDetail(value: unknown): ProjectDetail {
  return parseDetail(value, "服务端返回了无法识别的项目状态。");
}
export function parseStructuredDirectorDetail(value: unknown): StructuredDirectorDetail {
  return parseDetail(value, "服务端返回了无法识别的结构化导演台状态。");
}
function parseDetail(value: unknown, message: string): ProjectDetail {
  if (!isRecord(value) || !hasExactKeys(value, ["project", "structured_director"])) {
    throw new Error(message);
  }
  return {
    project: parseProject(value.project),
    structured_director: parseStructuredDirectorSnapshot(value.structured_director),
  };
}
export function parseDeleteResult(value: unknown): string {
  if (!isRecord(value) || !hasExactKeys(value, ["deleted_project_id"]) ||
    !isId(value.deleted_project_id)) {
    throw new Error("服务端返回的删除结果不合法。");
  }
  return value.deleted_project_id;
}
export function parseAudioTranscription(value: unknown): string {
  if (!isRecord(value) || !hasExactKeys(value, ["transcript"]) ||
    typeof value.transcript !== "string" || value.transcript.trim().length === 0) {
    throw new Error("音频转写结果格式不合法。");
  }
  return value.transcript;
}
export function parseError(value: unknown): ApiErrorPayload {
  if (!isRecord(value) || !hasExactKeys(value, ["error"]) || !isRecord(value.error)) {
    throw new Error("服务端返回了无法识别的错误。");
  }
  if (!checkSchema(schemas.ApiErrorBody, value.error, schemas)) {
    throw new Error("服务端错误格式不合法。");
  }
  return value as unknown as ApiErrorPayload;
}
export function parseImageSubmissionPreview(
  value: unknown,
): ImageSubmissionPreview {
  if (!isImageSubmissionPreview(value)) {
    throw new Error("最终完整提示词预览格式不合法。");
  }
  return value;
}
export function parseStructuredDirectorSnapshot(value: unknown): StructuredDirectorSnapshot {
  const required = schemas.StructuredDirectorSnapshot.required ?? [];
  if (!isRecord(value) || !hasExactKeys(value, required)) {
    throw new Error("服务端返回了无法识别的结构化导演台状态。");
  }
  const snapshot = value;
  if (!isProductionAvailability(snapshot.production_availability)) {
    throw new Error("制作能力状态不合法。");
  }
  if (!checkSchema(schemas.StructuredDirectorStatus, snapshot.status, schemas)) {
    throw new Error("引用库准备状态不合法。");
  }
  if (snapshot.active_director_run !== null && !isActiveDirectorRun(snapshot.active_director_run)) {
    throw new Error("Director run 状态不合法。");
  }
  if (!checkSchema(snapshotProperty("revision"), snapshot.revision, schemas)) {
    throw new Error("结构化导演台 revision 不合法。");
  }
  if (!checkSchema(schemas.ProjectAspectRatio, snapshot.aspect_ratio, schemas)) {
    throw new Error("结构化导演台画面比例不合法。");
  }
  if (!checkSchema(
    snapshotProperty("director_plan_markdown"),
    snapshot.director_plan_markdown,
    schemas,
  )) {
    throw new Error("结构化导演台导演方案不合法。");
  }
  if (!isWorkspaceLayers(snapshot.workspace_layers)) {
    throw new Error("结构化导演台解锁状态不合法。");
  }
  if (!checkSchema(snapshotProperty("allowed_actions"), snapshot.allowed_actions, schemas)) {
    throw new Error("结构化导演台允许动作不合法。");
  }
  const library = snapshot.reference_library;
  if (!isReferenceLibraryView(library)) {
    throw new Error("引用库格式不合法。");
  }
  if (!Array.isArray(library.characters) || !library.characters.every(isCharacterCard) ||
    (library.narrator !== null && !isNarratorProfile(library.narrator))) {
    throw new Error("引用库卡片格式不合法。");
  }
  if (!isProviderAvailability(snapshot.provider_availability)) {
    throw new Error("模型服务可用性格式不合法。");
  }
  const assets = snapshot.assets;
  if (!Array.isArray(assets) || !assets.every(isProjectAsset)) {
    throw new Error("Asset 清单格式不合法。");
  }
  const generations = snapshot.generations;
  if (!Array.isArray(generations) || !generations.every(isReferenceGeneration)) {
    throw new Error("Generation 清单格式不合法。");
  }
  if (snapshot.director_script !== null && !isDirectorScript(snapshot.director_script)) {
    throw new Error("结构化导演脚本格式不合法。");
  }
  if (!isLocationLibrary(snapshot.location_library)) {
    throw new Error("地点库格式不合法。");
  }
  if (snapshot.keyframe_plan !== null && !isKeyframePlan(snapshot.keyframe_plan)) {
    throw new Error("Segment Keyframe 计划格式不合法。");
  }
  if (snapshot.video_plan !== null && !isVideoPlan(snapshot.video_plan)) {
    throw new Error("Segment 视频计划格式不合法。");
  }
  if (snapshot.final_assembly !== null && !isFinalAssemblyPlan(snapshot.final_assembly)) {
    throw new Error("最终成片装配计划格式不合法。");
  }
  if (snapshot.final_approval !== null && !isFinalApproval(snapshot.final_approval)) {
    throw new Error("最终 Approval 格式不合法。");
  }
  const capabilityGapAlerts = snapshot.capability_gap_alerts;
  if (!Array.isArray(capabilityGapAlerts) || !capabilityGapAlerts.every(isCapabilityGapAlert)) {
    throw new Error("能力缺口报警格式不合法。");
  }
  snapshot.workflow = parseWorkflowState(snapshot.workflow);
  const parsed = snapshot as unknown as StructuredDirectorSnapshot;
  const consistency = snapshotConsistencyError(parsed);
  if (consistency) throw new Error(consistency);
  return parsed;
}
function snapshotProperty(name: string): JsonSchema {
  const property = schemas.StructuredDirectorSnapshot.properties?.[name];
  if (!property) throw new Error("契约缺少字段。");
  return property;
}
function isReferenceLibraryView(value: unknown): value is ReferenceLibraryView {
  if (!isRecord(value)) return false;
  const withReviewed = ["characters", "narrator", "reviewed"];
  const withoutReviewed = ["characters", "narrator"];
  if (!(hasExactKeys(value, withReviewed) || hasExactKeys(value, withoutReviewed))) return false;
  if ("reviewed" in value && typeof value.reviewed !== "boolean") return false;
  return true;
}
function parseWorkflowState(value: unknown): WorkflowState {
  if (!isWorkflowEnvelope(value) || !refineWorkflow(value)) {
    throw new Error("主流程状态不合法。");
  }
  const workflow = value as WorkflowState;
  for (const action of workflow.required_next_actions) {
    if (!isWorkflowAction(action)) throw new Error("主流程动作不合法。");
  }
  return workflow;
}

export function parseReferenceLibraryProposal(value: unknown): ReferenceLibraryProposal {
  if (!checkSchema(schemas.ReferenceLibraryProposal, value, schemas)) {
    throw new Error("proposal 不符合 ReferenceLibraryProposal。");
  }
  return value as ReferenceLibraryProposal;
}
export function parseStructuredDirectorScriptProposal(value: unknown): StructuredDirectorScriptProposal {
  if (!checkSchema(schemas.StructuredDirectorScriptProposal, value, schemas)) {
    throw new Error("proposal 不符合 StructuredDirectorScriptProposal。");
  }
  return value as StructuredDirectorScriptProposal;
}
export function parseStructuredDirectorScriptRevisionProposal(value: unknown): StructuredDirectorScriptRevisionProposal {
  if (!checkSchema(schemas.StructuredDirectorScriptRevisionProposal, value, schemas)) {
    throw new Error("proposal 不符合 StructuredDirectorScriptRevisionProposal。");
  }
  return value as StructuredDirectorScriptRevisionProposal;
}
export function parseNarrationReviewProposal(value: unknown): NarrationReviewProposal {
  if (!checkSchema(schemas.NarrationReviewProposal, value, schemas)) {
    throw new Error("proposal 不符合 NarrationReviewProposal。");
  }
  return value as NarrationReviewProposal;
}
export function parseKeyframePlanProposal(value: unknown): KeyframePlanProposal {
  if (!checkSchema(schemas.KeyframePlanProposal, value, schemas)) {
    throw new Error("proposal 不符合 KeyframePlanProposal。");
  }
  return value as KeyframePlanProposal;
}
export function parseLocationPlanProposal(value: unknown): LocationPlanProposal {
  if (!checkSchema(schemas.LocationPlanProposal, value, schemas)) {
    throw new Error("proposal 不符合 LocationPlanProposal。");
  }
  return value as LocationPlanProposal;
}
export function parseVideoPromptProposal(value: unknown): VideoPromptProposal {
  if (!checkSchema(schemas.VideoPromptProposal, value, schemas)) {
    throw new Error("proposal 不符合 VideoPromptProposal。");
  }
  return value as VideoPromptProposal;
}
