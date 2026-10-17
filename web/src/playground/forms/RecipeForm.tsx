import type { ManifestRecipe, PlaygroundRecipePreview } from "../../api";
import {
  SettingField,
  type SettingValue,
} from "../../provider_settings/SettingField";
import {
  SeedField,
  asNumber,
  AssetSlot,
  AssetIdList,
  DescribedAssetList,
  asAssetId,
  asMaybeIdList,
  asDescribedAssets,
  Field,
  type CapabilityFormProps,
  type MediaKind,
} from "./common";

export function slotWireKey(slot: ManifestRecipe["slots"][number]) {
  return slot.describe !== "none"
    ? slot.key
    : `${slot.key}_asset_id${slot.maximum === 1 ? "" : "s"}`;
}

export function recipeDefaults(
  recipe: ManifestRecipe,
): Record<string, unknown> {
  return Object.fromEntries([
    ...recipe.slots.map((slot) => [
      slotWireKey(slot),
      slot.describe === "none" && slot.maximum === 1 ? null : [],
    ]),
    ...recipe.params.map((field) => [field.key, field.default]),
  ]);
}

export function RecipeForm({
  recipe,
  preview,
  values,
  onChange,
  disabled,
}: CapabilityFormProps & {
  recipe: ManifestRecipe;
  preview?: PlaygroundRecipePreview | null;
}) {
  const renderField = (field: ManifestRecipe["params"][number]) => (
    <div key={field.key}>
      {field.widget === "seed" ? (
        <SeedField
          label={field.label}
          wireKey={field.key}
          disabled={disabled}
          value={asNumber(values[field.key], Number(field.default))}
          onChange={(value) => onChange({ ...values, [field.key]: value })}
        />
      ) : (
        <SettingField
          field={field}
          disabled={disabled}
          value={(values[field.key] ?? field.default) as SettingValue}
          onChange={(value) => onChange({ ...values, [field.key]: value })}
        />
      )}
      {field.help ? <small>{field.help}</small> : null}
    </div>
  );
  return (
    <div className="playground-form">
      {recipe.params.filter((field) => !field.advanced).map(renderField)}
      {recipe.slots.map((slot) => {
        const key = slotWireKey(slot);
        const kind = (slot.media_types[0]?.split("/")[0] ??
          "image") as MediaKind;
        const common = {
          label: slot.label,
          wireKey: key,
          kind,
          disabled,
          mediaTypes: slot.media_types,
          durationSeconds: slot.duration_seconds,
        };
        return slot.describe !== "none" ? (
          <DescribedAssetList
            key={key}
            {...common}
            maximum={slot.maximum}
            describe={slot.describe}
            items={asDescribedAssets(values[key])}
            onChange={(items) => onChange({ ...values, [key]: items })}
          />
        ) : slot.maximum === 1 ? (
          <AssetSlot
            key={key}
            {...common}
            assetId={asAssetId(values[key])}
            onChange={(id) => onChange({ ...values, [key]: id })}
          />
        ) : (
          <AssetIdList
            key={key}
            {...common}
            maximum={slot.maximum}
            items={asMaybeIdList(values[key])}
            onChange={(items) => onChange({ ...values, [key]: items })}
          />
        );
      })}
      {recipe.params.some((field) => field.advanced) ? (
        <details>
          <summary>高级参数</summary>
          {recipe.params.filter((field) => field.advanced).map(renderField)}
        </details>
      ) : null}
      {Object.keys(recipe.label_namespaces).length > 0 ? (
        <Field label="Provider 输入标签映射（只读预览）" wireKey="input_labels">
          <div
            className="playground-label-map"
            role="group"
            aria-label="输入标签映射"
          >
            {!preview?.input_labels.length ? (
              <p className="playground-hint">还没有选择素材。</p>
            ) : (
              <ul>
                {preview.input_labels.map((entry) => (
                  <li key={`${entry.label}-${entry.asset_id}`}>
                    <code>{entry.label}</code>
                    <span> · {entry.provider_input}</span>
                    {entry.description === null ? null : (
                      <span> · {entry.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Field>
      ) : null}
    </div>
  );
}

export function completeRecipeParameters(
  recipe: ManifestRecipe,
  values: Record<string, unknown>,
) {
  const result = { ...recipeDefaults(recipe), ...values };
  for (const field of recipe.params) {
    if (typeof result[field.key] === "string") {
      const text = (result[field.key] as string).trim();
      result[field.key] = text === "" && field.nullable ? null : text;
    }
  }
  for (const slot of recipe.slots) {
    const key = slotWireKey(slot);
    if (slot.describe !== "none") {
      result[key] = asDescribedAssets(result[key])
        .filter((item) => item.asset_id !== null)
        .map((item) => ({
          asset_id: item.asset_id,
          description: item.description.trim(),
        }));
    }
  }
  return result;
}

export function recipeParametersError(
  recipe: ManifestRecipe,
  values: Record<string, unknown>,
): string | null {
  for (const field of recipe.params) {
    const value = values[field.key];
    if (value === null && field.nullable) continue;
    if (field.widget === "text" || field.widget === "prompt") {
      if (
        typeof value !== "string" ||
        value.trim().length < (field.min_length ?? 0)
      )
        return `${field.label}不能为空。`;
      if (field.max_length !== null && value.length > field.max_length)
        return `${field.label}最多 ${field.max_length} 字。`;
    } else if (["number", "slider", "seed"].includes(field.widget)) {
      if (
        typeof value !== "number" ||
        !Number.isFinite(value) ||
        (field.widget === "seed" && !Number.isInteger(value))
      )
        return `${field.label}必须是有效数值。`;
      if (field.minimum !== null && value < field.minimum)
        return `${field.label}不能小于 ${field.minimum}。`;
      if (field.maximum !== null && value > field.maximum)
        return `${field.label}不能大于 ${field.maximum}。`;
    } else if (["enum", "preset"].includes(field.widget)) {
      if (!field.options.some((option) => option.id === value))
        return `请选择${field.label}。`;
    } else if (field.widget === "vector") {
      if (
        !Array.isArray(value) ||
        value.length !== field.dimension ||
        value.some(
          (item) =>
            typeof item !== "number" ||
            !Number.isFinite(item) ||
            (field.minimum !== null && item < field.minimum) ||
            (field.maximum !== null && item > field.maximum),
        )
      )
        return `${field.label}向量不合法。`;
    } else if (field.widget === "toggle" && typeof value !== "boolean")
      return `${field.label}必须是开关值。`;
  }
  const distinct = recipe.slots
    .filter((slot) => recipe.distinct_slots.includes(slot.key))
    .flatMap((slot) => {
      const value = values[slotWireKey(slot)];
      return Array.isArray(value)
        ? value
        : typeof value === "string"
          ? [value]
          : [];
    });
  if (new Set(distinct).size !== distinct.length)
    return "参考图不能与底图重复。";
  for (const slot of recipe.slots) {
    const value = values[slotWireKey(slot)];
    const items = Array.isArray(value)
      ? value
      : typeof value === "string" && value
        ? [value]
        : [];
    if (items.length < slot.minimum || items.length > slot.maximum)
      return `${slot.label}需要 ${slot.minimum} 到 ${slot.maximum} 项。`;
    const ids = items.map((item) =>
      typeof item === "string"
        ? item
        : asAssetId((item as { asset_id?: unknown } | null)?.asset_id),
    );
    if (ids.some((id) => id === null)) return `请为${slot.label}选择素材。`;
    if (slot.unique && new Set(ids).size !== ids.length)
      return `${slot.label}不能重复。`;
    if (
      slot.describe !== "none" &&
      items.some((item) => {
        const text = (item as { description?: unknown } | null)?.description;
        return (
          typeof text !== "string" ||
          text.length > 2000 ||
          (slot.describe === "required" && !text.trim())
        );
      })
    )
      return `${slot.label}每项必须填写有效说明。`;
  }
  if (
    recipe.require_any.length > 0 &&
    !recipe.slots.some(
      (slot) =>
        recipe.require_any.includes(slot.key) &&
        values[slotWireKey(slot)] &&
        (!Array.isArray(values[slotWireKey(slot)]) ||
          (values[slotWireKey(slot)] as unknown[]).length > 0),
    )
  )
    return "至少选择一个必需输入。";
  return null;
}
