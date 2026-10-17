import { useState } from "react";
import { createPortal } from "react-dom";
import type {
  Location,
  LocationView,
  LocationProduction,
  Scene,
  Shot,
  StructuredDirectorSnapshot,
} from "../api";
import type {
  LocationChange,
  LocationImpact,
  LocationOperation,
} from "../api/location";
import type { WorkspaceFlatProps } from "./contracts";
import {
  assetById,
  GenerationCandidateList,
  MultiImageAssetPickerDialog,
  TextArea,
  TextField,
  ZoomableImage,
} from "./shared";
import {
  normalizeAzimuth,
  PanoramaCameraEditor,
  relativeYawOffset,
  type CameraView,
} from "./PanoramaCameraEditor";
import "./location.css";

type Props = Pick<
  WorkspaceFlatProps,
  | "snapshot"
  | "busy"
  | "onPreviewLocationChange"
  | "onApplyLocationChange"
  | "onGenerateLocationMaster"
  | "onGenerateLocationView"
  | "onCancelGeneration"
  | "onDismissGeneration"
>;
const patch = (
  operations: LocationOperation[],
  locationIds: string[] = [],
  sceneIds: string[] = [],
  shotIds: string[] = [],
): LocationChange => ({
  name: "location.apply_operations",
  arguments: {
    scope: {
      location_ids: locationIds,
      scene_ids: sceneIds,
      shot_ids: shotIds,
    },
    operations,
  },
});

function finiteNumber(value: string) {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function angleInput(value: number) {
  const rounded = Math.round(value * 10) / 10;
  return String(Object.is(rounded, -0) ? 0 : rounded);
}

function useLocationChange(props: Props) {
  const [pending, setPending] = useState<{
    change: LocationChange;
    impact: LocationImpact;
    done?: () => void;
  } | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  async function preview(
    change: LocationChange,
    done?: () => void,
    revision = props.snapshot.revision,
  ) {
    if (!props.onPreviewLocationChange) return;
    setWorking(true);
    setError("");
    try {
      setPending({
        change,
        impact: await props.onPreviewLocationChange(change, revision),
        done,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法读取影响预览。");
    } finally {
      setWorking(false);
    }
  }
  const stale =
    pending !== null && pending.impact.revision !== props.snapshot.revision;
  const dialog = (
    <>
      {error ? <p role="alert">{error}</p> : null}
      {pending
        ? createPortal(
            <div className="scene-asset-picker-backdrop">
              <section
                className="scene-asset-picker-dialog location-impact"
                role="dialog"
                aria-modal="true"
                aria-label="地点修改影响预览"
              >
                <header>
                  <h2>地点修改影响预览</h2>
                  <button
                    className="secondary-button"
                    onClick={() => setPending(null)}
                    disabled={working}
                  >
                    取消
                  </button>
                </header>
                <p>
                  {pending.impact.will_write
                    ? `确认后保存修改，涉及 ${pending.impact.changed_ids.length} 个对象。`
                    : "与当前状态相同，无需修改。"}
                </p>
                <h3>将失效的内容</h3>
                {pending.impact.invalidated.length ? (
                  <ul>
                    {pending.impact.invalidated.map((item) => (
                      <li key={item}>{impactLabel(item, props.snapshot)}</li>
                    ))}
                  </ul>
                ) : (
                  <p>无下游内容失效。</p>
                )}
                <p className="muted-copy">
                  保留：
                  {pending.impact.preserved
                    .map(
                      (item) =>
                        ({
                          asset_history: "资产历史",
                          generation_history: "生成历史",
                          location_selection: "当前地点选择",
                        })[item] ?? item,
                    )
                    .join("、") || "无额外变更"}
                </p>
                {stale ? (
                  <p role="alert">项目已更新，请取消并重新预览。</p>
                ) : null}
                <footer>
                  <button
                    className="primary-button"
                    disabled={
                      props.busy ||
                      working ||
                      stale ||
                      !props.onApplyLocationChange
                    }
                    onClick={async () => {
                      setWorking(true);
                      try {
                        if (
                          await props.onApplyLocationChange?.(
                            pending.change,
                            pending.impact.revision,
                          )
                        ) {
                          pending.done?.();
                          setPending(null);
                        }
                      } catch (e) {
                        setError(e instanceof Error ? e.message : "保存失败。");
                      } finally {
                        setWorking(false);
                      }
                    }}
                  >
                    确认保存
                  </button>
                </footer>
              </section>
            </div>,
            document.body,
          )
        : null}
    </>
  );
  return { preview, dialog, working };
}
function impactLabel(item: string, snapshot: StructuredDirectorSnapshot) {
  const [kind, id] = item.split(":");
  const names: Record<string, string> = {
    location_view_crop: "视图裁切底图",
    location_calibration: "地点标定",
    location_view_selection: "地点视图选择",
    location_master_selection: "地点主图选择",
    keyframe: "关键帧选择",
    video_selection: "片段视频选择",
    keyframe_selection: "关键帧选择",
    video_upscale: "超分选择",
    final_assembly: "最终装配",
    scene_final: "场景成片",
  };
  const target = snapshot.location_library.locations
    .flatMap((l) => [l, ...l.views])
    .find((x) => x.id === id);
  return `${names[kind] ?? kind}${target ? ` · ${target.name}` : id ? ` · ${id.slice(0, 6)}` : ""}`;
}
function LocationImage({
  snapshot,
  id,
  label,
  panorama = false,
  empty = "尚无图片",
}: {
  snapshot: StructuredDirectorSnapshot;
  id: string | null;
  label: string;
  panorama?: boolean;
  empty?: string;
}) {
  const asset = id ? assetById(snapshot.assets, id) : null;
  return (
    <figure className="location-figure">
      <div
        className={`${panorama ? "location-panorama" : "location-image"}${asset ? "" : " is-empty"}`}
        style={
          panorama
            ? undefined
            : { aspectRatio: snapshot.aspect_ratio.replace(":", " / ") }
        }
      >
        {asset ? (
          <ZoomableImage src={asset.content_url} alt={label} />
        ) : (
          <p className="location-image-empty">{empty}</p>
        )}
      </div>
      <figcaption>{label}</figcaption>
    </figure>
  );
}
const STATUS_TONE: Record<string, string> = {
  already_selected: "done",
  in_progress: "working",
  awaiting_selection: "attention",
  failed: "problem",
  blocked: "problem",
  submission_uncertain: "problem",
};
function StatusBadge({ production }: { production?: LocationProduction }) {
  if (!production) return null;
  return (
    <span
      className={`location-status is-${STATUS_TONE[production.status] ?? "idle"}`}
    >
      {production.status_label}
    </span>
  );
}
function Production({
  production,
  selected,
  panorama,
  props,
  onSelect,
  onClear,
}: {
  production?: LocationProduction;
  selected: string | null;
  panorama?: boolean;
  props: Props;
  onSelect: (assetId: string) => void;
  onClear: () => void;
}) {
  if (!production) return null;
  const candidates = props.snapshot.generations.filter((g) =>
    production.candidate_generation_ids.includes(g.id),
  );
  const active = props.snapshot.generations.find(
    (g) => g.id === production.active_generation_id,
  );
  const cancellable = active?.allowed_actions.includes("cancel");
  return (
    <div className="location-production">
      {production.reason && !active ? (
        <p className="location-production-reason">{production.reason}</p>
      ) : null}
      <GenerationCandidateList
        kind="location"
        target={active?.target_id ?? candidates[0]?.target_id ?? "empty"}
        assets={props.snapshot.assets}
        candidates={candidates}
        active={active}
        busy={props.busy}
        summary={`图片候选（${candidates.length}）`}
        workingText="正在生成"
        onSelect={(g) => g.output_asset_id && onSelect(g.output_asset_id)}
        selectDisabled={(g) =>
          !production.allowed_actions.includes("select") ||
          !production.selectable_generation_ids.includes(g.id)
        }
        isSelected={(_g, a) => a?.id === selected}
        renderCandidate={(_g, a) =>
          a ? (
            <div className={panorama ? "location-panorama" : "location-image"}>
              <ZoomableImage src={a.content_url} alt="地点图片候选" />
            </div>
          ) : null
        }
        onDismiss={props.onDismissGeneration}
        dismissAllowed={(g) => g.allowed_actions.includes("dismiss_history")}
      />
      {cancellable || selected ? (
        <div className="location-production-actions">
          {cancellable ? (
            <button
              className="secondary-button"
              disabled={props.busy}
              onClick={() => props.onCancelGeneration(active!.id)}
            >
              取消生成
            </button>
          ) : null}
          {selected ? (
            <button
              className="delete-button"
              disabled={
                props.busy ||
                !production.allowed_actions.includes("clear_selection")
              }
              onClick={onClear}
            >
              清除选择
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type EditTarget =
  | { kind: "location"; location?: Location }
  | { kind: "view"; location: Location; view?: LocationView }
  | { kind: "fixture" | "state"; location: Location; id?: string };
type Change = ReturnType<typeof useLocationChange>;
type Edit = (target: EditTarget) => void;

export function LocationLibrary(props: Props) {
  const { snapshot, busy } = props;
  const change = useLocationChange(props);
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const library = snapshot.location_library;
  const active =
    library.locations.find((l) => l.id === activeId) ?? library.locations[0];
  return (
    <section className="location-library" aria-label="地点库">
      <header className="location-library-toolbar">
        <p>
          跨 Scene
          共享的固定空间：先定主图，再从主图得到各机位视图。候选生成后由你选择。
        </p>
        <button
          className="primary-button"
          disabled={
            busy || !library.allowed_actions?.includes("create_location")
          }
          onClick={() => setEditing({ kind: "location" })}
        >
          新建地点
        </button>
      </header>
      {!library.locations.length ? (
        <p className="location-library-empty">
          尚未建立地点，可手动创建或让 Director 规划。
        </p>
      ) : (
        <div className="location-library-body">
          <nav className="location-index" aria-label="地点列表">
            {library.locations.map((location) => (
              <button
                key={location.id}
                type="button"
                className={location === active ? "is-active" : undefined}
                aria-current={location === active ? "true" : undefined}
                onClick={() => setActiveId(location.id)}
              >
                <span className="location-index-thumb">
                  {location.master.selected_asset_id ? (
                    <img
                      src={
                        assetById(snapshot.assets, location.master.selected_asset_id)
                          ?.content_url
                      }
                      alt=""
                    />
                  ) : null}
                </span>
                <span className="location-index-text">
                  <strong>{location.name}</strong>
                  <small>
                    {location.kind === "interior" ? "室内" : "室外"} ·{" "}
                    {location.views.length} 个视图
                    {location.states.length
                      ? ` · ${location.states.length} 个状态`
                      : ""}
                  </small>
                </span>
              </button>
            ))}
          </nav>
          <LocationDetail
            key={active.id}
            location={active}
            props={props}
            change={change}
            edit={setEditing}
          />
        </div>
      )}
      {editing ? (
        <LocationEditor
          key={`${editing.kind}-${editing.location?.id}-${"id" in editing ? editing.id : "view" in editing ? editing.view?.id : ""}`}
          target={editing}
          props={props}
          working={change.working}
          onClose={() => setEditing(null)}
          onSave={(ops, revision) =>
            void change.preview(
              patch(ops, editing.location ? [editing.location.id] : []),
              () => setEditing(null),
              revision,
            )
          }
        />
      ) : null}
      {change.dialog}
    </section>
  );
}

function LocationDetail({
  location,
  props,
  change,
  edit,
}: {
  location: Location;
  props: Props;
  change: Change;
  edit: Edit;
}) {
  const { busy } = props;
  const interior = location.kind === "interior";
  const light = location.key_light;
  return (
    <article className="location-detail" aria-label={`地点 ${location.name}`}>
      <header className="location-detail-header">
        <div>
          <span className="location-kicker">
            {interior ? "室内地点 · 2:1 全景主图" : "室外地点 · 项目画幅主图"}
          </span>
          <h2>{location.name}</h2>
          {location.description ? <p>{location.description}</p> : null}
        </div>
        <div className="location-inline-actions">
          <button
            className="secondary-button"
            aria-label="编辑地点与主图计划"
            disabled={busy || !location.allowed_actions?.includes("edit")}
            onClick={() => edit({ kind: "location", location })}
          >
            编辑
          </button>
          <button
            className="delete-button"
            disabled={busy || !location.allowed_actions?.includes("delete")}
            onClick={() =>
              void change.preview(
                patch(
                  [{ op: "delete_location", location_id: location.id }],
                  [location.id],
                ),
              )
            }
          >
            删除地点
          </button>
        </div>
      </header>

      <section className="location-section" aria-label="主图">
        <header className="location-section-header">
          <h3>主图</h3>
          <StatusBadge production={location.master.production} />
          <button
            className="primary-button"
            disabled={
              busy ||
              !location.master.production?.allowed_actions.includes("generate")
            }
            onClick={() => props.onGenerateLocationMaster?.(location.id)}
          >
            {location.master.production?.generate_label ?? "生成主图"}
          </button>
        </header>
        <LocationImage
          snapshot={props.snapshot}
          id={location.master.selected_asset_id}
          label="已选主图"
          panorama={interior}
          empty="尚未选择主图"
        />
        <dl className="location-facts">
          <dt>主光</dt>
          <dd>
            {light?.description ?? "未设置"}
            {light?.azimuth_deg == null ? "" : ` · 方位 ${light.azimuth_deg}°`}
          </dd>
        </dl>
        <Production
          production={location.master.production}
          selected={location.master.selected_asset_id}
          panorama={interior}
          props={props}
          onSelect={(asset_id) =>
            void change.preview({
              name: "location.select_master",
              arguments: { location_id: location.id, asset_id },
            })
          }
          onClear={() =>
            void change.preview(
              patch(
                [{ op: "clear_master_selection", location_id: location.id }],
                [location.id],
              ),
            )
          }
        />
      </section>

      <div className="location-setting-columns">
        <ResourceList
          title="固定陈设"
          noun="陈设"
          empty="没有需要跨镜头保持位置的陈设。"
          rows={location.fixtures.map((f) => ({
            ...f,
            meta: f.azimuth_deg == null ? "未标定方位" : `方位 ${f.azimuth_deg}°`,
          }))}
          canCreate={!!location.allowed_actions?.includes("create_fixture")}
          busy={busy}
          onCreate={() => edit({ kind: "fixture", location })}
          onEdit={(id) => edit({ kind: "fixture", location, id })}
          onDelete={(id) =>
            void change.preview(
              patch(
                [{ op: "delete_fixture", location_id: location.id, fixture_id: id }],
                [location.id],
              ),
            )
          }
        />
        <ResourceList
          title="地点状态"
          noun="状态"
          empty="只有基础状态。昼夜、天气或布置变化在这里新增。"
          rows={location.states}
          canCreate={!!location.allowed_actions?.includes("create_state")}
          busy={busy}
          onCreate={() => edit({ kind: "state", location })}
          onEdit={(id) => edit({ kind: "state", location, id })}
          onDelete={(id) =>
            void change.preview(
              patch(
                [{ op: "delete_state", location_id: location.id, state_id: id }],
                [location.id],
              ),
            )
          }
        />
      </div>

      <section className="location-section" aria-label="机位视图">
        <header className="location-section-header">
          <h3>
            机位视图<small>{location.views.length}</small>
          </h3>
          <button
            className="secondary-button"
            disabled={
              busy || !location.allowed_actions?.includes("create_view")
            }
            onClick={() => edit({ kind: "view", location })}
          >
            新增视图
          </button>
        </header>
        {interior ? (
          <p className="location-section-hint">
            每个视图分两步：先由主图确定性裁切出底图，再清晰化细化成成品视图。裁切底图不是候选，也不会自动细化。
          </p>
        ) : (
          <p className="location-section-hint">
            每个视图由主图按机位转向编辑生成。
          </p>
        )}
        {location.views.length ? (
          <div className="location-view-grid">
            {location.views.map((view) => (
              <ViewCard
                key={view.id}
                location={location}
                view={view}
                props={props}
                change={change}
                edit={edit}
              />
            ))}
          </div>
        ) : (
          <p className="location-list-empty">尚无机位视图。</p>
        )}
      </section>
    </article>
  );
}

function ResourceList({
  title,
  noun,
  empty,
  rows,
  canCreate,
  busy,
  onCreate,
  onEdit,
  onDelete,
}: {
  title: string;
  noun: string;
  empty: string;
  rows: {
    id: string;
    name: string;
    description: string;
    meta?: string;
    allowed_actions?: ("edit" | "delete")[];
  }[];
  canCreate: boolean;
  busy: boolean;
  onCreate: () => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <section className="location-section location-resource-list" aria-label={title}>
      <header className="location-section-header">
        <h3>
          {title}
          <small>{rows.length}</small>
        </h3>
        <button
          className="secondary-button"
          disabled={busy || !canCreate}
          onClick={onCreate}
        >
          新增{noun}
        </button>
      </header>
      {rows.length ? (
        <ul>
          {rows.map((row) => (
            <li key={row.id}>
              <div>
                <strong>{row.name}</strong>
                {row.meta ? <small>{row.meta}</small> : null}
                <p>{row.description}</p>
              </div>
              <div className="location-inline-actions">
                <button
                  className="secondary-button"
                  aria-label={`编辑${noun}`}
                  disabled={busy || !row.allowed_actions?.includes("edit")}
                  onClick={() => onEdit(row.id)}
                >
                  编辑
                </button>
                <button
                  className="delete-button"
                  aria-label={`删除${noun}`}
                  disabled={busy || !row.allowed_actions?.includes("delete")}
                  onClick={() => onDelete(row.id)}
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="location-list-empty">{empty}</p>
      )}
    </section>
  );
}

function ViewCard({
  location,
  view,
  props,
  change,
  edit,
}: {
  location: Location;
  view: LocationView;
  props: Props;
  change: Change;
  edit: Edit;
}) {
  const { busy } = props;
  const interior = location.kind === "interior";
  const allowed = view.production?.allowed_actions ?? [];
  const named = (ids: string[]) =>
    ids.map((id) => location.views.find((v) => v.id === id)?.name).join("、");
  const facts = [
    view.look_at_fixture_id
      ? `朝向 ${location.fixtures.find((f) => f.id === view.look_at_fixture_id)?.name ?? "陈设"} ${view.yaw_offset_deg}°`
      : `方位 ${view.azimuth_deg}°`,
    `俯仰 ${view.pitch_deg}°`,
    `视场 ${view.hfov_deg}°`,
    location.states.find((s) => s.id === view.state_id)?.name ?? "基础状态",
    ...(view.reference_view_ids.length
      ? [`参考 ${named(view.reference_view_ids)}`]
      : []),
  ];
  return (
    <article className="location-view-card" aria-label={`视图 ${view.name}`}>
      <header>
        <h4>{view.name}</h4>
        <StatusBadge production={view.production} />
      </header>
      {view.purpose ? <p className="location-view-purpose">{view.purpose}</p> : null}
      <ul className="location-view-facts">
        {facts.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
      <div className={interior ? "location-comparison" : undefined}>
        {interior ? (
          <LocationImage
            snapshot={props.snapshot}
            id={view.has_valid_crop ? view.crop_asset_id : null}
            label="裁切底图（只读）"
            empty="尚未裁切"
          />
        ) : null}
        <LocationImage
          snapshot={props.snapshot}
          id={view.selected_asset_id}
          label="已选视图"
          empty="尚未选择"
        />
      </div>
      <div className="location-view-actions">
        <button
          className="primary-button"
          disabled={busy || !allowed.includes("generate")}
          onClick={() => props.onGenerateLocationView?.(view.id)}
        >
          {view.production?.generate_label ?? "生成视图"}
        </button>
        <span className="location-inline-actions">
          <button
            className="secondary-button"
            aria-label="编辑视图"
            disabled={busy || !allowed.includes("edit")}
            onClick={() => edit({ kind: "view", location, view })}
          >
            编辑
          </button>
          <button
            className="delete-button"
            aria-label="删除视图"
            disabled={busy || !allowed.includes("delete")}
            onClick={() =>
              void change.preview(
                patch([{ op: "delete_view", view_id: view.id }], [location.id]),
              )
            }
          >
            删除
          </button>
        </span>
      </div>
      <Production
        production={view.production}
        selected={view.selected_asset_id}
        props={props}
        onSelect={(asset_id) =>
          void change.preview({
            name: "location.select_view",
            arguments: { view_id: view.id, asset_id },
          })
        }
        onClear={() =>
          void change.preview(
            patch([{ op: "clear_view_selection", view_id: view.id }], [location.id]),
          )
        }
      />
    </article>
  );
}


function LocationEditor({
  target,
  props,
  working,
  onClose,
  onSave,
}: {
  target: EditTarget;
  props: Props;
  working: boolean;
  onClose: () => void;
  onSave: (ops: LocationOperation[], revision: number) => void;
}) {
  const [revision] = useState(props.snapshot.revision);
  const save = (ops: LocationOperation[]) => onSave(ops, revision);
  const location = target.location;
  const view = target.kind === "view" ? target.view : undefined;
  const resource =
    target.kind === "fixture"
      ? location?.fixtures.find((f) => f.id === target.id)
      : target.kind === "state"
        ? location?.states.find((s) => s.id === target.id)
        : undefined;
  const [name, setName] = useState(
    view?.name ??
      resource?.name ??
      (target.kind === "location" ? location?.name : "") ??
      "",
  );
  const [description, setDescription] = useState(
    resource?.description ??
      (target.kind === "location" ? location?.description : "") ??
      "",
  );
  const [kind, setKind] = useState<Location["kind"]>(
    location?.kind ?? "interior",
  );
  const [prompt, setPrompt] = useState(
    target.kind === "view"
      ? (view?.refine_prompt_text ?? "")
      : (location?.master.prompt_text ?? ""),
  );
  const [refs, setRefs] = useState(location?.master.reference_asset_ids ?? []);
  const [picking, setPicking] = useState(false);
  const [light, setLight] = useState(location?.key_light?.description ?? "");
  const [lightAzimuth, setLightAzimuth] = useState(
    String(location?.key_light?.azimuth_deg ?? ""),
  );
  const [purpose, setPurpose] = useState(view?.purpose ?? "");
  const [azimuth, setAzimuth] = useState(
    String(
      view?.azimuth_deg ??
        (target.kind === "fixture"
          ? location?.fixtures.find((f) => f.id === target.id)?.azimuth_deg
          : 0) ??
        "",
    ),
  );
  const [fixture, setFixture] = useState(view?.look_at_fixture_id ?? "");
  const [offset, setOffset] = useState(String(view?.yaw_offset_deg ?? 0));
  const [pitch, setPitch] = useState(String(view?.pitch_deg ?? 0));
  const [hfov, setHfov] = useState(String(view?.hfov_deg ?? 75));
  const [state, setState] = useState(view?.state_id ?? "");
  const [viewRefs, setViewRefs] = useState(view?.reference_view_ids ?? []);
  const masterAsset = location?.master.selected_asset_id
    ? assetById(props.snapshot.assets, location.master.selected_asset_id)
    : null;
  const targetFixture = fixture
    ? location?.fixtures.find((item) => item.id === fixture)
    : null;
  const fixtureAzimuth = targetFixture?.azimuth_deg ?? null;
  const numericAzimuth = finiteNumber(azimuth);
  const numericOffset = finiteNumber(offset);
  const numericPitch = finiteNumber(pitch);
  const numericHfov = finiteNumber(hfov);
  const resolvedYaw = fixture
    ? fixtureAzimuth === null || numericOffset === null
      ? null
      : normalizeAzimuth(fixtureAzimuth + numericOffset)
    : numericAzimuth === null
      ? null
      : normalizeAzimuth(numericAzimuth);
  const cameraView: CameraView | null =
    resolvedYaw === null || numericPitch === null || numericHfov === null
      ? null
      : {
          yawDeg: resolvedYaw,
          pitchDeg: numericPitch,
          hfovDeg: numericHfov,
        };
  const setCameraView = (next: CameraView) => {
    if (fixture && fixtureAzimuth !== null) {
      setOffset(angleInput(relativeYawOffset(next.yawDeg, fixtureAzimuth)));
    } else if (!fixture) {
      setAzimuth(angleInput(next.yawDeg));
    }
    setPitch(angleInput(next.pitchDeg));
    setHfov(angleInput(next.hfovDeg));
  };
  const isNew =
    target.kind === "location"
      ? !location
      : target.kind === "view"
        ? !view
        : !target.id;
  const title = `${isNew ? "新建" : "编辑"}${
    {
      location: "地点",
      view: "机位视图",
      fixture: "固定陈设",
      state: "地点状态",
    }[target.kind]
  }`;
  const numberField = (
    label: string,
    value: string,
    set: (v: string) => void,
    min: number,
    max: number,
    required = true,
  ) => (
    <label className="card-field">
      <span>{label}</span>
      <input
        aria-label={label}
        type="number"
        step="any"
        min={min}
        max={max}
        required={required}
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </label>
  );
  return createPortal(
    <div className="reference-image-dialog-backdrop">
      <section
        className="reference-image-dialog location-editor"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="reference-image-dialog-header">
          <div>
            {location && target.kind !== "location" ? (
              <p className="eyebrow">{location.name}</p>
            ) : null}
            <h2>{title}</h2>
          </div>
          <button
            className="secondary-button"
            onClick={onClose}
            disabled={working}
          >
            关闭
          </button>
        </header>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (target.kind === "location") {
              const id = location?.id ?? "new_location";
              const ops: LocationOperation[] = location
                ? []
                : [{ op: "create_location", key: id, name, kind, description }];
              ops.push({
                op: "update_location",
                location_id: id,
                fields: {
                  name,
                  kind,
                  description,
                  master_prompt_text: prompt,
                  master_reference_asset_ids: refs,
                  key_light: light.trim()
                    ? {
                        description: light,
                        azimuth_deg:
                          lightAzimuth === "" ? null : Number(lightAzimuth),
                      }
                    : null,
                },
              });
              save(ops);
            } else if (target.kind === "view") {
              const fields = {
                name,
                purpose,
                azimuth_deg: fixture ? null : Number(azimuth),
                look_at_fixture_id: fixture || null,
                yaw_offset_deg: fixture ? Number(offset) : null,
                pitch_deg: Number(pitch),
                hfov_deg: Number(hfov),
                state_id: state || null,
                refine_prompt_text: prompt,
                reference_view_ids: viewRefs,
              };
              save([
                view
                  ? { op: "update_view", view_id: view.id, fields }
                  : {
                      op: "create_view",
                      location_id: target.location.id,
                      key: "new_view",
                      fields,
                    },
              ]);
            } else if (target.kind === "fixture")
              save([
                {
                  op: "upsert_fixture",
                  location_id: target.location.id,
                  fixture: target.id ?? "new_fixture",
                  name,
                  description,
                  azimuth_deg: azimuth === "" ? null : Number(azimuth),
                },
              ]);
            else
              save([
                {
                  op: "upsert_state",
                  location_id: target.location.id,
                  state: target.id ?? "new_state",
                  name,
                  description,
                },
              ]);
          }}
        >
          {target.kind === "location" ? (
            <>
              <fieldset className="location-editor-group">
                <legend>基本信息</legend>
                <TextField label="名称" value={name} required onChange={setName} />
                <label className="card-field">
                  <span>地点类型</span>
                  <select
                    aria-label="地点类型"
                    value={kind}
                    onChange={(e) => setKind(e.target.value as Location["kind"])}
                  >
                    <option value="interior">室内（2:1 全景）</option>
                    <option value="exterior">室外（项目画幅）</option>
                  </select>
                </label>
                <TextArea
                  label="描述"
                  value={description}
                  onChange={setDescription}
                />
              </fieldset>
              <fieldset className="location-editor-group">
                <legend>主光</legend>
                <TextArea label="主光描述" value={light} onChange={setLight} />
                {numberField(
                  "主光方位（可留空）",
                  lightAzimuth,
                  setLightAzimuth,
                  0,
                  359.999,
                  false,
                )}
              </fieldset>
              <fieldset className="location-editor-group">
                <legend>主图生成</legend>
                <TextArea
                  label="主图提示词"
                  value={prompt}
                  onChange={setPrompt}
                />
                <div>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => setPicking(true)}
                  >
                    选择主图参考图（{refs.length}/5）
                  </button>
                </div>
              </fieldset>
            </>
          ) : null}
          {target.kind === "fixture" || target.kind === "state" ? (
            <>
              <TextField label="名称" value={name} required onChange={setName} />
              <TextArea
                label="描述"
                value={description}
                onChange={setDescription}
                required
              />
            </>
          ) : null}
          {target.kind === "fixture" && !location?.master.selected_asset_id
            ? numberField(
                "陈设方位（可留空）",
                azimuth,
                setAzimuth,
                0,
                359.999,
                false,
              )
            : null}
          {target.kind === "fixture" && location?.master.selected_asset_id ? (
            <p className="muted-copy">已选主图后，陈设方位由主图标定决定，这里不能直接修改。</p>
          ) : null}
          {target.kind === "view" ? (
            <>
              <fieldset className="location-editor-group">
                <legend>基本信息</legend>
                <TextField label="名称" value={name} required onChange={setName} />
                <TextArea
                  label="视图用途"
                  value={purpose}
                  required
                  onChange={setPurpose}
                />
                <label className="card-field">
                  <span>视图状态</span>
                  <select
                    aria-label="视图状态"
                    value={state}
                    onChange={(e) => setState(e.target.value)}
                  >
                    <option value="">基础状态</option>
                    {location?.states.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
              </fieldset>
              <fieldset className="location-editor-group">
                <legend>机位</legend>
                <label className="card-field">
                  <span>朝向方式</span>
                  <select
                    aria-label="朝向陈设"
                    value={fixture}
                    onChange={(e) => {
                      const nextFixture = e.target.value;
                      if (nextFixture) {
                        const nextOrigin = location?.fixtures.find(
                          (item) => item.id === nextFixture,
                        )?.azimuth_deg;
                        if (resolvedYaw !== null && nextOrigin != null) {
                          setOffset(
                            angleInput(relativeYawOffset(resolvedYaw, nextOrigin)),
                          );
                        }
                      } else if (resolvedYaw !== null) {
                        setAzimuth(angleInput(resolvedYaw));
                      }
                      setFixture(nextFixture);
                    }}
                  >
                    <option value="">绝对方位</option>
                    {location?.fixtures.map((f) => (
                      <option key={f.id} value={f.id}>
                        朝向陈设：{f.name}
                      </option>
                    ))}
                  </select>
                </label>
                {location?.kind === "interior" ? (
                  masterAsset && cameraView ? (
                    <PanoramaCameraEditor
                      panoramaUrl={masterAsset.content_url}
                      aspectRatio={props.snapshot.aspect_ratio}
                      view={cameraView}
                      onChange={setCameraView}
                    />
                  ) : (
                    <p className="location-camera-unavailable">
                      {!masterAsset
                        ? "选择室内 2:1 主图后，才能在这里实时转动机位。"
                        : fixture && fixtureAzimuth === null
                          ? `陈设「${targetFixture?.name ?? "未命名"}」尚未标定方位，暂时无法解析实时机位。`
                          : "请先填写有效的机位参数。"}
                    </p>
                  )
                ) : (
                  <p className="location-camera-unavailable">
                    室外主图不是 360° 全景，无法可靠地实时转动；参数用于后续图片转向编辑。
                  </p>
                )}
                <div className="location-editor-numbers">
                  {fixture
                    ? numberField("相对偏转", offset, setOffset, -180, 180)
                    : numberField("绝对方位", azimuth, setAzimuth, 0, 359.999)}
                  {numberField("俯仰角", pitch, setPitch, -60, 60)}
                  {numberField("水平视场角", hfov, setHfov, 20, 120)}
                </div>
              </fieldset>
              <fieldset className="location-editor-group">
                <legend>生成</legend>
                {location?.kind === "exterior" ? (
                  <TextArea label="转向提示词" value={prompt} onChange={setPrompt} />
                ) : (
                  <p className="muted-copy">
                    室内视图的细化只做清晰化：保持裁切底图的构图，去除拉伸与模糊并补足细节，不需要提示词。
                  </p>
                )}
                <div className="card-field">
                  <span>参考视图</span>
                  {location?.views.some((v) => v.id !== view?.id) ? (
                    <div className="location-editor-checks">
                      {location.views
                        .filter((v) => v.id !== view?.id)
                        .map((v) => (
                          <label key={v.id}>
                            <input
                              type="checkbox"
                              checked={viewRefs.includes(v.id)}
                              onChange={(e) =>
                                setViewRefs(
                                  e.target.checked
                                    ? [...viewRefs, v.id]
                                    : viewRefs.filter((id) => id !== v.id),
                                )
                              }
                            />
                            {v.name}
                          </label>
                        ))}
                    </div>
                  ) : (
                    <p className="muted-copy">本地点暂无其它视图。</p>
                  )}
                </div>
              </fieldset>
            </>
          ) : null}
          <footer>
            <button
              className="primary-button"
              type="submit"
              disabled={props.busy || working}
            >
              预览修改影响
            </button>
          </footer>
        </form>
        {picking ? (
          <MultiImageAssetPickerDialog
            title="主图参考图"
            ariaLabel="选择主图参考图"
            assets={props.snapshot.assets.filter((a) =>
              a.media_type.startsWith("image/"),
            )}
            selectedAssetIds={refs}
            maxSelected={5}
            busy={props.busy}
            onClose={() => setPicking(false)}
            onChange={setRefs}
          />
        ) : null}
      </section>
    </div>,
    document.body,
  );
}

export function LocationBinding({
  scene,
  shot,
  ...props
}: Props & { scene: Scene; shot?: Shot }) {
  const change = useLocationChange(props);
  const [editing, setEditing] = useState(false);
  const [revision, setRevision] = useState(props.snapshot.revision);
  const [locationId, setLocationId] = useState(scene.location_id ?? "");
  const [stateId, setStateId] = useState(scene.state_id ?? "");
  const [viewId, setViewId] = useState(shot?.view_id ?? "");
  const library = props.snapshot.location_library;
  const location = library.locations.find((l) => l.id === scene.location_id);
  const draftLocation = library.locations.find((l) => l.id === locationId);
  const view = location?.views.find((v) => v.id === shot?.view_id);
  return (
    <section
      className="location-binding"
      aria-label={shot ? "镜头机位视图" : "场景地点与状态"}
    >
      <h3>{shot ? "机位视图" : "地点与状态"}</h3>
      <p>
        {shot
          ? (view?.name ?? "未绑定视图")
          : `${location?.name ?? "未绑定地点"} · ${location?.states.find((s) => s.id === scene.state_id)?.name ?? "基础状态"}`}
      </p>
      {shot && view ? (
        <LocationImage
          snapshot={props.snapshot}
          id={view.selected_asset_id}
          label="镜头已绑视图"
        />
      ) : null}
      <button
        className="secondary-button"
        disabled={
          props.busy ||
          !library.allowed_actions?.includes(shot ? "bind_shot" : "bind_scene")
        }
        onClick={() => {
          setLocationId(scene.location_id ?? "");
          setStateId(scene.state_id ?? "");
          setViewId(shot?.view_id ?? "");
          setRevision(props.snapshot.revision);
          setEditing(true);
        }}
      >
        改绑{shot ? "视图" : "地点与状态"}
      </button>
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void change.preview(
              shot
                ? patch(
                    [
                      {
                        op: "bind_shot",
                        shot_id: shot.id,
                        view_id: viewId || null,
                      },
                    ],
                    [],
                    [],
                    [shot.id],
                  )
                : patch(
                    [
                      {
                        op: "bind_scene",
                        scene_id: scene.id,
                        location_id: locationId || null,
                        state_id: stateId || null,
                      },
                    ],
                    [],
                    [scene.id],
                  ),
              () => setEditing(false),
              revision,
            );
          }}
        >
          {shot ? (
            <label>
              视图
              <select
                aria-label="镜头视图"
                value={viewId}
                onChange={(e) => setViewId(e.target.value)}
              >
                <option value="">不绑定</option>
                {location?.views.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              <label>
                地点
                <select
                  aria-label="场景地点"
                  value={locationId}
                  onChange={(e) => {
                    setLocationId(e.target.value);
                    setStateId("");
                  }}
                >
                  <option value="">不绑定</option>
                  {library.locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                状态
                <select
                  aria-label="场景地点状态"
                  value={stateId}
                  onChange={(e) => setStateId(e.target.value)}
                >
                  <option value="">基础状态</option>
                  {draftLocation?.states.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <button
            className="secondary-button"
            type="submit"
            disabled={props.busy || change.working}
          >
            预览改绑影响
          </button>
          <button
            className="secondary-button"
            type="button"
            onClick={() => setEditing(false)}
          >
            取消
          </button>
        </form>
      ) : null}
      {change.dialog}
    </section>
  );
}
