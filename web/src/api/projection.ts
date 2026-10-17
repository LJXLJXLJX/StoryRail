export type StoryLevel = "scene" | "shot" | "segment";
export type StoryTarget = { level: StoryLevel; sceneId: string; id: string };
export type StoryNode = {
  id: string; kind: StoryLevel; scene_id: string; driver: "narration" | "drama";
  parent: { kind: string; id: string }; provenance: { source: string; field: string };
  title?: string; summary?: string; setting?: string; action?: string;
  composition?: string; camera_movement?: string; audio_direction?: string;
  transition_in?: string | null; duration_estimate_seconds?: number;
  shot_count?: number; segment_count?: number; visible_character_ids?: string[];
  narration?: { id: string; zh: StoryNarrationTrack; en: StoryNarrationTrack; timing: string;
    start_shot_id: string | null; end_shot_id: string | null }[];
  dialogue_lines?: {
    character_id: string | null; speaker_label: string | null; text: string; delivery: string;
  }[];
  boundary_from_previous?: { reason: string; continuity_instruction: string } | null;
  dialogue_timing?: { estimated_seconds: number; exceeds_duration: boolean } | null;
};
export type StoryNarrationTrack = {
  text: string; selected_audio_asset_id: string | null;
  duration_seconds: number | null; duration_source: string | null;
};
export type StoryProjection = {
  projection_version: number; project_id: string; revision: number;
  script_revision: number | null; level: "outline" | StoryLevel;
  scope: { project_id?: string; scene_ids?: string[] }; extensions: "text"[];
  text_mode: "preview" | "full"; text_preview_characters: number;
  parent_id?: string;
  items: StoryNode[]; total: number; next_cursor: string | null;
};
export type ProjectionRequest = {
  level: "outline" | StoryLevel; scope: { project_id: string } | { scene_ids: string[] };
  parent_id?: string; ids?: string[]; extensions?: "text"[]; limit?: number; cursor?: string;
};
type Check = (value: unknown) => boolean;
const text: Check = value => typeof value === "string";
const nullable = (check: Check): Check => value => value === null || check(value);
const array = (check: Check): Check => value => Array.isArray(value) && value.every(check);
const integer: Check = value => Number.isSafeInteger(value) && (value as number) >= 0;
const positive: Check = value => typeof value === "number" && Number.isFinite(value) && value > 0;
const oneOf = (...values: unknown[]): Check => value => values.includes(value);
const shape = (fields: Record<string, Check>): Check => value =>
  isRecord(value) && hasExactKeys(value, Object.keys(fields)) &&
  Object.entries(fields).every(([key, check]) => check(value[key]));
const narrationTrack = shape({
  text, selected_audio_asset_id: nullable(text), duration_seconds: nullable(positive),
  duration_source: oneOf(null, "selected_audio_asset"),
});
const narration = shape({
  id: text, zh: narrationTrack, en: narrationTrack, timing: text,
  start_shot_id: nullable(text), end_shot_id: nullable(text),
});
const dialogue = shape({
  character_id: nullable(text), speaker_label: nullable(text), text, delivery: text,
});
const dialogueTiming = nullable(shape({
  estimated_seconds: positive, exceeds_duration: value => typeof value === "boolean",
}));
const boundary = nullable(shape({
  reason: oneOf("model_constraint", "continuity_anchor", "control_boundary", "failure_cost"),
  continuity_instruction: text,
}));
const nodeFields: Record<string, Check> = {
  id: text, kind: oneOf("scene", "shot", "segment"), scene_id: text,
  driver: oneOf("narration", "drama"),
  parent: shape({ kind: oneOf("project", "scene", "shot"), id: text }),
  provenance: shape({ source: oneOf("project.json"), field: text }),
};
const detailFields: Record<string, Record<string, Check>> = {
  scene: { title: text, summary: text, shot_count: integer, narration: array(narration) },
  shot: {
    action: text, composition: text, camera_movement: text, audio_direction: text,
    visible_character_ids: array(text), transition_in: nullable(text), segment_count: integer,
  },
  segment: {
    action: text, duration_estimate_seconds: positive, dialogue_lines: array(dialogue),
    boundary_from_previous: boundary, dialogue_timing: dialogueTiming,
  },
};

// 阅读只请求默认故事字段或 text；生产 selection/dependencies 由既有详情入口处理。
export function parseStoryProjection(value: unknown): StoryProjection {
  if (!isRecord(value) || !shape({
    projection_version: oneOf(1), project_id: text, revision: integer,
    script_revision: nullable(integer), level: oneOf("outline", "scene", "shot", "segment"),
    scope: isRecord, extensions: array(oneOf("text")), text_mode: oneOf("preview", "full"),
    text_preview_characters: integer, items: array(isRecord), total: integer,
    next_cursor: nullable(text),
    ...('parent_id' in value ? {parent_id: text} : {}),
  })(value)) {
    throw new Error("故事读取结果格式不正确。");
  }
  const result = value as StoryProjection;
  const { scope, extensions, level, items } = result;
  if (result.parent_id !== undefined && (level !== 'segment' || items.some(item=>item.parent.id !== result.parent_id))) throw new Error('故事父节点范围不正确。');
  if (extensions.length > 1 || result.text_mode !== (extensions.length ? "full" : "preview") ||
    result.total < items.length || !(level === "outline"
      ? shape({ project_id: oneOf(result.project_id) })(scope)
      : shape({ scene_ids: array(text) })(scope) && scope.scene_ids!.length > 0 &&
        new Set(scope.scene_ids).size === scope.scene_ids!.length)) {
    throw new Error("故事读取范围或正文模式不正确。");
  }
  for (const node of items) {
    const kind = level === "outline" ? "scene" : level;
    if (node.kind !== kind || !shape({ ...nodeFields, ...detailFields[kind],
      ...(level === "scene" ? { setting: text } : {}),
    })(node) || node.parent.kind !== (kind === "scene" ? "project" : kind === "shot" ? "scene" : "shot") ||
      (level !== "outline" && !scope.scene_ids!.includes(node.scene_id)) ||
      (kind === "scene" && (node.id !== node.scene_id || node.parent.id !== result.project_id)) ||
      (kind === "shot" && node.parent.id !== node.scene_id)) {
      throw new Error("故事节点格式不正确。");
    }
  }
  return result;
}
import { hasExactKeys, isRecord } from "./validation";
