import { SettingField, type SettingValue } from "../provider_settings/SettingField";
import { stableStringify, useProtectedValue } from "./draft_protection";
import { useEffect, useState } from "react";
import type {
  NarrationCue,
  NarrationLanguage,
  NarrationTrack,
  Scene,
  StructuredDirectorSnapshot,
} from "../api";
import { generationPhaseLabel } from "./generation";
import { AssetAudio, DirectorDisclosure, GenerationCandidateList, assetById } from "./shared";

// 旁白固定中英双语：两种语言各自合成、审核与选择，时间以较长的一条为准。
export const NARRATION_LANGUAGES: readonly NarrationLanguage[] = ["zh", "en"];
export const NARRATION_LANGUAGE_LABELS: Record<NarrationLanguage, string> = {
  zh: "中文",
  en: "英文",
};

export function narrationCueFullySelected(cue: NarrationCue): boolean {
  return NARRATION_LANGUAGES.filter((language) => cue[language] !== null).every((language) => cue[language]!.selected_audio_asset_id !== null);
}

function formatSeconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "待选择" : `${value.toFixed(2)} 秒`;
}

export function NarrationCueCard({
  scene,
  cue,
  snapshot,
  busy,
  onSave,
  onGenerate,
  onSelect,
  onClearSelection,
  onCancel,
  onDismiss,
}: {
  scene: Scene;
  cue: NarrationCue;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  onSave: (cue: NarrationCue) => void;
  onGenerate: (language: NarrationLanguage) => void;
  onSelect: (generationId: string) => void;
  onClearSelection: (language: NarrationLanguage) => void;
  onCancel: (generationId: string) => void;
  onDismiss: (generationId: string) => void;
}) {
  // 展示服务端最近实际提交的 seed；不在 Web 推算下一次生成参数。
  const currentCue: NarrationCue = {
    ...cue,
    zh: withLatestSeed(cue.zh, cue.id, "zh", snapshot),
    en: withLatestSeed(cue.en, cue.id, "en", snapshot),
  };
  const { value: draft, setValue: setDraft, conflict, reset } = useProtectedValue(currentCue);
  const dirty = stableStringify(draft) !== stableStringify(currentCue);
  const canEdit = snapshot.allowed_actions.includes("edit_narration");
  const updateTrack = (language: NarrationLanguage, patch: Partial<NarrationTrack>) =>
    setDraft({ ...draft, [language]: { ...draft[language], ...patch } });
  return (
    <DirectorDisclosure className="narration-cue-card">
      {conflict ? <p role="alert">旁白已更新，未保存输入已保留。请先取消修改再编辑最新旁白。</p> : null}
      <summary>
        <div>
          <span>{scene.title}</span>
          <h2>{(cue.zh ?? cue.en)!.text}</h2>
        </div>
        <div className="narration-cue-summary-state">
          {snapshot.narration_languages.map((language) => (
            <strong
              key={language}
              className={cue[language]!.selected_audio_asset_id === null ? "is-pending" : "is-ready"}
            >
              {NARRATION_LANGUAGE_LABELS[language]} {formatSeconds(cue[language]!.selected_duration_seconds)}
              {cue.timing_language === language ? " · 时间基准" : ""}
            </strong>
          ))}
          <i aria-hidden="true">⌃</i>
        </div>
      </summary>
      <div className="narration-cue-content">
        <p className="muted-copy">
          覆盖本 Scene 全部 {scene.shots.length} 个 Shot；范围由 Core 固定。
          {snapshot.narration_languages.length === 2 ? "中英文两版共用画面，" : ""}
          {cue.timing_seconds === null
            ? (snapshot.narration_languages.length === 2 ? "两种语言都选定音频后，以较长的一条作为画面时长。" : "选定旁白音频后，以真实时长作为画面时长。")
            : `当前以${NARRATION_LANGUAGE_LABELS[cue.timing_language ?? "zh"]}（${cue.timing_seconds.toFixed(2)} 秒）作为画面时长${snapshot.narration_languages.length === 2 ? "，较短的一版同起点提前结束" : ""}。`}
        </p>
        <div className="narration-language-grid">
          {snapshot.narration_languages.map((language) => (
            <NarrationTrackPanel
              key={language}
              cueId={cue.id}
              language={language}
              track={cue[language]!}
              draft={draft[language]!}
              snapshot={snapshot}
              busy={busy}
              dirty={dirty}
              canEdit={canEdit}
              onChange={(patch) => updateTrack(language, patch)}
              onGenerate={() => onGenerate(language)}
              onSelect={onSelect}
              onClearSelection={() => onClearSelection(language)}
              onCancel={onCancel}
              onDismiss={onDismiss}
            />
          ))}
        </div>
        <div className="narration-cue-actions">
          <button
            type="button"
            className="secondary-button"
            disabled={busy || !dirty || conflict || !canEdit}
            onClick={() =>
              onSave({
                ...draft,
                zh: draft.zh === null ? null : { ...draft.zh, text: draft.zh.text.trim() },
                en: draft.en === null ? null : { ...draft.en, text: draft.en.text.trim() },
              })
            }
          >
            保存参数
          </button>
          {dirty ? <button className="secondary-button" type="button" disabled={busy} onClick={()=>{if(window.confirm('放弃未保存的旁白修改？')) reset();}}>取消旁白修改</button> : null}
        </div>
        {dirty ? (
          <p role="status">正文或参数尚未保存，请先保存再生成候选。</p>
        ) : null}
        {!snapshot.allowed_actions.includes("generate_narration") &&
        snapshot.allowed_actions.includes("confirm_script") ? (
          <p>正文和参数可以保存；生成旁白前请先确认当前脚本，进入旁白审核。</p>
        ) : null}
      </div>
    </DirectorDisclosure>
  );
}

function withLatestSeed(
  track: NarrationTrack | null,
  cueId: string,
  language: NarrationLanguage,
  snapshot: StructuredDirectorSnapshot,
): NarrationTrack | null {
  if (track === null) return null;
  const latestSeed = [...snapshot.generations]
    .reverse()
    .find(
      (item) =>
        item.kind === "narration_audio" &&
        item.target_id === cueId &&
        item.language === language &&
        item.seed !== null,
    )?.seed;
  return {
    ...track,
    seed: Math.max(track.seed, typeof latestSeed === "number" ? latestSeed : track.seed),
  };
}

function NarrationTrackPanel({
  cueId,
  language,
  track,
  draft,
  snapshot,
  busy,
  dirty,
  canEdit,
  onChange,
  onGenerate,
  onSelect,
  onClearSelection,
  onCancel,
  onDismiss,
}: {
  cueId: string;
  language: NarrationLanguage;
  track: NarrationTrack;
  draft: NarrationTrack;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  dirty: boolean;
  canEdit: boolean;
  onChange: (patch: Partial<NarrationTrack>) => void;
  onGenerate: () => void;
  onSelect: (generationId: string) => void;
  onClearSelection: () => void;
  onCancel: (generationId: string) => void;
  onDismiss: (generationId: string) => void;
}) {
  const label = NARRATION_LANGUAGE_LABELS[language];
  const [confirmClearSelection, setConfirmClearSelection] = useState(false);
  const selected =
    track.selected_audio_asset_id === null
      ? null
      : assetById(snapshot.assets, track.selected_audio_asset_id);
  const generations = snapshot.generations.filter(
    (item) =>
      item.kind === "narration_audio" &&
      item.target_id === cueId &&
      item.language === language &&
      !item.dismissed,
  );
  useEffect(() => {
    setConfirmClearSelection(false);
  }, [track.selected_audio_asset_id]);
  return (
    <section className="narration-language-panel" aria-label={`${label}旁白`}>
      <h3>{label}旁白</h3>
      <label className="card-field">
        <span>{label}正文</span>
        <textarea
          value={draft.text}
          disabled={busy}
          onChange={(event) => onChange({ text: event.target.value })}
        />
      </label>
      {(snapshot.provider_recipes ?? []).filter((view) => view.capability === "speech.synthesize").map((view) => (
        <fieldset key={view.recipe.id} disabled={busy || !canEdit}>
          <legend>{view.plugin_label} · {view.recipe.label}</legend>
          {view.editable_params.map((field) => <SettingField key={field.key} field={field}
            value={(draft.recipe_params[view.recipe.id]?.[field.key] ?? field.default) as SettingValue}
            onChange={(value) => onChange({ recipe_params: { ...draft.recipe_params,
              [view.recipe.id]: { ...Object.fromEntries(view.editable_params.map((item) => [item.key, item.default])),
                ...draft.recipe_params[view.recipe.id], [field.key]: value } } })} />)}
        </fieldset>
      ))}
      <div className="narration-parameters">
        <label>
          Seed{" "}
          <input
            type="number"
            min="0"
            value={draft.seed}
            disabled={busy}
            onChange={(event) => onChange({ seed: Number(event.target.value) })}
          />
        </label>
        <button
          type="button"
          className="primary-button"
          disabled={
            busy ||
            dirty ||
            !snapshot.allowed_actions.includes("generate_narration") ||
            !snapshot.provider_availability.speech_synthesis
          }
          onClick={onGenerate}
        >
          生成{label}候选
        </button>
      </div>
      {selected !== null ? (
        <section className="selected-narration-audio">
          <div className="selected-narration-audio-heading">
            <strong>已选{label}音频 · {formatSeconds(selected.duration_seconds)}</strong>
            {!confirmClearSelection ? (
              <button
                type="button"
                className="delete-button"
                disabled={busy || !canEdit}
                title={canEdit ? undefined : "当前项目状态不允许修改旁白。"}
                onClick={() => setConfirmClearSelection(true)}
              >
                取消选用
              </button>
            ) : null}
          </div>
          <AssetAudio asset={selected} />
          {confirmClearSelection ? (
            <div className="selected-narration-clear-confirm">
              <span>
                取消后将清空当前{label}旁白音频并使相关时序与装配失效；历史候选仍会保留。
              </span>
              <button
                type="button"
                className="delete-button"
                disabled={busy}
                onClick={onClearSelection}
              >
                确认取消选用
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => setConfirmClearSelection(false)}
              >
                保留当前音频
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
      <GenerationCandidateList
        kind="narration"
        target={`${cueId}:${language}`}
        assets={snapshot.assets}
        candidates={generations.filter((generation) =>
          generation.phase === "succeeded" && generation.output_asset_id !== null
        )}
        active={
          generations.find((generation) =>
            generation.phase === "submitting" ||
            generation.phase === "queued" ||
            generation.phase === "running"
          ) ?? null
        }
        busy={busy}
        collapsible={false}
        summary={`${label}旁白生成候选`}
        selectLabel="选择这条"
        selectedLabel="当前选择"
        onSelect={(generation) => onSelect(generation.id)}
        selectDisabled={(generation) =>
          busy || generation.allowed_actions.includes("select_narration_audio") === false
        }
        onDismiss={(generationId) => onDismiss(generationId)}
        dismissLabel="隐藏历史卡片"
        dismissAllowed={(generation) => generation.allowed_actions.includes("dismiss_history")}
        isSelected={() => false}
        renderCandidate={(generation, asset) => (
          <div className={`narration-candidate-body${asset !== null ? "" : " is-working"}`}>
            {asset !== null ? (
              <AssetAudio asset={asset} />
            ) : (
              <div className="scene-candidate-progress">
                <div className="candidate-progress">
                  <span style={{ width: `${generation.progress * 100}%` }} />
                </div>
                <strong>{generationPhaseLabel(generation.phase)}</strong>
                <p>{generation.message}</p>
              </div>
            )}
            <div className="narration-candidate-params">
              {asset?.duration_seconds !== null && asset?.duration_seconds !== undefined ? (
                <span>真实时长 {asset.duration_seconds.toFixed(3)} 秒</span>
              ) : null}
              <span>seed {generation.seed}</span>
            </div>
            {generation.allowed_actions.includes("cancel") ? (
              <button
                type="button"
                className="delete-button"
                disabled={busy}
                onClick={() => onCancel(generation.id)}
              >取消</button>
            ) : null}
          </div>
        )}
      />
    </section>
  );
}
