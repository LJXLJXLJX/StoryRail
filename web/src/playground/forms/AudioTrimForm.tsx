import {
  AssetSlot,
  Field,
  asAssetId,
  asNumber,
  numberOrZero,
  type CapabilityFormProps,
} from "./common";

export function AudioTrimForm({
  values,
  onChange,
  disabled,
}: CapabilityFormProps) {
  return (
    <div className="playground-form">
      <AssetSlot
        label="音频"
        wireKey="audio_asset_id"
        assetId={asAssetId(values.audio_asset_id)}
        kind="audio"
        disabled={disabled}
        onChange={(audio_asset_id) => onChange({ ...values, audio_asset_id })}
      />
      <Field label="截取起点（秒）" wireKey="start_seconds">
        <input
          type="number"
          aria-label="截取起点（秒）"
          min={0}
          step={0.1}
          value={String(asNumber(values.start_seconds, 0))}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...values, start_seconds: numberOrZero(event.target.value) })
          }
        />
      </Field>
      <Field label="截取终点（秒）" wireKey="end_seconds">
        <input
          type="number"
          aria-label="截取终点（秒）"
          min={0}
          step={0.1}
          value={String(asNumber(values.end_seconds, 0))}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...values, end_seconds: numberOrZero(event.target.value) })
          }
        />
      </Field>
    </div>
  );
}
