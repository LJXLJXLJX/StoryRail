import { stableStringify, useProtectedValue } from "./draft_protection";
import { useEffect, useState } from "react";
import {
  RecipeInputsControl,
  recipeInputsError,
  completeProjectRecipeInputs,
  useSegmentVideoDraft,
} from "./RecipeInputsControl";
import type {
  RecipeInputs,
  VideoRecipeState,
  ShotSegment,
  StructuredDirectorSnapshot,
} from "../api";
import { isVideoSeed } from "../api";
import {
  formatSamplingDuration,
  generationPhaseLabel,
  useSamplingTelemetry,
} from "./generation";
import {
  DirectorDisclosure,
  GenerationCandidateList,
  SingleVideoAssetPickerDialog,
  VideoFrameExtractDialog,
  type VideoFrameInfo,
  assetById,
} from "./shared";
export function SegmentVideoPanel({
  snapshot,
  segment,
  busy,
  dependenciesEditable,
  preparing,
  hideReferenceImageSlots = false,
  onSave,
  onPreview,
  onSaveRecipe,
  onExtractVideoFrame,
  onLoadVideoFrameInfo,
  onGenerate,
  onAttachCandidate,
  onSelect,
  onClearSelection,
  onDismiss,
  onCancel,
  onUpscale,
}: {
  snapshot: StructuredDirectorSnapshot;
  segment: ShotSegment;
  busy: boolean;
  dependenciesEditable: boolean;
  preparing: boolean;
  hideReferenceImageSlots?: boolean;
  onPreview?: (
    segmentId: string,
    inputs: RecipeInputs,
  ) => Promise<VideoRecipeState>;
  onSave: (segmentId: string, promptText: string, inputs: RecipeInputs) => void;
  onSaveRecipe: (segmentId: string, recipeId: string) => void;
  onExtractVideoFrame?: (assetId: string, frameIndex: number) => void;
  onLoadVideoFrameInfo?: (assetId: string) => Promise<VideoFrameInfo>;
  onGenerate: (segmentId: string, seed?: string) => void;
  onAttachCandidate: (segmentId: string, assetId: string) => void;
  onSelect: (segmentId: string, assetId: string) => void;
  onClearSelection: (segmentId: string) => void;
  onDismiss: (generationId: string) => void;
  onCancel?: (generationId: string) => void;
  onUpscale: (segmentId: string) => void;
}) {
  const segmentId = segment.id;
  const plan = snapshot.video_plan?.segments.find(
    (item) => item.segment_id === segmentId,
  );
  const sharedDraft = useSegmentVideoDraft();
  const localPromptDraft = useProtectedValue(plan?.prompt_text ?? "");
  const {
    value: draftPrompt,
    setValue: setDraftPrompt,
    conflict: promptConflict,
    reset: resetPrompt,
  } = sharedDraft?.segmentId === segmentId
    ? sharedDraft.prompt
    : localPromptDraft;
  const recipeView = snapshot.provider_recipes?.find(
    (item) => item.recipe.id === plan?.active_recipe,
  );
  const recipe = recipeView?.recipe;
  const savedInputs = plan?.active_recipe
    ? (plan.recipes[plan.active_recipe] ?? { bindings: {}, params: {} })
    : { bindings: {}, params: {} };
  const localInputsDraft = useProtectedValue(savedInputs);
  const {
    value: draftInputs,
    setValue: setDraftInputs,
    conflict: inputsConflict,
    reset: resetInputs,
  } = sharedDraft?.segmentId === segmentId
    ? sharedDraft.inputs
    : localInputsDraft;
  const [preview, setPreview] = useState<VideoRecipeState | undefined>(
    plan?.recipe_state,
  );
  const [previewError, setPreviewError] = useState<string | null>(null);
  const inputsDigest = stableStringify(draftInputs);
  useEffect(() => {
    if (!onPreview) {
      setPreview(plan?.recipe_state);
      return;
    }
    let stale = false;
    const timer = setTimeout(() => {
      void onPreview(segmentId, draftInputs)
        .then((state) => {
          if (!stale) {
            setPreview(state);
            setPreviewError(null);
          }
        })
        .catch((error: unknown) => {
          if (!stale)
            setPreviewError(
              error instanceof Error ? error.message : "输入预览暂时不可用。",
            );
        });
    }, 150);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [inputsDigest, snapshot.revision, segmentId, onPreview]);
  const [draftSeed, setDraftSeed] = useState("");
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const [frameDialogOpen, setFrameDialogOpen] = useState(false);
  const normalizedSeed = draftSeed.trim();
  const seedValid = normalizedSeed === "" || isVideoSeed(normalizedSeed);
  const latestVideoGenerationId = snapshot.generations
    .filter(
      (item) => item.kind === "segment_video" && item.target_id === segmentId,
    )
    .at(-1)?.id;
  useEffect(() => {
    setDraftSeed("");
  }, [segmentId, latestVideoGenerationId]);
  const selectedId = plan?.upscaled_asset_id ?? plan?.selected_asset_id ?? null;
  const selected =
    selectedId === null ? null : assetById(snapshot.assets, selectedId);
  const generations = snapshot.generations.filter(
    (item) =>
      item.kind === "segment_video" &&
      item.target_id === segmentId &&
      !item.dismissed,
  );
  const active = generations.find(
    (item) =>
      item.phase === "submitting" ||
      item.phase === "queued" ||
      item.phase === "running",
  );
  const samplingTelemetry = useSamplingTelemetry(active);
  const latestVideoGeneration = generations.at(-1);
  const latestFailure =
    latestVideoGeneration?.phase === "failed" ||
    latestVideoGeneration?.phase === "submission_uncertain"
      ? latestVideoGeneration
      : undefined;
  const upscaleGenerations = snapshot.generations.filter(
    (item) =>
      item.kind === "video_upscale" &&
      item.target_id === segmentId &&
      !item.dismissed,
  );
  const activeUpscale = upscaleGenerations.find(
    (item) =>
      item.phase === "submitting" ||
      item.phase === "queued" ||
      item.phase === "running",
  );
  const candidates = generations.filter(
    (item) => item.phase === "succeeded" && item.output_asset_id !== null,
  );
  const selectedFrameGeneration =
    selected === null
      ? null
      : ([...snapshot.generations]
          .reverse()
          .find(
            (item) =>
              item.kind === "video_frame" &&
              item.target_id === selected.id &&
              !item.dismissed,
          ) ?? null);
  const selectedFrameInProgress =
    selectedFrameGeneration !== null &&
    (selectedFrameGeneration.phase === "submitting" ||
      selectedFrameGeneration.phase === "queued" ||
      selectedFrameGeneration.phase === "running");
  const selectedFrameFailed =
    selectedFrameGeneration !== null &&
    (selectedFrameGeneration.phase === "failed" ||
      selectedFrameGeneration.phase === "submission_uncertain");
  const candidateAssetIds = candidates.flatMap((item) =>
    item.output_asset_id === null ? [] : [item.output_asset_id],
  );
  const compatibleVideoAssets = snapshot.assets.filter(
    (asset) =>
      asset.media_type === "video/mp4" &&
      asset.duration_seconds !== null &&
      asset.duration_seconds >= 0.2,
  );
  const mode = recipe?.label ?? plan?.active_recipe ?? "请选择视频 recipe";
  const binding = snapshot.keyframe_plan?.segments.find(
    (item) => item.segment_id === segmentId,
  );
  const startKeyframe = snapshot.keyframe_plan?.keyframes.find(
    (item) => item.id === binding?.start_keyframe_id,
  );
  const endKeyframe = snapshot.keyframe_plan?.keyframes.find(
    (item) => item.id === binding?.end_keyframe_id,
  );
  const startAsset =
    !binding?.start_enabled ||
    startKeyframe?.selected_asset_id === null ||
    startKeyframe?.selected_asset_id === undefined
      ? null
      : assetById(snapshot.assets, startKeyframe.selected_asset_id);
  const endAsset =
    !binding?.end_enabled ||
    endKeyframe?.selected_asset_id === null ||
    endKeyframe?.selected_asset_id === undefined
      ? null
      : assetById(snapshot.assets, endKeyframe.selected_asset_id);
  const submitDuration =
    plan?.recipe_state?.duration_seconds ?? segment.duration_estimate_seconds;
  const softLimit = plan?.recipe_state?.soft_duration_limit_seconds;
  const promptDirty = plan !== undefined && draftPrompt !== plan.prompt_text;
  const referencesDirty =
    stableStringify(draftInputs) !== stableStringify(savedInputs);
  const planDirty = promptDirty || referencesDirty;
  const inputsError = recipe
    ? recipeInputsError(recipe, draftInputs)
    : "当前视频 recipe 不可用。";
  const canGenerate =
    plan !== undefined &&
    preview?.ready === true &&
    draftPrompt.trim().length > 0 &&
    seedValid &&
    inputsError === null;
  const frameSummary =
    startAsset !== null && endAsset !== null
      ? "首帧 + 尾帧"
      : startAsset !== null
        ? "仅首帧"
        : endAsset !== null
          ? "仅尾帧"
          : "尚未选择";
  return (
    <DirectorDisclosure
      className={`segment-video-panel${plan === undefined ? " is-unplanned" : ""}`}
    >
      <summary
        className="segment-layer-summary"
        aria-label={`Segment @${segmentId.slice(0, 6)} 视频`}
      >
        <div>
          <p className="eyebrow">Segment video</p>
          <h4>{mode}</h4>
        </div>
        <span>
          {plan === undefined
            ? "计划待重建"
            : plan.upscaled_asset_id === null
              ? "原始视频"
              : "已超分"}
        </span>
      </summary>
      <div className="segment-video-inputs">
        <article className="segment-video-mode">
          <strong>生成模式</strong>
          <select
            aria-label={`Segment @${segmentId.slice(0, 6)} 生成模式`}
            value={plan?.active_recipe ?? ""}
            disabled={
              busy ||
              active !== undefined ||
              planDirty ||
              plan === undefined ||
              !dependenciesEditable
            }
            onChange={(event) => onSaveRecipe(segmentId, event.target.value)}
          >
            {!plan?.recipe_state?.available ? (
              <option value={plan?.active_recipe ?? ""}>{mode}</option>
            ) : null}
            {preview?.options.map((option) => (
              <option
                key={option.id}
                value={option.id}
                disabled={!option.allowed}
              >
                {option.label}
              </option>
            ))}
          </select>
          {preview?.options
            .filter((option) => !option.allowed)
            .map((option) => (
              <small key={option.id}>{option.reason}</small>
            ))}
          {preview?.reason ? (
            <small>{preview.reason}</small>
          ) : null}
        </article>
        <article>
          <strong>画面约束</strong>
          <span>{frameSummary}</span>
          <small>关键帧图片保留在上方画面输入卡中。</small>
        </article>
        <article className="segment-video-runtime">
          <strong>本次生成</strong>
          <span>
            {submitDuration.toFixed(1)} 秒 · {snapshot.aspect_ratio}
          </span>
          <small>
            脚本预估 {segment.duration_estimate_seconds.toFixed(1)} 秒
          </small>
          {softLimit !== null &&
          softLimit !== undefined &&
          segment.duration_estimate_seconds > softLimit ? (
            <em>超过 {softLimit} 秒软约束，可能 OOM；仍可生成</em>
          ) : null}
        </article>
      </div>
      {recipe ? (
        <div
          className="segment-video-recipe-inputs"
          aria-label={`${recipe.label} 媒体输入`}
        >
          <RecipeInputsControl
            recipe={recipe}
            value={draftInputs}
            state={preview}
            dialogueAudio={plan?.recipe_state?.dialogue_audio ?? null}
            snapshot={snapshot}
            boundaryAssets={{
              first_frame: startAsset?.id ?? null,
              last_frame: endAsset?.id ?? null,
            }}
            disabled={busy || active !== undefined || !dependenciesEditable}
            hiddenRoles={hideReferenceImageSlots ? ["reference_image"] : []}
            onChange={setDraftInputs}
          />
        </div>
      ) : null}
      {previewError ? <p role="alert">{previewError}</p> : null}
      {inputsError ? <p role="alert">{inputsError}</p> : null}
      {promptConflict || inputsConflict ? (
        <p role="alert">
          视频计划已更新，未保存输入已保留。请先复制需要的内容并取消修改，再编辑最新版本。
        </p>
      ) : null}
      <details className="story-prompt-editor">
        <summary>查看或编辑 视频提示词</summary>
        <label className="card-field segment-video-prompt">
          <span>当前 视频提示词</span>
          <textarea
            value={draftPrompt}
            aria-label="当前 视频提示词"
            readOnly={!dependenciesEditable}
            disabled={busy || active !== undefined || plan === undefined}
            placeholder={
              plan === undefined
                ? "当前脚本 revision 的视频计划尚未重建。"
                : undefined
            }
            onChange={(event) => setDraftPrompt(event.target.value)}
          />
          {!dependenciesEditable ? (
            <small>当前没有编辑视频计划权限。</small>
          ) : (
            <small>修改后在本视频卡内保存；脚本在当前节点独立编辑。</small>
          )}
        </label>
      </details>
      <label className="card-field segment-video-seed">
        <span>本次 Seed（留空自动递增）</span>
        <input
          type="text"
          inputMode="numeric"
          value={draftSeed}
          maxLength={19}
          aria-label="本次 Seed（留空自动递增）"
          placeholder="自动递增"
          disabled={busy || active !== undefined || plan === undefined}
          aria-invalid={!seedValid}
          onChange={(event) => setDraftSeed(event.target.value)}
        />
        <small>
          {seedValid
            ? "手动填写用于本次生成；后续自动从上次实际 Seed 继续递增。"
            : "请输入 0 到 9223372036854775807 的整数。"}
        </small>
      </label>

      {!draftPrompt.trim() ? (
        <p className="segment-video-notice">
          请填写并保存当前 视频提示词，或通过外部 Agent 提交专业提示词
          proposal。
        </p>
      ) : planDirty ? (
        <p className="segment-video-notice">
          {promptDirty && !referencesDirty
            ? "当前提示词有未保存修改，请先保存视频计划再生成。"
            : "当前视频计划有未保存修改，请先保存再生成。"}
        </p>
      ) : null}
      {plan === undefined ? (
        <p className="segment-video-notice">
          之前的视频层仍然保留显示，但当前脚本 revision
          已使计划失效。重新审核关键帧并进入视频生产后可继续编辑。
        </p>
      ) : null}
      {planDirty && selected !== null ? (
        <p className="segment-video-notice">
          保存新提示词会取消当前视频和超分选择；历史候选与 Asset 仍会保留。
        </p>
      ) : null}
      <div className="segment-video-plan-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={
            busy ||
            !dependenciesEditable ||
            promptConflict ||
            inputsConflict ||
            active !== undefined ||
            !planDirty ||
            inputsError !== null ||
            (promptDirty && !draftPrompt.trim()) ||
            !snapshot.allowed_actions.includes("edit_segment_video_plan")
          }
          onClick={() =>
            onSave(
              segmentId,
              draftPrompt.trim(),
              recipe
                ? completeProjectRecipeInputs(recipe, draftInputs)
                : draftInputs,
            )
          }
        >
          保存视频计划
        </button>
        {planDirty ? (
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => {
              if (window.confirm("放弃未保存的 视频计划修改？")) {
                resetPrompt();
                resetInputs();
              }
            }}
          >
            取消计划修改
          </button>
        ) : null}
      </div>
      {preparing && active === undefined ? (
        <div className="video-working" aria-live="polite">
          <div className="loading-rail">
            <span />
          </div>
          <strong>正在准备 Generation</strong>
          <p>
            正在校验生成模式、关键帧与参考输入，并使用已保存的当前视频
            提示词提交视频任务。
          </p>
          <small>
            完成后会创建 Generation、提交
            Provider，并在这里继续显示真实执行进度。
          </small>
        </div>
      ) : active !== undefined ? (
        <div className="video-working" aria-live="polite">
          <div className="video-progress-track" aria-hidden="true">
            <span style={{ width: `${Math.round(active.progress * 100)}%` }} />
          </div>
          <div className="video-progress-heading">
            <strong>{generationPhaseLabel(active.phase)}</strong>
            <b>{Math.round(active.progress * 100)}%</b>
          </div>
          {samplingTelemetry !== null ? (
            <div className="video-sampling-telemetry" aria-label="视频采样性能">
              <span>
                <small>采样</small>
                <strong>
                  {samplingTelemetry.completed}/{samplingTelemetry.total}
                </strong>
              </span>
              <span>
                <small>速度</small>
                <strong>
                  {samplingTelemetry.secondsPerIteration === null
                    ? "测速中…"
                    : `${samplingTelemetry.secondsPerIteration.toFixed(2)} s/iter`}
                </strong>
              </span>
              <span>
                <small>预计剩余</small>
                <strong>
                  {samplingTelemetry.completed >= samplingTelemetry.total
                    ? "采样完成"
                    : samplingTelemetry.remainingSeconds === null
                      ? "测速中…"
                      : formatSamplingDuration(
                          samplingTelemetry.remainingSeconds,
                        )}
                </strong>
              </span>
            </div>
          ) : null}
          <p>{active.message}</p>
          {onCancel && active.allowed_actions.includes("cancel") ? (
            <button disabled={busy} onClick={() => onCancel(active.id)}>
              取消视频生成
            </button>
          ) : null}
          <small>
            {mode} · {submitDuration.toFixed(1)} 秒 · {snapshot.aspect_ratio}
          </small>
        </div>
      ) : selected !== null ? (
        <div className="selected-segment-video">
          <video
            controls
            preload="metadata"
            playsInline
            muted={false}
            src={selected.content_url}
          />
          <button
            type="button"
            className="text-button"
            disabled={
              busy ||
              active !== undefined ||
              !snapshot.allowed_actions.includes("select_segment_video")
            }
            onClick={() => onClearSelection(segmentId)}
          >
            撤销当前视频选择
          </button>
          {onExtractVideoFrame !== undefined ? (
            <>
              <button
                type="button"
                className="secondary-button"
                disabled={
                  busy ||
                  selectedFrameInProgress ||
                  !selected.allowed_actions.includes("video_frame")
                }
                title={
                  selected.allowed_actions.includes("video_frame")
                    ? "在 Mac 本地按帧号提取当前已选视频的一帧，生成独立 PNG Asset"
                    : "当前项目状态或本地抽帧服务暂不允许抽帧"
                }
                onClick={() => setFrameDialogOpen(true)}
              >
                {selectedFrameInProgress
                  ? "正在抽帧…"
                  : selectedFrameFailed
                    ? "重新抽帧"
                    : "从当前视频抽帧"}
              </button>
              {frameDialogOpen && onLoadVideoFrameInfo !== undefined ? (
                <VideoFrameExtractDialog
                  videoUrl={selected.content_url}
                  title="从当前视频抽帧"
                  description="抽出的 PNG 进入资产中心“抽帧图”，不会自动绑定到任何关键帧。"
                  busy={busy}
                  loadInfo={() => onLoadVideoFrameInfo(selected.id)}
                  onClose={() => setFrameDialogOpen(false)}
                  onConfirm={(frameIndex) => {
                    setFrameDialogOpen(false);
                    onExtractVideoFrame(selected.id, frameIndex);
                  }}
                />
              ) : null}
              {selectedFrameFailed ? (
                <small className="video-generation-error" role="status">
                  {selectedFrameGeneration.phase === "submission_uncertain"
                    ? "上次提交没有建立可恢复任务："
                    : "抽帧失败："}
                  {selectedFrameGeneration.message ||
                    selectedFrameGeneration.error_code ||
                    "请重试"}
                </small>
              ) : selectedFrameInProgress ? (
                <small className="video-working" role="status">
                  {selectedFrameGeneration.message ||
                    "正在本地抽取，完成后会出现在资产中心的“图片”页。"}
                </small>
              ) : null}
            </>
          ) : null}
        </div>
      ) : (
        <div className="video-empty">尚未选择视频候选</div>
      )}
      {active === undefined && latestFailure !== undefined ? (
        <div className="video-generation-error" role="alert">
          <strong>
            {latestFailure.phase === "submission_uncertain"
              ? "未能连接视频生成服务"
              : "视频生成失败"}
          </strong>
          <p>{latestFailure.message}</p>
          <small>
            本次没有生成视频 · Seed {latestFailure.seed ?? "未记录"}
          </small>
          {latestFailure.seed !== null ? (
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => setDraftSeed(String(latestFailure.seed))}
            >
              将此 Seed 填回输入框
            </button>
          ) : null}
          {latestFailure.allowed_actions.includes("dismiss_history") ? (
            <button
              type="button"
              className="text-button"
              disabled={busy}
              onClick={() => onDismiss(latestFailure.id)}
            >
              删除这条失败记录
            </button>
          ) : null}
        </div>
      ) : null}
      <GenerationCandidateList
        kind="video"
        target={segmentId}
        assets={snapshot.assets}
        candidates={candidates}
        busy={busy}
        summary={`查看视频候选（${candidates.length}）`}
        selectLabel="选择候选"
        selectedLabel="当前选择"
        onSelect={(generation) => {
          const asset = generation.output_asset_id
            ? assetById(snapshot.assets, generation.output_asset_id)
            : null;
          if (asset) onSelect(segmentId, asset.id);
        }}
        selectDisabled={(generation, asset) =>
          busy ||
          active !== undefined ||
          asset.id === plan?.selected_asset_id ||
          generation.allowed_actions.includes("select_segment_video") === false
        }
        isSelected={(_, asset) => asset?.id === plan?.selected_asset_id}
        onDismiss={(generationId) => onDismiss(generationId)}
        dismissLabel="隐藏历史"
        dismissAllowed={(generation) =>
          generation.allowed_actions.includes("dismiss_history")
        }
        renderCandidate={(generation, asset) => (
          <section className="video-candidate">
            {asset ? (
              <video
                controls
                preload="metadata"
                playsInline
                muted={false}
                src={asset.content_url}
              />
            ) : null}
            <small>Seed：{generation.seed ?? "未记录"}</small>
            <p>{generation.message}</p>
            {generation.inputs_outdated ? (
              <p className="segment-video-notice">
                该候选生成时的关键帧、视频提示词或参考输入与当前计划不同。仍然可以选择，成片会直接使
                用这条视频；如需与当前计划一致请重新生成。
              </p>
            ) : null}
            {typeof generation.seed === "string" ? (
              <button
                type="button"
                className="text-button"
                disabled={busy || active !== undefined}
                onClick={() => setDraftSeed(String(generation.seed))}
              >
                使用此 Seed
              </button>
            ) : null}
          </section>
        )}
      />
      <button
        type="button"
        className="primary-button"
        disabled={
          busy ||
          active !== undefined ||
          !canGenerate ||
          planDirty ||
          !snapshot.allowed_actions.includes("generate_segment_video")
        }
        onClick={() => onGenerate(segmentId, normalizedSeed || undefined)}
      >
        {active === undefined ? "生成一个视频候选" : "视频生成中…"}
      </button>
      <button
        type="button"
        className="secondary-button"
        disabled={
          busy ||
          active !== undefined ||
          plan === undefined ||
          !snapshot.allowed_actions.includes("attach_segment_video_candidate")
        }
        onClick={() => setAssetPickerOpen(true)}
      >
        从资产库增加候选
      </button>
      {assetPickerOpen ? (
        <SingleVideoAssetPickerDialog
          assets={compatibleVideoAssets}
          attachedAssetIds={candidateAssetIds}
          busy={busy}
          onClose={() => setAssetPickerOpen(false)}
          onSelect={(assetId) => {
            onAttachCandidate(segmentId, assetId);
            setAssetPickerOpen(false);
          }}
        />
      ) : null}
      {activeUpscale !== undefined ? (
        <div className="video-working" aria-live="polite">
          <div className="loading-rail">
            <span />
          </div>
          <p>{activeUpscale.message}</p>
          {onCancel && activeUpscale.allowed_actions.includes("cancel") ? (
            <button disabled={busy} onClick={() => onCancel(activeUpscale.id)}>
              取消超分
            </button>
          ) : null}
          <strong>{Math.round(activeUpscale.progress * 100)}%</strong>
        </div>
      ) : null}
      <button
        type="button"
        className="secondary-button"
        disabled={
          busy ||
          plan?.selected_asset_id === null ||
          plan?.selected_asset_id === undefined ||
          plan?.upscaled_asset_id !== null ||
          activeUpscale !== undefined ||
          !snapshot.provider_availability.video_upscale ||
          !snapshot.allowed_actions.includes("upscale_segment_video")
        }
        onClick={() => onUpscale(segmentId)}
      >
        {plan?.upscaled_asset_id !== null &&
        plan?.upscaled_asset_id !== undefined
          ? "已超分"
          : activeUpscale !== undefined
            ? "超分处理中…"
            : "使用 SeedVR2 超分"}
      </button>
    </DirectorDisclosure>
  );
}
