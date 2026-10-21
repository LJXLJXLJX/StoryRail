import { stableStringify } from "./draft_protection";
import { ImageZoomButton, ZoomableImage } from "../ImagePreview";
import {
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  CharacterCard,
  CharacterCardDraft,
  CharacterLook,
  CharacterLookDraft,
  NarrationLanguage,
  NarratorProfile,
  NarratorVoice,
  ProjectAsset,
  ReferenceGeneration,
  StructuredDirectorSnapshot,
} from "../api";

import {
  ImportImageHandler,
} from "./contracts";
import {
  GenerationCandidates,
} from "./generation";
import {
  NARRATION_LANGUAGE_LABELS,
} from "./narration";
import {
  AssetAudio,
  CardActions,
  CardHeading,
  NewCardActions,
  TextArea,
  TextField,
  assetById,
  cardGenerations,
  imageAssets,
  isSupportedImageType,
  toggleId,
} from "./shared";

export function NarratorCardEditor({
  profile, snapshot, busy, onSave, onDesign, onAttach, onCancelGeneration,
  onDismissGeneration, onTranscribeAudio,
}: {
  profile: NarratorProfile;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  onSave: (profile: NarratorProfile) => void;
  onDesign: (
    narratorId: string, language: NarrationLanguage, description: string, sampleText: string,
    seed: number,
  ) => void;
  onAttach: (narratorId: string, generationId: string) => void;
  onCancelGeneration: (generationId: string) => void;
  onDismissGeneration: (generationId: string) => void;
  onTranscribeAudio: (assetId: string) => Promise<string>;
}) {
  const [draft, setDraft] = useState(profile);
  const generations = cardGenerations(snapshot, profile.id, "narrator_voice");
  return <form className="reference-card narrator-card" onSubmit={(event) => {
    event.preventDefault(); onSave(draft);
  }}>
    <CardHeading kind="独立旁白" name={draft.name} />
    <p className="muted-copy">旁白不出镜，也不属于角色对白；所选语言各用一套参考音色，分别克隆。</p>
    <TextField label="名称" value={draft.name} required
      onChange={(name) => setDraft({ ...draft, name })} />
    {snapshot.narration_languages.map((language) => <NarratorVoiceSection key={language}
      narratorId={profile.id} language={language} voice={draft[language]!} snapshot={snapshot}
      generations={generations.filter((generation) => generation.language === language)}
      busy={busy} onChange={(voice) => setDraft({ ...draft, [language]: voice })}
      onSelectAsset={(assetId) => onSave({
        ...draft,
        [language]: { ...draft[language]!, voice_reference_asset_id: assetId, voice_reference_transcript: null },
      })}
      onDesign={(description, text, seed) => onDesign(profile.id, language, description, text, seed)}
      onAttach={(generationId) => onAttach(profile.id, generationId)}
      onCancelGeneration={onCancelGeneration} onDismissGeneration={onDismissGeneration}
      onTranscribeAudio={onTranscribeAudio} />)}
    <div className="reference-card-actions"><button type="submit" className="secondary-button"
      disabled={busy || stableStringify(draft) === stableStringify(profile)}>保存旁白音色信息</button></div>
  </form>;
}


const NARRATOR_SAMPLE_TEXT: Record<NarrationLanguage, string> = {
  zh: "你好，很高兴认识你。我们从这里开始讲这个故事。",
  en: "Hello, it's good to meet you. Let us begin the story here.",
};


function NarratorVoiceSection({
  narratorId, language, voice, snapshot, generations, busy, onChange, onSelectAsset, onDesign,
  onAttach, onCancelGeneration, onDismissGeneration, onTranscribeAudio,
}: {
  narratorId: string;
  language: NarrationLanguage;
  voice: NarratorVoice;
  snapshot: StructuredDirectorSnapshot;
  generations: ReferenceGeneration[];
  busy: boolean;
  onChange: (voice: NarratorVoice) => void;
  onSelectAsset: (assetId: string) => void;
  onDesign: (description: string, sampleText: string, seed: number) => void;
  onAttach: (generationId: string) => void;
  onCancelGeneration: (generationId: string) => void;
  onDismissGeneration: (generationId: string) => void;
  onTranscribeAudio: (assetId: string) => Promise<string>;
}) {
  const [creating, setCreating] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcriptionError, setTranscriptionError] = useState<string | null>(null);
  const label = NARRATION_LANGUAGE_LABELS[language];
  const dialogTitle = voice.voice_reference_asset_id === null
    ? `创建${label}参考音色` : `修改或重选${label}参考音色`;
  return <section className="voice-section" aria-label={`${label}旁白音色`}>
    <div className="reference-media-heading"><h3>{label}参考音色</h3>
      <button type="button" className="secondary-button reference-create-button"
        disabled={busy} onClick={() => setCreating(true)}>
        {voice.voice_reference_asset_id === null ? `+ 创建${label}参考音色` : dialogTitle}
      </button></div>
    <TextArea label={`${label}旁白音色方向`} value={voice.voice_description} required
      onChange={(voice_description) => onChange({ ...voice, voice_description })} />
    {voice.voice_reference_asset_id === null ? <p className="muted-copy">尚未选择{label}参考音色。</p> :
      <AssetAudio asset={assetById(snapshot.assets, voice.voice_reference_asset_id)} />}
    {voice.voice_reference_asset_id !== null ? <ReferenceTranscriptField
      value={voice.voice_reference_transcript ?? ""} busy={busy || transcribing}
      available={snapshot.provider_availability.speech_recognition ?? false}
      error={transcriptionError}
      onChange={(value) => onChange({ ...voice, voice_reference_transcript: value || null })}
      onTranscribe={async () => {
        setTranscribing(true); setTranscriptionError(null);
        try { onChange({ ...voice, voice_reference_transcript: (await onTranscribeAudio(voice.voice_reference_asset_id!)).trim() || null }); }
        catch (error) { setTranscriptionError(error instanceof Error ? error.message : "自动提取音频文字失败。"); }
        finally { setTranscribing(false); }
      }} /> : null}
    {creating ? <ReferenceVoiceDialog cardId={`${narratorId}-${language}`} generations={generations}
      assets={snapshot.assets} currentAssetId={voice.voice_reference_asset_id}
      available={snapshot.provider_availability.voice_design} busy={busy}
      title={dialogTitle} defaultSampleText={NARRATOR_SAMPLE_TEXT[language]}
      voiceDescription={voice.voice_description}
      onVoiceDescriptionChange={(voice_description) => onChange({ ...voice, voice_description })}
      onClose={() => setCreating(false)}
      onSelectAsset={(assetId) => { onSelectAsset(assetId); setCreating(false); }}
      onDesign={onDesign} onAttach={onAttach}
      onCancel={onCancelGeneration} onDismiss={onDismissGeneration} /> : null}
  </section>;
}


export function CharacterCardEditor({
  card, snapshot, busy, onSave, onDiscard, onImportImage, onDesignVoice, onAttachVoice,
  onCancelGeneration, onDismissGeneration, onTranscribeAudio, onGenerateLookSheet, onPreviewLookSheet,
  onSelectLookSheet, onSelectLookAsset,
}: {
  card: CharacterCard;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  onSave: (card: CharacterCardDraft) => void;
  onGenerateLookSheet: (lookId: string, identityAssetIds: string[], promptText: string | null) => void;
  onPreviewLookSheet: (lookId: string, identityAssetIds: string[]) => Promise<string>;
  onSelectLookSheet: (lookId: string, generationId: string) => void;
  onSelectLookAsset: (lookId: string, assetId: string) => void;
  onDiscard: () => void;
  onImportImage: ImportImageHandler;
  onDesignVoice: (description: string, sampleText: string, seed: number) => void;
  onAttachVoice: (generationId: string) => void;
  onCancelGeneration: (generationId: string) => void;
  onDismissGeneration: (generationId: string) => void;
  onTranscribeAudio: (assetId: string) => Promise<string>;
}) {
  const [draft, setDraft] = useState<CharacterCardDraft>(card);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [creatingReferenceVoice, setCreatingReferenceVoice] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcriptionError, setTranscriptionError] = useState<string | null>(null);
  const voiceGenerations = cardGenerations(snapshot, card.id, "character_voice");
  return (
    <form className="reference-card" onSubmit={(event) => { event.preventDefault(); onSave(draft); }}>
      <CardHeading kind={draft.visual_description === null ? "非出镜声音" : "角色"} name={draft.name} />
      <TextField label="名称" value={draft.name} required
        onChange={(name) => setDraft({ ...draft, name })} />
      {draft.visual_description !== null ? <><TextArea label="稳定视觉描述" value={draft.visual_description} required
        onChange={(visual_description) => setDraft({ ...draft, visual_description })} />
      <CharacterLooks card={card} looks={draft.looks} snapshot={snapshot}
        busy={busy} onChange={(looks) => setDraft({ ...draft, looks })}
        onGenerate={onGenerateLookSheet} onPreview={onPreviewLookSheet}
        onSelect={onSelectLookSheet} onSelectAsset={onSelectLookAsset}
        onImportImage={onImportImage}
        onCancel={onCancelGeneration} onDismiss={onDismissGeneration} /></> : <p>故事内非出镜声音；不提交视觉参考。</p>}
      <section className="voice-section">
        <div className="reference-media-heading">
          <h3>参考音色</h3>
          <button type="button" className="secondary-button reference-create-button"
            disabled={busy} onClick={() => setCreatingReferenceVoice(true)}>
            {draft.voice_reference_asset_id === null ? "+ 创建参考音色" : "修改或重选参考音色"}
          </button>
        </div>
        {draft.voice_reference_asset_id === null ? <p className="muted-copy">尚未选择参考音色。</p> : (
          <AssetAudio asset={assetById(snapshot.assets, draft.voice_reference_asset_id)} />
        )}
        {draft.voice_reference_asset_id !== null ? <ReferenceTranscriptField
          value={draft.voice_reference_transcript ?? ""} busy={busy || transcribing}
          available={snapshot.provider_availability.speech_recognition ?? false}
          error={transcriptionError} onChange={(value) => setDraft({ ...draft, voice_reference_transcript: value || null })}
          onTranscribe={async () => {
            setTranscribing(true); setTranscriptionError(null);
            try { setDraft({ ...draft, voice_reference_transcript: (await onTranscribeAudio(draft.voice_reference_asset_id!)).trim() || null }); }
            catch (error) { setTranscriptionError(error instanceof Error ? error.message : "自动提取音频文字失败。"); }
            finally { setTranscribing(false); }
          }} /> : null}
        {creatingReferenceVoice ? (
          <ReferenceVoiceDialog cardId={card.id} generations={voiceGenerations}
            assets={snapshot.assets} currentAssetId={draft.voice_reference_asset_id}
            available={snapshot.provider_availability.voice_design} busy={busy}
            title={draft.voice_reference_asset_id === null ? "创建参考音色" : "修改或重选参考音色"}
            voiceDescription={draft.voice_description}
            onVoiceDescriptionChange={(voice_description) =>
              setDraft({ ...draft, voice_description })}
            onClose={() => setCreatingReferenceVoice(false)}
            onSelectAsset={(assetId) => {
              onSave({ ...draft, voice_reference_asset_id: assetId, voice_reference_transcript: null });
              setCreatingReferenceVoice(false);
            }}
            onDesign={onDesignVoice}
            onAttach={onAttachVoice} onCancel={onCancelGeneration}
            onDismiss={onDismissGeneration} />
        ) : null}
      </section>
      <CardActions busy={busy} confirmDiscard={confirmDiscard}
        onConfirmDiscard={setConfirmDiscard} onDiscard={onDiscard} />
    </form>
  );
}

function ReferenceTranscriptField({
  value, busy, available, error, onChange, onTranscribe,
}: {
  value: string;
  busy: boolean;
  available: boolean;
  error: string | null;
  onChange: (value: string) => void;
  onTranscribe: () => Promise<void>;
}) {
  return <label className="card-field">
    <span>参考音频完整文字稿（声音克隆必填）</span>
    <textarea value={value} disabled={busy}
      placeholder="请逐字填写参考音频中实际说出的全部内容。"
      onChange={(event) => onChange(event.target.value)} />
    <button type="button" className="secondary-button" disabled={busy || !available}
      onClick={() => void onTranscribe()}>{busy ? "正在识别……" : "自动提取音频文字"}</button>
    {!available ? <small>Whisper ASR 尚未启动，请手工填写。</small> : null}
    {error !== null ? <small className="reference-error" role="alert">{error}</small> : null}
    {!value.trim() ? <small className="reference-error">未填写完整文字稿；保存后无法使用声音克隆。</small> : null}
  </label>;
}


const MAX_LOOKS = 8;
const MAX_IDENTITY_REFERENCES = 4;

/** 造型是角色图的唯一单位：文字随整卡保存；造型图的生成与选择是独立的即时动作，只对已保存的造型可用。 */
function CharacterLooks({
  card, looks, snapshot, busy, onChange, onGenerate, onPreview, onSelect, onSelectAsset, onImportImage,
  onCancel, onDismiss,
}: {
  card: CharacterCard;
  looks: CharacterLookDraft[];
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  onChange: (looks: CharacterLookDraft[]) => void;
  onGenerate: (lookId: string, identityAssetIds: string[], promptText: string | null) => void;
  onPreview: (lookId: string, identityAssetIds: string[]) => Promise<string>;
  onSelect: (lookId: string, generationId: string) => void;
  onSelectAsset: (lookId: string, assetId: string) => void;
  onImportImage: ImportImageHandler;
  onCancel: (generationId: string) => void;
  onDismiss: (generationId: string) => void;
}) {
  const [imageLookId, setImageLookId] = useState<string | null>(null);
  const saved = new Map(card.looks.map((item) => [item.id, item]));
  const imageLook = imageLookId === null ? null : saved.get(imageLookId) ?? null;
  const update = (index: number, patch: Partial<CharacterLookDraft>) =>
    onChange(looks.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  return <section className="reference-media-section character-looks">
    <div className="reference-media-heading">
      <h3>造型 <span>{looks.length}</span></h3>
      <button type="button" className="secondary-button reference-create-button"
        disabled={busy || looks.length >= MAX_LOOKS}
        onClick={() => onChange([...looks, { id: null, name: "", appearance: "", usage: "" }])}>
        + 新增造型
      </button>
    </div>
    {looks.length === 0 ? <p className="muted-copy">尚未规划造型；每套造型一张造型图，Keyframe 按造型选择角色图。</p> : null}
    {looks.map((look, index) => {
      const current = look.id === null ? undefined : saved.get(look.id);
      const assetId = current?.selected_asset_id ?? null;
      const asset = assetId === null ? null : assetById(snapshot.assets, assetId);
      return <article className="character-look" key={look.id ?? `new-${index}`}
        aria-label={`造型 ${look.name || index + 1}`}>
        <div className="character-look-sheet">
          {asset ? <ZoomableImage src={asset.content_url} alt={`造型「${look.name}」造型图`} />
            : <span className="reference-thumbnail-missing">尚未选定造型图</span>}
        </div>
        <div className="character-look-fields">
          <TextField label="造型名称" value={look.name} required
            onChange={(name) => update(index, { name })} />
          <TextArea label="外观（服装、发型、配饰、状态）" value={look.appearance} required
            onChange={(appearance) => update(index, { appearance })} />
          <TextArea label="使用场合（故事时期或剧情状态）" value={look.usage} required
            onChange={(usage) => update(index, { usage })} />
          <div className="character-look-actions">
            <button type="button" className="secondary-button"
              disabled={busy || current === undefined}
              onClick={() => setImageLookId(current?.id ?? null)}>
              {assetId === null ? "设置造型图" : "更换造型图"}
            </button>
            {current === undefined ? <small className="muted-copy">保存角色卡后可设置造型图。</small> : null}
            <button type="button" className="delete-button" disabled={busy}
              onClick={() => onChange(looks.filter((_, itemIndex) => itemIndex !== index))}>删除造型</button>
          </div>
        </div>
      </article>;
    })}
    {imageLook !== null ? (
      <LookImageDialog card={card} look={imageLook} snapshot={snapshot} busy={busy}
        onClose={() => setImageLookId(null)}
        onGenerate={(identity, promptText) => onGenerate(imageLook.id, identity, promptText)}
        onPreview={(identity) => onPreview(imageLook.id, identity)}
        onSelect={(generationId) => onSelect(imageLook.id, generationId)}
        onSelectAsset={(assetId) => { onSelectAsset(imageLook.id, assetId); setImageLookId(null); }}
        onImportImage={onImportImage}
        onCancel={onCancel} onDismiss={onDismiss} />
    ) : null}
  </section>;
}

function LookImageDialog({
  card, look, snapshot, busy, onClose, onGenerate, onPreview, onSelect, onSelectAsset, onImportImage,
  onCancel, onDismiss,
}: {
  card: CharacterCard;
  look: CharacterLook;
  snapshot: StructuredDirectorSnapshot;
  busy: boolean;
  onClose: () => void;
  onGenerate: (identityAssetIds: string[], promptText: string | null) => void;
  onPreview: (identityAssetIds: string[]) => Promise<string>;
  onSelect: (generationId: string) => void;
  onSelectAsset: (assetId: string) => void;
  onImportImage: ImportImageHandler;
  onCancel: (generationId: string) => void;
  onDismiss: (generationId: string) => void;
}) {
  const [method, setMethod] = useState<"generate" | "library">("generate");
  const [identity, setIdentity] = useState<string[]>([]);
  // Core 编译的完整提示词随身份参考与造型变化重新预览；用户编辑过就保留用户版本，可一键恢复。
  const [compiled, setCompiled] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [edited, setEdited] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const identityKey = identity.join(",");
  const sourceKey = `${card.visual_description}|${look.name}|${look.appearance}`;
  useEffect(() => {
    let cancelled = false;
    onPreview(identityKey === "" ? [] : identityKey.split(","))
      .then((text) => {
        if (cancelled) return;
        setCompiled(text);
        setPreviewError(null);
        setEdited((wasEdited) => {
          if (!wasEdited) setPrompt(text);
          return wasEdited;
        });
      })
      .catch((error: unknown) => {
        if (!cancelled) setPreviewError(error instanceof Error ? error.message : "提示词预览失败。");
      });
    return () => { cancelled = true; };
    // onPreview 每次渲染都是新函数；只在输入事实变化时重新预览。
  }, [identityKey, sourceKey]);
  const importInput = useRef<HTMLInputElement>(null);
  const available = snapshot.provider_availability.image_generation;
  const candidates = imageAssets(snapshot.assets, "character_reference");
  const lookImages = new Map(card.looks.flatMap((item) =>
    item.selected_asset_id === null ? [] : [[item.selected_asset_id, item.name] as const]));
  const titleId = `look-image-${look.id}`;
  const assetLabel = (assetId: string) =>
    lookImages.has(assetId) ? `造型：${lookImages.get(assetId)}` : `@${assetId.slice(0, 6)}`;
  return <div className="reference-image-dialog-backdrop" role="presentation">
    <section className="reference-image-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <header className="reference-image-dialog-header">
        <div><p className="eyebrow">Look image</p><h2 id={titleId}>造型图：{look.name}</h2></div>
        <button type="button" className="dialog-close-button" aria-label="关闭造型图"
          onClick={onClose}>×</button>
      </header>
      <div className="reference-dialog-tabs" role="tablist" aria-label="造型图来源">
        <button type="button" role="tab" aria-selected={method === "generate"}
          className={method === "generate" ? "is-active" : ""}
          onClick={() => setMethod("generate")}>生成设定图</button>
        <button type="button" role="tab" aria-selected={method === "library"}
          className={method === "library" ? "is-active" : ""}
          onClick={() => setMethod("library")}>从资产库选择</button>
      </div>
      {method === "generate" ? <div className="reference-tool-block reference-dialog-tool">
        <p className="muted-copy">
          固定 2:1 柔和浅灰底：左侧四个视角，右侧头部正面特写；画什么由角色视觉描述与造型外观决定，
          非人类角色请在视觉描述里写清是什么生物。
        </p>
        <p className="mention-hint">身份参考（可选，最多 {MAX_IDENTITY_REFERENCES} 张；只保持身份特征与体型）</p>
        {candidates.length === 0 ? <p className="muted-copy">资产库没有角色图片，将纯文本生成。</p> : (
          <div className="mention-assets">{candidates.map((asset) => {
            const chosen = identity.includes(asset.id);
            return <div className="zoomable-tile" key={asset.id}>
              <button type="button" aria-pressed={chosen}
                className={chosen ? "is-mentioned" : ""}
                disabled={!chosen && identity.length >= MAX_IDENTITY_REFERENCES}
                onClick={() => setIdentity(toggleId(identity, asset.id))}>
                <img loading="lazy" src={asset.content_url} alt="可作身份参考的角色图" />
                <span>{assetLabel(asset.id)}</span>
              </button>
              <ImageZoomButton src={asset.content_url} alt={assetLabel(asset.id)} />
            </div>;
          })}</div>
        )}
        <label className="card-field look-sheet-prompt">
          <span>完整提示词（可编辑；按当前图片插件约定编译，原样提交）</span>
          <textarea value={prompt} disabled={busy || compiled === null}
            placeholder={previewError ?? "正在编译提示词……"}
            onChange={(event) => { setPrompt(event.target.value); setEdited(true); }} />
        </label>
        <div className="prompt-tools">
          <button type="button" className="secondary-button" disabled={busy || !edited || compiled === null}
            onClick={() => { setPrompt(compiled ?? ""); setEdited(false); }}>恢复 Core 编译的提示词</button>
          {edited ? <span>已手动编辑；身份参考或造型变化不会覆盖你的修改。</span> : null}
        </div>
        {previewError !== null ? <p className="reference-error" role="alert">{previewError}</p> : null}
        {!available ? <p className="muted-copy">图片生成服务尚未配置。</p> : null}
        <button type="button" className="primary-button"
          disabled={busy || !available || compiled === null || prompt.trim().length === 0}
          onClick={() => onGenerate(identity, edited ? prompt : null)}>生成设定图候选</button>
        <GenerationCandidates generations={cardGenerations(snapshot, look.id, "character_look_sheet")}
          assets={snapshot.assets} media="image" busy={busy}
          attachAction="select_look_sheet" attachLabel="设为本造型图"
          onAttach={onSelect} onCancel={onCancel} onDismiss={onDismiss} />
      </div> : null}
      {method === "library" ? <div className="reference-tool-block reference-dialog-tool asset-library-picker">
        <div className="asset-library-heading">
          <div><h3>角色图片资产</h3><p>导入只登记 Asset；点选图片才会设为本造型图。</p></div>
          <button type="button" className="secondary-button asset-import-button"
            disabled={busy} onClick={() => importInput.current?.click()}>
            加入本地文件到资产库
          </button>
          <input ref={importInput} className="asset-import-input" type="file"
            multiple
            aria-label="选择要加入资产库的本地图片"
            accept="image/png,image/jpeg,image/webp" disabled={busy}
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              if (files.length > 0 && files.every((file) => isSupportedImageType(file.type))) {
                onImportImage(files, "character_reference");
              }
              event.target.value = "";
            }} />
        </div>
        {candidates.length === 0 ? <p className="muted-copy">资产库中还没有角色图片，请先导入本地文件。</p> : (
          <div className="asset-library-grid" aria-label="角色图片资产">{candidates.map((asset) => {
            const current = asset.id === look.selected_asset_id;
            return <div className="zoomable-tile" key={asset.id}>
              <button type="button" disabled={current || busy}
                aria-label={current ? `当前造型图 ${assetLabel(asset.id)}` : `设为造型图 ${assetLabel(asset.id)}`}
                onClick={() => onSelectAsset(asset.id)}>
                <img loading="lazy" src={asset.content_url} alt="角色图片资产预览" />
                <span>{assetLabel(asset.id)}</span>
                {current ? <small>当前</small> : null}
              </button>
              <ImageZoomButton src={asset.content_url} alt={assetLabel(asset.id)} />
            </div>;
          })}</div>
        )}
      </div> : null}
    </section>
  </div>;
}


export function ReferenceVoiceDialog({
  cardId, generations, assets, currentAssetId, available, busy, title = "创建参考音色",
  defaultSampleText = "你好，很高兴认识你。我们从这里开始讲这个故事。", voiceDescription, onVoiceDescriptionChange,
  onClose, onSelectAsset, onDesign, onAttach, onCancel, onDismiss,
}: {
  cardId: string;
  generations: ReferenceGeneration[];
  assets: ProjectAsset[];
  currentAssetId: string | null;
  available: boolean;
  busy: boolean;
  title?: string;
  defaultSampleText?: string;
  voiceDescription: string;
  onVoiceDescriptionChange: (value: string) => void;
  onClose: () => void;
  onSelectAsset: (assetId: string) => void;
  onDesign: (description: string, sampleText: string, seed: number) => void;
  onAttach: (generationId: string) => void;
  onCancel: (generationId: string) => void;
  onDismiss: (generationId: string) => void;
}) {
  const [method, setMethod] = useState<"choose" | "assets" | "generate">("choose");
  const [sampleText, setSampleText] = useState(defaultSampleText);
  const [seed, setSeed] = useState(42);
  const wavAssets = assets.filter((asset) => asset.media_type === "audio/wav");
  const titleId = `create-reference-voice-${cardId}`;
  return <div className="reference-image-dialog-backdrop" role="presentation">
    <section className="reference-image-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <header className="reference-image-dialog-header">
        <div><p className="eyebrow">Reference voice</p><h2 id={titleId}>{title}</h2></div>
        <button type="button" className="dialog-close-button" aria-label={`关闭${title}`}
          onClick={onClose}>×</button>
      </header>
      {method === "choose" ? (
        <div className="reference-methods">
          <button type="button" onClick={() => setMethod("assets")}>
            <strong>从资产库选择</strong><span>从项目资产库选择已有 WAV，设为当前角色的参考音色。</span>
          </button>
          <button type="button" onClick={() => setMethod("generate")}>
            <strong>AI 设计音色</strong><span>填写本次音色描述，生成可试听候选。</span>
          </button>
        </div>
      ) : null}
      {method === "assets" ? (
        <div className="reference-tool-block reference-dialog-tool">
          <button type="button" className="reference-dialog-back"
            onClick={() => setMethod("choose")}>← 返回选择</button>
          <h3>选择资产库中的 WAV</h3>
          {wavAssets.length === 0 ? <p className="muted-copy">资产库中暂无 WAV 音频，请先在资产中心生成音频。</p> : (
            <div className="reference-voice-asset-list">
              {wavAssets.map((asset) => <article key={asset.id} className="reference-voice-asset-item">
                <div><strong>{asset.display_name ?? "未命名音频"}</strong><AssetAudio asset={asset} /></div>
                <button type="button" className="primary-button" disabled={busy || currentAssetId === asset.id}
                  onClick={() => onSelectAsset(asset.id)}>
                  {currentAssetId === asset.id ? "当前参考音色" : "设为参考音色"}
                </button>
              </article>)}
            </div>
          )}
        </div>
      ) : null}
      {method === "generate" ? (
        <div className="reference-tool-block reference-dialog-tool voice-tool">
          <button type="button" className="reference-dialog-back"
            onClick={() => setMethod("choose")}>← 返回选择</button>
          <h3>Voice Design</h3>
          <p className="muted-copy">Breeze TTS 2 按 Voice Description 生成基础音色。</p>
          <TextArea label="音色描述（Voice Description，基础音色）" value={voiceDescription} required
            onChange={onVoiceDescriptionChange} />
          <textarea value={sampleText} placeholder="试听文本"
            onChange={(event) => setSampleText(event.target.value)} />
          <label>Seed <input type="number" min="0" max="4294967295" value={seed}
            onChange={(event) => setSeed(Number(event.target.value))} /></label>
          {!available ? <p className="muted-copy">当前音频生成器尚未配置。</p> : null}
          <button type="button" className="primary-button"
            disabled={busy || !available || !voiceDescription.trim() || !sampleText.trim()}
            onClick={() => onDesign(voiceDescription.trim(), sampleText.trim(), seed)}>生成试听候选</button>
          <GenerationCandidates generations={generations} assets={assets} media="audio"
            busy={busy} onAttach={onAttach} onCancel={onCancel} onDismiss={onDismiss} />
        </div>
      ) : null}
    </section>
  </div>;
}


export function NewCharacterCard({ busy, onCancel, onSave }: {
  busy: boolean;
  onCancel: () => void;
  onSave: (card: Omit<CharacterCard, "id">) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [voiceOnly, setVoiceOnly] = useState(false);
  const [voiceDescription, setVoiceDescription] = useState("");
  return <form className="reference-card is-new" onSubmit={(event) => {
    event.preventDefault();
    onSave({ name, visual_description: voiceOnly ? null : description, looks: [],
      voice_description: voiceDescription, voice_reference_asset_id: null,
      voice_reference_transcript: null });
  }}>
    <CardHeading kind="新角色" name={name || "未命名"} />
    <TextField label="名称" value={name} required onChange={setName} />
    <label><input type="checkbox" checked={voiceOnly} onChange={event => setVoiceOnly(event.target.checked)} />非出镜声音身份</label>
    {voiceOnly ? <TextArea label="声音描述" value={voiceDescription} required onChange={setVoiceDescription} /> : <TextArea label="稳定视觉描述" value={description} required onChange={setDescription} />}
    <NewCardActions busy={busy} onCancel={onCancel} />
  </form>;
}
