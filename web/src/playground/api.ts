// Playground HTTP 客户端。只消费 Core 的快照、回执与错误，不推断 run 能做什么。
import { canonicalImportedMediaType, request } from "../api";
import type {
  ImageAssetCategory,
  PlaygroundAsset,
  PlaygroundCapabilityId,
  PlaygroundCommandReceipt,
  PlaygroundCopyToProjectResult,
  PlaygroundRun,
  PlaygroundSnapshot,
} from "../api";
import type { VideoFrameInfo } from "../director_workspace/shared";
import {
  hasExactKeys,
  isPlaygroundAssetResult,
  isPlaygroundCommandReceipt,
  isPlaygroundCopyToProjectResult,
  isPlaygroundRun,
  isPlaygroundRecipePreview,
  isPlaygroundSnapshot,
  isRecord,
} from "../api/validation";

export type PlaygroundCommandName =
  | "playground.list_capabilities"
  | "playground.list_runs"
  | "playground.get_runs"
  | "playground.list_assets"
  | "playground.submit_run"
  | "playground.wait_runs"
  | "playground.cancel_run"
  | "playground.retry_run"
  | "playground.dismiss_run"
  | "playground.set_note";

const PLAYGROUND_RESOURCE = "/api/playground";
const INVALID_RESPONSE = "服务端返回了无法识别的 Playground 数据。";

export const playgroundApi = {
  previewRecipeInputs: (
    capability: string,
    parameters: Record<string, unknown>,
  ) =>
    request(
      `${PLAYGROUND_RESOURCE}/recipe-inputs-preview`,
      (value) => {
        if (!isPlaygroundRecipePreview(value))
          throw new Error(INVALID_RESPONSE);
        return value;
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capability, parameters }),
      },
    ),
  get: () => request(`${PLAYGROUND_RESOURCE}`, parseSnapshot),
  refresh: () =>
    request(`${PLAYGROUND_RESOURCE}/runs/refresh`, parseSnapshot, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  command: <T>(
    name: PlaygroundCommandName,
    arguments_: Record<string, unknown>,
    key?: string,
  ) =>
    request(
      `${PLAYGROUND_RESOURCE}/commands`,
      (value) => parseCommandEnvelope<T>(value),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          idempotency_key: key ?? `ui:${crypto.randomUUID()}`,
          arguments: arguments_,
        }),
      },
    ),
  submitRun: async (
    capability: PlaygroundCapabilityId,
    parameters: Record<string, unknown>,
    note: string | null,
  ): Promise<PlaygroundRun> => {
    const { data } = await playgroundApi.command<{ run: unknown }>(
      "playground.submit_run",
      { capability, parameters, note },
    );
    return parseRun(data.run);
  },
  cancelRun: (runId: string) => runCommand("playground.cancel_run", runId),
  retryRun: (runId: string) => runCommand("playground.retry_run", runId),
  dismissRun: (runId: string) => runCommand("playground.dismiss_run", runId),
  setNote: async (
    runId: string,
    note: string | null,
  ): Promise<PlaygroundRun> => {
    const { data } = await playgroundApi.command<{ run: unknown }>(
      "playground.set_note",
      { run_id: runId, note },
    );
    return parseRun(data.run);
  },
  uploadAsset: (file: File): Promise<PlaygroundAsset> => {
    const query = new URLSearchParams({ filename: file.name });
    return request(
      `${PLAYGROUND_RESOURCE}/assets/media?${query.toString()}`,
      (value) => {
        if (!isPlaygroundAssetResult(value)) throw new Error(INVALID_RESPONSE);
        return value.asset;
      },
      {
        method: "POST",
        headers: { "Content-Type": canonicalImportedMediaType(file) },
        body: file,
      },
    );
  },
  deleteAssets: (assetIds: string[]): Promise<string[]> =>
    request(
      `${PLAYGROUND_RESOURCE}/assets`,
      (value) => {
        if (
          !isRecord(value) ||
          !hasExactKeys(value, ["deleted_asset_ids"]) ||
          !Array.isArray(value.deleted_asset_ids) ||
          !value.deleted_asset_ids.every((item) => typeof item === "string")
        ) {
          throw new Error(INVALID_RESPONSE);
        }
        return value.deleted_asset_ids as string[];
      },
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_ids: assetIds }),
      },
    ),
  videoFrameInfo: (assetId: string): Promise<VideoFrameInfo> =>
    request(
      `${PLAYGROUND_RESOURCE}/assets/${assetId}/video-frame-info`,
      (value) => {
        if (
          !isRecord(value) ||
          !hasExactKeys(value, ["frame_count", "duration_seconds"]) ||
          typeof value.frame_count !== "number" ||
          !Number.isInteger(value.frame_count) ||
          value.frame_count < 1 ||
          !(
            value.duration_seconds === null ||
            (typeof value.duration_seconds === "number" &&
              Number.isFinite(value.duration_seconds))
          )
        ) {
          throw new Error(INVALID_RESPONSE);
        }
        return {
          frame_count: value.frame_count,
          duration_seconds: value.duration_seconds as number | null,
        };
      },
    ),
  copyFromProject: (
    projectId: string,
    assetId: string,
  ): Promise<PlaygroundAsset> =>
    request(
      `${PLAYGROUND_RESOURCE}/assets/copy-from-project`,
      (value) => {
        if (!isPlaygroundAssetResult(value)) throw new Error(INVALID_RESPONSE);
        return value.asset;
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, asset_id: assetId }),
      },
    ),
  copyToProject: (
    projectId: string,
    assetId: string,
    expectedRevision: number,
    imageCategory: ImageAssetCategory | null,
  ): Promise<PlaygroundCopyToProjectResult> =>
    request(
      `/api/projects/${projectId}/structured-director/assets/copy-from-playground`,
      (value) => {
        if (!isPlaygroundCopyToProjectResult(value)) {
          throw new Error(INVALID_RESPONSE);
        }
        return value;
      },
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_id: assetId,
          expected_revision: expectedRevision,
          image_category: imageCategory,
        }),
      },
    ),
};

async function runCommand(
  name: PlaygroundCommandName,
  runId: string,
): Promise<PlaygroundRun> {
  const { data } = await playgroundApi.command<{ run: unknown }>(name, {
    run_id: runId,
  });
  return parseRun(data.run);
}

function parseSnapshot(value: unknown): PlaygroundSnapshot {
  if (!isPlaygroundSnapshot(value)) throw new Error(INVALID_RESPONSE);
  return value;
}

function parseRun(value: unknown): PlaygroundRun {
  if (!isPlaygroundRun(value)) throw new Error(INVALID_RESPONSE);
  return value;
}

function parseCommandEnvelope<T>(value: unknown): {
  receipt: PlaygroundCommandReceipt;
  data: T;
} {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["receipt", "data"]) ||
    !isPlaygroundCommandReceipt(value.receipt) ||
    !isRecord(value.data)
  ) {
    throw new Error(INVALID_RESPONSE);
  }
  return { receipt: value.receipt, data: value.data as T };
}
