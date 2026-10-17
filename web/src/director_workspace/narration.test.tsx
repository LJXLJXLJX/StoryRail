import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import fixture from "../test/story_reader_fixture.json";
import { parseStructuredDirectorSnapshot } from "../api/validation";
import { NarrationCueCard } from "./narration";

it("旁白轨道按 speech recipe 编辑参数，保存时保留另一语言与其它 recipe", () => {
  const snapshot = parseStructuredDirectorSnapshot(structuredClone(fixture.continuity.production_snapshot));
  const scene = snapshot.director_script!.scenes.find((item) => item.narration_cues.length > 0)!;
  const cue = scene.narration_cues[0];
  const current = { ...cue, zh: { ...cue.zh!, recipe_params: { "uninstalled.clone": { strength: 0.5 } } } };
  const save = vi.fn();
  render(<NarrationCueCard scene={scene} cue={current} snapshot={snapshot} busy={false}
    onSave={save} onGenerate={vi.fn()} onSelect={vi.fn()} onClearSelection={vi.fn()}
    onCancel={vi.fn()} onDismiss={vi.fn()} />);
  const chinese = within(screen.getByRole("region", { name: "中文旁白" }));
  expect(chinese.getByLabelText("表演指示")).toHaveAttribute("maxlength", "200");
  fireEvent.change(chinese.getByLabelText("表演指示"), { target: { value: "克制，语速稍慢" } });
  fireEvent.click(screen.getByRole("button", { name: "保存参数" }));
  expect(save.mock.calls[0][0].zh!.recipe_params).toEqual({
    "uninstalled.clone": { strength: 0.5 }, "breeze_tts2.clone": { performance_instruction: "克制，语速稍慢" },
  });
  expect(save.mock.calls[0][0].en!.recipe_params).toEqual(cue.en!.recipe_params);
});

it.each(["zh", "en"] as const)("单语言 %s 旁白卡不显示另一语言轨道", (language) => {
  const snapshot = parseStructuredDirectorSnapshot(structuredClone(fixture.continuity.production_snapshot));
  const disabled = language === "zh" ? "en" : "zh";
  snapshot.narration_languages = [language];
  const scene = snapshot.director_script!.scenes[0];
  const cue = { ...scene.narration_cues[0], [disabled]: null };
  render(<NarrationCueCard scene={scene} cue={cue} snapshot={snapshot} busy={false}
    onSave={vi.fn()} onGenerate={vi.fn()} onSelect={vi.fn()} onClearSelection={vi.fn()}
    onCancel={vi.fn()} onDismiss={vi.fn()} />);
  expect(screen.getByRole("heading", { name: language === "zh" ? "中文旁白" : "英文旁白" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: disabled === "zh" ? "中文旁白" : "英文旁白" })).not.toBeInTheDocument();
  expect(screen.queryByText(/两种语言都选定/)).not.toBeInTheDocument();
});
