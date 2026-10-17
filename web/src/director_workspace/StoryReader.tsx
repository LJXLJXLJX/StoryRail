import { LocationBinding } from "./location";
import { DraftProtection } from "./draft_protection";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  DialogueTimingWarning,
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
import { copyText } from "./clipboard";
import { newSceneDraft } from "./script_draft";
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
  const liveShot = liveScene?.shots.find(
    (s) => s.id === target?.id || s.segments.some((g) => g.id === target?.id),
  );
  const liveSegment = liveShot?.segments.find((s) => s.id === target?.id);
  const previous = useRef<{
    scene?: Scene;
    shot?: Shot;
    segment?: ShotSegment;
  }>({});
  if (
    liveScene &&
    (target?.level === "scene" ||
      (liveShot && (target?.level === "shot" || liveSegment)))
  )
    previous.current = {
      scene: liveScene,
      shot: liveShot,
      segment: liveSegment,
    };
  const scene = liveScene ?? (dirty ? previous.current.scene : undefined);
  const shot = liveShot ?? (dirty ? previous.current.shot : undefined);
  const segment = liveSegment ?? (dirty ? previous.current.segment : undefined);
  const [lastParent, setLastParent] = useState<StoryTarget | null>(null);
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
    if (target?.level === "segment" && shot)
      setLastParent({ level: "shot", id: shot.id, sceneId: target.sceneId });
    else if (target?.level === "shot" && scene)
      setLastParent({ level: "scene", id: scene.id, sceneId: scene.id });
  }, [target, shot?.id, scene?.id]);
  useEffect(() => {
    if (
      !target ||
      (liveScene &&
        (target.level === "scene" ||
          (liveShot && (target.level === "shot" || liveSegment))))
    )
      return;
    // Keep dirty input mounted after deletion until the user explicitly leaves it.
    if (dirty) {
      setNotice("当前节点已被删除，未保存输入仍保留。");
      return;
    }
    const parent =
      lastParent?.level === "shot" &&
      scene?.shots.some((s) => s.id === lastParent.id)
        ? lastParent
        : scene
          ? { level: "scene" as const, id: scene.id, sceneId: scene.id }
          : null;
    setTarget(parent);
    setNotice("当前节点已被删除，已返回仍存在的上级。");
  }, [target, scene, shot, segment, dirty, lastParent]);
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
        : (shot?.segments ?? []);
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
                disabled={!liveScene || (target.level !== "scene" && !liveShot) || (target.level === "segment" && !liveSegment)}
                onClick={async () => {
                  const location = [
                    `场景 ${sceneIndex + 1}`,
                    ...(shot ? [`镜头 ${scene.shots.indexOf(shot) + 1}`] : []),
                    ...(segment ? [`片段 ${shot!.segments.indexOf(segment) + 1}`] : []),
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
              {segment ? ` / 片段 ${shot!.segments.indexOf(segment) + 1}` : ""}
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
                <h2>完整场景内容</h2>
                {scene.shots.map((s, i) => (
                  <section key={s.id}>
                    <button
                      className="text-button"
                      onClick={() =>
                        choose({ level: "shot", sceneId: scene.id, id: s.id })
                      }
                    >
                      镜头 {i + 1}
                    </button>
                    <ShotText shot={s} character={character} timingWarnings={snapshot.dialogue_timing_warnings} />
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
                <ShotText shot={shot} character={character} timingWarnings={snapshot.dialogue_timing_warnings} />
                {shot.segments.map((s, i) => {
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
                        打开片段 {i + 1}
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
            ) : segment && shot ? (
              <>
                <SegmentText
                  segment={segment}
                  character={character}
                  timingWarnings={snapshot.dialogue_timing_warnings}
                />
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
                      shotIndex={scene.shots.indexOf(shot)}
                      segmentIndex={shot.segments.indexOf(segment)}
                      segmentCount={shot.segments.length}
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
                      for (const h of s.shots)
                        for (const g of h.segments)
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
  timingWarnings,
}: {
  shot: Shot;
  character: (id: string) => string;
  timingWarnings: DialogueTimingWarning[];
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
      {shot.segments.map((s, i) => (
        <section key={s.id}>
          <h3>片段 {i + 1}</h3>
          <SegmentText segment={s} character={character} timingWarnings={timingWarnings} />
        </section>
      ))}
    </>
  );
}
