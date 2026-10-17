import { afterEach, describe, expect, it, vi } from "vitest";

import { StoryRailApiError } from "../api";
import { playgroundApi } from "./api";

const runId = "a".repeat(32);
const assetId = "b".repeat(32);

function response(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as Response;
}

const parameters = {
  prompt: "雨夜站台",
  aspect_ratio: "16:9",
  duration_seconds: 6,
  seed: 1,
  first_frame_asset_id: null,
  last_frame_asset_id: null,
};

const run = {
  id: runId,
  capability: "video.fl2va",
  capability_label: "首尾帧视频",
  phase: "submitting",
  progress: 0,
  message: "正在提交首尾帧视频任务。",
  parameters,
  input_asset_ids: [],
  seed: 1,
  plugin_id: null,
  plugin_version: null,
  external_id: null,
  output_asset_id: null,
  result: null,
  error_code: null,
  cancellation_requested: false,
  retry_of: null,
  note: null,
  dismissed: false,
  provider: null,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
  recovery: {
    failure_origin: null,
    retry_policy: "wait_same_generation",
    automatic_retry_allowed: false,
  },
  allowed_actions: ["cancel", "set_note"],
};

const capability = {
  id: "video.fl2va",
  label: "首尾帧视频",
  execution: "async",
  group: "audio",
  available: true,
  notes: "",
  recipe: null,
};

const snapshot = {
  schema_version: 2,
  revision: 3,
  capabilities: [capability],
  runs: [run],
  assets: [],
};

const receipt = {
  command_id: "c".repeat(64),
  status: "succeeded",
  old_revision: 3,
  new_revision: 4,
  decision_summary: "已提交实验。",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("playgroundApi", () => {
  it("解析合法快照", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(snapshot)));
    const loaded = await playgroundApi.get();
    expect(loaded.revision).toBe(3);
    expect(loaded.runs[0].capability_label).toBe("首尾帧视频");
  });

  it("拒绝多余字段或错误的 phase", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ ...snapshot, extra: true })),
    );
    await expect(playgroundApi.get()).rejects.toThrow(
      "服务端返回了无法识别的 Playground 数据。",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          ...snapshot,
          runs: [{ ...run, phase: "paused" }],
        }),
      ),
    );
    await expect(playgroundApi.get()).rejects.toThrow(
      "服务端返回了无法识别的 Playground 数据。",
    );
  });

  it("submitRun 发送信封形状并以 ui: 开头生成幂等键", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(response({ receipt, data: { run } }));
    vi.stubGlobal("fetch", fetcher);
    const submitted = await playgroundApi.submitRun(
      "video.fl2va",
      parameters,
      null,
    );
    expect(submitted.id).toBe(runId);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/playground/commands");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual([
      "arguments",
      "idempotency_key",
      "name",
    ]);
    expect(body.name).toBe("playground.submit_run");
    expect(String(body.idempotency_key)).toMatch(/^ui:/);
    expect(body.arguments).toEqual({
      capability: "video.fl2va",
      parameters,
      note: null,
    });
    expect("expected_revision" in body).toBe(false);
  });

  it("上传时规范化 Content-Type 并带上 filename 查询参数", async () => {
    const asset = {
      id: assetId,
      media_type: "audio/wav",
      byte_count: 12,
      sha256: "d".repeat(64),
      relative_path: "assets/audio/imported/参考-0123456789.wav",
      duration_seconds: 1.5,
      origin: { kind: "imported" },
      created_at: "2026-01-01T00:00:00+00:00",
      display_name: "参考",
      content_url: `/api/playground/assets/${assetId}/content`,
      is_in_use: false,
      usage_reasons: [],
      allowed_actions: ["copy_to_project", "delete"],
    };
    const fetcher = vi.fn().mockResolvedValue(response({ asset }));
    vi.stubGlobal("fetch", fetcher);
    const file = new File(["wave"], "参考.wav", { type: "" });
    const uploaded = await playgroundApi.uploadAsset(file);
    expect(uploaded.media_type).toBe("audio/wav");
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "/api/playground/assets/media?filename=%E5%8F%82%E8%80%83.wav",
    );
    expect(init.headers).toEqual({ "Content-Type": "audio/wav" });
    expect(init.body).toBe(file);
  });

  it("把服务端错误翻译成保留 code 与 message 的 StoryRailApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response(
          {
            error: {
              code: "provider_unavailable",
              message: "对应模型服务未配置。",
              recoverable: true,
              origin: "provider",
              state_changed: false,
              retry_policy: "none",
              automatic_retry_allowed: false,
            },
          },
          409,
        ),
      ),
    );
    const caught = await playgroundApi
      .submitRun("video.fl2va", parameters, null)
      .catch((error: unknown) => error);
    expect(caught).toBeInstanceOf(StoryRailApiError);
    expect((caught as StoryRailApiError).code).toBe("provider_unavailable");
    expect((caught as StoryRailApiError).message).toBe("对应模型服务未配置。");
  });
});
