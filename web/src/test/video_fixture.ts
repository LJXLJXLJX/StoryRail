import type { RecipeInputs, SegmentVideo, VideoRecipeState } from "../api";
import fixture from "./video_recipes.json";
export function videoState(recipeId: string): VideoRecipeState {
  const state = (fixture.states as Record<string, VideoRecipeState>)[recipeId];
  return structuredClone(state ?? Object.values(fixture.states)[0]);
}
export function videoFixture(
  value: Omit<SegmentVideo, "recipe_state">,
  state?: VideoRecipeState,
): SegmentVideo {
  const inputs: RecipeInputs = { bindings: {}, params: {} };
  return {
    ...value,
    recipes: {
      "sample_video.ref2va": inputs,
      "sample_video.fl2va": { bindings: {}, params: {} },
      ...value.recipes,
    },
    recipe_state:
      state ?? videoState(value.active_recipe ?? "sample_video.fl2va"),
  };
}
export const videoRecipeViews = fixture.views;
