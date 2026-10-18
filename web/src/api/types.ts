// 勿手改，由 scripts/gen_web_contracts.py 生成。

export const AgentMessageRole = ["user", "agent", "system"] as const;
export type AgentMessageRole = (typeof AgentMessageRole)[number];
export const ProjectStatus = ["active", "needs_recovery"] as const;
export type ProjectStatus = (typeof ProjectStatus)[number];
export const ProjectAspectRatio = ["16:9", "9:16", "2:1"] as const;
export type ProjectAspectRatio = (typeof ProjectAspectRatio)[number];
export const ProviderCapabilityId = ["image.generate", "image.edit", "voice.design", "speech.synthesize", "speech.recognize", "video.generate", "video.upscale", "audio.generate", "audio.separate"] as const;
export type ProviderCapabilityId = (typeof ProviderCapabilityId)[number];
export const ManifestWidget = ["text", "prompt", "number", "slider", "enum", "preset", "toggle", "seed", "audio_stem", "vector", "asset_slot", "asset_list"] as const;
export type ManifestWidget = (typeof ManifestWidget)[number];
export const ManifestRole = ["first_frame", "last_frame", "reference_image", "reference_audio", "reference_video", "voice_reference", "voice_transcript", "edit_source", "source_video", "source_audio", "prompt", "speech_text", "language", "duration", "aspect_ratio", "seed", "audio_stem"] as const;
export type ManifestRole = (typeof ManifestRole)[number];
export const NarrationLanguage = ["zh", "en"] as const;
export type NarrationLanguage = (typeof NarrationLanguage)[number];
export const StructuredDirectorAction = ["confirm_reference_review", "edit_reference_library", "import_image_asset", "import_media_asset", "extract_video_frame", "generate_audio", "trim_audio", "apply_audio_effect", "separate_video_audio", "remix_video_audio", "delete_asset", "attach_reference_image", "upload_reference_voice", "observe_reference_generations", "edit_script", "confirm_script", "edit_narration", "generate_narration", "generate_narration_batch", "select_narration_audio", "generate_dialogue", "generate_dialogue_batch", "select_dialogue_audio", "set_dialogue_timing", "unlock_visual_production", "edit_keyframe_references", "generate_keyframe", "generate_keyframe_batch", "select_keyframe", "generate_scene_animatic", "generate_scene_final", "edit_segment_video_plan", "generate_segment_video", "attach_segment_video_candidate", "select_segment_video", "upscale_segment_video", "generate_final_video", "select_final_video", "clear_final_selection", "approve_final_video", "reopen_video_production"] as const;
export type StructuredDirectorAction = (typeof StructuredDirectorAction)[number];
export const StructuredDirectorStatus = ["awaiting_reference_proposal", "reviewing_references", "reviewing_script", "reviewing_narration", "reviewing_keyframes", "reviewing_videos", "reviewing_final", "approved"] as const;
export type StructuredDirectorStatus = (typeof StructuredDirectorStatus)[number];
export const DirectorRunKind = ["reference_proposal", "script_proposal", "script_edit", "narration_edit", "keyframe_plan", "location_plan", "director"] as const;
export type DirectorRunKind = (typeof DirectorRunKind)[number];
export const SegmentBoundaryReason = ["model_constraint", "continuity_anchor", "control_boundary", "failure_cost"] as const;
export type SegmentBoundaryReason = (typeof SegmentBoundaryReason)[number];
export const ImageOperation = ["generate", "edit"] as const;
export type ImageOperation = (typeof ImageOperation)[number];
export const ImageAspectRatio = ["16:9", "9:16", "2:1", "1:2", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5", "21:9", "9:21", "3:1", "1:3"] as const;
export type ImageAspectRatio = (typeof ImageAspectRatio)[number];
export const AssetUsageReasonCode = ["character_reference_image", "character_voice_reference", "narrator_voice_reference", "narration_audio", "dialogue_audio", "location_master_image", "location_view_image", "keyframe_reference_image", "keyframe_selected_asset", "segment_video_selected", "segment_video_upscaled", "segment_video_input_image", "segment_video_input_audio", "segment_video_input_video", "final_assembly", "visible_candidate", "unfinished_generation_input", "director_wait"] as const;
export type AssetUsageReasonCode = (typeof AssetUsageReasonCode)[number];
export const ImageAssetCategory = ["character_reference", "location_master", "location_crop", "location_view", "keyframe", "video_frame"] as const;
export type ImageAssetCategory = (typeof ImageAssetCategory)[number];
export const AssetAction = ["audio_trim", "audio_effect", "audio_editor", "video_frame", "delete"] as const;
export type AssetAction = (typeof AssetAction)[number];
export const AudioEffectPreset = ["walkie_talkie", "military_radio", "weak_signal", "bad_signal", "dying_transmission"] as const;
export type AudioEffectPreset = (typeof AudioEffectPreset)[number];
export const ReferenceGenerationKind = ["character_look_sheet", "character_voice", "narrator_voice", "narration_audio", "dialogue_audio", "generated_audio", "audio_effect", "audio_trim", "video_audio_voice", "video_audio_background", "video_audio_remix", "location_master_image", "location_view_crop", "location_view_image", "keyframe_image", "segment_video", "video_frame", "video_upscale", "final_video", "scene_final_video", "scene_animatic"] as const;
export type ReferenceGenerationKind = (typeof ReferenceGenerationKind)[number];
export const GenerationOperation = ["generate", "edit", "attach", "voice_design", "synthesize", "render", "upscale", "assemble", "process", "separate", "remix"] as const;
export type GenerationOperation = (typeof GenerationOperation)[number];
export const ReferenceGenerationPhase = ["submitting", "submission_uncertain", "queued", "running", "succeeded", "failed", "cancelled"] as const;
export type ReferenceGenerationPhase = (typeof ReferenceGenerationPhase)[number];
export const ReferenceGenerationAction = ["attach_output", "select_look_sheet", "select_output", "select_narration_audio", "select_dialogue_audio", "select_segment_video", "attach_upscaled_video", "select_final_video", "dismiss_history", "cancel", "retry"] as const;
export type ReferenceGenerationAction = (typeof ReferenceGenerationAction)[number];
export const KeyframeEnvironmentMode = ["edit", "reference", "none"] as const;
export type KeyframeEnvironmentMode = (typeof KeyframeEnvironmentMode)[number];
export const LocationKind = ["interior", "exterior"] as const;
export type LocationKind = (typeof LocationKind)[number];
export type PlaygroundCapabilityId = string;
export const PlaygroundRunPhase = ["submitting", "submission_uncertain", "queued", "running", "succeeded", "failed", "cancelled"] as const;
export type PlaygroundRunPhase = (typeof PlaygroundRunPhase)[number];
export const PlaygroundRunAction = ["cancel", "retry", "dismiss", "set_note"] as const;
export type PlaygroundRunAction = (typeof PlaygroundRunAction)[number];
export const PlaygroundAssetAction = ["delete", "copy_to_project", "video_frame", "pano_view"] as const;
export type PlaygroundAssetAction = (typeof PlaygroundAssetAction)[number];
export const PlaygroundAssetOriginKind = ["imported", "run_output", "copied_from_project"] as const;
export type PlaygroundAssetOriginKind = (typeof PlaygroundAssetOriginKind)[number];

export interface ProjectSummary {
  id: string;
  title: string;
  aspect_ratio: ProjectAspectRatio;
  updated_at: string;
  status: ProjectStatus;
}

export interface ProjectBootstrap {
  projects: ProjectSummary[];
}

export interface ManifestOption {
  id: string;
  label: string;
}

export interface ManifestField {
  key: string;
  widget: ManifestWidget;
  label: string;
  default: string | number | boolean | null | number[];
  nullable: boolean;
  advanced: boolean;
  options: ManifestOption[];
  minimum: number | null;
  maximum: number | null;
  max_length: number | null;
  min_length: number | null;
  dimension: number | null;
  component_labels: string[];
  role: ManifestRole | null;
  help: string;
}

export interface ManifestSlot {
  key: string;
  role: ManifestRole;
  label: string;
  minimum: number;
  maximum: number;
  media_types: string[];
  duration_seconds: number[] | null;
  describe: "required" | "optional" | "none";
  unique: boolean;
  namespace: string | null;
}

export interface ManifestRecipe {
  id: string;
  capability: ProviderCapabilityId;
  label: string;
  slots: ManifestSlot[];
  params: ManifestField[];
  require_any: string[];
  label_namespaces: Record<string, unknown>;
  skills: string[];
  distinct_slots: string[];
}

export interface ImagePromptConvention {
  namespace: string;
  single_image_label: string | null;
  aspect_ratio_in_prompt: boolean;
}

export interface PluginManifest {
  plugin_id: string;
  plugin_version: number;
  label: string;
  settings: ManifestField[];
  hints: Record<string, unknown>;
  recipes: ManifestRecipe[];
  defaults: Record<string, unknown>;
  image_prompt: ImagePromptConvention | null;
}

export interface ProviderRecipeView {
  capability: ProviderCapabilityId;
  plugin_id: string;
  plugin_label: string;
  recipe: ManifestRecipe;
  editable_params: ManifestField[];
  settings_summary: string;
  hints: Record<string, unknown>;
}

export interface ProviderCandidate {
  plugin_id: string;
  label: string;
}

export interface ProviderCapabilityView {
  id: ProviderCapabilityId;
  label: string;
  bound_plugin_id: string | null;
  candidates: ProviderCandidate[];
  message: string | null;
}

export interface ProviderPluginView {
  plugin_id: string;
  plugin_version: number;
  label: string;
  endpoint: string | null;
  manifest: PluginManifest;
  settings: Record<string, unknown>;
  settings_summary: string;
  settings_error: string | null;
}

export interface ProviderToolView {
  id: string;
  label: string;
  available: boolean;
}

export interface ProviderSettingsView {
  capabilities: ProviderCapabilityView[];
  plugins: ProviderPluginView[];
  tools: ProviderToolView[];
}

export interface ProjectDetail {
  project: ProjectSummary;
  structured_director: StructuredDirectorSnapshot;
}

export interface ActiveDirectorRun {
  id: string;
  kind: DirectorRunKind;
  status: "running" | "waiting_user" | "waiting_jobs";
  waiting_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface CharacterLook {
  id: string;
  name: string;
  appearance: string;
  usage: string;
  selected_asset_id: string | null;
}

export interface DialogueLine {
  id: string;
  character_id: string | null;
  speaker_label: string | null;
  voice_description: string | null;
  text: string;
  delivery: string;
}

export interface DialogueAudio {
  dialogue_line_id: string;
  seed: number;
  recipe_params: Record<string, unknown>;
  selected_audio_asset_id: string | null;
  start_seconds: number | null;
}

export interface DialoguePlan {
  source_script_revision: number;
  items: DialogueAudio[];
}

export interface DialogueTimingWarning {
  segment_id: string;
  estimated_seconds: number;
  duration_seconds: number;
}

export interface SegmentBoundary {
  reason: SegmentBoundaryReason;
  continuity_instruction: string;
}

export interface ShotSegment {
  id: string;
  shot_ids: string[];
  duration_estimate_seconds: number;
  action: string;
  dialogue_lines: DialogueLine[];
  boundary_from_previous: SegmentBoundary | null;
}

export interface Shot {
  id: string;
  visible_character_ids: string[];
  composition: string;
  camera_movement: string;
  action: string;
  audio_direction: string;
  transition_in: string | null;
  view_id: string | null;
}

export interface SceneAnimaticState {
  reason: string;
  provider_available: boolean;
  ready: boolean;
  active_generation_id: string | null;
  latest_succeeded_generation_id: string | null;
}

export interface SceneFinalLanguageState {
  active_generation_id: string | null;
  latest_succeeded_generation_id: string | null;
  current_asset_id: string | null;
  outdated: boolean;
}

export interface SceneFinalState {
  reason: string;
  provider_available: boolean;
  ready: boolean;
  zh: SceneFinalLanguageState | null;
  en: SceneFinalLanguageState | null;
}

export interface Scene {
  location_id: string | null;
  state_id: string | null;
  driver: "narration" | "drama";
  id: string;
  title: string;
  summary: string;
  setting: string;
  shots: Shot[];
  segments: ShotSegment[];
  narration_cues: NarrationCue[];
  animatic?: SceneAnimaticState;
  scene_final?: SceneFinalState;
}

export interface NarrationTrack {
  text: string;
  seed: number;
  selected_audio_asset_id: string | null;
  recipe_params: Record<string, Record<string, unknown>>;
  selected_duration_seconds: number | null;
}

export interface NarrationCue {
  id: string;
  zh: NarrationTrack | null;
  en: NarrationTrack | null;
  timing_language: NarrationLanguage | null;
  timing_seconds: number | null;
}

export interface DirectorScript {
  revision: number;
  source_reference_revision: number;
  production_baseline_revision: number | null;
  production_baseline_scenes: Scene[] | null;
  scenes: Scene[];
}

export interface LocationProduction {
  status: string;
  status_label: string;
  reason: string | null;
  generation_step: "master" | "crop" | "refine" | "turn";
  generate_label: string;
  active_generation_id: string | null;
  candidate_generation_ids: string[];
  selectable_generation_ids: string[];
  allowed_actions: ("generate" | "select" | "edit" | "delete" | "clear_selection")[];
}

export interface LocationFixture {
  allowed_actions?: ("edit" | "delete")[];
  id: string;
  name: string;
  description: string;
  azimuth_deg: number | null;
}

export interface LocationKeyLight {
  description: string;
  azimuth_deg: number | null;
}

export interface LocationMaster {
  production?: LocationProduction;
  prompt_text: string;
  reference_asset_ids: string[];
  selected_asset_id: string | null;
}

export interface LocationState {
  id: string;
  name: string;
  description: string;
  allowed_actions?: ("edit" | "delete")[];
}

export interface LocationView {
  production?: LocationProduction;
  has_valid_crop?: boolean;
  id: string;
  name: string;
  purpose: string;
  azimuth_deg: number | null;
  look_at_fixture_id: string | null;
  yaw_offset_deg: number | null;
  pitch_deg: number;
  hfov_deg: number;
  state_id: string | null;
  refine_prompt_text: string;
  reference_view_ids: string[];
  crop_asset_id: string | null;
  selected_asset_id: string | null;
}

export interface Location {
  allowed_actions?: ("edit" | "delete" | "create_view" | "create_fixture" | "create_state")[];
  id: string;
  name: string;
  kind: LocationKind;
  description: string;
  fixtures: LocationFixture[];
  key_light: LocationKeyLight | null;
  master: LocationMaster;
  calibrated_master_asset_id: string | null;
  states: LocationState[];
  views: LocationView[];
}

export interface LocationLibrary {
  locations: Location[];
  allowed_actions?: ("create_location" | "bind_scene" | "bind_shot")[];
}

export interface Keyframe {
  id: string;
  owner_segment_id: string;
  predecessor_keyframe_id: string | null;
  prompt_text: string;
  visible_character_ids: string[];
  character_references: KeyframeCharacterReference[];
  selected_asset_id: string | null;
  environment_mode: KeyframeEnvironmentMode;
  environment_view_id: string | null;
  environment_none_reason: string | null;
}

export interface KeyframeCharacterReference {
  character_id: string;
  look_id: string | null;
}

export interface StartFrameExtraction {
  source_segment_id: string | null;
  source_video_asset_id: string | null;
  state: "ready" | "unavailable" | "shared_boundary" | "waiting_source_video" | "source_not_current";
  message: string;
}

export interface SegmentKeyframes {
  segment_id: string;
  start_keyframe_id: string;
  end_keyframe_id: string;
  start_enabled: boolean;
  end_enabled: boolean;
  reference_asset_ids: string[];
  start_frame_extraction: StartFrameExtraction;
}

export interface KeyframePlan {
  source_script_revision: number;
  keyframes: Keyframe[];
  segments: SegmentKeyframes[];
}

export interface RecipeBinding {
  asset_id: string;
  description: string | null;
}

export interface RecipeInputs {
  bindings: Record<string, RecipeBinding[]>;
  params: Record<string, unknown>;
}

export interface VideoRecipeOption {
  id: string;
  label: string;
  allowed: boolean;
  reason: string | null;
}

export interface RecipeInputLabel {
  slot: string;
  role: ManifestRole;
  index: number;
  asset_id: string;
  description: string | null;
  label: string | null;
}

export interface VideoRecipeState {
  available: boolean;
  ready: boolean;
  reason: string | null;
  options: VideoRecipeOption[];
  duration_seconds: number;
  soft_duration_limit_seconds: number | null;
  bindings: RecipeInputLabel[];
  slot_labels: Record<string, (string | null)[]>;
}

export interface SegmentVideo {
  segment_id: string;
  prompt_text: string;
  active_recipe: string | null;
  recipe_state?: VideoRecipeState;
  recipes: Record<string, RecipeInputs>;
  selected_asset_id: string | null;
  upscaled_asset_id: string | null;
}

export interface VideoPlan {
  source_script_revision: number;
  segments: SegmentVideo[];
}

export interface FinalAssemblyClip {
  scene_id: string;
  zh_asset_id: string | null;
  en_asset_id: string | null;
  transition_from_previous: null | "seam_blend";
}

export interface FinalAssemblyPlan {
  source_script_revision: number;
  clips: FinalAssemblyClip[];
  selected_zh_asset_id: string | null;
  selected_en_asset_id: string | null;
}

export interface FinalApproval {
  zh_asset_id: string | null;
  zh_generation_id: string | null;
  en_asset_id: string | null;
  en_generation_id: string | null;
  source_script_revision: number;
  approved_project_revision: number;
}

export interface AssetUsageReason {
  code: AssetUsageReasonCode;
  label: string;
}

export interface ProjectAsset {
  id: string;
  media_type: "image/png" | "image/jpeg" | "image/webp" | "audio/wav" | "video/mp4";
  image_category: ImageAssetCategory | null;
  byte_count: number;
  duration_seconds: number | null;
  display_name?: string;
  content_url: string;
  is_in_use: boolean;
  usage_reasons: AssetUsageReason[];
  retains_derived_assets_on_delete: boolean;
  allowed_actions: AssetAction[];
}

export interface SubmissionAttachment {
  asset_id: string;
  display_name: string;
  content_url: string;
  role: "source_image" | "reference_image";
  input_roles: string[];
  purpose: string;
}

export interface ImageSubmissionPreview {
  reference_prompt: string;
  instruction: string | null;
  ready: boolean;
  operation: ImageOperation;
  attachments: SubmissionAttachment[];
}

export interface GenerationProvider {
  plugin_id: string;
  recipe_id: string;
  summary: string;
}

export interface ReferenceGeneration {
  id: string;
  kind: ReferenceGenerationKind;
  operation: GenerationOperation;
  target_id: string;
  phase: ReferenceGenerationPhase;
  progress: number;
  message: string;
  prompt_text: string;
  input_asset_ids: string[];
  sample_text: string | null;
  language: NarrationLanguage | null;
  aspect_ratio?: ImageAspectRatio | null;
  seed: number | string | null;
  duration_seconds?: number | null;
  output_asset_id: string | null;
  error_code: string | null;
  cancellation_requested: boolean;
  retry_of: string | null;
  dismissed: boolean;
  provider?: GenerationProvider | null;
  inputs_outdated?: boolean;
  allowed_actions: ReferenceGenerationAction[];
}

export interface WorkspaceLayers {
  narration_unlocked: boolean;
  keyframes_unlocked: boolean;
  videos_unlocked: boolean;
  final_assembly_unlocked: boolean;
}

export interface ProviderAvailability {
  image_generation: boolean;
  voice_design: boolean;
  speech_synthesis: boolean;
  speech_recognition?: boolean;
  video_generation?: boolean;
  video_upscale?: boolean;
  final_assembly?: boolean;
  scene_animatic?: boolean;
  audio_separation?: boolean;
  audio_remix?: boolean;
}

export interface ReferenceLibraryView {
  reviewed?: boolean;
  characters: CharacterCard[];
  narrator: NarratorProfile | null;
}

export interface CharacterCard {
  id: string;
  name: string;
  visual_description: string | null;
  voice_description: string;
  voice_reference_asset_id: string | null;
  voice_reference_transcript?: string | null;
  looks: CharacterLook[];
}

export interface NarratorProfile {
  id: string;
  name: string;
  zh: NarratorVoice | null;
  en: NarratorVoice | null;
}

export interface NarratorVoice {
  voice_description: string;
  voice_reference_asset_id: string | null;
  voice_reference_transcript: string | null;
}

export interface ProductionAvailabilityEntry {
  unlocked: boolean;
  reason: string;
  next_location: "project";
  action: string | null;
}

export interface ProductionAvailability {
  narration: ProductionAvailabilityEntry;
  keyframes: ProductionAvailabilityEntry;
  videos: ProductionAvailabilityEntry;
  final: ProductionAvailabilityEntry;
}

export interface WorkflowAction {
  action: string;
  tool: string | null;
  target_ids: string[];
  human_only: boolean;
  requires_explicit_user_request: boolean;
  [key: string]: unknown;
}

export interface WorkflowSemantics {
  current_stage: "primary_workflow_focus_not_capability_lock";
  active_task: "primary_workflow_task_only_parallel_activity_uses_task_discovery";
  required_next_actions: "primary_workflow_actions_only";
}

export interface WorkspaceCapabilities {
  semantics: "cumulative_unlocked_layers_not_primary_workflow";
  unlocked: ("narration" | "keyframe" | "video" | "final")[];
}

export interface ActivitySummary {
  active_generation_count: number;
  has_active_generations: boolean;
  task_discovery_tool: "read_workflow";
  semantics: "parallel_project_activity_not_primary_workflow";
}

export interface BlockedActionReason {
  reason: string;
}

export interface WorkflowState {
  current_stage: string;
  stage_status: string;
  semantics: WorkflowSemantics;
  required_next_actions: WorkflowAction[];
  recommended_next_actions?: WorkflowAction[];
  blocking_prerequisites: string[];
  blocked_actions: Record<string, BlockedActionReason>;
  workspace_capabilities: WorkspaceCapabilities;
  activity_summary: ActivitySummary;
  requires_explicit_user_request: boolean;
  active_task: Record<string, unknown> | null;
}

export interface CapabilityGapAlert {
  gap_id: string;
  run_id: string;
  missing_command: string;
  raw_user_request_summary: string;
  target_ids: string[];
  scope_scene_ids: string[];
  operation_summary: string;
  old_revision: number;
  new_revision: number;
  result: "succeeded" | "noop";
  first_occurred_at: string;
  last_occurred_at: string;
  occurrence_count: number;
  closed_revision: number | null;
  closed_by_command: string | null;
  status: "open" | "closed";
}

export interface StructuredDirectorSnapshot {
  status: StructuredDirectorStatus;
  active_director_run: ActiveDirectorRun | null;
  revision: number;
  aspect_ratio: ProjectAspectRatio;
  director_plan_markdown: string;
  narration_languages: NarrationLanguage[];
  workspace_layers: WorkspaceLayers;
  allowed_actions: StructuredDirectorAction[];
  workflow: WorkflowState;
  dialogue_timing_warnings: DialogueTimingWarning[];
  provider_availability: ProviderAvailability;
  assets: ProjectAsset[];
  generations: ReferenceGeneration[];
  reference_library: ReferenceLibraryView;
  director_script: DirectorScript | null;
  dialogue_plan?: DialoguePlan | null;
  production_availability: ProductionAvailability;
  location_library: LocationLibrary;
  keyframe_plan: KeyframePlan | null;
  video_plan?: VideoPlan | null;
  final_assembly?: FinalAssemblyPlan | null;
  final_approval: FinalApproval | null;
  capability_gap_alerts: CapabilityGapAlert[];
  provider_recipes?: ProviderRecipeView[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  recoverable: boolean;
  origin: string;
  state_changed: boolean | "unknown";
  retry_policy: string;
  automatic_retry_allowed: boolean;
  expected_revision?: number;
  current_revision?: number;
}

export interface ApiErrorPayload {
  error: ApiErrorBody;
}

export interface AudioTrimSettings {
  start_seconds: number;
  end_seconds: number;
}

export interface AudioEffectSettings {
  effect: "radio";
  preset: AudioEffectPreset;
  strength: number;
  seed: number;
  start_seconds?: number;
  end_seconds?: number;
}

export interface AudioGainSettings {
  gain_db: number;
  start_seconds?: number;
  end_seconds?: number;
}

export interface AudioGenerationSettings {
  operation: "voice_design" | "synthesize";
  text: string;
  voice_description?: string;
  voice_asset_id?: string;
  reference_transcript?: string;
  recipe_params?: Record<string, Record<string, unknown>>;
  seed: number;
}

export interface PlaygroundRecipe {
  plugin_id: string;
  plugin_label: string;
  recipe: ManifestRecipe;
}

export interface PlaygroundCapabilityInfo {
  id: PlaygroundCapabilityId;
  label: string;
  execution: "async" | "sync";
  group: "image" | "speech" | "video" | "audio";
  available: boolean;
  notes: string;
  recipe?: PlaygroundRecipe | null;
  parameters_schema?: Record<string, unknown>;
}

export interface PlaygroundAssetOrigin {
  kind: PlaygroundAssetOriginKind;
  run_id?: string;
  project_id?: string;
  asset_id?: string;
}

export interface PlaygroundAssetUsageReason {
  code: string;
  label: string;
}

export interface PlaygroundAsset {
  id: string;
  media_type: "image/png" | "image/jpeg" | "image/webp" | "audio/wav" | "video/mp4";
  byte_count: number;
  sha256: string;
  relative_path: string;
  duration_seconds: number | null;
  origin: PlaygroundAssetOrigin;
  created_at: string;
  display_name: string;
  content_url: string;
  is_in_use: boolean;
  usage_reasons: PlaygroundAssetUsageReason[];
  allowed_actions: PlaygroundAssetAction[];
}

export interface PlaygroundRunRecovery {
  failure_origin: string | null;
  retry_policy: string;
  automatic_retry_allowed: boolean;
}

export interface PlaygroundInputLabel {
  label: string;
  provider_input: string;
  asset_id: string;
  description: string | null;
}

export interface PlaygroundRecipePreview {
  ready: boolean;
  reason: string | null;
  input_labels: PlaygroundInputLabel[];
}

export interface PlaygroundRun {
  id: string;
  capability: PlaygroundCapabilityId;
  capability_label: string;
  phase: PlaygroundRunPhase;
  progress: number;
  message: string;
  parameters: Record<string, unknown>;
  input_asset_ids: string[];
  seed: number | null;
  plugin_id: string | null;
  plugin_version: number | null;
  external_id: string | null;
  output_asset_id: string | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
  cancellation_requested: boolean;
  retry_of: string | null;
  note: string | null;
  dismissed: boolean;
  provider?: GenerationProvider | null;
  created_at: string;
  updated_at: string;
  recovery: PlaygroundRunRecovery;
  allowed_actions: PlaygroundRunAction[];
  input_labels?: PlaygroundInputLabel[];
}

export interface PlaygroundSnapshot {
  schema_version: number;
  revision: number;
  capabilities: PlaygroundCapabilityInfo[];
  runs: PlaygroundRun[];
  assets: PlaygroundAsset[];
}

export interface PlaygroundCommandReceipt {
  command_id: string;
  status: "succeeded" | "noop";
  old_revision: number;
  new_revision: number;
  decision_summary: string;
}

export interface PlaygroundCopyToProjectResult {
  asset_id: string;
  project_revision: number;
}

export interface PlaygroundAssetResult {
  asset: PlaygroundAsset;
}

export interface ReferenceLibraryProposal {
  characters: CharacterCardProposal[];
  narrator: NarratorProfileProposal | null;
}

export interface CharacterCardProposal {
  name: string;
  visual_description: string | null;
  voice_description: string;
  looks: CharacterLookProposal[];
}

export interface CharacterLookProposal {
  name: string;
  appearance: string;
  usage: string;
}

export interface NarratorProfileProposal {
  name: string;
  zh_voice_description: string | null;
  en_voice_description: string | null;
}

export interface StructuredDirectorScriptProposal {
  scenes: SceneProposal[];
}

export interface SceneProposal {
  title: string;
  summary: string;
  setting: string;
  shots: ShotProposal[];
  segments: ShotSegmentProposal[];
  narration_cues: NarrationCueProposal[];
  driver: "narration" | "drama";
}

export interface ShotProposal {
  visible_character_ids: string[];
  composition: string;
  camera_movement: string;
  action: string;
  audio_direction: string;
  transition_in: string | null;
}

export interface ShotSegmentProposal {
  shot_indexes: number[];
  duration_estimate_seconds: number;
  action: string;
  dialogue_lines: DialogueLineProposal[];
  boundary_from_previous: SegmentBoundaryProposal | null;
}

export interface DialogueLineProposal {
  character_id: string | null;
  text: string;
  delivery: string;
  speaker_label?: string | null;
  id?: string | null;
  voice_description?: string | null;
}

export interface SegmentBoundaryProposal {
  reason: "model_constraint" | "continuity_anchor" | "control_boundary" | "failure_cost";
  continuity_instruction: string;
}

export interface NarrationCueProposal {
  zh: NarrationTrackProposal | null;
  en: NarrationTrackProposal | null;
}

export interface NarrationTrackProposal {
  text: string;
  seed: number;
  recipe_params?: Record<string, Record<string, string | number | boolean | null | number[]>>;
}

export interface StructuredDirectorScriptRevisionProposal {
  reply_markdown: string;
  operations: ScriptRevisionOperationProposal[];
}

export interface ScriptRevisionOperationProposal {
  operation: "replace_scene" | "insert_scene" | "delete_scene" | "move_scene" | "replace_segment";
  scene_id: string | null;
  after_scene_id: string | null;
  scene: EditableSceneProposal | null;
  segment: EditableShotSegmentProposal | null;
}

export interface EditableSceneProposal {
  id: string | null;
  title: string;
  summary: string;
  setting: string;
  shots: EditableShotProposal[];
  segments: EditableShotSegmentProposal[];
  narration_cues: EditableNarrationCueProposal[];
  driver: "narration" | "drama";
}

export interface EditableShotProposal {
  id: string | null;
  visible_character_ids: string[];
  composition: string;
  camera_movement: string;
  action: string;
  audio_direction: string;
  transition_in: string | null;
}

export interface EditableShotSegmentProposal {
  id: string | null;
  shot_indexes: number[];
  duration_estimate_seconds: number;
  action: string;
  dialogue_lines: DialogueLineProposal[];
  boundary_from_previous: SegmentBoundaryProposal | null;
}

export interface EditableNarrationCueProposal {
  id: string | null;
  zh: NarrationTrackProposal | null;
  en: NarrationTrackProposal | null;
}

export interface NarrationReviewProposal {
  reply_markdown: string;
  cue_updates: NarrationCueUpdate[];
}

export interface NarrationCueUpdate {
  cue_id: string;
  language: "zh" | "en";
  seed: number;
  regenerate: boolean;
  recipe_params: Record<string, Record<string, string | number | boolean | null | number[]>>;
}

export interface KeyframePlanProposal {
  segments: KeyframeSegmentProposal[];
}

export interface KeyframeSegmentProposal {
  segment_id: string;
  continues_from_previous: boolean;
  frame_strategy: "start" | "end" | "both";
  start_prompt_text: string;
  start_visible_character_ids: string[];
  end_prompt_text: string;
  end_visible_character_ids: string[];
  start_environment_mode: "edit" | "reference" | "none" | null;
  start_environment_view_id: string | null;
  start_environment_none_reason: string | null;
  start_character_references: KeyframeCharacterReferenceProposal[];
  end_environment_mode: "edit" | "reference" | "none" | null;
  end_environment_view_id: string | null;
  end_environment_none_reason: string | null;
  end_character_references: KeyframeCharacterReferenceProposal[];
}

export interface KeyframeCharacterReferenceProposal {
  character_id: string;
  look_id: string | null;
}

export interface LocationPlanProposal {
  locations: LocationProposal[];
  scene_bindings: SceneLocationBindingProposal[];
  shot_bindings: ShotViewBindingProposal[];
}

export interface LocationProposal {
  name: string;
  kind: "interior" | "exterior";
  description: string;
  key_light: LocationKeyLightProposal | null;
  master_prompt_text: string;
  fixtures: LocationFixtureProposal[];
  states: LocationStateProposal[];
  views: LocationViewProposal[];
  id?: string | null;
  key?: string | null;
}

export interface LocationKeyLightProposal {
  description: string;
  azimuth_deg: number | null;
}

export interface LocationFixtureProposal {
  name: string;
  description: string;
  azimuth_deg: number | null;
  id?: string | null;
  key?: string | null;
}

export interface LocationStateProposal {
  name: string;
  description: string;
  id?: string | null;
  key?: string | null;
}

export interface LocationViewProposal {
  name: string;
  purpose: string;
  azimuth_deg: number | null;
  look_at_fixture_id: string | null;
  yaw_offset_deg: number | null;
  pitch_deg: number;
  hfov_deg: number;
  state_id: string | null;
  refine_prompt_text: string;
  reference_view_ids: string[];
  id?: string | null;
  key?: string | null;
}

export interface SceneLocationBindingProposal {
  scene_id: string;
  location_id: string | null;
  state_id: string | null;
}

export interface ShotViewBindingProposal {
  shot_id: string;
  view_id: string | null;
}

export interface VideoPromptProposal {
  prompt_text: string;
}

export type KeyframeSubmissionPreview = ImageSubmissionPreview;
export type StructuredDirectorDetail = ProjectDetail;
