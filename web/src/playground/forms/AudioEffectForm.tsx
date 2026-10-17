import {
  AssetSlot,
  Field,
  NullableNumberField,
  SeedField,
  SelectField,
  asAssetId,
  asNumber,
  asString,
  numberOrZero,
  type CapabilityFormProps,
} from "./common";
import { AUDIO_EFFECT_PRESETS } from "./parameters";

export function AudioEffectForm({
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
      <SelectField
        label="Preset"
        wireKey="preset"
        value={asString(values.preset, "weak_signal")}
        disabled={disabled}
        options={AUDIO_EFFECT_PRESETS}
        onChange={(preset) => onChange({ ...values, preset })}
      />
      <Field label="强度" wireKey="strength" hint="0–1">
        <input
          type="number"
          aria-label="强度"
          min={0}
          max={1}
          step={0.05}
          value={String(asNumber(values.strength, 0.7))}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...values, strength: numberOrZero(event.target.value) })
          }
        />
      </Field>
      <SeedField
        value={asNumber(values.seed, 42)}
        disabled={disabled}
        onChange={(seed) => onChange({ ...values, seed })}
      />
      <NullableNumberField
        label="处理起点（秒）"
        wireKey="start_seconds"
        value={typeof values.start_seconds === "number" ? values.start_seconds : null}
        disabled={disabled}
        onChange={(start_seconds) => onChange({ ...values, start_seconds })}
      />
      <NullableNumberField
        label="处理终点（秒）"
        wireKey="end_seconds"
        value={typeof values.end_seconds === "number" ? values.end_seconds : null}
        disabled={disabled}
        onChange={(end_seconds) => onChange({ ...values, end_seconds })}
      />
    </div>
  );
}
