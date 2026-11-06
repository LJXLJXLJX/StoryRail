import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectAsset } from "../api";
import {
  MultiImageAssetPickerDialog,
  SingleAudioAssetPickerDialog,
  SingleImageAssetPickerDialog,
  SingleVideoAssetPickerDialog,
} from "./shared";

function asset(
  index: number,
  overrides: Partial<ProjectAsset> = {},
): ProjectAsset {
  return {
    id: (index + 1).toString(16).repeat(32).slice(0, 32),
    display_name: `备选 ${index}.mp4`,
    media_type: "video/mp4",
    image_category: null,
    byte_count: 1024,
    duration_seconds: 5,
    content_url: `/video-${index}.mp4`,
    is_in_use: false,
    usage_reasons: [],
    retains_derived_assets_on_delete: false,
    allowed_actions: [],
    ...overrides,
  };
}

describe("资产库候选弹窗", () => {
  it("视频候选列表在固定标题之下的可滚动区域中完整列出", () => {
    const assets = Array.from({ length: 12 }, (_, index) =>
      asset(index + 1),
    );
    const onSelect = vi.fn();

    render(
      <SingleVideoAssetPickerDialog
        assets={assets}
        attachedAssetIds={[]}
        busy={false}
        onClose={vi.fn()}
        onSelect={onSelect}
      />,
    );

    const dialog = screen.getByRole("dialog", {
      name: "从资产库增加视频候选",
    });
    const scroller = dialog.querySelector(".scene-asset-picker-scroll");
    expect(scroller).not.toBeNull();
    expect(dialog).toHaveClass("scene-asset-picker-dialog");
    // 标题与关闭按钮固定在滚动区域之外，只有候选列表滚动。
    expect(scroller!.contains(dialog.querySelector("header"))).toBe(false);
    expect(
      within(dialog).getByRole("heading", { name: "增加视频候选" }),
    ).toBeInTheDocument();
    expect(scroller!.querySelectorAll(":scope > .scene-asset-picker-grid"))
      .toHaveLength(1);
    const options = within(dialog).getAllByRole("button", { name: /^增加 / });
    expect(options).toHaveLength(assets.length);
    for (const option of options)
      expect(scroller!.contains(option)).toBe(true);
  });

  it("没有可用资产时滚动区域仍保留为空状态占位", () => {
    render(
      <SingleVideoAssetPickerDialog
        assets={[]}
        attachedAssetIds={[]}
        busy={false}
        onClose={vi.fn()}
        onSelect={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", {
      name: "从资产库增加视频候选",
    });
    const scroller = dialog.querySelector(".scene-asset-picker-scroll")!;
    expect(scroller).toHaveTextContent("项目中还没有不短于 0.2 秒的 MP4 视频。");
  });

  it("音频与图片候选列表同样位于可滚动区域中", () => {
    const audioView = render(
      <SingleAudioAssetPickerDialog
        assets={[
          asset(1, {
            display_name: "旁白 1.wav",
            media_type: "audio/wav",
            content_url: "/voice-1.wav",
          }),
        ]}
        busy={false}
        onClose={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    const audioDialog = screen.getByRole("dialog", {
      name: "添加音频",
    });
    expect(
      audioDialog.querySelector(
        ".scene-asset-picker-scroll > .audio-asset-picker-list",
      ),
    ).toContainElement(
      within(audioDialog).getByRole("button", { name: "选择 旁白 1.wav" }),
    );
    audioView.unmount();

    render(
      <MultiImageAssetPickerDialog
        title="添加 Ref2VA 附加图片"
        ariaLabel="添加 Ref2VA 附加图片"
        assets={[
          asset(2, {
            display_name: "地点视图.png",
            media_type: "image/png",
            image_category: "location_image",
            content_url: "/scene.png",
          }),
        ]}
        selectedAssetIds={[]}
        maxSelected={4}
        busy={false}
        onClose={vi.fn()}
        onChange={vi.fn()}
      />,
    );
    const imageDialog = screen.getByRole("dialog", {
      name: "添加 Ref2VA 附加图片",
    });
    expect(
      imageDialog.querySelector(
        ".scene-asset-picker-scroll > .scene-asset-picker-grid",
      ),
    ).toContainElement(
      within(imageDialog).getByRole("button", { name: "选择 地点视图.png" }),
    );
  });
});

it("单图选择弹窗只滚动图片网格，标题与关闭按钮固定", () => {
  const images = Array.from({ length: 30 }, (_, index) =>
    asset(index, { display_name: `图 ${index}.png`, media_type: "image/png", duration_seconds: null }),
  );
  render(
    <SingleImageAssetPickerDialog
      title="选择首帧"
      ariaLabel="从资产库选择首帧"
      assets={images}
      selectedAssetId={null}
      busy={false}
      onClose={vi.fn()}
      onSelect={vi.fn()}
    />,
  );
  const dialog = screen.getByRole("dialog", { name: "从资产库选择首帧" });
  const scroller = dialog.querySelector(".scene-asset-picker-scroll");
  expect(scroller).not.toBeNull();
  expect(scroller!.contains(dialog.querySelector("header"))).toBe(false);
  expect(scroller!.querySelectorAll(":scope > .scene-asset-picker-grid")).toHaveLength(1);
  expect(within(scroller as HTMLElement).getAllByRole("button", { name: /^选择 / })).toHaveLength(30);
  // 每张缩略图另有一个只放大、不选择的角落按钮。
  expect(within(scroller as HTMLElement).getAllByRole("button", { name: /^查看全图：/ })).toHaveLength(30);
});
