import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FinalAssemblyWorkspace } from "./final";
import fixture from "../test/mixed_approval_fixture.json";
import type { StructuredDirectorSnapshot } from "../api";
import { parseStructuredDirectorSnapshot } from "../api/validation";

it("中英成片各自选择；两版都选定后才可一次批准；重新开放遵守 Core 权限", () => {
  const snapshot = structuredClone(fixture) as StructuredDirectorSnapshot;
  snapshot.final_approval = null;
  snapshot.final_assembly!.selected_zh_asset_id = null;
  snapshot.final_assembly!.selected_en_asset_id = null;
  snapshot.allowed_actions = ["select_final_video"];
  const onSelect = vi.fn(),
    onApprove = vi.fn(),
    onReopen = vi.fn();
  const props = {
    snapshot,
    busy: false,
    pending: null,
    error: null,
    onGenerate: vi.fn(),
    onSelect,
    onApprove,
    onReopen,
    onDismiss: vi.fn(),
  };
  const view = render(<FinalAssemblyWorkspace {...props} />);
  expect(
    screen.getByText(/查看中文成片候选/).closest("details"),
  ).not.toHaveAttribute("open");
  expect(
    screen.queryByRole("button", { name: "批准中英成片" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText(/查看英文成片候选/));
  fireEvent.click(screen.getByRole("button", { name: "选择英文成片" }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith(
    fixture.final_approval.en_generation_id,
  );
  // 只选了中文时批准按钮出现但不可用。
  snapshot.final_assembly!.selected_zh_asset_id = fixture.final_approval.zh_asset_id;
  snapshot.allowed_actions = ["approve_final_video"];
  view.rerender(<FinalAssemblyWorkspace {...props} />);
  expect(screen.getByRole("button", { name: "批准中英成片" })).toBeDisabled();
  snapshot.final_assembly!.selected_en_asset_id = fixture.final_approval.en_asset_id;
  view.rerender(<FinalAssemblyWorkspace {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "批准中英成片" }));
  expect(onApprove).toHaveBeenCalledOnce();
  snapshot.final_approval = fixture.final_approval;
  snapshot.allowed_actions = [];
  view.rerender(<FinalAssemblyWorkspace {...props} />);
  expect(
    screen.queryByRole("button", { name: "返回视频生产" }),
  ).not.toBeInTheDocument();
  snapshot.allowed_actions = ["reopen_video_production"];
  view.rerender(<FinalAssemblyWorkspace {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "返回视频生产" }));
  expect(onReopen).toHaveBeenCalledOnce();
});

it("装配概览与时间线按 Scene 成片表达，不再展示原始 Segment 或旁白定位", () => {
  const snapshot = structuredClone(fixture) as StructuredDirectorSnapshot;
  render(
    <FinalAssemblyWorkspace
      snapshot={snapshot}
      busy={false}
      pending={null}
      error={null}
      onGenerate={vi.fn()}
      onSelect={vi.fn()}
      onApprove={vi.fn()}
      onDismiss={vi.fn()}
    />,
  );
  expect(screen.getByText("Scene 成片")).toBeInTheDocument();
  expect(screen.queryByText("Segment 视频")).not.toBeInTheDocument();
  expect(screen.getByText(/旁白 Cue（已含在成片内）/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("查看装配时间线"));
  expect(screen.getByText("Scene 1 · 末班车")).toBeInTheDocument();
  expect(screen.getByText("Scene 2 · 末班车")).toBeInTheDocument();
  expect(screen.getByText("从上一 Scene 硬切")).toBeInTheDocument();
  expect(screen.getByText("含 1 条旁白")).toBeInTheDocument();
  expect(screen.queryByText("旁白起点")).not.toBeInTheDocument();
});

it.each(["zh", "en"] as const)("单语言 %s 只显示并批准当前语言成片", (language) => {
  const snapshot = structuredClone(fixture) as StructuredDirectorSnapshot;
  const disabled = language === "zh" ? "en" : "zh";
  snapshot.narration_languages = [language];
  snapshot.status = "reviewing_final";
  snapshot.final_approval = null;
  snapshot.generations = snapshot.generations.filter((item) => item.language !== disabled);
  snapshot.reference_library.narrator![disabled] = null;
  snapshot.director_script!.scenes.forEach((scene) => {
    scene.scene_final![disabled] = null;
    scene.narration_cues.forEach((cue) => { cue[disabled] = null; });
  });
  snapshot.final_assembly!.clips.forEach((clip) => {
    if (disabled === "zh") clip.zh_asset_id = null;
    else clip.en_asset_id = null;
  });
  if (disabled === "zh") snapshot.final_assembly!.selected_zh_asset_id = null;
  else snapshot.final_assembly!.selected_en_asset_id = null;
  snapshot.allowed_actions = ["approve_final_video"];
  expect(() => parseStructuredDirectorSnapshot(snapshot)).not.toThrow();
  const approve = vi.fn();
  render(<FinalAssemblyWorkspace snapshot={snapshot} busy={false} pending={null} error={null}
    onGenerate={vi.fn()} onSelect={vi.fn()} onApprove={approve} onDismiss={vi.fn()} />);
  expect(screen.queryByText(disabled === "zh" ? "中文成片" : "英文成片")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "批准成片" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "批准成片" }));
  expect(approve).toHaveBeenCalledOnce();
  const invalid = structuredClone(snapshot);
  invalid.director_script!.scenes[0].narration_cues[0][disabled] = fixture.director_script.scenes[0].narration_cues[0][disabled];
  expect(() => parseStructuredDirectorSnapshot(invalid)).toThrow(/旁白轨道/);
});
