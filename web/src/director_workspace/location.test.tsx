import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import fixture from "../test/story_reader_fixture.json";
import type { StructuredDirectorSnapshot } from "../api";
import { LocationBinding, LocationLibrary } from "./location";

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
    expect(screen.getByText("地点保存空间语义；图片彼此独立，全景图只是可进入 3D 预览并取景的特殊类别。")).toBeInTheDocument();
    expect(screen.getByText("大厅中央的完整 360 度视野。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "生成图片" }));
    expect(onGenerateLocationImage).toHaveBeenCalledWith("c".repeat(32));
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
