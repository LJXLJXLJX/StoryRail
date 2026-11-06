import type { StructuredDirectorSnapshot } from "../api";

import { NARRATION_LANGUAGE_LABELS } from "./narration";
import { assetById, GenerationCandidateList } from "./shared";

export function FinalAssemblyWorkspace({
  snapshot,
  busy,
  pending,
  error,
  onGenerate,
  onSelect,
  onClearSelection,
  onApprove,
  onReopen,
  onDismiss,
  onCancel,
}: {
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  pending: string | null;
  error: string | null;
  onGenerate: () => void;
  onSelect: (generationId: string) => void;
  onClearSelection?: () => void;
  onApprove: () => void;
  onReopen?: () => void;
  onDismiss: (generationId: string) => void;
  onCancel?: (generationId: string) => void;
}) {
  const plan = snapshot.final_assembly;
  if (plan === null || plan === undefined) return null;
  const generations = snapshot.generations.filter(
    (item) => item.kind === "final_video" && !item.dismissed,
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
  // 中英两个单语成片共用画面，各自选择候选；一次 Approval 同时批准两版。
  const languages = snapshot.narration_languages.map((language) => {
    const selectedAssetId =
      language === "zh" ? plan.selected_zh_asset_id : plan.selected_en_asset_id;
    return {
      language,
      label: NARRATION_LANGUAGE_LABELS[language],
      selectedAssetId,
      selected: selectedAssetId === null ? null : assetById(snapshot.assets, selectedAssetId),
      candidates: candidates.filter((item) => item.language === language),
      active: generations.find(
        (item) =>
          item.language === language &&
          (item.phase === "submitting" || item.phase === "queued" || item.phase === "running"),
      ),
    };
  });
  const anySelected = languages.some((item) => item.selected !== null);
  const allSelected = languages.every((item) => item.selected !== null);
  const approval = snapshot.final_approval;
  const seamBlends = plan.clips.filter(
    (item) => item.transition_from_previous === "seam_blend",
  ).length;
  const hardCuts = plan.clips.filter(
    (item) => item.transition_from_previous === null && item !== plan.clips[0],
  ).length;
  const narrationCueCount =
    snapshot.director_script?.scenes.reduce(
      (total, scene) => total + scene.narration_cues.length,
      0,
    ) ?? 0;
  const sceneLabels = new Map<string, string>();
  snapshot.director_script?.scenes.forEach((scene, sceneIndex) => {
    sceneLabels.set(scene.id, `Scene ${sceneIndex + 1} · ${scene.title}`);
  });
  const sceneNarration = new Map<string, number>();
  snapshot.director_script?.scenes.forEach((scene) =>
    sceneNarration.set(scene.id, scene.narration_cues.length),
  );

  return (
    <section className="final-assembly-workspace" id="final-assembly">
      <header>
        <p className="eyebrow">Final assembly</p>
        <h1>最终成片装配</h1>
        <p>
          按结构化脚本顺序拼接已审核的 Scene 成片，分别产出中文版与英文版两个单语成片，
          画面一致、只换旁白。这个步骤不再读取原始 Segment 或旁白：Scene 内的转场与旁白已经
          固化在成片里，跨 Scene 只有共享同一边界关键帧时才做短接缝融合。
        </p>
      </header>
      <div className="final-assembly-summary">
        <article>
          <strong>{plan.clips.length}</strong>
          <span>Scene 成片</span>
        </article>
        <article>
          <strong>{seamBlends}</strong>
          <span>接缝融合</span>
        </article>
        <article>
          <strong>{hardCuts}</strong>
          <span>硬切</span>
        </article>
        <article>
          <strong>{narrationCueCount}</strong>
          <span>旁白 Cue（已含在成片内）</span>
        </article>
      </div>
      <details className="final-assembly-timeline">
        <summary>查看装配时间线</summary>
        <ol>
          {plan.clips.map((clip, index) => (
            <li key={clip.scene_id}>
              <strong>
                {sceneLabels.get(clip.scene_id) ?? clip.scene_id}
              </strong>
              <span>
                {index === 0
                  ? "成片起点"
                  : clip.transition_from_previous === "seam_blend"
                    ? "从上一 Scene 接缝融合"
                    : "从上一 Scene 硬切"}
              </span>
              <span>
                {(sceneNarration.get(clip.scene_id) ?? 0) > 0
                  ? `含 ${sceneNarration.get(clip.scene_id)} 条旁白`
                  : "无旁白"}
              </span>
            </li>
          ))}
        </ol>
      </details>

      {approval !== null ? (
        <section className="final-approval-summary">
          <p className="eyebrow">Approved</p>
          <h2>{snapshot.narration_languages.length === 2 ? "中英成片已批准" : "成片已批准"}</h2>
          <p>
            Approval 绑定脚本 revision {approval.source_script_revision}、项目
            revision {approval.approved_project_revision}；
            {snapshot.narration_languages.map((language) => `${NARRATION_LANGUAGE_LABELS[language]} Generation @${(language === "zh" ? approval.zh_generation_id : approval.en_generation_id)?.slice(0, 6)}`).join("、")}。
          </p>
          {onReopen !== undefined &&
          snapshot.allowed_actions.includes("reopen_video_production") ? (
            <button
              className="secondary-button"
              type="button"
              disabled={busy}
              onClick={onReopen}
            >
              {pending === "reopen_video_production"
                ? "正在返回…"
                : "返回视频生产"}
            </button>
          ) : null}
        </section>
      ) : null}
      {active !== undefined ? (
        <div className="video-working" aria-live="polite">
          <div className="loading-rail">
            <span />
          </div>
          <p>{active.message}</p>
          {onCancel && active.allowed_actions.includes("cancel") ? (
            <button disabled={busy} onClick={() => onCancel(active.id)}>
              取消装配
            </button>
          ) : null}
          <strong>{Math.round(active.progress * 100)}%</strong>
        </div>
      ) : null}
      {error !== null ? (
        <div className="reference-error" role="alert">
          {error}
        </div>
      ) : null}
      {approval === null ? (
        <button
          className="primary-button"
          type="button"
          disabled={
            busy ||
            active !== undefined ||
            !snapshot.provider_availability.final_assembly ||
            !snapshot.allowed_actions.includes("generate_final_video")
          }
          onClick={onGenerate}
        >
          {pending === "generate_final_video" || active !== undefined
            ? "正在装配成片…"
            : candidates.length > 0
              ? (snapshot.narration_languages.length === 2 ? "再装配一组中英候选" : "再装配一个候选")
              : (snapshot.narration_languages.length === 2 ? "装配中英成片候选" : "装配成片候选")}
        </button>
      ) : null}
      {approval === null && anySelected ? (
        <button
          className="approval-button"
          type="button"
          disabled={
            busy ||
            !allSelected ||
            !snapshot.allowed_actions.includes("approve_final_video")
          }
          title={allSelected ? undefined : "请先分别选定中文与英文成片。"}
          onClick={onApprove}
        >
          {pending === "approve_final_video"
            ? "正在记录 Approval…"
            : (snapshot.narration_languages.length === 2 ? "批准中英成片" : "批准成片")}
        </button>
      ) : null}
      {approval === null &&
      anySelected &&
      onClearSelection !== undefined ? (
        <button
          className="secondary-button"
          type="button"
          disabled={
            busy || !snapshot.allowed_actions.includes("clear_final_selection")
          }
          onClick={onClearSelection}
        >
          {snapshot.narration_languages.length === 2 ? "撤销中英成片选择" : "撤销成片选择"}
        </button>
      ) : null}
      {languages.map((item) => (
        <section
          className="final-language"
          key={item.language}
          aria-label={`${item.label}成片`}
        >
          <h2>{item.label}成片</h2>
          {item.selected !== null ? (
            <div className="final-selected">
              <h3>当前选定{item.label}成片</h3>
              <video
                controls
                preload="metadata"
                playsInline
                muted={false}
                src={item.selected.content_url}
              />
            </div>
          ) : (
            <p className="muted-copy">尚未选定{item.label}成片。</p>
          )}
          <GenerationCandidateList
            kind="final"
            target={item.selectedAssetId ?? `final:${item.language}`}
            assets={snapshot.assets}
            candidates={item.candidates}
            active={item.active ?? null}
            busy={busy}
            summary={`查看${item.label}成片候选（${item.candidates.length}）`}
            selectLabel={`选择${item.label}成片`}
            selectedLabel="当前选择"
            onSelect={(generation) => onSelect(generation.id)}
            selectDisabled={(_, asset) =>
              busy ||
              asset.id === item.selectedAssetId ||
              approval !== null ||
              snapshot.allowed_actions.includes("select_final_video") === false
            }
            isSelected={(_, asset) => asset?.id === item.selectedAssetId}
            onDismiss={(generationId) => onDismiss(generationId)}
            dismissAllowed={(generation) => generation.allowed_actions.includes("dismiss_history")}
            renderCandidate={(_, asset) =>
              asset ? (
                <video
                  controls
                  preload="metadata"
                  playsInline
                  muted={false}
                  src={asset.content_url}
                />
              ) : null
            }
          />
        </section>
      ))}
      {generations
        .filter(
          (item) =>
            item.phase === "failed" || item.phase === "submission_uncertain",
        )
        .map((item) => (
          <div className="reference-error" key={item.id} role="alert">
            {item.message}
            {item.error_code ? `（${item.error_code}）` : ""}
          </div>
        ))}
    </section>
  );
}
