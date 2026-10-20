import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import fixture from "../test/story_reader_fixture.json";
import type { ProjectAsset, StructuredDirectorSnapshot } from "../api";
import { LocationBinding, LocationLibrary } from "./location";

function imageAsset(index: number): ProjectAsset {
  return {
    id: String(index).repeat(32),
    display_name: `参考图 ${index}.png`,
    media_type: "image/png",
    image_category: "location_image",
    byte_count: 1024,
    duration_seconds: null,
    content_url: `/reference-${index}.png`,
    is_in_use: false,
    usage_reasons: [],
    retains_derived_assets_on_delete: false,
    allowed_actions: [],
  };
}

function snapshot(): StructuredDirectorSnapshot {
  const value = structuredClone(fixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
  value.location_library = {
    allowed_actions: ["create_location", "bind_scene"],
    locations: [
      {
        id: "a".repeat(32),
        name: "大厅",
        description: "挑高石材大厅。",
        fixtures: [],
        key_light: null,
        states: [{ id: "b".repeat(32), name: "夜晚", description: "灯光开启。", allowed_actions: ["edit"] }],
        images: [
          {
            id: "c".repeat(32),
            name: "空间全景",
            kind: "panorama",
            description: "大厅中央的完整 360 度视野。",
            prompt_text: "生成大厅全景。",
            reference_asset_ids: [],
            selected_asset_id: null,
            source: null,
            production: {
              status: "ready",
              status_label: "可生成",
              reason: null,
              generation_step: "image",
              generate_label: "生成图片",
              active_generation_id: null,
              candidate_generation_ids: [],
              selectable_generation_ids: [],
              allowed_actions: ["generate", "edit", "delete"],
            },
          },
        ],
        allowed_actions: ["edit", "create_image"],
      },
    ],
  };
  return value;
}

describe("location image library", () => {
  it("shows independent images and generates the selected image entry", () => {
    const onGenerateLocationImage = vi.fn();
    render(
      <LocationLibrary
        snapshot={snapshot()}
        busy={false}
        onGenerateLocationImage={onGenerateLocationImage}
        onCancelGeneration={vi.fn()}
        onDismissGeneration={vi.fn()}
      />,
    );
    expect(screen.getByText("先选择地点，再查看其中的空间说明、状态与独立图片。")).toBeInTheDocument();
    expect(screen.getByText("挑高石材大厅。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成图片" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /大厅/ }));
    expect(screen.getByRole("button", { name: "← 返回地点列表" })).toBeInTheDocument();
    expect(screen.getByText("大厅中央的完整 360 度视野。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "生成图片" }));
    expect(onGenerateLocationImage).toHaveBeenCalledWith("c".repeat(32));
  });

  it("opens image editing in a dialog and selects previewable references from the asset library", async () => {
    const onApplyLocationChange = vi.fn(async () => true);
    const value = snapshot();
    value.assets = [imageAsset(1), imageAsset(2)];
    value.location_library.locations[0].images[0].reference_asset_ids = [value.assets[0].id];
    render(
      <LocationLibrary
        snapshot={value}
        busy={false}
        onApplyLocationChange={onApplyLocationChange}
        onCancelGeneration={vi.fn()}
        onDismissGeneration={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /大厅/ }));
    expect(screen.queryByRole("dialog", { name: "编辑地点图片：空间全景" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    const editor = screen.getByRole("dialog", { name: "编辑地点图片：空间全景" });
    expect(within(editor).getByRole("button", { name: "查看全图：参考图 1.png" })).toBeInTheDocument();
    expect(within(editor).getByText("1 / 5 张参考图")).toBeInTheDocument();

    fireEvent.click(within(editor).getByRole("button", { name: "从资产库选择参考图" }));
    const library = screen.getByRole("dialog", { name: "从资产库选择地点图片参考图" });
    expect(within(library).getByRole("button", { name: "查看全图：参考图 2.png" })).toBeInTheDocument();
    fireEvent.click(within(library).getByRole("button", { name: "选择 参考图 2.png" }));
    fireEvent.click(within(library).getByRole("button", { name: "完成" }));

    expect(screen.queryByRole("dialog", { name: "从资产库选择地点图片参考图" })).not.toBeInTheDocument();
    expect(within(editor).getByRole("button", { name: "查看全图：参考图 2.png" })).toBeInTheDocument();
    expect(within(editor).getByText("2 / 5 张参考图")).toBeInTheDocument();
    fireEvent.click(within(editor).getByRole("button", { name: "保存修改" }));

    await waitFor(() => expect(onApplyLocationChange).toHaveBeenCalledTimes(1));
    expect(onApplyLocationChange).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "location.apply_operations",
        arguments: expect.objectContaining({
          operations: [
            expect.objectContaining({
              op: "update_image",
              fields: expect.objectContaining({
                reference_asset_ids: [value.assets[0].id, value.assets[1].id],
              }),
            }),
          ],
        }),
      }),
      value.revision,
    );
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑地点图片：空间全景" })).not.toBeInTheDocument());
  });

  it("keeps location creation behind a dialog on the overview", async () => {
    const onApplyLocationChange = vi.fn(async () => true);
    const value = snapshot();
    render(
      <LocationLibrary
        snapshot={value}
        busy={false}
        onApplyLocationChange={onApplyLocationChange}
        onCancelGeneration={vi.fn()}
        onDismissGeneration={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("地点名称")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "添加地点" }));
    const dialog = screen.getByRole("dialog", { name: "添加地点" });
    fireEvent.change(within(dialog).getByLabelText("地点名称"), { target: { value: "钟楼" } });
    fireEvent.change(within(dialog).getByLabelText("地点说明"), { target: { value: "旧城钟楼内部。" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建地点" }));

    await waitFor(() => expect(onApplyLocationChange).toHaveBeenCalledTimes(1));
    expect(onApplyLocationChange).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "location.apply_operations",
        arguments: expect.objectContaining({
          operations: [expect.objectContaining({ op: "create_location", name: "钟楼" })],
        }),
      }),
      value.revision,
    );
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "添加地点" })).not.toBeInTheDocument());
  });

  it("binds only the Scene semantic location and state", () => {
    const onApplyLocationChange = vi.fn(async () => true);
    const value = snapshot();
    const scene = { ...value.director_script!.scenes[0], location_id: null, state_id: null };
    render(
      <LocationBinding
        snapshot={value}
        scene={scene}
        busy={false}
        onApplyLocationChange={onApplyLocationChange}
        onCancelGeneration={vi.fn()}
        onDismissGeneration={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Scene 地点（仅语义关系）"), {
      target: { value: "a".repeat(32) },
    });
    expect(onApplyLocationChange).toHaveBeenCalledWith(
      expect.objectContaining({ name: "location.apply_operations" }),
      value.revision,
    );
  });
});
