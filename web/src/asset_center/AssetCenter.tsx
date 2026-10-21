import { DismissibleDialog } from "../DismissibleDialog";
import { useEffect, useRef, useState } from "react";
import { ZoomableImage } from "../ImagePreview";
import type { ClipboardEvent as ReactClipboardEvent } from "react";

import type {
  AudioEffectPreset,
  AudioEffectSettings,
  AudioGenerationSettings,
  AudioTrimSettings,
  AudioGainSettings,
  ImageAssetCategory,
  PlaygroundAsset,
  ProjectAsset,
  ProviderRecipeView,
  ReferenceGeneration,
} from "../api";
import { SettingField, type SettingValue } from "../provider_settings/SettingField";
import { VideoFrameExtractDialog, type VideoFrameInfo } from "../director_workspace/shared";

type AssetFilter = "all" | "image" | ImageAssetCategory | "audio" | "video" | "playground";

const IMAGE_CATEGORIES: Array<{ value: ImageAssetCategory; label: string }> = [
  { value: "character_reference", label: "角色参考图" },
  { value: "location_image", label: "地点图片" },
  { value: "panorama_capture", label: "地点裁切图" },
  { value: "keyframe", label: "Keyframe 图" },
  { value: "video_frame", label: "抽帧图" },
];
// 抽帧图与全景裁切图由 Core 生成，只能浏览，不能作为导入分类。
export const IMPORT_IMAGE_CATEGORIES = IMAGE_CATEGORIES.filter(
  (item) => item.value !== "video_frame" && item.value !== "panorama_capture",
);

const AUDIO_EFFECT_PRESETS: Array<{
  value: AudioEffectPreset;
  label: string;
  description: string;
}> = [
  { value: "walkie_talkie", label: "手持对讲机", description: "清晰窄带，轻微静电。" },
  { value: "military_radio", label: "军用无线电", description: "更紧的动态与低带宽质感。" },
  { value: "weak_signal", label: "弱信号", description: "仍可听清，伴随轻微掉线。" },
  { value: "bad_signal", label: "信号不良", description: "明显不稳定，但大部分可理解。" },
  {
    value: "dying_transmission",
    label: "逐渐中断",
    description: "噪声、掉线和低带宽随时间增强。",
  },
];

interface AssetCenterProps {
  providerRecipes?: ProviderRecipeView[];
  assets: ProjectAsset[];
  generations: ReferenceGeneration[];
  audioSeparationAvailable: boolean;
  audioRemixAvailable: boolean;
  voiceDesignAvailable: boolean;
  speechSynthesisAvailable: boolean;
  speechRecognitionAvailable: boolean;
  referenceVoiceTranscripts: Record<string, string | null>;
  busy: boolean;
  canGenerateAudio: boolean;
  canImportImage: boolean;
  canImportMedia: boolean;
  canDeleteAssets: boolean;
  onClose: () => void;
  onImportImage: (files: File[], category: ImageAssetCategory) => void;
  onImportMedia: (files: File[]) => void;
  onDelete: (assetId: string) => void;
  onDeleteMany: (assetIds: string[]) => void;
  onGenerateAudio: (settings: AudioGenerationSettings) => Promise<boolean>;
  onTrimAudio: (assetId: string, settings: AudioTrimSettings) => Promise<boolean>;
  onApplyAudioEffect: (assetId: string, settings: AudioEffectSettings) => void;
  onSeparateVideoAudio: (assetId: string) => void;
  onExtractVideoFrame: (assetId: string, frameIndex: number) => void;
  onLoadVideoFrameInfo?: (assetId: string) => Promise<VideoFrameInfo>;
  onRemixVideoAudio: (assetId: string, voiceAssetId: string, backgroundAssetId: string,
    voiceGain: AudioGainSettings, backgroundGain: AudioGainSettings) => Promise<boolean>;
  initialFilter?: AssetFilter;
  voiceSelectionTarget?: {
    name: string;
    currentAssetId: string | null;
  } | null;
  onSelectReferenceVoice?: (assetId: string) => void;
  // 两者都传入时才显示「Playground」页签，避免破坏既有调用点。
  onLoadPlaygroundAssets?: () => Promise<PlaygroundAsset[]>;
  onCopyFromPlayground?: (
    assetId: string,
    category: ImageAssetCategory | null,
  ) => Promise<boolean>;
}

export function AssetCenter({
  assets,
  generations,
  audioSeparationAvailable,
  audioRemixAvailable,
  voiceDesignAvailable,
  speechSynthesisAvailable,
  providerRecipes = [],
  referenceVoiceTranscripts,
  busy,
  canGenerateAudio,
  canImportImage,
  canImportMedia,
  canDeleteAssets,
  onClose,
  onImportImage,
  onImportMedia,
  onDelete,
  onDeleteMany,
  onGenerateAudio,
  onTrimAudio,
  onApplyAudioEffect,
  onSeparateVideoAudio,
  onExtractVideoFrame,
  onLoadVideoFrameInfo,
  onRemixVideoAudio,
  initialFilter = "all",
  voiceSelectionTarget = null,
  onSelectReferenceVoice,
  onLoadPlaygroundAssets,
  onCopyFromPlayground,
}: AssetCenterProps) {
  const [filter, setFilter] = useState<AssetFilter>(initialFilter);
  const [frameAsset, setFrameAsset] = useState<ProjectAsset | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [confirmingBulkDelete, setConfirmingBulkDelete] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importCategory, setImportCategory] = useState<ImageAssetCategory | "">("");
  const [effectAssetId, setEffectAssetId] = useState<string | null>(null);
  const [audioCreatorOpen, setAudioCreatorOpen] = useState(false);
  const [audioCreatorBaselineGenerationIds, setAudioCreatorBaselineGenerationIds] =
    useState<Set<string>>(() => new Set());
  const [audioOperation, setAudioOperation] = useState<"voice_design" | "synthesize">("voice_design");
  const [audioText, setAudioText] = useState("");
  const [voiceDescription, setVoiceDescription] = useState("");
  const [recipeParams, setRecipeParams] = useState<Record<string, Record<string, unknown>>>({});
  const speechRecipe = providerRecipes.find((item) => item.capability === "speech.synthesize");
  const [referenceVoiceAssetId, setReferenceVoiceAssetId] = useState("");
  const [audioSeed, setAudioSeed] = useState("42");
  const [trimAssetId, setTrimAssetId] = useState<string | null>(null);
  const [trimStartSeconds, setTrimStartSeconds] = useState("0");
  const [trimEndSeconds, setTrimEndSeconds] = useState("0");
  const [effectPreset, setEffectPreset] = useState<AudioEffectPreset>("weak_signal");
  const [effectStrength, setEffectStrength] = useState(0.7);
  const [effectSeed, setEffectSeed] = useState("42");
  const [effectStartSeconds, setEffectStartSeconds] = useState("0");
  const [effectEndSeconds, setEffectEndSeconds] = useState("0");
  const [effectTargetTrack, setEffectTargetTrack] = useState<"voice" | "background" | null>(null);
  const [videoEditorAssetId, setVideoEditorAssetId] = useState<string | null>(null);
  const [playgroundAssets, setPlaygroundAssets] = useState<PlaygroundAsset[] | null>(null);
  const [playgroundCategory, setPlaygroundCategory] = useState<ImageAssetCategory | "">("");
  const [playgroundPending, setPlaygroundPending] = useState<string | null>(null);
  const [playgroundError, setPlaygroundError] = useState<string | null>(null);
  const [playgroundNotice, setPlaygroundNotice] = useState<string | null>(null);
  const playgroundRequested = useRef(false);
  const loadPlaygroundRef = useRef(onLoadPlaygroundAssets);
  loadPlaygroundRef.current = onLoadPlaygroundAssets;
  const [voiceGainDb, setVoiceGainDb] = useState(0);
  const [backgroundGainDb, setBackgroundGainDb] = useState(0);
  const [voiceGainStartSeconds, setVoiceGainStartSeconds] = useState("0");
  const [voiceGainEndSeconds, setVoiceGainEndSeconds] = useState("0");
  const [backgroundGainStartSeconds, setBackgroundGainStartSeconds] = useState("0");
  const [backgroundGainEndSeconds, setBackgroundGainEndSeconds] = useState("0");
  const [voiceUseProcessed, setVoiceUseProcessed] = useState(false);
  const [backgroundUseProcessed, setBackgroundUseProcessed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const visibleAssets = assets.filter((asset) =>
    filter === "all" || (
      filter === "image"
        ? asset.media_type.startsWith("image/")
        : (filter === "audio" || filter === "video"
          ? asset.media_type.startsWith(`${filter}/`)
          : asset.image_category === filter)
    )
  );
  const deletableVisibleAssets = visibleAssets.filter((asset) =>
    asset.allowed_actions.includes("delete")
  );
  const filterLabel = filter === "all"
    ? "全部"
    : filter === "image" ? "图片"
    : filter === "audio" ? "音频"
    : filter === "video" ? "视频"
    : filter === "playground" ? "Playground"
    : IMAGE_CATEGORIES.find((item) => item.value === filter)?.label ?? filter;
  const showPlaygroundTab =
    onLoadPlaygroundAssets !== undefined &&
    onCopyFromPlayground !== undefined;
  const filterTabs: AssetFilter[] =
    ["all", "image", ...IMAGE_CATEGORIES.map((item) => item.value), "audio", "video"];
  if (showPlaygroundTab) filterTabs.push("playground");
  const wavAssets = assets.filter((asset) => asset.media_type === "audio/wav");
  const referenceVoiceAsset = wavAssets.find(
    (asset) => asset.id === referenceVoiceAssetId,
  ) ?? null;
  const referenceTranscript = referenceVoiceTranscripts[referenceVoiceAssetId] ?? "";
  const audioCreatorGenerations = audioCreatorOpen
    ? generations.filter((generation) =>
        generation.kind === "generated_audio" &&
        !audioCreatorBaselineGenerationIds.has(generation.id)
      ).reverse()
    : [];
  const validAudioSeed = /^[0-9]{1,19}$/.test(audioSeed) &&
    BigInt(audioSeed || "0") <= BigInt(Number.MAX_SAFE_INTEGER);
  const selectedAudioModelAvailable = audioOperation === "voice_design"
    ? voiceDesignAvailable
    : speechSynthesisAvailable;
  const validAudioGeneration = audioText.trim().length > 0 && validAudioSeed &&
    selectedAudioModelAvailable && (audioOperation === "voice_design"
      ? voiceDescription.trim().length > 0
      : referenceVoiceAssetId.length > 0 && referenceTranscript.trim().length > 0);
  const effectAsset = assets.find((asset) => asset.id === effectAssetId) ?? null;
  const trimAsset = assets.find((asset) => asset.id === trimAssetId) ?? null;
  const trimDuration = trimAsset?.duration_seconds ?? null;
  const trimStart = Number(trimStartSeconds);
  const trimEnd = Number(trimEndSeconds);
  const validTrimRange = trimDuration !== null && validTimeRange(
    trimDuration, trimStartSeconds, trimEndSeconds,
  ) && (trimStart > 0 || trimEnd < trimDuration);
  const videoEditorAsset = assets.find((asset) => asset.id === videoEditorAssetId) ?? null;
  const stemPair = videoEditorAssetId === null ? null : latestStemPair(
    generations, videoEditorAssetId,
  );
  const voiceAsset = assetForGeneration(assets, stemPair?.voice ?? null);
  const backgroundAsset = assetForGeneration(assets, stemPair?.background ?? null);
  const voiceEffectAsset = latestEffectAsset(assets, generations, voiceAsset?.id ?? null);
  const backgroundEffectAsset = latestEffectAsset(
    assets, generations, backgroundAsset?.id ?? null,
  );
  const voiceGainDuration = voiceAsset?.duration_seconds ?? videoEditorAsset?.duration_seconds ?? null;
  const backgroundGainDuration = backgroundAsset?.duration_seconds ??
    videoEditorAsset?.duration_seconds ?? null;
  const validVoiceGainRange = validTimeRange(
    voiceGainDuration, voiceGainStartSeconds, voiceGainEndSeconds,
  );
  const validBackgroundGainRange = validTimeRange(
    backgroundGainDuration, backgroundGainStartSeconds, backgroundGainEndSeconds,
  );
  const validSeed = /^[0-9]{1,19}$/.test(effectSeed) &&
    BigInt(effectSeed || "0") <= BigInt(Number.MAX_SAFE_INTEGER);
  const effectDuration = effectAsset?.duration_seconds ?? null;
  const effectStart = Number(effectStartSeconds);
  const effectEnd = Number(effectEndSeconds);
  const validRange = effectDuration === null || (
    Number.isFinite(effectStart) && Number.isFinite(effectEnd) && effectStart >= 0 &&
    effectEnd > effectStart && effectEnd <= effectDuration
  );

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  // Playground 页签懒加载：只在第一次进入时读取一次。
  useEffect(() => {
    if (filter !== "playground" || playgroundRequested.current) return;
    const loader = loadPlaygroundRef.current;
    if (loader === undefined) return;
    playgroundRequested.current = true;
    let cancelled = false;
    setPlaygroundError(null);
    void loader().then(
      (items) => {
        if (!cancelled) setPlaygroundAssets(items);
      },
      (caught: unknown) => {
        if (!cancelled) {
          setPlaygroundError(
            caught instanceof Error ? caught.message : "无法读取 Playground 资产。",
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [filter]);

  async function copyFromPlayground(asset: PlaygroundAsset) {
    if (onCopyFromPlayground === undefined) return;
    const isImage = asset.media_type.startsWith("image/");
    const category: ImageAssetCategory | null =
      isImage && playgroundCategory !== "" ? playgroundCategory : null;
    if (isImage && category === null) {
      setPlaygroundError("请先选择图片分类，再复制图片。");
      return;
    }
    setPlaygroundError(null);
    setPlaygroundNotice(null);
    setPlaygroundPending(asset.id);
    try {
      const copied = await onCopyFromPlayground(asset.id, category);
      if (copied) {
        setPlaygroundNotice(`已复制 ${asset.display_name} 到本项目。`);
        // 复制成功后切回对应类型的页签。
        setFilter(
          isImage
            ? (category ?? "image")
            : asset.media_type.startsWith("audio/")
              ? "audio"
              : "video",
        );
      }
    } catch (caught) {
      setPlaygroundError(
        caught instanceof Error ? caught.message : "复制失败，请重试。",
      );
    } finally {
      setPlaygroundPending(null);
    }
  }

  function importImages(files: File[]) {
    if (files.length === 0) return;
    if (importCategory === "") {
      setImportError("请先选择图片分类，再导入图片。");
      return;
    }
    if (!files.every(isSupportedImage)) {
      setImportError("只支持 PNG、JPEG 或 WebP 图片。");
      return;
    }
    setImportError(null);
    onImportImage(files, importCategory);
    if (inputRef.current !== null) inputRef.current.value = "";
  }

  function pasteImage(event: ReactClipboardEvent<HTMLElement>) {
    const file = clipboardImage(event.clipboardData);
    if (file === null) return;
    event.preventDefault();
    if (busy || !canImportImage) return;
    importImages([file]);
  }

  function importMedia(files: File[]) {
    if (files.length === 0) return;
    const supported = filter === "audio" ? files.every(isSupportedAudio) :
      filter === "video" ? files.every(isSupportedVideo) : false;
    if (!supported) {
      setImportError(filter === "audio" ? "只支持 WAV 音频。" : "只支持 MP4 视频。");
      return;
    }
    setImportError(null);
    onImportMedia(files);
    if (mediaInputRef.current !== null) mediaInputRef.current.value = "";
  }

  function openAudioEffect(assetId: string, track: "voice" | "background" | null = null) {
    const source = assets.find((asset) => asset.id === assetId);
    setEffectAssetId(assetId);
    setEffectTargetTrack(track);
    setEffectPreset("weak_signal");
    setEffectStrength(0.7);
    setEffectSeed("42");
    setEffectStartSeconds("0");
    setEffectEndSeconds(inputSeconds(source?.duration_seconds ?? 0));
  }

  function openAudioTrim(assetId: string) {
    const source = assets.find((asset) => asset.id === assetId);
    setTrimAssetId(assetId);
    setTrimStartSeconds("0");
    setTrimEndSeconds(inputSeconds(source?.duration_seconds ?? 0));
  }

  function openAudioCreator() {
    setAudioOperation(voiceDesignAvailable ? "voice_design" : "synthesize");
    setAudioText("");
    setVoiceDescription("");
    setRecipeParams({});
    setReferenceVoiceAssetId(wavAssets[0]?.id ?? "");
    setAudioSeed("42");
    setAudioCreatorBaselineGenerationIds(new Set(
      generations
        .filter((generation) => generation.kind === "generated_audio")
        .map((generation) => generation.id),
    ));
    setAudioCreatorOpen(true);
  }

  function closeAudioCreator() {
    setAudioCreatorOpen(false);
    setAudioOperation("voice_design");
    setAudioText("");
    setVoiceDescription("");
    setRecipeParams({});
    setReferenceVoiceAssetId("");
    setAudioSeed("42");
    setAudioCreatorBaselineGenerationIds(new Set());
  }

  return <div className="reference-image-dialog-backdrop" role="presentation">
    <DismissibleDialog onClose={onClose} ref={dialogRef} className="reference-image-dialog asset-center-dialog" role="dialog"
      aria-modal="true" aria-label="资产中心" tabIndex={-1}
      onPaste={pasteImage}>
      <header className="asset-center-header">
        <div>
          <p className="eyebrow">Project assets</p>
          <h2>资产中心</h2>
          <p>查看项目中的全部媒体。未被项目使用且没有未结束任务的 Asset 可以永久删除。</p>
        </div>
        <button className="dialog-close-button" type="button" aria-label="关闭资产中心"
          onClick={onClose}>×</button>
      </header>

      <div className="asset-center-toolbar">
        <div className="reference-dialog-tabs asset-center-tabs" role="tablist" aria-label="资产类型">
          {filterTabs.map((value) => (
            <button key={value} className={filter === value ? "is-active" : ""}
              type="button" role="tab" aria-selected={filter === value}
              onClick={() => { setFilter(value); setConfirmingBulkDelete(false); }}>
              {value === "all" ? "全部" :
                value === "image" ? "图片" :
                value === "audio" ? "音频" : value === "video" ? "视频" :
                value === "playground" ? "Playground" :
                  IMAGE_CATEGORIES.find((item) => item.value === value)?.label}
            </button>
          ))}
        </div>
        {filter === "playground" ? <>
          <label className="asset-import-category">
            <span>复制为</span>
            <select aria-label="Playground 图片分类" value={playgroundCategory}
              disabled={playgroundPending !== null}
              onChange={(event) => {
                setPlaygroundCategory(event.target.value as ImageAssetCategory | "");
                setPlaygroundError(null);
              }}>
              <option value="">请选择分类</option>
              {IMPORT_IMAGE_CATEGORIES.map((item) => <option key={item.value} value={item.value}>
                {item.label}
              </option>)}
            </select>
          </label>
          <span className="asset-import-paste-hint">图片需要先选分类；音频和视频直接复制</span>
        </> : filter === "audio" || filter === "video" ? <>
          <button className="secondary-button" type="button"
            disabled={busy || !canImportMedia}
            onClick={() => mediaInputRef.current?.click()}>
            {filter === "audio" ? "导入本地音频" : "导入本地视频"}
          </button>
          <span className="asset-import-paste-hint">
            {filter === "audio" ? "仅支持 WAV" : "仅支持 MP4"}
          </span>
          <input ref={mediaInputRef} type="file" hidden multiple
            aria-label={filter === "audio" ? "选择要导入的本地音频" : "选择要导入的本地视频"}
            accept={filter === "audio" ? ".wav,audio/wav" : ".mp4,video/mp4"}
            disabled={busy || !canImportMedia}
            onChange={(event) => importMedia(Array.from(event.target.files ?? []))} />
        </> : <>
          <label className="asset-import-category">
            <span>导入为</span>
            <select aria-label="本地图片分类" value={importCategory}
              disabled={busy || !canImportImage}
              onChange={(event) => {
                setImportCategory(event.target.value as ImageAssetCategory | "");
                setImportError(null);
              }}>
              <option value="">请选择分类</option>
              {IMPORT_IMAGE_CATEGORIES.map((item) => <option key={item.value} value={item.value}>
                {item.label}
              </option>)}
            </select>
          </label>
          <button className="secondary-button" type="button"
            disabled={busy || !canImportImage || importCategory === ""}
            onClick={() => inputRef.current?.click()}>
            加入本地图片
          </button>
          <span className="asset-import-paste-hint">或按 ⌘V / Ctrl+V 粘贴图片</span>
          <input ref={inputRef} type="file" hidden multiple
            aria-label="选择要加入资产中心的本地图片" accept="image/png,image/jpeg,image/webp"
            disabled={busy || !canImportImage}
            onChange={(event) => importImages(Array.from(event.target.files ?? []))} />
        </>}
        {filter === "audio" ? (
          <button className="primary-button" type="button"
            disabled={busy || !canGenerateAudio ||
              (!voiceDesignAvailable && !speechSynthesisAvailable)}
            onClick={openAudioCreator}>创建音频</button>
        ) : null}
        {filter === "playground" ? null : (
          <button className="danger-text-button" type="button"
            disabled={busy || !canDeleteAssets || deletableVisibleAssets.length === 0}
            onClick={() => setConfirmingBulkDelete(true)}>
            清理当前页废弃 Asset（{deletableVisibleAssets.length}）
          </button>
        )}
      </div>
      {confirmingBulkDelete ? (
        <div className="asset-center-selection-notice" role="alert">
          <span>将永久删除“{filterLabel}”页中 {deletableVisibleAssets.length} 个废弃 Asset，并清理仅与它们关联的隐藏生成血缘。确定继续？</span>
          <button className="danger-text-button" type="button" disabled={busy}
            onClick={() => {
              onDeleteMany(deletableVisibleAssets.map((asset) => asset.id));
              setConfirmingBulkDelete(false);
            }}>确认清理</button>
          <button type="button" disabled={busy}
            onClick={() => setConfirmingBulkDelete(false)}>取消</button>
        </div>
      ) : null}
      {voiceSelectionTarget !== null ? (
        <p className="asset-center-selection-notice">
          正在为 <strong>{voiceSelectionTarget.name}</strong> 选择参考音色；请选择一个 WAV Asset。
        </p>
      ) : null}
      {importError !== null ? <p className="reference-error" role="alert">{importError}</p> : null}

      {filter === "playground" ? (
        <>
          {playgroundNotice !== null ? (
            <p className="asset-center-selection-notice" role="status">{playgroundNotice}</p>
          ) : null}
          {playgroundError !== null ? (
            <p className="reference-error" role="alert">{playgroundError}</p>
          ) : null}
          {playgroundAssets === null ? (
            <div className="asset-center-empty">正在读取 Playground 资产…</div>
          ) : playgroundAssets.length === 0 ? (
            <div className="asset-center-empty">Playground 还没有资产。</div>
          ) : (
            <div className="asset-center-grid">
              {playgroundAssets.map((asset) => (
                <article className="asset-center-item" key={asset.id}>
                  <div className="asset-center-preview">
                    {asset.media_type.startsWith("image/") ? (
                      <ZoomableImage src={asset.content_url} alt={asset.display_name} />
                    ) : asset.media_type === "video/mp4" ? (
                      <video controls preload="metadata" src={asset.content_url} />
                    ) : (
                      <audio controls preload="none" src={asset.content_url} />
                    )}
                  </div>
                  <div className="asset-center-meta">
                    <strong>{asset.display_name}</strong>
                    <span>{asset.media_type} · {formatBytes(asset.byte_count)}</span>
                  </div>
                  <div className="asset-center-actions">
                    <button className="primary-button" type="button"
                      disabled={playgroundPending !== null ||
                        (asset.media_type.startsWith("image/") && playgroundCategory === "")}
                      onClick={() => void copyFromPlayground(asset)}>
                      {playgroundPending === asset.id ? "复制中…" : "复制到本项目"}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      ) : visibleAssets.length === 0 ? (
        <div className="asset-center-empty">当前分类还没有 Asset。</div>
      ) : (
        <div className="asset-center-grid">
          {visibleAssets.map((asset) => {
            const canDelete = asset.allowed_actions.includes("delete");
            const confirming = confirmingDelete === asset.id;
            // 使用原因与删除清理语义完全来自 Core；Web 不从 Generation 血缘反推。
            const retainsDerivedAssets = asset.retains_derived_assets_on_delete;
            const usageLabels = asset.usage_reasons.map((reason) => reason.label).join("、");
            const frameGeneration = asset.media_type === "video/mp4"
              ? [...generations].reverse().find((generation) =>
                generation.kind === "video_frame" && generation.target_id === asset.id &&
                !generation.dismissed
              ) ?? null
              : null;
            const frameInProgress = frameGeneration !== null &&
              (frameGeneration.phase === "submitting" ||
                frameGeneration.phase === "queued" ||
                frameGeneration.phase === "running");
            const frameFailed = frameGeneration !== null &&
              (frameGeneration.phase === "failed" ||
                frameGeneration.phase === "submission_uncertain");
            return <article className="asset-center-item" key={asset.id}>
              <div className="asset-center-preview">
                {asset.media_type.startsWith("image/") ? (
                  <ZoomableImage src={asset.content_url} alt={asset.display_name ?? "项目图片"} />
                ) : asset.media_type === "video/mp4" ? (
                  <video controls preload="metadata" src={asset.content_url} />
                ) : (
                  <audio controls preload="none" src={asset.content_url} />
                )}
              </div>
              <div className="asset-center-meta">
                <strong>{asset.display_name ?? "项目图片"}</strong>
                <span>{asset.media_type} · {formatBytes(asset.byte_count)}</span>
                {asset.image_category === null ? null : (
                  <span>{IMAGE_CATEGORIES.find(
                    (item) => item.value === asset.image_category,
                  )?.label}</span>
                )}
                {asset.duration_seconds === null ? null : (
                  <span>{asset.duration_seconds.toFixed(2)} 秒</span>
                )}
              </div>
              <div className="asset-center-actions">
                {voiceSelectionTarget !== null && asset.media_type === "audio/wav" ? (
                  <button
                    className="primary-button"
                    type="button"
                    disabled={
                      busy ||
                      onSelectReferenceVoice === undefined ||
                      voiceSelectionTarget.currentAssetId === asset.id
                    }
                    onClick={() => onSelectReferenceVoice?.(asset.id)}
                  >
                    {voiceSelectionTarget.currentAssetId === asset.id
                      ? "当前参考音色"
                      : `设为 ${voiceSelectionTarget.name} 的参考音色`}
                  </button>
                ) : null}
                {asset.media_type === "audio/wav" ? (
                  <>
                    <button className="secondary-button asset-audio-effect-button" type="button"
                      disabled={busy || !asset.allowed_actions.includes("audio_trim")}
                      title={asset.allowed_actions.includes("audio_trim")
                        ? "选择时间范围并创建一份新的 WAV 副本"
                        : "当前音频没有可靠时长，无法截取"}
                      onClick={() => openAudioTrim(asset.id)}>
                      截取
                    </button>
                    <button className="secondary-button asset-audio-effect-button" type="button"
                      disabled={busy || !asset.allowed_actions.includes("audio_effect")}
                      title={asset.allowed_actions.includes("audio_effect")
                        ? "创建一个保留原音频的处理后副本"
                        : "当前项目状态暂不允许新增后处理副本"}
                      onClick={() => openAudioEffect(asset.id)}>
                      音频后处理
                    </button>
                  </>
                ) : null}
                {asset.media_type === "video/mp4" ? (
                  <>
                    <button className="secondary-button asset-audio-effect-button" type="button"
                      disabled={busy || frameInProgress || onLoadVideoFrameInfo === undefined ||
                        !asset.allowed_actions.includes("video_frame")}
                      title={asset.allowed_actions.includes("video_frame")
                        ? "按帧号提取视频中的一帧，默认最后一帧，生成独立 PNG Asset"
                        : "当前项目状态或抽帧服务暂不允许抽帧"}
                      onClick={() => setFrameAsset(asset)}>
                      {frameInProgress
                        ? "正在抽帧…"
                        : frameFailed ? "重新抽帧" : "抽帧"}
                    </button>
                    {frameFailed ? (
                      <small className="asset-center-action-hint" role="status">
                        {frameGeneration.phase === "submission_uncertain"
                          ? "上次提交没有建立可恢复任务："
                          : "抽帧失败："}
                        {frameGeneration.message || frameGeneration.error_code || "请重试"}
                      </small>
                    ) : frameInProgress ? (
                      <small className="asset-center-action-hint" role="status">
                        {frameGeneration.message || "任务已提交，完成后会出现在“图片”页。"}
                      </small>
                    ) : null}
                  </>
                ) : null}
                {asset.media_type === "video/mp4" ? (
                  <button className="secondary-button asset-audio-effect-button" type="button"
                    disabled={busy || !asset.allowed_actions.includes("audio_editor")}
                    onClick={() => {
                      const duration = inputSeconds(asset.duration_seconds ?? 0);
                      setVideoEditorAssetId(asset.id);
                      setVoiceGainDb(0);
                      setBackgroundGainDb(0);
                      setVoiceGainStartSeconds("0");
                      setVoiceGainEndSeconds(duration);
                      setBackgroundGainStartSeconds("0");
                      setBackgroundGainEndSeconds(duration);
                      setVoiceUseProcessed(false);
                      setBackgroundUseProcessed(false);
                    }}>
                    处理音轨
                  </button>
                ) : null}
                {canDelete ? (
                  confirming ? <>
                    <span>{retainsDerivedAssets
                      ? "派生 Asset 将保留并可继续使用，但无法再从这个源素材重新处理；相关 Generation 记录将一并清理。确定永久删除？"
                      : "将同时清理只与它关联的隐藏生成血缘，确定永久删除？"}</span>
                    <button className="danger-text-button" type="button"
                      disabled={busy || !canDeleteAssets}
                      onClick={() => { onDelete(asset.id); setConfirmingDelete(null); }}>
                      确认删除
                    </button>
                    <button className="asset-center-cancel" type="button"
                      onClick={() => setConfirmingDelete(null)}>取消</button>
                  </> : (
                    <button className="danger-text-button" type="button"
                      disabled={busy || !canDeleteAssets}
                      onClick={() => setConfirmingDelete(asset.id)}>永久删除废弃 Asset</button>
                  )
                ) : asset.is_in_use ? (
                  <small>正在使用：{usageLabels}</small>
                ) : (
                  <small>当前项目状态不允许删除 Asset</small>
                )}
              </div>
            </article>;
          })}
        </div>
      )}
      {audioCreatorOpen ? (
        <div className="audio-effect-dialog-backdrop" role="presentation">
          <DismissibleDialog onClose={closeAudioCreator} className="audio-effect-dialog audio-generation-dialog" role="dialog" aria-modal="true"
            aria-label="创建音频">
            <header>
              <div>
                <p className="eyebrow">Audio generation</p>
                <h3>创建音频</h3>
                <p>生成完成后会作为新的 WAV Asset 出现在音频栏目。</p>
              </div>
              <button className="dialog-close-button" type="button" aria-label="关闭创建音频"
                onClick={closeAudioCreator}>×</button>
            </header>
            <form onSubmit={async (event) => {
              event.preventDefault();
              if (!validAudioGeneration) return;
              const common = {text: audioText.trim(), seed: Number(audioSeed)};
              const settings: AudioGenerationSettings = audioOperation === "voice_design"
                ? {
                    operation: "voice_design",
                    ...common,
                    voice_description: voiceDescription.trim(),
                  }
                : {
                    operation: "synthesize",
                    ...common,
                    voice_asset_id: referenceVoiceAssetId,
                    reference_transcript: referenceTranscript.trim(),
                    recipe_params: speechRecipe ? { [speechRecipe.recipe.id]: { ...Object.fromEntries(speechRecipe.editable_params.map((field) => [field.key, field.default])), ...recipeParams[speechRecipe.recipe.id] } } : {},
                  };
              await onGenerateAudio(settings);
            }}>
              {!selectedAudioModelAvailable ? <small className="reference-error">
                Breeze TTS 2 服务尚未配置。
              </small> : null}
              <label>
                <span>用途</span>
                <select aria-label="音频生成用途" value={audioOperation} disabled={busy}
                  onChange={(event) => setAudioOperation(event.target.value as "voice_design" | "synthesize")}>
                  <option value="voice_design" disabled={!voiceDesignAvailable}>Voice Design（描述基础音色）</option>
                  <option value="synthesize" disabled={!speechSynthesisAvailable}>Voice Clone / Direction（参考音频 + 当前表现）</option>
                </select>
              </label>
              <label>
                <span>要朗读的文本</span>
                <textarea aria-label="音频生成文本" value={audioText} disabled={busy}
                  maxLength={audioOperation === "voice_design" ? 2000 : 20000}
                  onChange={(event) => setAudioText(event.target.value)} />
              </label>
              {audioOperation === "voice_design" ? (
                <label>
                  <span>音色描述</span>
                  <textarea aria-label="音色描述" value={voiceDescription}
                    disabled={busy} maxLength={500}
                    onChange={(event) => setVoiceDescription(event.target.value)} />
                  <small>例如：低沉、克制的中年男声，语速稍慢，近距离录音。</small>
                </label>
              ) : <>
                <label>
                  <span>参考音频</span>
                  <select aria-label="参考音频" value={referenceVoiceAssetId}
                    disabled={busy || wavAssets.length === 0}
                    onChange={(event) => {
                      setReferenceVoiceAssetId(event.target.value);
                    }}>
                    {wavAssets.length === 0 ? <option value="">资产中心没有 WAV 音频</option> : null}
                    {wavAssets.map((asset) => <option key={asset.id} value={asset.id}>
                      {asset.display_name ?? asset.id}
                    </option>)}
                  </select>
                </label>
                {referenceVoiceAsset !== null ? (
                  <section className="audio-generation-reference-preview"
                    aria-label="当前参考音频试听">
                    <div>
                      <strong>试听参考音频</strong>
                      <span>{referenceVoiceAsset.display_name ?? referenceVoiceAsset.id}</span>
                    </div>
                    <audio aria-label="播放当前参考音频" controls preload="metadata"
                      src={referenceVoiceAsset.content_url} />
                  </section>
                ) : null}
                <small className={referenceTranscript.trim() ? "" : "reference-error"}>
                  {referenceTranscript.trim() ? "已使用引用库中的完整参考文字稿。" : "请先在角色或旁白引用库填写完整参考文字稿。"}
                </small>
                {speechRecipe?.editable_params.map((field) => <SettingField key={field.key} field={field} disabled={busy}
                  value={(recipeParams[speechRecipe.recipe.id]?.[field.key] ?? field.default) as SettingValue}
                  onChange={(value) => setRecipeParams({ ...recipeParams, [speechRecipe.recipe.id]: { ...recipeParams[speechRecipe.recipe.id], [field.key]: value } })} />)}
              </>}
              <label>
                <span>Seed</span>
                <input aria-label="音频生成 Seed" type="text" inputMode="numeric"
                  value={audioSeed} disabled={busy}
                  onChange={(event) => setAudioSeed(event.target.value.trim())} />
                {!validAudioSeed ? <small className="reference-error" role="alert">
                  Seed 必须是 0 到 2^53-1 之间的整数。
                </small> : null}
              </label>
              {audioCreatorGenerations.length > 0 ? (
                <section className="audio-generation-session" aria-label="本次生成进度">
                  <header>
                    <div>
                      <strong>本次生成</strong>
                      <span>可继续提交下一条；关闭窗口后清空此处记录。</span>
                    </div>
                    <b>{audioCreatorGenerations.length} 条</b>
                  </header>
                  <div>{audioCreatorGenerations.map((generation) => {
                    const output = generation.output_asset_id === null
                      ? null
                      : assets.find((asset) => asset.id === generation.output_asset_id) ?? null;
                    const spokenText = generation.operation === "voice_design"
                      ? generation.sample_text
                      : generation.prompt_text;
                    return <article key={generation.id} className="audio-generation-session-item">
                      <div className="audio-generation-session-heading">
                        <strong>Breeze TTS 2</strong>
                        <span>{audioGenerationPhaseLabel(generation.phase)} · {Math.round(
                          generation.progress * 100,
                        )}%</span>
                      </div>
                      <p>{spokenText}</p>
                      <progress aria-label="音频生成进度" max="1" value={generation.progress} />
                      {generation.message ? <small>{generation.message}</small> : null}
                      {output !== null ? (
                        <audio aria-label="试听生成音频" controls preload="metadata"
                          src={output.content_url} />
                      ) : null}
                      {generation.error_code !== null ? (
                        <small className="reference-error" role="alert">
                          {generation.error_code}
                        </small>
                      ) : null}
                    </article>;
                  })}</div>
                </section>
              ) : null}
              <footer>
                <button className="secondary-button" type="button" disabled={busy}
                  onClick={closeAudioCreator}>关闭</button>
                <button className="primary-button" type="submit"
                  disabled={busy || !validAudioGeneration}>提交生成</button>
              </footer>
            </form>
          </DismissibleDialog>
        </div>
      ) : null}
      {trimAsset !== null ? (
        <div className="audio-effect-dialog-backdrop" role="presentation">
          <DismissibleDialog onClose={() => setTrimAssetId(null)} className="audio-effect-dialog" role="dialog" aria-modal="true"
            aria-label="截取音频">
            <header>
              <div>
                <p className="eyebrow">Audio trim</p>
                <h3>截取音频</h3>
                <p>源文件：{trimAsset.display_name ?? trimAsset.id}</p>
              </div>
              <button className="dialog-close-button" type="button" aria-label="关闭音频截取"
                disabled={busy} onClick={() => setTrimAssetId(null)}>×</button>
            </header>
            <form onSubmit={async (event) => {
              event.preventDefault();
              if (!validTrimRange) return;
              const succeeded = await onTrimAudio(trimAsset.id, {
                start_seconds: trimStart,
                end_seconds: trimEnd,
              });
              if (succeeded) setTrimAssetId(null);
            }}>
              <audio controls preload="metadata" src={trimAsset.content_url} />
              <fieldset className="audio-effect-time-range">
                <legend>保留时间范围</legend>
                <div>
                  <label>
                    <span>开始（秒）</span>
                    <input aria-label="截取开始时间" type="number" min="0"
                      max={trimDuration ?? undefined} step="0.01" value={trimStartSeconds}
                      disabled={busy}
                      onChange={(event) => setTrimStartSeconds(event.target.value)} />
                  </label>
                  <label>
                    <span>结束（秒）</span>
                    <input aria-label="截取结束时间" type="number" min="0"
                      max={trimDuration ?? undefined} step="0.01" value={trimEndSeconds}
                      disabled={busy}
                      onChange={(event) => setTrimEndSeconds(event.target.value)} />
                  </label>
                </div>
                {!validTrimRange ? <small className="reference-error" role="alert">
                  请选择完整音频以内的一段有效范围；至少需要裁掉开头或结尾的一部分。
                </small> : <small>
                  将保留 {formatSeconds(trimStart)}–{formatSeconds(trimEnd)} 秒，原音频不会改变。
                </small>}
              </fieldset>
              <footer>
                <button className="secondary-button" type="button" disabled={busy}
                  onClick={() => setTrimAssetId(null)}>取消</button>
                <button className="primary-button" type="submit"
                  disabled={busy || !validTrimRange}>创建截取副本</button>
              </footer>
            </form>
          </DismissibleDialog>
        </div>
      ) : null}
      {effectAsset !== null ? (
        <div className={`audio-effect-dialog-backdrop${effectTargetTrack === null
          ? "" : " is-nested"}`} role="presentation">
          <DismissibleDialog onClose={() => { setEffectAssetId(null); setEffectTargetTrack(null); }} className="audio-effect-dialog" role="dialog" aria-modal="true"
            aria-label="音频后处理">
            <header>
              <div>
                <p className="eyebrow">Audio post-processing</p>
                <h3>音频后处理</h3>
                <p>源文件：{effectAsset.display_name ?? effectAsset.id}</p>
              </div>
              <button className="dialog-close-button" type="button" aria-label="关闭音频后处理"
                disabled={busy} onClick={() => {
                  setEffectAssetId(null);
                  setEffectTargetTrack(null);
                }}>×</button>
            </header>
            <form onSubmit={(event) => {
              event.preventDefault();
              if (!validSeed || !validRange) return;
              onApplyAudioEffect(effectAsset.id, {
                effect: "radio",
                preset: effectPreset,
                strength: effectStrength,
                seed: Number(effectSeed),
                ...(effectDuration === null ? {} : {
                  start_seconds: effectStart,
                  end_seconds: effectEnd,
                }),
              });
              if (effectTargetTrack === "voice") setVoiceUseProcessed(true);
              if (effectTargetTrack === "background") setBackgroundUseProcessed(true);
              setEffectAssetId(null);
              setEffectTargetTrack(null);
            }}>
              <label>
                <span>效果</span>
                <strong>无线电 / 弱信号</strong>
              </label>
              <label>
                <span>预设</span>
                <select aria-label="音频后处理预设" value={effectPreset} disabled={busy}
                  onChange={(event) => setEffectPreset(event.target.value as AudioEffectPreset)}>
                  {AUDIO_EFFECT_PRESETS.map((preset) => (
                    <option key={preset.value} value={preset.value}>{preset.label}</option>
                  ))}
                </select>
                <small>{AUDIO_EFFECT_PRESETS.find(
                  (preset) => preset.value === effectPreset,
                )?.description}</small>
              </label>
              <label>
                <span>强度：{effectStrength.toFixed(2)}</span>
                <input aria-label="音频后处理强度" type="range" min="0" max="1" step="0.05"
                  value={effectStrength} disabled={busy}
                  onChange={(event) => setEffectStrength(Number(event.target.value))} />
              </label>
              <fieldset className="audio-effect-time-range">
                <legend>处理时间范围</legend>
                {effectDuration === null ? (
                  <small>当前 Asset 没有可靠时长，将处理完整音频。</small>
                ) : <>
                  <div>
                    <label>
                      <span>开始（秒）</span>
                      <input aria-label="后处理开始时间" type="number" min="0"
                        max={effectDuration} step="0.01" value={effectStartSeconds}
                        disabled={busy}
                        onChange={(event) => setEffectStartSeconds(event.target.value)} />
                    </label>
                    <label>
                      <span>结束（秒）</span>
                      <input aria-label="后处理结束时间" type="number" min="0"
                        max={effectDuration} step="0.01" value={effectEndSeconds}
                        disabled={busy}
                        onChange={(event) => setEffectEndSeconds(event.target.value)} />
                    </label>
                  </div>
                  <button className="secondary-button" type="button" disabled={busy}
                    onClick={() => {
                      setEffectStartSeconds("0");
                      setEffectEndSeconds(inputSeconds(effectDuration));
                    }}>选择完整音频</button>
                  {!validRange ? <small className="reference-error" role="alert">
                    时间范围必须位于 0–{formatSeconds(effectDuration)} 秒内，且结束晚于开始。
                  </small> : <small>
                    仅 {formatSeconds(effectStart)}–{formatSeconds(effectEnd)} 秒应用效果，区间外保持原声。
                  </small>}
                </>}
              </fieldset>
              <label>
                <span>Seed</span>
                <input aria-label="音频后处理 Seed" type="text" inputMode="numeric"
                  value={effectSeed} disabled={busy}
                  onChange={(event) => setEffectSeed(event.target.value.trim())} />
                {!validSeed ? <small className="reference-error" role="alert">
                  Seed 必须是 0 到 2^53-1 之间的整数。
                </small> : <small>相同输入、参数和 Seed 会得到相同结果。</small>}
              </label>
              <footer>
                <button className="secondary-button" type="button" disabled={busy}
                  onClick={() => {
                    setEffectAssetId(null);
                    setEffectTargetTrack(null);
                  }}>取消</button>
                <button className="primary-button" type="submit"
                  disabled={busy || !validSeed || !validRange}>
                  创建处理后副本
                </button>
              </footer>
            </form>
          </DismissibleDialog>
        </div>
      ) : null}
      {videoEditorAsset !== null ? (
        <div className="audio-effect-dialog-backdrop" role="presentation">
          <DismissibleDialog onClose={() => setVideoEditorAssetId(null)} className="audio-effect-dialog audio-track-editor" role="dialog"
            aria-modal="true" aria-label="视频音轨编辑器">
            <header>
              <div>
                <p className="eyebrow">Video audio editor</p>
                <h3>视频音轨编辑器</h3>
                <p>源视频：{videoEditorAsset.display_name ?? videoEditorAsset.id}</p>
              </div>
              <button className="dialog-close-button" type="button" aria-label="关闭视频音轨编辑器"
                disabled={busy} onClick={() => setVideoEditorAssetId(null)}>×</button>
            </header>
            <div className="audio-track-editor-tabs" role="tablist" aria-label="视频编辑选项">
              <button className="is-active" role="tab" aria-selected="true" type="button">音轨</button>
            </div>
            <video controls preload="metadata" src={videoEditorAsset.content_url} />
            {stemPair === null ? (
              <div className="audio-track-empty">
                <p>分离后将得到可独立试听和处理的人声、背景声副本。</p>
                <button className="primary-button" type="button"
                  disabled={busy || !audioSeparationAvailable}
                  onClick={() => onSeparateVideoAudio(videoEditorAsset.id)}>
                  分离人声和背景声
                </button>
                {!audioSeparationAvailable ? <small>当前未配置 Demucs 分离服务。</small> : null}
              </div>
            ) : (
              <div className="audio-track-list">
                <AudioTrackRow label="人声 / 对白" generation={stemPair.voice} asset={voiceAsset}
                  effectAsset={voiceEffectAsset} gain={voiceGainDb} setGain={setVoiceGainDb}
                  gainStart={voiceGainStartSeconds} setGainStart={setVoiceGainStartSeconds}
                  gainEnd={voiceGainEndSeconds} setGainEnd={setVoiceGainEndSeconds}
                  duration={voiceGainDuration} validGainRange={validVoiceGainRange}
                  useProcessed={voiceUseProcessed} setUseProcessed={setVoiceUseProcessed}
                  busy={busy} onOpenEffect={(assetId) => openAudioEffect(assetId, "voice")} />
                <AudioTrackRow label="背景声（音乐、环境与音效）" generation={stemPair.background}
                  asset={backgroundAsset} effectAsset={backgroundEffectAsset}
                  gain={backgroundGainDb} setGain={setBackgroundGainDb}
                  gainStart={backgroundGainStartSeconds}
                  setGainStart={setBackgroundGainStartSeconds}
                  gainEnd={backgroundGainEndSeconds} setGainEnd={setBackgroundGainEndSeconds}
                  duration={backgroundGainDuration} validGainRange={validBackgroundGainRange}
                  useProcessed={backgroundUseProcessed}
                  setUseProcessed={setBackgroundUseProcessed}
                  busy={busy} onOpenEffect={(assetId) => openAudioEffect(assetId, "background")} />
                <footer>
                  <button className="primary-button" type="button"
                    disabled={busy || !audioRemixAvailable || voiceAsset === null ||
                      backgroundAsset === null || (voiceUseProcessed && voiceEffectAsset === null) ||
                      (backgroundUseProcessed && backgroundEffectAsset === null) ||
                      !validVoiceGainRange || !validBackgroundGainRange}
                    onClick={() => void onRemixVideoAudio(
                      videoEditorAsset.id,
                      (voiceUseProcessed ? voiceEffectAsset : voiceAsset)?.id ?? "",
                      (backgroundUseProcessed ? backgroundEffectAsset : backgroundAsset)?.id ?? "",
                      gainSettings(voiceGainDb, voiceGainDuration, voiceGainStartSeconds,
                        voiceGainEndSeconds),
                      gainSettings(backgroundGainDb, backgroundGainDuration,
                        backgroundGainStartSeconds, backgroundGainEndSeconds),
                    ).then((succeeded) => {
                      if (succeeded) setVideoEditorAssetId(null);
                    })}>
                    重新应用到视频并创建副本
                  </button>
                </footer>
              </div>
            )}
          </DismissibleDialog>
        </div>
      ) : null}
      {frameAsset !== null && onLoadVideoFrameInfo !== undefined ? (
        <VideoFrameExtractDialog
          videoUrl={frameAsset.content_url}
          title={`从 ${frameAsset.display_name ?? "视频"} 抽帧`}
          description="抽出的 PNG 进入“抽帧图”分类，不会自动绑定到任何关键帧。"
          busy={busy}
          loadInfo={() => onLoadVideoFrameInfo(frameAsset.id)}
          onClose={() => setFrameAsset(null)}
          onConfirm={(frameIndex) => {
            const assetId = frameAsset.id;
            setFrameAsset(null);
            onExtractVideoFrame(assetId, frameIndex);
          }}
        />
      ) : null}
    </DismissibleDialog>
  </div>;
}

function AudioTrackRow({label, generation, asset, effectAsset, gain, setGain, gainStart,
  setGainStart, gainEnd, setGainEnd, duration, validGainRange, useProcessed,
  setUseProcessed, busy, onOpenEffect}: {
  label: string;
  generation: ReferenceGeneration;
  asset: ProjectAsset | null;
  effectAsset: ProjectAsset | null;
  gain: number;
  setGain: (value: number) => void;
  gainStart: string;
  setGainStart: (value: string) => void;
  gainEnd: string;
  setGainEnd: (value: string) => void;
  duration: number | null;
  validGainRange: boolean;
  useProcessed: boolean;
  setUseProcessed: (value: boolean) => void;
  busy: boolean;
  onOpenEffect: (assetId: string) => void;
}) {
  return <article className="audio-track-row">
    <header><strong>{label}</strong><span>{generation.message}</span></header>
    {asset === null ? <progress max="1" value={generation.progress} /> : <>
      <AudioTrackPreview
        src={(useProcessed && effectAsset !== null ? effectAsset : asset).content_url}
        gainDb={gain}
        startSeconds={validGainRange && duration !== null ? Number(gainStart) : null}
        endSeconds={validGainRange && duration !== null ? Number(gainEnd) : null}
      />
      <label><span>音量：{gain.toFixed(1)} dB</span>
        <input aria-label={`${label}音量`} type="range" min="-60" max="12" step="0.5"
          value={gain} disabled={busy} onChange={(event) => setGain(Number(event.target.value))} />
      </label>
      <small>播放时会即时试听当前音量；最终导出还会对混合结果进行限峰。</small>
      <fieldset className="audio-track-gain-range">
        <legend>音量应用范围</legend>
        {duration === null ? <small>当前音轨没有可靠时长，将对完整音轨应用音量。</small> : <>
          <div>
            <label><span>开始（秒）</span>
              <input aria-label={`${label}音量开始时间`} type="number" min="0" max={duration}
                step="0.01" value={gainStart} disabled={busy}
                onChange={(event) => setGainStart(event.target.value)} />
            </label>
            <label><span>结束（秒）</span>
              <input aria-label={`${label}音量结束时间`} type="number" min="0" max={duration}
                step="0.01" value={gainEnd} disabled={busy}
                onChange={(event) => setGainEnd(event.target.value)} />
            </label>
          </div>
          <button className="secondary-button" type="button" disabled={busy}
            onClick={() => {
              setGainStart("0");
              setGainEnd(inputSeconds(duration));
            }}>选择完整音轨</button>
          {!validGainRange ? <small className="reference-error" role="alert">
            时间范围必须位于 0–{formatSeconds(duration)} 秒内，且结束晚于开始。
          </small> : <small>
            仅 {formatSeconds(Number(gainStart))}–{formatSeconds(Number(gainEnd))} 秒应用音量。
          </small>}
        </>}
      </fieldset>
      <div className="audio-track-processing">
        <button className="secondary-button" type="button" disabled={busy}
          onClick={() => onOpenEffect(asset.id)}>完整后处理…</button>
        <label><span>试听和导出使用的版本</span>
          <select aria-label={`${label}使用音轨`} value={useProcessed ? "processed" : "original"}
            disabled={busy || effectAsset === null}
            onChange={(event) => setUseProcessed(event.target.value === "processed")}>
            <option value="original">原始音轨（未后处理）</option>
            <option value="processed" disabled={effectAsset === null}>后处理副本（最近一次）</option>
          </select>
        </label>
      </div>
      {useProcessed && effectAsset !== null ? <small>
        上方播放器和“重新应用到视频”将使用：{effectAsset.display_name ?? effectAsset.id}
      </small> : effectAsset === null ? <small>
        当前使用未经后处理的原始音轨；创建副本后可在这里切换。
      </small> : <small>上方播放器和“重新应用到视频”将使用未经后处理的原始音轨。</small>}
    </>}
  </article>;
}

function AudioTrackPreview({src, gainDb, startSeconds, endSeconds}: {
  src: string;
  gainDb: number;
  startSeconds: number | null;
  endSeconds: number | null;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const gainRef = useRef<GainNode | null>(null);

  function ensureAudioGraph(): AudioContext | null {
    const audio = audioRef.current;
    if (audio === null || typeof AudioContext === "undefined") return null;
    if (contextRef.current !== null) return contextRef.current;
    const context = new AudioContext();
    const source = context.createMediaElementSource(audio);
    const gain = context.createGain();
    source.connect(gain);
    gain.connect(context.destination);
    contextRef.current = context;
    sourceRef.current = source;
    gainRef.current = gain;
    return context;
  }

  function updatePreviewGain() {
    const audio = audioRef.current;
    const context = contextRef.current;
    const gain = gainRef.current;
    if (audio === null || context === null || gain === null) return;
    schedulePreviewGain(
      gain.gain,
      context.currentTime,
      audio.currentTime,
      audio.playbackRate,
      gainDb,
      startSeconds,
      endSeconds,
    );
  }

  useEffect(() => {
    updatePreviewGain();
  }, [gainDb, startSeconds, endSeconds, src]);

  useEffect(() => () => {
    sourceRef.current?.disconnect();
    gainRef.current?.disconnect();
    if (contextRef.current !== null) void contextRef.current.close();
  }, []);

  return <audio ref={audioRef} controls preload="none" src={src}
    onPlay={() => {
      const context = ensureAudioGraph();
      if (context !== null) void context.resume().then(updatePreviewGain);
    }}
    onSeeking={updatePreviewGain}
    onRateChange={updatePreviewGain}
    onTimeUpdate={updatePreviewGain} />;
}

function schedulePreviewGain(
  parameter: AudioParam,
  contextTime: number,
  mediaTime: number,
  playbackRate: number,
  gainDb: number,
  startSeconds: number | null,
  endSeconds: number | null,
) {
  const selectedGain = 10 ** (gainDb / 20);
  const fullTrack = startSeconds === null || endSeconds === null;
  const selectedNow = fullTrack || (mediaTime >= startSeconds && mediaTime < endSeconds);
  const rate = playbackRate > 0 ? playbackRate : 1;
  parameter.cancelScheduledValues(contextTime);
  parameter.setValueAtTime(selectedNow ? selectedGain : 1, contextTime);
  if (fullTrack) return;
  const fadeSeconds = Math.min(0.005, (endSeconds - startSeconds) / (2 * rate));
  if (mediaTime < startSeconds) {
    const boundary = contextTime + (startSeconds - mediaTime) / rate;
    parameter.setValueAtTime(1, Math.max(contextTime, boundary - fadeSeconds));
    parameter.linearRampToValueAtTime(selectedGain, boundary);
  }
  if (mediaTime < endSeconds) {
    const boundary = contextTime + (endSeconds - mediaTime) / rate;
    parameter.setValueAtTime(selectedGain, Math.max(contextTime, boundary - fadeSeconds));
    parameter.linearRampToValueAtTime(1, boundary);
  }
}

function latestStemPair(generations: ReferenceGeneration[], videoAssetId: string): {
  voice: ReferenceGeneration;
  background: ReferenceGeneration;
} | null {
  const voices = generations.filter((item) =>
    item.target_id === videoAssetId && item.kind === "video_audio_voice" && !item.dismissed
  ).reverse();
  for (const voice of voices) {
    const batch = generationBatch(voice);
    const background = [...generations].reverse().find((item) =>
      item.target_id === videoAssetId && item.kind === "video_audio_background" &&
      !item.dismissed && generationBatch(item) === batch
    );
    if (background !== undefined) return {voice, background};
  }
  return null;
}

function generationBatch(generation: ReferenceGeneration): string | null {
  try {
    const value = JSON.parse(generation.prompt_text) as unknown;
    if (typeof value === "object" && value !== null && "batch_id" in value &&
      typeof value.batch_id === "string") return value.batch_id;
  } catch { /* malformed historical metadata is ignored */ }
  return null;
}

function assetForGeneration(assets: ProjectAsset[], generation: ReferenceGeneration | null) {
  if (generation?.phase !== "succeeded" || generation.output_asset_id === null) return null;
  return assets.find((item) => item.id === generation.output_asset_id) ?? null;
}

function latestEffectAsset(assets: ProjectAsset[], generations: ReferenceGeneration[],
  sourceId: string | null) {
  if (sourceId === null) return null;
  const generation = [...generations].reverse().find((item) =>
    item.kind === "audio_effect" && item.input_asset_ids[0] === sourceId &&
    item.phase === "succeeded" && item.output_asset_id !== null
  );
  return assetForGeneration(assets, generation ?? null);
}

function isSupportedImage(file: File): boolean {
  return file.type === "image/png" || file.type === "image/jpeg" ||
    file.type === "image/webp";
}

function isSupportedAudio(file: File): boolean {
  return file.type === "audio/wav" || file.type === "audio/x-wav" ||
    file.name.toLowerCase().endsWith(".wav");
}

function isSupportedVideo(file: File): boolean {
  return file.type === "video/mp4" || file.name.toLowerCase().endsWith(".mp4");
}

function audioGenerationPhaseLabel(phase: ReferenceGeneration["phase"]): string {
  return {
    submitting: "正在提交",
    submission_uncertain: "提交结果未知",
    queued: "排队中",
    running: "生成中",
    succeeded: "生成完成",
    failed: "生成失败",
    cancelled: "已取消",
  }[phase];
}

function clipboardImage(data: DataTransfer): File | null {
  const item = Array.from(data.items).find(
    (candidate) => candidate.kind === "file" && candidate.type.startsWith("image/"),
  );
  const file = item?.getAsFile() ?? Array.from(data.files).find(
    (candidate) => candidate.type.startsWith("image/"),
  ) ?? null;
  if (file === null || file.name.trim()) return file;
  const extension = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
  }[file.type] ?? "image";
  return new File([file], `剪贴板图片.${extension}`, {
    type: file.type,
    lastModified: file.lastModified,
  });
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatSeconds(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2).replace(/\.00$/, "") : "0";
}

function inputSeconds(value: number): string {
  return Number.isFinite(value) ? String(Number(value.toFixed(6))) : "0";
}

function validTimeRange(duration: number | null, startText: string, endText: string): boolean {
  if (duration === null) return true;
  const start = Number(startText);
  const end = Number(endText);
  return Number.isFinite(start) && Number.isFinite(end) && start >= 0 &&
    end > start && end <= duration;
}

function gainSettings(
  gainDb: number,
  duration: number | null,
  startText: string,
  endText: string,
): AudioGainSettings {
  return duration === null ? { gain_db: gainDb } : {
    gain_db: gainDb,
    start_seconds: Number(startText),
    end_seconds: Number(endText),
  };
}
