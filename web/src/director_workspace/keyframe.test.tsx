import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { StructuredDirectorSnapshot, SubmissionAttachment } from "../api";
import { structuredDirectorApi } from "../api";
import fixture from "../test/story_reader_fixture.json";
import { SegmentKeyframeInputs } from "./keyframe";
import { SegmentVideoDraftProvider } from "./RecipeInputsControl";

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
      id: referenceAssetId,
      display_name: "控制台参考图.png",
      media_type: "image/png",
      image_category: "location_view",
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
    <SegmentVideoDraftProvider
      snapshot={snapshot}
      segmentId={video.segment_id}
    >
      <SegmentKeyframeInputs
        projectId={"a".repeat(32)}
        snapshot={snapshot}
        segmentId={video.segment_id}
        sceneIndex={0}
        shotIndex={0}
        segmentIndex={0}
        segmentCount={1}
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
    within(section).getByRole("button", { name: "从关键帧选择" }),
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
    within(section).getByRole("button", { name: "从资产库选择参考图" }),
  );
  dialog = screen.getByRole("dialog", { name: "从资产库选择其他图片" });
  expect(
    within(dialog).queryByRole("button", {
      name: "选择 另一镜头关键帧.png",
    }),
  ).toBeNull();
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
  const source = plan.keyframes.find((item) => item.id === binding.start_keyframe_id)!;
  plan.keyframes.push({ ...source, id: startId, owner_segment_id: binding.segment_id, predecessor_keyframe_id: null });
  plan.keyframes = plan.keyframes.map((item) =>
    item.id === binding.end_keyframe_id ? { ...item, predecessor_keyframe_id: startId } : item,
  );
  binding.start_keyframe_id = startId;
  binding.start_frame_extraction = {
    source_segment_id: previous.segment_id,
    source_video_asset_id: videoId,
    state: "ready",
    message: "可以从上一段视频抽取。",
  };
  snapshot.allowed_actions = [...snapshot.allowed_actions, "extract_video_frame"];
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
      shotIndex={0}
      segmentIndex={1}
      segmentCount={2}
      busy={false}
      onSaveKeyframe={vi.fn()}
      onGenerate={vi.fn()}
      onSelect={vi.fn()}
      onSaveReferences={vi.fn()}
      onSaveActivation={vi.fn()}
      onSaveBoundary={onSaveBoundary}
      onExtractFrame={onExtractFrame}
      onLoadVideoFrameInfo={() => Promise.resolve({ frame_count: 96, duration_seconds: 4 })}
      onDismissGeneration={vi.fn()}
    />,
  );
  expect(screen.getByText(/独立首帧 · @/)).toBeInTheDocument();
  const share = screen.getByRole("checkbox", { name: "与上一段尾帧共享" });
  expect(share).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "从上一 seg 抽取" }));
  const picker = await screen.findByRole("dialog", { name: "从上一 Segment 视频抽取首帧" });
  expect(await within(picker).findByText(/可选范围 0-95/)).toBeInTheDocument();
  fireEvent.change(within(picker).getByLabelText("抽帧帧号"), { target: { value: "90" } });
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
    { id: youngLook, name: "青年军服", appearance: "军服", usage: "青年时期", selected_asset_id: youngId },
    { id: crownLook, name: "加冕华服", appearance: "华服", usage: "加冕之后", selected_asset_id: crownId },
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
      ? { ...item, prompt_text: "小满戴冠。", visible_character_ids: [character.id] }
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
      shotIndex={0}
      segmentIndex={0}
      segmentCount={1}
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
  fireEvent.click(within(endSlot).getByRole("button", { name: "手动修改关键帧计划" }));
  const dialog = screen.getByRole("dialog", { name: "手动修改尾帧关键帧计划" });
  expect(within(dialog).getByText(/尚未选择：多套造型必须为本帧选择/)).toBeInTheDocument();
  const crown = within(dialog).getByRole("radio", { name: /加冕华服/ });
  expect(crown).not.toBeChecked();
  fireEvent.click(crown);
  expect(within(dialog).getByText("已选造型「加冕华服」")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "保存关键帧计划" }));
  expect(onSaveKeyframe).toHaveBeenCalledWith(
    binding.end_keyframe_id,
    binding.segment_id,
    "小满戴冠。",
    [character.id],
    [{ character_id: character.id, look_id: crownLook }],
    [],
    "none",
    null,
    null,
  );
});

// --- 地点视图：选择器过滤、跨地点当前值、none 理由可选、实际提交映射 ---

const [VIEW_MAIN, VIEW_UNSELECTED, VIEW_OTHER] = ["5".repeat(32), "6".repeat(32), "7".repeat(32)];

function view(id: string, name: string, purpose: string, selected: string | null) {
  return {
    id,
    name,
    purpose,
    azimuth_deg: 0,
    look_at_fixture_id: null,
    yaw_offset_deg: null,
    pitch_deg: 0,
    hfov_deg: 60,
    state_id: null,
    refine_prompt_text: "",
    reference_view_ids: [],
    crop_asset_id: null,
    selected_asset_id: selected,
  };
}

function location(id: string, name: string, views: ReturnType<typeof view>[]) {
  return {
    id,
    name,
    kind: "interior" as const,
    description: "固定空间。",
    fixtures: [],
    key_light: null,
    master: { prompt_text: "", reference_asset_ids: [], selected_asset_id: null },
    calibrated_master_asset_id: null,
    states: [],
    views,
  };
}

/** 第二个 Scene 绑定「客厅」（两个视图，其一未选图）；另有「走廊」地点。目标为最后一个已启用尾帧的 Segment。 */
function locationSnapshot(environment: {
  mode: "edit" | "reference" | "none";
  viewId: string | null;
  reason: string | null;
}) {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.keyframe_plan!;
  const binding = plan.segments.find((item) => item.end_enabled)!;
  const scene = snapshot.director_script!.scenes.find((item) =>
    item.shots.some((shot) => shot.segments.some((segment) => segment.id === binding.segment_id)),
  )!;
  const [livingId, hallId] = ["3".repeat(32), "4".repeat(32)];
  snapshot.location_library.locations = [
    location(livingId, "客厅", [
      view(VIEW_MAIN, "沙发正面", "人眼高中景", "f".repeat(32)),
      view(VIEW_UNSELECTED, "窗边反打", "过肩反打背景", null),
    ]),
    location(hallId, "走廊", [view(VIEW_OTHER, "走廊尽头", "纵深全景", "e".repeat(32))]),
  ];
  scene.location_id = livingId;
  for (const shot of scene.shots) shot.view_id = VIEW_MAIN;
  plan.keyframes = plan.keyframes.map((item) =>
    item.id === binding.end_keyframe_id
      ? {
          ...item,
          prompt_text: "两人坐下。",
          environment_mode: environment.mode,
          environment_view_id: environment.viewId,
          environment_none_reason: environment.reason,
        }
      : item,
  );
  return { snapshot, binding };
}

function openEndDialog(
  snapshot: StructuredDirectorSnapshot,
  segmentId: string,
  onSaveKeyframe = vi.fn(),
) {
  render(
    <SegmentKeyframeInputs
      projectId={"a".repeat(32)}
      snapshot={snapshot}
      segmentId={segmentId}
      sceneIndex={1}
      shotIndex={1}
      segmentIndex={1}
      segmentCount={2}
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
  fireEvent.click(within(endSlot).getByRole("button", { name: "手动修改关键帧计划" }));
  return screen.getByRole("dialog", { name: "手动修改尾帧关键帧计划" });
}

function mockPreview(attachments: SubmissionAttachment[] = []) {
  return vi.spyOn(structuredDirectorApi, "previewKeyframe").mockResolvedValue({
    reference_prompt: "图片引用：",
    instruction: null,
    ready: true,
    operation: attachments.some((item) => item.role === "source_image") ? "edit" : "generate",
    attachments,
  });
}

it("视图选择器只列本 Scene 地点的视图，未选图标明需要选图，跨地点当前值保留并标明来源", () => {
  mockPreview();
  const { snapshot, binding } = locationSnapshot({
    mode: "reference",
    viewId: VIEW_OTHER,
    reason: null,
  });
  const onSaveKeyframe = vi.fn();
  const dialog = openEndDialog(snapshot, binding.segment_id, onSaveKeyframe);
  const select = within(dialog).getByLabelText("地点视图");
  const options = within(select).getAllByRole("option").map((item) => item.textContent);
  expect(options).toEqual([
    "不使用地点视图",
    "当前值（来自地点「走廊」，不属于本 Scene 地点）· 走廊尽头 · 纵深全景",
    "沙发正面 · 人眼高中景 · Shot 绑定",
    "窗边反打 · 过肩反打背景 · 未选图，生成前需要选图",
  ]);
  expect(select).toHaveValue(VIEW_OTHER);
  expect(within(dialog).getByText(/当前视图来自地点「走廊」/)).toBeInTheDocument();
  expect(within(dialog).getByText(/只列出本 Scene 地点「客厅」的视图/)).toBeInTheDocument();
  fireEvent.change(select, { target: { value: VIEW_UNSELECTED } });
  expect(within(dialog).getByText(/视图「窗边反打」未选图，生成前需要选图/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "保存关键帧计划" }));
  expect(onSaveKeyframe).toHaveBeenCalledWith(
    binding.end_keyframe_id,
    binding.segment_id,
    "两人坐下。",
    [],
    [],
    [],
    "reference",
    VIEW_UNSELECTED,
    null,
  );
});

it("从不使用选回视图时默认作为空间参考；Scene 未绑定地点时没有可选视图并给出提示", () => {
  mockPreview();
  const { snapshot, binding } = locationSnapshot({
    mode: "none",
    viewId: null,
    reason: "黑场",
  });
  const dialog = openEndDialog(snapshot, binding.segment_id);
  fireEvent.change(within(dialog).getByLabelText("地点视图"), {
    target: { value: VIEW_MAIN },
  });
  expect(within(dialog).getByLabelText("地点视图使用方式")).toHaveValue("reference");
  expect(within(dialog).getByText(/默认 reference/)).toBeInTheDocument();
  expect(within(dialog).queryByLabelText("不使用地点视图的理由")).not.toBeInTheDocument();
  cleanup();

  const unbound = locationSnapshot({ mode: "none", viewId: null, reason: "黑场" });
  for (const scene of unbound.snapshot.director_script!.scenes) {
    scene.location_id = null;
    for (const shot of scene.shots) shot.view_id = null;
  }
  const unboundDialog = openEndDialog(unbound.snapshot, unbound.binding.segment_id);
  const select = within(unboundDialog).getByLabelText("地点视图");
  expect(within(select).getAllByRole("option").map((item) => item.textContent)).toEqual([
    "不使用地点视图",
  ]);
  expect(within(unboundDialog).getByText(/本 Scene 尚未绑定地点，没有可选视图/)).toBeInTheDocument();
});

it("选择不使用地点视图时理由可选，空白理由按 null 保存", () => {
  mockPreview();
  const { snapshot, binding } = locationSnapshot({
    mode: "edit",
    viewId: VIEW_MAIN,
    reason: null,
  });
  const onSaveKeyframe = vi.fn();
  const dialog = openEndDialog(snapshot, binding.segment_id, onSaveKeyframe);
  fireEvent.change(within(dialog).getByLabelText("地点视图使用方式"), {
    target: { value: "none" },
  });
  expect(within(dialog).getByLabelText("地点视图")).toHaveValue("");
  const reason = within(dialog).getByLabelText("不使用地点视图的理由");
  expect(reason).toHaveValue("");
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
  const save = within(dialog).getByRole("button", { name: "保存关键帧计划" });
  fireEvent.change(reason, { target: { value: "   " } });
  expect(save).toBeEnabled();
  fireEvent.click(save);
  expect(onSaveKeyframe).toHaveBeenLastCalledWith(
    binding.end_keyframe_id,
    binding.segment_id,
    "两人坐下。",
    [],
    [],
    [],
    "none",
    null,
    null,
  );
  fireEvent.change(reason, { target: { value: "理".repeat(501) } });
  expect(within(dialog).getByRole("alert")).toHaveTextContent("理由最多 500 字");
  expect(save).toBeDisabled();
  fireEvent.change(reason, { target: { value: " 纯黑场过渡，没有环境信息 " } });
  fireEvent.click(save);
  expect(onSaveKeyframe).toHaveBeenLastCalledWith(
    binding.end_keyframe_id,
    binding.segment_id,
    "两人坐下。",
    [],
    [],
    [],
    "none",
    null,
    "纯黑场过渡，没有环境信息",
  );
});

it("实际提交映射按 Core 预览展示视图已选图及其底图或参考位置", async () => {
  const purpose =
    "同一地点该机位的空环境，这是本次图片编辑的底图；保持其中陈设、材质与光线不变，只加入本帧的人物与动作。";
  const preview = mockPreview([
    {
      asset_id: "f".repeat(32),
      display_name: "沙发正面.png",
      content_url: "/view.png",
      role: "source_image",
      input_roles: ["地点视图"],
      purpose: `地点「客厅」的视图「沙发正面」：${purpose}`,
    },
    {
      asset_id: "1".repeat(32),
      display_name: "前一帧.png",
      content_url: "/prev.png",
      role: "reference_image",
      input_roles: ["前置帧"],
      purpose: "前一时间边界 Keyframe；用于保持相邻画面的动作、位置和构图连续。",
    },
  ]);
  const { snapshot, binding } = locationSnapshot({
    mode: "edit",
    viewId: VIEW_MAIN,
    reason: null,
  });
  const dialog = openEndDialog(snapshot, binding.segment_id);
  expect(await within(dialog).findByText("编辑底图 · 地点视图")).toBeInTheDocument();
  expect(within(dialog).getByText(`地点「客厅」的视图「沙发正面」：${purpose}`)).toBeInTheDocument();
  expect(within(dialog).getByText("参考图 · 前置帧")).toBeInTheDocument();
  expect(within(dialog).getByAltText("实际输入图1 沙发正面.png")).toHaveAttribute("src", "/view.png");
  expect(preview).toHaveBeenLastCalledWith(
    "a".repeat(32),
    snapshot.revision,
    binding.end_keyframe_id,
    binding.segment_id,
    "两人坐下。",
    [],
    [],
    [],
    "edit",
    VIEW_MAIN,
    null,
  );
});
