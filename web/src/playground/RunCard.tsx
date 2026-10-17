import { useRef, useState } from "react";
import { ZoomableImage } from "../ImagePreview";

import {
  StoryRailApiError,
  type PlaygroundAsset,
  type PlaygroundCapabilityId,
  type PlaygroundRun,
  type PlaygroundCapabilityInfo,
} from "../api";
import { copyText } from "../director_workspace/clipboard";
// 状态文案复用 generation.tsx 的导出函数；颜色由 playground.css 的
// .playground-phase-badge.phase-* 规则提供（generation.tsx 没有颜色映射）。
import { generationPhaseLabel } from "../director_workspace/generation";
import { playgroundApi } from "./api";
import { assetMediaKind, type SlotTarget } from "./forms/common";

export const OUTPUT_TARGETS: Record<"image" | "audio" | "video", SlotTarget[]> =
  {
    image: [
      {
        capability: "image.pano_view",
        key: "image_asset_id",
        label: "全景裁切 · 全景",
        requiredAction: "pano_view",
      },
    ],
    audio: [
      {
        capability: "audio.effect",
        key: "audio_asset_id",
        label: "后处理 · 音频",
      },
      { capability: "audio.trim", key: "audio_asset_id", label: "截取 · 音频" },
      {
        capability: "audio.remix",
        key: "voice_asset_id",
        label: "混音 · 人声",
      },
      {
        capability: "audio.remix",
        key: "background_asset_id",
        label: "混音 · 背景",
      },
    ],
    video: [
      {
        capability: "video.extract_frame",
        key: "video_asset_id",
        label: "抽帧 · 视频",
      },
      {
        capability: "audio.remix",
        key: "video_asset_id",
        label: "混音 · 视频",
      },
    ],
  };

export function outputTargets(
  asset: PlaygroundAsset,
  capabilities: PlaygroundCapabilityInfo[],
): SlotTarget[] {
  return [
    ...OUTPUT_TARGETS[assetMediaKind(asset.media_type)].filter(
      (target) =>
        target.requiredAction === undefined ||
        asset.allowed_actions.includes(target.requiredAction),
    ),
    ...capabilities.flatMap((info) =>
      (info.available ? (info.recipe?.recipe.slots ?? []) : [])
        .filter(
          (slot) =>
            slot.media_types.includes(asset.media_type) &&
            (slot.duration_seconds === null ||
              (asset.duration_seconds !== null &&
                asset.duration_seconds >= slot.duration_seconds[0]! &&
                asset.duration_seconds <= slot.duration_seconds[1]!)),
        )
        .map((slot) => {
          const key =
            slot.describe !== "none"
              ? slot.key
              : `${slot.key}_asset_id${slot.maximum === 1 ? "" : "s"}`;
          return {
            capability: info.id,
            key,
            label: `${info.label} · ${slot.label}`,
            ...(slot.describe !== "none"
              ? { list: key }
              : slot.maximum !== 1
                ? { idList: key }
                : {}),
          };
        }),
    ),
  ];
}

const TERMINAL_PHASES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "submission_uncertain",
]);
const DELETED_ASSET = "已删除素材";
const DELETED_OUTPUT = "产物已从 Playground 资产库删除。";
const ASSET_ID = /^[0-9a-f]{32}$/;

export function assetById(
  assets: PlaygroundAsset[],
  assetId: string | null,
): PlaygroundAsset | null {
  return assetId === null
    ? null
    : (assets.find((asset) => asset.id === assetId) ?? null);
}

export function truncate(value: string, maximum = 120): string {
  return value.length > maximum ? `${value.slice(0, maximum)}…` : value;
}

export function formatParameterValue(
  value: unknown,
  assets: PlaygroundAsset[],
): string {
  if (typeof value === "string") {
    if (ASSET_ID.test(value)) {
      return assetById(assets, value)?.display_name ?? DELETED_ASSET;
    }
    return truncate(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) {
    return truncate(
      value
        .map((item) => {
          if (typeof item === "object" && item !== null && "asset_id" in item) {
            const record = item as {
              asset_id?: unknown;
              description?: unknown;
            };
            const name =
              typeof record.asset_id === "string"
                ? (assetById(assets, record.asset_id)?.display_name ??
                  DELETED_ASSET)
                : DELETED_ASSET;
            return typeof record.description === "string" &&
              record.description !== ""
              ? `${name}（${record.description}）`
              : name;
          }
          return formatParameterValue(item, assets);
        })
        .join("、"),
    );
  }
  return truncate(JSON.stringify(value) ?? "");
}

export function summarizeParameters(
  parameters: Record<string, unknown>,
  assets: PlaygroundAsset[],
): Array<{ key: string; value: string }> {
  return Object.entries(parameters).map(([key, value]) => ({
    key,
    value: formatParameterValue(value, assets),
  }));
}

const RETRY_POLICY_LABELS: Record<string, string> = {
  inspect_then_explicit_generation_retry: "先检查 Provider 状态，再显式重试。",
  explicit_generation_retry_after_fix: "修正输入后显式重试。",
  explicit_generation_retry_if_inputs_unchanged: "输入未变时可显式重试。",
  wait_same_generation: "等待当前任务，不要新建重复任务。",
  none: "无需重试。",
};

function recoveryLabel(recovery: PlaygroundRun["recovery"]): string {
  return RETRY_POLICY_LABELS[recovery.retry_policy] ?? recovery.retry_policy;
}

function elapsedLabel(run: PlaygroundRun): string | null {
  if (!TERMINAL_PHASES.has(run.phase)) return null;
  const seconds =
    (Date.parse(run.updated_at) - Date.parse(run.created_at)) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return `用时 ${seconds.toFixed(1)} 秒`;
  return `用时 ${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
}

export function RunCard({
  run,
  assets,
  capabilities = [],
  highlighted = false,
  selected = false,
  onToggleSelected,
  onUseParameters,
  onUseAsInput,
  onChanged,
  disabled = false,
}: {
  run: PlaygroundRun;
  assets: PlaygroundAsset[];
  capabilities?: PlaygroundCapabilityInfo[];
  highlighted?: boolean;
  selected?: boolean;
  onToggleSelected?: (runId: string) => void;
  onUseParameters: (
    capability: PlaygroundCapabilityId,
    parameters: Record<string, unknown>,
  ) => void;
  onUseAsInput: (target: SlotTarget, assetId: string) => void;
  onChanged: () => void;
  disabled?: boolean;
}) {
  const [editingNote, setEditingNote] = useState(false);
  const [note, setNote] = useState(run.note ?? "");
  const [targetsOpen, setTargetsOpen] = useState(false);
  const [showParameters, setShowParameters] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const committed = useRef(false);
  const output = assetById(assets, run.output_asset_id);
  const targets = output === null ? [] : outputTargets(output, capabilities);
  const parameters = summarizeParameters(run.parameters, assets);
  const transcript =
    typeof run.result?.transcript === "string" ? run.result.transcript : null;

  async function act(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      onChanged();
    } catch (caught) {
      setError(
        caught instanceof StoryRailApiError
          ? caught.message
          : "操作失败，请重试。",
      );
    }
  }

  function startEditingNote() {
    committed.current = false;
    setNote(run.note ?? "");
    setEditingNote(true);
  }

  function finishEditingNote(save: boolean) {
    if (committed.current) return;
    committed.current = true;
    setEditingNote(false);
    if (!save) {
      setNote(run.note ?? "");
      return;
    }
    const next = note.trim() === "" ? null : note.trim();
    if (next === run.note) return;
    void act(() => playgroundApi.setNote(run.id, next));
  }

  return (
    <article
      className={[
        "playground-run-card",
        highlighted ? "is-highlighted" : "",
        run.dismissed ? "is-dismissed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={`${run.capability_label} 实验`}
    >
      <header className="playground-run-head">
        <strong>{run.capability_label}</strong>
        <span className={`playground-phase-badge phase-${run.phase}`}>
          {generationPhaseLabel(run.phase)}
        </span>
        <span className="playground-run-time">
          {new Date(run.created_at).toLocaleString("zh-CN")}
        </span>
        {elapsedLabel(run) === null ? null : (
          <span className="playground-run-time">{elapsedLabel(run)}</span>
        )}
        {run.provider?.summary ? (
          <span className="playground-run-time" title="提交时的 Provider 设置">
            {run.provider.summary}
          </span>
        ) : null}
        {onToggleSelected === undefined ? null : (
          <label>
            <input
              type="checkbox"
              aria-label={`对比 ${run.capability_label} ${run.id.slice(0, 8)}`}
              checked={selected}
              onChange={() => onToggleSelected(run.id)}
            />
            对比
          </label>
        )}
      </header>

      {TERMINAL_PHASES.has(run.phase) ? null : (
        <>
          <div className="playground-progress">
            <span style={{ width: `${Math.round(run.progress * 100)}%` }} />
          </div>
          <p className="playground-hint">{run.message}</p>
        </>
      )}
      {run.error_code === null ? null : (
        <>
          <p className="playground-error" role="alert">
            {run.error_code} · {run.message}
          </p>
          <p className="playground-hint">
            恢复建议：{recoveryLabel(run.recovery)}
          </p>
        </>
      )}

      <div className="playground-param-summary">
        <span>参数摘要</span>
        <ul>
          {parameters.map((entry) => (
            <li key={entry.key}>
              <code>{entry.key}</code> = {entry.value}
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="secondary-button"
          aria-expanded={showParameters}
          onClick={() => setShowParameters((open) => !open)}
        >
          {showParameters ? "收起完整 JSON" : "展开完整 JSON"}
        </button>
        {showParameters ? (
          <pre>{JSON.stringify(run.parameters, null, 2)}</pre>
        ) : null}
        {run.input_labels === undefined ? null : (
          <ul>
            {run.input_labels.map((label) => (
              <li key={`${label.label}-${label.asset_id}`}>
                <code>{label.label}</code> · {label.provider_input} ·{" "}
                {assetById(assets, label.asset_id)?.display_name ??
                  DELETED_ASSET}
              </li>
            ))}
          </ul>
        )}
      </div>

      {transcript !== null ? (
        <div className="playground-run-media">
          <pre>{transcript}</pre>
          <button
            type="button"
            className="secondary-button"
            onClick={() => void copyText(transcript)}
          >
            复制转写
          </button>
        </div>
      ) : null}
      {run.output_asset_id !== null ? (
        <div className="playground-run-media">
          {output === null ? (
            <p className="playground-hint">{DELETED_OUTPUT}</p>
          ) : output.media_type.startsWith("image/") ? (
            <ZoomableImage src={output.content_url} alt={`${run.capability_label}产物`} />
          ) : output.media_type === "audio/wav" ? (
            <audio controls preload="none" src={output.content_url} />
          ) : (
            <video controls preload="none" src={output.content_url} />
          )}
        </div>
      ) : null}

      <div className="playground-run-note">
        {editingNote ? (
          <input
            type="text"
            aria-label="实验备注"
            autoFocus
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onBlur={() => finishEditingNote(true)}
            onKeyDown={(event) => {
              if (event.key === "Enter") finishEditingNote(true);
              if (event.key === "Escape") finishEditingNote(false);
            }}
          />
        ) : (
          <span>{run.note === null ? "无备注" : run.note}</span>
        )}
        {run.allowed_actions.includes("set_note") && !editingNote ? (
          <button
            type="button"
            className="secondary-button"
            disabled={disabled}
            onClick={startEditingNote}
          >
            备注
          </button>
        ) : null}
      </div>

      {error === null ? null : (
        <p className="playground-error" role="alert">
          {error}
        </p>
      )}

      <div className="playground-run-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={disabled}
          onClick={() => onUseParameters(run.capability, run.parameters)}
        >
          用这组参数
        </button>
        {targets.length === 0 ? null : (
          <div className="playground-input-targets">
            <button
              type="button"
              className="secondary-button"
              aria-expanded={targetsOpen}
              disabled={disabled}
              onClick={() => setTargetsOpen((open) => !open)}
            >
              作为输入 ▾
            </button>
            {targetsOpen ? (
              <div className="playground-input-targets-menu">
                {targets.map((target) => (
                  <button
                    key={`${target.capability}-${target.key}-${target.label}`}
                    type="button"
                    disabled={run.output_asset_id === null}
                    onClick={() => {
                      setTargetsOpen(false);
                      if (run.output_asset_id !== null) {
                        onUseAsInput(target, run.output_asset_id);
                      }
                    }}
                  >
                    {target.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        )}
        {run.allowed_actions.includes("retry") ? (
          <button
            type="button"
            className="secondary-button"
            disabled={disabled}
            onClick={() => void act(() => playgroundApi.retryRun(run.id))}
          >
            重试
          </button>
        ) : null}
        {run.allowed_actions.includes("cancel") ? (
          <button
            type="button"
            className="delete-button"
            disabled={disabled}
            onClick={() => void act(() => playgroundApi.cancelRun(run.id))}
          >
            取消
          </button>
        ) : null}
        {run.allowed_actions.includes("dismiss") ? (
          <button
            type="button"
            className="secondary-button"
            disabled={disabled}
            onClick={() => void act(() => playgroundApi.dismissRun(run.id))}
          >
            隐藏
          </button>
        ) : null}
      </div>
    </article>
  );
}
