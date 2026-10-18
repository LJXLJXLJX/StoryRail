import type { LocationChange, LocationImpact } from "../api/location";
import { createContext } from "react";
import type {
  AudioEffectSettings,
  AudioGenerationSettings,
  AudioTrimSettings,
  AudioGainSettings,
  CharacterCard,
  CharacterCardDraft,
  ImageAssetCategory,
  NarrationCue,
  NarrationLanguage,
  NarratorProfile,
  ProjectSummary,
  Scene,
  StructuredDirectorSnapshot,
  KeyframeCharacterReference,
} from "../api";
import type { VideoFrameInfo } from "./shared";
export type CardKind = "characters";
export interface StructuredDirectorWorkspaceProps {
  project: ProjectSummary;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  pending: string | null;
  pendingSegmentVideoId?: string | null;
  error: string | null;
  globalReferencesOpen?: boolean;
  toolbarTarget?: HTMLElement | null;
  actions?: WorkspaceActions;
}

export interface WorkspaceActions {
  onPreviewLocationChange?: (change: LocationChange, revision: number) => Promise<LocationImpact>;
  onApplyLocationChange?: (change: LocationChange, revision: number) => Promise<boolean>;
  onPreviewScriptChange?: (
    change: import("../api").ScriptChange,
    revision: number,
  ) => Promise<import("../api").ScriptImpact>;
  onApplyScriptChange?: (
    change: import("../api").ScriptChange,
    revision: number,
  ) => Promise<boolean>;
  onGenerateLocationImage?: (imageId: string) => void;
  onCaptureLocationPanorama?: (
    panoramaImageId: string,
    name: string,
    description: string,
    yawDeg: number,
    pitchDeg: number,
    hfovDeg: number,
  ) => void;
  onCloseGlobalReferences?: () => void;
  onConfirmReferences: () => void;
  onSaveScript: (scenes: Scene[], expectedRevision?: number) => void;
  onConfirmScript: () => void;
  onSaveNarrationCue: (sceneId: string, cue: NarrationCue) => void;
  onGenerateNarration: (sceneId: string, cueId: string, language: NarrationLanguage) => void;
  onGenerateNarrationBatch: () => void;
  onSelectNarrationAudio: (
    sceneId: string,
    cueId: string,
    generationId: string,
  ) => void;
  onClearNarrationAudioSelection: (
    sceneId: string,
    cueId: string,
    language: NarrationLanguage,
  ) => void;
  onGenerateDialogue?: (dialogueLineId: string) => void;
  onGenerateDialogueBatch?: () => void;
  onSelectDialogueAudio?: (dialogueLineId: string, generationId: string) => void;
  onSetDialogueTiming?: (
    segmentId: string,
    starts: Record<string, number>,
    durationSeconds: number,
  ) => void;
  onGenerateSceneAnimatic?: (sceneId: string) => void;
  onGenerateSceneFinal?: (
    sceneId: string,
    videoAudioVolume?: number,
    narrationAudioVolume?: number,
  ) => void;
  onUnlockVisualProduction: () => void;
  onSaveKeyframe: (
    keyframeId: string,
    segmentId: string,
    promptText: string,
    visibleCharacterIds: string[],
    characterReferences: KeyframeCharacterReference[],
    referenceAssetIds: string[],
  ) => void;
  onGenerateKeyframe: (keyframeId: string) => void;
  onSelectKeyframe: (keyframeId: string, assetId: string) => void;
  onSaveSegmentKeyframeReferences: (
    segmentId: string,
    assetIds: string[],
  ) => void;
  onSaveSegmentKeyframeActivation: (
    segmentId: string,
    startEnabled: boolean,
    endEnabled: boolean,
  ) => void;
  onPreviewSegmentVideoInputs?: (segmentId: string, inputs: import("../api").RecipeInputs) => Promise<import("../api").VideoRecipeState>;
  onSaveSegmentVideoInputs?: (
    segmentId: string,
    promptText: string,
    inputs: import("../api").RecipeInputs,
  ) => void;
  onSaveSegmentVideoRecipe?: (segmentId: string, recipeId: string) => void;
  onSaveSegmentKeyframeBoundary?: (segmentId: string, shared: boolean) => void;
  onExtractKeyframeVideoFrame?: (keyframeId: string, sourceVideoAssetId: string, frameIndex: number) => void;
  onLoadVideoFrameInfo?: (assetId: string) => Promise<VideoFrameInfo>;
  onGenerateSegmentVideo?: (segmentId: string, seed?: string) => void;
  onAttachSegmentVideoCandidate?: (segmentId: string, assetId: string) => void;
  onSelectSegmentVideo?: (segmentId: string, assetId: string) => void;
  onClearSegmentVideoSelection?: (segmentId: string) => void;
  onUpscaleSegmentVideo?: (segmentId: string) => void;
  onGenerateFinalVideo?: () => void;
  onSelectFinalVideo?: (generationId: string) => void;
  onClearFinalSelection?: () => void;
  onApproveFinalVideo?: () => void;
  onReopenVideoProduction?: () => void;
  onAddCharacter: (card: Omit<CharacterCard, "id">) => void;
  onUpdateCharacter: (card: CharacterCardDraft) => void;
  onUpdateNarrator: (profile: NarratorProfile) => void;
  onDiscard: (kind: CardKind, cardId: string) => void;
  onImportImage: (file: File, category: ImageAssetCategory) => void;
  onImportMedia: (file: File) => void;
  onDeleteAsset: (assetId: string) => void;
  onDeleteAssets: (assetIds: string[]) => void;
  onGenerateAudio: (settings: AudioGenerationSettings) => Promise<boolean>;
  onTranscribeAudio: (assetId: string) => Promise<string>;
  onTrimAudio: (assetId: string, settings: AudioTrimSettings) => Promise<boolean>;
  onApplyAudioEffect: (assetId: string, settings: AudioEffectSettings) => void;
  onSeparateVideoAudio: (assetId: string) => void;
  onExtractVideoFrame?: (assetId: string, frameIndex: number) => void;
  onRemixVideoAudio: (
    assetId: string,
    voiceAssetId: string,
    backgroundAssetId: string,
    voiceGain: AudioGainSettings,
    backgroundGain: AudioGainSettings,
  ) => Promise<boolean>;
  // Playground → 项目复制完成后，请求外层重新读取项目快照。
  onRefreshProjectSnapshot?: () => void;
  onUploadVoice: (cardId: string, file: File) => void;
  onUploadNarratorVoice: (narratorId: string, language: NarrationLanguage, file: File) => void;
  // promptText 为 null 时由 Core 编译版式提示词；非 null 是人类编辑过的完整提示词，原样提交。
  onGenerateLookSheet: (
    cardId: string,
    lookId: string,
    identityAssetIds: string[],
    promptText: string | null,
  ) => void;
  onPreviewLookSheet: (
    cardId: string,
    lookId: string,
    identityAssetIds: string[],
  ) => Promise<string>;
  onSelectLookSheet: (cardId: string, lookId: string, generationId: string) => void;
  onSelectLookAsset: (cardId: string, lookId: string, assetId: string) => void;
  onDesignVoice: (
    cardId: string,
    voiceDescription: string,
    sampleText: string,
    seed: number,
  ) => void;
  onDesignNarratorVoice: (
    narratorId: string,
    language: NarrationLanguage,
    voiceDescription: string,
    sampleText: string,
    seed: number,
  ) => void;
  onAttachNarratorVoice: (narratorId: string, generationId: string) => void;
  onAttachVoice: (cardId: string, generationId: string) => void;
  onCancelGeneration: (generationId: string) => void;
  onDismissGeneration: (generationId: string) => void;
}

export type WorkspaceFlatProps = Omit<StructuredDirectorWorkspaceProps, "actions"> & WorkspaceActions;
export const WorkspaceActionsContext = createContext<WorkspaceActions | null>(null);

export type ImportImageHandler = (
  file: File,
  category: ImageAssetCategory,
) => void;
