import { useEffect, useImperativeHandle, useState, type Ref } from "react";

import {
  StoryRailApiError,
  type PlaygroundAsset,
  type PlaygroundCapabilityId,
  type PlaygroundCapabilityInfo,
  type PlaygroundRun,
  type ManifestRecipe,
  type PlaygroundRecipePreview,
} from "../api";
import { playgroundApi } from "./api";
import {
  FormProvider,
  asDescribedAssets,
  asMaybeIdList,
  type AssetPickRequest,
  type SlotTarget,
} from "./forms/common";
import {
  RecipeForm,
  recipeDefaults,
  completeRecipeParameters,
  recipeParametersError,
} from "./forms/RecipeForm";
import { CAPABILITY_FORMS } from "./forms/index";
import {
  batchVariants,
  completeParameters,
  defaultParameters,
  parametersError,
} from "./forms/parameters";

export type RunFormHandle = {
  prefill: (
    capability: PlaygroundCapabilityId,
    parameters: Record<string, unknown>,
  ) => void;
  fillSlot: (target: SlotTarget, assetId: string) => void;
};

// 01 §12.8 与风险 R7 的统一文案。
export const DELETED_INPUT_NOTICE = "部分输入素材已删除，已清空对应槽位";
const QUEUE_NOTICE =
  "提交后进入对应模型服务的队列，与项目生产任务按提交顺序排队。";

function stripMissingAssets(
  capability: PlaygroundCapabilityId,
  parameters: Record<string, unknown>,
  known: Set<string>,
  recipe?: ManifestRecipe,
): { parameters: Record<string, unknown>; removed: boolean } {
  const result: Record<string, unknown> = {
    ...(recipe ? recipeDefaults(recipe) : defaultParameters(capability)),
    ...parameters,
  };
  let removed = false;
  for (const key of Object.keys(result)) {
    if (!key.endsWith("_asset_id")) continue;
    const value = result[key];
    if (typeof value === "string" && value.length > 0 && !known.has(value)) {
      result[key] = null;
      removed = true;
    }
  }
  for (const key of Object.keys(result)) {
    if (key.endsWith("_asset_ids") && Array.isArray(result[key])) {
      const items = asMaybeIdList(result[key]);
      const kept = items.filter((item) => item === null || known.has(item));
      if (kept.length !== items.length) {
        result[key] = kept;
        removed = true;
      }
    }
  }
  for (const slot of recipe?.slots ?? []) {
    if (slot.describe === "none") continue;
    const items = asDescribedAssets(result[slot.key]);
    const kept = items.filter(
      (item) => item.asset_id === null || known.has(item.asset_id),
    );
    if (kept.length !== items.length) {
      result[slot.key] = kept;
      removed = true;
    }
  }
  return { parameters: result, removed };
}

export function RunForm({
  ref,
  capabilities,
  assets,
  selectedCapability,
  onSubmitted,
  onRequestAsset,
  disabled = false,
}: {
  ref?: Ref<RunFormHandle>;
  capabilities: PlaygroundCapabilityInfo[];
  assets: PlaygroundAsset[];
  selectedCapability: PlaygroundCapabilityId | null;
  onSubmitted: (run: PlaygroundRun) => void;
  onRequestAsset: (request: AssetPickRequest) => void;
  disabled?: boolean;
}) {
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>(
    {},
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [preview, setPreview] = useState<PlaygroundRecipePreview | null>(null);

  const recipe = capabilities.find((item) => item.id === selectedCapability)
    ?.recipe?.recipe;
  const values =
    selectedCapability === null
      ? null
      : (drafts[selectedCapability] ??
        (recipe
          ? recipeDefaults(recipe)
          : defaultParameters(selectedCapability)));

  const previewKey = JSON.stringify([selectedCapability, values]);
  useEffect(() => {
    setPreview(null);
    if (!recipe || selectedCapability === null || values === null) return;
    let stale = false;
    const timer = setTimeout(() => {
      void playgroundApi
        .previewRecipeInputs(
          selectedCapability,
          completeRecipeParameters(recipe, values),
        )
        .then((result) => {
          if (!stale) setPreview(result);
        })
        .catch(() => {
          if (!stale) setPreview(null);
        });
    }, 120);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [previewKey, recipe, selectedCapability]);

  useImperativeHandle(
    ref,
    () => ({
      prefill(capability, parameters) {
        const known = new Set(assets.map((asset) => asset.id));
        const prepared = stripMissingAssets(
          capability,
          parameters,
          known,
          capabilities.find((item) => item.id === capability)?.recipe?.recipe,
        );
        setDrafts((current) => ({
          ...current,
          [capability]: prepared.parameters,
        }));
        setSubmitError(null);
        setNotice(prepared.removed ? DELETED_INPUT_NOTICE : null);
      },
      fillSlot(target, assetId) {
        setDrafts((current) => {
          const base =
            current[target.capability] ??
            (() => {
              const targetRecipe = capabilities.find(
                (item) => item.id === target.capability,
              )?.recipe?.recipe;
              return targetRecipe
                ? recipeDefaults(targetRecipe)
                : defaultParameters(target.capability);
            })();
          if (target.list !== undefined) {
            const items = asDescribedAssets(base[target.list]);
            return {
              ...current,
              [target.capability]: {
                ...base,
                [target.list]: [
                  ...items,
                  { asset_id: assetId, description: "" },
                ],
              },
            };
          }
          if (target.idList !== undefined) {
            const items = asMaybeIdList(base[target.idList]);
            return {
              ...current,
              [target.capability]: {
                ...base,
                [target.idList]: [...items, assetId],
              },
            };
          }
          return {
            ...current,
            [target.capability]: { ...base, [target.key]: assetId },
          };
        });
        setSubmitError(null);
        setNotice(null);
      },
    }),
    [assets, capabilities],
  );

  function update(next: Record<string, unknown>) {
    if (selectedCapability === null) return;
    setDrafts((current) => ({ ...current, [selectedCapability]: next }));
    setSubmitError(null);
  }

  async function submitParameters(
    capability: PlaygroundCapabilityId,
    parameters: Record<string, unknown>,
  ): Promise<PlaygroundRun> {
    const run = await playgroundApi.submitRun(capability, parameters, null);
    return run;
  }

  async function submit() {
    if (selectedCapability === null || values === null) return;
    const capability = selectedCapability;
    const error = recipe
      ? recipeParametersError(recipe, values)
      : parametersError(capability, values);
    if (error !== null) {
      setSubmitError(error);
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      onSubmitted(
        await submitParameters(
          capability,
          recipe
            ? completeRecipeParameters(recipe, values)
            : completeParameters(capability, values),
        ),
      );
    } catch (caught) {
      setSubmitError(submitErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  async function separateBoth() {
    if (selectedCapability === null || !recipe || values === null) return;
    const stemField = recipe.params.find(
      (field) => field.role === "audio_stem",
    );
    if (!stemField) return;
    const error = recipeParametersError(recipe, values);
    if (error !== null) {
      setSubmitError(error);
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      let last: PlaygroundRun | null = null;
      for (const stem of stemField.options.map((option) => option.id)) {
        last = await submitParameters(selectedCapability, {
          ...completeRecipeParameters(recipe, values),
          [stemField.key]: stem,
        });
      }
      if (last !== null) onSubmitted(last);
    } catch (caught) {
      setSubmitError(submitErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  async function submitBatch(variants: Array<Record<string, unknown>>) {
    if (selectedCapability === null) return;
    setSubmitting(true);
    setSubmitError(null);
    let last: PlaygroundRun | null = null;
    try {
      // 逐条提交；任何一条被拒绝即停止，已提交的 run 保留在运行流里。
      for (const variant of variants) {
        last = await submitParameters(selectedCapability, variant);
      }
    } catch (caught) {
      setSubmitError(submitErrorMessage(caught));
    } finally {
      setSubmitting(false);
      if (last !== null) onSubmitted(last);
    }
  }

  const capability =
    capabilities.find((item) => item.id === selectedCapability) ?? null;
  const Form =
    selectedCapability === null
      ? null
      : (CAPABILITY_FORMS[selectedCapability] ?? null);
  const clientError =
    selectedCapability === null || values === null
      ? "请选择左侧能力。"
      : recipe
        ? recipeParametersError(recipe, values)
        : parametersError(selectedCapability, values);
  const isSync = capability?.execution === "sync";
  const batch =
    selectedCapability === null || values === null || recipe
      ? null
      : batchVariants(selectedCapability, values);
  const formDisabled = disabled || submitting;

  return (
    <section className="playground-column" aria-label="参数表单">
      <h2>参数</h2>
      {capability === null || (Form === null && !recipe) || values === null ? (
        <p className="playground-hint">请选择左侧能力。</p>
      ) : (
        <FormProvider
          assets={assets}
          requestAsset={onRequestAsset}
          disabled={formDisabled}
        >
          <p className="playground-wire-key">{capability.id}</p>
          {notice === null ? null : (
            <p className="playground-warning">{notice}</p>
          )}
          {clientError === null ? null : (
            <p className="playground-error" role="alert">
              {clientError}
            </p>
          )}
          {submitError === null ? null : (
            <p className="playground-error" role="alert">
              {submitError}
            </p>
          )}
          {recipe ? (
            <RecipeForm
              recipe={recipe}
              preview={preview}
              values={values}
              onChange={update}
              disabled={formDisabled}
            />
          ) : Form ? (
            <Form values={values} onChange={update} disabled={formDisabled} />
          ) : null}
          <div className="playground-form-actions">
            <button
              type="button"
              className="primary-button"
              disabled={formDisabled || clientError !== null}
              onClick={() => void submit()}
            >
              {submitting ? (isSync ? "处理中…" : "提交中…") : "提交"}
            </button>
            {recipe?.params.some(
              (field) =>
                field.role === "audio_stem" && field.options.length === 2,
            ) ? (
              <button
                type="button"
                className="secondary-button"
                disabled={formDisabled || clientError !== null}
                onClick={() => void separateBoth()}
              >
                分离两轨
              </button>
            ) : null}
            {batch === null ? null : (
              <button
                type="button"
                className="secondary-button"
                disabled={formDisabled || clientError !== null}
                onClick={() => void submitBatch(batch.variants)}
              >
                {batch.label}
              </button>
            )}
          </div>
          <p className="playground-hint">{QUEUE_NOTICE}</p>
        </FormProvider>
      )}
    </section>
  );
}

function submitErrorMessage(caught: unknown): string {
  return caught instanceof StoryRailApiError
    ? caught.message
    : "提交失败，请重试。";
}
