import type {
  NarrationLanguage,
  Scene,
  SceneAnimaticState,
  SceneFinalState,
} from "../api";
import type { WorkspaceFlatProps } from "./contracts";
import { generationPhaseLabel } from "./generation";
import { NARRATION_LANGUAGE_LABELS } from "./narration";
import { useState } from "react";
type OutputKind = "animatic" | "scene_final";

/** 一种输出（Animatic 或某语言 Scene 成片）的进行中、失败、当前产物与可删除卡片。 */
function outputState(
  snapshot: WorkspaceFlatProps["snapshot"],
  sceneId: string,
  kind: OutputKind,
  activeGenerationId: string | null,
  currentAssetId: string | null,
  language: NarrationLanguage | null,
) {
  const active = snapshot.generations.find((g) => g.id === activeGenerationId);
  const history = snapshot.generations.filter(
    (g) =>
      g.kind === (kind === "animatic" ? "scene_animatic" : "scene_final_video") &&
      g.target_id === sceneId &&
      g.language === language &&
      !g.dismissed,
  );
  const latest = history.at(-1);
  const failed =
    latest?.phase === "failed" || latest?.phase === "submission_uncertain" ? latest : undefined;
  const candidates = history.filter((g) => g.phase === "succeeded" && g.output_asset_id);
  const selected = snapshot.assets.find(
    (a) => a.id === (currentAssetId ?? candidates.at(-1)?.output_asset_id),
  );
  return { active, failed, selected, deletable: candidates.at(-1) ?? latest };
}

export function SceneMedia(
  props: WorkspaceFlatProps & { scene: Scene },
) {
  const { scene, snapshot, busy } = props;
  const [videoAudioVolume, setVideoAudioVolume] = useState(1);
  const [narrationAudioVolume, setNarrationAudioVolume] = useState(1);
  return (
    <>
      {(["animatic", "scene_final"] as const).map((kind) => {
        const state = scene[kind];
        if (!state) return null;
        const label = kind === "animatic" ? "Animatic" : "Scene 成片";
        const action =
          kind === "animatic"
            ? "generate_scene_animatic"
            : "generate_scene_final";
        // Scene 成片按中英旁白各出一版，共用画面；Animatic 只有一版。
        const outputs =
          kind === "animatic"
            ? [
                {
                  language: null,
                  title: label,
                  outdated: false,
                  ...outputState(
                    snapshot,
                    scene.id,
                    kind,
                    (state as SceneAnimaticState).active_generation_id,
                    null,
                    null,
                  ),
                },
              ]
            : snapshot.narration_languages.map((language) => {
                const languageState = (state as SceneFinalState)[language]!;
                return {
                  language,
                  title: `${NARRATION_LANGUAGE_LABELS[language]} Scene 成片`,
                  outdated: languageState.outdated,
                  ...outputState(
                    snapshot,
                    scene.id,
                    kind,
                    languageState.active_generation_id,
                    languageState.current_asset_id,
                    language,
                  ),
                };
              });
        const anyActive = outputs.some((output) => output.active);
        const anyFailed = outputs.some((output) => output.failed);
        const allowed =
          (kind === "animatic"
            ? !!props.onGenerateSceneAnimatic
            : !!props.onGenerateSceneFinal) &&
          snapshot.allowed_actions.includes(action) &&
          state.ready &&
          state.provider_available &&
          !anyActive;
        return (
          <section key={kind} aria-label={label}>
            <h2>{label}</h2>
            <button
              className="secondary-button"
              disabled={busy || !allowed}
              onClick={() =>
                kind === "scene_final"
                  ? props.onGenerateSceneFinal?.(
                      scene.id,
                      videoAudioVolume,
                      narrationAudioVolume,
                    )
                  : props.onGenerateSceneAnimatic?.(scene.id)
              }
            >
              {anyActive
                ? `${label} 合成中…`
                : anyFailed
                  ? `重新生成 ${label}`
                  : kind === "animatic"
                    ? "Animatic 预览"
                    : (snapshot.narration_languages.length === 2 ? "生成中英 Scene 成片" : "生成 Scene 成片")}
            </button>
            {!allowed && !anyActive ? <p>{!state.provider_available ? "当前未配置媒体 Provider，请先完成项目媒体服务配置。" : state.reason}</p> : null}
            {kind === "scene_final" ? (
              <fieldset className="scene-audio-volume-controls">
                <legend>成片音量（下次生成时生效）</legend>
                <label>
                  <span>视频自带音频：{Math.round(videoAudioVolume * 100)}%</span>
                  <input
                    aria-label="视频自带音频音量"
                    type="range"
                    min="0"
                    max="2"
                    step="0.05"
                    value={videoAudioVolume}
                    disabled={busy || anyActive}
                    onChange={(event) => setVideoAudioVolume(Number(event.target.value))}
                  />
                </label>
                <label>
                  <span>旁白音频：{Math.round(narrationAudioVolume * 100)}%</span>
                  <input
                    aria-label="旁白音频音量"
                    type="range"
                    min="0"
                    max="2"
                    step="0.05"
                    value={narrationAudioVolume}
                    disabled={busy || anyActive}
                    onChange={(event) => setNarrationAudioVolume(Number(event.target.value))}
                  />
                </label>
              </fieldset>
            ) : null}
            {outputs.map((output) => (
              <div
                key={output.language ?? "single"}
                className="scene-media-output"
                aria-label={output.language === null ? undefined : output.title}
              >
                {output.language !== null ? <h3>{output.title}</h3> : null}
                {output.outdated ? (
                  <p role="status">
                    当前{output.title}已落后于最新的 Segment 或旁白选择，最终装配会拒绝它；请重新生成 Scene 成片。
                  </p>
                ) : null}
                {output.active ? (
                  <div role="status">
                    <progress max="1" value={output.active.progress} />
                    <p>
                      {generationPhaseLabel(output.active.phase)} ·{" "}
                      {Math.round(output.active.progress * 100)}% {output.active.message}
                    </p>
                    {output.active.allowed_actions.includes("cancel") ? (
                      <button
                        disabled={busy}
                        onClick={() => props.onCancelGeneration(output.active!.id)}
                      >
                        取消生成
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {output.failed ? (
                  <div role="alert">
                    <strong>{output.title} 合成失败</strong>
                    <p>{output.failed.message}</p>
                    {output.failed.allowed_actions.includes("dismiss_history") ? (
                      <button
                        disabled={busy}
                        onClick={() => props.onDismissGeneration(output.failed!.id)}
                      >
                        删除这条失败记录
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {output.selected ? (
                  <video
                    className={kind === "scene_final" ? "scene-final-preview" : undefined}
                    controls
                    data-aspect-ratio={kind === "scene_final" ? snapshot.aspect_ratio : undefined}
                    preload="none"
                    src={output.selected.content_url}
                  />
                ) : null}
                {output.deletable?.allowed_actions.includes("dismiss_history") ? (
                  <button
                    className="secondary-button"
                    disabled={busy || !!output.active}
                    onClick={() => props.onDismissGeneration(output.deletable!.id)}
                  >
                    {kind === "scene_final" ? `删除当前${output.title}` : "删除当前 Animatic"}
                  </button>
                ) : null}
              </div>
            ))}
          </section>
        );
      })}
    </>
  );
}
