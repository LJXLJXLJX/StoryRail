import {
  AssetSlot,
  Field,
  NullableNumberField,
  asAssetId,
  asNumber,
  numberOrZero,
  type CapabilityFormProps,
} from "./common";

export function AudioRemixForm({
  values,
  onChange,
  disabled,
}: CapabilityFormProps) {
  return (
    <div className="playground-form">
      <AssetSlot
        label="视频"
        wireKey="video_asset_id"
        assetId={asAssetId(values.video_asset_id)}
        kind="video"
        disabled={disabled}
        onChange={(video_asset_id) => onChange({ ...values, video_asset_id })}
      />
      <AssetSlot
        label="人声"
        wireKey="voice_asset_id"
        assetId={asAssetId(values.voice_asset_id)}
        kind="audio"
        disabled={disabled}
        onChange={(voice_asset_id) => onChange({ ...values, voice_asset_id })}
      />
      <AssetSlot
        label="背景声"
        wireKey="background_asset_id"
        assetId={asAssetId(values.background_asset_id)}
        kind="audio"
        disabled={disabled}
        onChange={(background_asset_id) =>
          onChange({ ...values, background_asset_id })
        }
      />
      <Field label="人声音量增益（dB）" wireKey="voice_gain_db" hint="-100–24">
        <input
          type="number"
          aria-label="人声音量增益（dB）"
          value={String(asNumber(values.voice_gain_db, 0))}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...values, voice_gain_db: numberOrZero(event.target.value) })
          }
        />
      </Field>
      <Field label="背景音量增益（dB）" wireKey="background_gain_db" hint="-100–24">
        <input
          type="number"
          aria-label="背景音量增益（dB）"
          value={String(asNumber(values.background_gain_db, -6))}
          disabled={disabled}
          onChange={(event) =>
            onChange({
              ...values,
              background_gain_db: numberOrZero(event.target.value),
            })
          }
        />
      </Field>
      <NullableNumberField
        label="人声增益起点（秒）"
        wireKey="voice_gain_start_seconds"
        value={typeof values.voice_gain_start_seconds === "number" ? values.voice_gain_start_seconds : null}
        disabled={disabled}
        onChange={(voice_gain_start_seconds) =>
          onChange({ ...values, voice_gain_start_seconds })
        }
      />
      <NullableNumberField
        label="人声增益终点（秒）"
        wireKey="voice_gain_end_seconds"
        value={typeof values.voice_gain_end_seconds === "number" ? values.voice_gain_end_seconds : null}
        disabled={disabled}
        onChange={(voice_gain_end_seconds) =>
          onChange({ ...values, voice_gain_end_seconds })
        }
      />
      <NullableNumberField
        label="背景增益起点（秒）"
        wireKey="background_gain_start_seconds"
        value={
          typeof values.background_gain_start_seconds === "number"
            ? values.background_gain_start_seconds
            : null
        }
        disabled={disabled}
        onChange={(background_gain_start_seconds) =>
          onChange({ ...values, background_gain_start_seconds })
        }
      />
      <NullableNumberField
        label="背景增益终点（秒）"
        wireKey="background_gain_end_seconds"
        value={
          typeof values.background_gain_end_seconds === "number"
            ? values.background_gain_end_seconds
            : null
        }
        disabled={disabled}
        onChange={(background_gain_end_seconds) =>
          onChange({ ...values, background_gain_end_seconds })
        }
      />
    </div>
  );
}
