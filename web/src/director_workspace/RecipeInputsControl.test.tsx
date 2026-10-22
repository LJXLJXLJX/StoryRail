import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ManifestRecipe, RecipeInputs, StructuredDirectorSnapshot } from "../api";
import fixture from "../test/story_reader_fixture.json";
import { videoRecipeViews, videoState } from "../test/video_fixture";
import { RecipeInputsControl } from "./RecipeInputsControl";

const recipe = videoRecipeViews.find((view) => view.recipe.id === "minimax_h3.ref2va")!.recipe as ManifestRecipe;
const snapshot = fixture.continuity.production_snapshot as unknown as StructuredDirectorSnapshot;

function setup(initial: RecipeInputs, stateName = "dialogue", disabled = false) {
  const changed = vi.fn();
  const state = videoState(stateName);
  function Editor() {
    const [value, setValue] = useState(initial);
    return <RecipeInputsControl recipe={recipe} snapshot={snapshot} state={state}
      value={value} boundaryAssets={{ first_frame: null, last_frame: null }} disabled={disabled}
      onChange={(next) => { changed(next); setValue(next); }} />;
  }
  render(<Editor />);
  const section = within(screen.getByLabelText("Ref2VA 参考音频"));
  return { changed, section, button: section.getByRole("button", { name: "一键添加本段对白 TTS" }), state };
}

it("一键添加对白反复点击只覆盖对应说明，保留手动参考及其他输入", () => {
  const state = videoState("dialogue");
  const selected = state.dialogue_audio!.bindings;
  const manual = state.bindings.filter((item) => item.role === "reference_audio")
    .filter((item) => !selected.some((entry) => entry.asset_id === item.asset_id));
  const initial: RecipeInputs = {
    bindings: {
      reference_audios: [{ ...selected[1], description: "旧说明" }, ...manual.map(({asset_id, description}) => ({asset_id, description}))],
      reference_videos: [{ asset_id: "f".repeat(32), description: "保留运镜参考" }],
    },
    params: { keep: 7 },
  };
  const { changed, button, section } = setup(initial);
  fireEvent.click(button);
  const expected = {
    ...initial, bindings: {
      ...initial.bindings,
      reference_audios: [...selected, ...initial.bindings.reference_audios.slice(1)],
    },
  };
  expect(changed).toHaveBeenLastCalledWith(expected);
  expect(section.getAllByText("本段对白")).toHaveLength(3);
  expect(section.getAllByText("手动参考")).toHaveLength(2);
  expect(section.getByLabelText("参考音频 1 描述")).toHaveValue(selected[0].description);
  fireEvent.change(section.getByLabelText("参考音频 1 描述"), { target: { value: "过时说明" } });
  fireEvent.click(button);
  expect(changed).toHaveBeenLastCalledWith(expected);
  fireEvent.click(button);
  expect(changed).toHaveBeenLastCalledWith(expected);
  expect(section.getByText("5/8")).toBeInTheDocument();
});

it("任一句未选 TTS 时提示具体对白，不部分添加", () => {
  const { changed, section, button } = setup({ bindings: {}, params: {} }, "dialogue_missing");
  fireEvent.click(button);
  expect(section.getByRole("alert")).toHaveTextContent("第 2 句「好的。」");
  expect(changed).not.toHaveBeenCalled();
  expect(section.getByText("0/8")).toBeInTheDocument();
});

it("与手动参考合计超限时整次不添加", () => {
  const { changed, section, button } = setup({
    bindings: { reference_audios: Array.from({length: 6}, (_, index) => ({asset_id: `${index + 1}`.repeat(32), description: "手动参考"})) }, params: {},
  });
  fireEvent.click(button);
  expect(section.getByRole("alert")).toHaveTextContent("合计 9 条，超过 8 条上限");
  expect(changed).not.toHaveBeenCalled();
});

it("没有编辑权限或生成中时禁用一键添加", () => {
  const { button } = setup({ bindings: {}, params: {} }, "dialogue", true);
  expect(button).toBeDisabled();
});
