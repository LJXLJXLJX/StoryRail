// 手写跨字段 refine。结构、枚举和单字段约束由生成的 validation.ts 负责。
// 每条规则注明领域来源；这里不复制状态机，只拒绝与 Core 不变量矛盾的响应。

import {
  isRecord,
  isVideoSeed,
} from "./schema_check";
import {
  type Scene,
  type StructuredDirectorSnapshot,
} from "./types";

/** 来源：WorkspaceLayers.__post_init__。各层必须按旁白 → 关键帧 → 视频 → 成片累加。 */
export function refineWorkspaceLayers(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const narration = value.narration_unlocked === true;
  const keyframes = value.keyframes_unlocked === true;
  const videos = value.videos_unlocked === true;
  const finalAssembly = value.final_assembly_unlocked === true;
  if (keyframes && !narration) return false;
  if (videos && !keyframes) return false;
  if (finalAssembly && !videos) return false;
  return true;
}

/** 来源：Director run 的 waiting_reason 只在等待态出现。 */
export function refineActiveDirectorRun(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (value.status === "running") return value.waiting_reason === null;
  if (value.status === "waiting_user" || value.status === "waiting_jobs") {
    return typeof value.waiting_reason === "string" && value.waiting_reason.length > 0;
  }
  return false;
}

/** 来源：活动摘要的布尔值必须与计数一致。 */
export function refineWorkflow(value: unknown): boolean {
  if (!isRecord(value) || !isRecord(value.activity_summary)) return false;
  const count = value.activity_summary.active_generation_count;
  if (typeof count !== "number") return false;
  return value.activity_summary.has_active_generations === count > 0;
}

/** 来源：narration Scene 可以暂无 Shot；drama Scene 至少一个。覆盖关系只由 Core 校验。 */
export function refineScene(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !Array.isArray(value.shots) ||
    !Array.isArray(value.segments) ||
    !Array.isArray(value.narration_cues)
  ) {
    return false;
  }
  return value.shots.length > 0 || value.driver === "narration";
}

/**
 * 来源：生产基线 revision 与 scenes 同生同灭，且不超过当前脚本 revision。
 * Scene 级规则再走 refineScene。
 */
export function refineDirectorScript(value: unknown): boolean {
  if (!isRecord(value) || typeof value.revision !== "number" || !Array.isArray(value.scenes)) {
    return false;
  }
  const baselineRevision = value.production_baseline_revision;
  const baselineScenes = value.production_baseline_scenes;
  if ((baselineRevision === null) !== (baselineScenes === null)) return false;
  if (typeof baselineRevision === "number" && baselineRevision > value.revision) return false;
  if (!value.scenes.every(refineScene)) return false;
  return baselineScenes === null || (Array.isArray(baselineScenes) && baselineScenes.every(refineScene));
}

/** 来源：成片首段没有接缝；其后只允许硬切或系统 seam_blend。 */
export function refineFinalAssembly(value: unknown): boolean {
  if (!isRecord(value) || !Array.isArray(value.clips) || value.clips.length === 0) return false;
  return value.clips.every((clip, index) => {
    if (!isRecord(clip)) return false;
    if (index === 0) return clip.transition_from_previous === null;
    return clip.transition_from_previous === null || clip.transition_from_previous === "seam_blend";
  });
}

/** 来源：使用原因按 code 唯一，is_in_use 与原因列表同生同灭。 */
export function refineAsset(value: unknown): boolean {
  if (!isRecord(value) || !Array.isArray(value.usage_reasons)) return false;
  const codes = value.usage_reasons.map((reason) => (isRecord(reason) ? reason.code : undefined));
  if (new Set(codes).size !== value.usage_reasons.length) return false;
  return value.is_in_use === value.usage_reasons.length > 0;
}

/** 来源：Segment 视频与图片 seed 是十进制字符串（63 位）；其它 Generation 的 seed 是整数或 null。 */
const STRING_SEED_KINDS = new Set(["segment_video", "character_look_sheet", "location_master_image", "location_view_image", "keyframe_image"]);

export function refineGeneration(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (value.seed !== null && value.seed !== undefined) {
    if (typeof value.kind === "string" && STRING_SEED_KINDS.has(value.kind)) {
      if (!isVideoSeed(value.seed)) return false;
    } else if (typeof value.seed !== "number" || !Number.isInteger(value.seed)) {
      return false;
    }
  }
  return true;
}

/** 来源：图片/音色设置的 selected 必须出现在 available 中。 */
/**
 * 来源：快照状态与已建立计划必须一致。
 * 成片层解锁后上游回改不清空解锁，因此 reviewing_final 可以暂时没有装配；
 * approved 必须同时有装配和 Approval。Director run 进行中可以提前持有装配计划。
 */
export function snapshotConsistencyError(value: StructuredDirectorSnapshot): string | null {
  const languages = value.narration_languages;
  const narrator = value.reference_library.narrator;
  for (const language of ["zh", "en"] as const) {
    const enabled = languages.includes(language);
    if (narrator !== null && (narrator[language] !== null) !== enabled) {
      return "旁白音色与项目所选语言不一致。";
    }
    if (value.director_script?.scenes.some((scene) =>
      scene.narration_cues.some((cue) => (cue[language] !== null) !== enabled))) {
      return "旁白轨道与项目所选语言不一致。";
    }
  }
  const status = value.status;
  const directorScript = value.director_script;
  const keyframePlan = value.keyframe_plan;
  const finalAssembly = value.final_assembly ?? null;
  const finalApproval = value.final_approval;
  const activeDirectorRun = value.active_director_run;
  const scriptRequired =
    status === "reviewing_script" ||
    status === "reviewing_narration" ||
    status === "reviewing_videos" ||
    status === "reviewing_final" ||
    status === "approved";
  if (scriptRequired !== (directorScript !== null)) {
    return "结构化导演脚本与项目状态不一致。";
  }
  if (
    (status === "reviewing_keyframes" || status === "reviewing_final" || status === "approved") &&
    keyframePlan === null
  ) {
    return "Segment Keyframe 计划与项目状态不一致。";
  }
  if (
    keyframePlan !== null &&
    status !== "reviewing_keyframes" &&
    status !== "reviewing_videos" &&
    status !== "reviewing_final" &&
    status !== "approved"
  ) {
    return "Segment Keyframe 计划与项目状态不一致。";
  }
  if (status === "approved" && finalAssembly === null) {
    return "最终成片装配计划与项目状态不一致。";
  }
  if (
    finalAssembly !== null &&
    status !== "reviewing_final" &&
    status !== "approved" &&
    !(activeDirectorRun !== null && activeDirectorRun.kind === "director")
  ) {
    return "最终成片装配计划与项目状态不一致。";
  }
  if ((status === "approved") !== (finalApproval !== null)) {
    return "最终 Approval 与项目状态不一致。";
  }
  return null;
}

function editableTrack(track: Scene["narration_cues"][number]["zh"]) {
  if (track === null) return null;
  return {
    text: track.text,
    seed: track.seed,
    selected_audio_asset_id: track.selected_audio_asset_id,
    recipe_params: track.recipe_params,
  };
}

// 整卡手工保存请求使用 v33 写入形状：Shot 无 segments，Segment 用本 Scene 新 shots 数组的序号。
export function editableScenePayload(scene: Scene) {
  const positions = new Map(scene.shots.map((shot, index) => [shot.id, index]));
  return {
    ...scene,
    id: scene.id.startsWith("new:") ? null : scene.id,
    shots: scene.shots.map((shot) => ({
      ...shot,
      id: shot.id.startsWith("new:") ? null : shot.id,
    })),
    segments: scene.segments.map((segment) => ({
      id: segment.id.startsWith("new:") ? null : segment.id,
      shot_indexes: segment.shot_ids.map((shotId) => {
        const index = positions.get(shotId);
        if (index === undefined) {
          throw new Error("Segment 覆盖了当前 Scene 中不存在的 Shot。");
        }
        return index;
      }),
      duration_estimate_seconds: segment.duration_estimate_seconds,
      action: segment.action,
      dialogue_lines: segment.dialogue_lines,
      boundary_from_previous: segment.boundary_from_previous,
    })),
    // 只回传编辑器字段；时长与时间基准是 Core 派生的只读投影。
    narration_cues: scene.narration_cues.map((cue) => ({
      id: cue.id,
      zh: editableTrack(cue.zh),
      en: editableTrack(cue.en),
    })),
  };
}
