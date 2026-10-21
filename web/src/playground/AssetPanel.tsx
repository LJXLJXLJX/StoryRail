import { DismissibleDialog } from "../DismissibleDialog";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  StoryRailApiError,
  projectApi,
  structuredDirectorApi,
  type PlaygroundAsset,
  type ProjectAsset,
  type ProjectSummary,
} from "../api";
import { ZoomableImage } from "../ImagePreview";
import { playgroundApi } from "./api";
import { AssetAudioPlayer } from "./AssetAudioPlayer";
import { CopyToProjectDialog } from "./CopyToProjectDialog";
import { assetMediaKind, type AssetPickRequest } from "./forms/common";

// 01 §12.8 的统一文案。
const ASSET_IN_USE_MESSAGE =
  "该素材正被未结束的实验使用，请等待或取消相关实验后再删除。";

type MediaFilter = "all" | "image" | "audio" | "video";
type Tab = "playground" | "project";
type Offset = { x: number; y: number };

type UploadResult = { name: string; ok: boolean; message?: string };

const WINDOW_MARGIN = 8;

function originLabel(
  asset: PlaygroundAsset,
  projects: ProjectSummary[] | null,
): string {
  if (asset.origin.kind === "imported") return "导入";
  if (asset.origin.kind === "run_output") return "实验产物";
  const projectId = asset.origin.project_id ?? "";
  const title = projects?.find((item) => item.id === projectId)?.title;
  return `来自项目《${title ?? projectId.slice(0, 8)}》`;
}

// 悬浮窗口拖动：始终保证窗口至少有一部分留在视口内。
function clampValue(value: number, min: number, max: number): number {
  if (max < min) return 0;
  return Math.min(Math.max(value, min), max);
}

function clampOffset(
  panel: HTMLElement,
  current: Offset,
  next: Offset,
): Offset {
  const rect = panel.getBoundingClientRect();
  const baseLeft = rect.left - current.x;
  const baseTop = rect.top - current.y;
  return {
    x: clampValue(
      next.x,
      WINDOW_MARGIN - baseLeft,
      window.innerWidth - WINDOW_MARGIN - rect.width - baseLeft,
    ),
    y: clampValue(
      next.y,
      WINDOW_MARGIN - baseTop,
      window.innerHeight - WINDOW_MARGIN - rect.height - baseTop,
    ),
  };
}

function AssetMedia({
  mediaType,
  contentUrl,
  name,
}: {
  mediaType: string;
  contentUrl: string;
  name: string;
}) {
  if (mediaType.startsWith("image/")) {
    return (
      <div className="playground-asset-media is-image">
        <ZoomableImage src={contentUrl} alt={name} />
      </div>
    );
  }
  if (mediaType.startsWith("audio/")) {
    return (
      <div className="playground-asset-media is-audio">
        <AssetAudioPlayer src={contentUrl} label={name} />
      </div>
    );
  }
  return (
    <div className="playground-asset-media is-video">
      <video controls preload="none" src={contentUrl} />
    </div>
  );
}

export function AssetPanel({
  assets,
  selection = null,
  onClose,
  onChanged,
}: {
  assets: PlaygroundAsset[];
  selection?: AssetPickRequest | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const selecting = selection !== null;
  const [tab, setTab] = useState<Tab>("playground");
  const [filter, setFilter] = useState<MediaFilter>("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [uploadResults, setUploadResults] = useState<UploadResult[]>([]);
  const [uploading, setUploading] = useState(false);
  const [copyTarget, setCopyTarget] = useState<PlaygroundAsset | null>(null);
  const [highlightAssetId, setHighlightAssetId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [projectId, setProjectId] = useState("");
  const [projectAssets, setProjectAssets] = useState<ProjectAsset[] | null>(
    null,
  );
  const [projectError, setProjectError] = useState<string | null>(null);
  const [offset, setOffset] = useState<Offset>({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  const windowRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    origin: Offset;
  } | null>(null);

  useEffect(() => {
    if (projects !== null) return;
    if (!assets.some((asset) => asset.origin.kind === "copied_from_project")) {
      return;
    }
    let cancelled = false;
    void projectApi.list().then(
      (items) => {
        if (!cancelled) setProjects(items);
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [assets, projects]);

  useEffect(() => {
    if (tab !== "project" || projects !== null) return;
    let cancelled = false;
    void projectApi.list().then(
      (items) => {
        if (!cancelled) setProjects(items);
      },
      (caught: unknown) => {
        if (!cancelled) {
          setProjectError(
            caught instanceof Error ? caught.message : "无法读取项目列表。",
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [tab, projects]);

  // 视口变化后把窗口拉回可见区域，避免拖动过以后窗口留在屏幕外。
  useEffect(() => {
    function handleResize() {
      const panel = windowRef.current;
      if (panel === null) return;
      setOffset((current) => clampOffset(panel, current, current));
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const effectiveFilter: MediaFilter = selecting ? selection.mediaKind : filter;
  const visible = selecting
    ? assets.filter(
        (asset) =>
          assetMediaKind(asset.media_type) === selection.mediaKind &&
          (!selection.mediaTypes ||
            selection.mediaTypes.includes(asset.media_type)) &&
          (!selection.requiredAction ||
            asset.allowed_actions.includes(selection.requiredAction)) &&
          (!selection.durationSeconds ||
            (asset.duration_seconds !== null &&
              asset.duration_seconds >= selection.durationSeconds[0]! &&
              asset.duration_seconds <= selection.durationSeconds[1]!)),
      )
    : assets.filter(
        (asset) =>
          effectiveFilter === "all" ||
          assetMediaKind(asset.media_type) === effectiveFilter,
      );
  const selectedAssets = visible.filter((asset) => selected.includes(asset.id));
  // 全选只作用于当前过滤下可删除的资产；被占用资产不能勾选，也不计入全选。
  const selectableIds = visible
    .filter((asset) => asset.allowed_actions.includes("delete"))
    .map((asset) => asset.id);
  const allSelected =
    selectableIds.length > 0 &&
    selectableIds.every((id) => selected.includes(id));

  function toggleSelectAll() {
    setSelected((current) =>
      allSelected
        ? current.filter((id) => !selectableIds.includes(id))
        : [...new Set([...current, ...selectableIds])],
    );
  }

  const startDrag = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      const target = event.target as HTMLElement;
      if (target.closest("button, a, input, select, label")) return;
      const panel = windowRef.current;
      if (panel === null) return;
      dragRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        origin: offset,
      };
      // jsdom 等测试环境没有指针捕获，缺失时不影响拖动状态机。
      if (typeof event.currentTarget.setPointerCapture === "function") {
        try {
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
          // 指针已释放或环境不支持，忽略。
        }
      }
      setDragging(true);
    },
    [offset],
  );

  const moveDrag = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    const panel = windowRef.current;
    if (drag === null || panel === null || drag.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    setOffset((current) =>
      clampOffset(panel, current, {
        x: drag.origin.x + (event.clientX - drag.startX),
        y: drag.origin.y + (event.clientY - drag.startY),
      }),
    );
  }, []);

  const endDrag = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDragging(false);
  }, []);

  async function uploadFiles(files: File[]) {
    if (files.length === 0) return;
    setUploading(true);
    const results: UploadResult[] = [];
    for (const file of files) {
      try {
        await playgroundApi.uploadAsset(file);
        results.push({ name: file.name, ok: true });
      } catch (caught) {
        results.push({
          name: file.name,
          ok: false,
          message:
            caught instanceof StoryRailApiError
              ? caught.message
              : "上传失败，请重试。",
        });
      }
    }
    setUploadResults(results);
    setUploading(false);
    if (results.some((result) => result.ok)) onChanged();
  }

  async function deleteSelected() {
    const ids = selectedAssets.map((asset) => asset.id);
    setConfirmingDelete(false);
    setDeleteError(null);
    if (ids.length === 0) return;
    try {
      await playgroundApi.deleteAssets(ids);
      setSelected([]);
      onChanged();
    } catch (caught) {
      if (
        caught instanceof StoryRailApiError &&
        caught.code === "asset_in_use"
      ) {
        setDeleteError(ASSET_IN_USE_MESSAGE);
      } else {
        setDeleteError(
          caught instanceof StoryRailApiError
            ? caught.message
            : "删除失败，请重试。",
        );
      }
    }
  }

  async function loadProject(targetId: string) {
    setProjectId(targetId);
    setProjectAssets(null);
    setProjectError(null);
    if (targetId === "") return;
    try {
      const snapshot = await structuredDirectorApi.get(targetId);
      setProjectAssets(snapshot.assets);
    } catch (caught) {
      setProjectError(
        caught instanceof StoryRailApiError
          ? caught.message
          : "无法读取项目资产。",
      );
    }
  }

  async function copyFromProject(assetId: string) {
    if (projectId === "") return;
    setProjectError(null);
    try {
      const copied = await playgroundApi.copyFromProject(projectId, assetId);
      setTab("playground");
      setFilter("all");
      setHighlightAssetId(copied.id);
      onChanged();
    } catch (caught) {
      setProjectError(
        caught instanceof StoryRailApiError
          ? caught.message
          : "复制失败，请重试。",
      );
    }
  }

  return (
    <div className="playground-window-layer" role="presentation">
      <DismissibleDialog onClose={onClose}
        ref={windowRef}
        className={
          dragging ? "playground-window is-dragging" : "playground-window"
        }
        role="dialog"
        aria-label={selecting ? "选择素材" : "Playground 资产"}
        style={
          offset.x === 0 && offset.y === 0
            ? undefined
            : { transform: `translate(${offset.x}px, ${offset.y}px)` }
        }
      >
        <header
          className="playground-window-head"
          title="拖动标题栏可移动窗口"
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <span className="playground-window-grip" aria-hidden="true" />
          <h2>{selecting ? "选择素材" : "资产"}</h2>
          {selecting ? (
            <p className="playground-window-note">
              正在为表单槽位选择
              {selection.mediaKind === "image"
                ? "图片"
                : selection.mediaKind === "audio"
                  ? "音频"
                  : "视频"}
            </p>
          ) : null}
          <span className="playground-window-head-spacer" />
          <button type="button" className="secondary-button" onClick={onClose}>
            {selecting ? "取消" : "关闭"}
          </button>
        </header>

        <div className="playground-window-body">
          {selecting ? null : (
            <div
              className="playground-window-tabs"
              role="tablist"
              aria-label="资产页签"
            >
              <button
                type="button"
                role="tab"
                aria-selected={tab === "playground"}
                className={tab === "playground" ? "is-active" : ""}
                onClick={() => setTab("playground")}
              >
                Playground 资产
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "project"}
                className={tab === "project" ? "is-active" : ""}
                onClick={() => setTab("project")}
              >
                项目资产
              </button>
            </div>
          )}

          {selecting || tab === "playground" ? (
            <>
              {selecting ? null : (
                <>
                  <div className="playground-window-toolbar">
                    <label className="playground-window-filter">
                      <span>类型</span>
                      <select
                        aria-label="资产类型"
                        value={filter}
                        onChange={(event) =>
                          setFilter(event.target.value as MediaFilter)
                        }
                      >
                        <option value="all">全部</option>
                        <option value="image">图片</option>
                        <option value="audio">音频</option>
                        <option value="video">视频</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={uploading}
                      onClick={() => uploadInput.current?.click()}
                    >
                      {uploading ? "上传中…" : "导入素材"}
                    </button>
                    <input
                      ref={uploadInput}
                      type="file"
                      multiple
                      aria-label="选择要上传的素材"
                      style={{ display: "none" }}
                      onChange={(event) => {
                        void uploadFiles(Array.from(event.target.files ?? []));
                        event.target.value = "";
                      }}
                    />
                    <button
                      type="button"
                      className="secondary-button playground-select-all"
                      disabled={selectableIds.length === 0}
                      onClick={toggleSelectAll}
                    >
                      {allSelected ? "取消全选" : "全选"}
                    </button>
                    <button
                      type="button"
                      className="danger-text-button"
                      disabled={selectedAssets.length === 0}
                      onClick={() => setConfirmingDelete(true)}
                    >
                      删除所选（{selectedAssets.length}）
                    </button>
                  </div>
                  {uploadResults.length === 0 ? null : (
                    <ul className="playground-upload-results">
                      {uploadResults.map((result, index) => (
                        <li
                          key={`${result.name}-${index}`}
                          className={result.ok ? "" : "is-error"}
                        >
                          {result.name}：
                          {result.ok
                            ? "上传成功"
                            : `上传失败：${result.message}`}
                        </li>
                      ))}
                    </ul>
                  )}
                  {confirmingDelete ? (
                    <div className="playground-window-confirm" role="alert">
                      <p>
                        将删除 {selectedAssets.length} 个 Playground
                        资产，确定继续？
                      </p>
                      <div className="playground-window-confirm-actions">
                        <button
                          type="button"
                          className="delete-button"
                          onClick={() => void deleteSelected()}
                        >
                          确认删除
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => setConfirmingDelete(false)}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : null}
                  {deleteError === null ? null : (
                    <p className="playground-error" role="alert">
                      {deleteError}
                    </p>
                  )}
                </>
              )}
              {visible.length === 0 ? (
                <p className="playground-hint">没有匹配的 Playground 资产。</p>
              ) : (
                <div className="playground-asset-grid">
                  {visible.map((asset) => {
                    const canDelete = asset.allowed_actions.includes("delete");
                    return (
                      <article
                        key={asset.id}
                        className={
                          asset.id === highlightAssetId
                            ? "playground-asset-item is-selected"
                            : "playground-asset-item"
                        }
                      >
                        <AssetMedia
                          mediaType={asset.media_type}
                          contentUrl={asset.content_url}
                          name={asset.display_name}
                        />
                        <div className="playground-asset-meta">
                          <strong title={asset.display_name}>
                            {asset.display_name}
                          </strong>
                          <span>
                            {asset.media_type} · {originLabel(asset, projects)}
                          </span>
                        </div>
                        {selecting ? (
                          <div className="playground-asset-item-actions">
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => {
                                selection.onPick(asset.id);
                                onClose();
                              }}
                            >
                              选择
                            </button>
                          </div>
                        ) : (
                          <div className="playground-asset-item-actions">
                            <label className="playground-asset-select">
                              <input
                                type="checkbox"
                                aria-label={`选择 ${asset.display_name}`}
                                disabled={!canDelete}
                                title={
                                  canDelete ? undefined : ASSET_IN_USE_MESSAGE
                                }
                                checked={selected.includes(asset.id)}
                                onChange={(event) =>
                                  setSelected((current) =>
                                    event.target.checked
                                      ? [...current, asset.id]
                                      : current.filter((id) => id !== asset.id),
                                  )
                                }
                              />
                              <span>选择</span>
                            </label>
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => setCopyTarget(asset)}
                            >
                              复制到项目…
                            </button>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="playground-window-toolbar">
                <label className="playground-window-filter">
                  <span>项目</span>
                  <select
                    aria-label="项目"
                    value={projectId}
                    onChange={(event) => void loadProject(event.target.value)}
                  >
                    <option value="">请选择项目</option>
                    {(projects ?? []).map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.title}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {projectError === null ? null : (
                <p className="playground-error" role="alert">
                  {projectError}
                </p>
              )}
              {projectAssets === null ? (
                <p className="playground-hint">
                  {projectId === "" ? "请选择项目。" : "正在读取项目资产…"}
                </p>
              ) : (
                <div className="playground-asset-grid">
                  {projectAssets.map((asset) => {
                    const name = asset.display_name ?? "项目素材";
                    return (
                      <article key={asset.id} className="playground-asset-item">
                        <AssetMedia
                          mediaType={asset.media_type}
                          contentUrl={asset.content_url}
                          name={name}
                        />
                        <div className="playground-asset-meta">
                          <strong title={name}>{name}</strong>
                          <span>{asset.media_type}</span>
                        </div>
                        <div className="playground-asset-item-actions">
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => void copyFromProject(asset.id)}
                          >
                            复制到 Playground
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </DismissibleDialog>
      {copyTarget === null ? null : (
        <CopyToProjectDialog
          asset={copyTarget}
          projects={projects}
          onClose={() => setCopyTarget(null)}
        />
      )}
    </div>
  );
}
