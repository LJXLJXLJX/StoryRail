import { useState } from "react";
import type { Location, LocationImage, Scene, StructuredDirectorSnapshot } from "../api";
import type { LocationChange, LocationOperation } from "../api/location";
import type { WorkspaceFlatProps } from "./contracts";
import { assetById, GenerationCandidateList, ZoomableImage } from "./shared";
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
  const [name, setName] = useState(image.name);
  const [description, setDescription] = useState(image.description);
  const [promptText, setPromptText] = useState(image.prompt_text);
  const [references, setReferences] = useState(image.reference_asset_ids);
  const imageAssets = props.snapshot.assets.filter((asset) => asset.media_type.startsWith("image/"));

  async function save() {
    if (!description.trim()) return;
    const ok = await apply(
      props,
      change(
        [{ op: "update_image", image_id: image.id, fields: { name, description, prompt_text: promptText, reference_asset_ids: references } }],
        [location.id],
      ),
    );
    if (ok) setEditing(false);
  }

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
        {can("edit") ? <button className="secondary-button" onClick={() => setEditing((value) => !value)}>编辑</button> : null}
        {can("clear_selection") ? <button className="secondary-button" onClick={() => void apply(props, change([{ op: "clear_image_selection", image_id: image.id }], [location.id]))}>清除选择</button> : null}
        {can("delete") ? <button className="delete-button" onClick={() => void apply(props, change([{ op: "delete_image", image_id: image.id }], [location.id]))}>删除</button> : null}
      </div>
      {editing ? (
        <div className="location-editor-form">
          <label>名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>画面说明（必填）<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <label>生成提示词<textarea value={promptText} onChange={(event) => setPromptText(event.target.value)} /></label>
          <fieldset>
            <legend>任意参考图片（最多 5 张）</legend>
            {imageAssets.map((asset) => (
              <label key={asset.id}>
                <input
                  type="checkbox"
                  checked={references.includes(asset.id)}
                  disabled={!references.includes(asset.id) && references.length >= 5}
                  onChange={(event) => setReferences(event.target.checked ? [...references, asset.id] : references.filter((id) => id !== asset.id))}
                />
                {asset.display_name ?? asset.id.slice(0, 8)}
              </label>
            ))}
          </fieldset>
          <button disabled={!name.trim() || !description.trim()} onClick={() => void save()}>保存</button>
        </div>
      ) : null}
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

export function LocationLibrary(props: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <section className="location-library-shell">
      <header className="location-library-header"><div><p className="eyebrow">Location Library</p><h2>地点库</h2><p>地点保存空间语义；图片彼此独立，全景图只是可进入 3D 预览并取景的特殊类别。</p></div></header>
      {props.snapshot.location_library.allowed_actions?.includes("create_location") ? (
        <div className="location-editor-form">
          <label>新地点名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>地点说明<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <button disabled={!name.trim()} onClick={() => void apply(props, change([{ op: "create_location", key: localKey("location"), name, description }])).then((ok) => { if (ok) { setName(""); setDescription(""); } })}>创建地点</button>
        </div>
      ) : null}
      <div className="location-list">
        {props.snapshot.location_library.locations.map((location) => (
          <article key={location.id} className="location-detail">
            <header className="location-card-header"><div><h3>{location.name}</h3><p>{location.description || "暂无地点说明"}</p></div></header>
            <div className="location-inline-actions"><NewImage props={props} location={location} />{location.allowed_actions?.includes("delete") ? <button className="delete-button" onClick={() => void apply(props, change([{ op: "delete_location", location_id: location.id }], [location.id]))}>删除地点</button> : null}</div>
            <div className="location-view-grid">{location.images.map((image) => <ImageCard key={image.id} props={props} location={location} image={image} />)}</div>
          </article>
        ))}
      </div>
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
