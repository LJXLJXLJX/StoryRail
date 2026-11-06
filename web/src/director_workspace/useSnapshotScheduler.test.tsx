import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StructuredDirectorSnapshot } from "../api";
import { useSnapshotScheduler } from "./useSnapshotScheduler";

const projectId = "a".repeat(32);

function snapshot(phase: "running" | "succeeded"): StructuredDirectorSnapshot {
  return {
    revision: 1,
    generations: [
      {
        id: "b".repeat(32),
        phase,
        progress: phase === "running" ? 0.5 : 1,
      },
    ],
  } as StructuredDirectorSnapshot;
}

function setup(active: boolean) {
  const get = vi.fn();
  const refreshActiveGenerations = vi.fn();
  const onSnapshot = vi.fn();
  const onError = vi.fn();
  const api = { get, refreshActiveGenerations };
  renderHook(() =>
    useSnapshotScheduler({
      projectId,
      snapshot: snapshot(active ? "running" : "succeeded"),
      onSnapshot,
      onError,
      api,
      activeIntervalMs: 1000,
      idleIntervalMs: 5000,
      maxBackoffMs: 30000,
    }),
  );
  return { get, refreshActiveGenerations, onSnapshot, onError };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

it("有活跃 Generation 时按 1250ms 自动观察，且 in-flight 不重入", async () => {
  const { refreshActiveGenerations, get } = setup(true);
  refreshActiveGenerations.mockImplementation(() => new Promise(() => undefined));
  expect(get).not.toHaveBeenCalled();
  expect(refreshActiveGenerations).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(refreshActiveGenerations).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(refreshActiveGenerations).toHaveBeenCalledTimes(1);
});

it("无活跃 Generation 时按 5s 拉取快照", async () => {
  const { get, refreshActiveGenerations } = setup(false);
  get.mockResolvedValue(snapshot("succeeded"));
  await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
  expect(get).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(get).toHaveBeenCalledTimes(1);
  expect(refreshActiveGenerations).not.toHaveBeenCalled();
});

it("页面隐藏时暂停，恢复可见后立即调度", async () => {
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  const { get } = setup(false);
  get.mockResolvedValue(snapshot("succeeded"));
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(get).not.toHaveBeenCalled();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  document.dispatchEvent(new Event("visibilitychange"));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(get).toHaveBeenCalledTimes(1);
});

it("错误按指数退避，成功后恢复基础间隔", async () => {
  const { get, onError } = setup(false);
  get.mockRejectedValueOnce(new Error("offline"));
  get.mockResolvedValue(snapshot("succeeded"));
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(get).toHaveBeenCalledTimes(1);
  expect(onError).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(get).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(get).toHaveBeenCalledTimes(2);
});
