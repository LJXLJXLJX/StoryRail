import {
  createContext,
  useContext,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import type {
  ManifestRole,
  ManifestRecipe,
  RecipeInputs,
  StructuredDirectorSnapshot,
  VideoRecipeState,
} from "../api";
import { useProtectedValue } from "./draft_protection";
import {
  SettingField,
  type SettingValue,
} from "../provider_settings/SettingField";
import {
  AssetAudio,
  assetById,
  SingleAudioAssetPickerDialog,
  SingleImageAssetPickerDialog,
  SingleVideoAssetPickerDialog,
  ZoomableImage,
} from "./shared";

interface ProtectedDraft<T> {
  value: T;
  setValue: Dispatch<SetStateAction<T>>;
  dirty: boolean;
  conflict: boolean;
  reset: () => void;
}

interface SegmentVideoDraft {
  segmentId: string;
  prompt: ProtectedDraft<string>;
  inputs: ProtectedDraft<RecipeInputs>;
}

const SegmentVideoDraftContext = createContext<SegmentVideoDraft | null>(null);

export function SegmentVideoDraftProvider({
  snapshot,
  segmentId,
  children,
}: {
  snapshot: StructuredDirectorSnapshot;
  segmentId: string;
  children: ReactNode;
}) {
  const plan = snapshot.video_plan?.segments.find(
    (item) => item.segment_id === segmentId,
  );
  const savedInputs = plan?.active_recipe
    ? (plan.recipes[plan.active_recipe] ?? { bindings: {}, params: {} })
    : { bindings: {}, params: {} };
  const prompt = useProtectedValue(plan?.prompt_text ?? "");
  const inputs = useProtectedValue(savedInputs);
  return (
    <SegmentVideoDraftContext.Provider value={{ segmentId, prompt, inputs }}>
      {children}
    </SegmentVideoDraftContext.Provider>
  );
}

export function useSegmentVideoDraft(): SegmentVideoDraft | null {
  return useContext(SegmentVideoDraftContext);
}

export function recipeInputsError(
  recipe: ManifestRecipe,
  value: RecipeInputs,
): string | null {
  for (const slot of recipe.slots) {
    if (["first_frame", "last_frame"].includes(slot.role)) continue;
    const items = value.bindings[slot.key] ?? [];
    if (items.length < slot.minimum || items.length > slot.maximum)
      return `${slot.label}需要 ${slot.minimum} 到 ${slot.maximum} 项。`;
    if (
      slot.describe === "required" &&
      items.some((item) => !item.description?.trim())
    )
      return `${slot.label}每一项都必须填写说明。`;
  }
  return null;
}

export function completeProjectRecipeInputs(
  recipe: ManifestRecipe,
  value: RecipeInputs,
): RecipeInputs {
  return {
    bindings: {
      ...value.bindings,
      ...Object.fromEntries(
        recipe.slots
          .filter((slot) => !["first_frame", "last_frame"].includes(slot.role))
          .map((slot) => [
            slot.key,
            (value.bindings[slot.key] ?? []).map((item) => ({
              ...item,
              description: item.description?.trim() ?? null,
            })),
          ]),
      ),
    },
    params: {
      ...Object.fromEntries(
        recipe.params
          .filter((field) => field.role === null)
          .map((field) => [field.key, field.default]),
      ),
      ...value.params,
    },
  };
}

export function RecipeInputsControl({
  recipe,
  value,
  state,
  snapshot,
  boundaryAssets,
  disabled,
  hiddenRoles = [],
  onChange,
}: {
  recipe: ManifestRecipe;
  value: RecipeInputs;
  state?: VideoRecipeState;
  snapshot: StructuredDirectorSnapshot;
  boundaryAssets: { first_frame: string | null; last_frame: string | null };
  disabled: boolean;
  hiddenRoles?: ManifestRole[];
  onChange: (value: RecipeInputs) => void;
}) {
  const [picker, setPicker] = useState<string | null>(null);
  const slot = recipe.slots.find((item) => item.key === picker);
  const media = (assetId: string, label: string) => {
    const asset = assetById(snapshot.assets, assetId);
    if (!asset) return <span>媒体不可用</span>;
    if (asset.media_type.startsWith("image/"))
      return <ZoomableImage src={asset.content_url} alt={label} />;
    if (asset.media_type.startsWith("audio/"))
      return <AssetAudio asset={asset} />;
    return (
      <video
        src={asset.content_url}
        controls
        preload="metadata"
        aria-label={label}
      />
    );
  };
  const update = (key: string, items: RecipeInputs["bindings"][string]) =>
    onChange({ ...value, bindings: { ...value.bindings, [key]: items } });
  const available = slot
    ? snapshot.assets.filter(
        (asset) =>
          slot.media_types.includes(asset.media_type) &&
          (!slot.unique ||
            !(value.bindings[slot.key] ?? []).some(
              (item) => item.asset_id === asset.id,
            )) &&
          (slot.duration_seconds === null ||
            (asset.duration_seconds !== null &&
              asset.duration_seconds >= slot.duration_seconds[0] &&
              asset.duration_seconds <= slot.duration_seconds[1])),
      )
    : [];
  const choose = (assetId: string) => {
    if (slot)
      update(slot.key, [
        ...(value.bindings[slot.key] ?? []),
        {
          asset_id: assetId,
          description: slot.describe === "none" ? null : "",
        },
      ]);
    setPicker(null);
  };
  return (
    <>
      {recipe.slots.filter((item) => !hiddenRoles.includes(item.role)).map((item) => {
        const automatic = ["first_frame", "last_frame"].includes(item.role);
        const automaticId =
          item.role === "first_frame"
            ? boundaryAssets.first_frame
            : boundaryAssets.last_frame;
        const items = automatic
          ? automaticId
            ? [{ asset_id: automaticId, description: null }]
            : []
          : (value.bindings[item.key] ?? []);
        return (
          <section
            key={item.key}
            className={`segment-video-audio-references${item.role === "reference_image" ? " segment-video-additional-references" : ""}`}
            aria-label={`${recipe.label} ${item.label}`}
          >
            <h5>{item.label}</h5>
            <small>
              {items.length}/{item.maximum}
            </small>
            {!automatic && items.length === 0 ? (
              <>
                <p>未添加{item.label}。</p>
                <small>
                  {item.minimum === 0 ? "此槽位可选。" : "请先添加输入。"}
                </small>
              </>
            ) : null}
            {item.describe === "required" &&
            items.some((binding) => !binding.description?.trim()) ? (
              <p>每条{item.label}都必须填写说明后才能保存。</p>
            ) : null}
            {items.map((binding, index) => {
              const label = state?.slot_labels[item.key]?.[index] ?? item.label;
              return (
                <article
                  className={
                    automatic ? "segment-video-boundary-frame" : undefined
                  }
                  key={binding.asset_id}
                >
                  <strong>
                    {automatic ? `${label} · ${item.label}` : label}
                  </strong>
                  {media(
                    binding.asset_id,
                    `${recipe.label} ${item.label} ${index + 1}`,
                  )}
                  {!automatic && item.describe !== "none" ? (
                    <label className="card-field">
                      <span>{label} 说明</span>
                      <textarea
                        aria-label={`${item.label} ${index + 1} 描述`}
                        aria-invalid={
                          item.describe === "required" &&
                          !binding.description?.trim()
                        }
                        value={binding.description ?? ""}
                        maxLength={2000}
                        disabled={disabled}
                        onChange={(event) =>
                          update(
                            item.key,
                            items.map((old, position) =>
                              position === index
                                ? { ...old, description: event.target.value }
                                : old,
                            ),
                          )
                        }
                      />
                    </label>
                  ) : null}
                  {!automatic ? (
                    <button
                      disabled={disabled}
                      onClick={() =>
                        update(
                          item.key,
                          items.filter((_, position) => position !== index),
                        )
                      }
                    >
                      移除{item.label}
                    </button>
                  ) : null}
                </article>
              );
            })}
            {automatic ? (
              <small>在关键帧卡中启用并选择图片。</small>
            ) : (
              <button
                disabled={disabled || items.length >= item.maximum}
                onClick={() => setPicker(item.key)}
              >
                添加{item.label}
              </button>
            )}
            {!automatic && item.duration_seconds ? (
              <small>
                {item.duration_seconds[0]}–{item.duration_seconds[1]} 秒
              </small>
            ) : null}
          </section>
        );
      })}
      {recipe.params
        .filter((field) => field.role === null)
        .map((field) => (
          <SettingField
            key={field.key}
            field={field}
            value={(value.params[field.key] ?? field.default) as SettingValue}
            disabled={disabled}
            onChange={(parameter) =>
              onChange({
                ...value,
                params: { ...value.params, [field.key]: parameter },
              })
            }
          />
        ))}
      {slot && slot.media_types[0]?.startsWith("image/") ? (
        <SingleImageAssetPickerDialog
          title={`添加 ${recipe.label} ${slot.label}`}
          ariaLabel={`添加 ${recipe.label} ${slot.label}`}
          assets={available}
          selectedAssetId={null}
          busy={disabled}
          onClose={() => setPicker(null)}
          onSelect={choose}
        />
      ) : null}
      {slot && slot.media_types[0]?.startsWith("audio/") ? (
        <SingleAudioAssetPickerDialog
          title={`添加 ${recipe.label} ${slot.label}`}
          assets={available}
          busy={disabled}
          onClose={() => setPicker(null)}
          onSelect={choose}
        />
      ) : null}
      {slot && slot.media_types[0]?.startsWith("video/") ? (
        <SingleVideoAssetPickerDialog
          title={`添加 ${recipe.label} ${slot.label}`}
          ariaLabel={`添加 ${recipe.label} ${slot.label}`}
          assets={available}
          attachedAssetIds={(value.bindings[slot.key] ?? []).map(
            (item) => item.asset_id,
          )}
          busy={disabled}
          onClose={() => setPicker(null)}
          onSelect={choose}
        />
      ) : null}
    </>
  );
}
