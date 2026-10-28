// 脚本结构修改：Segment 拆分 / 合并与相邻 Scene 合并的请求形状与服务端影响预览解析。
// 覆盖是否合法只由 Core 判断；这里不复制 §4.1 规则。

import { isRecord } from "./schema_check";
import type { DialogueLine, SegmentBoundary } from "./types";

/** 一个 Segment 的完整可编辑字段；shot_ids 必须是本 Scene 中连续的 Shot 区间。 */
export interface ScriptSegmentDraft {
  shot_ids: string[];
  duration_estimate_seconds: number;
  action: string;
  dialogue_lines: DialogueLine[];
  boundary_from_previous: SegmentBoundary | null;
}

export type ScriptOperation =
  | {
      op: "split_segment";
      segment_id: string;
      preserve_id: "first" | "second";
      first: ScriptSegmentDraft;
      second: ScriptSegmentDraft;
    }
  | {
      op: "merge_adjacent_segments";
      left_segment_id: string;
      right_segment_id: string;
      preserve_id: "left" | "right";
      merged: ScriptSegmentDraft;
    }
  | {
      op: "merge_adjacent_scenes";
      left_scene_id: string;
      right_scene_id: string;
    };

export interface ScriptOperationsPatch {
  scope: { scene_ids: string[] };
  operations: ScriptOperation[];
}

export type ScriptChange = {
  name: "script.apply_operations";
  arguments: ScriptOperationsPatch;
};

/** project.preview_impact 对 script.apply_operations 的返回；不含地点专属字段。 */
export interface ScriptImpact {
  revision: number;
  command_name: string;
  will_write: boolean;
  high_impact: boolean;
  changed_ids: string[];
  invalidated: string[];
  preserved: string[];
}

export function parseScriptImpact(value: unknown): ScriptImpact {
  const strings = (items: unknown) =>
    Array.isArray(items) && items.every((item) => typeof item === "string");
  if (
    !isRecord(value) ||
    typeof value.revision !== "number" ||
    typeof value.command_name !== "string" ||
    typeof value.will_write !== "boolean" ||
    typeof value.high_impact !== "boolean" ||
    !strings(value.changed_ids) ||
    !strings(value.invalidated) ||
    !strings(value.preserved)
  ) {
    throw new Error("脚本修改影响预览格式不正确。");
  }
  return value as unknown as ScriptImpact;
}
