import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ManifestRecipe } from "../../api";
import { isPlaygroundCapabilityInfo } from "../../api/validation";
import fixture from "../../test/playground_recipes.json";
import { FormProvider } from "./common";
import {
  RecipeForm,
  completeRecipeParameters,
  recipeDefaults,
  recipeParametersError,
} from "./RecipeForm";

const recipe = fixture.sample_recipe as ManifestRecipe;

it("未知插件的向量与种子字段使用声明的键和分量标签", () => {
  const onChange = vi.fn();
  const values = {
    ...recipeDefaults(recipe),
    content: "你好",
    emotion: [0.2, -0.1],
  };
  render(
    <FormProvider assets={[]} requestAsset={vi.fn()} disabled={false}>
      <RecipeForm
        recipe={recipe}
        values={values}
        onChange={onChange}
        disabled={false}
      />
    </FormProvider>,
  );
  expect(screen.getByRole("spinbutton", { name: "随机种子" })).toHaveValue(42);
  expect(screen.getByRole("spinbutton", { name: "情感 喜悦" })).toHaveAttribute(
    "min",
    "-1",
  );
  fireEvent.change(screen.getByRole("spinbutton", { name: "情感 平静" }), {
    target: { value: "0.6" },
  });
  expect(onChange).toHaveBeenLastCalledWith({ ...values, emotion: [0.2, 0.6] });
  expect(
    completeRecipeParameters(recipe, { ...values, content: "  你好  " })
      .content,
  ).toBe("你好");
  expect(
    recipeParametersError(recipe, {
      ...values,
      speaker_asset_id: "a".repeat(32),
    }),
  ).toBeNull();
  expect(recipeParametersError(recipe, { ...values, emotion: [2, 0] })).toBe(
    "情感向量不合法。",
  );
});

it("Web 接受 Core 的动态目录，向量默认值随 recipe 进入严格契约", () => {
  for (const descriptor of fixture.capabilities)
    expect(isPlaygroundCapabilityInfo(descriptor)).toBe(true);
  const descriptor = {
    ...fixture.capabilities[0],
    id: recipe.id,
    recipe: { plugin_id: "second_sample", plugin_label: "第二样本", recipe },
  };
  expect(isPlaygroundCapabilityInfo(descriptor)).toBe(true);
  expect(isPlaygroundCapabilityInfo({ ...descriptor, surprise: true })).toBe(
    false,
  );
});
