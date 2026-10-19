import { LocationLibrary } from "./director_workspace/location";
import { StoryReader } from "./director_workspace/StoryReader";
import { type ReactNode, lazy, Suspense, useContext, useState } from "react";
import { createPortal } from "react-dom";
const AssetCenter = lazy(() => import("./asset_center/AssetCenter").then((module) => ({ default: module.AssetCenter })));
import { MarkdownText } from "./MarkdownText";
import { playgroundApi } from "./playground/api";
import { type StructuredDirectorWorkspaceProps, WorkspaceActionsContext, type WorkspaceActions, type WorkspaceFlatProps } from "./director_workspace/contracts";
import {
  CharacterCardEditor,
  NarratorCardEditor,
  NewCharacterCard,
} from "./director_workspace/references";
import { CapabilityGapBanner } from "./director_workspace/shared";
export function StructuredDirectorWorkspace(
  props: StructuredDirectorWorkspaceProps & Partial<WorkspaceActions>,
) {
  const { actions: suppliedActions, ...data } = props;
  const contextActions = useContext(WorkspaceActionsContext);
  const actions = suppliedActions ?? contextActions ?? (props as unknown as WorkspaceActions);
  const flat = { ...data, ...actions } as WorkspaceFlatProps;
  const {
    project,
    snapshot,
    busy,
    error,
    globalReferencesOpen = false,
    toolbarTarget,
    onCloseGlobalReferences,
    onUpdateDirectorPlan,
    onConfirmReferences,
    onAddCharacter,
    onUpdateCharacter,
    onUpdateNarrator,
    onDiscard,
    onImportImage,
    onImportMedia,
    onDeleteAsset,
    onDeleteAssets,
    onGenerateAudio,
    onTranscribeAudio,
    onTrimAudio,
    onApplyAudioEffect,
    onSeparateVideoAudio,
    onExtractVideoFrame,
    onLoadVideoFrameInfo,
    onRemixVideoAudio,
    onGenerateLookSheet,
    onPreviewLookSheet,
    onSelectLookSheet,
    onSelectLookAsset,
    onDesignVoice,
    onDesignNarratorVoice,
    onAttachNarratorVoice,
    onAttachVoice,
    onCancelGeneration,
    onDismissGeneration,
    onRefreshProjectSnapshot,
  } = flat;
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const referenceReviewRequired = snapshot.workflow.required_next_actions.some(
    (action) => action.action === "reference.confirm_review" && action.human_only,
  );
  const [editingLibrary, setEditingLibrary] = useState(false);
  const [assetCenterOpen, setAssetCenterOpen] = useState(false);
  const [assetCenterVoiceTargetId, setAssetCenterVoiceTargetId] = useState<
    string | null
  >(null);
  const assetCenterVoiceTarget = snapshot.reference_library.characters.find(
    (item) => item.id === assetCenterVoiceTargetId,
  );
  const [directorPlanOpen, setDirectorPlanOpen] = useState(false);
  const [directorPlanEditing, setDirectorPlanEditing] = useState(false);
  const [directorPlanDraft, setDirectorPlanDraft] = useState(
    snapshot.director_plan_markdown,
  );
  const activeRunKind = snapshot.active_director_run?.kind;
  const isPreparing =
    snapshot.director_script === null &&
    (snapshot.status === "awaiting_reference_proposal" ||
      activeRunKind === "reference_proposal" ||
      activeRunKind === "script_proposal");
  function withAssetCenter(content: ReactNode): ReactNode {
    const toolbar = (
      <>
        <button className="secondary-button" onClick={() => setLocationsOpen(true)}>
          地点库
        </button>
        <button
          className="director-plan-trigger"
          type="button"
          onClick={() => {
            setDirectorPlanDraft(snapshot.director_plan_markdown);
            setDirectorPlanEditing(false);
            setDirectorPlanOpen(true);
          }}
        >
          原始导演方案
        </button>
        <button
          className="asset-center-trigger"
          type="button"
          onClick={() => {
            setAssetCenterVoiceTargetId(null);
            setAssetCenterOpen(true);
          }}
        >
          资产中心
        </button>
      </>
    );
    return (
      <>
        {activeRunKind ? (
          <section
            className="director-inline-operation"
            aria-label="外部 Agent 工作区"
          >
            <div>
              <strong>
                {activeRunKind
                  ? "等待外部 Agent 完成当前请求"
                  : "外部 Agent 工作区"}
              </strong>
              <span>
                {activeRunKind
                  ? "请求和范围已由 Core 保存。请在原外部 Agent 中继续或取消；这里可查看最新状态。"
                  : "在外部 Agent 中规划与执行，在此查看结果、编辑材料、选择候选和审核。"}
              </span>
            </div>
          </section>
        ) : null}
        <CapabilityGapBanner alerts={snapshot.capability_gap_alerts} />
        {content}
        {locationsOpen ? (
          <div className="director-plan-backdrop">
            <section className="global-references-dialog location-library-dialog"
              role="dialog" aria-modal="true" aria-label="项目地点库">
              <header>
                <h2>项目地点库</h2>
                <button className="secondary-button" onClick={() => setLocationsOpen(false)}>
                  关闭地点库
                </button>
              </header>
              <LocationLibrary {...flat} />
            </section>
          </div>
        ) : null}
        {toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbar}
        {directorPlanOpen ? (
          <div
            className="director-plan-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget)
                setDirectorPlanOpen(false);
            }}
          >
            <section
              className="director-plan-reader"
              role="dialog"
              aria-modal="true"
              aria-label="原始导演方案"
            >
              <header>
                <div>
                  <p className="eyebrow">Project source</p>
                  <h2>原始导演方案</h2>
                </div>
                <div className="director-plan-actions">
                  {!directorPlanEditing && snapshot.allowed_actions.includes("edit_director_plan") ? (
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => setDirectorPlanEditing(true)}
                    >
                      编辑方案
                    </button>
                  ) : null}
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => setDirectorPlanOpen(false)}
                  >
                    关闭
                  </button>
                </div>
              </header>
              {directorPlanEditing ? (
                <form
                  className="director-plan-editor"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    if (await onUpdateDirectorPlan(directorPlanDraft)) {
                      setDirectorPlanEditing(false);
                    }
                  }}
                >
                  <p className="form-hint">
                    只更新项目原始方案，不会自动改写或失效已有脚本和媒体。需要把新增内容落入成片时，请随后修改结构化脚本。
                  </p>
                  <textarea
                    aria-label="编辑原始导演方案"
                    value={directorPlanDraft}
                    maxLength={50000}
                    disabled={busy}
                    onChange={(event) => setDirectorPlanDraft(event.target.value)}
                  />
                  <div className="director-plan-editor-footer">
                    <span>{directorPlanDraft.length.toLocaleString()} / 50,000</span>
                    <div className="director-plan-actions">
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setDirectorPlanDraft(snapshot.director_plan_markdown);
                          setDirectorPlanEditing(false);
                        }}
                      >
                        取消
                      </button>
                      <button
                        className="primary-button"
                        type="submit"
                        disabled={busy || !directorPlanDraft.trim()}
                      >
                        保存方案
                      </button>
                    </div>
                  </div>
                </form>
              ) : (
                <div className="director-plan-content">
                  <MarkdownText markdown={snapshot.director_plan_markdown} />
                </div>
              )}
            </section>
          </div>
        ) : null}
        {assetCenterOpen ? (
          <Suspense fallback={<div className="asset-center-loading">正在加载资产中心…</div>}>
          <AssetCenter
          providerRecipes={snapshot.provider_recipes}
            assets={snapshot.assets}
            generations={snapshot.generations}
            audioSeparationAvailable={snapshot.provider_availability.audio_separation ?? false}
            audioRemixAvailable={snapshot.provider_availability.audio_remix ?? false}
            voiceDesignAvailable={snapshot.provider_availability.voice_design}
            speechSynthesisAvailable={snapshot.provider_availability.speech_synthesis}
            speechRecognitionAvailable={snapshot.provider_availability.speech_recognition ?? false}
            referenceVoiceTranscripts={Object.fromEntries([
              ...snapshot.reference_library.characters.map((item) => [item.voice_reference_asset_id, item.voice_reference_transcript] as const),
              ...(snapshot.reference_library.narrator === null ? [] : snapshot.narration_languages.map((language) => snapshot.reference_library.narrator![language]!).map((voice) => [voice.voice_reference_asset_id, voice.voice_reference_transcript] as const)),
            ].filter(([assetId]) => assetId !== null) as Array<[string, string | null]>) }
            busy={busy}
            canGenerateAudio={snapshot.allowed_actions.includes("generate_audio")}
            canImportImage={snapshot.allowed_actions.includes(
              "import_image_asset",
            )}
            canImportMedia={snapshot.allowed_actions.includes(
              "import_media_asset",
            )}
            canDeleteAssets={snapshot.allowed_actions.includes("delete_asset")}
            initialFilter={assetCenterVoiceTarget === undefined ? "all" : "audio"}
            voiceSelectionTarget={
              assetCenterVoiceTarget === undefined
                ? null
                : {
                    name: assetCenterVoiceTarget.name,
                    currentAssetId: assetCenterVoiceTarget.voice_reference_asset_id,
                  }
            }
            onSelectReferenceVoice={(assetId) => {
              if (assetCenterVoiceTarget === undefined) return;
              onUpdateCharacter({
                ...assetCenterVoiceTarget,
                voice_reference_asset_id: assetId,
                voice_reference_transcript: null,
              });
              setAssetCenterOpen(false);
              setAssetCenterVoiceTargetId(null);
            }}
            onClose={() => {
              setAssetCenterOpen(false);
              setAssetCenterVoiceTargetId(null);
            }}
            onImportImage={onImportImage}
            onImportMedia={onImportMedia}
            onDelete={onDeleteAsset}
            onDeleteMany={onDeleteAssets}
            onGenerateAudio={onGenerateAudio}
            onTrimAudio={onTrimAudio}
            onApplyAudioEffect={onApplyAudioEffect}
            onSeparateVideoAudio={onSeparateVideoAudio}
            onExtractVideoFrame={onExtractVideoFrame ?? (() => undefined)}
            onLoadVideoFrameInfo={onLoadVideoFrameInfo}
            onRemixVideoAudio={onRemixVideoAudio}
            onLoadPlaygroundAssets={() =>
              playgroundApi.get().then((playground) => playground.assets)
            }
            onCopyFromPlayground={async (assetId, category) => {
              await playgroundApi.copyToProject(
                project.id,
                assetId,
                snapshot.revision,
                category,
              );
              onRefreshProjectSnapshot?.();
              return true;
            }}
          />
          </Suspense>
        ) : null}
        {globalReferencesOpen ? (
          <div
            className="director-plan-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget)
                onCloseGlobalReferences?.();
            }}
          >
            <section
              className="global-references-dialog"
              role="dialog"
              aria-modal="true"
              aria-label="全局引用"
            >
              <header>
                <div>
                  <p className="eyebrow">Global references</p>
                  <h2>全局引用</h2>
                </div>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={onCloseGlobalReferences}
                >
                  关闭
                </button>
              </header>
              <p>
                这里集中展示跨镜头保持一致的角色与旁白身份；脚本只保存它们的
                ID。
              </p>
              <div className="global-reference-sections">
                <section>
                  <h3>角色</h3>
                  <div className="director-reference-list">
                    {snapshot.reference_library.characters.map((card) => (
                      <div key={card.id}>
                        <strong>{card.name}</strong>
                        <span>角色</span>
                      </div>
                    ))}
                    {snapshot.reference_library.characters.length === 0 ? (
                      <small>当前没有全局角色卡。</small>
                    ) : null}
                  </div>
                </section>
                <section>
                  <h3>旁白身份</h3>
                  <div className="director-reference-list">
                    {snapshot.reference_library.narrator !== null ? (
                      <div>
                        <strong>
                          {snapshot.reference_library.narrator.name}
                        </strong>
                        <span>旁白</span>
                      </div>
                    ) : (
                      <small>当前没有独立旁白身份。</small>
                    )}
                  </div>
                </section>
              </div>
              <footer>
                <button
                  className={
                    referenceReviewRequired ? "secondary-button" : "primary-button"
                  }
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    onCloseGlobalReferences?.();
                    setEditingLibrary(true);
                  }}
                >
                  编辑引用库
                </button>
                {referenceReviewRequired ? (
                  <button
                    className="primary-button"
                    type="button"
                    disabled={busy}
                    onClick={onConfirmReferences}
                  >
                    完成审核并继续
                  </button>
                ) : null}
                {error !== null ? <p role="alert">{error}</p> : null}
              </footer>
            </section>
          </div>
        ) : null}
      </>
    );
  }
  function renderLibrary() {
    const characters = snapshot.reference_library.characters;
    return (
      <section className="reference-workspace">
        <header className="reference-header">
          <div>
            <p className="eyebrow">Structured director · reference library</p>
            <h1>{project.title}</h1>
            <p className="reference-intro">
              角色卡只管理跨镜头稳定的视觉和声音参考。角色是否出场、场内动作和故事作用仍由脚本决定。
            </p>
          </div>
          <div className="reference-summary" aria-label="引用库摘要">
            <span>
              <strong>{characters.length}</strong> 角色
            </span>
            <small>revision {snapshot.revision}</small>
          </div>
        </header>

        <div className="reference-toolbar">
          <div className="reference-tabs">
            <strong>角色与声音引用库</strong>
          </div>
          <button
            className="secondary-button reference-add-button"
            type="button"
            disabled={busy}
            onClick={() => setAdding(true)}
          >
            + 新增角色
          </button>
        </div>

        {error !== null ? (
          <div className="reference-error" role="alert">
            {error}
          </div>
        ) : null}

        {referenceReviewRequired ? (
          <div className="reference-toolbar">
            <button type="button" className="primary-button"
              disabled={busy}
              onClick={onConfirmReferences}>
              {snapshot.director_script === null
                ? "确认角色与声音引用" : "完成审核并继续"}
            </button>
          </div>
        ) : null}

        <div className="reference-grid">
          {snapshot.reference_library.narrator !== null ? (
            <NarratorCardEditor
              key={`${snapshot.reference_library.narrator.id}:${JSON.stringify(snapshot.reference_library.narrator)}`}
              profile={snapshot.reference_library.narrator}
              snapshot={snapshot}
              busy={busy}
              onSave={onUpdateNarrator}
              onDesign={onDesignNarratorVoice}
              onAttach={onAttachNarratorVoice}
              onCancelGeneration={onCancelGeneration}
              onDismissGeneration={onDismissGeneration}
              onTranscribeAudio={onTranscribeAudio}
            />
          ) : null}
          {characters.map((card) => (
            <CharacterCardEditor
              key={`${card.id}:${JSON.stringify(card)}`}
              card={card}
              snapshot={snapshot}
              busy={busy}
              onSave={onUpdateCharacter}
              onDiscard={() => onDiscard("characters", card.id)}
              onImportImage={onImportImage}
              onDesignVoice={(description, text, seed) =>
                onDesignVoice(card.id, description, text, seed)
              }
              onGenerateLookSheet={(lookId, identityAssetIds, promptText) =>
                onGenerateLookSheet(card.id, lookId, identityAssetIds, promptText)
              }
              onPreviewLookSheet={(lookId, identityAssetIds) =>
                onPreviewLookSheet(card.id, lookId, identityAssetIds)
              }
              onSelectLookSheet={(lookId, generationId) =>
                onSelectLookSheet(card.id, lookId, generationId)
              }
              onSelectLookAsset={(lookId, assetId) => onSelectLookAsset(card.id, lookId, assetId)}
              onAttachVoice={(generationId) => onAttachVoice(card.id, generationId)}
              onCancelGeneration={onCancelGeneration}
              onDismissGeneration={onDismissGeneration}
              onTranscribeAudio={onTranscribeAudio}
            />
          ))}
          {adding ? (
            <NewCharacterCard
              busy={busy}
              onCancel={() => setAdding(false)}
              onSave={(card) => {
                onAddCharacter(card);
                setAdding(false);
              }}
            />
          ) : null}
        </div>

        <footer className="reference-next-step">
          <div>
            <p className="eyebrow">
              {editingLibrary ? "Reference library" : "Next checkpoint"}
            </p>
            <h2>
              {editingLibrary
                ? "修改会保留当前脚本，不会静默重写"
                : "生成结构化导演脚本"}
            </h2>
            <p>
              {editingLibrary
                ? "移出角色卡只改变引用库；脚本中的既有引用会保留，便于你明确处理。"
                : "造型图和音色都可以稍后继续补充；生成后仍可逐项编辑再确认。"}
            </p>
          </div>
          {editingLibrary ? (
            <button
              className="secondary-button"
              type="button"
              onClick={() => setEditingLibrary(false)}
            >
              返回当前故事位置
            </button>
          ) : (
            <p>审核卡片后，请在外部 Agent 中明确发起结构化脚本请求。</p>
          )}
        </footer>
      </section>
    );
  }
  if (snapshot.director_script !== null) {
    return withAssetCenter(
      <>
        <StoryReader
          {...flat}
        />
        {editingLibrary ? (
          <div className="director-plan-backdrop">
            <section
              className="story-reference-editor"
              role="dialog"
              aria-modal="true"
              aria-label="编辑引用库"
            >
              {renderLibrary()}
            </section>
          </div>
        ) : null}
      </>,
    );
  }
  if (isPreparing) {
    const waitingForReferences = activeRunKind === undefined;
    const preparingScript = activeRunKind === "script_proposal";
    const planningKeyframes = activeRunKind === "keyframe_plan";
    const preparingKeyframes = planningKeyframes;
    return withAssetCenter(
      <section className="reference-preparing" aria-live="polite">
        <div className="reference-preparing-card">
          <p className="eyebrow">
            {preparingKeyframes
              ? "Segment keyframes"
              : preparingScript
                ? "Director script"
                : "Reference setup"}
          </p>
          <h1>
            {activeRunKind
              ? "等待外部 Agent 提交"
              : waitingForReferences
                ? "角色与声音引用库尚未建立"
                : preparingKeyframes
                  ? "正在规划 Segment 关键帧"
                  : preparingScript
                    ? "正在生成结构化导演脚本"
                    : "正在整理角色"}
          </h1>
          <p>
            {waitingForReferences
              ? "导演方案已保存。点击左上角「连接 Agent」，你可以询问当前应该做什么。整理角色与声音引用后在这里审核并确认。"
              : preparingKeyframes
                ? "Agent 正在为每个 Segment 提取准确的首尾静态时刻；这里只建立计划，不会自动生成图片。"
                : preparingScript
                  ? "Agent 正在把已确认材料拆成 Scene、Shot 和显式 Segment；Core 会校验并分配 ID。"
                    : "Agent 只提取需要跨镜头保持一致的视觉或声音身份，不复述剧情和表演。"}
          </p>
          {error !== null ? (
            <div className="reference-error" role="alert">
              {error}
            </div>
          ) : null}
        </div>
      </section>,
    );
  }
  return withAssetCenter(renderLibrary());
}
