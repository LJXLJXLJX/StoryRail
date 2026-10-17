import type { ManifestField } from "../api";
export type SettingValue = string | number | boolean | number[] | null;

export function SettingField({
  field,
  value,
  onChange,
  disabled = false,
  label = field.label,
}: {
  field: ManifestField;
  value: SettingValue;
  disabled?: boolean;
  label?: string;
  onChange: (value: SettingValue) => void;
}) {
  if (field.widget === "toggle") {
    return (
      <label className="provider-toggle">
        <input
          disabled={disabled}
          type="checkbox"
          aria-label={label}
          checked={value === true}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{label}</span>
      </label>
    );
  }
  if (field.widget === "enum" || field.widget === "preset") {
    return (
      <label>
        <span>{label}</span>
        <select
          disabled={disabled}
          aria-label={label}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (field.widget === "number" || field.widget === "slider" || field.widget === "seed") {
    return (
      <label>
        <span>{label}</span>
        <input
          disabled={disabled}
          type="number"
          aria-label={label}
          value={typeof value === "number" ? value : ""}
          step={field.widget === "seed" ? 1 : "any"}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          onChange={(event) => {
            const next = event.target.valueAsNumber;
            if (event.target.value === "" && field.nullable) onChange(null);
            else if (Number.isFinite(next)) onChange(next);
          }}
        />
      </label>
    );
  }
  if (field.widget === "vector") {
    const parts = Array.isArray(value) ? value : Array(field.dimension ?? 0).fill(0);
    return <fieldset disabled={disabled}><legend>{label}</legend>{parts.map((part, index) =>
      <label key={index}>{field.component_labels[index] ?? String(index + 1)}<input type="number"
        aria-label={`${label} ${field.component_labels[index] ?? index + 1}`} value={part}
        min={field.minimum ?? undefined} max={field.maximum ?? undefined} step="any"
        onChange={(event) => onChange(parts.map((item, position) => position === index ? Number(event.target.value) : item))} /></label>
    )}</fieldset>;
  }
  return (
    <label>
      <span>{label}</span>
      <textarea
          disabled={disabled}
        aria-label={label}
        value={typeof value === "string" ? value : ""}
        minLength={field.min_length ?? undefined}
        maxLength={field.max_length ?? undefined}
        onChange={(event) => onChange(field.nullable && event.target.value.trim() === "" ? null : event.target.value)}
      />
    </label>
  );
}
