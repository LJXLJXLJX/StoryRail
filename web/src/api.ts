import type { LocationChange, LocationImpact } from "./api/location";
import { parseScriptImpact, type ScriptChange, type ScriptImpact } from "./api/script";
import { isVideoRecipeState } from "./api/validation";
import { parseStoryProjection, type ProjectionRequest } from "./api/projection";
import type {
  ProjectAspectRatio,
  CharacterCard,
  CharacterLook,
  NarratorProfile,
  Scene,
  NarrationCue,
  ImageAssetCategory,
  AudioGenerationSettings,
  AudioTrimSettings,
  AudioEffectSettings,
  AudioGainSettings,
  StructuredDirectorSnapshot,
  KeyframeCharacterReference,
  ApiErrorPayload,
  NarrationLanguage,
  NarrationTrack,
} from "./api/types";
import {
  parseProjectList,
  parseProjectBootstrap,
  parseProviderSettings,
  parseAudioTranscription,
  parseProjectDetail,
  parseDeleteResult,
  parseStructuredDirectorSnapshot,
  parseError,
  parseImageSubmissionPreview,
  editableScenePayload,
  isRecord,
} from "./api/validation";
export type * from "./api/types";
export type {
  ScriptChange,
  ScriptImpact,
  ScriptOperation,
  ScriptOperationsPatch,
  ScriptSegmentDraft,
} from "./api/script";

/** 人类整卡回传：只含造型文字，新造型的 id 为 null 由 Core 分配；造型图只经选择入口改变。 */
export type CharacterLookDraft = Omit<CharacterLook, "id" | "selected_asset_id"> & {
  id: string | null;
};
export type CharacterCardDraft = Omit<CharacterCard, "looks"> & { looks: CharacterLookDraft[] };

/** 旁白单语轨道中用户可编辑并回传给 Core 的字段；已选音频与时长由 Core 维护。 */
function editableNarrationTrack(track: NarrationTrack | null) {
  if (track === null) return null;
  return {
    text: track.text.trim(),
    seed: track.seed,
    recipe_params: track.recipe_params,
  };
}
export { isVideoSeed } from "./api/validation";
export class StoryRailApiError extends Error {
  readonly code: string;
  readonly recoverable: boolean;
  constructor(payload: ApiErrorPayload) {
    super(payload.error.message);
    this.name = "StoryRailApiError";
    this.code = payload.error.code;
    this.recoverable = payload.error.recoverable;
  }
}
export const projectApi = {
  list: () => request("/api/projects", parseProjectList),
  bootstrap: () => request("/api/projects", parseProjectBootstrap),
  create: (
    title: string,
    aspectRatio: ProjectAspectRatio,
    directorPlanMarkdown: string,
    narrationLanguages: NarrationLanguage[],
  ) =>
    request("/api/projects", parseProjectDetail, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        aspect_ratio: aspectRatio,
        director_plan_markdown: directorPlanMarkdown,
        narration_languages: narrationLanguages,
      }),
    }),
  delete: (projectId: string) =>
    request(`/api/projects/${projectId}`, parseDeleteResult, {
      method: "DELETE",
    }),
};
/** 全局 Provider 设置：插件实例设置与能力绑定；只影响之后新提交的任务。 */
export const providerSettingsApi = {
  read: () => request("/api/settings/providers", parseProviderSettings),
  bind: (capability: string, pluginId: string) =>
    request("/api/settings/providers/bindings", parseProviderSettings, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capability, plugin_id: pluginId }),
    }),
  updatePlugin: (pluginId: string, settings: Record<string, unknown>) =>
    request(
      `/api/settings/providers/plugins/${encodeURIComponent(pluginId)}`,
      parseProviderSettings,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      },
    ),
};
export const structuredDirectorApi = {
  updateDirectorPlan: (
    projectId: string,
    revision: number,
    directorPlanMarkdown: string,
  ) =>
    structuredMutation(projectId, "director-plan", {
      expected_revision: revision,
      director_plan_markdown: directorPlanMarkdown,
    }, "PUT"),
  confirmReferences: (projectId: string, revision: number) =>
    request(`${structuredDirectorResource(projectId)}/commands`, value => value, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        name: "reference.confirm_review",
        expected_revision: revision,
        idempotency_key: `reference-review-${revision}`,
        arguments: {},
      }),
    }),
  getProjection: (
    projectId: string,
    revision: number,
    query: ProjectionRequest,
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/commands`,
      (value) => {
        if (!isRecord(value) || !isRecord(value.receipt))
          throw new Error("故事读取回执格式不正确。");
        return parseStoryProjection(value.data);
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "project.get_projection",
          expected_revision: revision,
          idempotency_key: "story-reader",
          arguments: query,
        }),
      },
    ),
  previewLocationChange: (
    projectId: string,
    revision: number,
    change: LocationChange,
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/commands`,
      (value): LocationImpact => {
        const data = isRecord(value) ? value.data : null;
        if (
          !isRecord(data) ||
          typeof data.revision !== "number" ||
          typeof data.command_name !== "string" ||
          typeof data.will_write !== "boolean" ||
          typeof data.high_impact !== "boolean" ||
          ![data.changed_ids, data.invalidated, data.preserved].every(
            (items) =>
              Array.isArray(items) && items.every((x) => typeof x === "string"),
          ) ||
          !Array.isArray(data.soft_reference_clears) ||
          !data.soft_reference_clears.every(
            (item) =>
              isRecord(item) &&
              typeof item.shot_id === "string" &&
              typeof item.scene_id === "string" &&
              typeof item.label === "string",
          )
        )
          throw new Error("地点影响预览格式不正确。");
        return data as unknown as LocationImpact;
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "project.preview_impact",
          expected_revision: revision,
          idempotency_key: "location-preview",
          arguments: {
            command: {
              ...change,
              expected_revision: revision,
              idempotency_key: "location-edit",
            },
          },
        }),
      },
    ),
  applyLocationChange: (
    projectId: string,
    revision: number,
    change: LocationChange,
  ) => {
    if (change.name === "location.apply_operations")
      return structuredMutation(projectId, "locations/operations", {
        expected_revision: revision,
        ...change.arguments,
      });
    return structuredMutation(
      projectId,
      `location-images/${change.arguments.image_id}/select`,
      { expected_revision: revision, asset_id: change.arguments.asset_id },
    );
  },
  generateLocationImage: (
    projectId: string,
    revision: number,
    imageId: string,
  ) =>
    structuredMutation(projectId, `location-images/${imageId}/generate`, {
      expected_revision: revision,
    }),
  captureLocationPanorama: (
    projectId: string,
    revision: number,
    panoramaImageId: string,
    name: string,
    description: string,
    yawDeg: number,
    pitchDeg: number,
    hfovDeg: number,
  ) => structuredMutation(projectId, `location-images/${panoramaImageId}/capture`, {
    expected_revision: revision,
    name,
    description,
    yaw_deg: yawDeg,
    pitch_deg: pitchDeg,
    hfov_deg: hfovDeg,
  }),
  previewScriptChange: (
    projectId: string,
    revision: number,
    change: ScriptChange,
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/commands`,
      (value): ScriptImpact => {
        const data = isRecord(value) ? value.data : null;
        return parseScriptImpact(data);
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "project.preview_impact",
          expected_revision: revision,
          idempotency_key: `script-preview-${revision}`,
          arguments: {
            command: {
              ...change,
              expected_revision: revision,
              idempotency_key: `script-edit-${revision}`,
            },
          },
        }),
      },
    ),
  applyScriptChange: (
    projectId: string,
    revision: number,
    change: ScriptChange,
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/commands`,
      (value) => {
        if (!isRecord(value) || !isRecord(value.snapshot))
          throw new Error("脚本修改回执缺少项目快照。");
        return parseStructuredDirectorSnapshot(value.snapshot);
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "script.apply_operations",
          expected_revision: revision,
          idempotency_key: `script-edit-${revision}`,
          arguments: change.arguments,
        }),
      },
    ),
  get: (projectId: string) =>
    request(
      structuredDirectorResource(projectId),
      parseStructuredDirectorSnapshot,
    ),
  saveScript: (projectId: string, revision: number, scenes: Scene[]) =>
    request(
      `${structuredDirectorResource(projectId)}/director-script`,
      parseStructuredDirectorSnapshot,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          scenes: scenes.map(editableScenePayload),
        }),
      },
    ),
  confirmScript: (projectId: string, revision: number) =>
    structuredMutation(projectId, "director-script/confirm", {
      expected_revision: revision,
    }),
  saveNarrationCue: (
    projectId: string,
    revision: number,
    sceneId: string,
    cue: NarrationCue,
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/scenes/${sceneId}/narration-cues/${cue.id}`,
      parseStructuredDirectorSnapshot,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          zh: editableNarrationTrack(cue.zh),
          en: editableNarrationTrack(cue.en),
        }),
      },
    ),
  generateNarration: (
    projectId: string,
    revision: number,
    sceneId: string,
    cueId: string,
    language: NarrationLanguage,
  ) =>
    structuredMutation(
      projectId,
      `scenes/${sceneId}/narration-cues/${cueId}/generate`,
      {
        expected_revision: revision,
        language,
      },
    ),
  generateNarrationBatch: (projectId: string, revision: number) =>
    structuredMutation(projectId, "narration/generate-batch", {
      expected_revision: revision,
    }),
  selectNarrationAudio: (
    projectId: string,
    revision: number,
    sceneId: string,
    cueId: string,
    generationId: string,
  ) =>
    structuredMutation(
      projectId,
      `scenes/${sceneId}/narration-cues/${cueId}/select`,
      { expected_revision: revision, generation_id: generationId },
    ),
  generateDialogue: (projectId: string, revision: number, dialogueLineId: string) =>
    structuredMutation(projectId, `dialogue-lines/${dialogueLineId}/generate`, {
      expected_revision: revision,
    }),
  saveDialogueRecipeParams: (
    projectId: string,
    revision: number,
    dialogueLineId: string,
    recipeParams: Record<string, unknown>,
  ) =>
    structuredMutation(
      projectId,
      `dialogue-lines/${dialogueLineId}/recipe-params`,
      { expected_revision: revision, recipe_params: recipeParams },
      "PUT",
    ),
  generateDialogueBatch: (projectId: string, revision: number) =>
    structuredMutation(projectId, "dialogue/generate-batch", {
      expected_revision: revision,
    }),
  selectDialogueAudio: (
    projectId: string,
    revision: number,
    dialogueLineId: string,
    generationId: string,
  ) =>
    structuredMutation(projectId, `dialogue-lines/${dialogueLineId}/select`, {
      expected_revision: revision,
      generation_id: generationId,
    }),
  setDialogueTiming: (
    projectId: string,
    revision: number,
    segmentId: string,
    starts: Record<string, number>,
    durationSeconds: number,
  ) =>
    structuredMutation(
      projectId,
      `segments/${segmentId}/dialogue-timing`,
      {
        expected_revision: revision,
        starts,
        duration_seconds: durationSeconds,
      },
      "PUT",
    ),
  autoCalibrateDialogueTimings: (projectId: string, revision: number) =>
    structuredMutation(projectId, "dialogue/auto-calibrate-timing", {
      expected_revision: revision,
    }),
  clearNarrationAudioSelection: (
    projectId: string,
    revision: number,
    sceneId: string,
    cueId: string,
    language: NarrationLanguage,
  ) =>
    structuredMutation(
      projectId,
      `scenes/${sceneId}/narration-cues/${cueId}/clear-selection`,
      { expected_revision: revision, language },
    ),
  generateSceneAnimatic: (
    projectId: string,
    revision: number,
    sceneId: string,
  ) =>
    structuredMutation(projectId, `scenes/${sceneId}/animatic`, {
      expected_revision: revision,
    }),
  generateSceneFinal: (
    projectId: string,
    revision: number,
    sceneId: string,
    videoAudioVolume = 1,
    narrationAudioVolume = 1,
  ) =>
    structuredMutation(projectId, `scenes/${sceneId}/final`, {
      expected_revision: revision,
      video_audio_volume: videoAudioVolume,
      narration_audio_volume: narrationAudioVolume,
    }),
  unlockVisualProduction: (projectId: string, revision: number) =>
    unlockVisualProductionWithRevisionRetry(projectId, revision),
  generateKeyframeBatch: (projectId: string, revision: number) =>
    structuredMutation(projectId, "keyframes/generate-batch", {
      expected_revision: revision,
    }),
  generateKeyframe: (projectId: string, revision: number, keyframeId: string) =>
    structuredMutation(projectId, `keyframes/${keyframeId}/generate`, {
      expected_revision: revision,
    }),
  saveKeyframe: (
    projectId: string,
    revision: number,
    keyframeId: string,
    segmentId: string,
    promptText: string,
    visibleCharacterIds: string[],
    characterReferences: KeyframeCharacterReference[],
    referenceAssetIds: string[],
  ) =>
    structuredMutation(
      projectId,
      `keyframes/${keyframeId}`,
      {
        expected_revision: revision,
        segment_id: segmentId,
        prompt_text: promptText,
        visible_character_ids: visibleCharacterIds,
        character_references: characterReferences,
        reference_asset_ids: referenceAssetIds,
      },
      "PUT",
    ),
  previewKeyframe: (
    projectId: string,
    revision: number,
    keyframeId: string,
    segmentId: string,
    promptText: string,
    visibleCharacterIds: string[],
    characterReferences: KeyframeCharacterReference[],
    referenceAssetIds: string[],
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/keyframes/${keyframeId}/preview`,
      parseImageSubmissionPreview,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          segment_id: segmentId,
          prompt_text: promptText,
          visible_character_ids: visibleCharacterIds,
          character_references: characterReferences,
          reference_asset_ids: referenceAssetIds,
        }),
      },
    ),
  selectKeyframe: (
    projectId: string,
    revision: number,
    keyframeId: string,
    assetId: string,
  ) =>
    structuredMutation(projectId, `keyframes/${keyframeId}/select`, {
      expected_revision: revision,
      asset_id: assetId,
    }),
  saveSegmentKeyframeReferences: (
    projectId: string,
    revision: number,
    segmentId: string,
    assetIds: string[],
  ) =>
    structuredMutation(
      projectId,
      `segments/${segmentId}/keyframe-references`,
      {
        expected_revision: revision,
        asset_ids: assetIds,
      },
      "PUT",
    ),
  saveSegmentKeyframeActivation: (
    projectId: string,
    revision: number,
    segmentId: string,
    startEnabled: boolean,
    endEnabled: boolean,
    expectedBinding: {
      startKeyframeId: string;
      endKeyframeId: string;
      startEnabled: boolean;
      endEnabled: boolean;
      startSelectedAssetId: string | null;
      endSelectedAssetId: string | null;
    },
  ) =>
    structuredMutation(
      projectId,
      `segments/${segmentId}/keyframe-activation`,
      {
        expected_revision: revision,
        start_enabled: startEnabled,
        end_enabled: endEnabled,
        expected_start_keyframe_id: expectedBinding.startKeyframeId,
        expected_end_keyframe_id: expectedBinding.endKeyframeId,
        expected_start_enabled: expectedBinding.startEnabled,
        expected_end_enabled: expectedBinding.endEnabled,
        expected_start_selected_asset_id: expectedBinding.startSelectedAssetId,
        expected_end_selected_asset_id: expectedBinding.endSelectedAssetId,
      },
      "PUT",
    ),
  previewSegmentVideoInputs: (projectId: string, revision: number, segmentId: string, inputs: import("./api/types").RecipeInputs) =>
    request(`${structuredDirectorResource(projectId)}/segments/${segmentId}/videos/inputs-preview`, (value) => {
      if (!isVideoRecipeState(value)) throw new Error("视频输入预览响应不合法。");
      return value;
    }, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision, ...inputs }) }),
  saveSegmentVideoInputs: (
    projectId: string,
    revision: number,
    segmentId: string,
    promptText: string,
    inputs: import("./api/types").RecipeInputs,
  ) => structuredMutation(projectId, `segments/${segmentId}/videos/inputs`, {
    expected_revision: revision, prompt_text: promptText, ...inputs,
  }, "PUT"),
  saveSegmentVideoRecipe: (projectId: string, revision: number, segmentId: string, recipeId: string) =>
    structuredMutation(projectId, `segments/${segmentId}/videos/recipe`, { expected_revision: revision, recipe_id: recipeId }, "PUT"),
  generateSegmentVideo: (
    projectId: string,
    revision: number,
    segmentId: string,
    seed?: string,
  ) =>
    structuredMutation(projectId, `segments/${segmentId}/videos/generate`, {
      expected_revision: revision,
      ...(seed === undefined ? {} : { seed }),
    }),
  attachSegmentVideoCandidate: (
    projectId: string,
    revision: number,
    segmentId: string,
    assetId: string,
  ) =>
    structuredMutation(
      projectId,
      `segments/${segmentId}/videos/attach-candidate`,
      {
        expected_revision: revision,
        asset_id: assetId,
      },
    ),
  selectSegmentVideo: (
    projectId: string,
    revision: number,
    segmentId: string,
    assetId: string,
  ) =>
    structuredMutation(projectId, `segments/${segmentId}/videos/select`, {
      expected_revision: revision,
      asset_id: assetId,
    }),
  clearSegmentVideoSelection: (
    projectId: string,
    revision: number,
    segmentId: string,
  ) =>
    structuredMutation(
      projectId,
      `segments/${segmentId}/videos/clear-selection`,
      {
        expected_revision: revision,
      },
    ),
  upscaleSegmentVideo: (
    projectId: string,
    revision: number,
    segmentId: string,
  ) =>
    structuredMutation(projectId, `segments/${segmentId}/videos/upscale`, {
      expected_revision: revision,
    }),
  enterFinalStage: (projectId: string, revision: number) =>
    structuredMutation(projectId, "final/enter", {
      expected_revision: revision,
    }),
  generateFinalVideo: (projectId: string, revision: number) =>
    structuredMutation(projectId, "final/generate", {
      expected_revision: revision,
    }),
  selectFinalVideo: (
    projectId: string,
    revision: number,
    generationId: string,
  ) =>
    structuredMutation(projectId, "final/select", {
      expected_revision: revision,
      generation_id: generationId,
    }),
  clearFinalSelection: (projectId: string, revision: number) =>
    structuredMutation(projectId, "final/clear-selection", {
      expected_revision: revision,
    }),
  approveFinalVideo: (
    projectId: string,
    revision: number,
    zhAssetId: string,
    enAssetId: string,
  ) =>
    structuredMutation(projectId, "final/approve", {
      expected_revision: revision,
      zh_asset_id: zhAssetId,
      en_asset_id: enAssetId,
    }),
  reopenVideoProduction: (projectId: string, revision: number) =>
    structuredMutation(projectId, "final/reopen-videos", {
      expected_revision: revision,
    }),
  addCharacter: (
    projectId: string,
    revision: number,
    card: Omit<CharacterCard, "id">,
  ) =>
    mutateCard(projectId, "characters", null, "POST", revision, {
      name: card.name,
      visual_description: card.visual_description,
      voice_description: card.voice_description,
    }),
  updateCharacter: (projectId: string, revision: number, card: CharacterCardDraft) =>
    mutateCard(projectId, "characters", card.id, "PUT", revision, {
      ...withoutId(card),
      looks: card.looks.map(({ id, name, appearance, usage }) => ({ id, name, appearance, usage })),
    }),
  updateNarrator: (
    projectId: string,
    revision: number,
    narrator: NarratorProfile,
  ) =>
    structuredMutation(
      projectId,
      "narrator",
      {
        expected_revision: revision,
        ...narrator,
      },
      "PUT",
    ),
  discardCard: (
    projectId: string,
    revision: number,
    kind: "characters",
    cardId: string,
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/${kind}/${cardId}`,
      parseStructuredDirectorSnapshot,
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision }),
      },
    ),
  importImageAsset: (
    projectId: string,
    revision: number,
    file: File,
    category: ImageAssetCategory,
  ) =>
    binaryAssetUpload(projectId, "assets/images", file, {
      expected_revision: String(revision),
      category,
    }),
  importImageAssets: async (
    projectId: string,
    revision: number,
    files: File[],
    category: ImageAssetCategory,
  ) => {
    if (files.length === 0) throw new Error("请选择至少一个图片文件。");
    let updated = await binaryAssetUpload(projectId, "assets/images", files[0], {
      expected_revision: String(revision),
      category,
    });
    for (const file of files.slice(1)) {
      updated = await binaryAssetUpload(projectId, "assets/images", file, {
        expected_revision: String(updated.revision),
        category,
      });
    }
    return updated;
  },
  importMediaAsset: (
    projectId: string,
    revision: number,
    file: File,
  ) =>
    binaryAssetUpload(
      projectId,
      "assets/media",
      file,
      { expected_revision: String(revision) },
      canonicalImportedMediaType(file),
    ),
  importMediaAssets: async (
    projectId: string,
    revision: number,
    files: File[],
  ) => {
    if (files.length === 0) throw new Error("请选择至少一个媒体文件。");
    let updated = await binaryAssetUpload(
      projectId,
      "assets/media",
      files[0],
      { expected_revision: String(revision) },
      canonicalImportedMediaType(files[0]),
    );
    for (const file of files.slice(1)) {
      updated = await binaryAssetUpload(
        projectId,
        "assets/media",
        file,
        { expected_revision: String(updated.revision) },
        canonicalImportedMediaType(file),
      );
    }
    return updated;
  },
  deleteAsset: (projectId: string, revision: number, assetId: string) =>
    request(
      `${structuredDirectorResource(projectId)}/assets/${assetId}`,
      parseStructuredDirectorSnapshot,
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision }),
      },
    ),
  deleteAssets: (projectId: string, revision: number, assetIds: string[]) =>
    request(
      `${structuredDirectorResource(projectId)}/assets/batch-delete`,
      parseStructuredDirectorSnapshot,
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision, asset_ids: assetIds }),
      },
    ),
  generateAudio: (
    projectId: string,
    revision: number,
    settings: AudioGenerationSettings,
  ) =>
    structuredMutation(projectId, "audio-generations", {
      expected_revision: revision,
      ...settings,
    }),
  transcribeAudio: (projectId: string, assetId: string) =>
    request(
      `${structuredDirectorResource(projectId)}/assets/${assetId}/transcription`,
      parseAudioTranscription,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: "auto" }),
      },
    ),
  trimAudio: (
    projectId: string,
    revision: number,
    assetId: string,
    settings: AudioTrimSettings,
  ) =>
    structuredMutation(projectId, `assets/${assetId}/audio-trim`, {
      expected_revision: revision,
      ...settings,
    }),
  applyAudioEffect: (
    projectId: string,
    revision: number,
    assetId: string,
    settings: AudioEffectSettings,
  ) =>
    structuredMutation(projectId, `assets/${assetId}/audio-effect`, {
      expected_revision: revision,
      ...settings,
    }),
  separateVideoAudio: (projectId: string, revision: number, assetId: string) =>
    structuredMutation(projectId, `assets/${assetId}/audio-separation`, {
      expected_revision: revision,
    }),
  extractVideoFrame: (projectId: string, revision: number, assetId: string, frameIndex: number) =>
    structuredMutation(projectId, `assets/${assetId}/video-frame`, {
      expected_revision: revision,
      frame_index: frameIndex,
    }),
  extractKeyframeVideoFrame: (
    projectId: string,
    revision: number,
    keyframeId: string,
    sourceVideoAssetId: string,
    frameIndex: number,
  ) =>
    structuredMutation(projectId, `keyframes/${keyframeId}/extract-frame`, {
      expected_revision: revision,
      source_video_asset_id: sourceVideoAssetId,
      frame_index: frameIndex,
    }),
  getVideoFrameInfo: (projectId: string, assetId: string) =>
    request(
      `${structuredDirectorResource(projectId)}/assets/${assetId}/video-frame-info`,
      parseVideoFrameInfo,
    ),
  saveSegmentKeyframeBoundary: (projectId: string, revision: number, segmentId: string, shared: boolean) =>
    structuredMutation(
      projectId,
      `segments/${segmentId}/keyframe-boundary`,
      { expected_revision: revision, shared },
      "PUT",
    ),
  remixVideoAudio: (
    projectId: string,
    revision: number,
    assetId: string,
    voiceAssetId: string,
    backgroundAssetId: string,
    voiceGain: AudioGainSettings,
    backgroundGain: AudioGainSettings,
  ) => structuredMutation(projectId, `assets/${assetId}/audio-remix`, {
    expected_revision: revision,
    voice_asset_id: voiceAssetId,
    background_asset_id: backgroundAssetId,
    voice_gain_db: voiceGain.gain_db,
    background_gain_db: backgroundGain.gain_db,
    voice_gain_start_seconds: voiceGain.start_seconds,
    voice_gain_end_seconds: voiceGain.end_seconds,
    background_gain_start_seconds: backgroundGain.start_seconds,
    background_gain_end_seconds: backgroundGain.end_seconds,
  }),
  uploadReferenceVoice: (
    projectId: string,
    revision: number,
    cardId: string,
    file: File,
  ) =>
    binaryAssetUpload(
      projectId,
      `characters/${cardId}/voice-reference/upload`,
      file,
      { expected_revision: String(revision) },
      "audio/wav",
    ),
  uploadNarratorVoice: (
    projectId: string,
    revision: number,
    narratorId: string,
    language: NarrationLanguage,
    file: File,
  ) =>
    binaryAssetUpload(
      projectId,
      "narrator/voice-reference/upload",
      file,
      { expected_revision: String(revision), narrator_id: narratorId, language },
      "audio/wav",
    ),
  generateLookSheet: (
    projectId: string,
    revision: number,
    cardId: string,
    lookId: string,
    identityAssetIds: string[],
    promptText: string | null,
  ) =>
    structuredMutation(projectId, `characters/${cardId}/looks/${lookId}/sheet-generations`, {
      expected_revision: revision,
      identity_asset_ids: identityAssetIds,
      prompt_text: promptText,
    }),
  previewLookSheet: (
    projectId: string,
    cardId: string,
    lookId: string,
    identityAssetIds: string[],
  ) =>
    request(
      `${structuredDirectorResource(projectId)}/characters/${cardId}/looks/${lookId}/sheet-preview`,
      parseLookSheetPreview,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity_asset_ids: identityAssetIds }),
      },
    ),
  selectLookAsset: (
    projectId: string,
    revision: number,
    cardId: string,
    lookId: string,
    assetId: string,
  ) =>
    structuredMutation(projectId, `characters/${cardId}/looks/${lookId}/select-asset`, {
      expected_revision: revision,
      asset_id: assetId,
    }),
  selectLookSheet: (
    projectId: string,
    revision: number,
    cardId: string,
    lookId: string,
    generationId: string,
  ) =>
    structuredMutation(projectId, `characters/${cardId}/looks/${lookId}/select-sheet`, {
      expected_revision: revision,
      generation_id: generationId,
    }),
  designVoice: (
    projectId: string,
    revision: number,
    cardId: string,
    voiceDescription: string,
    sampleText: string,
    seed: number,
  ) =>
    structuredMutation(projectId, `characters/${cardId}/voice-generations`, {
      expected_revision: revision,
      voice_description: voiceDescription,
      sample_text: sampleText,
      seed,
    }),
  designNarratorVoice: (
    projectId: string,
    revision: number,
    narratorId: string,
    language: NarrationLanguage,
    voiceDescription: string,
    sampleText: string,
    seed: number,
  ) =>
    structuredMutation(projectId, "narrator/voice-generations", {
      expected_revision: revision,
      narrator_id: narratorId,
      language,
      voice_description: voiceDescription,
      sample_text: sampleText,
      seed,
    }),
  attachNarratorVoice: (
    projectId: string,
    revision: number,
    narratorId: string,
    generationId: string,
  ) =>
    structuredMutation(projectId, "narrator/voice-reference/attach", {
      expected_revision: revision,
      narrator_id: narratorId,
      generation_id: generationId,
    }),
  refreshGeneration: (projectId: string, generationId: string) =>
    structuredMutation(projectId, `generations/${generationId}/refresh`, {}),
  refreshActiveGenerations: (projectId: string) =>
    structuredMutation(projectId, "generations/refresh", {}),
  cancelGeneration: (
    projectId: string,
    revision: number,
    generationId: string,
  ) =>
    structuredMutation(projectId, `generations/${generationId}/cancel`, {
      expected_revision: revision,
    }),
  retryGeneration: (
    projectId: string,
    revision: number,
    generationId: string,
  ) =>
    structuredMutation(projectId, `generations/${generationId}/retry`, {
      expected_revision: revision,
    }),
  waitGeneration: (projectId: string, revision: number, generationId: string) =>
    structuredMutation(projectId, `generations/${generationId}/wait`, {
      expected_revision: revision,
    }),
  dismissGeneration: (
    projectId: string,
    revision: number,
    generationId: string,
  ) =>
    structuredMutation(projectId, `generations/${generationId}/dismiss`, {
      expected_revision: revision,
    }),
  attachVoice: (
    projectId: string,
    revision: number,
    cardId: string,
    generationId: string,
  ) =>
    structuredMutation(projectId, `characters/${cardId}/voice-reference/attach`, {
      expected_revision: revision,
      generation_id: generationId,
    }),
};
function parseLookSheetPreview(value: unknown): string {
  if (
    typeof value !== "object" || value === null || Array.isArray(value) ||
    Object.keys(value).join() !== "prompt_text" ||
    typeof (value as { prompt_text: unknown }).prompt_text !== "string"
  ) {
    throw new Error("设定图提示词预览格式不合法。");
  }
  return (value as { prompt_text: string }).prompt_text;
}
function structuredDirectorResource(projectId: string): string {
  if (!/^[0-9a-f]{32}$/.test(projectId)) {
    throw new Error("项目 ID 不合法。");
  }
  return `/api/projects/${projectId}/structured-director`;
}
function mutateCard(
  projectId: string,
  kind: "characters",
  cardId: string | null,
  method: "POST" | "PUT",
  revision: number,
  card: object,
): Promise<StructuredDirectorSnapshot> {
  const suffix = cardId === null ? kind : `${kind}/${cardId}`;
  return request(
    `${structuredDirectorResource(projectId)}/${suffix}`,
    parseStructuredDirectorSnapshot,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: revision, ...card }),
    },
  );
}
function structuredMutation(
  projectId: string,
  suffix: string,
  body: Record<string, unknown>,
  method: "POST" | "PUT" = "POST",
): Promise<StructuredDirectorSnapshot> {
  return request(
    `${structuredDirectorResource(projectId)}/${suffix}`,
    parseStructuredDirectorSnapshot,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}
// Core 在 revision 过期时仍返回 revision_conflict，即使视觉层已经解锁。
// 冲突后重读：层已解锁则采用最新快照，否则用新 revision 再提交一次。
async function unlockVisualProductionWithRevisionRetry(
  projectId: string,
  revision: number,
): Promise<StructuredDirectorSnapshot> {
  try {
    return await structuredMutation(projectId, "visual-production/unlock", {
      expected_revision: revision,
    });
  } catch (caught) {
    if (
      !(caught instanceof StoryRailApiError) ||
      caught.code !== "revision_conflict"
    ) {
      throw caught;
    }
    const latest = await request(
      structuredDirectorResource(projectId),
      parseStructuredDirectorSnapshot,
    );
    if (
      latest.workspace_layers.keyframes_unlocked &&
      latest.workspace_layers.videos_unlocked
    ) {
      return latest;
    }
    if (!latest.allowed_actions.includes("unlock_visual_production")) {
      throw caught;
    }
    return structuredMutation(projectId, "visual-production/unlock", {
      expected_revision: latest.revision,
    });
  }
}
function binaryAssetUpload(
  projectId: string,
  suffix: string,
  file: File,
  query: Record<string, string>,
  mediaType = file.type,
): Promise<StructuredDirectorSnapshot> {
  const parameters = new URLSearchParams({ ...query, filename: file.name });
  return request(
    `${structuredDirectorResource(projectId)}/${suffix}?${parameters.toString()}`,
    parseStructuredDirectorSnapshot,
    {
      method: "POST",
      headers: { "Content-Type": mediaType },
      body: file,
    },
  );
}
export function canonicalImportedMediaType(file: File): string {
  const name = file.name.toLowerCase();
  if (
    file.type === "audio/wav" ||
    file.type === "audio/x-wav" ||
    name.endsWith(".wav")
  ) {
    return "audio/wav";
  }
  if (file.type === "video/mp4" || name.endsWith(".mp4")) return "video/mp4";
  return file.type;
}
function withoutId<
  T extends {
    id: string;
  },
>(value: T): Omit<T, "id"> {
  const { id: _id, ...rest } = value;
  return rest;
}
function parseVideoFrameInfo(value: unknown): { frame_count: number; duration_seconds: number | null } {
  if (
    !isRecord(value) ||
    typeof value.frame_count !== "number" ||
    !Number.isInteger(value.frame_count) ||
    value.frame_count < 1 ||
    !(value.duration_seconds === null || typeof value.duration_seconds === "number")
  ) {
    throw new Error("视频帧数响应格式不正确。");
  }
  return { frame_count: value.frame_count, duration_seconds: value.duration_seconds };
}
export async function request<T>(
  url: string,
  parse: (value: unknown) => T,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, init);
  const value: unknown = await response.json();
  if (!response.ok) {
    throw new StoryRailApiError(parseError(value));
  }
  return parse(value);
}
