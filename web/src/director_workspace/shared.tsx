import { DismissibleDialog } from "../DismissibleDialog";
import { Children, type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
// 图片放大查看已抽到 web/src/ImagePreview.tsx，供导演台外的其它页面（如 Playground 资产窗口）复用。
import { ImageZoomButton, ZoomableImage } from "../ImagePreview";
import type {
  ImageAssetCategory,
  ImageSubmissionPreview,
  ProjectAsset,
  ReferenceGeneration,
  StructuredDirectorSnapshot,
} from "../api";
export function CapabilityGapBanner({
  alerts,
}: {
  alerts: NonNullable<StructuredDirectorSnapshot["capability_gap_alerts"]>;
}) {
  const open = alerts.filter((item) => item.status === "open");
  if (open.length === 0) return null;
  return (
    <aside className="capability-gap-banner" aria-label="能力缺口报警">
      <strong>⚠ CAPABILITY_GAP · {open.length} 项待收口</strong>
      <span>受控 repair 已完成，项目可继续工作；这不是正式领域能力。</span>
      <details>
        <summary>查看修复记录</summary>
        <div>
          {open.map((item) => (
            <article key={item.gap_id}>
              <b>{item.missing_command}</b>
              <p>{item.operation_summary}</p>
              <small>
                revision {item.old_revision} → {item.new_revision} · 发生{" "}
                {item.occurrence_count} 次 · {item.raw_user_request_summary}
              </small>
            </article>
          ))}
        </div>
      </details>
    </aside>
  );
}
// 保留旧的导入路径，导演台各文件继续从本模块取 ZoomableImage。
export { ZoomableImage };
export function DirectorDisclosure({
  className,
  id,
  forceOpen = false,
  initiallyOpen = true,
  children,
}: {
  className: string;
  id?: string;
  forceOpen?: boolean;
  initiallyOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const [hasOpened, setHasOpened] = useState(initiallyOpen);
  const items = Children.toArray(children);
  useEffect(() => {
    if (!forceOpen) return;
    setOpen(true);
    setHasOpened(true);
  }, [forceOpen]);
  return (
    <details
      className={className}
      id={id}
      open={forceOpen || open}
      onClick={(event) => {
        const target = event.target;
        if (
          !(target instanceof Element) ||
          target.closest("summary") !== event.currentTarget.firstElementChild ||
          target.closest("button, a, input, select, textarea")
        )
          return;
        // 同步记录用户操作，避免原生异步 toggle 与保存后的渲染竞争。
        event.preventDefault();
        setOpen((current) => !current);
        setHasOpened(true);
      }}
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        const nextOpen = event.currentTarget.open;
        setOpen(nextOpen);
        if (nextOpen) setHasOpened(true);
      }}
    >
      {items[0]}
      {forceOpen || hasOpened ? items.slice(1) : null}
    </details>
  );
}
export function ImagePromptEditorFields({
  referencePrompt,
  promptLabel,
  promptText,
  promptPlaceholder,
  onPromptChange,
  disabled,
}: {
  referencePrompt: string;
  promptLabel: string;
  promptText: string;
  promptPlaceholder?: string;
  onPromptChange: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <>
      <label className="card-field">
        <span>图片引用（Core 固定，只读）</span>
        <textarea readOnly rows={6} value={referencePrompt} />
      </label>
      <label className="card-field">
        <span>{promptLabel}</span>
        <textarea
          value={promptText}
          placeholder={promptPlaceholder}
          disabled={disabled}
          onChange={(event) => onPromptChange(event.target.value)}
        />
      </label>
      <p className="muted-copy">
        可直接编辑提示词，或在外部 Agent 中读取当前图片与专业工作集后提交。
      </p>
    </>
  );
}

export function ImageSubmissionPreviewDialog({
  preview,
  onClose,
}: {
  preview: {
    data: ImageSubmissionPreview | null;
    error: string | null;
  };
  onClose: () => void;
}) {
  return createPortal(
    <div
      className="scene-submission-preview-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="scene-submission-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="最终完整提示词预览"
      >
        <header>
          <div>
            <p className="eyebrow">Actual image request</p>
            <h2>最终完整提示词预览</h2>
          </div>
          <button
            autoFocus
            type="button"
            className="secondary-button"
            onClick={onClose}
          >
            关闭
          </button>
        </header>
        {preview.error !== null ? (
          <p className="reference-error" role="alert">
            {preview.error}
          </p>
        ) : preview.data === null ? (
          <p className="muted-copy">正在编译真实提交内容…</p>
        ) : (
          <>
            <section className="scene-submission-attachments">
              <h3>实际提交的图片附件</h3>
              {preview.data.attachments.length === 0 ? (
                <p className="muted-copy">本次不提交图片附件。</p>
              ) : (
                <div>
                  {preview.data.attachments.map((attachment, index) => (
                    <figure key={`${attachment.role}:${attachment.asset_id}`}>
                      <ZoomableImage
                        src={attachment.content_url}
                        alt={`图${index + 1} ${attachment.display_name}`}
                      />
                      <figcaption>
                        <strong>
                          图{index + 1} · {attachment.display_name}
                        </strong>
                        <span>
                          {attachment.role === "source_image"
                            ? "编辑底图 · source_image"
                            : `参考附件 · reference_images[${
                                preview
                                  .data!.attachments.slice(0, index)
                                  .filter(
                                    (item) => item.role === "reference_image",
                                  ).length
                              }]`}
                        </span>
                      </figcaption>
                    </figure>
                  ))}
                </div>
              )}
            </section>
            <label className="card-field scene-submission-instruction">
              <span>实际提交的完整 instruction</span>
              <textarea
                readOnly
                rows={18}
                value={
                  preview.data.instruction ??
                  "依赖图片尚未就绪，当前不能形成真实提交请求。"
                }
              />
            </label>
          </>
        )}
      </DismissibleDialog>
    </div>,
    document.body,
  );
}
export function SingleImageAssetPickerDialog({
  title,
  ariaLabel,
  assets,
  selectedAssetId,
  busy,
  onClose,
  onSelect,
}: {
  title: string;
  ariaLabel: string;
  assets: ProjectAsset[];
  selectedAssetId: string | null;
  busy: boolean;
  onClose: () => void;
  onSelect: (assetId: string) => void;
}) {
  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="scene-asset-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
      >
        <header>
          <div>
            <p className="eyebrow">Project images</p>
            <h2>{title}</h2>
          </div>
          <button
            autoFocus
            type="button"
            className="secondary-button"
            onClick={onClose}
          >
            关闭
          </button>
        </header>
        <div className="scene-asset-picker-scroll">
          <div className="scene-asset-picker-grid">
            {assets.map((asset) => {
              const name = asset.display_name ?? "项目图片";
              return (
                <div className="zoomable-tile" key={asset.id}>
                  <button
                    type="button"
                    className={asset.id === selectedAssetId ? "is-selected" : ""}
                    disabled={busy || asset.id === selectedAssetId}
                    aria-label={`选择 ${name}`}
                    onClick={() => onSelect(asset.id)}
                  >
                    <img loading="lazy" src={asset.content_url} alt={name} />
                    <span>{name}</span>
                    {asset.id === selectedAssetId ? <small>当前选择</small> : null}
                  </button>
                  <ImageZoomButton src={asset.content_url} alt={name} />
                </div>
              );
            })}
          </div>
          {assets.length === 0 ? (
            <p className="muted-copy">项目中还没有可用图片。</p>
          ) : null}
        </div>
      </DismissibleDialog>
    </div>,
    document.body,
  );
}
export function SingleAudioAssetPickerDialog({
  title = "添加音频",
  assets,
  busy,
  onClose,
  onSelect,
}: {
  title?: string;
  assets: ProjectAsset[];
  busy: boolean;
  onClose: () => void;
  onSelect: (assetId: string) => void;
}) {
  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="scene-asset-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <div>
            <p className="eyebrow">Project audio</p>
            <h2>{title}</h2>
            <span>选择当前槽位支持的项目音频。</span>
          </div>
          <button
            autoFocus
            type="button"
            className="secondary-button"
            onClick={onClose}
          >
            关闭
          </button>
        </header>
        <div className="scene-asset-picker-scroll">
          <div className="audio-asset-picker-list">
            {assets.map((asset) => (
              <article key={asset.id}>
                <strong>{asset.display_name ?? "项目音频"}</strong>
                <AssetAudio asset={asset} />
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  aria-label={`选择 ${asset.display_name ?? "项目音频"}`}
                  onClick={() => onSelect(asset.id)}
                >
                  选择
                </button>
              </article>
            ))}
          </div>
          {assets.length === 0 ? (
            <p className="muted-copy">项目中还没有 WAV 音频。</p>
          ) : null}
        </div>
      </DismissibleDialog>
    </div>,
    document.body,
  );
}
export function SingleVideoAssetPickerDialog({
  assets,
  attachedAssetIds,
  busy,
  onClose,
  onSelect,
  title = "增加视频候选",
  ariaLabel = "从资产库增加视频候选",
  description = "只增加候选，不会切换当前选择。任意时长的 MP4 都可挂接，不改变当前 Segment 的生成预算。",
  emptyMessage = "项目中还没有不短于 0.2 秒的 MP4 视频。",
  attachedLabel = "已是候选",
  attachedHint = "已在当前候选中",
}: {
  assets: ProjectAsset[];
  attachedAssetIds: string[];
  busy: boolean;
  onClose: () => void;
  onSelect: (assetId: string) => void;
  title?: string;
  ariaLabel?: string;
  description?: string;
  emptyMessage?: string;
  attachedLabel?: string;
  attachedHint?: string;
}) {
  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="scene-asset-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
      >
        <header>
          <div>
            <p className="eyebrow">Project videos</p>
            <h2>{title}</h2>
            <span>{description}</span>
          </div>
          <button
            autoFocus
            type="button"
            className="secondary-button"
            onClick={onClose}
          >
            关闭
          </button>
        </header>
        <div className="scene-asset-picker-scroll">
          <div className="scene-asset-picker-grid video-asset-picker-grid">
            {assets.map((asset) => {
              const name = asset.display_name ?? "项目视频";
              const attached = attachedAssetIds.includes(asset.id);
              return (
                <button
                  type="button"
                  key={asset.id}
                  className={attached ? "is-selected" : ""}
                  disabled={busy || attached}
                  aria-label={`${attached ? attachedLabel : "增加"} ${name}`}
                  onClick={() => onSelect(asset.id)}
                >
                  <video
                    muted
                    playsInline
                    preload="metadata"
                    src={asset.content_url}
                  />
                  <span>{name}</span>
                  <small>
                    {attached
                      ? attachedHint
                      : formatDuration(asset.duration_seconds ?? 0)}
                  </small>
                </button>
              );
            })}
          </div>
          {assets.length === 0 ? (
            <p className="muted-copy">{emptyMessage}</p>
          ) : null}
        </div>
      </DismissibleDialog>
    </div>,
    document.body,
  );
}
export function MultiImageAssetPickerDialog({
  title,
  ariaLabel,
  assets,
  selectedAssetIds,
  maxSelected,
  busy,
  onClose,
  onChange,
}: {
  title: string;
  ariaLabel: string;
  assets: ProjectAsset[];
  selectedAssetIds: string[];
  maxSelected: number;
  busy: boolean;
  onClose: () => void;
  onChange: (assetIds: string[]) => void;
}) {
  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="scene-asset-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
      >
        <header>
          <div>
            <p className="eyebrow">Project images</p>
            <h2>{title}</h2>
            <span>可选择任意项目图片，最多 {maxSelected} 张。</span>
          </div>
          <button
            autoFocus
            type="button"
            className="secondary-button"
            onClick={onClose}
          >
            完成
          </button>
        </header>
        <div className="scene-asset-picker-scroll">
          <div className="scene-asset-picker-grid">
            {assets.map((asset) => {
              const name = asset.display_name ?? "项目图片";
              const selected = selectedAssetIds.includes(asset.id);
              return (
                <div className="zoomable-tile" key={asset.id}>
                  <button
                    type="button"
                    className={selected ? "is-selected" : ""}
                    disabled={
                      busy || (!selected && selectedAssetIds.length >= maxSelected)
                    }
                    aria-pressed={selected}
                    aria-label={`${selected ? "取消选择" : "选择"} ${name}`}
                    onClick={() => onChange(toggleId(selectedAssetIds, asset.id))}
                  >
                    <img loading="lazy" src={asset.content_url} alt={name} />
                    <span>{name}</span>
                    <small>{selected ? "已选择" : "点击选择"}</small>
                  </button>
                  <ImageZoomButton src={asset.content_url} alt={name} />
                </div>
              );
            })}
          </div>
          {assets.length === 0 ? (
            <p className="muted-copy">项目中还没有可用图片。</p>
          ) : null}
        </div>
      </DismissibleDialog>
    </div>,
    document.body,
  );
}
export function formatDuration(seconds: number): string {
  return `${Number(seconds.toFixed(1))} 秒`;
}
export function CardHeading({ kind, name }: { kind: string; name: string }) {
  return (
    <header className="reference-card-heading">
      <span>{kind}</span>
      <h2>{name}</h2>
    </header>
  );
}
export function CardActions({
  busy,
  confirmDiscard,
  onConfirmDiscard,
  onDiscard,
}: {
  busy: boolean;
  confirmDiscard: boolean;
  onConfirmDiscard: (value: boolean) => void;
  onDiscard: () => void;
}) {
  return (
    <footer className="reference-card-actions">
      {confirmDiscard ? (
        <div className="card-decision-panel">
          <p>只会移出全局引用库，不会修改剧情。</p>
          <button
            className="danger-text"
            type="button"
            disabled={busy}
            onClick={onDiscard}
          >
            确认移出
          </button>
          <button type="button" onClick={() => onConfirmDiscard(false)}>
            取消
          </button>
        </div>
      ) : (
        <button
          className="delete-button"
          type="button"
          disabled={busy}
          onClick={() => onConfirmDiscard(true)}
        >
          移出引用库
        </button>
      )}
      <button className="primary-button" type="submit" disabled={busy}>
        保存卡片
      </button>
    </footer>
  );
}
export function NewCardActions({
  busy,
  onCancel,
}: {
  busy: boolean;
  onCancel: () => void;
}) {
  return (
    <footer className="reference-card-actions">
      <button
        className="delete-button"
        type="button"
        disabled={busy}
        onClick={onCancel}
      >
        取消
      </button>
      <button className="primary-button" disabled={busy}>
        创建卡片
      </button>
    </footer>
  );
}
export function TextField({
  label,
  value,
  required = false,
  readOnly = false,
  onChange,
}: {
  label: string;
  value: string;
  required?: boolean;
  readOnly?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="card-field">
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      <input
        value={value}
        required={required}
        readOnly={readOnly}
        onChange={
          readOnly ? undefined : (event) => onChange(event.target.value)
        }
      />
    </label>
  );
}
export function TextArea({
  label,
  value,
  required = false,
  readOnly = false,
  onChange,
}: {
  label: string;
  value: string;
  required?: boolean;
  readOnly?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="card-field">
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      <textarea
        value={value}
        required={required}
        readOnly={readOnly}
        onChange={
          readOnly ? undefined : (event) => onChange(event.target.value)
        }
      />
    </label>
  );
}
export function AssetAudio({ asset }: { asset: ProjectAsset | null }) {
  return asset ? (
    <audio
      aria-label={`播放 ${asset.display_name ?? "项目音频"}`}
      controls
      preload="none"
      src={asset.content_url}
    />
  ) : (
    <p className="muted-copy">音频 Asset 不可用。</p>
  );
}
export function assetById(
  assets: ProjectAsset[],
  id: string,
): ProjectAsset | null {
  return assets.find((asset) => asset.id === id) ?? null;
}
export function imageAssets(
  assets: ProjectAsset[],
  category?: ImageAssetCategory,
): ProjectAsset[] {
  return assets.filter(
    (asset) =>
      asset.media_type.startsWith("image/") &&
      (category === undefined ||
        // 未分类的历史图片与抽帧图仍留在库内选择器中，不因新增分类而消失。
        asset.image_category === null ||
        asset.image_category === undefined ||
        asset.image_category === "video_frame" ||
        asset.image_category === category),
  );
}
export function cardGenerations(
  snapshot: StructuredDirectorSnapshot,
  cardId: string,
  kind: ReferenceGeneration["kind"],
): ReferenceGeneration[] {
  return snapshot.generations.filter(
    (item) =>
      item.target_id === cardId && item.kind === kind && !item.dismissed,
  );
}
export function toggleId(values: string[], id: string): string[] {
  return values.includes(id)
    ? values.filter((value) => value !== id)
    : [...values, id];
}
export function isSupportedImageType(
  value: string,
): value is "image/png" | "image/jpeg" | "image/webp" {
  return (
    value === "image/png" || value === "image/jpeg" || value === "image/webp"
  );
}
export function isSupportedWavFile(file: File): boolean {
  return (
    file.name.toLowerCase().endsWith(".wav") &&
    (file.type === "" ||
      file.type === "audio/wav" ||
      file.type === "audio/x-wav" ||
      file.type === "audio/wave" ||
      file.type === "audio/vnd.wave")
  );
}

export function GenerationCandidateList({
  kind,
  target,
  assets,
  candidates,
  active = null,
  collapsible = true,
  busy,
  emptyText,
  workingText,
  summary,
  selectLabel = "选择候选",
  selectedLabel = "当前选择",
  onSelect,
  selectDisabled,
  dismissLabel = "隐藏历史",
  dismissConfirmation = "隐藏后不再显示；废弃产物可随后在资产中心永久清理。",
  onDismiss,
  dismissAllowed,
  dismissDisabled,
  renderCandidate,
  isSelected,
}: {
  kind: string;
  target: string;
  assets: ProjectAsset[];
  candidates: ReferenceGeneration[];
  active?: ReferenceGeneration | null;
  busy: boolean;
  emptyText?: string;
  workingText?: string;
  summary: string;
  collapsible?: boolean;
  selectLabel?: string;
  selectedLabel?: string;
  onSelect?: (generation: ReferenceGeneration) => void;
  selectDisabled?: (generation: ReferenceGeneration, asset: ProjectAsset) => boolean;
  dismissLabel?: string;
  dismissConfirmation?: string;
  onDismiss?: (generationId: string) => void;
  dismissAllowed?: (generation: ReferenceGeneration) => boolean;
  dismissDisabled?: (generation: ReferenceGeneration) => boolean;
  renderCandidate: (
    generation: ReferenceGeneration,
    asset: ProjectAsset | null,
    selected: boolean,
  ) => ReactNode;
  isSelected?: (generation: ReferenceGeneration, asset: ProjectAsset | null) => boolean;
}) {
  const [confirmDismiss, setConfirmDismiss] = useState<string | null>(null);
  return (
    <div className={`${kind}-candidate-list`} data-candidate-target={target}>
      {active ? (
        <div className="candidate-working" role="status">
          <strong>{workingText ?? "生成中"}</strong>
          <progress max={1} value={active.progress} />
          <p>{active.message}</p>
        </div>
      ) : null}
      {candidates.length === 0 ? (
        emptyText ? <p className={`${kind}-candidate-empty`}>{emptyText}</p> : null
      ) : (
        <details open={collapsible === false}>
          <summary>{summary}</summary>
          <div className={`${kind}-candidates`}>
            {candidates.map((generation) => {
              const asset = generation.output_asset_id
                ? assetById(assets, generation.output_asset_id)
                : null;
              const selected = isSelected?.(generation, asset) ?? false;
              return (
                <article className={`${kind}-candidate`} key={generation.id}>
                  {renderCandidate(generation, asset, selected)}
                  {generation.provider?.summary ? (
                    <small className="candidate-provider" title="提交时的 Provider 设置">
                      {generation.provider.summary}
                    </small>
                  ) : null}
                  {onSelect && asset ? (
                    <button
                      type="button"
                      className={`${kind}-candidate-select secondary-button`}
                      disabled={busy || (selectDisabled?.(generation, asset) ?? false)}
                      onClick={() => onSelect(generation)}
                    >
                      {selected ? selectedLabel : selectLabel}
                    </button>
                  ) : null}
                  {onDismiss && (dismissAllowed?.(generation) ?? true) ? (
                    confirmDismiss === generation.id ? (
                      <div className="candidate-dismiss-confirm">
                        <span>{dismissConfirmation}</span>
                        <button
                          type="button"
                          className="delete-button"
                          disabled={busy || (dismissDisabled?.(generation) ?? false)}
                          onClick={() => onDismiss(generation.id)}
                        >确认隐藏</button>
                        <button type="button" className="secondary-button" onClick={() => setConfirmDismiss(null)}>取消</button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="delete-button"
                        disabled={busy || (dismissDisabled?.(generation) ?? false)}
                        onClick={() => setConfirmDismiss(generation.id)}
                      >{dismissLabel}</button>
                    )
                  ) : null}
                </article>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
}

export type VideoFrameInfo = { frame_count: number; duration_seconds: number | null };

/** 按帧号抽帧：范围 0-(N-1) 直接显示，默认最后一帧；预览只是浏览器定位，实际帧由 Core/FFmpeg 精确抽取。 */
export function VideoFrameExtractDialog({
  videoUrl,
  title,
  description,
  busy,
  loadInfo,
  onClose,
  onConfirm,
}: {
  videoUrl: string;
  title: string;
  description: string;
  busy: boolean;
  loadInfo: () => Promise<VideoFrameInfo>;
  onClose: () => void;
  onConfirm: (frameIndex: number) => void;
}) {
  const [info, setInfo] = useState<VideoFrameInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  // 只在打开时读取一次帧数；调用方通常传入内联函数。
  const loadInfoRef = useRef(loadInfo);
  useEffect(() => {
    let cancelled = false;
    loadInfoRef.current().then(
      (value) => {
        if (cancelled) return;
        setInfo(value);
        setDraft(String(value.frame_count - 1));
      },
      (reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "无法读取视频帧数。");
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);
  const last = info === null ? null : info.frame_count - 1;
  const index = /^\d+$/.test(draft) ? Number(draft) : null;
  const valid = last !== null && index !== null && index <= last;
  useEffect(() => {
    const video = videoRef.current;
    if (!valid || video === null || info === null || info.duration_seconds === null) return;
    // 取帧中点定位，避免浏览器落在相邻帧边界。
    video.currentTime = ((index + 0.5) / info.frame_count) * info.duration_seconds;
  }, [valid, index, info]);
  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="scene-asset-picker-dialog video-frame-extract-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <div>
            <p className="eyebrow">Video frame</p>
            <h2>{title}</h2>
            <span>{description}</span>
          </div>
          <button autoFocus type="button" className="secondary-button" onClick={onClose}>
            关闭
          </button>
        </header>
        <div className="video-frame-extract-body">
          <video ref={videoRef} src={videoUrl} preload="auto" muted playsInline />
          {error !== null ? (
            <p role="alert">{error}</p>
          ) : last === null ? (
            <p role="status">正在读取视频帧数…</p>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (valid) onConfirm(index);
              }}
            >
              <label>
                <span>帧号</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={last}
                  step={1}
                  value={draft}
                  aria-label="抽帧帧号"
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>
              <input
                type="range"
                min={0}
                max={last}
                step={1}
                value={valid ? index : last}
                aria-label="抽帧位置"
                onChange={(event) => setDraft(event.target.value)}
              />
              <small>
                可选范围 {`0-${last}`}（共 {info?.frame_count} 帧），默认最后一帧。预览为浏览器近似定位。
              </small>
              <div className="video-frame-extract-actions">
                <button type="button" className="text-button" onClick={() => setDraft(String(last))}>
                  最后一帧
                </button>
                <button type="submit" className="primary-button" disabled={busy || !valid}>
                  抽取第 {valid ? index : "?"} 帧
                </button>
              </div>
            </form>
          )}
        </div>
      </DismissibleDialog>
    </div>,
    document.body,
  );
}
