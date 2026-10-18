import {
  useEffect,
  useRef,
  useState,
} from "react";

import { ZoomableImage } from "../ImagePreview";

import type {
  ProjectAsset,
  ReferenceGeneration,
} from "../api";

import {
  GenerationCandidateList,
  assetById,
} from "./shared";

export function GenerationCandidates({
  generations, assets, media, busy, onAttach, onCancel, onDismiss,
  attachAction = "attach_output", attachLabel,
}: {
  generations: ReferenceGeneration[];
  assets: ProjectAsset[];
  media: "image" | "audio";
  busy: boolean;
  attachAction?: "attach_output" | "select_look_sheet";
  attachLabel?: string;
  onAttach: (generationId: string) => void;
  onCancel: (generationId: string) => void;
  onDismiss: (generationId: string) => void;
}) {
  const [promptGenerationId, setPromptGenerationId] = useState<string | null>(null);
  const promptGeneration = promptGenerationId === null
    ? null
    : generations.find((generation) => generation.id === promptGenerationId) ?? null;
  const promptAsset = promptGeneration?.output_asset_id
    ? assetById(assets, promptGeneration.output_asset_id)
    : null;
  return (
    <div className="generation-candidates">
      <GenerationCandidateList
        kind="generation"
        target={media}
        assets={assets}
        candidates={generations}
        busy={busy}
        collapsible={false}
        summary="生成候选"
        onDismiss={onDismiss}
        dismissLabel="隐藏历史卡片"
        renderCandidate={(generation, asset) => {
          const issueStage = generationIssueStage(generation);
          return (
            <div className={`generation-candidate-body${asset && media === "image" ? " has-image" : ""}`}>
              {asset && media === "image" ? (
                <div className="generation-candidate-image">
                  <ZoomableImage src={asset.content_url} alt="生成的图片候选" />
                </div>
              ) : null}
              {asset && media === "audio" ? (
                <audio controls preload="none" src={asset.content_url} />
              ) : null}
              <div>
                <strong>{generationPhaseLabel(generation.phase)}</strong>
                <span>{Math.round(generation.progress * 100)}%</span>
              </div>
              <p>{generation.message}</p>
              {issueStage ? (
                <p className="generation-issue-stage"><strong>问题环节</strong>{issueStage}</p>
              ) : null}
              {media === "image" ? (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => setPromptGenerationId(generation.id)}
                >查看完整提示词</button>
              ) : null}
              {generation.allowed_actions.includes(attachAction) ? (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => onAttach(generation.id)}
                >{attachLabel ?? (media === "image" ? "加入参考图" : "设为参考音色")}</button>
              ) : null}
              {generation.allowed_actions.includes("cancel") ? (
                <button
                  type="button"
                  className="delete-button"
                  disabled={busy || generation.cancellation_requested}
                  onClick={() => onCancel(generation.id)}
                >{generation.cancellation_requested ? "已请求取消" : "取消生成"}</button>
              ) : null}
            </div>
          );
        }}
      />
      {promptGeneration !== null ? (
        <div className="reference-image-dialog-backdrop" role="presentation">
          <section className="reference-image-dialog generation-prompt-dialog" role="dialog"
            aria-modal="true" aria-labelledby="generation-prompt-title">
            <header className="reference-image-dialog-header">
              <div><p className="eyebrow">Generation prompt</p>
                <h2 id="generation-prompt-title">完整提示词</h2></div>
              <button type="button" className="dialog-close-button" aria-label="关闭完整提示词"
                onClick={() => setPromptGenerationId(null)}>×</button>
            </header>
            {promptAsset !== null ? <ZoomableImage className="reference-detail-image"
              src={promptAsset.content_url} alt="生成图片候选大图" /> : null}
            <p className="muted-copy">{promptGeneration.kind === "location_image" ||
                promptGeneration.kind === "panorama_capture"
              ? "这是提交给图片插件并持久化的完整提示词，包含 Core 编译的地点空间约束。"
              : "这是 Core 持久化并原样提交给图片插件的创意提示词，没有自动优化。"}</p>
            <pre className="generation-prompt-text">{promptGeneration.prompt_text}</pre>
            <div className="generation-prompt-inputs">
              <strong>输入参考图</strong>
              {promptGeneration.input_asset_ids.length === 0 ? (
                <span>无（纯文本生图）</span>
              ) : (
                <div className="mention-assets">{promptGeneration.input_asset_ids.map((assetId) => {
                  const input = assetById(assets, assetId);
                  return <div key={assetId} className="generation-prompt-input">
                    {input ? <ZoomableImage src={input.content_url} alt="生成时使用的参考图" /> : null}
                    <span>@{assetId.slice(0, 6)}</span>
                  </div>;
                })}</div>
              )}
            </div>
            <footer className="reference-image-dialog-actions">
              <span />
              <button type="button" className="primary-button"
                onClick={() => setPromptGenerationId(null)}>完成</button>
            </footer>
          </section>
        </div>
      ) : null}
    </div>
  );
}



export function generationPhaseLabel(phase: ReferenceGeneration["phase"]): string {
  return {
    submitting: "正在提交",
    submission_uncertain: "提交结果未知",
    queued: "排队中",
    running: "生成中",
    succeeded: "候选已生成",
    failed: "生成失败",
    cancelled: "已取消",
  }[phase];
}


export interface SamplingTelemetry {
  generationId: string;
  completed: number;
  total: number;
  secondsPerIteration: number | null;
  remainingSeconds: number | null;
}


export interface SamplingClock extends SamplingTelemetry {
  observedAt: number;
}


export function parseSamplingMessage(message: string) {
  const steps = message.match(/扩散采样\s+(\d+)\s*\/\s*(\d+)/u);
  if (steps === null) return null;
  const completed = Number.parseInt(steps[1], 10);
  const total = Number.parseInt(steps[2], 10);
  if (total < 1 || completed < 0 || completed > total) return null;
  const speed = message.match(/(\d+(?:\.\d+)?)\s*s\/it(?:er)?\b/iu);
  const remaining = message.match(/预计剩余\s+(\d+(?:\.\d+)?)\s*秒/u);
  return {
    completed,
    total,
    secondsPerIteration: speed === null ? null : Number.parseFloat(speed[1]),
    remainingSeconds: remaining === null ? null : Number.parseFloat(remaining[1]),
  };
}


export function useSamplingTelemetry(generation: ReferenceGeneration | undefined) {
  const clock = useRef<SamplingClock | null>(null);
  const [telemetry, setTelemetry] = useState<SamplingTelemetry | null>(null);
  useEffect(() => {
    if (generation === undefined) {
      clock.current = null;
      setTelemetry(null);
      return;
    }
    const parsed = parseSamplingMessage(generation.message);
    if (parsed === null) {
      clock.current = null;
      setTelemetry(null);
      return;
    }
    const now = performance.now();
    const previous = clock.current;
    const reset = previous === null || previous.generationId !== generation.id ||
      previous.total !== parsed.total || parsed.completed < previous.completed;
    let secondsPerIteration = parsed.secondsPerIteration;
    if (!reset && parsed.completed > previous.completed) {
      const elapsedSeconds = (now - previous.observedAt) / 1_000;
      const measured = elapsedSeconds / (parsed.completed - previous.completed);
      if (secondsPerIteration === null && measured > 0 && Number.isFinite(measured)) {
        secondsPerIteration = previous.secondsPerIteration === null
          ? measured : 0.3 * measured + 0.7 * previous.secondsPerIteration;
      }
    } else if (!reset && secondsPerIteration === null) {
      secondsPerIteration = previous.secondsPerIteration;
    }
    const remainingSeconds = parsed.remainingSeconds ?? (
      secondsPerIteration === null ? null
        : secondsPerIteration * Math.max(0, parsed.total - parsed.completed)
    );
    const next = {
      generationId: generation.id,
      completed: parsed.completed,
      total: parsed.total,
      secondsPerIteration,
      remainingSeconds,
    };
    clock.current = {
      ...next,
      observedAt: !reset && parsed.completed === previous.completed
        ? previous.observedAt : now,
    };
    setTelemetry(next);
  }, [generation?.id, generation?.message]);
  return telemetry?.generationId === generation?.id ? telemetry : null;
}


export function formatSamplingDuration(value: number) {
  const seconds = Math.max(0, Math.ceil(value));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder === 0 ? `${minutes} 分钟` : `${minutes} 分 ${remainder} 秒`;
}


export function generationIssueStage(generation: ReferenceGeneration): string | null {
  if (generation.error_code === null) return null;
  return {
    invalid_response: "提交阶段 · 外部响应协议校验",
    submission_rejected: "提交阶段 · 外部服务拒绝",
    transport_error: "提交阶段 · 模型节点连接",
    provider_error: "提交阶段 · Core Provider 插件",
    core_restarted_during_submit: "提交阶段 · Core 中断恢复",
  }[generation.error_code] ?? (
    generation.phase === "failed" ? "生成阶段 · 外部模型执行" : "任务处理阶段"
  );
}
