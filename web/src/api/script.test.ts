import { afterEach, expect, it, vi } from "vitest";
import { StoryRailApiError, structuredDirectorApi } from "../api";
import type { ScriptChange, ScriptImpact } from "../api";
import fixture from "../test/story_reader_fixture.json";

const projectId = "0".repeat(32);
const sceneId = "1".repeat(32);
const segmentId = "2".repeat(32);
const shotId = "3".repeat(32);
const change: ScriptChange = {
  name: "script.apply_operations",
  arguments: {
    scope: { scene_ids: [sceneId] },
    operations: [
      {
        op: "split_segment",
        segment_id: segmentId,
        preserve_id: "first",
        first: {
          shot_ids: [shotId],
          duration_estimate_seconds: 3,
          action: "前段。",
          dialogue_lines: [],
          boundary_from_previous: null,
        },
        second: {
          shot_ids: [shotId],
          duration_estimate_seconds: 3,
          action: "后段。",
          dialogue_lines: [],
          boundary_from_previous: {
            reason: "continuity_anchor",
            continuity_instruction: "延续同一姿态。",
          },
        },
      },
    ],
  },
};
const impact: ScriptImpact = {
  revision: 26,
  command_name: "script.apply_operations",
  will_write: true,
  high_impact: false,
  changed_ids: [segmentId],
  invalidated: [],
  preserved: ["asset_history", "generation_history"],
};
function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
afterEach(() => vi.restoreAllMocks());

it("影响预览通过 commands 的 project.preview_impact 提交并读取 data", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(response({ data: impact }));
  await expect(
    structuredDirectorApi.previewScriptChange(projectId, 26, change),
  ).resolves.toEqual(impact);
  expect(fetcher).toHaveBeenCalledWith(
    `/api/projects/${projectId}/structured-director/commands`,
    expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "project.preview_impact",
        expected_revision: 26,
        idempotency_key: "script-preview-26",
        arguments: {
          command: {
            ...change,
            expected_revision: 26,
            idempotency_key: "script-edit-26",
          },
        },
      }),
    }),
  );
});

it("结构修改通过 commands 的 script.apply_operations 提交并从 snapshot 刷新", async () => {
  const snapshot = fixture.continuity.production_snapshot;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(response({ snapshot }));
  const result = await structuredDirectorApi.applyScriptChange(projectId, 26, change);
  expect(result.revision).toBe(snapshot.revision);
  expect(fetcher).toHaveBeenCalledWith(
    `/api/projects/${projectId}/structured-director/commands`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "script.apply_operations",
        expected_revision: 26,
        idempotency_key: "script-edit-26",
        arguments: change.arguments,
      }),
    }),
  );
});

it("Core 拒绝时原样抛出服务端错误信息", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    response(
      {
        error: {
          code: "business_rule_rejected",
          message: "Scene「站台」的 Segment 1 覆盖必须恰好覆盖全部 Shot。",
          recoverable: true,
          origin: "core_domain",
          state_changed: false,
          retry_policy: "change_business_state_or_request",
          automatic_retry_allowed: false,
        },
      },
      409,
    ),
  );
  await expect(
    structuredDirectorApi.applyScriptChange(projectId, 26, change),
  ).rejects.toThrow("Scene「站台」的 Segment 1 覆盖必须恰好覆盖全部 Shot。");
  await expect(
    structuredDirectorApi.applyScriptChange(projectId, 26, change),
  ).rejects.toBeInstanceOf(StoryRailApiError);
});
