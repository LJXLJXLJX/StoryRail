import { expect, it } from "vitest";
import { editableScenePayload } from "../api/refine";
import { newSceneDraft } from "./script_draft";

it("新 Scene 草稿默认一个 Shot 与一个覆盖它的 Segment", () => {
  const scene = newSceneDraft();
  expect(scene.driver).toBe("drama");
  expect(scene.shots).toHaveLength(1);
  expect(scene.segments).toHaveLength(1);
  expect(scene.segments[0].shot_ids).toEqual([scene.shots[0].id]);
  expect(scene.segments[0].boundary_from_previous).toBeNull();
  expect(scene.segments[0].duration_estimate_seconds).toBeGreaterThanOrEqual(0.2);
});

it("新 Scene 草稿的临时 ID 与覆盖序号按 v33 整卡保存形状提交", () => {
  const scene = newSceneDraft();
  const payload = editableScenePayload(scene);
  expect(payload.id).toBeNull();
  expect(payload.shots.map((shot) => shot.id)).toEqual([null]);
  expect(payload.segments.map((segment) => segment.id)).toEqual([null]);
  expect(payload.segments[0].shot_indexes).toEqual([0]);
});
