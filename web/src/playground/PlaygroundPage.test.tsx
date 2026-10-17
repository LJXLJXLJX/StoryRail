import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PlaygroundCapabilityInfo,
  PlaygroundRun,
  PlaygroundRunPhase,
  PlaygroundSnapshot,
} from "../api";
import { PlaygroundPage } from "./PlaygroundPage";
import { usePlaygroundScheduler } from "./usePlaygroundScheduler";

const capability: PlaygroundCapabilityInfo = {
  id: "minimax_h3.fl2va",
  label: "首尾帧视频",
  execution: "async",
  group: "video",
  available: true,
  notes: "",
  recipe: null,
};

const run: PlaygroundRun = {
  id: "a".repeat(32),
  capability: "minimax_h3.fl2va",
  capability_label: "首尾帧视频",
  phase: "running",
  progress: 0.4,
  message: "生成中",
  parameters: {},
  input_asset_ids: [],
  seed: 1,
  plugin_id: null,
  plugin_version: null,
  external_id: "task-1",
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

function snapshot(phase: PlaygroundRunPhase | null): PlaygroundSnapshot {
  return {
    schema_version: 2,
    revision: 1,
    capabilities: [capability],
    runs: phase === null ? [] : [{ ...run, phase }],
    assets: [],
  };
}

function response(value: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => value,
  } as Response;
}

describe("usePlaygroundScheduler", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
  });

  function setup(phase: PlaygroundRunPhase | null) {
    const get = vi.fn();
    const refresh = vi.fn();
    const onSnapshot = vi.fn();
    const onError = vi.fn();
    renderHook(() =>
      usePlaygroundScheduler({
        snapshot: snapshot(phase),
        onSnapshot,
        onError,
        api: { get, refresh },
        activeIntervalMs: 1250,
        idleIntervalMs: 10000,
        maxBackoffMs: 30000,
      }),
    );
    return { get, refresh, onSnapshot, onError };
  }

  it("有非终态 run 时按 1250ms 调用 refresh", async () => {
    const { refresh, get } = setup("running");
    refresh.mockResolvedValue(snapshot("running"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1249);
    });
    expect(refresh).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(get).not.toHaveBeenCalled();
  });

  it("没有活动 run 时按 10000ms 调用 get", async () => {
    const { get, refresh } = setup("succeeded");
    get.mockResolvedValue(snapshot("succeeded"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9999);
    });
    expect(get).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(get).toHaveBeenCalledTimes(1);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("页面隐藏时不再发请求，恢复可见后立即调度", async () => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    const { get } = setup(null);
    get.mockResolvedValue(snapshot(null));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(get).not.toHaveBeenCalled();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(get).toHaveBeenCalledTimes(1);
  });
});

describe("PlaygroundPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("加载快照并渲染标题、副标题与能力名", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(snapshot(null))));
    render(<PlaygroundPage onExit={vi.fn()} />);
    expect(
      screen.getByRole("heading", { name: "Playground" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "与故事无关的模型实验台。产物保存在 Playground 资产库，需要时可复制到项目。",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "首尾帧视频" }),
    ).toBeInTheDocument();
    // 绑定是全局设置，Playground 顶栏必须提供切换入口（改完会刷新能力列表）。
    expect(screen.getByText("Provider 设置")).toBeInTheDocument();
  });
});
