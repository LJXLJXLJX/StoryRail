import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { StructuredDirectorSnapshot } from "../api";
import { structuredDirectorApi } from "../api";
import fixture from "../test/story_reader_fixture.json";
import { SegmentKeyframeInputs } from "./keyframe";
import { VideoReferenceImageCard } from "./VideoReferenceImageCard";
import { SegmentVideoDraftProvider } from "./RecipeInputsControl";

it("其他图片规划支持 Esc，并保留草稿确认与嵌套素材窗的关闭边界", () => {
  const snapshot = structuredClone(fixture.continuity.production_snapshot) as unknown as StructuredDirectorSnapshot;
  const command = vi.fn();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<VideoReferenceImageCard snapshot={snapshot} segmentId="segment" sceneId="scene"
    index={3} label="其他图片 4" disabled={false} selectionDisabled={false}
    onCommand={command} onChoose={vi.fn()} onRemove={vi.fn()} onDescribe={vi.fn()} />);
  const open = screen.getByRole("button", { name: "规划 / 编辑" });
  fireEvent.click(open);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.click(open);
  const editor = screen.getByRole("dialog", { name: "规划其他图片 4" });
  const input = within(editor).getByRole("textbox", { name: "参考图片用途" });
  fireEvent.change(input, { target: { value: "展示道具" } });
  fireEvent.click(within(editor).getByRole("button", { name: "选择生图参考" }));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "参考图片生图输入" })).not.toBeInTheDocument();
  expect(editor).toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
  input.focus();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(confirm).toHaveBeenCalledWith("关闭并放弃未保存的图片规划？");
  expect(input).toHaveValue("展示道具");
  confirm.mockReturnValue(true);
  fireEvent.keyDown(input, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(command).not.toHaveBeenCalled();
  fireEvent.click(open);
  expect(screen.getByRole("textbox", { name: "参考图片用途" })).toHaveValue("");
  confirm.mockRestore();
});

it("Ref2VA 其他图片在首尾帧下方分别从关键帧与资产库选择并写回 recipe 输入簿", () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const video = snapshot.video_plan!.segments.find(
    (item) => item.active_recipe === "minimax_h3.ref2va",
  )!;
  const otherKeyframe = snapshot.keyframe_plan!.keyframes.find(
    (item) => item.owner_segment_id !== video.segment_id,
  )!;
  const keyframeAssetId = "6".repeat(32);
  const referenceAssetId = "7".repeat(32);
  const activeBoundaryAssetId = "8".repeat(32);
  const disabledBoundaryAssetId = "9".repeat(32);
  otherKeyframe.selected_asset_id = keyframeAssetId;
  const segmentBinding = snapshot.keyframe_plan!.segments.find(
    (item) => item.segment_id === video.segment_id,
  )!;
  segmentBinding.start_enabled = true;
  segmentBinding.end_enabled = false;
  snapshot.keyframe_plan!.keyframes.find(
    (item) => item.id === segmentBinding.start_keyframe_id,
  )!.selected_asset_id = activeBoundaryAssetId;
  snapshot.keyframe_plan!.keyframes.find(
    (item) => item.id === segmentBinding.end_keyframe_id,
  )!.selected_asset_id = disabledBoundaryAssetId;
  video.prompt_text = "人物从控制台旁转身。";
  video.recipes[video.active_recipe!] = {
    bindings: {
      additional_images: [],
      reference_audios: [],
      reference_videos: [],
    },
    params: {},
  };
  snapshot.allowed_actions = [
    ...new Set([
      ...snapshot.allowed_actions,
      "edit_segment_video_plan" as const,
    ]),
  ];
  snapshot.assets.push(
    {
      id: keyframeAssetId,
      display_name: "另一镜头关键帧.png",
      media_type: "image/png",
      image_category: "keyframe",
      byte_count: 1024,
      duration_seconds: null,
      content_url: "/other-keyframe.png",
      is_in_use: true,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    },
    {
      id: "5".repeat(32),
      display_name: "手动导入未采用关键帧.png",
      media_type: "image/png",
      image_category: "keyframe",
      byte_count: 1024,
      duration_seconds: null,
      content_url: "/imported-keyframe.png",
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    },
    {
      id: referenceAssetId,
      display_name: "控制台参考图.png",
      media_type: "image/png",
      image_category: "location_image",
      byte_count: 1024,
      duration_seconds: null,
      content_url: "/console-reference.png",
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    },
    ...[
      [activeBoundaryAssetId, "已启用首帧.png"],
      [disabledBoundaryAssetId, "已停用尾帧.png"],
    ].map(([id, displayName]) => ({
      id,
      display_name: displayName,
      media_type: "image/png" as const,
      image_category: "keyframe" as const,
      byte_count: 1024,
      duration_seconds: null,
      content_url: `/${id}.png`,
      is_in_use: true,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    })),
  );
  const onSaveVideoInputs = vi.fn();
  render(
    <SegmentVideoDraftProvider snapshot={snapshot} segmentId={video.segment_id}>
      <SegmentKeyframeInputs
        projectId={"a".repeat(32)}
        snapshot={snapshot}
        segmentId={video.segment_id}
        sceneIndex={0}
        segmentIndex={0}
        continuesPrevious={false}
        continuesNext={false}
        busy={false}
        videoDependenciesEditable
        onSaveVideoInputs={onSaveVideoInputs}
        onSaveKeyframe={vi.fn()}
        onGenerate={vi.fn()}
        onSelect={vi.fn()}
        onSaveReferences={vi.fn()}
        onSaveActivation={vi.fn()}
        onDismissGeneration={vi.fn()}
      />
    </SegmentVideoDraftProvider>,
  );

  const section = screen.getByLabelText("Segment 其他图片");
  expect(within(section).getByText("0/4")).toBeInTheDocument();
  fireEvent.click(
    within(section).getAllByRole("button", { name: "从关键帧选择" })[0],
  );
  let dialog = screen.getByRole("dialog", {
    name: "从关键帧选择其他图片",
  });
  expect(
    within(dialog).queryByRole("button", { name: "选择 已启用首帧.png" }),
  ).toBeNull();
  expect(
    within(dialog).getByRole("button", { name: "选择 已停用尾帧.png" }),
  ).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: "选择 另一镜头关键帧.png",
    }),
  );
  expect(
    within(section).getByText(
      new RegExp(`关键帧 @${otherKeyframe.id.slice(0, 6)}`),
    ),
  ).toBeInTheDocument();
  const keyframeDescription = within(section).getByRole("textbox", {
    name: "其他图片 1 描述",
  });
  expect(keyframeDescription).toHaveAttribute("aria-invalid", "true");
  fireEvent.change(keyframeDescription, {
    target: { value: "保持角色转身前的服装和发型一致。" },
  });

  fireEvent.click(
    within(section).getAllByRole("button", { name: "从资产库选择参考图" })[1],
  );
  dialog = screen.getByRole("dialog", { name: "从资产库选择其他图片" });
  expect(
    within(dialog).queryByRole("button", {
      name: "选择 另一镜头关键帧.png",
    }),
  ).toBeNull();
  expect(
    within(dialog).getByRole("button", {
      name: "选择 手动导入未采用关键帧.png",
    }),
  ).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "选择 控制台参考图.png" }),
  );
  fireEvent.change(
    within(section).getByRole("textbox", { name: "其他图片 2 描述" }),
    { target: { value: "保持控制台按键布局和红色确认灯一致。" } },
  );
  fireEvent.click(
    within(section).getByRole("button", { name: "保存其他图片" }),
  );

  expect(onSaveVideoInputs).toHaveBeenCalledOnce();
  const [savedSegmentId, savedPrompt, savedInputs] =
    onSaveVideoInputs.mock.calls[0];
  expect(savedSegmentId).toBe(video.segment_id);
  expect(savedPrompt).toBe(video.prompt_text);
  expect(savedInputs.bindings.additional_images).toEqual([
    {
      asset_id: keyframeAssetId,
      description: "保持角色转身前的服装和发型一致。",
    },
    {
      asset_id: referenceAssetId,
      description: "保持控制台按键布局和红色确认灯一致。",
    },
  ]);
});

it("独立首帧可以按帧号从上一 Segment 已采用视频抽取候选", async () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.keyframe_plan!;
  const [previous, binding] = plan.segments;
  const startId = "9".repeat(32);
  const videoId = "8".repeat(32);
  const source = plan.keyframes.find(
    (item) => item.id === binding.start_keyframe_id,
  )!;
  plan.keyframes.push({
    ...source,
    id: startId,
    owner_segment_id: binding.segment_id,
    predecessor_keyframe_id: null,
  });
  plan.keyframes = plan.keyframes.map((item) =>
    item.id === binding.end_keyframe_id
      ? { ...item, predecessor_keyframe_id: startId }
      : item,
  );
  binding.start_keyframe_id = startId;
  binding.start_frame_extraction = {
    source_segment_id: previous.segment_id,
    source_video_asset_id: videoId,
    state: "ready",
    message: "可以从上一段视频抽取。",
  };
  snapshot.allowed_actions = [
    ...snapshot.allowed_actions,
    "extract_video_frame",
  ];
  snapshot.assets.push({
    id: videoId,
    display_name: "上一段.mp4",
    media_type: "video/mp4",
    image_category: null,
    byte_count: 4096,
    duration_seconds: 4,
    content_url: "/previous.mp4",
    is_in_use: true,
    usage_reasons: [],
    retains_derived_assets_on_delete: false,
    allowed_actions: ["video_frame"],
  });
  const onExtractFrame = vi.fn();
  const onSaveBoundary = vi.fn();
  render(
    <SegmentKeyframeInputs
      projectId={"a".repeat(32)}
      snapshot={snapshot}
      segmentId={binding.segment_id}
      sceneIndex={0}
      segmentIndex={1}
      continuesPrevious
      continuesNext={false}
      busy={false}
      onSaveKeyframe={vi.fn()}
      onGenerate={vi.fn()}
      onSelect={vi.fn()}
      onSaveReferences={vi.fn()}
      onSaveActivation={vi.fn()}
      onSaveBoundary={onSaveBoundary}
      onExtractFrame={onExtractFrame}
      onLoadVideoFrameInfo={() =>
        Promise.resolve({ frame_count: 96, duration_seconds: 4 })
      }
      onDismissGeneration={vi.fn()}
    />,
  );
  expect(screen.getByText(/独立首帧 · @/)).toBeInTheDocument();
  const share = screen.getByRole("checkbox", { name: "与上一段尾帧共享" });
  expect(share).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "从上一 seg 抽取" }));
  const picker = await screen.findByRole("dialog", {
    name: "从上一 Segment 视频抽取首帧",
  });
  expect(await within(picker).findByText(/可选范围 0-95/)).toBeInTheDocument();
  fireEvent.change(within(picker).getByLabelText("抽帧帧号"), {
    target: { value: "90" },
  });
  fireEvent.click(within(picker).getByRole("button", { name: "抽取第 90 帧" }));
  expect(onExtractFrame).toHaveBeenCalledWith(startId, videoId, 90);
  fireEvent.click(share);
  expect(onSaveBoundary).toHaveBeenCalledWith(binding.segment_id, true);
});

it("多套造型须为本帧显式选择，保存只提交选中的那一套", () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.keyframe_plan!;
  const binding = plan.segments.find((item) => item.end_enabled)!;
  const character = snapshot.reference_library.characters[0];
  const [youngId, crownId] = ["1".repeat(32), "2".repeat(32)];
  const [youngLook, crownLook] = ["3".repeat(32), "4".repeat(32)];
  character.looks = [
    {
      id: youngLook,
      name: "青年军服",
      appearance: "军服",
      usage: "青年时期",
      selected_asset_id: youngId,
    },
    {
      id: crownLook,
      name: "加冕华服",
      appearance: "华服",
      usage: "加冕之后",
      selected_asset_id: crownId,
    },
  ];
  for (const id of [youngId, crownId])
    snapshot.assets.push({
      id,
      display_name: `${id.slice(0, 1)}.png`,
      media_type: "image/png",
      image_category: "character_reference",
      byte_count: 64,
      duration_seconds: null,
      content_url: `/${id}.png`,
      is_in_use: true,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    });
  plan.keyframes = plan.keyframes.map((item) =>
    item.id === binding.end_keyframe_id
      ? {
          ...item,
          prompt_text: "小满戴冠。",
          visible_character_ids: [character.id],
        }
      : item,
  );
  vi.spyOn(structuredDirectorApi, "previewKeyframe").mockResolvedValue({
    reference_prompt: "图片引用：",
    instruction: null,
    ready: true,
    operation: "generate",
    attachments: [],
  });
  const onSaveKeyframe = vi.fn();
  render(
    <SegmentKeyframeInputs
      projectId={"a".repeat(32)}
      snapshot={snapshot}
      segmentId={binding.segment_id}
      sceneIndex={0}
      segmentIndex={0}
      continuesPrevious={false}
      continuesNext={false}
      busy={false}
      onSaveKeyframe={onSaveKeyframe}
      onGenerate={vi.fn()}
      onSelect={vi.fn()}
      onSaveReferences={vi.fn()}
      onSaveActivation={vi.fn()}
      onDismissGeneration={vi.fn()}
    />,
  );
  const endSlot = document.querySelector<HTMLElement>(".keyframe-slot.is-end")!;
  fireEvent.click(
    within(endSlot).getByRole("button", { name: "手动修改关键帧计划" }),
  );
  const dialog = screen.getByRole("dialog", { name: "手动修改尾帧关键帧计划" });
  expect(
    within(dialog).getByText(/尚未选择：多套造型必须为本帧选择/),
  ).toBeInTheDocument();
  const crown = within(dialog).getByRole("radio", { name: /加冕华服/ });
  expect(crown).not.toBeChecked();
  fireEvent.click(crown);
  expect(within(dialog).getByText("已选造型「加冕华服」")).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "保存关键帧计划" }),
  );
  expect(onSaveKeyframe).toHaveBeenCalledWith(
    binding.end_keyframe_id,
    binding.segment_id,
    "小满戴冠。",
    [character.id],
    [{ character_id: character.id, look_id: crownLook }],
    [],
  );
});

it("关键帧编辑器不绑定地点视图，手工参考允许选择地点与角色图片", () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const binding = snapshot.keyframe_plan!.segments.find(
    (item) => item.end_enabled,
  )!;
  const locationId = "b".repeat(32);
  const panoramaId = "c".repeat(32);
  const characterId = "d".repeat(32);
  snapshot.assets.push(...[
    { id: locationId, display_name: "地点参考图.png", image_category: "location_image" as const },
    { id: panoramaId, display_name: "地点全景图.png", image_category: "location_image" as const },
    { id: characterId, display_name: "角色造型图.png", image_category: "character_reference" as const },
  ].map((asset) => ({
    ...asset, media_type: "image/png" as const, byte_count: 1024, duration_seconds: null,
    content_url: `/${asset.id}.png`, is_in_use: false, usage_reasons: [],
    retains_derived_assets_on_delete: false, allowed_actions: [],
  })));
  binding.reference_asset_ids = [locationId];
  const onSaveReferences = vi.fn();
  render(
    <SegmentKeyframeInputs
      projectId={"a".repeat(32)}
      snapshot={snapshot}
      segmentId={binding.segment_id}
      sceneIndex={1}
      segmentIndex={1}
      continuesPrevious={false}
      continuesNext={false}
      busy={false}
      onSaveKeyframe={vi.fn()}
      onGenerate={vi.fn()}
      onSelect={vi.fn()}
      onSaveReferences={onSaveReferences}
      onSaveActivation={vi.fn()}
      onDismissGeneration={vi.fn()}
    />,
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "填写关键帧计划" }).at(-1)!,
  );
  const dialog = screen.getByRole("dialog", { name: /手动修改/ });
  expect(within(dialog).queryByLabelText("地点视图")).toBeNull();
  expect(within(dialog).queryByLabelText("地点视图使用方式")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "调整已选的 1 张图片" }));
  const picker = screen.getByRole("dialog", { name: "从资产库选择关键帧参考图片" });
  expect(within(picker).getByRole("button", { name: "取消选择 地点参考图.png" })).toHaveAttribute("aria-pressed", "true");
  expect(within(picker).getByRole("button", { name: "选择 角色造型图.png" })).toBeInTheDocument();
  fireEvent.click(within(picker).getByRole("button", { name: "选择 地点全景图.png" }));
  fireEvent.click(within(picker).getByRole("button", { name: "完成" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "保存图片引用" }));
  expect(onSaveReferences).toHaveBeenCalledWith(binding.segment_id, [locationId, panoramaId]);
});

it("其他图片固定四张子卡片，规划与生成动作携带独立槽位", () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const video = snapshot.video_plan!.segments.find(
    (item) => item.active_recipe === "minimax_h3.ref2va",
  )!;
  const scene = snapshot.director_script!.scenes.find((item) =>
    item.segments.some((segment) => segment.id === video.segment_id),
  )!;
  video.reference_images = [
    {
      id: "a".repeat(32),
      recipe_id: video.active_recipe!,
      slot_index: 0,
      prompt_text: "控制台全貌",
      description: "空间布局",
      visible_character_ids: [],
      character_references: [],
      reference_asset_ids: [],
    },
  ];
  const onReferenceImageAction = vi.fn();
  render(
    <SegmentVideoDraftProvider snapshot={snapshot} segmentId={video.segment_id}>
      <SegmentKeyframeInputs
        projectId="p"
        snapshot={snapshot}
        segmentId={video.segment_id}
        sceneIndex={0}
        segmentIndex={0}
        continuesPrevious={false}
        continuesNext={false}
        busy={false}
        videoDependenciesEditable={true}
        onReferenceImageAction={onReferenceImageAction}
        onSaveVideoInputs={vi.fn()}
        onSaveKeyframe={vi.fn()}
        onGenerate={vi.fn()}
        onSelect={vi.fn()}
        onSaveReferences={vi.fn()}
        onSaveActivation={vi.fn()}
        onDismissGeneration={vi.fn()}
      />
    </SegmentVideoDraftProvider>,
  );
  const section = screen.getByLabelText("Segment 其他图片");
  const cards = within(section).getAllByRole("article");
  expect(cards).toHaveLength(4);
  fireEvent.click(within(cards[0]).getByRole("button", { name: "生成候选" }));
  expect(onReferenceImageAction).toHaveBeenCalledWith(
    "video.generate_reference_image",
    { image_id: "a".repeat(32) },
  );
  fireEvent.click(
    within(cards[2]).getByRole("button", { name: "规划 / 编辑" }),
  );
  const dialog = screen.getByRole("dialog", { name: "规划其他图片 3" });
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: "参考图片用途" }),
    { target: { value: "道具结构" } },
  );
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: "参考图片画面正文" }),
    { target: { value: "正面展示通话器按键布局" } },
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "保存规划" }));
  expect(onReferenceImageAction).toHaveBeenLastCalledWith(
    "video.save_reference_image_plan",
    expect.objectContaining({
      scope: { scene_ids: [scene.id] },
      segment_id: video.segment_id,
      slot_index: 2,
      prompt_text: "正面展示通话器按键布局",
      description: "道具结构",
    }),
  );
});
