import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LocationBinding, LocationLibrary } from "./location";
import { StructuredDirectorWorkspace } from "../StructuredDirectorWorkspace";
import fixture from "../test/mixed_approval_fixture.json";
import { parseStructuredDirectorSnapshot } from "../api/validation";
import {
  structuredDirectorApi,
  type Location,
  type LocationProduction,
} from "../api";
const base = parseStructuredDirectorSnapshot(fixture);
const roomId = "a".repeat(32),
  viewId = "b".repeat(32);
const image = base.assets.find((a) => a.media_type === "image/png")!;
const generation = {
  ...base.generations.find((g) => g.kind === "keyframe_image")!,
  kind: "location_view_image" as const,
  target_id: viewId,
  output_asset_id: image.id,
};
const production: LocationProduction = {
  status: "awaiting_selection",
  status_label: "等待选择",
  reason: null,
  generation_step: "refine",
  generate_label: "第二步：细化视图",
  active_generation_id: null,
  candidate_generation_ids: [generation.id],
  selectable_generation_ids: [generation.id],
  allowed_actions: ["generate", "select", "edit", "delete"],
};
const room: Location = {
  id: roomId,
  name: "客厅",
  kind: "interior",
  description: "白墙",
  fixtures: [],
  key_light: null,
  master: {
    prompt_text: "客厅",
    reference_asset_ids: [],
    selected_asset_id: image.id,
    production: {
      ...production,
      candidate_generation_ids: [],
      selectable_generation_ids: [],
      generation_step: "master",
      generate_label: "生成主图",
    },
  },
  calibrated_master_asset_id: null,
  states: [],
  views: [
    {
      id: viewId,
      name: "正打",
      purpose: "中景",
      azimuth_deg: 90,
      look_at_fixture_id: null,
      yaw_offset_deg: null,
      pitch_deg: 0,
      hfov_deg: 75,
      state_id: null,
      refine_prompt_text: "保持布局",
      reference_view_ids: [],
      crop_asset_id: image.id,
      has_valid_crop: true,
      selected_asset_id: null,
      production,
    },
  ],
  allowed_actions: ["edit", "create_view", "create_fixture", "create_state"],
};
function props() {
  return {
    snapshot: {
      ...base,
      status: "reviewing_videos" as const,
      active_director_run: null,
      generations: [generation],
      location_library: {
        locations: [structuredClone(room)],
        allowed_actions: [
          "create_location",
          "bind_scene",
          "bind_shot",
        ] as Array<"create_location" | "bind_scene" | "bind_shot">,
      },
    },
    busy: false,
    onPreviewLocationChange: vi.fn().mockResolvedValue({
      revision: base.revision,
      command_name: "location.select_view",
      will_write: true,
      high_impact: true,
      changed_ids: [viewId],
      invalidated: [`keyframe:${viewId}`],
      preserved: ["asset_history", "generation_history"],
      soft_reference_clears: [],
    }),
    onApplyLocationChange: vi.fn().mockResolvedValue(true),
    onGenerateLocationMaster: vi.fn(),
    onGenerateLocationView: vi.fn(),
    onCancelGeneration: vi.fn(),
    onDismissGeneration: vi.fn(),
  };
}
afterEach(() => vi.restoreAllMocks());
it("displays crop and selection, previews before choosing a server-selectable candidate", async () => {
  const p = props();
  render(<LocationLibrary {...p} />);
  expect(screen.getByText("裁切底图（只读）")).toBeInTheDocument();
  expect(screen.getByText("已选视图")).toBeInTheDocument();
  fireEvent.click(screen.getByText("图片候选（1）"));
  fireEvent.click(screen.getByRole("button", { name: /^选择候选$/ }));
  await screen.findByRole("dialog", { name: "地点修改影响预览" });
  expect(p.onApplyLocationChange).not.toHaveBeenCalled();
  const change = {
    name: "location.select_view",
    arguments: { view_id: viewId, asset_id: image.id },
  };
  expect(p.onPreviewLocationChange).toHaveBeenCalledWith(change, base.revision);
  fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
  await waitFor(() =>
    expect(p.onApplyLocationChange).toHaveBeenCalledWith(change, base.revision),
  );
});
it("buttons follow allowed_actions even when crop and master exist", () => {
  const p = props();
  p.snapshot.location_library.locations[0].views[0].production!.allowed_actions =
    [];
  render(<LocationLibrary {...p} />);
  for (const name of ["第二步：细化视图", "编辑视图", "删除视图"])
    expect(screen.getByRole("button", { name })).toBeDisabled();
  fireEvent.click(screen.getByText("图片候选（1）"));
  expect(screen.getByRole("button", { name: "选择候选" })).toBeDisabled();
});
it("submits one explicit crop or refine action using the Core label", () => {
  const p = props();
  const { rerender } = render(<LocationLibrary {...p} />);
  fireEvent.click(screen.getByRole("button", { name: "第二步：细化视图" }));
  expect(p.onGenerateLocationView).toHaveBeenCalledOnce();
  expect(p.onGenerateLocationView).toHaveBeenCalledWith(viewId);
  p.snapshot.location_library.locations[0].views[0].has_valid_crop = false;
  p.snapshot.location_library.locations[0].views[0].production!.generate_label =
    "第一步：生成裁切底图";
  rerender(<LocationLibrary {...p} />);
  fireEvent.click(screen.getByRole("button", { name: "第一步：生成裁切底图" }));
  expect(p.onGenerateLocationView).toHaveBeenCalledTimes(2);
});
it("shows Shot soft-reference clears in the location impact dialog", async () => {
  const p = props();
  p.onPreviewLocationChange.mockResolvedValue({
    revision: base.revision,
    command_name: "location.apply_operations",
    will_write: true,
    high_impact: false,
    changed_ids: [viewId],
    invalidated: [],
    preserved: ["asset_history", "generation_history"],
    soft_reference_clears: [
      {
        shot_id: "c".repeat(32),
        scene_id: "d".repeat(32),
        label: "Scene「客厅」第 2 个 Shot",
      },
    ],
  });
  render(<LocationLibrary {...p} />);
  fireEvent.click(screen.getByRole("button", { name: "删除视图" }));
  await screen.findByRole("dialog", { name: "地点修改影响预览" });
  expect(screen.getByText("将清空的空间参考建议")).toBeInTheDocument();
  expect(screen.getByText("Scene「客厅」第 2 个 Shot")).toBeInTheDocument();
});
it("previews scene and shot bindings with the correct scope", async () => {
  const p = props();
  const scene = {
    ...base.director_script!.scenes[0],
    location_id: roomId,
    state_id: null,
  };
  const { unmount } = render(<LocationBinding {...p} scene={scene} />);
  fireEvent.click(screen.getByRole("button", { name: "改绑地点与状态" }));
  fireEvent.change(screen.getByRole("combobox", { name: "场景地点" }), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览改绑影响" }));
  await waitFor(() =>
    expect(p.onPreviewLocationChange).toHaveBeenCalledWith(
      expect.objectContaining({
        arguments: {
          scope: { location_ids: [], scene_ids: [scene.id], shot_ids: [] },
          operations: [
            {
              op: "bind_scene",
              scene_id: scene.id,
              location_id: null,
              state_id: null,
            },
          ],
        },
      }),
      base.revision,
    ),
  );
  unmount();
  render(<LocationBinding {...p} scene={scene} shot={scene.shots[0]} />);
  expect(screen.getByText("空间参考建议")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "改绑参考视图" }));
  fireEvent.change(screen.getByRole("combobox", { name: "镜头视图" }), {
    target: { value: viewId },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览改绑影响" }));
  await waitFor(() =>
    expect(p.onPreviewLocationChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        arguments: {
          scope: {
            location_ids: [],
            scene_ids: [],
            shot_ids: [scene.shots[0].id],
          },
          operations: [
            { op: "bind_shot", shot_id: scene.shots[0].id, view_id: viewId },
          ],
        },
      }),
      base.revision,
    ),
  );
});
it("preserves draft after failed save and blocks stale impact confirmation", async () => {
  const p = props();
  p.onApplyLocationChange.mockResolvedValue(false);
  const { rerender } = render(<LocationLibrary {...p} />);
  fireEvent.click(screen.getByRole("button", { name: "编辑地点与主图计划" }));
  const editor = screen.getByRole("dialog", { name: "编辑地点" });
  fireEvent.change(within(editor).getByRole("textbox", { name: /名称/ }), {
    target: { value: "新客厅" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览修改影响" }));
  await screen.findByRole("dialog", { name: "地点修改影响预览" });
  fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
  await waitFor(() => expect(p.onApplyLocationChange).toHaveBeenCalled());
  expect(within(editor).getByRole("textbox", { name: /名称/ })).toHaveValue(
    "新客厅",
  );
  rerender(
    <LocationLibrary
      {...p}
      snapshot={{ ...p.snapshot, revision: base.revision + 1 }}
    />,
  );
  expect(screen.getByRole("button", { name: "确认保存" })).toBeDisabled();
});
it("opens location library within the existing director workspace", () => {
  const p = props();
  render(
    <StructuredDirectorWorkspace
      {...p}
      project={{
        id: "c".repeat(32),
        title: "测试",
        aspect_ratio: "16:9",
        updated_at: "2026-10-11T00:00:00Z",
        status: "active",
      }}
      pending={null}
      error={null}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /^地点库$/ }));
  expect(
    screen.getByRole("dialog", { name: "项目地点库" }),
  ).toBeInTheDocument();
});
it("uses human generate and select HTTP routes", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(
      async () => new Response(JSON.stringify(base), { status: 200 }),
    );
  await structuredDirectorApi.generateLocationMaster(roomId, 7, roomId);
  expect(fetcher).toHaveBeenLastCalledWith(
    `/api/projects/${roomId}/structured-director/locations/${roomId}/master/generate`,
    expect.objectContaining({ body: JSON.stringify({ expected_revision: 7 }) }),
  );
  await structuredDirectorApi.generateLocationView(roomId, 7, viewId);
  expect(fetcher).toHaveBeenLastCalledWith(
    `/api/projects/${roomId}/structured-director/location-views/${viewId}/generate`,
    expect.anything(),
  );
  await structuredDirectorApi.applyLocationChange(roomId, 7, {
    name: "location.select_master",
    arguments: { location_id: roomId, asset_id: image.id },
  });
  expect(fetcher).toHaveBeenLastCalledWith(
    `/api/projects/${roomId}/structured-director/locations/${roomId}/master/select`,
    expect.objectContaining({
      body: JSON.stringify({ expected_revision: 7, asset_id: image.id }),
    }),
  );
  await structuredDirectorApi.applyLocationChange(roomId, 7, {
    name: "location.select_view",
    arguments: { view_id: viewId, asset_id: image.id },
  });
  expect(fetcher).toHaveBeenLastCalledWith(
    `/api/projects/${roomId}/structured-director/location-views/${viewId}/select`,
    expect.anything(),
  );
});

it("previews the exact scoped operation before the human HTTP mutation", async () => {
  const change = {
    name: "location.apply_operations" as const,
    arguments: {
      scope: { location_ids: [roomId], scene_ids: [], shot_ids: [] },
      operations: [
        {
          op: "update_location" as const,
          location_id: roomId,
          fields: { name: "新客厅" },
        },
      ],
    },
  };
  const impact = {
    revision: 7,
    command_name: change.name,
    will_write: true,
    high_impact: false,
    changed_ids: [roomId],
    invalidated: [],
    preserved: ["asset_history"],
    soft_reference_clears: [],
  };
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: impact }), { status: 200 }),
    )
    .mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200 }));
  expect(
    await structuredDirectorApi.previewLocationChange(roomId, 7, change),
  ).toEqual(impact);
  const request = JSON.parse(fetcher.mock.calls[0][1]!.body as string);
  expect(request.name).toBe("project.preview_impact");
  expect(request.arguments.command).toMatchObject({
    ...change,
    expected_revision: 7,
  });
  await structuredDirectorApi.applyLocationChange(
    roomId,
    impact.revision,
    change,
  );
  expect(fetcher).toHaveBeenLastCalledWith(
    `/api/projects/${roomId}/structured-director/locations/operations`,
    expect.objectContaining({
      body: JSON.stringify({ expected_revision: 7, ...change.arguments }),
    }),
  );
});
