import { createContext, useContext, type ReactNode } from "react";
import { ZoomableImage } from "../../ImagePreview";

import type {
  PlaygroundAsset,
  PlaygroundAssetAction,
  PlaygroundCapabilityId,
} from "../../api";

export type MediaKind = "image" | "audio" | "video";

export type AssetPickRequest = {
  mediaKind: MediaKind;
  onPick: (assetId: string) => void;
  mediaTypes?: string[];
  durationSeconds?: number[] | null;
  // 只列出 Core 在 allowed_actions 中授予该动作的资产（例如 2:1 全景才有 pano_view）。
  requiredAction?: PlaygroundAssetAction;
};

// 「作为输入」的槽位描述：单个 Asset 槽、纯 ID 列表槽或 Ref2VA 的描述列表槽。
export type SlotTarget = {
  capability: PlaygroundCapabilityId;
  key: string;
  label: string;
  list?: string;
  idList?: string;
  requiredAction?: PlaygroundAssetAction;
};

export type DescribedAsset = { asset_id: string | null; description: string };

export type CapabilityFormProps = {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  disabled: boolean;
};

export function assetMediaKind(
  mediaType: PlaygroundAsset["media_type"],
): MediaKind {
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("audio/")) return "audio";
  return "video";
}

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function asAssetId(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

/** 保留空槽位，供表单编辑；提交前由 completeParameters 过滤。 */
export function asMaybeIdList(value: unknown): Array<string | null> {
  return Array.isArray(value)
    ? value.map((item) =>
        typeof item === "string" && item.length > 0 ? item : null,
      )
    : [];
}

export function asDescribedAssets(value: unknown): DescribedAsset[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const record =
      typeof item === "object" && item !== null && !Array.isArray(item)
        ? (item as Record<string, unknown>)
        : {};
    return {
      asset_id: asAssetId(record.asset_id),
      description: asString(record.description),
    };
  });
}

export function numberOrZero(raw: string): number {
  const value = Number(raw);
  return Number.isFinite(value) ? value : 0;
}

export function numberOrNull(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

const FormContext = createContext<{
  assets: PlaygroundAsset[];
  requestAsset: (request: AssetPickRequest) => void;
  disabled: boolean;
} | null>(null);

export function FormProvider({
  assets,
  requestAsset,
  disabled,
  children,
}: {
  assets: PlaygroundAsset[];
  requestAsset: (request: AssetPickRequest) => void;
  disabled: boolean;
  children: ReactNode;
}) {
  return (
    <FormContext.Provider value={{ assets, requestAsset, disabled }}>
      {children}
    </FormContext.Provider>
  );
}

export function useFormContext() {
  const value = useContext(FormContext);
  if (value === null) throw new Error("表单字段必须放在 RunForm 内。");
  return value;
}

export function Field({
  label,
  wireKey,
  hint,
  children,
}: {
  label: string;
  wireKey: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="playground-field">
      <span className="playground-field-label">{label}</span>
      {children}
      <span className="playground-wire-key">{wireKey}</span>
      {hint === undefined ? null : (
        <span className="playground-hint">{hint}</span>
      )}
    </div>
  );
}

export function TextField({
  label,
  wireKey,
  value,
  onChange,
  multiline = false,
  disabled = false,
  placeholder,
}: {
  label: string;
  wireKey: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <Field label={label} wireKey={wireKey}>
      {multiline ? (
        <textarea
          aria-label={label}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          type="text"
          aria-label={label}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}

export function NullableTextField({
  label,
  wireKey,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  wireKey: string;
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}) {
  return (
    <TextField
      label={label}
      wireKey={wireKey}
      value={value ?? ""}
      disabled={disabled}
      onChange={(raw) => onChange(raw.trim() === "" ? null : raw)}
    />
  );
}

export function SelectField({
  label,
  wireKey,
  value,
  options,
  onChange,
  disabled = false,
}: {
  label: string;
  wireKey: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <Field label={label} wireKey={wireKey}>
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function SeedField({
  value,
  onChange,
  disabled = false,
  label = "随机种子",
  wireKey = "seed",
}: {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  label?: string;
  wireKey?: string;
}) {
  return (
    <Field label={label} wireKey={wireKey}>
      <div className="playground-seed-row">
        <input
          type="number"
          aria-label={label}
          min={0}
          value={String(value)}
          disabled={disabled}
          onChange={(event) => onChange(numberOrZero(event.target.value))}
        />
        <button
          type="button"
          className="secondary-button"
          disabled={disabled}
          onClick={() => onChange(Math.floor(Math.random() * 2 ** 31))}
        >
          随机
        </button>
      </div>
    </Field>
  );
}

export function AspectRatioField({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <SelectField
      label="画面比例"
      wireKey="aspect_ratio"
      value={value}
      disabled={disabled}
      options={[
        { value: "16:9", label: "16:9 横屏" },
        { value: "9:16", label: "9:16 竖屏" },
        { value: "2:1", label: "2:1 宽银幕" },
      ]}
      onChange={onChange}
    />
  );
}

export function DurationField({
  value,
  onChange,
  disabled = false,
}: {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <Field
      label="时长（秒）"
      wireKey="duration_seconds"
      hint="≥ 0.2；超过 15 秒可能 OOM"
    >
      <input
        type="number"
        aria-label="时长（秒）"
        min={0.2}
        step={0.1}
        value={String(value)}
        disabled={disabled}
        onChange={(event) => onChange(numberOrZero(event.target.value))}
      />
    </Field>
  );
}

export function NullableNumberField({
  label,
  wireKey,
  value,
  onChange,
  disabled = false,
  step,
}: {
  label: string;
  wireKey: string;
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
  step?: number;
}) {
  return (
    <Field label={label} wireKey={wireKey} hint="可留空">
      <input
        type="number"
        aria-label={label}
        step={step}
        value={value === null ? "" : String(value)}
        disabled={disabled}
        onChange={(event) => onChange(numberOrNull(event.target.value))}
      />
    </Field>
  );
}

export function AssetSlot({
  label,
  wireKey,
  assetId,
  kind,
  onChange,
  disabled = false,
  mediaTypes,
  durationSeconds,
  requiredAction,
}: {
  label: string;
  wireKey: string;
  assetId: string | null;
  kind: MediaKind;
  onChange: (assetId: string | null) => void;
  disabled?: boolean;
  mediaTypes?: string[];
  durationSeconds?: number[] | null;
  requiredAction?: PlaygroundAssetAction;
}) {
  const { assets, requestAsset } = useFormContext();
  const asset =
    assetId === null
      ? null
      : (assets.find((item) => item.id === assetId) ?? null);
  return (
    <Field label={label} wireKey={wireKey}>
      <div className="playground-asset-slot">
        {asset !== null && kind === "image" ? (
          <ZoomableImage src={asset.content_url} alt={`${label}缩略图`} />
        ) : null}
        <div className="playground-slot-body">
          <span className="playground-slot-name">
            {asset !== null
              ? asset.display_name
              : assetId === null
                ? "未选择"
                : "已删除素材"}
          </span>
          <span className="playground-slot-kind">
            {asset !== null ? asset.media_type : kind}
          </span>
        </div>
        <div className="playground-slot-actions">
          <button
            type="button"
            className="secondary-button"
            aria-label={`从资产选择（${label}）`}
            disabled={disabled}
            onClick={() =>
              requestAsset({
                mediaKind: kind,
                mediaTypes,
                durationSeconds,
                requiredAction,
                onPick: (picked) => onChange(picked),
              })
            }
          >
            从资产选择
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-label={`清除（${label}）`}
            disabled={disabled || assetId === null}
            onClick={() => onChange(null)}
          >
            清除
          </button>
        </div>
      </div>
    </Field>
  );
}

export function AssetIdList({
  label,
  wireKey,
  items,
  kind,
  maximum,
  onChange,
  disabled = false,
  mediaTypes,
  durationSeconds,
}: {
  label: string;
  wireKey: string;
  items: Array<string | null>;
  kind: MediaKind;
  maximum: number;
  onChange: (items: Array<string | null>) => void;
  disabled?: boolean;
  mediaTypes?: string[];
  durationSeconds?: number[] | null;
}) {
  return (
    <Field label={label} wireKey={wireKey} hint={`最多 ${maximum} 张`}>
      <div className="playground-described-list">
        {items.map((assetId, index) => (
          <AssetSlot
            key={`${wireKey}-${index}`}
            label={`${label} ${index + 1}`}
            wireKey={`${wireKey}[${index}]`}
            assetId={assetId}
            kind={kind}
            mediaTypes={mediaTypes}
            durationSeconds={durationSeconds}
            disabled={disabled}
            onChange={(picked) => {
              if (picked === null) {
                onChange(items.filter((_, position) => position !== index));
                return;
              }
              onChange(
                items.map((entry, position) =>
                  position === index ? picked : entry,
                ),
              );
            }}
          />
        ))}
        <button
          type="button"
          className="secondary-button"
          disabled={disabled || items.length >= maximum}
          onClick={() => onChange([...items, null])}
        >
          添加{label}
        </button>
      </div>
    </Field>
  );
}

export function DescribedAssetList({
  label,
  wireKey,
  items,
  kind,
  maximum,
  onChange,
  describe = "required",
  disabled = false,
  mediaTypes,
  durationSeconds,
}: {
  label: string;
  wireKey: string;
  items: DescribedAsset[];
  kind: MediaKind;
  maximum: number;
  onChange: (items: DescribedAsset[]) => void;
  describe?: "required" | "optional";
  disabled?: boolean;
  mediaTypes?: string[];
  durationSeconds?: number[] | null;
}) {
  return (
    <Field
      label={label}
      wireKey={wireKey}
      hint={`最多 ${maximum} 项${describe === "required" ? "，每项必填说明" : ""}`}
    >
      <div className="playground-described-list">
        {items.map((item, index) => (
          <div className="playground-described-row" key={`${wireKey}-${index}`}>
            <AssetSlot
              label={`${label} ${index + 1}`}
              wireKey={`${wireKey}[${index}].asset_id`}
              assetId={item.asset_id}
              kind={kind}
              mediaTypes={mediaTypes}
              durationSeconds={durationSeconds}
              disabled={disabled}
              onChange={(picked) => {
                if (picked === null) {
                  onChange(items.filter((_, position) => position !== index));
                  return;
                }
                onChange(
                  items.map((entry, position) =>
                    position === index ? { ...entry, asset_id: picked } : entry,
                  ),
                );
              }}
            />
            <input
              type="text"
              maxLength={2000}
              aria-label={`${label} ${index + 1} 说明`}
              placeholder={describe === "required" ? "必填说明" : "可选说明"}
              value={item.description}
              disabled={disabled}
              onChange={(event) =>
                onChange(
                  items.map((entry, position) =>
                    position === index
                      ? { ...entry, description: event.target.value }
                      : entry,
                  ),
                )
              }
            />
            <button
              type="button"
              className="delete-button"
              disabled={disabled}
              onClick={() =>
                onChange(items.filter((_, position) => position !== index))
              }
            >
              删除
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary-button"
          disabled={disabled || items.length >= maximum}
          onClick={() =>
            onChange([...items, { asset_id: null, description: "" }])
          }
        >
          添加{label}
        </button>
      </div>
    </Field>
  );
}
