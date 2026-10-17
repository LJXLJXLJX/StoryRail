import { useState } from "react";

import {
  StoryRailApiError,
  type PlaygroundAsset,
  type PlaygroundCapabilityId,
  type PlaygroundCapabilityInfo,
  type PlaygroundRun,
} from "../api";
import { playgroundApi } from "./api";
import { CompareDrawer } from "./CompareDrawer";
import { RunCard } from "./RunCard";
import type { SlotTarget } from "./forms/common";

const ACTIVE_PHASES = new Set(["submitting", "queued", "running"]);
const FAILED_PHASES = new Set(["failed", "cancelled", "submission_uncertain"]);

type StatusFilter = "all" | "active" | "succeeded" | "failed";

export function RunFeed({
  runs,
  assets,
  capabilities,
  highlightRunId,
  onUseParameters,
  onUseAsInput,
  onChanged,
}: {
  runs: PlaygroundRun[];
  assets: PlaygroundAsset[];
  capabilities: PlaygroundCapabilityInfo[];
  highlightRunId: string | null;
  onUseParameters: (
    capability: PlaygroundCapabilityId,
    parameters: Record<string, unknown>,
  ) => void;
  onUseAsInput: (target: SlotTarget, assetId: string) => void;
  onChanged: () => void;
}) {
  const [capability, setCapability] = useState<PlaygroundCapabilityId | "all">(
    "all",
  );
  const [status, setStatus] = useState<StatusFilter>("all");
  const [includeDismissed, setIncludeDismissed] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const [confirmingDismiss, setConfirmingDismiss] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [dismissError, setDismissError] = useState<string | null>(null);

  const visible = runs.filter((run) => {
    if (run.dismissed && !includeDismissed) return false;
    if (capability !== "all" && run.capability !== capability) return false;
    if (status === "active" && !ACTIVE_PHASES.has(run.phase)) return false;
    if (status === "succeeded" && run.phase !== "succeeded") return false;
    if (status === "failed" && !FAILED_PHASES.has(run.phase)) return false;
    return true;
  });
  const dismissible = visible.filter((run) =>
    run.allowed_actions.includes("dismiss"),
  );
  const capabilityLabel =
    capability === "all"
      ? "全部能力"
      : (capabilities.find((item) => item.id === capability)?.label ??
        capability);
  const selectedRuns = selected
    .map((runId) => runs.find((run) => run.id === runId))
    .filter((run): run is PlaygroundRun => run !== undefined);
  const sameCapability =
    new Set(selectedRuns.map((run) => run.capability)).size === 1;
  const canCompare =
    selectedRuns.length >= 2 && selectedRuns.length <= 4 && sameCapability;
  const compareHint =
    selectedRuns.length > 4
      ? "一次最多对比 4 个实验。"
      : sameCapability
        ? "请选择 2 到 4 个实验。"
        : "只有同一能力的实验可以对比。";

  function toggleSelected(runId: string) {
    setSelected((current) =>
      current.includes(runId)
        ? current.filter((id) => id !== runId)
        : [...current, runId],
    );
  }

  async function dismissAll() {
    setConfirmingDismiss(false);
    setDismissing(true);
    setDismissError(null);
    let failed = 0;
    let lastMessage: string | null = null;
    for (const run of dismissible) {
      try {
        await playgroundApi.dismissRun(run.id);
      } catch (caught) {
        failed += 1;
        if (caught instanceof StoryRailApiError) lastMessage = caught.message;
      }
    }
    setDismissing(false);
    if (failed > 0) {
      setDismissError(
        `${failed} 个实验隐藏失败${lastMessage === null ? "，请重试。" : `：${lastMessage}`}`,
      );
    }
    onChanged();
  }

  return (
    <section className="playground-column" aria-label="运行流">
      <h2>运行流</h2>
      <div className="playground-run-filters">
        <select
          aria-label="按能力过滤"
          value={capability}
          onChange={(event) =>
            setCapability(event.target.value as PlaygroundCapabilityId | "all")
          }
        >
          <option value="all">全部能力</option>
          {capabilities.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
        <select
          aria-label="按状态过滤"
          value={status}
          onChange={(event) => setStatus(event.target.value as StatusFilter)}
        >
          <option value="all">全部状态</option>
          <option value="active">进行中</option>
          <option value="succeeded">成功</option>
          <option value="failed">失败</option>
        </select>
        <label>
          <input
            type="checkbox"
            checked={includeDismissed}
            onChange={(event) => setIncludeDismissed(event.target.checked)}
          />
          显示已隐藏
        </label>
        <button
          type="button"
          className="secondary-button"
          disabled={dismissible.length === 0 || dismissing}
          title={
            dismissible.length === 0
              ? "当前过滤条件下没有可隐藏的已结束实验。"
              : undefined
          }
          onClick={() => {
            setDismissError(null);
            setConfirmingDismiss(true);
          }}
        >
          {dismissing ? "正在隐藏…" : `全部隐藏 (${dismissible.length})`}
        </button>
      </div>
      {confirmingDismiss && dismissible.length > 0 ? (
        <div className="playground-window-confirm" role="alert">
          <p>
            将隐藏「{capabilityLabel}」下当前列出的 {dismissible.length}{" "}
            个已结束实验，确定继续？
          </p>
          <div className="playground-window-confirm-actions">
            <button
              type="button"
              className="primary-button"
              onClick={() => void dismissAll()}
            >
              确认隐藏
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setConfirmingDismiss(false)}
            >
              取消
            </button>
          </div>
        </div>
      ) : null}
      {dismissError === null ? null : (
        <p className="playground-error" role="alert">
          {dismissError}
        </p>
      )}
      {visible.length === 0 ? (
        <p className="playground-hint">当前过滤条件下没有实验。</p>
      ) : (
        <div className="playground-run-list">
          {visible.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              assets={assets}
              capabilities={capabilities}
              highlighted={run.id === highlightRunId}
              selected={selected.includes(run.id)}
              onToggleSelected={toggleSelected}
              onUseParameters={onUseParameters}
              onUseAsInput={onUseAsInput}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}
      {selected.length === 0 ? null : (
        <div className="playground-compare-bar">
          <button
            type="button"
            className="primary-button"
            disabled={!canCompare}
            title={canCompare ? undefined : compareHint}
            onClick={() => setComparing(true)}
          >
            对比所选 ({selected.length})
          </button>
        </div>
      )}
      {comparing && canCompare ? (
        <CompareDrawer
          runs={selectedRuns}
          assets={assets}
          onClose={() => setComparing(false)}
        />
      ) : null}
    </section>
  );
}
