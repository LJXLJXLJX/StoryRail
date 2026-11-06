import {
  AspectRatioField,
  AssetSlot,
  Field,
  asAssetId,
  asNumber,
  asString,
  numberOrZero,
  type CapabilityFormProps,
} from "./common";
import { PANO_HFOV_PRESETS, PANO_YAW_PRESETS } from "./parameters";

// 只有 Core 判定为 2:1 等距柱状全景（allowed_actions 含 pano_view）的 PNG/JPEG 才能选入。
const PANO_MEDIA_TYPES = ["image/png", "image/jpeg"];

function AngleField({
  label,
  wireKey,
  hint,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string;
  wireKey: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={label} wireKey={wireKey} hint={hint}>
      <input
        type="number"
        aria-label={label}
        min={min}
        max={max}
        step={0.5}
        value={String(value)}
        disabled={disabled}
        onChange={(event) => onChange(numberOrZero(event.target.value))}
      />
    </Field>
  );
}

export function PanoViewForm({
  values,
  onChange,
  disabled,
}: CapabilityFormProps) {
  const yaw = asNumber(values.yaw_deg, 0);
  const hfov = asNumber(values.hfov_deg, 90);
  return (
    <div className="playground-form">
      <AssetSlot
        label="全景"
        wireKey="image_asset_id"
        assetId={asAssetId(values.image_asset_id)}
        kind="image"
        mediaTypes={PANO_MEDIA_TYPES}
        requiredAction="pano_view"
        disabled={disabled}
        onChange={(image_asset_id) => onChange({ ...values, image_asset_id })}
      />
      <Field label="常用朝向" wireKey="yaw_deg" hint="一次只裁一个视图">
        <div className="playground-seed-row">
          {PANO_YAW_PRESETS.map((preset) => (
            <button
              key={preset.yaw}
              type="button"
              className="secondary-button"
              aria-pressed={yaw === preset.yaw}
              disabled={disabled}
              onClick={() => onChange({ ...values, yaw_deg: preset.yaw })}
            >
              {preset.label} {preset.yaw}°
            </button>
          ))}
        </div>
      </Field>
      <AngleField
        label="水平朝向 yaw"
        wireKey="yaw_deg"
        hint="0 ≤ yaw < 360，全景正中为 0，顺时针为正"
        value={yaw}
        min={0}
        max={359.5}
        disabled={disabled}
        onChange={(yaw_deg) => onChange({ ...values, yaw_deg })}
      />
      <AngleField
        label="俯仰 pitch"
        wireKey="pitch_deg"
        hint="-60 到 60，抬头为正"
        value={asNumber(values.pitch_deg, 0)}
        min={-60}
        max={60}
        disabled={disabled}
        onChange={(pitch_deg) => onChange({ ...values, pitch_deg })}
      />
      <Field label="常用视场角" wireKey="hfov_deg">
        <div className="playground-seed-row">
          {PANO_HFOV_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className="secondary-button"
              aria-pressed={hfov === preset}
              disabled={disabled}
              onClick={() => onChange({ ...values, hfov_deg: preset })}
            >
              hfov {preset}°
            </button>
          ))}
        </div>
      </Field>
      <AngleField
        label="水平视场角 hfov"
        wireKey="hfov_deg"
        hint="20 到 120"
        value={hfov}
        min={20}
        max={120}
        disabled={disabled}
        onChange={(hfov_deg) => onChange({ ...values, hfov_deg })}
      />
      <AspectRatioField
        value={asString(values.aspect_ratio, "16:9")}
        disabled={disabled}
        onChange={(aspect_ratio) => onChange({ ...values, aspect_ratio })}
      />
    </div>
  );
}
