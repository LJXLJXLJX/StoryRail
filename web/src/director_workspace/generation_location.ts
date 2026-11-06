import type { ReferenceGeneration, StructuredDirectorSnapshot } from "../api";
import type { StoryTarget } from "../api/projection";

export interface GenerationLocation {
  /** 任务所在位置的可读描述，如“场景 2 · 片段 3”。 */
  place: string;
  /** 可在故事导航中直接打开的位置；不属于 Scene/Segment 的任务为 null。 */
  target: StoryTarget | null;
}

const kindLabels: Record<ReferenceGeneration["kind"], string> = {
  character_look_sheet: "造型设定图",
  character_voice: "角色音色",
  narrator_voice: "旁白音色",
  narration_audio: "旁白 TTS",
  dialogue_audio: "对白 TTS",
  generated_audio: "生成音频",
  audio_effect: "音频处理",
  audio_trim: "音频截取",
  video_audio_voice: "人声分离",
  video_audio_background: "背景分离",
  video_audio_remix: "音频混音",
  location_image: "地点图片",
  panorama_capture: "全景取景",
  keyframe_image: "关键帧",
  video_reference_image: "其他图片",
  segment_video: "视频",
  video_frame: "抽帧",
  video_upscale: "超分",
  final_video: "最终成片",
  scene_final_video: "Scene 成片",
  scene_animatic: "Animatic",
};

export function generationKindLabel(kind: ReferenceGeneration["kind"]) {
  return kindLabels[kind];
}

/** 只按当前快照中的 target 关系定位任务所属 Scene / Segment，不推断其它业务规则。 */
export function locateGeneration(
  snapshot: Pick<
    StructuredDirectorSnapshot,
    "director_script" | "keyframe_plan" | "video_plan"
  >,
  generation: ReferenceGeneration,
): GenerationLocation {
  const scenes = snapshot.director_script?.scenes ?? [];
  const sceneLocation = (sceneId: string): GenerationLocation | null => {
    const index = scenes.findIndex((scene) => scene.id === sceneId);
    return index < 0
      ? null
      : {
          place: `场景 ${index + 1}`,
          target: { level: "scene", sceneId, id: sceneId },
        };
  };
  const segmentLocation = (
    match: (segment: (typeof scenes)[number]["segments"][number]) => boolean,
  ): GenerationLocation | null => {
    for (const [sceneIndex, scene] of scenes.entries()) {
      const segmentIndex = scene.segments.findIndex(match);
      if (segmentIndex >= 0) {
        const segment = scene.segments[segmentIndex];
        return {
          place: `场景 ${sceneIndex + 1} · 片段 ${segmentIndex + 1}`,
          target: { level: "segment", sceneId: scene.id, id: segment.id },
        };
      }
    }
    return null;
  };
  const keyframeSegmentId = (keyframeId: string) =>
    snapshot.keyframe_plan?.segments.find(
      (item) =>
        item.start_keyframe_id === keyframeId ||
        item.end_keyframe_id === keyframeId,
    )?.segment_id;
  const id = generation.target_id;
  let located: GenerationLocation | null = null;
  switch (generation.kind) {
    case "segment_video":
    case "video_upscale":
      located = segmentLocation((segment) => segment.id === id);
      break;
    case "keyframe_image":
    case "video_frame": {
      const segmentId = keyframeSegmentId(id);
      located = segmentId
        ? segmentLocation((segment) => segment.id === segmentId)
        : null;
      break;
    }
    case "video_reference_image": {
      const segmentId = snapshot.video_plan?.segments.find((item) =>
        (item.reference_images ?? []).some((image) => image.id === id),
      )?.segment_id;
      located = segmentId
        ? segmentLocation((segment) => segment.id === segmentId)
        : null;
      break;
    }
    case "dialogue_audio":
      located = segmentLocation((segment) =>
        segment.dialogue_lines.some((line) => line.id === id),
      );
      break;
    case "narration_audio": {
      const scene = scenes.find((item) =>
        item.narration_cues.some((cue) => cue.id === id),
      );
      located = scene ? sceneLocation(scene.id) : null;
      break;
    }
    case "scene_final_video":
    case "scene_animatic":
      located = sceneLocation(id);
      break;
    case "character_look_sheet":
    case "character_voice":
    case "narrator_voice":
      return { place: "引用库", target: null };
    case "location_image":
    case "panorama_capture":
      return { place: "地点库", target: null };
    case "final_video":
      return { place: "项目", target: null };
    default:
      return { place: "资产库", target: null };
  }
  return located ?? { place: "已不在当前脚本中", target: null };
}
