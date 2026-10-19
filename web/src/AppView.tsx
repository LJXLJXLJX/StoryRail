import { type FormEvent, lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  projectApi,
  structuredDirectorApi,
  type AudioEffectSettings,
  type AudioGenerationSettings,
  type AudioTrimSettings,
  type AudioGainSettings,
  type NarrationCue,
  type NarrationLanguage,
  type ProjectAspectRatio,
  type ProjectSummary,
  type ReferenceGeneration,
  type Scene,
  type StructuredDirectorSnapshot,
  type KeyframeCharacterReference,
} from "./api";
import { ProviderSettingsControl } from "./provider_settings/ProviderSettingsControl";
const StructuredDirectorWorkspace = lazy(() => import("./StructuredDirectorWorkspace").then((module) => ({ default: module.StructuredDirectorWorkspace })));
const PlaygroundPage = lazy(() => import("./playground/PlaygroundPage").then((module) => ({ default: module.PlaygroundPage })));
const CreativePartnerPrompt = lazy(() => import("./CreativePartnerPrompt").then((module) => ({ default: module.CreativePartnerPrompt })));
const ExternalAgentEntry = lazy(() => import("./ExternalAgentConnect").then((module) => ({ default: module.ExternalAgentEntry })));
import { ConsistencyNotice } from "./director_workspace/ConsistencyNotice";
import { captureContentSave, savedContentChanges, mergeContentChanges, type ContentChange, type ContentSave } from "./director_workspace/consistency";
import { useSnapshotScheduler } from "./director_workspace/useSnapshotScheduler";
type PendingAction =
  | "edit_director_plan"
  | "edit_location"
  | "generate_location_image"
  | "capture_location_panorama"
  | "list"
  | "create"
  | "open"
  | "edit_script"
  | "confirm_reference_review"
  | "confirm_script"
  | "edit_narration"
  | "generate_narration"
  | "generate_narration_batch"
  | "select_narration"
  | "clear_narration_selection"
  | "generate_dialogue"
  | "edit_dialogue_audio"
  | "generate_dialogue_batch"
  | "select_dialogue"
  | "set_dialogue_timing"
  | "unlock_visual_production"
  | "generate_keyframes"
  | "select_keyframe"
  | "generate_scene_animatic"
  | "generate_scene_final"
  | "edit_keyframe_references"
  | "edit_segment_video_plan"
  | "extract_video_frame"
  | "generate_segment_video"
  | "attach_segment_video_candidate"
  | "select_segment_video"
  | "upscale_segment_video"
  | "generate_final_video"
  | "select_final_video"
  | "clear_final_selection"
  | "approve_final_video"
  | "reopen_video_production"
  | "edit_reference_card"
  | "delete_asset"
  | "delete_assets"
  | "generate_audio"
  | "trim_audio"
  | "apply_audio_effect"
  | "separate_video_audio"
  | "remix_video_audio"
  | "delete"
  | null;
export function App() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [selectedProject, setSelectedProject] = useState<ProjectSummary | null>(
    null,
  );
  const [structuredSnapshot, setStructuredSnapshot] =
    useState<StructuredDirectorSnapshot | null>(null);
  const [pending, setPending] = useState<PendingAction>("list");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [contentChanges, setContentChanges] = useState<ContentChange[]>([]);
  const saveSequence = useRef(0);
  const dialogueLocators = useRef(new Set<string>());
  useEffect(() => { setContentChanges([]); setNotice(null); dialogueLocators.current.clear(); }, [selectedProject?.id]);
  const [projectTitle, setProjectTitle] = useState("");
  const [directorPlan, setDirectorPlan] = useState("");
  const [aspectRatio, setAspectRatio] = useState<ProjectAspectRatio>("16:9");
  const [narrationLanguages, setNarrationLanguages] = useState<NarrationLanguage[]>([]);
  const [deleteConfirmation, setDeleteConfirmation] = useState<string | null>(
    null,
  );
  const [globalReferencesOpen, setGlobalReferencesOpen] = useState(false);
  const [playgroundOpen, setPlaygroundOpen] = useState(playgroundFromLocation);
  const [workspaceToolbar, setWorkspaceToolbar] =
    useState<HTMLDivElement | null>(null);
  const [pendingSegmentVideoId, setPendingSegmentVideoId] = useState<
    string | null
  >(null);
  const activeStructuredProjectId = useRef<string | null>(null);
  activeStructuredProjectId.current = selectedProject?.id ?? null;
  const applyScheduledSnapshot = useCallback(
    (updated: StructuredDirectorSnapshot) => {
      // 采样进度是 Core 的 UI-only 观察：revision 不变也会前进，
      // 因此只拒绝严格更旧的快照（与 mutation 返回路径同一规则）。
      setStructuredSnapshot(current =>
        current !== null && current.revision > updated.revision ? current : updated,
      );
    },
    [],
  );
  const handleSchedulerError = useCallback((caught: unknown) => {
    setError(errorMessage(caught));
  }, []);
  useSnapshotScheduler({
    projectId: selectedProject?.id ?? null,
    snapshot: structuredSnapshot,
    onSnapshot: applyScheduledSnapshot,
    onError: handleSchedulerError,
  });
  useEffect(() => {
    void loadProjects();
  }, []);
  useEffect(() => {
    const onPopState = () => {
      if (playgroundFromLocation()) {
        setSelectedProject(null);
        setStructuredSnapshot(null);
        setGlobalReferencesOpen(false);
        setPlaygroundOpen(true);
        return;
      }
      setPlaygroundOpen(false);
      const requested = projectIdFromLocation();
      if (requested === null) {
        setSelectedProject(null);
        setStructuredSnapshot(null);
        setGlobalReferencesOpen(false);
        return;
      }
      const project = projects?.find((item) => item.id === requested);
      if (project !== undefined) void openProject(project, false);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [projects]);
  async function loadProjects() {
    setPending("list");
    try {
      const bootstrap = await projectApi.bootstrap();
      const loadedProjects = bootstrap.projects;
      setProjects(loadedProjects);
      setError(null);
      const requestedProjectId = playgroundFromLocation()
        ? null
        : projectIdFromLocation();
      if (requestedProjectId !== null) {
        const requestedProject = loadedProjects.find(
          (project) => project.id === requestedProjectId,
        );
        if (requestedProject === undefined) {
          replaceProjectLocation(null);
        } else {
          await openProject(requestedProject, false);
        }
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(null);
    }
  }
  async function openProject(project: ProjectSummary, updateHistory = true) {
    setPending("open");
    setError(null);
    try {
      setStructuredSnapshot(await structuredDirectorApi.get(project.id));
      setSelectedProject(project);
      if (updateHistory) pushProjectLocation(project.id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(null);
    }
  }
  // Playground 复制到项目后重新读取快照；revision 只会前进。
  async function reloadStructuredSnapshot() {
    if (selectedProject === null) return;
    try {
      applyScheduledSnapshot(await structuredDirectorApi.get(selectedProject.id));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }
  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = projectTitle.trim();
    const plan = directorPlan.trim();
    if (title.length === 0 || plan.length === 0 || narrationLanguages.length === 0) return;
    setPending("create");
    setError(null);
    try {
      const detail = await projectApi.create(title, aspectRatio, plan, narrationLanguages);
      setProjects((current) => [detail.project, ...(current ?? [])]);
      setSelectedProject(detail.project);
      setStructuredSnapshot(detail.structured_director);
      pushProjectLocation(detail.project.id);
      setProjectTitle("");
      setDirectorPlan("");
      setAspectRatio("16:9");
      setNarrationLanguages([]);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(null);
    }
  }
  async function deleteProject(projectId: string) {
    setPending("delete");
    setError(null);
    try {
      await projectApi.delete(projectId);
      setProjects(
        (current) =>
          current?.filter((project) => project.id !== projectId) ?? [],
      );
      setDeleteConfirmation(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(null);
    }
  }
  async function saveScript(scenes: Scene[], expectedRevision?: number) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.saveScript(
          selectedProject.id,
          expectedRevision ?? structuredSnapshot.revision,
          scenes,
        ),
      "edit_script",
      { kind: "script", scenes },
    );
  }
  async function confirmScript() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.confirmScript(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "confirm_script",
    );
  }
  async function confirmReferences() {
    if (selectedProject === null || structuredSnapshot === null) return;
    const projectId = selectedProject.id;
    const revision = structuredSnapshot.revision;
    const confirmed = await mutateStructuredDirector(
      async () => {
        await structuredDirectorApi.confirmReferences(projectId, revision);
        return structuredDirectorApi.get(projectId);
      },
      "confirm_reference_review",
    );
    if (confirmed) setGlobalReferencesOpen(false);
  }
  async function saveNarrationCue(sceneId: string, cue: NarrationCue) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.saveNarrationCue(
          selectedProject.id,
          structuredSnapshot.revision,
          sceneId,
          cue,
        ),
      "edit_narration",
      { kind: "cue", id: cue.id },
    );
  }
  async function generateNarration(
    sceneId: string,
    cueId: string,
    language: NarrationLanguage,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateNarration(
          selectedProject.id,
          structuredSnapshot.revision,
          sceneId,
          cueId,
          language,
        ),
      "generate_narration",
    );
  }
  async function generateNarrationBatch() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateNarrationBatch(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "generate_narration_batch",
    );
  }
  async function selectNarration(
    sceneId: string,
    cueId: string,
    generationId: string,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.selectNarrationAudio(
          selectedProject.id,
          structuredSnapshot.revision,
          sceneId,
          cueId,
          generationId,
        ),
      "select_narration",
    );
  }
  async function clearNarrationSelection(
    sceneId: string,
    cueId: string,
    language: NarrationLanguage,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.clearNarrationAudioSelection(
          selectedProject.id,
          structuredSnapshot.revision,
          sceneId,
          cueId,
          language,
        ),
      "clear_narration_selection",
    );
  }
  async function generateDialogue(dialogueLineId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateDialogue(
          selectedProject.id,
          structuredSnapshot.revision,
          dialogueLineId,
        ),
      "generate_dialogue",
    );
  }
  async function saveDialogueRecipeParams(
    dialogueLineId: string,
    recipeParams: Record<string, unknown>,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.saveDialogueRecipeParams(
          selectedProject.id,
          structuredSnapshot.revision,
          dialogueLineId,
          recipeParams,
        ),
      "edit_dialogue_audio",
    );
  }
  async function generateDialogueBatch() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateDialogueBatch(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "generate_dialogue_batch",
    );
  }
  async function selectDialogue(dialogueLineId: string, generationId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.selectDialogueAudio(
          selectedProject.id,
          structuredSnapshot.revision,
          dialogueLineId,
          generationId,
        ),
      "select_dialogue",
    );
  }
  async function setDialogueTiming(
    segmentId: string,
    starts: Record<string, number>,
    durationSeconds: number,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.setDialogueTiming(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
          starts,
          durationSeconds,
        ),
      "set_dialogue_timing",
    );
  }
  async function unlockVisualProduction() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.unlockVisualProduction(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "unlock_visual_production",
    );
  }
  async function saveKeyframe(
    keyframeId: string,
    segmentId: string,
    promptText: string,
    visibleCharacterIds: string[],
    characterReferences: KeyframeCharacterReference[],
    referenceAssetIds: string[],
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.saveKeyframe(
          selectedProject.id,
          structuredSnapshot.revision,
          keyframeId,
          segmentId,
          promptText,
          visibleCharacterIds,
          characterReferences,
          referenceAssetIds,
        ),
      "edit_keyframe_references",
      { kind: "keyframe", id: keyframeId },
    );
  }
  async function generateKeyframe(keyframeId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateKeyframe(
          selectedProject.id,
          structuredSnapshot.revision,
          keyframeId,
        ),
      "generate_keyframes",
    );
  }
  async function selectKeyframe(keyframeId: string, assetId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.selectKeyframe(
          selectedProject.id,
          structuredSnapshot.revision,
          keyframeId,
          assetId,
        ),
      "select_keyframe",
    );
  }
  async function saveSegmentKeyframeReferences(
    segmentId: string,
    assetIds: string[],
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.saveSegmentKeyframeReferences(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
          assetIds,
        ),
      "edit_keyframe_references",
    );
  }
  async function saveSegmentKeyframeActivation(
    segmentId: string,
    startEnabled: boolean,
    endEnabled: boolean,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    const plan = structuredSnapshot.keyframe_plan;
    const binding = plan?.segments.find(
      (item) => item.segment_id === segmentId,
    );
    const start = plan?.keyframes.find(
      (item) => item.id === binding?.start_keyframe_id,
    );
    const end = plan?.keyframes.find(
      (item) => item.id === binding?.end_keyframe_id,
    );
    if (binding === undefined || start === undefined || end === undefined) {
      setError("当前 Segment 的关键帧绑定已更新，请刷新后重试。");
      return;
    }
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.saveSegmentKeyframeActivation(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
          startEnabled,
          endEnabled,
          {
            startKeyframeId: binding.start_keyframe_id,
            endKeyframeId: binding.end_keyframe_id,
            startEnabled: binding.start_enabled,
            endEnabled: binding.end_enabled,
            startSelectedAssetId: start.selected_asset_id,
            endSelectedAssetId: end.selected_asset_id,
          },
        ),
      "edit_keyframe_references",
    );
  }
  async function generateSegmentVideo(segmentId: string, seed?: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    setPendingSegmentVideoId(segmentId);
    try {
      await mutateStructuredDirector(
        () =>
          structuredDirectorApi.generateSegmentVideo(
            selectedProject.id,
            structuredSnapshot.revision,
            segmentId,
            seed,
          ),
        "generate_segment_video",
      );
    } finally {
      setPendingSegmentVideoId(null);
    }
  }
  async function generateSceneAnimatic(sceneId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateSceneAnimatic(
          selectedProject.id,
          structuredSnapshot.revision,
          sceneId,
        ),
      "generate_scene_animatic",
    );
  }
  async function generateSceneFinal(
    sceneId: string,
    videoAudioVolume = 1,
    narrationAudioVolume = 1,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateSceneFinal(
          selectedProject.id,
          structuredSnapshot.revision,
          sceneId,
          videoAudioVolume,
          narrationAudioVolume,
        ),
      "generate_scene_final",
    );
  }
  async function saveSegmentVideoInputs(
    segmentId: string,
    promptText: string,
    inputs: import("./api").RecipeInputs,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(() => structuredDirectorApi.saveSegmentVideoInputs(selectedProject.id, structuredSnapshot.revision, segmentId, promptText, inputs), "edit_segment_video_plan", { kind: "video_prompt", id: segmentId });
  }
  async function saveSegmentVideoRecipe(segmentId: string, recipeId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(() => structuredDirectorApi.saveSegmentVideoRecipe(selectedProject.id, structuredSnapshot.revision, segmentId, recipeId), "edit_segment_video_plan");
  }
  async function saveSegmentKeyframeBoundary(segmentId: string, shared: boolean) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () => structuredDirectorApi.saveSegmentKeyframeBoundary(selectedProject.id, structuredSnapshot.revision, segmentId, shared),
      "edit_keyframe_references",
    );
  }
  async function extractKeyframeVideoFrame(keyframeId: string, sourceVideoAssetId: string, frameIndex: number) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () => structuredDirectorApi.extractKeyframeVideoFrame(
        selectedProject.id, structuredSnapshot.revision, keyframeId, sourceVideoAssetId, frameIndex,
      ),
      "extract_video_frame",
    );
  }
  const loadVideoFrameInfo = useCallback(
    (assetId: string) => {
      if (selectedProject === null) return Promise.reject(new Error("项目尚未打开。"));
      return structuredDirectorApi.getVideoFrameInfo(selectedProject.id, assetId);
    },
    [selectedProject],
  );
  async function selectSegmentVideo(segmentId: string, assetId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.selectSegmentVideo(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
          assetId,
        ),
      "select_segment_video",
    );
  }
  async function attachSegmentVideoCandidate(
    segmentId: string,
    assetId: string,
  ) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.attachSegmentVideoCandidate(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
          assetId,
        ),
      "attach_segment_video_candidate",
    );
  }
  async function clearSegmentVideoSelection(segmentId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.clearSegmentVideoSelection(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
        ),
      "edit_segment_video_plan",
    );
  }
  async function upscaleSegmentVideo(segmentId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.upscaleSegmentVideo(
          selectedProject.id,
          structuredSnapshot.revision,
          segmentId,
        ),
      "upscale_segment_video",
    );
  }
  async function generateFinalVideo() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.generateFinalVideo(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "generate_final_video",
    );
  }
  async function selectFinalVideo(generationId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.selectFinalVideo(
          selectedProject.id,
          structuredSnapshot.revision,
          generationId,
        ),
      "select_final_video",
    );
  }
  async function approveFinalVideo() {
    if (selectedProject === null || structuredSnapshot === null) return;
    const plan = structuredSnapshot.final_assembly;
    const zhAssetId = plan?.selected_zh_asset_id;
    const enAssetId = plan?.selected_en_asset_id;
    if (!zhAssetId || !enAssetId) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.approveFinalVideo(
          selectedProject.id,
          structuredSnapshot.revision,
          zhAssetId,
          enAssetId,
        ),
      "approve_final_video",
    );
  }
  async function clearFinalSelection() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.clearFinalSelection(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "clear_final_selection",
    );
  }
  async function reopenVideoProduction() {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.reopenVideoProduction(
          selectedProject.id,
          structuredSnapshot.revision,
        ),
      "reopen_video_production",
    );
  }
  async function deleteAsset(assetId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.deleteAsset(
          selectedProject.id,
          structuredSnapshot.revision,
          assetId,
        ),
      "delete_asset",
    );
  }
  async function deleteAssets(assetIds: string[]) {
    if (selectedProject === null || structuredSnapshot === null || assetIds.length === 0) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.deleteAssets(
          selectedProject.id,
          structuredSnapshot.revision,
          assetIds,
        ),
      "delete_assets",
    );
  }
  async function applyAudioEffect(assetId: string, settings: AudioEffectSettings) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () =>
        structuredDirectorApi.applyAudioEffect(
          selectedProject.id,
          structuredSnapshot.revision,
          assetId,
          settings,
        ),
      "apply_audio_effect",
    );
  }
  async function trimAudio(assetId: string, settings: AudioTrimSettings): Promise<boolean> {
    if (selectedProject === null || structuredSnapshot === null) return false;
    return mutateStructuredDirector(
      () => structuredDirectorApi.trimAudio(
        selectedProject.id,
        structuredSnapshot.revision,
        assetId,
        settings,
      ),
      "trim_audio",
    );
  }
  async function generateAudio(settings: AudioGenerationSettings): Promise<boolean> {
    if (selectedProject === null || structuredSnapshot === null) return false;
    return mutateStructuredDirector(
      () => structuredDirectorApi.generateAudio(
        selectedProject.id,
        structuredSnapshot.revision,
        settings,
      ),
      "generate_audio",
    );
  }
  async function previewLookSheet(
    cardId: string,
    lookId: string,
    identityAssetIds: string[],
  ): Promise<string> {
    if (selectedProject === null) throw new Error("请先选择项目。");
    return structuredDirectorApi.previewLookSheet(selectedProject.id, cardId, lookId, identityAssetIds);
  }
  async function transcribeAudio(assetId: string): Promise<string> {
    if (selectedProject === null) throw new Error("请先选择项目。");
    return structuredDirectorApi.transcribeAudio(selectedProject.id, assetId);
  }
  async function separateVideoAudio(assetId: string) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () => structuredDirectorApi.separateVideoAudio(
        selectedProject.id, structuredSnapshot.revision, assetId,
      ),
      "separate_video_audio",
    );
  }
  async function extractVideoFrame(assetId: string, frameIndex: number) {
    if (selectedProject === null || structuredSnapshot === null) return;
    await mutateStructuredDirector(
      () => structuredDirectorApi.extractVideoFrame(
        selectedProject.id, structuredSnapshot.revision, assetId, frameIndex,
      ),
      "extract_video_frame",
    );
  }
  async function remixVideoAudio(
    assetId: string,
    voiceAssetId: string,
    backgroundAssetId: string,
    voiceGain: AudioGainSettings,
    backgroundGain: AudioGainSettings,
  ): Promise<boolean> {
    if (selectedProject === null || structuredSnapshot === null) return false;
    return mutateStructuredDirector(
      () => structuredDirectorApi.remixVideoAudio(
        selectedProject.id, structuredSnapshot.revision, assetId,
        voiceAssetId, backgroundAssetId, voiceGain, backgroundGain,
      ),
      "remix_video_audio",
    );
  }
  async function mutateStructuredDirector(
    operation: () => Promise<StructuredDirectorSnapshot>,
    action: PendingAction = "edit_reference_card",
    contentSave?: ContentSave,
  ): Promise<boolean> {
    const previousSnapshot = structuredSnapshot;
    const projectId = selectedProject?.id;
    const sequence = ++saveSequence.current;
    const captured = previousSnapshot && contentSave ? captureContentSave(previousSnapshot, contentSave) : [];
    const stillCurrent = () => activeStructuredProjectId.current === projectId && saveSequence.current === sequence;
    setPending(action);
    setError(null);
    try {
      const updated = await operation();
      if (!stillCurrent()) return false;
      if (previousSnapshot && captured.length) {
        const changes = savedContentChanges(captured, previousSnapshot.revision, updated);
        setContentChanges(current => mergeContentChanges(current, changes));
      }
      setStructuredSnapshot(current => current !== null && current.revision > updated.revision ? current : updated);
      if (contentSave?.kind === "script" && previousSnapshot?.workspace_layers.videos_unlocked) {
        const locators = changedDialogueSegmentLocators(
          previousSnapshot.director_script?.scenes ?? [],
          updated.director_script?.scenes ?? [],
        );
        if (locators.length > 0) {
          locators.forEach(locator => dialogueLocators.current.add(locator));
          setNotice(dialoguePromptReminder([...dialogueLocators.current]));
        }
      }
      return true;
    } catch (caught) {
      if (!stillCurrent()) return false;
      setError(errorMessage(caught));
      if (selectedProject !== null) {
        try {
          const refreshed = await structuredDirectorApi.get(selectedProject.id);
          if (stillCurrent()) setStructuredSnapshot(current => current && current.revision > refreshed.revision ? current : refreshed);
        } catch {
          // 保留原错误，避免用过期 revision 继续覆盖。
        }
      }
      return false;
    } finally {
      if (stillCurrent()) setPending(null);
    }
  }
  async function updateDirectorPlan(directorPlanMarkdown: string): Promise<boolean> {
    if (selectedProject === null || structuredSnapshot === null) return false;
    return mutateStructuredDirector(
      () =>
        structuredDirectorApi.updateDirectorPlan(
          selectedProject.id,
          structuredSnapshot.revision,
          directorPlanMarkdown,
        ),
      "edit_director_plan",
    );
  }
  function returnHome() {
    activeStructuredProjectId.current = null;
    ++saveSequence.current;
    setContentChanges([]);
    setGlobalReferencesOpen(false);
    setSelectedProject(null);
    setStructuredSnapshot(null);
    setError(null);
    setNotice(null);
    pushProjectLocation(null);
    void loadProjects();
  }
  function enterPlayground() {
    setSelectedProject(null);
    setStructuredSnapshot(null);
    setGlobalReferencesOpen(false);
    pushPlaygroundLocation();
    setPlaygroundOpen(true);
  }
  function exitPlayground() {
    clearPlaygroundLocation();
    setPlaygroundOpen(false);
  }
  const isBusy = pending !== null;
  if (playgroundOpen) {
    return (
      <Suspense fallback={<div className="app-shell" />}>
        <PlaygroundPage onExit={exitPlayground} />
      </Suspense>
    );
  }
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-and-agent">
          <div className="brand-lockup" aria-label="StoryRail 镜序">
            <div className="brand-mark" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div>
              <div className="brand-name">StoryRail</div>
              <div className="brand-cn">镜序</div>
            </div>
          </div>
          {selectedProject !== null ? <Suspense fallback={null}><ExternalAgentEntry key={selectedProject.id} target={{ kind: "project", projectId: selectedProject.id }} /></Suspense> : null}
        </div>
        {selectedProject === null ? (
          <div className="stage-label">
            <span className="stage-index">00</span>
            <span>项目</span>
          </div>
        ) : (
          <button className="home-link" type="button" onClick={returnHome}>
            <span aria-hidden="true">←</span> 所有项目{" "}
            <span className="stage-separator">/</span> 结构化导演台
          </button>
        )}
        <div className="topbar-actions">
          <ProviderSettingsControl />
          {selectedProject !== null ? (
            <>
              <div className="workspace-toolbar" ref={setWorkspaceToolbar} />
              <button
                className="reference-library-trigger"
                type="button"
                onClick={() => setGlobalReferencesOpen(true)}
              >
                引用库
              </button>
            </>
          ) : null}
          {structuredSnapshot !== null ? (
            <GenerationProgress generations={structuredSnapshot.generations} />
          ) : null}
          <div className="status-chip">
            <span className={isBusy ? "status-dot is-working" : "status-dot"} />
            {isBusy
              ? pending === "delete"
                ? "正在删除"
                : "处理中"
              : selectedProject !== null
                ? "项目状态已保存"
                : `${projects?.length ?? 0} 个项目`}
          </div>
        </div>
      </header>

      {selectedProject !== null &&
      structuredSnapshot !== null &&
      error !== null ? (
        <FloatingErrorNotice message={error} onDismiss={() => setError(null)} />
      ) : null}
      {selectedProject !== null &&
      structuredSnapshot !== null &&
      error === null &&
      notice !== null && contentChanges.length === 0 ? (
        <FloatingActionNotice
          message={notice}
          onDismiss={() => setNotice(null)}
        />
      ) : null}

      {selectedProject && contentChanges.length > 0 ? <ConsistencyNotice
        key={selectedProject.id} project={selectedProject} changes={contentChanges} reminder={notice}
        onDismiss={() => { setContentChanges([]); setNotice(null); dialogueLocators.current.clear(); }}
      /> : null}
      <main className="workspace">
        {projects === null ? (
          error === null ? (
            <LoadingState label="正在读取项目…" />
          ) : (
            <LoadFailure error={error} onRetry={() => void loadProjects()} />
          )
        ) : selectedProject === null ? (
          <ProjectHome
            projects={projects}
            projectTitle={projectTitle}
            directorPlan={directorPlan}
            aspectRatio={aspectRatio}
            narrationLanguages={narrationLanguages}
            onNarrationLanguagesChange={setNarrationLanguages}
            pending={pending}
            error={error}
            deleteConfirmation={deleteConfirmation}
            onTitleChange={setProjectTitle}
            onDirectorPlanChange={setDirectorPlan}
            onAspectRatioChange={setAspectRatio}
            onCreate={createProject}
            onOpen={(project) => void openProject(project)}
            onAskDelete={setDeleteConfirmation}
            onDelete={(projectId) => void deleteProject(projectId)}
            onOpenPlayground={enterPlayground}
          />
        ) : structuredSnapshot === null ? (
          <LoadFailure
            error={error}
            onRetry={() => void openProject(selectedProject)}
          />
        ) : (
          <Suspense fallback={<LoadingState label="正在加载工作台…" />}>
          <StructuredDirectorWorkspace
            toolbarTarget={workspaceToolbar}
            project={selectedProject}
            snapshot={structuredSnapshot}
            pendingSegmentVideoId={pendingSegmentVideoId}
            busy={isBusy}
            pending={pending}
            error={error}
            globalReferencesOpen={globalReferencesOpen}
            onCloseGlobalReferences={() => setGlobalReferencesOpen(false)}
            onUpdateDirectorPlan={updateDirectorPlan}
            onRefreshProjectSnapshot={() => void reloadStructuredSnapshot()}
            onPreviewLocationChange={(change, revision) =>
              structuredDirectorApi.previewLocationChange(selectedProject.id, revision, change)}
            onApplyLocationChange={async (change, revision) => {
              const result = await mutateStructuredDirector(
                () => structuredDirectorApi.applyLocationChange(selectedProject.id, revision, change),
                "edit_location",
              );
              return result !== false;
            }}
            onPreviewScriptChange={(change, revision) =>
              structuredDirectorApi.previewScriptChange(selectedProject.id, revision, change)}
            onApplyScriptChange={async (change, revision) => {
              const result = await mutateStructuredDirector(
                () => structuredDirectorApi.applyScriptChange(selectedProject.id, revision, change),
                "edit_script",
              );
              return result !== false;
            }}
            onGenerateLocationImage={(id) => void mutateStructuredDirector(
              () => structuredDirectorApi.generateLocationImage(selectedProject.id, structuredSnapshot.revision, id),
              "generate_location_image",
            )}
            onCaptureLocationPanorama={(id, name, description, yaw, pitch, hfov) => void mutateStructuredDirector(
              () => structuredDirectorApi.captureLocationPanorama(selectedProject.id, structuredSnapshot.revision, id, name, description, yaw, pitch, hfov),
              "capture_location_panorama",
            )}
            onConfirmReferences={() => void confirmReferences()}
            onSaveScript={(scenes, revision) => void saveScript(scenes, revision)}
            onConfirmScript={() => void confirmScript()}
            onSaveNarrationCue={(sceneId, cue) =>
              void saveNarrationCue(sceneId, cue)
            }
            onGenerateNarration={(sceneId, cueId, language) =>
              void generateNarration(sceneId, cueId, language)
            }
            onGenerateNarrationBatch={() => void generateNarrationBatch()}
            onSelectNarrationAudio={(sceneId, cueId, generationId) =>
              void selectNarration(sceneId, cueId, generationId)
            }
            onClearNarrationAudioSelection={(sceneId, cueId, language) =>
              void clearNarrationSelection(sceneId, cueId, language)
            }
            onGenerateDialogue={(lineId) => void generateDialogue(lineId)}
            onSaveDialogueRecipeParams={(lineId, recipeParams) =>
              void saveDialogueRecipeParams(lineId, recipeParams)
            }
            onGenerateDialogueBatch={() => void generateDialogueBatch()}
            onSelectDialogueAudio={(lineId, generationId) =>
              void selectDialogue(lineId, generationId)
            }
            onSetDialogueTiming={(segmentId, starts, durationSeconds) =>
              void setDialogueTiming(segmentId, starts, durationSeconds)
            }
            onGenerateSceneAnimatic={(sceneId) =>
              void generateSceneAnimatic(sceneId)
            }
            onGenerateSceneFinal={(sceneId, videoAudioVolume, narrationAudioVolume) =>
              void generateSceneFinal(
                sceneId,
                videoAudioVolume,
                narrationAudioVolume,
              )
            }
            onUnlockVisualProduction={() => void unlockVisualProduction()}
            onGenerateKeyframe={(keyframeId) =>
              void generateKeyframe(keyframeId)
            }
            onSaveKeyframe={(
              keyframeId,
              segmentId,
              promptText,
              visibleCharacterIds,
              characterReferences,
              referenceAssetIds,
            ) =>
              void saveKeyframe(
                keyframeId,
                segmentId,
                promptText,
                visibleCharacterIds,
                characterReferences,
                referenceAssetIds,
              )
            }
            onSelectKeyframe={(keyframeId, assetId) =>
              void selectKeyframe(keyframeId, assetId)
            }
            onSaveSegmentKeyframeReferences={(segmentId, assetIds) =>
              void saveSegmentKeyframeReferences(segmentId, assetIds)
            }
            onSaveSegmentKeyframeActivation={(
              segmentId,
              startEnabled,
              endEnabled,
            ) =>
              void saveSegmentKeyframeActivation(
                segmentId,
                startEnabled,
                endEnabled,
              )
            }
            onPreviewSegmentVideoInputs={(segmentId, inputs) => structuredDirectorApi.previewSegmentVideoInputs(selectedProject.id, structuredSnapshot.revision, segmentId, inputs)}
            onSaveSegmentVideoInputs={(segmentId, promptText, inputs) => void saveSegmentVideoInputs(segmentId, promptText, inputs)}
            onSaveSegmentVideoRecipe={(segmentId, recipeId) => void saveSegmentVideoRecipe(segmentId, recipeId)}
            onSaveSegmentKeyframeBoundary={(segmentId, shared) => void saveSegmentKeyframeBoundary(segmentId, shared)}
            onExtractKeyframeVideoFrame={(keyframeId, sourceVideoAssetId, frameIndex) =>
              void extractKeyframeVideoFrame(keyframeId, sourceVideoAssetId, frameIndex)
            }
            onLoadVideoFrameInfo={loadVideoFrameInfo}
            onGenerateSegmentVideo={(segmentId, seed) =>
              void generateSegmentVideo(segmentId, seed)
            }
            onAttachSegmentVideoCandidate={(segmentId, assetId) =>
              void attachSegmentVideoCandidate(segmentId, assetId)
            }
            onSelectSegmentVideo={(segmentId, assetId) =>
              void selectSegmentVideo(segmentId, assetId)
            }
            onClearSegmentVideoSelection={(segmentId) =>
              void clearSegmentVideoSelection(segmentId)
            }
            onUpscaleSegmentVideo={(segmentId) =>
              void upscaleSegmentVideo(segmentId)
            }
            onGenerateFinalVideo={() => void generateFinalVideo()}
            onSelectFinalVideo={(generationId) =>
              void selectFinalVideo(generationId)
            }
            onClearFinalSelection={() => void clearFinalSelection()}
            onApproveFinalVideo={() => void approveFinalVideo()}
            onReopenVideoProduction={() => void reopenVideoProduction()}
            onAddCharacter={(card) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.addCharacter(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  card,
                ),
              )
            }
            onUpdateCharacter={(card) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.updateCharacter(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  card,
                ),
                "edit_reference_card",
                { kind: "character", id: card.id },
              )
            }
            onUpdateNarrator={(profile) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.updateNarrator(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  profile,
                ),
                "edit_reference_card",
                { kind: "narrator", id: profile.id },
              )
            }
            onDiscard={(kind, cardId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.discardCard(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  kind,
                  cardId,
                ),
              )
            }
            onImportImage={(file, category) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.importImageAsset(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  file,
                  category,
                ),
              )
            }
            onImportMedia={(file) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.importMediaAsset(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  file,
                ),
              )
            }
            onDeleteAsset={(assetId) => void deleteAsset(assetId)}
            onDeleteAssets={(assetIds) => void deleteAssets(assetIds)}
            onGenerateAudio={generateAudio}
            onTranscribeAudio={transcribeAudio}
            onTrimAudio={trimAudio}
            onApplyAudioEffect={(assetId, settings) =>
              void applyAudioEffect(assetId, settings)
            }
            onSeparateVideoAudio={(assetId) => void separateVideoAudio(assetId)}
            onExtractVideoFrame={(assetId, frameIndex) => void extractVideoFrame(assetId, frameIndex)}
            onRemixVideoAudio={remixVideoAudio}
            onUploadVoice={(cardId, file) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.uploadReferenceVoice(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  cardId,
                  file,
                ),
              )
            }
            onUploadNarratorVoice={(narratorId, language, file) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.uploadNarratorVoice(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  narratorId,
                  language,
                  file,
                ),
              )
            }
            onGenerateLookSheet={(cardId, lookId, identityAssetIds, promptText) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.generateLookSheet(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  cardId,
                  lookId,
                  identityAssetIds,
                  promptText,
                ),
              )
            }
            onPreviewLookSheet={previewLookSheet}
            onSelectLookAsset={(cardId, lookId, assetId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.selectLookAsset(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  cardId,
                  lookId,
                  assetId,
                ),
              )
            }
            onSelectLookSheet={(cardId, lookId, generationId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.selectLookSheet(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  cardId,
                  lookId,
                  generationId,
                ),
              )
            }
            onDesignVoice={(cardId, voiceDescription, sampleText, seed) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.designVoice(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  cardId,
                  voiceDescription,
                  sampleText,
                  seed,
                ),
              )
            }
            onDesignNarratorVoice={(
              narratorId,
              language,
              voiceDescription,
              sampleText,
              seed,
            ) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.designNarratorVoice(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  narratorId,
                  language,
                  voiceDescription,
                  sampleText,
                  seed,
                ),
              )
            }
            onAttachNarratorVoice={(narratorId, generationId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.attachNarratorVoice(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  narratorId,
                  generationId,
                ),
              )
            }
            onAttachVoice={(cardId, generationId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.attachVoice(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  cardId,
                  generationId,
                ),
              )
            }
            onCancelGeneration={(generationId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.cancelGeneration(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  generationId,
                ),
              )
            }
            onDismissGeneration={(generationId) =>
              void mutateStructuredDirector(() =>
                structuredDirectorApi.dismissGeneration(
                  selectedProject.id,
                  structuredSnapshot.revision,
                  generationId,
                ),
              )
            }
          />
          </Suspense>
        )}
      </main>
    </div>
  );
}
function GenerationProgress({
  generations,
}: {
  generations: ReferenceGeneration[];
}) {
  const progress = summarizeGenerationProgress(generations);
  return (
    <div className="generation-progress" aria-label="生成任务进度">
      {(["tts", "image", "video"] as const).map((category) => {
        const item = progress[category];
        const label =
          category === "tts" ? "TTS" : category === "image" ? "图片" : "视频";
        return (
          <span
            key={category}
            title={`${label}：共 ${item.total} 次尝试`}
          >
            {label} <b>成功 {item.succeeded}</b>
            {item.active > 0 ? ` · 进行 ${item.active}` : ""}
            {item.failed > 0 ? ` · 失败 ${item.failed}` : ""}
          </span>
        );
      })}
    </div>
  );
}
export function summarizeGenerationProgress(
  generations: ReferenceGeneration[],
) {
  const result = {
    tts: { total: 0, succeeded: 0, active: 0, failed: 0 },
    image: { total: 0, succeeded: 0, active: 0, failed: 0 },
    video: { total: 0, succeeded: 0, active: 0, failed: 0 },
  };
  for (const generation of generations) {
    if (generation.dismissed) continue;
    const category =
      generation.kind === "character_voice" ||
      generation.kind === "narrator_voice" ||
      generation.kind === "narration_audio" ||
      generation.kind === "dialogue_audio" ||
      generation.kind === "generated_audio"
        ? "tts"
        : generation.kind === "character_look_sheet" ||
            generation.kind === "location_image" ||
            generation.kind === "panorama_capture" ||
            generation.kind === "keyframe_image"
          ? "image"
          : "video";
    const item = result[category];
    item.total += 1;
    if (generation.phase === "succeeded") {
      item.succeeded += 1;
    } else if (
      generation.phase === "failed" ||
      generation.phase === "cancelled" ||
      generation.phase === "submission_uncertain"
    ) {
      item.failed += 1;
    } else {
      item.active += 1;
    }
  }
  return result;
}
interface ProjectHomeProps {
  projects: ProjectSummary[];
  projectTitle: string;
  directorPlan: string;
  aspectRatio: ProjectAspectRatio;
  narrationLanguages: NarrationLanguage[];
  onNarrationLanguagesChange: (value: NarrationLanguage[]) => void;
  pending: PendingAction;
  error: string | null;
  deleteConfirmation: string | null;
  onTitleChange: (value: string) => void;
  onDirectorPlanChange: (value: string) => void;
  onAspectRatioChange: (value: ProjectAspectRatio) => void;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onOpen: (project: ProjectSummary) => void;
  onAskDelete: (projectId: string | null) => void;
  onDelete: (projectId: string) => void;
  onOpenPlayground: () => void;
}
function ProjectHome({
  projects,
  projectTitle,
  directorPlan,
  aspectRatio,
  narrationLanguages,
  onNarrationLanguagesChange,
  pending,
  error,
  deleteConfirmation,
  onTitleChange,
  onDirectorPlanChange,
  onAspectRatioChange,
  onCreate,
  onOpen,
  onAskDelete,
  onDelete,
  onOpenPlayground,
}: ProjectHomeProps) {
  const isBusy = pending !== null;
  return (
    <section className="project-home">
      <div className="project-hero">
        <div className="empty-copy">
          <p className="eyebrow">Your stories</p>
          <h1>从完整导演方案开始。</h1>
          <p className="empty-lead">
            前期创意讨论留在你习惯的工具中；StoryRail
            专注把方案变成可生产的结构化脚本。
          </p>
          <div className="boundary-note">
            <span>00</span>
            <p>项目保存在 `.stories/`；删除后先进入内部回收站。</p>
          </div>
        </div>
        <form className="idea-card" onSubmit={onCreate}>
          <div className="idea-card-header">
            <label htmlFor="project-title">导入完整导演方案</label>
            <span>创建后原文固化为只读基线</span>
          </div>
          <Suspense fallback={null}><CreativePartnerPrompt /></Suspense>
          <label className="card-field" htmlFor="project-title">
            <span>项目名称</span>
            <input
              id="project-title"
              value={projectTitle}
              disabled={isBusy}
              maxLength={56}
              onChange={(event) => onTitleChange(event.target.value)}
            />
          </label>
          <textarea
            id="director-plan"
            aria-label="完整导演方案"
            value={directorPlan}
            disabled={isBusy}
            maxLength={50000}
            placeholder="粘贴已经讨论完成的 Director Plan Markdown…"
            onChange={(event) => onDirectorPlanChange(event.target.value)}
          />
          <fieldset className="narration-language-choice" disabled={isBusy}>
            <legend>旁白语言（至少选一种）</legend>
            {(["zh", "en"] as const).map((language) => (
              <label key={language}>
                <input type="checkbox" checked={narrationLanguages.includes(language)}
                  onChange={(event) => onNarrationLanguagesChange(
                    (["zh", "en"] as const).filter((item) => item === language
                      ? event.target.checked : narrationLanguages.includes(item)),
                  )} />
                {language === "zh" ? "中文旁白" : "英文旁白"}
              </label>
            ))}
            <p>仅生成所选语言；两种都选时制作双语版本。创建后不可修改。</p>
          </fieldset>
          <div className="idea-card-footer">
            <p>创建后进入角色与旁白引用准备</p>
            <div className="idea-card-actions">
              <label className="aspect-ratio-field" htmlFor="aspect-ratio">
                <span>画面比例</span>
                <select
                  id="aspect-ratio"
                  value={aspectRatio}
                  disabled={isBusy}
                  onChange={(event) =>
                    onAspectRatioChange(
                      event.target.value as ProjectAspectRatio,
                    )
                  }
                >
                  <option value="16:9">16:9 横屏</option>
                  <option value="9:16">9:16 竖屏</option>
                  <option value="2:1">2:1 宽银幕</option>
                </select>
              </label>
              <button
                className="primary-button"
                disabled={
                  isBusy || !projectTitle.trim() || !directorPlan.trim() || narrationLanguages.length === 0
                }
              >
                {pending === "create" ? "正在创建…" : "创建项目"}
                <span aria-hidden="true">↗</span>
              </button>
            </div>
          </div>
        </form>
      </div>

      <div className="project-library">
        <div className="library-heading">
          <div>
            <p className="eyebrow">Project library</p>
            <h2>已有项目</h2>
          </div>
          <button
            className="secondary-button"
            type="button"
            disabled={isBusy}
            onClick={onOpenPlayground}
          >
            Playground
          </button>
          <span>{projects.length.toString().padStart(2, "0")}</span>
        </div>
        {error !== null ? <ErrorNotice message={error} /> : null}
        {projects.length === 0 ? (
          <div className="project-empty">
            <p>还没有项目。上面的第一句话，就是第一条 StoryRail。</p>
          </div>
        ) : (
          <div className="project-grid">
            {projects.map((project, index) => (
              <article className="project-card" key={project.id}>
                <div className="project-card-index">
                  {String(index + 1).padStart(2, "0")}
                </div>
                <h3>{project.title}</h3>
                <div className="project-meta">
                  <span>
                    {project.status === "needs_recovery"
                      ? "等待恢复"
                      : "结构化导演台"}
                  </span>
                  <span>{project.aspect_ratio}</span>
                  <time dateTime={project.updated_at}>
                    {formatUpdatedAt(project.updated_at)}
                  </time>
                </div>
                <div className="project-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={isBusy}
                    onClick={() => onOpen(project)}
                  >
                    打开
                  </button>
                  {deleteConfirmation === project.id ? (
                    <div className="delete-confirmation">
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => onDelete(project.id)}
                      >
                        确定删除
                      </button>
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => onAskDelete(null)}
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      className="delete-button"
                      type="button"
                      disabled={isBusy}
                      onClick={() => onAskDelete(project.id)}
                    >
                      删除
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
function LoadingState({ label }: { label: string }) {
  return (
    <div className="center-state" role="status">
      <div className="loading-rail" aria-hidden="true">
        <span />
      </div>
      <p>{label}</p>
    </div>
  );
}
function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="error-notice" role="alert">
      <span aria-hidden="true">!</span>
      <p>{message}</p>
    </div>
  );
}
export function FloatingErrorNotice({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="floating-error-notice" role="alert" aria-live="assertive">
      <span aria-hidden="true">!</span>
      <p>{message}</p>
      <button type="button" aria-label="关闭错误提示" onClick={onDismiss}>
        ×
      </button>
    </div>
  );
}
export function FloatingActionNotice({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="floating-action-notice" role="status" aria-live="polite">
      <span aria-hidden="true">i</span>
      <p>{message}</p>
      <button type="button" aria-label="关闭操作提示" onClick={onDismiss}>
        ×
      </button>
    </div>
  );
}
export function changedDialogueSegmentLocators(
  previous: Scene[],
  current: Scene[],
) {
  const previousDialogueBySegmentId = new Map(
    previous
      .flatMap((scene) => scene.segments)
      .map((segment) => [segment.id, JSON.stringify(segment.dialogue_lines)]),
  );
  return current.flatMap((scene, sceneIndex) =>
    scene.segments.flatMap((segment, segmentIndex) =>
      previousDialogueBySegmentId.get(segment.id) !==
      JSON.stringify(segment.dialogue_lines)
        ? [
            `scene${String(sceneIndex + 1).padStart(2, "0")}-seg${String(segmentIndex + 1).padStart(2, "0")}`,
          ]
        : [],
    ),
  );
}
function dialoguePromptReminder(locators: string[]) {
  const shown = locators.slice(0, 4).join("、");
  const remaining =
    locators.length > 4 ? ` 等 ${locators.length} 个 Segment` : "";
  return `对白已保存。请同步手动修改或使用“优化视频提示词”：${shown}${remaining}。`;
}
function LoadFailure({
  error,
  onRetry,
}: {
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="center-state load-failure">
      <p>{error ?? "无法读取项目。"}</p>
      <button className="secondary-button" type="button" onClick={onRetry}>
        重新读取
      </button>
    </div>
  );
}
function formatUpdatedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
function errorMessage(caught: unknown): string {
  if (caught instanceof Error) return caught.message;
  return "发生了无法识别的错误。";
}
const PROJECT_QUERY_PARAMETER = "project";
const PLAYGROUND_QUERY_PARAMETER = "playground";
function projectIdFromLocation(): string | null {
  const projectId = new URL(window.location.href).searchParams
    .get(PROJECT_QUERY_PARAMETER)
    ?.trim();
  return projectId === undefined || projectId.length === 0 ? null : projectId;
}
// `?playground=1` 与 `?project=<id>` 互斥；Playground 优先。
function playgroundFromLocation(): boolean {
  return (
    new URL(window.location.href).searchParams
      .get(PLAYGROUND_QUERY_PARAMETER)
      ?.trim() === "1"
  );
}
function pushPlaygroundLocation(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete(PROJECT_QUERY_PARAMETER);
  url.searchParams.set(PLAYGROUND_QUERY_PARAMETER, "1");
  applyLocation(url, "push");
}
function clearPlaygroundLocation(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete(PLAYGROUND_QUERY_PARAMETER);
  applyLocation(url, "replace");
}
function pushProjectLocation(projectId: string | null): void {
  updateProjectLocation(projectId, "push");
}
function replaceProjectLocation(projectId: string | null): void {
  updateProjectLocation(projectId, "replace");
}
function updateProjectLocation(
  projectId: string | null,
  mode: "push" | "replace",
): void {
  const url = new URL(window.location.href);
  if (projectId === null) {
    url.searchParams.delete(PROJECT_QUERY_PARAMETER);
  } else {
    url.searchParams.set(PROJECT_QUERY_PARAMETER, projectId);
  }
  applyLocation(url, mode);
}
function applyLocation(url: URL, mode: "push" | "replace"): void {
  const nextLocation = `${url.pathname}${url.search}${url.hash}`;
  const currentLocation = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextLocation === currentLocation) return;
  if (mode === "push") {
    window.history.pushState(null, "", nextLocation);
  } else {
    window.history.replaceState(null, "", nextLocation);
  }
}
