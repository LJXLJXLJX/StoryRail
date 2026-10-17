import { useEffect, useRef } from "react";
import {
  structuredDirectorApi,
  type StructuredDirectorSnapshot,
} from "../api";

const ACTIVE_INTERVAL_MS = 1250;
const IDLE_INTERVAL_MS = 5000;
const MAX_BACKOFF_MS = 30000;

type SnapshotApi = Pick<
  typeof structuredDirectorApi,
  "get" | "refreshActiveGenerations"
>;

export type SnapshotSchedulerOptions = {
  projectId: string | null;
  snapshot: StructuredDirectorSnapshot | null;
  enabled?: boolean;
  onSnapshot: (snapshot: StructuredDirectorSnapshot) => void;
  onError: (error: unknown) => void;
  api?: SnapshotApi;
  activeIntervalMs?: number;
  idleIntervalMs?: number;
  maxBackoffMs?: number;
};

function hasActiveGeneration(snapshot: StructuredDirectorSnapshot | null): boolean {
  return (
    snapshot?.generations.some(
      generation => generation.phase === "queued" || generation.phase === "running",
    ) ?? false
  );
}

export function useSnapshotScheduler({
  projectId,
  snapshot,
  enabled = true,
  onSnapshot,
  onError,
  api = structuredDirectorApi,
  activeIntervalMs = ACTIVE_INTERVAL_MS,
  idleIntervalMs = IDLE_INTERVAL_MS,
  maxBackoffMs = MAX_BACKOFF_MS,
}: SnapshotSchedulerOptions): void {
  const timer = useRef<number | null>(null);
  const inFlight = useRef(false);
  const cancelled = useRef(false);
  const failures = useRef(0);
  const projectIdRef = useRef<string | null>(projectId);
  const snapshotRef = useRef(snapshot);
  const onSnapshotRef = useRef(onSnapshot);
  const onErrorRef = useRef(onError);
  const apiRef = useRef(api);
  projectIdRef.current = projectId;
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
      if (enabled === false || projectIdRef.current === null || document.hidden) return;
      timer.current = window.setTimeout(() => {
        timer.current = null;
        void run();
      }, delay);
    };
    const run = async () => {
      if (
        enabled === false ||
        projectIdRef.current === null ||
        document.hidden ||
        inFlight.current
      ) return;
      inFlight.current = true;
      const requestedProjectId = projectIdRef.current;
      const active = hasActiveGeneration(snapshotRef.current);
      try {
        const updated = active
          ? await apiRef.current.refreshActiveGenerations(requestedProjectId)
          : await apiRef.current.get(requestedProjectId);
        if (cancelled.current === false && projectIdRef.current === requestedProjectId) {
          failures.current = 0;
          onSnapshotRef.current(updated);
          schedule(active ? activeIntervalMs : idleIntervalMs);
        }
      } catch (error) {
        if (cancelled.current === false && projectIdRef.current === requestedProjectId) {
          failures.current += 1;
          const base = active ? activeIntervalMs : idleIntervalMs;
          const delay = Math.min(maxBackoffMs, base * 2 ** Math.min(failures.current, 8));
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
    if (enabled && projectId !== null) {
      schedule(hasActiveGeneration(snapshotRef.current) ? activeIntervalMs : idleIntervalMs);
    }
    return () => {
      cancelled.current = true;
      clear();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [
    activeIntervalMs,
    enabled,
    idleIntervalMs,
    maxBackoffMs,
    projectId,
  ]);
}
