import { useState } from "react";
import { createPortal } from "react-dom";
import type { Location, LocationImage, Scene, StructuredDirectorSnapshot } from "../api";
import type { LocationChange, LocationOperation } from "../api/location";
import type { WorkspaceFlatProps } from "./contracts";
import {
  assetById,
  GenerationCandidateList,
  MultiImageAssetPickerDialog,
  ZoomableImage,
} from "./shared";
import { PanoramaCameraEditor, type CameraView } from "./PanoramaCameraEditor";
import "./location.css";

type Props = Pick<
  WorkspaceFlatProps,
  | "snapshot"
  | "busy"
  | "onPreviewLocationChange"
  | "onApplyLocationChange"
  | "onGenerateLocationImage"
  | "onCaptureLocationPanorama"
  | "onCancelGeneration"
  | "onDismissGeneration"
>;

function change(
  operations: LocationOperation[],
  locationIds: string[] = [],
  sceneIds: string[] = [],
): LocationChange {
  return {
    name: "location.apply_operations",
    arguments: { scope: { location_ids: locationIds, scene_ids: sceneIds }, operations },
  };
}

function localKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
}

async function apply(props: Props, value: LocationChange) {
  if (!props.onApplyLocationChange) return false;
  if (props.onPreviewLocationChange) {
    const impact = await props.onPreviewLocationChange(value, props.snapshot.revision);
    if (impact.high_impact && !window.confirm("这次修改会影响已有内容，是否继续？")) return false;
  }
  return props.onApplyLocationChange(value, props.snapshot.revision);
}

function ImagePreview({ snapshot, image }: { snapshot: StructuredDirectorSnapshot; image: LocationImage }) {
  const asset = image.selected_asset_id ? assetById(snapshot.assets, image.selected_asset_id) : null;
  return (
    <div
      className={`${image.kind === "panorama" ? "location-panorama" : "location-image"}${asset ? "" : " is-empty"}`}
      style={image.kind === "panorama" ? undefined : { aspectRatio: snapshot.aspect_ratio.replace(":", " / ") }}
    >
      {asset ? <ZoomableImage src={asset.content_url} alt={image.name} /> : <p className="location-image-empty">尚未选择图片</p>}
    </div>
  );
}

function ImageCard({ props, location, image }: { props: Props; location: Location; image: LocationImage }) {
  const production = image.production;
  const candidates = props.snapshot.generations.filter((item) =>
    production?.candidate_generation_ids.includes(item.id),
  );
  const active = props.snapshot.generations.find((item) => item.id === production?.active_generation_id);
  const can = (action: string) => production?.allowed_actions.includes(action as never) ?? false;
  const [editing, setEditing] = useState(false);

  return (
    <article className="location-view-card">
      <header className="location-card-header">
        <div>
          <p className="eyebrow">{image.kind === "panorama" ? "全景图" : image.source ? "全景取景" : "地点图片"}</p>
          <h4>{image.name}</h4>
        </div>
        {production ? <span className="location-status">{production.status_label}</span> : null}
      </header>
      <ImagePreview snapshot={props.snapshot} image={image} />
      <p className="location-view-purpose">{image.description}</p>
      {image.source ? <p className="location-production-reason">来源：全景取景（{image.source.yaw_deg}° / {image.source.pitch_deg}° / {image.source.hfov_deg}°）</p> : null}
      <div className="location-inline-actions">
        {can("generate") && image.source === null ? <button disabled={props.busy} onClick={() => props.onGenerateLocationImage?.(image.id)}>{production?.generate_label ?? "生成图片"}</button> : null}
        {can("preview_panorama") ? <PanoramaDialog props={props} image={image} /> : null}
        {can("edit") ? <button className="secondary-button" onClick={() => setEditing(true)}>编辑</button> : null}
        {can("clear_selection") ? <button className="secondary-button" onClick={() => void apply(props, change([{ op: "clear_image_selection", image_id: image.id }], [location.id]))}>清除选择</button> : null}
        {can("delete") ? <button className="delete-button" onClick={() => void apply(props, change([{ op: "delete_image", image_id: image.id }], [location.id]))}>删除</button> : null}
      </div>
      {editing ? <ImageEditorDialog props={props} location={location} image={image} onClose={() => setEditing(false)} /> : null}
      {production ? (
        <GenerationCandidateList
          kind="location"
          target={image.id}
          assets={props.snapshot.assets}
          candidates={candidates}
          active={active}
          busy={props.busy}
          summary={`图片候选（${candidates.length}）`}
          workingText="正在生成"
          onSelect={(generation) => generation.output_asset_id && void apply(props, { name: "location.select_image", arguments: { image_id: image.id, asset_id: generation.output_asset_id } })}
          selectDisabled={(generation) => !production.selectable_generation_ids.includes(generation.id)}
          isSelected={(_generation, asset) => asset?.id === image.selected_asset_id}
          renderCandidate={(_generation, asset) => asset ? <div className={image.kind === "panorama" ? "location-panorama" : "location-image"}><ZoomableImage src={asset.content_url} alt="地点图片候选" /></div> : null}
          onDismiss={props.onDismissGeneration}
          dismissAllowed={(generation) => generation.allowed_actions.includes("dismiss_history")}
        />
      ) : null}
      {active?.allowed_actions.includes("cancel") ? <button className="secondary-button" onClick={() => props.onCancelGeneration(active.id)}>取消生成</button> : null}
    </article>
  );
}

function ImageEditorDialog({
  props,
  location,
  image,
  onClose,
}: {
  props: Props;
  location: Location;
  image: LocationImage;
  onClose: () => void;
}) {
  const [name, setName] = useState(image.name);
  const [description, setDescription] = useState(image.description);
  const [promptText, setPromptText] = useState(image.prompt_text);
  const [references, setReferences] = useState(image.reference_asset_ids);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const imageAssets = props.snapshot.assets.filter((asset) => asset.media_type.startsWith("image/"));
  const referenceAssets = references
    .map((assetId) => assetById(props.snapshot.assets, assetId))
    .filter((asset) => asset !== null);

  async function save() {
    if (!name.trim() || !description.trim()) return;
    const ok = await apply(
      props,
      change(
        [{
          op: "update_image",
          image_id: image.id,
          fields: {
            name,
            description,
            prompt_text: promptText,
            reference_asset_ids: references,
          },
        }],
        [location.id],
      ),
    );
    if (ok) onClose();
  }

  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="scene-asset-picker-dialog location-image-editor-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`编辑地点图片：${image.name}`}
        onKeyDown={(event) => {
          if (event.key === "Escape" && !assetPickerOpen) onClose();
        }}
      >
        <header>
          <div>
            <p className="eyebrow">Location image</p>
            <h2>编辑地点图片</h2>
            <span>{image.kind === "panorama" ? "2:1 全景图" : "普通图片"}</span>
          </div>
          <button autoFocus type="button" className="secondary-button" onClick={onClose}>关闭</button>
        </header>
        <div className="location-image-editor-scroll">
          <div className="location-image-editor-form">
            <label>名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>画面说明（必填）<textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <label>生成提示词<textarea rows={8} value={promptText} onChange={(event) => setPromptText(event.target.value)} /></label>
          </div>
          <section className="location-reference-editor" aria-label="参考图片">
            <header>
              <div>
                <h3>参考图片</h3>
                <p>从项目资产库选择，最多 5 张；生成时按当前顺序提交。</p>
              </div>
              <button type="button" className="secondary-button" disabled={props.busy} onClick={() => setAssetPickerOpen(true)}>
                从资产库选择参考图
              </button>
            </header>
            {referenceAssets.length === 0 ? <p className="muted-copy">尚未选择参考图片。</p> : (
              <div className="location-reference-preview-grid">
                {referenceAssets.map((asset, index) => {
                  const assetName = asset.display_name ?? `参考图 ${index + 1}`;
                  return (
                    <article key={asset.id}>
                      <ZoomableImage src={asset.content_url} alt={assetName} />
                      <div>
                        <span>{index + 1}. {assetName}</span>
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={props.busy}
                          aria-label={`移除参考图 ${assetName}`}
                          onClick={() => setReferences(references.filter((assetId) => assetId !== asset.id))}
                        >移除</button>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
        <footer className="location-image-editor-actions">
          <span>{references.length} / 5 张参考图</span>
          <button type="button" className="secondary-button" onClick={onClose}>取消</button>
          <button type="button" disabled={props.busy || !name.trim() || !description.trim()} onClick={() => void save()}>保存修改</button>
        </footer>
        {assetPickerOpen ? (
          <MultiImageAssetPickerDialog
            title="选择地点图片参考图"
            ariaLabel="从资产库选择地点图片参考图"
            assets={imageAssets}
            selectedAssetIds={references}
            maxSelected={5}
            busy={props.busy}
            onClose={() => setAssetPickerOpen(false)}
            onChange={setReferences}
          />
        ) : null}
      </section>
    </div>,
    document.body,
  );
}

function PanoramaDialog({ props, image }: { props: Props; image: LocationImage }) {
  const [open, setOpen] = useState(false);
  const [camera, setCamera] = useState<CameraView>({ yawDeg: 0, pitchDeg: 0, hfovDeg: 65 });
  const [name, setName] = useState("新视角");
  const [description, setDescription] = useState("");
  const asset = image.selected_asset_id ? assetById(props.snapshot.assets, image.selected_asset_id) : null;
  if (!asset) return null;
  return (
    <>
      <button onClick={() => setOpen(true)}>3D 预览</button>
      {open ? (
        <div className="scene-asset-picker-backdrop">
          <section className="scene-asset-picker-dialog location-panorama-dialog" role="dialog" aria-modal="true" aria-label="全景图 3D 预览">
            <header><h3>{image.name}</h3><button className="secondary-button" onClick={() => setOpen(false)}>关闭</button></header>
            <PanoramaCameraEditor panoramaUrl={asset.content_url} aspectRatio={props.snapshot.aspect_ratio} view={camera} onChange={setCamera} />
            <label>子图名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>子图画面说明（必填）<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <button
              disabled={props.busy || !name.trim() || !description.trim()}
              onClick={() => {
                props.onCaptureLocationPanorama?.(image.id, name.trim(), description.trim(), camera.yawDeg, camera.pitchDeg, camera.hfovDeg);
                setOpen(false);
              }}
            >生成这个视角的子图</button>
          </section>
        </div>
      ) : null}
    </>
  );
}

function NewImage({ props, location }: { props: Props; location: Location }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"image" | "panorama">("image");
  const [description, setDescription] = useState("");
  const [promptText, setPromptText] = useState("");
  return open ? (
    <div className="location-editor-form">
      <label>名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label>类别<select value={kind} onChange={(event) => setKind(event.target.value as "image" | "panorama")}><option value="image">普通图片</option><option value="panorama">2:1 全景图</option></select></label>
      <label>画面说明（必填）<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      <label>生成提示词<textarea value={promptText} onChange={(event) => setPromptText(event.target.value)} /></label>
      <div className="location-inline-actions">
        <button disabled={!name.trim() || !description.trim()} onClick={() => void apply(props, change([{ op: "create_image", location_id: location.id, key: localKey("image"), fields: { name, kind, description, prompt_text: promptText, reference_asset_ids: [], source: null } }], [location.id])).then((ok) => ok && setOpen(false))}>创建图片条目</button>
        <button className="secondary-button" onClick={() => setOpen(false)}>取消</button>
      </div>
    </div>
  ) : <button onClick={() => setOpen(true)}>添加图片</button>;
}

function NewLocationDialog({ props, onClose }: { props: Props; onClose: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return createPortal(
    <div
      className="scene-asset-picker-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="scene-asset-picker-dialog location-create-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="添加地点"
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
        }}
      >
        <header>
          <div><p className="eyebrow">New location</p><h2>添加地点</h2></div>
          <button autoFocus type="button" className="secondary-button" onClick={onClose}>关闭</button>
        </header>
        <div className="location-image-editor-scroll">
          <div className="location-image-editor-form">
            <label>地点名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>地点说明<textarea rows={7} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          </div>
        </div>
        <footer className="location-image-editor-actions">
          <button type="button" className="secondary-button" onClick={onClose}>取消</button>
          <button
            type="button"
            disabled={props.busy || !name.trim()}
            onClick={() => void apply(
              props,
              change([{ op: "create_location", key: localKey("location"), name, description }]),
            ).then((ok) => ok && onClose())}
          >创建地点</button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}

function LocationOverviewCard({
  snapshot,
  location,
  onOpen,
}: {
  snapshot: StructuredDirectorSnapshot;
  location: Location;
  onOpen: () => void;
}) {
  const coverImage = location.images.find((image) => image.selected_asset_id !== null);
  const coverAsset = coverImage?.selected_asset_id
    ? assetById(snapshot.assets, coverImage.selected_asset_id)
    : null;
  return (
    <button type="button" className="location-overview-card" onClick={onOpen}>
      <span className="location-overview-cover">
        {coverAsset ? <img src={coverAsset.content_url} alt="" /> : <span>尚无已选地点图片</span>}
      </span>
      <span className="location-overview-content">
        <strong>{location.name}</strong>
        <span>{location.description || "暂无地点说明"}</span>
        <small>{location.images.length} 张图片 · {location.states.length} 个状态</small>
      </span>
      <span className="location-overview-enter">查看地点</span>
    </button>
  );
}

export function LocationLibrary(props: Props) {
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [creatingLocation, setCreatingLocation] = useState(false);
  const selectedLocation = props.snapshot.location_library.locations.find(
    (location) => location.id === selectedLocationId,
  ) ?? null;

  if (selectedLocation) {
    return (
      <section className="location-library-shell">
        <header className="location-detail-navigation">
          <button type="button" className="secondary-button" onClick={() => setSelectedLocationId(null)}>← 返回地点列表</button>
          <div>
            <p className="eyebrow">Location detail</p>
            <h2>{selectedLocation.name}</h2>
            <p>{selectedLocation.description || "暂无地点说明"}</p>
          </div>
        </header>
        <div className="location-detail-summary">
          <span>{selectedLocation.images.length} 张图片</span>
          <span>{selectedLocation.states.length} 个状态</span>
          <span>{selectedLocation.fixtures.length} 项固定陈设</span>
        </div>
        <div className="location-inline-actions">
          <NewImage props={props} location={selectedLocation} />
          {selectedLocation.allowed_actions?.includes("delete") ? (
            <button
              className="delete-button"
              onClick={() => void apply(
                props,
                change([{ op: "delete_location", location_id: selectedLocation.id }], [selectedLocation.id]),
              ).then((ok) => ok && setSelectedLocationId(null))}
            >删除地点</button>
          ) : null}
        </div>
        {selectedLocation.images.length === 0 ? <p className="location-library-empty">这个地点还没有图片。</p> : (
          <div className="location-view-grid">
            {selectedLocation.images.map((image) => (
              <ImageCard key={image.id} props={props} location={selectedLocation} image={image} />
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="location-library-shell">
      <header className="location-library-header">
        <div><p className="eyebrow">Location Library</p><h2>地点库</h2><p>先选择地点，再查看其中的空间说明、状态与独立图片。</p></div>
        {props.snapshot.location_library.allowed_actions?.includes("create_location") ? (
          <button type="button" onClick={() => setCreatingLocation(true)}>添加地点</button>
        ) : null}
      </header>
      {props.snapshot.location_library.locations.length === 0 ? <p className="location-library-empty">项目中还没有地点。</p> : (
        <div className="location-overview-grid">
          {props.snapshot.location_library.locations.map((location) => (
            <LocationOverviewCard
              key={location.id}
              snapshot={props.snapshot}
              location={location}
              onOpen={() => setSelectedLocationId(location.id)}
            />
          ))}
        </div>
      )}
      {creatingLocation ? <NewLocationDialog props={props} onClose={() => setCreatingLocation(false)} /> : null}
    </section>
  );
}

export function LocationBinding(props: Props & { scene: Scene; shot?: unknown }) {
  const { scene } = props;
  const location = props.snapshot.location_library.locations.find((item) => item.id === scene.location_id);
  return (
    <div className="location-binding">
      <label>Scene 地点（仅语义关系）
        <select value={scene.location_id ?? ""} onChange={(event) => void apply(props, change([{ op: "bind_scene", scene_id: scene.id, location_id: event.target.value || null, state_id: null }], event.target.value ? [event.target.value] : [], [scene.id]))}>
          <option value="">不指定</option>
          {props.snapshot.location_library.locations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {location ? <label>状态<select value={scene.state_id ?? ""} onChange={(event) => void apply(props, change([{ op: "bind_scene", scene_id: scene.id, location_id: location.id, state_id: event.target.value || null }], [location.id], [scene.id]))}><option value="">常态</option>{location.states.map((state) => <option key={state.id} value={state.id}>{state.name}</option>)}</select></label> : null}
    </div>
  );
}
