import { useEffect, useState } from "react";

import {
  StoryRailApiError,
  projectApi,
  structuredDirectorApi,
  type ProjectSummary,
} from "../api";
import { playgroundApi } from "./api";
import { IMPORT_IMAGE_CATEGORIES } from "../asset_center/AssetCenter";
import type { ImageAssetCategory, PlaygroundAsset } from "../api";

export function CopyToProjectDialog({
  asset,
  projects,
  onClose,
}: {
  asset: PlaygroundAsset;
  projects: ProjectSummary[] | null;
  onClose: () => void;
}) {
  const isImage = asset.media_type.startsWith("image/");
  const [projectId, setProjectId] = useState("");
  const [category, setCategory] = useState<ImageAssetCategory | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loadedProjects, setLoadedProjects] = useState<ProjectSummary[] | null>(
    projects,
  );

  useEffect(() => {
    if (loadedProjects !== null) return;
    let cancelled = false;
    void projectApi.list().then(
      (items) => {
        if (!cancelled) setLoadedProjects(items);
      },
      (caught: unknown) => {
        if (!cancelled) {
          setError(
            caught instanceof Error ? caught.message : "无法读取项目列表。",
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [loadedProjects]);

  const project = loadedProjects?.find((item) => item.id === projectId) ?? null;
  const ready = projectId !== "" && (!isImage || category !== null);

  async function confirm() {
    if (!ready) return;
    setPending(true);
    setError(null);
    try {
      await copyWithRevisionRetry(projectId, asset.id, category);
      setSuccess(`已复制到《${project?.title ?? projectId}》`);
    } catch (caught) {
      setError(
        caught instanceof StoryRailApiError
          ? caught.message
          : "复制失败，请重试。",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="playground-dialog-backdrop" role="presentation">
      <section
        className="playground-dialog"
        role="dialog"
        aria-label="复制到项目"
      >
        <h2>复制到项目</h2>
        <p className="playground-hint">
          {asset.display_name} · {asset.media_type}
        </p>
        <div className="playground-field">
          <span className="playground-field-label">目标项目</span>
          <select
            aria-label="目标项目"
            value={projectId}
            disabled={pending}
            onChange={(event) => {
              setProjectId(event.target.value);
              setSuccess(null);
              setError(null);
            }}
          >
            <option value="">请选择项目</option>
            {(loadedProjects ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </div>
        {isImage ? (
          <div className="playground-field">
            <span className="playground-field-label">图片分类</span>
            <select
              aria-label="图片分类"
              value={category ?? ""}
              disabled={pending}
              onChange={(event) => {
                const value = event.target.value;
                setCategory(value === "" ? null : (value as ImageAssetCategory));
                setSuccess(null);
                setError(null);
              }}
            >
              <option value="">请选择分类</option>
              {IMPORT_IMAGE_CATEGORIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        {error === null ? null : (
          <p className="playground-error" role="alert">
            {error}
          </p>
        )}
        {success === null ? null : (
          <p className="playground-hint" role="status">
            {success}
          </p>
        )}
        <div className="playground-dialog-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            关闭
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={pending || !ready}
            onClick={() => void confirm()}
          >
            {pending ? "复制中…" : "确认复制"}
          </button>
        </div>
      </section>
    </div>
  );
}

// 先取目标项目当前 revision；revision_conflict 时重新读取并只重试一次。
async function copyWithRevisionRetry(
  projectId: string,
  assetId: string,
  category: ImageAssetCategory | null,
): Promise<void> {
  const snapshot = await structuredDirectorApi.get(projectId);
  try {
    await playgroundApi.copyToProject(
      projectId,
      assetId,
      snapshot.revision,
      category,
    );
  } catch (caught) {
    if (
      !(caught instanceof StoryRailApiError) ||
      caught.code !== "revision_conflict"
    ) {
      throw caught;
    }
    const latest = await structuredDirectorApi.get(projectId);
    await playgroundApi.copyToProject(
      projectId,
      assetId,
      latest.revision,
      category,
    );
  }
}
