import { stableStringify, useProtectedValue } from "./draft_protection";
import { ImageZoomButton } from "../ImagePreview";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type {
  CharacterCard,
  KeyframeEnvironmentMode,
  KeyframeSubmissionPreview,
  KeyframeCharacterReference,
  StructuredDirectorSnapshot,
} from "../api";
import { structuredDirectorApi } from "../api";
import {
  DirectorDisclosure,
  ImagePromptEditorFields,
  ImageSubmissionPreviewDialog,
  MultiImageAssetPickerDialog,
  GenerationCandidateList,
  SingleImageAssetPickerDialog,
  VideoFrameExtractDialog,
  type VideoFrameInfo,
  ZoomableImage,
  assetById,
  imageAssets,
  toggleId,
} from "./shared";
import {
  completeProjectRecipeInputs,
  recipeInputsError,
  useSegmentVideoDraft,
} from "./RecipeInputsControl";
export function SegmentKeyframeInputs({
  projectId,
  snapshot,
  segmentId,
  sceneIndex,
  shotIndex,
  segmentIndex,
  segmentCount,
  busy,
  videoDependenciesEditable = false,
  onSaveVideoInputs,
  onSaveKeyframe,
  onGenerate,
  onSelect,
  onSaveReferences,
  onSaveActivation,
  onSaveBoundary,
  onExtractFrame,
  onLoadVideoFrameInfo,
  onDismissGeneration,
  onCancel,
}: {
  projectId: string;
  snapshot: StructuredDirectorSnapshot;
  segmentId: string;
  sceneIndex: number;
  shotIndex: number;
  segmentIndex: number;
  segmentCount: number;
  busy: boolean;
  videoDependenciesEditable?: boolean;
  onSaveVideoInputs?: (
    segmentId: string,
    promptText: string,
    inputs: import("../api").RecipeInputs,
  ) => void;
  onSaveKeyframe: (
    keyframeId: string,
    segmentId: string,
    promptText: string,
    visibleCharacterIds: string[],
    characterReferences: KeyframeCharacterReference[],
    referenceAssetIds: string[],
    environmentMode: KeyframeEnvironmentMode,
    environmentViewId: string | null,
    environmentNoneReason: string | null,
  ) => void;
  onGenerate: (keyframeId: string) => void;
  onSelect: (keyframeId: string, assetId: string) => void;
  onSaveReferences: (segmentId: string, assetIds: string[]) => void;
  onSaveActivation: (
    segmentId: string,
    startEnabled: boolean,
    endEnabled: boolean,
  ) => void;
  onSaveBoundary?: (segmentId: string, shared: boolean) => void;
  onExtractFrame?: (keyframeId: string, sourceVideoAssetId: string, frameIndex: number) => void;
  onLoadVideoFrameInfo?: (assetId: string) => Promise<VideoFrameInfo>;
  onDismissGeneration: (generationId: string) => void;
  onCancel?: (generationId: string) => void;
}) {
  const [frameDialogOpen, setFrameDialogOpen] = useState(false);
  const plan = snapshot.keyframe_plan;
  const binding = plan?.segments.find((item) => item.segment_id === segmentId);
  const {
    value: referenceIds,
    setValue: setReferenceIds,
    conflict: referenceConflict,
    reset: resetReferences,
  } = useProtectedValue(binding?.reference_asset_ids ?? []);
  if (plan === null || binding === undefined) return null;
  const keyframeById = new Map(plan.keyframes.map((item) => [item.id, item]));
  const start = keyframeById.get(binding.start_keyframe_id);
  const end = keyframeById.get(binding.end_keyframe_id);
  if (start === undefined || end === undefined) return null;
  // 共享首帧由上一段拥有；Core 投影是唯一事实，Web 不推断连续性。
  const sharesPrevious = start.owner_segment_id !== segmentId;
  const sharesNext = plan.segments.some(
    (item) => item.segment_id !== segmentId && item.start_keyframe_id === end.id,
  );
  const startRelation = sharesPrevious
    ? segmentIndex > 0
      ? "与上一 Segment 尾帧共享"
      : "与上一 Shot 末段尾帧共享"
    : segmentIndex > 0 || shotIndex > 0
      ? "独立首帧"
      : "当前 Shot 的起始时间边界";
  const endRelation = sharesNext
    ? "与下一 Segment 首帧共享"
    : segmentIndex < segmentCount - 1
      ? "独立尾帧"
      : "当前 Shot 的结束时间边界";
  const extraction = binding.start_frame_extraction;
  const hasPreviousInScene = segmentIndex > 0 || shotIndex > 0;
  const sourceVideo =
    extraction.source_video_asset_id === null
      ? null
      : assetById(snapshot.assets, extraction.source_video_asset_id);
  const frameGeneration = snapshot.generations
    .filter((item) => item.kind === "video_frame" && item.target_id === start.id && !item.dismissed)
    .at(-1);
  const frameInProgress =
    frameGeneration !== undefined &&
    ["submitting", "queued", "running"].includes(frameGeneration.phase);
  const frameFailed =
    frameGeneration !== undefined &&
    ["failed", "cancelled", "submission_uncertain"].includes(frameGeneration.phase);
  const canExtract =
    extraction.state === "ready" &&
    sourceVideo !== null &&
    onExtractFrame !== undefined &&
    onLoadVideoFrameInfo !== undefined &&
    snapshot.allowed_actions.includes("extract_video_frame");
  return (
    <DirectorDisclosure initiallyOpen className="segment-keyframe-inputs">
      <summary
        className="segment-layer-summary"
        aria-label={`Scene ${sceneIndex + 1} Shot ${shotIndex + 1} Segment ${segmentIndex + 1} 画面输入`}
      >
        <div>
          <strong>Segment 画面输入</strong>
          <span>首尾帧具有明确的时间位置；其他图片没有时间位置。</span>
        </div>
        <small>
          支持图片参考的 recipe 可在技术层把三者都作为图片输入，但 Core
          不混淆关键帧与视觉参考的语义。
        </small>
      </summary>
      <div className="segment-keyframe-grid">
        <KeyframeSlot
          label="首帧"
          temporalLabel="START"
          keyframe={start}
          projectId={projectId}
          segmentId={segmentId}
          referenceAssetIds={referenceIds}
          onReferenceAssetIdsChange={setReferenceIds}
          onSaveReferences={() => {
            if (
              !referenceConflict &&
              snapshot.allowed_actions.includes("edit_keyframe_references")
            )
              onSaveReferences(segmentId, referenceIds);
          }}
          onResetReferences={resetReferences}
          referenceDirty={
            JSON.stringify(referenceIds) !==
            JSON.stringify(binding.reference_asset_ids)
          }
          relation={startRelation}
          snapshot={snapshot}
          busy={busy || referenceConflict}
          enabled={binding.start_enabled}
          onToggle={() =>
            onSaveActivation(
              segmentId,
              !binding.start_enabled,
              binding.end_enabled,
            )
          }
          onSave={onSaveKeyframe}
          onGenerate={onGenerate}
          onSelect={onSelect}
          onDismiss={onDismissGeneration}
          onCancel={onCancel}
        />
        <div className="keyframe-time-direction" aria-hidden="true">
          <span />
          <b>时间方向</b>
          <span />
        </div>
        <KeyframeSlot
          label="尾帧"
          temporalLabel="END"
          keyframe={end}
          projectId={projectId}
          segmentId={segmentId}
          referenceAssetIds={referenceIds}
          onReferenceAssetIdsChange={setReferenceIds}
          onSaveReferences={() => {
            if (
              !referenceConflict &&
              snapshot.allowed_actions.includes("edit_keyframe_references")
            )
              onSaveReferences(segmentId, referenceIds);
          }}
          onResetReferences={resetReferences}
          referenceDirty={
            JSON.stringify(referenceIds) !==
            JSON.stringify(binding.reference_asset_ids)
          }
          relation={endRelation}
          snapshot={snapshot}
          busy={busy || referenceConflict}
          enabled={binding.end_enabled}
          onToggle={() =>
            onSaveActivation(
              segmentId,
              binding.start_enabled,
              !binding.end_enabled,
            )
          }
          onSave={onSaveKeyframe}
          onGenerate={onGenerate}
          onSelect={onSelect}
          onDismiss={onDismissGeneration}
          onCancel={onCancel}
        />
      </div>
      <SegmentOtherImages
        snapshot={snapshot}
        segmentId={segmentId}
        busy={busy}
        dependenciesEditable={videoDependenciesEditable}
        onSave={onSaveVideoInputs}
      />
      {extraction.source_segment_id !== null ? (
        <div className="cross-shot-continuity" aria-label="与上一段的衔接">
          <div>
            <strong>与上一段的衔接</strong>
            <span>
              {sharesPrevious
                ? "首帧与上一段尾帧是同一 Keyframe，两段按同一张图衔接。"
                : "首帧是独立 Keyframe：可直接生成，也可从上一段已采用视频抽取任意一帧作为候选，再按需后期处理。程序不强制两段一致。"}
            </span>
            {extraction.state !== "ready" && !sharesPrevious ? (
              <span role="status">{extraction.message}</span>
            ) : null}
            {frameInProgress ? (
              <span role="status">{frameGeneration?.message || "正在抽帧…"}</span>
            ) : frameFailed ? (
              <span role="status">
                抽帧失败：{frameGeneration?.message || frameGeneration?.error_code || "请重试"}
              </span>
            ) : null}
          </div>
          <div className="keyframe-boundary-actions">
            {hasPreviousInScene && onSaveBoundary !== undefined ? (
              <label>
                <input
                  type="checkbox"
                  checked={sharesPrevious}
                  disabled={busy || !snapshot.allowed_actions.includes("edit_keyframe_references")}
                  onChange={() => onSaveBoundary(segmentId, !sharesPrevious)}
                />
                与上一段尾帧共享
              </label>
            ) : null}
            {!sharesPrevious ? (
              <button
                type="button"
                className="secondary-button"
                disabled={busy || frameInProgress || !canExtract}
                title={canExtract ? "按帧号从上一段已采用视频抽取一帧，作为本首帧候选" : extraction.message}
                onClick={() => setFrameDialogOpen(true)}
              >
                {frameInProgress ? "正在抽帧…" : "从上一 seg 抽取"}
              </button>
            ) : null}
          </div>
          {frameDialogOpen && canExtract && sourceVideo !== null ? (
            <VideoFrameExtractDialog
              videoUrl={sourceVideo.content_url}
              title="从上一 Segment 视频抽取首帧"
              description="抽出的帧成为本首帧的候选，不会自动选择；分辨率不足时可下载后期处理，再导入并选择。"
              busy={busy}
              loadInfo={() => onLoadVideoFrameInfo!(sourceVideo.id)}
              onClose={() => setFrameDialogOpen(false)}
              onConfirm={(frameIndex) => {
                setFrameDialogOpen(false);
                onExtractFrame!(start.id, sourceVideo.id, frameIndex);
              }}
            />
          ) : null}
        </div>
      ) : null}
    </DirectorDisclosure>
  );
}

function SegmentOtherImages({
  snapshot,
  segmentId,
  busy,
  dependenciesEditable,
  onSave,
}: {
  snapshot: StructuredDirectorSnapshot;
  segmentId: string;
  busy: boolean;
  dependenciesEditable: boolean;
  onSave?: (
    segmentId: string,
    promptText: string,
    inputs: import("../api").RecipeInputs,
  ) => void;
}) {
  const draft = useSegmentVideoDraft();
  const [picker, setPicker] = useState<"keyframe" | "reference" | null>(null);
  if (draft === null || draft.segmentId !== segmentId) return null;
  const video = snapshot.video_plan?.segments.find(
    (item) => item.segment_id === segmentId,
  );
  const recipeView = snapshot.provider_recipes?.find(
    (item) => item.recipe.id === video?.active_recipe,
  );
  const recipe = recipeView?.recipe;
  const slot = recipe?.slots.find((item) => item.role === "reference_image");
  const referenceImageRecipe = video?.recipe_state?.options
    .map((option) =>
      snapshot.provider_recipes?.find(
        (item) => item.recipe.id === option.id,
      )?.recipe,
    )
    .find((item) =>
      item?.slots.some((candidate) => candidate.role === "reference_image"),
    );
  const referenceImageSlot = referenceImageRecipe?.slots.find(
    (item) => item.role === "reference_image",
  );
  const activeGeneration = snapshot.generations.some(
    (item) =>
      item.kind === "segment_video" &&
      item.target_id === segmentId &&
      ["submitting", "queued", "running"].includes(item.phase),
  );
  const disabled =
    busy ||
    activeGeneration ||
    !dependenciesEditable ||
    !snapshot.allowed_actions.includes("edit_segment_video_plan");
  if (video === undefined || recipe === undefined || slot === undefined) {
    return (
      <section className="segment-other-images" aria-label="Segment 其他图片">
        <header>
          <div>
            <strong>其他图片</strong>
            <span>没有时间位置，只作为图片参考 recipe 的显式视觉条件。</span>
          </div>
          <small>0/{referenceImageSlot?.maximum ?? 0}</small>
        </header>
        <p>
          {video === undefined
            ? "视频计划尚未建立。"
            : `当前 ${recipe?.label ?? video.active_recipe ?? "视频 recipe"} 不接收其他图片；切换到 ${referenceImageRecipe?.label ?? "支持图片参考的 recipe"} 后可添加。`}
        </p>
      </section>
    );
  }
  const items = draft.inputs.value.bindings[slot.key] ?? [];
  const savedInputs = video.recipes[video.active_recipe ?? ""] ?? {
    bindings: {},
    params: {},
  };
  const savedItems = savedInputs.bindings[slot.key] ?? [];
  const otherDirty = stableStringify(items) !== stableStringify(savedItems);
  const keyframesByAsset = new Map(
    (snapshot.keyframe_plan?.keyframes ?? []).flatMap((keyframe) =>
      keyframe.selected_asset_id === null
        ? []
        : [[keyframe.selected_asset_id, keyframe] as const],
    ),
  );
  const segmentBinding = snapshot.keyframe_plan?.segments.find(
    (item) => item.segment_id === segmentId,
  );
  const boundaryAssetIds = new Set(
    [
      [segmentBinding?.start_keyframe_id, segmentBinding?.start_enabled],
      [segmentBinding?.end_keyframe_id, segmentBinding?.end_enabled],
    ].flatMap(([keyframeId, enabled]) => {
      if (!enabled) return [];
      const assetId = snapshot.keyframe_plan?.keyframes.find(
        (item) => item.id === keyframeId,
      )?.selected_asset_id;
      return assetId ? [assetId] : [];
    }),
  );
  const selectedIds = new Set(items.map((item) => item.asset_id));
  const availableImages = imageAssets(snapshot.assets).filter(
    (asset) => !selectedIds.has(asset.id) && !boundaryAssetIds.has(asset.id),
  );
  const keyframeImages = availableImages.filter((asset) =>
    keyframesByAsset.has(asset.id),
  );
  const referenceImages = availableImages.filter(
    (asset) =>
      !keyframesByAsset.has(asset.id) && asset.image_category !== "keyframe",
  );
  const updateItems = (next: typeof items) =>
    draft.inputs.setValue((current) => ({
      ...current,
      bindings: { ...current.bindings, [slot.key]: next },
    }));
  const choose = (assetId: string) => {
    updateItems([...items, { asset_id: assetId, description: "" }]);
    setPicker(null);
  };
  const inputsError = recipeInputsError(recipe, draft.inputs.value);
  const saveDisabled =
    disabled ||
    onSave === undefined ||
    activeGeneration ||
    draft.prompt.conflict ||
    draft.inputs.conflict ||
    !otherDirty ||
    inputsError !== null ||
    (draft.prompt.dirty && !draft.prompt.value.trim());
  return (
    <section className="segment-other-images" aria-label="Segment 其他图片">
      <header>
        <div>
          <strong>其他图片</strong>
          <span>
            可来自已选关键帧或资产库参考图；当前已启用的首尾帧不会重复列入。
            没有时间位置，只作为当前 {recipe.label} 的视觉条件。
          </span>
        </div>
        <small>
          {items.length}/{slot.maximum}
        </small>
      </header>
      {items.length === 0 ? <p>尚未添加其他图片。</p> : null}
      <div className="segment-other-image-list">
        {items.map((binding, index) => {
          const asset = assetById(snapshot.assets, binding.asset_id);
          const keyframe = keyframesByAsset.get(binding.asset_id);
          const label =
            video.recipe_state?.slot_labels[slot.key]?.[index] ??
            `其他图片 ${index + 1}`;
          return (
            <article key={binding.asset_id}>
              {asset ? (
                <ZoomableImage
                  src={asset.content_url}
                  alt={asset.display_name ?? label}
                />
              ) : (
                <span className="segment-video-reference-missing">
                  图片不可用
                </span>
              )}
              <div>
                <strong>{label}</strong>
                <small>
                  {keyframe
                    ? `关键帧 @${keyframe.id.slice(0, 6)}`
                    : "资产库参考图"}
                </small>
                <label>
                  <span>{label} 说明</span>
                  <textarea
                    aria-label={`其他图片 ${index + 1} 描述`}
                    aria-invalid={!binding.description?.trim()}
                    maxLength={2000}
                    value={binding.description ?? ""}
                    disabled={disabled}
                    placeholder="说明这张图定义的角色、场景、道具或视觉关系。"
                    onChange={(event) =>
                      updateItems(
                        items.map((item, position) =>
                          position === index
                            ? { ...item, description: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={disabled}
                  onClick={() =>
                    updateItems(
                      items.filter((_, position) => position !== index),
                    )
                  }
                >
                  移除其他图片
                </button>
              </div>
            </article>
          );
        })}
      </div>
      <div className="segment-other-image-source-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={
            disabled ||
            items.length >= slot.maximum ||
            keyframeImages.length === 0
          }
          onClick={() => setPicker("keyframe")}
        >
          从关键帧选择
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={
            disabled ||
            items.length >= slot.maximum ||
            referenceImages.length === 0
          }
          onClick={() => setPicker("reference")}
        >
          从资产库选择参考图
        </button>
      </div>
      {items.some((item) => !item.description?.trim()) ? (
        <p role="alert">每张其他图片都必须填写说明后才能保存。</p>
      ) : inputsError ? (
        <p role="alert">{inputsError}</p>
      ) : null}
      {draft.prompt.conflict || draft.inputs.conflict ? (
        <p role="alert">
          视频计划已更新，未保存输入仍被保留；请取消计划修改后重试。
        </p>
      ) : null}
      <div className="segment-other-image-save-actions">
        <button
          type="button"
          className="primary-button"
          disabled={saveDisabled}
          onClick={() =>
            onSave?.(
              segmentId,
              draft.prompt.value.trim(),
              completeProjectRecipeInputs(recipe, draft.inputs.value),
            )
          }
        >
          保存其他图片
        </button>
        {otherDirty ? (
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => updateItems(structuredClone(savedItems))}
          >
            取消其他图片修改
          </button>
        ) : null}
      </div>
      {picker === "keyframe" ? (
        <SingleImageAssetPickerDialog
          title="从已选关键帧添加其他图片"
          ariaLabel="从关键帧选择其他图片"
          assets={keyframeImages}
          selectedAssetId={null}
          busy={disabled}
          onClose={() => setPicker(null)}
          onSelect={choose}
        />
      ) : null}
      {picker === "reference" ? (
        <SingleImageAssetPickerDialog
          title="从资产库添加参考图"
          ariaLabel="从资产库选择其他图片"
          assets={referenceImages}
          selectedAssetId={null}
          busy={disabled}
          onClose={() => setPicker(null)}
          onSelect={choose}
        />
      ) : null}
    </section>
  );
}

export function KeyframeSlot({
  projectId,
  segmentId,
  referenceAssetIds,
  onReferenceAssetIdsChange,
  onSaveReferences,
  referenceDirty,
  onResetReferences,
  label,
  temporalLabel,
  keyframe,
  relation,
  snapshot,
  busy,
  onSave,
  onGenerate,
  onSelect,
  onDismiss,
  onCancel,
  enabled,
  onToggle,
}: {
  projectId: string;
  segmentId: string;
  referenceAssetIds: string[];
  onReferenceAssetIdsChange: (assetIds: string[]) => void;
  onSaveReferences: () => void;
  referenceDirty: boolean;
  onResetReferences?: () => void;
  label: string;
  temporalLabel: "START" | "END";
  keyframe: NonNullable<
    StructuredDirectorSnapshot["keyframe_plan"]
  >["keyframes"][number];
  relation: string;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  enabled: boolean;
  onToggle: () => void;
  onSave: (
    keyframeId: string,
    segmentId: string,
    promptText: string,
    visibleCharacterIds: string[],
    characterReferences: KeyframeCharacterReference[],
    referenceAssetIds: string[],
    environmentMode: KeyframeEnvironmentMode,
    environmentViewId: string | null,
    environmentNoneReason: string | null,
  ) => void;
  onGenerate: (keyframeId: string) => void;
  onSelect: (keyframeId: string, assetId: string) => void;
  onDismiss: (generationId: string) => void;
  onCancel?: (generationId: string) => void;
}) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [referencePickerOpen, setReferencePickerOpen] = useState(false);
  const protectedPlan = useProtectedValue({
    promptText: keyframe.prompt_text,
    visibleCharacterIds: keyframe.visible_character_ids,
    characterReferences: keyframe.character_references,
    environmentMode: keyframe.environment_mode,
    environmentViewId: keyframe.environment_view_id,
    environmentNoneReason: keyframe.environment_none_reason ?? "",
  });
  const {
    promptText,
    visibleCharacterIds,
    characterReferences,
    environmentMode,
    environmentViewId,
    environmentNoneReason,
  } = protectedPlan.value;
  // none 理由可选，只在 none 时提交；空白与其它模式回传 null。
  const submittedNoneReason =
    environmentMode === "none" ? environmentNoneReason.trim() || null : null;
  const noneReasonInvalid = (submittedNoneReason?.length ?? 0) > 500;
  const setPromptText = (promptText: string) =>
    protectedPlan.setValue((v) => ({ ...v, promptText }));
  const setVisibleCharacterIds = (
    next: string[] | ((current: string[]) => string[]),
  ) =>
    protectedPlan.setValue((v) => {
      const ids =
        typeof next === "function" ? next(v.visibleCharacterIds) : next;
      return {
        ...v,
        visibleCharacterIds: ids,
        // 不再可见的角色同时移除其造型选择，与 Core 规则一致。
        characterReferences: v.characterReferences.filter((item) =>
          ids.includes(item.character_id),
        ),
      };
    });
  const setCharacterLook = (character: CharacterCard, lookId: string | null) =>
    protectedPlan.setValue((v) => ({
      ...v,
      characterReferences: [
        ...v.characterReferences.filter(
          (item) => item.character_id !== character.id,
        ),
        { character_id: character.id, look_id: lookId },
      ],
    }));
  const setEnvironment = (
    environment: Partial<{
      environmentMode: KeyframeEnvironmentMode;
      environmentViewId: string | null;
      environmentNoneReason: string;
    }>,
  ) => protectedPlan.setValue((v) => ({ ...v, ...environment }));
  const [editorOpen, setEditorOpen] = useState(false);
  const closeEditor = () => {
    if (
      (!protectedPlan.dirty && !referenceDirty) ||
      window.confirm("关闭并放弃未保存的关键帧修改？")
    ) {
      protectedPlan.reset();
      onResetReferences?.();
      setEditorOpen(false);
    }
  };
  const [submissionPreviewOpen, setSubmissionPreviewOpen] = useState(false);
  const [submissionPreview, setSubmissionPreview] = useState<{
    key: string;
    inputKey: string;
    data: KeyframeSubmissionPreview | null;
    error: string | null;
  }>({ key: "", inputKey: "", data: null, error: null });
  const previewInputKey = JSON.stringify({
    keyframeId: keyframe.id,
    segmentId,
    promptText,
    visibleCharacterIds,
    characterReferences,
    referenceAssetIds,
    environmentMode,
    environmentViewId,
    submittedNoneReason,
  });
  const previewKey = `${snapshot.revision}:${previewInputKey}`;
  useEffect(() => {
    if (!editorOpen && !submissionPreviewOpen) return;
    let activePreview = true;
    const timer = window.setTimeout(() => {
      void structuredDirectorApi
        .previewKeyframe(
          projectId,
          snapshot.revision,
          keyframe.id,
          segmentId,
          promptText,
          visibleCharacterIds,
          characterReferences,
          referenceAssetIds,
          environmentMode,
          environmentViewId,
          submittedNoneReason,
        )
        .then((data) => {
          if (activePreview)
            setSubmissionPreview({
              key: previewKey,
              inputKey: previewInputKey,
              data,
              error: null,
            });
        })
        .catch((error: unknown) => {
          if (activePreview)
            setSubmissionPreview({
              key: previewKey,
              inputKey: previewInputKey,
              data: null,
              error:
                error instanceof Error ? error.message : "关键帧预览暂不可用。",
            });
        });
    }, 150);
    return () => {
      activePreview = false;
      window.clearTimeout(timer);
    };
  }, [
    editorOpen,
    submissionPreviewOpen,
    projectId,
    snapshot.revision,
    keyframe.id,
    segmentId,
    promptText,
    visibleCharacterIds.join(":"),
    JSON.stringify(characterReferences),
    referenceAssetIds.join(":"),
    environmentMode,
    environmentViewId,
    submittedNoneReason,
    previewKey,
  ]);
  const selected =
    keyframe.selected_asset_id === null
      ? null
      : assetById(snapshot.assets, keyframe.selected_asset_id);
  const generations = snapshot.generations.filter(
    (item) =>
      item.kind === "keyframe_image" &&
      item.target_id === keyframe.id &&
      !item.dismissed,
  );
  const active = generations.find(
    (item) =>
      item.phase === "submitting" ||
      item.phase === "queued" ||
      item.phase === "running",
  );
  const candidates = generations.filter(
    (item) => item.phase === "succeeded" && item.output_asset_id !== null,
  );
  const latestGeneration = generations[generations.length - 1] ?? null;
  const effectivePreview =
    submissionPreview.key === previewKey ||
    submissionPreview.inputKey === previewInputKey
      ? submissionPreview
      : null;
  const visibleNames = keyframe.visible_character_ids.map(
    (characterId) =>
      snapshot.reference_library.characters.find(
        (item) => item.id === characterId,
      )?.name ?? `@${characterId.slice(0, 6)}`,
  );
  return (
    <article
      className={`keyframe-slot is-${temporalLabel.toLowerCase()}${enabled ? " is-enabled" : " is-disabled"}`}
    >
      <div className="keyframe-slot-heading">
        <span>{label}</span>
        <div>
          <strong>{temporalLabel}</strong>
          <button
            type="button"
            className="keyframe-activation-button"
            aria-label={`${enabled ? "停用" : "激活"}${label}`}
            aria-pressed={enabled}
            title={`${enabled ? "停用" : "激活"}${label}`}
            disabled={
              busy ||
              !snapshot.allowed_actions.includes("edit_keyframe_references")
            }
            onClick={onToggle}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="8.5" />
              <path d="M8.5 12.2l2.2 2.2 4.8-5" />
            </svg>
          </button>
        </div>
      </div>
      {!enabled ? (
        <small className="keyframe-disabled-note">
          未激活 · 不参与 Agent 与视频输入
        </small>
      ) : null}
      {selected !== null ? (
        <ZoomableImage
          className="keyframe-selected-image"
          src={selected.content_url}
          alt={`${label} @${selected.id.slice(0, 6)}`}
        />
      ) : active !== undefined ? (
        <div className="keyframe-empty-preview is-working">
          <span>{active.message}</span>
          <progress value={active.progress} max={1} />
        </div>
      ) : (
        <div className="keyframe-empty-preview">
          <b>＋</b>
          <span>尚未选择候选</span>
        </div>
      )}
      <p>
        {relation} · @{keyframe.id.slice(0, 6)}
      </p>
      <button
        type="button"
        className="keyframe-manual-editor-trigger"
        disabled={busy || !enabled}
        onClick={() => setEditorOpen(true)}
      >
        <span aria-hidden="true">▶</span>
        {keyframe.prompt_text.trim() ? "手动修改关键帧计划" : "填写关键帧计划"}
      </button>
      {editorOpen
        ? createPortal(
            <div
              className="scene-submission-preview-backdrop"
              onClick={(event) => {
                if (event.target === event.currentTarget) closeEditor();
              }}
            >
              <section
                className="scene-submission-preview-dialog keyframe-plan-dialog"
                role="dialog"
                aria-modal="true"
                aria-label={`手动修改${label}关键帧计划`}
                onKeyDown={(event) => {
                  if (event.key === "Escape") closeEditor();
                }}
              >
                <header>
                  <div>
                    <p className="eyebrow">Manual keyframe plan</p>
                    <h2>{label} · 手动关键帧计划</h2>
                  </div>
                  <button
                    autoFocus
                    type="button"
                    className="secondary-button"
                    onClick={closeEditor}
                  >
                    关闭
                  </button>
                </header>
                {protectedPlan.conflict ? (
                  <p role="alert">
                    关键帧计划已更新，输入已保留。请关闭并重新打开最新计划后修改。
                  </p>
                ) : null}
                <KeyframeEnvironmentFields
                  snapshot={snapshot}
                  ownerSegmentId={keyframe.owner_segment_id}
                  mode={environmentMode}
                  viewId={environmentViewId}
                  noneReason={environmentNoneReason}
                  noneReasonInvalid={noneReasonInvalid}
                  disabled={busy || !enabled}
                  onChange={setEnvironment}
                />
                <section className="keyframe-effective-reference-section">
                  <div>
                    <h3>当前实际图片输入</h3>
                    <p>
                      这里合并 Agent 计划、Core
                      自动引用与手工辅助图；下方实际提交顺序与 Provider
                      完全一致。
                    </p>
                  </div>
                  {effectivePreview?.error ? (
                    <p className="reference-error" role="alert">
                      {effectivePreview.error}
                    </p>
                  ) : effectivePreview?.data === null ||
                    effectivePreview === null ? (
                    <p className="muted-copy">正在更新实际图片输入…</p>
                  ) : effectivePreview.data.attachments.length === 0 ? (
                    <p className="muted-copy">本次不提交图片附件。</p>
                  ) : (
                    <div className="keyframe-effective-reference-grid">
                      {effectivePreview.data.attachments.map(
                        (attachment, index) => (
                          <figure
                            key={`${attachment.role}:${attachment.asset_id}`}
                          >
                            <ZoomableImage
                              src={attachment.content_url}
                              alt={`实际输入图${index + 1} ${attachment.display_name}`}
                            />
                            <figcaption>
                              <strong>
                                图{index + 1} · {attachment.display_name}
                              </strong>
                              <span>
                                {attachment.role === "source_image"
                                  ? "编辑底图"
                                  : "参考图"}{" "}
                                · {attachment.input_roles.join("、")}
                              </span>
                              <small>{attachment.purpose}</small>
                            </figcaption>
                          </figure>
                        ),
                      )}
                    </div>
                  )}
                </section>
                <section className="keyframe-manual-reference-section">
                  <div>
                    <h3>手工图片引用</h3>
                    <p>
                      从项目资产库选择真正交给生图工具的图片；本 Segment
                      的首尾帧共用这组辅助参考。
                    </p>
                  </div>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy || !enabled}
                    onClick={() => setReferencePickerOpen(true)}
                  >
                    {referenceAssetIds.length === 0
                      ? "从资产库选择图片"
                      : `调整已选的 ${referenceAssetIds.length} 张图片`}
                  </button>
                  {referenceAssetIds.length === 0 ? (
                    <p className="muted-copy">尚未手动选择图片。</p>
                  ) : (
                    <div className="scene-submission-attachments">
                      <div>
                        {referenceAssetIds.map((assetId, index) => {
                          const asset = assetById(snapshot.assets, assetId);
                          return asset === null ? null : (
                            <figure key={asset.id}>
                              <ZoomableImage
                                src={asset.content_url}
                                alt={`手工引用图${index + 1} ${asset.display_name ?? "项目图片"}`}
                              />
                              <figcaption>
                                <strong>
                                  图{index + 1} ·{" "}
                                  {asset.display_name ?? "项目图片"}
                                </strong>
                                <span>手工辅助参考</span>
                              </figcaption>
                            </figure>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy || !enabled || !referenceDirty}
                    onClick={onSaveReferences}
                  >
                    保存图片引用
                  </button>
                  {referencePickerOpen ? (
                    <MultiImageAssetPickerDialog
                      title="选择关键帧参考图片"
                      ariaLabel="从资产库选择关键帧参考图片"
                      assets={imageAssets(snapshot.assets, "keyframe")}
                      selectedAssetIds={referenceAssetIds}
                      maxSelected={4}
                      busy={busy || !enabled}
                      onClose={() => setReferencePickerOpen(false)}
                      onChange={onReferenceAssetIdsChange}
                    />
                  ) : null}
                </section>
                <fieldset className="character-checkboxes">
                  <legend>
                    本帧实际可见角色（Core 只提交下方为本帧选中的造型图）
                  </legend>
                  {snapshot.reference_library.characters.map((character) => (
                    <label key={character.id}>
                      <input
                        type="checkbox"
                        disabled={busy || !enabled}
                        checked={visibleCharacterIds.includes(character.id)}
                        onChange={() =>
                          setVisibleCharacterIds((current) =>
                            toggleId(current, character.id),
                          )
                        }
                      />
                      <span>{character.name}</span>
                    </label>
                  ))}
                </fieldset>
                {snapshot.reference_library.characters
                  .filter(
                    (character) =>
                      visibleCharacterIds.includes(character.id) &&
                      character.looks.length > 0,
                  )
                  .map((character) => (
                    <CharacterReferencePicker
                      key={character.id}
                      character={character}
                      snapshot={snapshot}
                      selection={
                        characterReferences.find(
                          (item) => item.character_id === character.id,
                        ) ?? null
                      }
                      disabled={busy || !enabled}
                      onChange={(lookId) =>
                        setCharacterLook(character, lookId)
                      }
                    />
                  ))}
                <ImagePromptEditorFields
                  referencePrompt={
                    effectivePreview !== null
                      ? (effectivePreview.data?.reference_prompt ??
                        effectivePreview.error ??
                        "正在更新图片引用…")
                      : "正在更新图片引用…"
                  }
                  promptLabel="静态画面提示词（自由编写）"
                  promptText={promptText}
                  promptPlaceholder="只描述这个时间边界的一张静态画面……"
                  onPromptChange={setPromptText}
                  disabled={busy || !enabled}
                />
                <div className="keyframe-plan-dialog-actions">
                  <button
                    type="button"
                    className="secondary-button scene-submission-preview-trigger"
                    disabled={!promptText.trim()}
                    onClick={() => setSubmissionPreviewOpen(true)}
                  >
                    最终完整提示词预览
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    disabled={
                      busy ||
                      protectedPlan.conflict ||
                      !snapshot.allowed_actions.includes(
                        "edit_keyframe_references",
                      ) ||
                      !enabled ||
                      !promptText.trim() ||
                      (promptText === keyframe.prompt_text &&
                        JSON.stringify(visibleCharacterIds) ===
                          JSON.stringify(keyframe.visible_character_ids) &&
                        JSON.stringify(characterReferences) ===
                          JSON.stringify(keyframe.character_references) &&
                        environmentMode === keyframe.environment_mode &&
                        environmentViewId === keyframe.environment_view_id &&
                        submittedNoneReason === keyframe.environment_none_reason &&
                        !referenceDirty) ||
                      noneReasonInvalid
                    }
                    onClick={() =>
                      onSave(
                        keyframe.id,
                        segmentId,
                        promptText.trim(),
                        visibleCharacterIds,
                        characterReferences,
                        referenceAssetIds,
                        environmentMode,
                        environmentViewId,
                        submittedNoneReason,
                      )
                    }
                  >
                    保存关键帧计划
                  </button>
                </div>
                {submissionPreviewOpen ? (
                  <ImageSubmissionPreviewDialog
                    preview={
                      effectivePreview !== null
                        ? effectivePreview
                        : {
                            key: previewKey,
                            inputKey: previewInputKey,
                            data: null,
                            error: null,
                          }
                    }
                    onClose={() => setSubmissionPreviewOpen(false)}
                  />
                ) : null}
              </section>
            </div>,
            document.body,
          )
        : null}
      <details className="keyframe-prompt">
        <summary>查看完整提示词与输入映射</summary>
        <small>
          本帧角色：{visibleNames.length > 0 ? visibleNames.join("、") : "无"}
        </small>
        <p>{latestGeneration?.prompt_text ?? keyframe.prompt_text}</p>
        {latestGeneration !== null ? (
          <div className="mention-assets">
            {latestGeneration.input_asset_ids.map((assetId, index) => {
              const input = assetById(snapshot.assets, assetId);
              return (
                <div key={assetId} className="generation-prompt-input">
                  {input !== null ? (
                    <ZoomableImage
                      src={input.content_url}
                      alt={`第 ${index + 1} 张生成输入图`}
                    />
                  ) : null}
                  <span>
                    第 {index + 1} 张 · @{assetId.slice(0, 6)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <small>
            尚未提交 Generation；生成后这里会显示 Core
            实际提交的完整提示词与输入顺序。
          </small>
        )}
      </details>
      {latestGeneration &&
      ["failed", "submission_uncertain"].includes(latestGeneration.phase) ? (
        <div role="alert">
          <strong>关键帧生成未完成</strong>
          <p>{latestGeneration.message}</p>
          {latestGeneration.allowed_actions.includes("dismiss_history") ? (
            <button
              disabled={busy}
              onClick={() => onDismiss(latestGeneration.id)}
            >
              删除这条失败记录
            </button>
          ) : null}
        </div>
      ) : null}
      {active && onCancel && active.allowed_actions.includes("cancel") ? (
        <button disabled={busy} onClick={() => onCancel(active.id)}>
          取消关键帧生成
        </button>
      ) : null}
      <GenerationCandidateList
        kind="keyframe"
        target={keyframe.id}
        assets={snapshot.assets}
        candidates={candidates}
        busy={busy}
        summary={`查看${label}候选（${candidates.length}）`}
        selectLabel="选择候选"
        selectedLabel="当前选择"
        onSelect={(generation) => {
          const asset = generation.output_asset_id ? assetById(snapshot.assets, generation.output_asset_id) : null;
          if (asset) onSelect(keyframe.id, asset.id);
        }}
        selectDisabled={(_, asset) =>
          busy ||
          enabled === false ||
          asset.id === keyframe.selected_asset_id ||
          snapshot.allowed_actions.includes("select_keyframe") === false
        }
        isSelected={(_, asset) => asset?.id === keyframe.selected_asset_id}
        onDismiss={(generationId) => onDismiss(generationId)}
        dismissLabel="隐藏候选卡片"
        dismissConfirmation="先隐藏候选；废弃产物可随后在资产中心永久清理。"
        dismissAllowed={(generation) => generation.allowed_actions.includes("dismiss_history") && enabled}
        renderCandidate={(_, asset) =>
          asset ? (
            <div className={`keyframe-candidate-preview${asset.id === keyframe.selected_asset_id ? " is-selected" : ""}`}>
              <ZoomableImage src={asset.content_url} alt={`候选 @${asset.id.slice(0, 6)}`} />
            </div>
          ) : null
        }
      />
      <div className="keyframe-library-picker">
        <button
          type="button"
          className="secondary-button"
          disabled={
            busy ||
            !enabled ||
            !snapshot.allowed_actions.includes("select_keyframe")
          }
          onClick={() => setLibraryOpen(true)}
        >
          从资产库选择关键帧
        </button>
        {libraryOpen ? (
          <SingleImageAssetPickerDialog
            title={`选择${label}`}
            ariaLabel={`从资产库选择${label}`}
            assets={imageAssets(snapshot.assets, "keyframe")}
            selectedAssetId={keyframe.selected_asset_id}
            busy={busy || !enabled}
            onClose={() => setLibraryOpen(false)}
            onSelect={(assetId) => {
              onSelect(keyframe.id, assetId);
              setLibraryOpen(false);
            }}
          />
        ) : null}
      </div>
      <button
        type="button"
        className="secondary-button"
        disabled={
          busy ||
          !enabled ||
          active !== undefined ||
          !keyframe.prompt_text.trim() ||
          !snapshot.allowed_actions.includes("generate_keyframe")
        }
        onClick={() => {
          if (snapshot.allowed_actions.includes("generate_keyframe"))
            onGenerate(keyframe.id);
        }}
      >
        {active !== undefined
          ? "生成中…"
          : candidates.length > 0
            ? "再生成一个候选"
            : "生成关键帧"}
      </button>
    </article>
  );
}

function CharacterReferencePicker({
  character,
  snapshot,
  selection,
  disabled,
  onChange,
}: {
  character: CharacterCard;
  snapshot: StructuredDirectorSnapshot;
  selection: KeyframeCharacterReference | null;
  disabled: boolean;
  onChange: (lookId: string | null) => void;
}) {
  // 未显式选择时：只有一套造型默认使用它；多套造型必须选择，否则 Core 拒绝生成。
  const looks = character.looks;
  const chosen =
    selection !== null ? selection.look_id : looks.length === 1 ? looks[0].id : undefined;
  const chosenLook = looks.find((item) => item.id === chosen);
  const status =
    selection === null && looks.length > 1
      ? "尚未选择：多套造型必须为本帧选择，否则无法生成"
      : chosen === null
        ? "本帧不提交该角色的图"
        : chosenLook !== undefined && chosenLook.selected_asset_id === null
          ? "所选造型尚未选定造型图，无法生成"
          : selection === null
            ? "默认使用唯一造型"
            : `已选造型「${chosenLook?.name ?? ""}」`;
  const name = `keyframe-look-${character.id}`;
  return (
    <fieldset className="keyframe-character-references">
      <legend>
        「{character.name}」本帧造型 · <small>{status}</small>
      </legend>
      <div className="keyframe-character-reference-grid">
        {looks.map((look) => {
          const asset =
            look.selected_asset_id === null ? null : assetById(snapshot.assets, look.selected_asset_id);
          const label = `造型「${look.name}」：${look.usage}`;
          return (
            <label key={look.id}>
              <input
                type="radio"
                name={name}
                disabled={disabled}
                checked={chosen === look.id}
                onChange={() => onChange(look.id)}
              />
              {asset !== null ? (
                <>
                  <img src={asset.content_url} alt={label} />
                  <ImageZoomButton src={asset.content_url} alt={label} />
                </>
              ) : (
                <span className="reference-thumbnail-missing">未选定造型图</span>
              )}
              <span>{label}</span>
            </label>
          );
        })}
        <label>
          <input
            type="radio"
            name={name}
            disabled={disabled}
            checked={chosen === null}
            onChange={() => onChange(null)}
          />
          <span>本帧不提交该角色的图</span>
        </label>
      </div>
    </fieldset>
  );
}

/** 弹窗中的地点视图选项：只列所属 Scene 绑定地点的视图；帧当前引用的其它地点视图作为当前值保留。 */
export function keyframeViewOptions(
  snapshot: StructuredDirectorSnapshot,
  ownerSegmentId: string,
  currentViewId: string | null,
) {
  const scene = snapshot.director_script?.scenes.find((item) =>
    item.shots.some((shot) =>
      shot.segments.some((segment) => segment.id === ownerSegmentId),
    ),
  );
  const shot = scene?.shots.find((item) =>
    item.segments.some((segment) => segment.id === ownerSegmentId),
  );
  const locations = snapshot.location_library.locations;
  const location =
    scene?.location_id == null
      ? null
      : (locations.find((item) => item.id === scene.location_id) ?? null);
  const describe = (
    owner: (typeof locations)[number],
    view: (typeof locations)[number]["views"][number],
  ) => ({
    id: view.id,
    name: view.name,
    purpose: view.purpose,
    locationName: owner.name,
    stateName:
      view.state_id === null
        ? null
        : (owner.states.find((item) => item.id === view.state_id)?.name ?? null),
    selected: view.selected_asset_id !== null,
    shotDefault: shot?.view_id === view.id,
  });
  const options = (location?.views ?? []).map((view) => describe(location!, view));
  let foreign: (ReturnType<typeof describe> & { ownLocation: false }) | null = null;
  if (currentViewId !== null && !options.some((item) => item.id === currentViewId)) {
    const owner = locations.find((item) =>
      item.views.some((view) => view.id === currentViewId),
    );
    const view = owner?.views.find((item) => item.id === currentViewId);
    if (owner !== undefined && view !== undefined)
      foreign = { ...describe(owner, view), ownLocation: false };
  }
  return { location, options, foreign };
}

function KeyframeEnvironmentFields({
  snapshot,
  ownerSegmentId,
  mode,
  viewId,
  noneReason,
  noneReasonInvalid,
  disabled,
  onChange,
}: {
  snapshot: StructuredDirectorSnapshot;
  ownerSegmentId: string;
  mode: KeyframeEnvironmentMode;
  viewId: string | null;
  noneReason: string;
  noneReasonInvalid: boolean;
  disabled: boolean;
  onChange: (
    environment: Partial<{
      environmentMode: KeyframeEnvironmentMode;
      environmentViewId: string | null;
      environmentNoneReason: string;
    }>,
  ) => void;
}) {
  const { location, options, foreign } = keyframeViewOptions(
    snapshot,
    ownerSegmentId,
    viewId,
  );
  const current =
    options.find((item) => item.id === viewId) ??
    (foreign?.id === viewId ? foreign : null);
  const optionLabel = (item: (typeof options)[number]) =>
    [
      item.name,
      item.purpose,
      item.stateName === null ? null : `状态「${item.stateName}」`,
      item.shotDefault ? "Shot 绑定" : null,
      item.selected ? null : "未选图，生成前需要选图",
    ]
      .filter((part) => part !== null && part !== "")
      .join(" · ");
  return (
    <fieldset className="keyframe-environment-fields">
      <legend>地点视图</legend>
      <label className="card-field">
        视图
        <select
          aria-label="地点视图"
          value={viewId ?? ""}
          disabled={disabled}
          onChange={(event) => {
            const next = event.target.value || null;
            onChange(
              next === null
                ? { environmentViewId: null, environmentMode: "none" }
                : {
                    environmentViewId: next,
                    // 从 none 选回视图时默认作为空间参考。
                    environmentMode: mode === "none" ? "reference" : mode,
                  },
            );
          }}
        >
          <option value="">不使用地点视图</option>
          {foreign !== null ? (
            <option value={foreign.id}>
              当前值（来自地点「{foreign.locationName}」，不属于本 Scene 地点）·{" "}
              {optionLabel(foreign)}
            </option>
          ) : null}
          {options.map((item) => (
            <option key={item.id} value={item.id}>
              {optionLabel(item)}
            </option>
          ))}
        </select>
        <small>
          {location === null
            ? "本 Scene 尚未绑定地点，没有可选视图；可先在地点库绑定，或选择不使用。"
            : `只列出本 Scene 地点「${location.name}」的视图。`}
          {current !== null && !current.selected
            ? ` 视图「${current.name}」未选图，生成前需要选图。`
            : ""}
          {foreign !== null
            ? ` 当前视图来自地点「${foreign.locationName}」（例如 Scene 后来改绑），保存时保持原值，除非重新选择。`
            : ""}
        </small>
      </label>
      <label className="card-field">
        使用方式
        <select
          aria-label="地点视图使用方式"
          value={mode}
          disabled={disabled}
          onChange={(event) => {
            const next = event.target.value as KeyframeEnvironmentMode;
            onChange(
              next === "none"
                ? { environmentMode: "none", environmentViewId: null }
                : { environmentMode: next },
            );
          }}
        >
          <option value="edit" disabled={viewId === null}>
            编辑底图（edit）
          </option>
          <option value="reference" disabled={viewId === null}>
            仅作参考（reference）
          </option>
          <option value="none">不使用（none）</option>
        </select>
        <small>
          默认 reference：视图只作空间参考，只参考固定陈设的方位关系、空间布局、材质与主光方向，
          不照搬该图的机位与构图；可按本帧朝向改选本地点的其它视图；需要画面严格贴合视图时选编辑底图（edit）；
          没有合适视图或画面没有环境信息时选不使用（理由可选）。
        </small>
      </label>
      {mode === "none" ? (
        <label className="card-field">
          不使用地点视图的理由（可选）
          <textarea
            aria-label="不使用地点视图的理由"
            aria-invalid={noneReasonInvalid}
            maxLength={500}
            rows={2}
            value={noneReason}
            disabled={disabled}
            onChange={(event) =>
              onChange({ environmentNoneReason: event.target.value })
            }
          />
          {noneReasonInvalid ? (
            <small role="alert">理由最多 500 字。</small>
          ) : null}
        </label>
      ) : null}
    </fieldset>
  );
}
