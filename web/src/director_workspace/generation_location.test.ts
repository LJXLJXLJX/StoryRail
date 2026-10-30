import { describe, expect, it } from "vitest";
import type { ReferenceGeneration, StructuredDirectorSnapshot } from "../api";
import { locateGeneration } from "./generation_location";

const sceneA = "a".repeat(32);
const sceneB = "b".repeat(32);
const segment = (id: string, dialogueIds: string[] = []) => ({
  id,
  dialogue_lines: dialogueIds.map((lineId) => ({ id: lineId })),
});
const snapshot = {
  director_script: {
    scenes: [
      { id: sceneA, narration_cues: [{ id: "cue-1" }], segments: [segment("seg-a1")] },
      {
        id: sceneB,
        narration_cues: [],
        segments: [segment("seg-b1"), segment("seg-b2", ["line-1"])],
      },
    ],
  },
  keyframe_plan: {
    segments: [
      { segment_id: "seg-b1", start_keyframe_id: "kf-start", end_keyframe_id: "kf-end" },
    ],
  },
  video_plan: {
    segments: [{ segment_id: "seg-b2", reference_images: [{ id: "ref-1" }] }],
  },
} as unknown as StructuredDirectorSnapshot;
const generation = (kind: ReferenceGeneration["kind"], targetId: string) =>
  ({ kind, target_id: targetId }) as ReferenceGeneration;

describe("locateGeneration", () => {
  it.each([
    ["segment_video", "seg-b2", "场景 2 · 片段 2", "seg-b2"],
    ["video_upscale", "seg-a1", "场景 1 · 片段 1", "seg-a1"],
    ["keyframe_image", "kf-end", "场景 2 · 片段 1", "seg-b1"],
    ["video_frame", "kf-start", "场景 2 · 片段 1", "seg-b1"],
    ["video_reference_image", "ref-1", "场景 2 · 片段 2", "seg-b2"],
    ["dialogue_audio", "line-1", "场景 2 · 片段 2", "seg-b2"],
  ] as const)("%s 定位到所属 Segment", (kind, targetId, place, segmentId) => {
    const location = locateGeneration(snapshot, generation(kind, targetId));
    expect(location.place).toBe(place);
    expect(location.target).toMatchObject({ level: "segment", id: segmentId });
  });

  it.each([
    ["narration_audio", "cue-1", "场景 1", sceneA],
    ["scene_final_video", sceneB, "场景 2", sceneB],
    ["scene_animatic", sceneA, "场景 1", sceneA],
  ] as const)("%s 定位到所属 Scene", (kind, targetId, place, sceneId) => {
    expect(locateGeneration(snapshot, generation(kind, targetId))).toEqual({
      place,
      target: { level: "scene", sceneId, id: sceneId },
    });
  });

  it("不属于 Scene/Segment 或已从脚本移除的任务不可导航", () => {
    expect(locateGeneration(snapshot, generation("location_image", "x"))).toEqual({ place: "地点库", target: null });
    expect(locateGeneration(snapshot, generation("character_look_sheet", "x"))).toEqual({ place: "引用库", target: null });
    expect(locateGeneration(snapshot, generation("final_video", "x"))).toEqual({ place: "项目", target: null });
    expect(locateGeneration(snapshot, generation("video_frame", "asset-id"))).toEqual({
      place: "已不在当前脚本中",
      target: null,
    });
    expect(locateGeneration(snapshot, generation("segment_video", "gone"))).toEqual({
      place: "已不在当前脚本中",
      target: null,
    });
  });
});
