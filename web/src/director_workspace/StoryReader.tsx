import { LocationBinding } from "./location";
import { DraftProtection } from "./draft_protection";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  DialogueTimingWarning,
  DialogueLine,
  DialogueAudio,
  ProviderRecipeView,
  Scene,
  Shot,
  ShotSegment,
  StructuredDirectorSnapshot,
} from "../api";
import type { StoryTarget } from "../api/projection";
import type { WorkspaceFlatProps } from "./contracts";
import { StoryNavigation } from "./StoryNavigation";
import { NodeEditor } from "./NodeEditor";
import { SegmentKeyframeInputs } from "./keyframe";
import { SegmentVideoPanel } from "./video";
import { SegmentVideoDraftProvider } from "./RecipeInputsControl";
import {
  NARRATION_LANGUAGE_LABELS,
  NarrationCueCard,
  narrationCueFullySelected,
} from "./narration";
import { FinalAssemblyWorkspace } from "./final";
import { SceneMedia } from "./SceneMedia";
import { generationPhaseLabel } from "./generation";
import { SettingField, type SettingValue } from "../provider_settings/SettingField";
import { copyText } from "./clipboard";
import { newSceneDraft } from "./script_draft";
import {
  segmentShotLabel,
  segmentShots,
  shotLabel,
  shotSegments,
} from "./script_index";
import { InsertShotSection, SegmentStructureActions } from "./script_structure";
import "./story_reader.css";
const noop = () => undefined;

export function StoryReader(props: WorkspaceFlatProps) {
  const { project, snapshot, busy, error } = props;
  const key = `story-reader:${project.id}`;
  const scenes = snapshot.director_script?.scenes ?? [];
  const [target, setTarget] = useState<StoryTarget | null>(() => {
    try {
      const t = JSON.parse(sessionStorage.getItem(key) ?? "null");
      return t &&
        ["scene", "shot", "segment"].includes(t.level) &&
        typeof t.id === "string" &&
        typeof t.sceneId === "string"
        ? t
        : null;
    } catch {
      return null;
    }
  });
  const [scriptDirty, setDirty] = useState(false);
  const [dirtySources, setDirtySources] = useState<string[]>([]);
  const registerDraft = useCallback(
    (id: string, value: boolean) =>
      setDirtySources((current) =>
        value
          ? current.includes(id)
            ? current
            : [...current, id]
          : current.filter((x) => x !== id),
      ),
    [],
  );
  const dirty = scriptDirty || dirtySources.length > 0;
  const [deleteScene, setDeleteScene] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const liveScene = scenes.find((s) => s.id === target?.sceneId);
  const liveShot =
    target?.level === "shot"
      ? liveScene?.shots.find((s) => s.id === target.id)
      : undefined;
  const liveSegment =
    target?.level === "segment"
      ? liveScene?.segments.find((s) => s.id === target.id)
      : undefined;
  const previous = useRef<{
    scene?: Scene;
    shot?: Shot;
    segment?: ShotSegment;
  }>({});
  const liveTarget =
    liveScene &&
    (target?.level === "scene" ||
      (target?.level === "shot" && liveShot) ||
      (target?.level === "segment" && liveSegment));
  if (liveTarget)
    previous.current = {
      scene: liveScene,
      shot: liveShot,
      segment: liveSegment,
    };
  const scene = liveScene ?? (dirty ? previous.current.scene : undefined);
  const shot = liveShot ?? (dirty ? previous.current.shot : undefined);
  const segment = liveSegment ?? (dirty ? previous.current.segment : undefined);
  const choose = (next: StoryTarget | null) => {
    if (next?.id === target?.id) return;
    if (dirty && !window.confirm("当前内容有未保存的修改，是否放弃并切换？"))
      return;
    setDirty(false);
    setTarget(next);
    setNotice("");
  };
  useEffect(() => {
    if (target) sessionStorage.setItem(key, JSON.stringify(target));
    else sessionStorage.removeItem(key);
  }, [key, target]);
  useEffect(() => {
    if (!target || liveTarget) return;
    // Keep dirty input mounted after deletion until the user explicitly leaves it.
    if (dirty) {
      setNotice("当前节点已被删除，未保存输入仍保留。");
      return;
    }
    setTarget(scene ? { level: "scene", id: scene.id, sceneId: scene.id } : null);
    setNotice("当前节点已被删除，已返回仍存在的上级。");
  }, [target, scene, liveTarget, dirty]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const current =
    target?.level === "scene"
      ? scene
      : target?.level === "shot"
        ? shot
        : segment;
  const siblings = !target
    ? []
    : target.level === "scene"
      ? scenes
      : target.level === "shot"
        ? (scene?.shots ?? [])
        : (scene?.segments ?? []);
  const index = siblings.findIndex((s) => s.id === target?.id);
  const character = (id: string) =>
    snapshot.reference_library.characters.find((c) => c.id === id)?.name ??
    `已移出 @${id.slice(0, 6)}`;
  const can = (action: StructuredDirectorSnapshot["allowed_actions"][number]) =>
    snapshot.allowed_actions.includes(action);
  const narrationTimingConflict = snapshot.workflow.required_next_actions.find(
    (action) =>
      action.action === "script.apply_operations" &&
      action.reason === "narration_timing_conflict",
  );
  const narrationShotPlanRequired = snapshot.workflow.required_next_actions.some(
    (action) =>
      action.action === "script.apply_operations" &&
      action.reason === "narration_shot_plan_required",
  );
  const recommendedActions = snapshot.workflow.recommended_next_actions ?? [];
  const sceneIndex = scenes.findIndex((s) => s.id === scene?.id);
  return (
    <DraftProtection.Provider value={registerDraft}>
      <StoryNavigation
        scenes={scenes}
        title={project.title}
        target={target}
        timingConfirmed={Boolean(
          snapshot.director_script &&
            snapshot.director_script.production_baseline_revision ===
              snapshot.director_script.revision,
        )}
        timingWarnings={snapshot.dialogue_timing_warnings}
        softDurationLimits={Object.fromEntries(
          (snapshot.video_plan?.segments ?? []).map((item) => [
            item.segment_id,
            item.recipe_state?.soft_duration_limit_seconds ?? null,
          ]),
        )}
        onChoose={choose}
      >
        {notice ? <p role="status">{notice}</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {recommendedActions.length > 0 ? (
          <section className="workflow-recommendations" aria-label="可选建议">
            {recommendedActions.map((action, index) => (
              <p key={`${action.action}-${index}`}>
                {String(action.message ?? action.action)}
              </p>
            ))}
          </section>
        ) : null}
        {target && current && scene ? (
          <>
            <div className="story-reader-tools">
              <button
                disabled={index <= 0}
                onClick={() =>
                  choose({
                    ...target,
                    id: siblings[index - 1].id,
                    sceneId:
                      target.level === "scene"
                        ? siblings[index - 1].id
                        : target.sceneId,
                  })
                }
              >
                上一
                {target.level === "scene"
                  ? "场景"
                  : target.level === "shot"
                    ? "镜头"
                    : "片段"}
              </button>
              <button
                disabled={index < 0 || index >= siblings.length - 1}
                onClick={() =>
                  choose({
                    ...target,
                    id: siblings[index + 1].id,
                    sceneId:
                      target.level === "scene"
                        ? siblings[index + 1].id
                        : target.sceneId,
                  })
                }
              >
                下一
                {target.level === "scene"
                  ? "场景"
                  : target.level === "shot"
                    ? "镜头"
                    : "片段"}
              </button>
              <button
                disabled={!liveTarget}
                onClick={async () => {
                  const location = [
                    `场景 ${sceneIndex + 1}`,
                    ...(shot ? [`镜头 ${scene.shots.indexOf(shot) + 1}`] : []),
                    ...(segment ? [`片段 ${scene.segments.indexOf(segment) + 1}`] : []),
                  ].join("－");
                  const copied = await copyText(
                    location,
                  );
                  if (copied) setNotice("已复制当前定位");
                }}
              >
                复制定位
              </button>
            </div>
            <p className="eyebrow">
              {scene.title}
              {shot ? ` / 镜头 ${scene.shots.indexOf(shot) + 1}` : ""}
              {segment
                ? ` / 片段 ${scene.segments.indexOf(segment) + 1}（${segmentShotLabel(scene, segment)}）`
                : ""}
            </p>
            <h1>
              {target.level === "scene"
                ? scene.title
                : `${target.level === "shot" ? "镜头" : "片段"} ${index + 1} · ${"action" in current ? current.action.slice(0, 50) : ""}`}
            </h1>
            <NodeEditor
              key={target.id}
              snapshot={snapshot}
              target={target}
              scene={scene}
              shot={shot}
              segment={segment}
              busy={busy}
              error={error}
              onSave={props.onSaveScript}
              onDirty={setDirty}
            />
            {target.level === "scene" ? (
              <>
                <p>{scene.summary}</p>
                <LocationBinding key={`location-${scene.id}`} {...props} scene={scene} />
                <h2>时空与环境</h2>
                <p>{scene.setting}</p>
                <p className="muted-copy">
                  {scene.driver === "narration"
                    ? "旁白驱动：只有旁白、没有对白；先选择真实 TTS 音频，再规划镜头。"
                    : "表演驱动：没有旁白，对白按需；Scene 无预设总时长。"}
                </p>
                {scene.narration_cues.map((cue) => (
                  <section className="story-reader-narration" key={cue.id}>
                    <h2>
                      旁白 ·{" "}
                      {snapshot.reference_library.narrator?.name ?? "旁白"}
                    </h2>
                    {snapshot.narration_languages.map((language) => {
                      const track = cue[language]!;
                      const audio = track.selected_audio_asset_id
                        ? snapshot.assets.find((a) => a.id === track.selected_audio_asset_id)
                        : undefined;
                      return (
                        <div className="story-reader-narration-track" key={language}>
                          <p>
                            <strong>{NARRATION_LANGUAGE_LABELS[language]}</strong> {track.text}
                          </p>
                          {audio ? (
                            <audio controls src={audio.content_url} />
                          ) : (
                            <small>尚未选择{NARRATION_LANGUAGE_LABELS[language]}旁白音频</small>
                          )}
                        </div>
                      );
                    })}
                    {!snapshot.production_availability.narration.unlocked ? <p>{snapshot.production_availability.narration.reason}<button onClick={() => choose(null)}>前往项目概览</button></p> : null}
                    {snapshot.workspace_layers.narration_unlocked ? (
                      <details open>
                        <summary>旁白编辑、生成与候选</summary>
                        <NarrationCueCard
                          scene={scene}
                          cue={cue}
                          snapshot={snapshot}
                          busy={busy}
                          onSave={(c) => props.onSaveNarrationCue(scene.id, c)}
                          onGenerate={(language) =>
                            props.onGenerateNarration(scene.id, cue.id, language)
                          }
                          onSelect={(id) =>
                            props.onSelectNarrationAudio(scene.id, cue.id, id)
                          }
                          onClearSelection={(language) =>
                            props.onClearNarrationAudioSelection(scene.id, cue.id, language)
                          }
                          onCancel={props.onCancelGeneration}
                          onDismiss={props.onDismissGeneration}
                        />
                      </details>
                    ) : null}
                  </section>
                ))}
                <h2>镜头设计</h2>
                {scene.shots.map((s, i) => {
                  const covers = shotSegments(scene, s.id);
                  return (
                    <section key={s.id}>
                      <button
                        className="text-button"
                        onClick={() =>
                          choose({ level: "shot", sceneId: scene.id, id: s.id })
                        }
                      >
                        镜头 {i + 1}
                      </button>
                      <ShotText shot={s} character={character} />
                      <small className="story-shot-coverage">
                        {covers.length
                          ? `被片段 ${covers
                              .map(
                                (cover) =>
                                  `${scene.segments.indexOf(cover) + 1}（${segmentShotLabel(scene, cover)}）`,
                              )
                              .join("、")}覆盖`
                          : "尚未被任何片段覆盖"}
                      </small>
                    </section>
                  );
                })}
                {can("edit_script") ? (
                  <InsertShotSection
                    key={`insert-shot:${scene.id}`}
                    snapshot={snapshot}
                    scene={scene}
                    busy={busy}
                    error={error}
                    disabled={dirty}
                    onSave={props.onSaveScript}
                  />
                ) : null}
                {scene.segments.length ? <h2>生成片段</h2> : null}
                {scene.segments.map((g, i) => (
                  <section key={g.id}>
                    <button
                      className="text-button"
                      onClick={() =>
                        choose({ level: "segment", sceneId: scene.id, id: g.id })
                      }
                    >
                      片段 {i + 1} · {segmentShotLabel(scene, g)}
                    </button>
                    <SegmentText
                      segment={g}
                      character={character}
                      timingWarnings={snapshot.dialogue_timing_warnings}
                    />
                  </section>
                ))}
                {!scene.shots.length ? (
                  <p>镜头尚未规划。完成旁白音频选择后由外部 Agent 按 Core 提供的目标画面时长规划。</p>
                ) : null}
                <SceneMedia scene={scene} {...props} />
                {can("edit_script") ? (
                  <details>
                    <summary>场景结构操作</summary>
                    <button
                      disabled={busy || dirty}
                      onClick={() =>
                        props.onSaveScript(
                          [
                            ...scenes.slice(0, sceneIndex + 1),
                            newSceneDraft(),
                            ...scenes.slice(sceneIndex + 1),
                          ],
                          snapshot.revision,
                        )
                      }
                    >
                      在此后插入 Scene
                    </button>
                    <button
                      disabled={busy || dirty || scenes.length <= 1}
                      onClick={() => setDeleteScene(scene.id)}
                    >
                      删除这个 Scene
                    </button>
                    {deleteScene === scene.id ? <div role="alert"><p>删除这个 Scene？环境资源会保留，Core 将更新相关下游依赖。</p><button disabled={busy || dirty} onClick={() => {props.onSaveScript(scenes.filter(s => s.id !== scene.id), snapshot.revision); setDeleteScene(null);}}>确认删除 Scene</button><button onClick={() => setDeleteScene(null)}>保留 Scene</button></div> : null}
                  </details>
                ) : null}
              </>
            ) : target.level === "shot" && shot ? (
              <>
                <LocationBinding key={`view-${shot.id}`} {...props} scene={scene} shot={shot} />
                <ShotText shot={shot} character={character} />
                {shotSegments(scene, shot.id).map((s) => {
                  const plan = snapshot.video_plan?.segments.find(
                    (v) => v.segment_id === s.id,
                  );
                  const asset = snapshot.assets.find(
                    (a) =>
                      a.id ===
                      (plan?.upscaled_asset_id ?? plan?.selected_asset_id),
                  );
                  return (
                    <section key={s.id}>
                      <button
                        className="secondary-button"
                        onClick={() =>
                          choose({
                            level: "segment",
                            sceneId: scene.id,
                            id: s.id,
                          })
                        }
                      >
                        打开片段 {scene.segments.indexOf(s) + 1} · {segmentShotLabel(scene, s)}
                      </button>
                      {asset ? (
                        <video
                          controls
                          preload="none"
                          src={asset.content_url}
                        />
                      ) : null}
                    </section>
                  );
                })}
              </>
            ) : segment ? (
              <>
                <p className="muted-copy">
                  覆盖{" "}
                  {segmentShots(scene, segment)
                    .map((item) => `镜头 ${scene.shots.indexOf(item) + 1}`)
                    .join("、")}
                </p>
                <ul className="story-segment-shots" aria-label="覆盖的镜头">
                  {segmentShots(scene, segment).map((item) => (
                    <li key={item.id}>
                      <button
                        className="text-button"
                        onClick={() =>
                          choose({
                            level: "shot",
                            sceneId: scene.id,
                            id: item.id,
                          })
                        }
                      >
                        {shotLabel(scene, item.id)}
                      </button>
                      <p>{item.action}</p>
                      <small>
                        构图：{item.composition} · 运镜：{item.camera_movement}
                        {item.visible_character_ids.length
                          ? ` · 可见角色：${item.visible_character_ids
                              .map(character)
                              .join("、")}`
                          : ""}
                      </small>
                    </li>
                  ))}
                </ul>
                <SegmentText
                  segment={segment}
                  character={character}
                  timingWarnings={snapshot.dialogue_timing_warnings}
                />
                {segment.dialogue_lines.length ? (
                  <DialogueProductionPanel
                    segment={segment}
                    snapshot={snapshot}
                    busy={busy}
                    character={character}
                    onGenerate={props.onGenerateDialogue}
                    onSelect={props.onSelectDialogueAudio}
                    onSaveRecipeParams={props.onSaveDialogueRecipeParams}
                    onDismiss={props.onDismissGeneration}
                    onSetTiming={props.onSetDialogueTiming}
                  />
                ) : null}
                {can("edit_script") ? (
                  <SegmentStructureActions
                    key={`structure:${segment.id}`}
                    snapshot={snapshot}
                    scene={scene}
                    segment={segment}
                    busy={busy}
                    error={error}
                    disabled={dirty}
                    onPreview={props.onPreviewScriptChange}
                    onApply={props.onApplyScriptChange}
                  />
                ) : null}
                {!snapshot.production_availability.keyframes.unlocked ? <section aria-label="关键帧尚未解锁"><h3>首尾关键帧</h3><p>{snapshot.production_availability.keyframes.reason}</p><button onClick={() => choose(null)}>前往项目概览完成前置步骤</button></section> : null}
                {!snapshot.production_availability.videos.unlocked ? <section aria-label="视频尚未解锁"><h3>片段视频</h3><p>{snapshot.production_availability.videos.reason}</p><button onClick={() => choose(null)}>前往项目概览完成前置步骤</button></section> : null}
                <SegmentVideoDraftProvider
                  key={`video-draft:${segment.id}`}
                  snapshot={snapshot}
                  segmentId={segment.id}
                >
                  {snapshot.workspace_layers.keyframes_unlocked ? (
                    <SegmentKeyframeInputs
                      key={`keyframes:${segment.id}`}
                      projectId={project.id}
                      snapshot={snapshot}
                      segmentId={segment.id}
                      sceneIndex={sceneIndex}
                      segmentIndex={scene.segments.indexOf(segment)}
                      continuesPrevious={segment.boundary_from_previous !== null}
                      continuesNext={
                        scene.segments[scene.segments.indexOf(segment) + 1]
                          ?.boundary_from_previous != null
                      }
                      busy={busy}
                      videoDependenciesEditable={can("edit_segment_video_plan")}
                      onSaveVideoInputs={props.onSaveSegmentVideoInputs}
                      onSaveKeyframe={props.onSaveKeyframe}
                      onGenerate={props.onGenerateKeyframe}
                      onSelect={props.onSelectKeyframe}
                      onSaveReferences={props.onSaveSegmentKeyframeReferences}
                      onSaveActivation={props.onSaveSegmentKeyframeActivation}
                      onSaveBoundary={props.onSaveSegmentKeyframeBoundary ?? noop}
                      onExtractFrame={props.onExtractKeyframeVideoFrame ?? noop}
                      onLoadVideoFrameInfo={props.onLoadVideoFrameInfo}
                      onDismissGeneration={props.onDismissGeneration}
                      onCancel={props.onCancelGeneration}
                    />
                  ) : null}
                  {snapshot.workspace_layers.videos_unlocked ? (
                    <SegmentVideoPanel
                      key={`video:${segment.id}:${snapshot.video_plan?.segments.find((item) => item.segment_id === segment.id)?.active_recipe}`}
                      snapshot={snapshot}
                      segment={segment}
                      busy={busy}
                      dependenciesEditable={can("edit_segment_video_plan")}
                      preparing={props.pendingSegmentVideoId === segment.id}
                      hideReferenceImageSlots
                      onPreview={props.onPreviewSegmentVideoInputs}
                      onSave={props.onSaveSegmentVideoInputs ?? noop}
                      onSaveRecipe={props.onSaveSegmentVideoRecipe ?? noop}
                      onExtractVideoFrame={props.onExtractVideoFrame ?? noop}
                      onLoadVideoFrameInfo={props.onLoadVideoFrameInfo}
                      onGenerate={props.onGenerateSegmentVideo ?? noop}
                      onAttachCandidate={
                        props.onAttachSegmentVideoCandidate ?? noop
                      }
                      onSelect={props.onSelectSegmentVideo ?? noop}
                      onClearSelection={
                        props.onClearSegmentVideoSelection ?? noop
                      }
                      onDismiss={props.onDismissGeneration}
                      onCancel={props.onCancelGeneration}
                      onUpscale={props.onUpscaleSegmentVideo ?? noop}
                    />
                  ) : null}
                </SegmentVideoDraftProvider>
              </>
            ) : null}
          </>
        ) : (
          <>
            <p className="eyebrow">项目概览</p>
            <h1>{project.title}</h1>
            <p>
              共 {scenes.length} 个场景，
              {scenes.reduce((n, s) => n + s.shots.length, 0)}{" "}
              个镜头。选择左侧故事位置阅读和制作。
            </p>
            <div className="story-project-actions">
              {snapshot.workspace_layers.videos_unlocked ? (
                <p aria-label="视频选择进度">
                  {snapshot.video_plan?.segments.filter(
                    (s) => s.selected_asset_id,
                  ).length ?? 0}
                  /{snapshot.video_plan?.segments.length ?? 0} Segment 已选择
                </p>
              ) : null}
              {can("confirm_script") ? (
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={props.onConfirmScript}
                >
                  确认脚本，进入旁白审核
                </button>
              ) : null}
              {snapshot.workspace_layers.narration_unlocked ? (
                <>
                  <p aria-label="旁白选择进度">
                    {
                      scenes
                        .flatMap((s) => s.narration_cues)
                        .filter(narrationCueFullySelected).length
                    }
                    /{scenes.flatMap((s) => s.narration_cues).length} 旁白已选齐中英文音频
                  </p>
                  {scenes
                    .flatMap((s) => s.narration_cues)
                    .some((c) => !narrationCueFullySelected(c)) ? (
                    <p>
                      请先为全部旁白选择中文与英文音频，选齐后 Core 按较长的一条自动校准时长。
                    </p>
                  ) : null}
                  {narrationShotPlanRequired ? (
                    <p>
                      旁白音频已就绪。请先让 Agent 按 Core 提供的目标画面时长规划每个
                      Scene 的 Shot / Segment，Core 会按真实音频自动校准时长。
                    </p>
                  ) : null}
                  {narrationTimingConflict ? (
                    <p role="alert" aria-label="旁白时长冲突">
                      旁白时长无法自动校准：{String(narrationTimingConflict.message ?? "")}
                    </p>
                  ) : null}
                  <button
                    disabled={busy || !can("generate_narration_batch")}
                    onClick={props.onGenerateNarrationBatch}
                  >
                    生成所有缺失旁白
                  </button>
                </>
              ) : null}
              {snapshot.dialogue_plan?.items.length ? (
                <>
                  <p aria-label="对白 TTS 选择进度">
                    {
                      snapshot.dialogue_plan.items.filter(
                        (item) => item.selected_audio_asset_id,
                      ).length
                    }
                    /{snapshot.dialogue_plan.items.length} 句对白已选择 TTS 音频
                  </p>
                  <button
                    disabled={busy || !can("generate_dialogue_batch")}
                    onClick={props.onGenerateDialogueBatch}
                  >
                    生成所有缺失对白
                  </button>
                </>
              ) : null}
              {can("unlock_visual_production") ? (
                <button
                  disabled={busy}
                  onClick={props.onUnlockVisualProduction}
                >
                  解锁视觉生产
                </button>
              ) : null}
              {snapshot.workspace_layers.videos_unlocked ? (
                <button
                  onClick={() => {
                    for (const s of scenes)
                      for (const g of s.segments)
                          if (
                            !snapshot.video_plan?.segments.find(
                              (v) => v.segment_id === g.id,
                            )?.selected_asset_id
                          ) {
                            choose({
                              level: "segment",
                              sceneId: s.id,
                              id: g.id,
                            });
                            return;
                          }
                  }}
                >
                  导航到下一个未成片 Segment
                </button>
              ) : null}
            </div>
            {snapshot.workspace_layers.final_assembly_unlocked &&
            snapshot.final_assembly ? (
              <FinalAssemblyWorkspace
                snapshot={snapshot}
                busy={busy}
                pending={props.pending}
                error={error}
                onGenerate={props.onGenerateFinalVideo ?? noop}
                onSelect={props.onSelectFinalVideo ?? noop}
                onClearSelection={props.onClearFinalSelection}
                onApprove={props.onApproveFinalVideo ?? noop}
                onReopen={props.onReopenVideoProduction}
                onCancel={props.onCancelGeneration}
                onDismiss={props.onDismissGeneration}
              />
            ) : (
              <section aria-label="最终成片装配">
                <h2>最终成片装配</h2>
                <p>{snapshot.production_availability.final.reason}</p>
                {!snapshot.provider_availability.final_assembly ? <p>未配置成片装配 Provider，请先完成媒体服务配置。</p> : null}
                <button className="primary-button" disabled={busy || !can("generate_final_video") || !snapshot.provider_availability.final_assembly} onClick={props.onGenerateFinalVideo}>一键生成成片</button>
              </section>
            )}
            {scenes.map((s, i) => (
              <section key={s.id}>
                <h2>
                  场景 {i + 1} · {s.title}
                </h2>
                <p>{s.summary}</p>
              </section>
            ))}
          </>
        )}
      </StoryNavigation>
    </DraftProtection.Provider>
  );
}
function DialogueProductionPanel({
  segment,
  snapshot,
  busy,
  character,
  onGenerate,
  onSelect,
  onSaveRecipeParams,
  onDismiss,
  onSetTiming,
}: {
  segment: ShotSegment;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  character: (id: string) => string;
  onGenerate?: (dialogueLineId: string) => void;
  onSelect?: (dialogueLineId: string, generationId: string) => void;
  onSaveRecipeParams?: (
    dialogueLineId: string,
    recipeParams: Record<string, unknown>,
  ) => void;
  onDismiss?: (generationId: string) => void;
  onSetTiming?: (
    segmentId: string,
    starts: Record<string, number>,
    durationSeconds: number,
  ) => void;
}) {
  const [confirmDismiss, setConfirmDismiss] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [candidateOpen, setCandidateOpen] = useState<Record<string, boolean>>({});
  const plan = new Map(
    (snapshot.dialogue_plan?.items ?? []).map((item) => [
      item.dialogue_line_id,
      item,
    ]),
  );
  const assets = new Map(snapshot.assets.map((asset) => [asset.id, asset]));
  const selected = segment.dialogue_lines.map((line) => {
    const item = plan.get(line.id);
    const asset = item?.selected_audio_asset_id
      ? assets.get(item.selected_audio_asset_id)
      : undefined;
    return { line, item, asset };
  });
  const ready = selected.every(
    ({ item, asset }) => item?.selected_audio_asset_id && asset?.duration_seconds,
  );
  const selectedCount = selected.filter(({ asset }) => asset !== undefined).length;
  const autoTiming = () => {
    let cursor = 0.5;
    const starts: Record<string, number> = {};
    for (const { line, asset } of selected) {
      starts[line.id] = cursor;
      cursor += (asset?.duration_seconds ?? 0) + 0.25;
    }
    onSetTiming?.(segment.id, starts, Math.max(0.2, cursor + 0.25));
  };
  return (
    <section aria-label="对白 TTS" className="dialogue-production-panel">
      <button
        type="button"
        className="dialogue-panel-toggle"
        aria-expanded={panelOpen}
        onClick={() => setPanelOpen((value) => !value)}
      >
        <span>
          <strong>对白 TTS</strong>
          <small>已选 {selectedCount}/{selected.length}</small>
        </span>
        <span aria-hidden="true">{panelOpen ? "收起" : "展开"}</span>
      </button>
      {panelOpen ? (
        <div className="dialogue-panel-body">
          <p className="dialogue-panel-intro">
            视频只使用这里选定的 WAV；有角色参考音色时强制克隆，否则使用音色设计。
          </p>
          <div className="dialogue-line-list">
            {selected.map(({ line, item, asset }, lineIndex) => {
              const card = snapshot.reference_library.characters.find(
                (value) => value.id === line.character_id,
              );
              const route = card?.voice_reference_asset_id ? "音色克隆" : "音色设计";
              const voiceDescription = card?.voice_description ?? line.voice_description;
              const speechRecipe = (snapshot.provider_recipes ?? []).find(
                (view) => view.capability === "speech.synthesize",
              );
              const history = snapshot.generations.filter(
                (generation) =>
                  generation.kind === "dialogue_audio" &&
                  generation.target_id === line.id &&
                  !generation.dismissed,
              );
              const activeGeneration = history.find((generation) =>
                ["submitting", "queued", "running"].includes(generation.phase),
              );
              const latest = history.at(-1);
              const failed =
                latest?.phase === "failed" || latest?.phase === "submission_uncertain"
                  ? latest
                  : undefined;
              // 所有成功、未隐藏的 WAV 都保留在候选列表；输入变化只显示软提示。
              const candidates = history.filter(
                (generation) =>
                  generation.phase === "succeeded" && generation.output_asset_id !== null,
              );
              const speaker =
                line.character_id === null ? line.speaker_label : character(line.character_id);
              const timing =
                item?.start_seconds === null || item?.start_seconds === undefined
                  ? " · 待校准起点"
                  : " · " + item.start_seconds.toFixed(3) + "s 开始";
              const candidatesExpanded = candidateOpen[line.id] ?? true;
              return (
                <article className="dialogue-line-card" key={line.id}>
            <header className="dialogue-line-header">
              <span className="dialogue-line-index">对白 {lineIndex + 1}</span>
              <div>
                <strong>{speaker}</strong>
                <span className="dialogue-route-badge">{route}</span>
              </div>
              <span className={asset ? "dialogue-status is-selected" : "dialogue-status"}>
                {activeGeneration ? "生成中" : asset ? "已选择" : "待选择"}
              </span>
            </header>

            <section className="dialogue-card-section" aria-label="对白与表演">
              <h4>对白与表演</h4>
              <blockquote className="dialogue-copy">{line.text}</blockquote>
              <dl className="dialogue-direction-list">
                <div>
                  <dt>基础音色</dt>
                  <dd>{voiceDescription || "未填写"}</dd>
                </div>
                <div>
                  <dt>剧本表演</dt>
                  <dd>{line.delivery || "未填写"}</dd>
                </div>
              </dl>
              {card?.voice_reference_asset_id && speechRecipe && item ? (
                <DialogueRecipeControls
                  line={line}
                  item={item}
                  recipe={speechRecipe}
                  busy={busy}
                  canEdit={snapshot.allowed_actions.includes("edit_dialogue_audio")}
                  onSave={onSaveRecipeParams}
                />
              ) : null}
            </section>

            <section className="dialogue-card-section" aria-label="当前选择">
              <h4>当前选择</h4>
              <p className="dialogue-selection-state">
                {asset
                  ? "已选 WAV · " + asset.duration_seconds?.toFixed(3) + " 秒" + timing
                  : "尚未选择对白音频"}
              </p>
              {asset ? (
                <audio
                  aria-label={`试听已选对白 ${speaker}`}
                  controls
                  preload="none"
                  src={asset.content_url}
                />
              ) : null}
            </section>

            <section className="dialogue-card-section" aria-label="生成与候选">
              <h4>生成与候选</h4>
              {activeGeneration ? (
                <div className="dialogue-generation-state" role="status">
                  <progress max="1" value={activeGeneration.progress} />
                  <p>
                    {generationPhaseLabel(activeGeneration.phase)} ·{" "}
                    {Math.round(activeGeneration.progress * 100)}% ·{" "}
                    {activeGeneration.message}
                  </p>
                </div>
              ) : null}
              {failed ? (
                <div className="dialogue-generation-state is-failed" role="alert">
                  <strong>对白 TTS 失败</strong>
                  <p>{failed.message || failed.error_code || "外部语音模型执行失败。"}</p>
                  {failed.allowed_actions.includes("dismiss_history") ? (
                    confirmDismiss === failed.id ? (
                      <div className="dialogue-dismiss-confirm">
                        <span>隐藏后不再显示；废弃产物可随后在资产中心永久清理。</span>
                        <button
                          type="button"
                          className="delete-button"
                          disabled={busy || !onDismiss}
                          onClick={() => {
                            setConfirmDismiss(null);
                            onDismiss?.(failed.id);
                          }}
                        >
                          确认隐藏
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => setConfirmDismiss(null)}
                        >
                          取消
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="delete-button"
                        disabled={busy || !onDismiss}
                        onClick={() => setConfirmDismiss(failed.id)}
                      >
                        隐藏失败记录
                      </button>
                    )
                  ) : null}
                </div>
              ) : null}
              <button
                disabled={busy || !!activeGeneration || !onGenerate}
                onClick={() => onGenerate?.(line.id)}
              >
                {activeGeneration
                  ? "生成中…"
                  : failed
                    ? "重新生成对白 TTS"
                    : "生成对白 TTS"}
              </button>
              <button
                type="button"
                className="dialogue-candidate-toggle"
                aria-expanded={candidatesExpanded}
                onClick={() =>
                  setCandidateOpen((current) => ({
                    ...current,
                    [line.id]: !candidatesExpanded,
                  }))
                }
              >
                <span>对白候选</span>
                <span>{candidates.length} 条 · {candidatesExpanded ? "收起" : "展开"}</span>
              </button>
              {candidatesExpanded ? (
                <div className="dialogue-candidate-list">
                  {candidates.length === 0 ? <p>尚无成功候选。</p> : null}
                  {candidates.map((generation) => {
                    const candidate = generation.output_asset_id
                      ? assets.get(generation.output_asset_id)
                      : undefined;
                    const isSelected =
                      generation.output_asset_id === item?.selected_audio_asset_id;
                    const canSelect =
                      generation.allowed_actions.includes("select_dialogue_audio");
                    return (
                      <div className="dialogue-audio-candidate" key={generation.id}>
                        {candidate ? (
                          <audio
                            aria-label={`试听对白候选 ${generation.id.slice(0, 6)}`}
                            controls
                            preload="none"
                            src={candidate.content_url}
                          />
                        ) : null}
                        <div className="dialogue-audio-candidate-actions">
                          {isSelected ? (
                            <strong>当前已选 · {generation.id.slice(0, 6)}</strong>
                          ) : canSelect ? (
                            <button
                              disabled={busy || !onSelect}
                              onClick={() => onSelect?.(line.id, generation.id)}
                            >
                              选择候选 {generation.id.slice(0, 6)}
                            </button>
                          ) : (
                            <span>项目当前不可编辑</span>
                          )}
                          {generation.allowed_actions.includes("dismiss_history") &&
                          confirmDismiss !== generation.id ? (
                            <button
                              type="button"
                              className="delete-button"
                              aria-label={`隐藏候选 ${generation.id.slice(0, 6)}`}
                              disabled={busy || !onDismiss}
                              onClick={() => setConfirmDismiss(generation.id)}
                            >
                              隐藏
                            </button>
                          ) : null}
                        </div>
                        {generation.inputs_outdated ? (
                          <p className="dialogue-candidate-notice">
                            该候选生成后的正文、音色或表演参数已经变化；仍可试听并选择，如需匹配当前设置请重新生成。
                          </p>
                        ) : null}
                        {confirmDismiss === generation.id ? (
                          <div className="dialogue-dismiss-confirm">
                            <span>隐藏后不再显示；废弃产物可随后在资产中心永久清理。</span>
                            <button
                              type="button"
                              className="delete-button"
                              aria-label={`确认隐藏候选 ${generation.id.slice(0, 6)}`}
                              disabled={busy || !onDismiss}
                              onClick={() => {
                                setConfirmDismiss(null);
                                onDismiss?.(generation.id);
                              }}
                            >
                              确认隐藏
                            </button>
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => setConfirmDismiss(null)}
                            >
                              取消
                            </button>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </section>
          </article>
        );
            })}
          </div>
          <footer className="dialogue-timing-actions">
            <button disabled={busy || !ready || !onSetTiming} onClick={autoTiming}>
              按真实音频自动校准时长
            </button>
            <p>自动校准会留基础停顿；Director Agent 可按镜头和情绪设置更大的余量。</p>
          </footer>
        </div>
      ) : null}
    </section>
  );
}

function DialogueRecipeControls({
  line,
  item,
  recipe,
  busy,
  canEdit,
  onSave,
}: {
  line: DialogueLine;
  item: DialogueAudio;
  recipe: ProviderRecipeView;
  busy: boolean;
  canEdit: boolean;
  onSave?: (dialogueLineId: string, recipeParams: Record<string, unknown>) => void;
}) {
  const effectiveParams = { ...item.recipe_params };
  if (!(recipe.recipe.id in effectiveParams)) {
    effectiveParams[recipe.recipe.id] = Object.fromEntries(
      recipe.editable_params.map((field) => [
        field.key,
        field.key === "performance_instruction" && line.delivery.trim()
          ? line.delivery.trim()
          : field.default,
      ]),
    );
  }
  const savedKey = JSON.stringify(effectiveParams);
  const [draft, setDraft] = useState<Record<string, unknown>>(effectiveParams);
  useEffect(() => setDraft(effectiveParams), [line.id, savedKey]);
  if (!recipe.editable_params.length) return null;
  const current = (draft[recipe.recipe.id] ?? {}) as Record<string, SettingValue>;
  const dirty = JSON.stringify(draft) !== savedKey;
  const update = (key: string, value: SettingValue) => {
    const defaults = Object.fromEntries(
      recipe.editable_params.map((field) => [field.key, field.default]),
    );
    setDraft({
      ...draft,
      [recipe.recipe.id]: { ...defaults, ...current, [key]: value },
    });
  };
  return (
    <fieldset className="dialogue-recipe-controls" disabled={busy || !canEdit}>
      <legend>{recipe.plugin_label} · {recipe.recipe.label}</legend>
      {recipe.editable_params.map((field) => (
        <div key={field.key}>
          <SettingField
            field={field}
            label={
              field.key === "performance_instruction"
                ? "表演指示（语气、情绪、语速、停顿）"
                : field.label
            }
            value={current[field.key] ?? field.default}
            onChange={(value) => update(field.key, value)}
          />
          {field.help ? <small>{field.help}</small> : null}
        </div>
      ))}
      <button
        type="button"
        className="secondary-button"
        disabled={busy || !canEdit || !onSave || !dirty}
        onClick={() => onSave?.(line.id, draft)}
      >
        保存对白表演参数
      </button>
      {dirty && item.selected_audio_asset_id ? (
        <small>保存后会清除这句已选音频，并重新校准本段对白时序。</small>
      ) : null}
    </fieldset>
  );
}

function SegmentText({
  segment,
  character,
  timingWarnings,
}: {
  segment: ShotSegment;
  character: (id: string) => string;
  timingWarnings: DialogueTimingWarning[];
}) {
  const timing = timingWarnings.find((item) => item.segment_id === segment.id);
  return (
    <section className="story-segment-text">
      <p>{segment.action}</p>
      {segment.dialogue_lines.map((l, i) => (
        <blockquote key={i}>
          <small>
            {l.character_id === null ? l.speaker_label : character(l.character_id)} · {l.delivery}
          </small>
          <p>{l.text}</p>
        </blockquote>
      ))}
      <small>预计 {segment.duration_estimate_seconds} 秒</small>
      {timing ? (
        <em role="note">
          对白约需 {timing.estimated_seconds} 秒，超过预估时长；建议加长 Segment 或拆分，不压缩台词
        </em>
      ) : null}
      {segment.boundary_from_previous ? (
        <p>
          延续上一片段 · {segment.boundary_from_previous.reason}：
          {segment.boundary_from_previous.continuity_instruction}
        </p>
      ) : null}
    </section>
  );
}
function ShotText({
  shot,
  character,
}: {
  shot: Shot;
  character: (id: string) => string;
}) {
  return (
    <>
      <p>{shot.action}</p>
      <p>构图：{shot.composition}</p>
      <p>摄影机运动：{shot.camera_movement}</p>
      <p>
        可见角色：{shot.visible_character_ids.map(character).join("、") || "无"}
      </p>
      {shot.audio_direction ? <p>声音：{shot.audio_direction}</p> : null}
      {shot.transition_in ? <p>入镜转场：{shot.transition_in}</p> : null}
    </>
  );
}
