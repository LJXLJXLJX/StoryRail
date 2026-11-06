// 可见性感知的 Playground 轮询：与 director_workspace/useSnapshotScheduler 同一套机制，
// 但有活动 run 时刷新 Provider 状态，闲置时周期读取快照来发现 Agent 提交的新 run。
import { useEffect, useRef } from "react";

import type { PlaygroundSnapshot } from "../api";
import { playgroundApi } from "./api";

const ACTIVE_INTERVAL_MS = 1250;
const IDLE_INTERVAL_MS = 10000;
const MAX_BACKOFF_MS = 30000;

const ACTIVE_PHASES = new Set(["submitting", "queued", "running"]);

type SnapshotApi = Pick<typeof playgroundApi, "get" | "refresh">;

export type PlaygroundSchedulerOptions = {
  snapshot: PlaygroundSnapshot | null;
  enabled?: boolean;
  onSnapshot: (snapshot: PlaygroundSnapshot) => void;
  onError: (error: unknown) => void;
  api?: SnapshotApi;
  activeIntervalMs?: number;
  idleIntervalMs?: number;
  maxBackoffMs?: number;
};

export function hasActivePlaygroundRun(
  snapshot: PlaygroundSnapshot | null,
): boolean {
  return (
    snapshot?.runs.some((run) => ACTIVE_PHASES.has(run.phase)) ?? false
  );
}

export function usePlaygroundScheduler({
  snapshot,
  enabled = true,
  onSnapshot,
  onError,
  api = playgroundApi,
  activeIntervalMs = ACTIVE_INTERVAL_MS,
  idleIntervalMs = IDLE_INTERVAL_MS,
  maxBackoffMs = MAX_BACKOFF_MS,
}: PlaygroundSchedulerOptions): void {
  const timer = useRef<number | null>(null);
  const inFlight = useRef(false);
  const cancelled = useRef(false);
  const failures = useRef(0);
  const snapshotRef = useRef(snapshot);
  const onSnapshotRef = useRef(onSnapshot);
  const onErrorRef = useRef(onError);
  const apiRef = useRef(api);
  snapshotRef.current = snapshot;
  onSnapshotRef.current = onSnapshot;
  onErrorRef.current = onError;
  apiRef.current = api;

  useEffect(() => {
    cancelled.current = false;
    const clear = () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
    };
    const schedule = (delay: number) => {
      clear();
      if (enabled === false || document.hidden) return;
      timer.current = window.setTimeout(() => {
        timer.current = null;
        void run();
      }, delay);
    };
    const run = async () => {
      if (enabled === false || document.hidden || inFlight.current) return;
      inFlight.current = true;
      const active = hasActivePlaygroundRun(snapshotRef.current);
      try {
        const updated = active
          ? await apiRef.current.refresh()
          : await apiRef.current.get();
        if (cancelled.current === false) {
          failures.current = 0;
          onSnapshotRef.current(updated);
          schedule(active ? activeIntervalMs : idleIntervalMs);
        }
      } catch (error) {
        if (cancelled.current === false) {
          failures.current += 1;
          const base = active ? activeIntervalMs : idleIntervalMs;
          const delay = Math.min(
            maxBackoffMs,
            base * 2 ** Math.min(failures.current, 8),
          );
          onErrorRef.current(error);
          schedule(delay);
        }
      } finally {
        inFlight.current = false;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        clear();
      } else {
        schedule(0);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    if (enabled) {
      schedule(
        hasActivePlaygroundRun(snapshotRef.current)
          ? activeIntervalMs
          : idleIntervalMs,
      );
    }
    return () => {
      cancelled.current = true;
      clear();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [activeIntervalMs, enabled, idleIntervalMs, maxBackoffMs]);
}
