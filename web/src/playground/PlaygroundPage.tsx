import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";

import type {
  PlaygroundCapabilityId,
  PlaygroundRun,
  PlaygroundSnapshot,
} from "../api";
import { FloatingErrorNotice } from "../AppView";
import { ProviderSettingsControl } from "../provider_settings/ProviderSettingsControl";
import { playgroundApi } from "./api";
import { AssetPanel } from "./AssetPanel";
import { CapabilityList } from "./CapabilityList";
const ExternalAgentEntry = lazy(() =>
  import("../ExternalAgentConnect").then((module) => ({
    default: module.ExternalAgentEntry,
  })),
);
import { RunFeed } from "./RunFeed";
import { RunForm, type RunFormHandle } from "./RunForm";
import { usePlaygroundScheduler } from "./usePlaygroundScheduler";
import type { AssetPickRequest, SlotTarget } from "./forms/common";
import "./playground.css";

// 01 §12.8 的统一文案。
const SUBTITLE =
  "与故事无关的模型实验台。产物保存在 Playground 资产库，需要时可复制到项目。";

export function PlaygroundPage({ onExit }: { onExit: () => void }) {
  const [snapshot, setSnapshot] = useState<PlaygroundSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCapability, setSelectedCapability] =
    useState<PlaygroundCapabilityId | null>(null);
  const [highlightRunId, setHighlightRunId] = useState<string | null>(null);
  const [assetPick, setAssetPick] = useState<AssetPickRequest | null>(null);
  const [assetPanelOpen, setAssetPanelOpen] = useState(false);
  const runFormRef = useRef<RunFormHandle | null>(null);

  const applySnapshot = useCallback((updated: PlaygroundSnapshot) => {
    setSnapshot((current) =>
      current !== null && current.revision > updated.revision ? current : updated,
    );
  }, []);
  const handleError = useCallback((caught: unknown) => {
    setError(caught instanceof Error ? caught.message : "发生了无法识别的错误。");
  }, []);
  usePlaygroundScheduler({
    snapshot,
    onSnapshot: applySnapshot,
    onError: handleError,
  });

  const load = useCallback(async () => {
    try {
      applySnapshot(await playgroundApi.get());
      setError(null);
    } catch (caught) {
      handleError(caught);
    }
  }, [applySnapshot, handleError]);
  useEffect(() => {
    void load();
  }, [load]);
  // 新提交的 run 高亮 2 秒（01 §12.3）。
  useEffect(() => {
    if (highlightRunId === null) return;
    const timer = window.setTimeout(() => setHighlightRunId(null), 2000);
    return () => window.clearTimeout(timer);
  }, [highlightRunId]);

  const refresh = useCallback(async () => {
    try {
      applySnapshot(await playgroundApi.refresh());
      setError(null);
    } catch (caught) {
      handleError(caught);
    }
  }, [applySnapshot, handleError]);

  function handleSubmitted(run: PlaygroundRun) {
    setHighlightRunId(run.id);
    void refresh();
  }

  function useParameters(
    capability: PlaygroundCapabilityId,
    parameters: Record<string, unknown>,
  ) {
    setSelectedCapability(capability);
    runFormRef.current?.prefill(capability, parameters);
  }

  function useAsInput(target: SlotTarget, assetId: string) {
    setSelectedCapability(target.capability);
    runFormRef.current?.fillSlot(target, assetId);
  }

  const capabilities = snapshot?.capabilities ?? [];
  const assets = snapshot?.assets ?? [];
  const selected = selectedCapability ?? capabilities[0]?.id ?? null;

  return (
    <div className="playground-page">
      <header className="playground-topbar">
        <button className="home-link" type="button" onClick={onExit}>
          <span aria-hidden="true">←</span> 项目列表
        </button>
        <div className="playground-heading">
          <h1>Playground</h1>
          <p className="playground-subtitle">{SUBTITLE}</p>
        </div>
        <div className="playground-topbar-actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => setAssetPanelOpen(true)}
          >
            资产
          </button>
          <ProviderSettingsControl onChanged={() => void load()} />
          <Suspense fallback={null}>
            <ExternalAgentEntry target={{ kind: "playground" }} />
          </Suspense>
        </div>
      </header>
      {error !== null ? (
        <FloatingErrorNotice message={error} onDismiss={() => setError(null)} />
      ) : null}
      <div className="playground-body">
        <CapabilityList
          capabilities={capabilities}
          selected={selected}
          onSelect={setSelectedCapability}
        />
        <RunForm
          ref={runFormRef}
          capabilities={capabilities}
          assets={assets}
          selectedCapability={selected}
          onSubmitted={handleSubmitted}
          onRequestAsset={setAssetPick}
        />
        <RunFeed
          runs={snapshot?.runs ?? []}
          assets={assets}
          capabilities={capabilities}
          highlightRunId={highlightRunId}
          onUseParameters={useParameters}
          onUseAsInput={useAsInput}
          onChanged={() => void refresh()}
        />
      </div>
      {assetPanelOpen || assetPick !== null ? (
        <AssetPanel
          assets={assets}
          selection={assetPick}
          onClose={() => {
            setAssetPanelOpen(false);
            setAssetPick(null);
          }}
          onChanged={() => void refresh()}
        />
      ) : null}
    </div>
  );
}
