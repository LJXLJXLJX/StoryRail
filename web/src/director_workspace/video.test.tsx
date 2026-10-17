import { videoState } from "../test/video_fixture";
import { fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type {
  ProjectAsset,
  ShotSegment,
  StructuredDirectorAction,
  StructuredDirectorSnapshot,
} from "../api";
import fixture from "../test/story_reader_fixture.json";
import { SegmentVideoPanel } from "./video";

it("导演台上移其他图片后视频卡不重复渲染 reference_image 槽位", () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.video_plan!.segments.find(
    (item) => item.active_recipe === "minimax_h3.ref2va",
  )!;
  plan.recipe_state = videoState(plan.active_recipe!);
  const segment = snapshot.director_script!.scenes
    .flatMap((scene) => scene.shots)
    .flatMap((shot) => shot.segments)
    .find((item) => item.id === plan.segment_id) as ShotSegment;

  render(
    <SegmentVideoPanel
      snapshot={snapshot}
      segment={segment}
      busy={false}
      dependenciesEditable
      preparing={false}
      hideReferenceImageSlots
      onSave={vi.fn()}
      onSaveRecipe={vi.fn()}
      onGenerate={vi.fn()}
      onAttachCandidate={vi.fn()}
      onSelect={vi.fn()}
      onClearSelection={vi.fn()}
      onDismiss={vi.fn()}
      onUpscale={vi.fn()}
    />,
  );

  expect(screen.queryByLabelText("Ref2VA 附加图片")).toBeNull();
  expect(screen.getByLabelText("Ref2VA 参考音频")).toBeInTheDocument();
  expect(screen.getByLabelText("Ref2VA 参考视频")).toBeInTheDocument();
});

it("Ref2VA 在首尾帧右侧纵向编辑小尺寸附加图及必填描述", async () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.video_plan!.segments.find(
    (item) => item.active_recipe === "minimax_h3.ref2va",
  )!;
  plan.recipes[plan.active_recipe!] ??= { bindings: {}, params: {} };
  plan.recipe_state = videoState(plan.active_recipe!);
  plan.prompt_text = "仅使用图片参考保持场景一致。";
  plan.recipes["minimax_h3.ref2va"] ??= { bindings: {}, params: {} };
  plan.recipes["minimax_h3.ref2va"].bindings.reference_audios = [];
  const segment = snapshot.director_script!.scenes
    .flatMap((scene) => scene.shots)
    .flatMap((shot) => shot.segments)
    .find((item) => item.id === plan.segment_id) as ShotSegment;
  const binding = snapshot.keyframe_plan!.segments.find(
    (item) => item.segment_id === segment.id,
  )!;
  binding.start_enabled = true;
  binding.end_enabled = true;
  snapshot.assets.push(
    ...[0, 1, 2].map((index): ProjectAsset => ({
      id: String(index + 1).repeat(32),
      display_name: `附加图 ${index + 1}`,
      media_type: "image/png",
      image_category: "keyframe" as const,
      byte_count: 32,
      duration_seconds: null,
      content_url: `/image-${index + 1}.png`,
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    })),
    {
      id: "a".repeat(32),
      display_name: "原始对白",
      media_type: "audio/wav",
      image_category: null,
      byte_count: 64,
      duration_seconds: 4,
      content_url: "/dialogue.wav",
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    },
    ...[
      { id: "8".repeat(32), display_name: "短音效", duration_seconds: 0.5 },
      { id: "9".repeat(32), display_name: "长环境声", duration_seconds: 42 },
    ].map((item) => ({
      ...item,
      media_type: "audio/wav" as const,
      image_category: null,
      byte_count: 64,
      content_url: `/${item.id}.wav`,
      is_in_use: false,
      usage_reasons: [],
      retains_derived_assets_on_delete: false,
      allowed_actions: [],
    })),
  );
  const images = snapshot.assets.filter((asset) =>
    asset.media_type.startsWith("image/"),
  );
  expect(images.length).toBeGreaterThanOrEqual(3);
  snapshot.keyframe_plan!.keyframes.find(
    (item) => item.id === binding.start_keyframe_id,
  )!.selected_asset_id = images[0].id;
  snapshot.keyframe_plan!.keyframes.find(
    (item) => item.id === binding.end_keyframe_id,
  )!.selected_asset_id = images[1].id;
  snapshot.allowed_actions = [
    ...new Set([
      ...snapshot.allowed_actions,
      "edit_segment_video_plan",
      "generate_segment_video",
    ]),
  ] as StructuredDirectorAction[];
  snapshot.generations = [];
  const onSave = vi.fn();

  const view = render(
    <SegmentVideoPanel
      snapshot={snapshot}
      segment={segment}
      busy={false}
      dependenciesEditable
      preparing={false}
      onSave={onSave}
      onSaveRecipe={vi.fn()}
      onPreview={vi.fn().mockResolvedValue(videoState("blocked"))}
      onGenerate={vi.fn()}
      onAttachCandidate={vi.fn()}
      onSelect={vi.fn()}
      onClearSelection={vi.fn()}
      onDismiss={vi.fn()}
      onUpscale={vi.fn()}
    />,
  );

  const layout = screen.getByLabelText("Ref2VA 媒体输入");
  expect(layout.querySelectorAll(".segment-video-boundary-frame")).toHaveLength(2);
  expect(within(layout).getByText("<Picture 1> · 首帧")).toBeInTheDocument();
  expect(within(layout).getByText("<Picture 2> · 尾帧")).toBeInTheDocument();
  expect(
    within(screen.getByLabelText("Ref2VA 参考音频")).getByText(
      "未添加参考音频。",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "生成一个视频候选" }),
  ).toBeEnabled();

  fireEvent.click(within(layout).getByRole("button", { name: "添加附加图片" }));
  const picker = screen.getByRole("dialog", {
    name: "添加 Ref2VA 附加图片",
  });
  fireEvent.click(within(picker).getAllByRole("button", { name: /^选择 / })[2]);

  const description = screen.getByRole("textbox", {
    name: "附加图片 1 描述",
  });
  expect(within(layout).getByText("<Picture 3>")).toBeInTheDocument();
  expect(description).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "保存视频计划" })).toBeDisabled();

  fireEvent.change(description, {
    target: { value: "保持画面中红色行李箱的形状与材质一致。" },
  });

  fireEvent.click(
    within(screen.getByLabelText("Ref2VA 参考音频")).getByRole("button", {
      name: "添加参考音频",
    }),
  );
  const audioPicker = screen.getByRole("dialog", {
    name: "添加 Ref2VA 参考音频",
  });
  // 参考音频不限时长：短于 2 秒和长于 15 秒的 WAV 都可选。
  expect(within(audioPicker).getByRole("button", { name: "选择 短音效" })).toBeInTheDocument();
  expect(within(audioPicker).getByRole("button", { name: "选择 长环境声" })).toBeInTheDocument();
  fireEvent.click(
    within(audioPicker).getByRole("button", { name: "选择 原始对白" }),
  );
  const audioDescription = screen.getByRole("textbox", {
    name: "参考音频 1 描述",
  });
  expect(screen.getByText("<Audio 1>")).toBeInTheDocument();
  expect(audioDescription).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "保存视频计划" })).toBeDisabled();
  fireEvent.change(audioDescription, {
    target: { value: "这段对白需要按原内容呈现。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存视频计划" }));
  expect(onSave).toHaveBeenCalledWith(segment.id, plan.prompt_text, {bindings: {additional_images: [
    {
      asset_id: images[2].id,
      description: "保持画面中红色行李箱的形状与材质一致。",
    },
  ], reference_audios: [
    {
      asset_id: "a".repeat(32),
      description: "这段对白需要按原内容呈现。",
    },
  ], reference_videos: []}, params: {}});
  await waitFor(() => expect(screen.getByRole("option", { name: "FL2VA" })).toBeDisabled());
  expect(
    view.container.querySelector(".segment-video-additional-references > article"),
  ).not.toBeNull();
});

function videoAsset(id: string, name: string, duration: number): ProjectAsset {
  return {
    id,
    display_name: name,
    media_type: "video/mp4",
    image_category: null,
    byte_count: 4096,
    duration_seconds: duration,
    content_url: `/${id}.mp4`,
    is_in_use: false,
    usage_reasons: [],
    retains_derived_assets_on_delete: false,
    allowed_actions: [],
  };
}

function ref2vaVideoSnapshot() {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.video_plan!.segments.find(
    (item) => item.active_recipe === "minimax_h3.ref2va",
  )!;
  plan.recipes[plan.active_recipe!] ??= { bindings: {}, params: {} };
  plan.recipe_state = videoState(plan.active_recipe!);
  plan.prompt_text = "参考视频中的运镜节奏。";
  plan.recipe_state = videoState(plan.active_recipe!);
  plan.recipes["minimax_h3.ref2va"] ??= { bindings: {}, params: {} };
  plan.recipes["minimax_h3.ref2va"].bindings.additional_images = [];
  plan.recipes["minimax_h3.ref2va"] ??= { bindings: {}, params: {} };
  plan.recipes["minimax_h3.ref2va"].bindings.reference_audios = [];
  plan.recipes["minimax_h3.ref2va"].bindings.reference_videos = [];
  const segment = snapshot.director_script!.scenes
    .flatMap((scene) => scene.shots)
    .flatMap((shot) => shot.segments)
    .find((item) => item.id === plan.segment_id) as ShotSegment;
  snapshot.assets.push(
    videoAsset("b".repeat(32), "运镜参考", 4),
    videoAsset("c".repeat(32), "动作参考", 2),
    videoAsset("d".repeat(32), "过长素材", 20),
    videoAsset("e".repeat(32), "过短素材", 1.5),
  );
  snapshot.allowed_actions = [
    ...new Set([...snapshot.allowed_actions, "edit_segment_video_plan"]),
  ] as StructuredDirectorAction[];
  snapshot.generations = [];
  return { snapshot, plan, segment };
}

it("Ref2VA 参考视频只列 2–15 秒 MP4，按添加顺序编号并要求必填说明", async () => {
  const { snapshot, plan, segment } = ref2vaVideoSnapshot();
  const onSave = vi.fn();
  render(
    <SegmentVideoPanel
      snapshot={snapshot}
      segment={segment}
      busy={false}
      dependenciesEditable
      preparing={false}
      onSave={onSave}
      onSaveRecipe={vi.fn()}
      onPreview={vi.fn().mockResolvedValue(videoState("blocked"))}
      onGenerate={vi.fn()}
      onAttachCandidate={vi.fn()}
      onSelect={vi.fn()}
      onClearSelection={vi.fn()}
      onDismiss={vi.fn()}
      onUpscale={vi.fn()}
    />,
  );

  const section = screen.getByLabelText("Ref2VA 参考视频");
  expect(within(section).getByText("0/3")).toBeInTheDocument();
  expect(within(section).getByText("未添加参考视频。")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "FL2VA" })).toBeEnabled();

  fireEvent.click(within(section).getByRole("button", { name: "添加参考视频" }));
  let picker = screen.getByRole("dialog", { name: "添加 Ref2VA 参考视频" });
  expect(within(picker).getByRole("button", { name: "增加 运镜参考" })).toBeInTheDocument();
  expect(within(picker).getByRole("button", { name: "增加 动作参考" })).toBeInTheDocument();
  expect(within(picker).queryByRole("button", { name: /过长素材/ })).toBeNull();
  expect(within(picker).queryByRole("button", { name: /过短素材/ })).toBeNull();
  fireEvent.click(within(picker).getByRole("button", { name: "增加 动作参考" }));

  fireEvent.click(within(section).getByRole("button", { name: "添加参考视频" }));
  picker = screen.getByRole("dialog", { name: "添加 Ref2VA 参考视频" });
  // 已添加的视频不再出现在可选列表中，不能重复引用。
  expect(within(picker).queryByRole("button", { name: /动作参考/ })).toBeNull();
  fireEvent.click(within(picker).getByRole("button", { name: "增加 运镜参考" }));

  expect(within(section).getByText("2/3")).toBeInTheDocument();
  expect(within(section).getByText("<Video 1>")).toBeInTheDocument();
  expect(within(section).getByText("<Video 2>")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("option", { name: "FL2VA" })).toBeDisabled());
  expect(
    within(section).getByText("每条参考视频都必须填写说明后才能保存。"),
  ).toBeInTheDocument();
  const save = screen.getByRole("button", { name: "保存视频计划" });
  expect(save).toBeDisabled();

  const first = screen.getByRole("textbox", { name: "参考视频 1 描述" });
  expect(first).toHaveAttribute("maxLength", "2000");
  fireEvent.change(first, { target: { value: "  参考人物转身动作。  " } });
  fireEvent.change(screen.getByRole("textbox", { name: "参考视频 2 描述" }), {
    target: { value: "参考整体运镜节奏。" },
  });
  expect(save).toBeEnabled();
  fireEvent.click(save);
  expect(onSave).toHaveBeenCalledWith(segment.id, plan.prompt_text, {bindings: {additional_images: [], reference_audios: [], reference_videos: [
    { asset_id: "c".repeat(32), description: "参考人物转身动作。" },
    { asset_id: "b".repeat(32), description: "参考整体运镜节奏。" },
  ]}, params: {}});

  fireEvent.click(within(section).getAllByRole("button", { name: "移除参考视频" })[0]);
  expect(within(section).getByText("1/3")).toBeInTheDocument();
  expect(within(section).queryByText("<Video 2>")).toBeNull();
  expect(screen.getByRole("textbox", { name: "参考视频 1 描述" })).toHaveValue(
    "参考整体运镜节奏。",
  );
});

it("参考视频达到 3 条上限后禁止继续添加，FL2VA 卡片不显示参考视频区", () => {
  const { snapshot, plan, segment } = ref2vaVideoSnapshot();
  snapshot.assets.push(videoAsset("f".repeat(32), "续写参考", 6));
  plan.recipes["minimax_h3.ref2va"].bindings.reference_videos = [
    { asset_id: "b".repeat(32), description: "运镜。" },
    { asset_id: "c".repeat(32), description: "动作。" },
    { asset_id: "f".repeat(32), description: "续写。" },
  ];
  const props = {
    busy: false,
    dependenciesEditable: true,
    preparing: false,
    onSave: vi.fn(),
    onSaveRecipe: vi.fn(),
    onGenerate: vi.fn(),
    onAttachCandidate: vi.fn(),
    onSelect: vi.fn(),
    onClearSelection: vi.fn(),
    onDismiss: vi.fn(),
    onUpscale: vi.fn(),
  };
  const view = render(
    <SegmentVideoPanel snapshot={snapshot} segment={segment} {...props} />,
  );
  const section = screen.getByLabelText("Ref2VA 参考视频");
  expect(within(section).getByText("3/3")).toBeInTheDocument();
  expect(within(section).getByText("<Video 3>")).toBeInTheDocument();
  expect(within(section).getByRole("button", { name: "添加参考视频" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "保存视频计划" })).toBeDisabled();
  view.unmount();

  const fl2va = structuredClone(snapshot);
  const fl2vaPlan = fl2va.video_plan!.segments.find(
    (item) => item.segment_id === plan.segment_id,
  )!;
  fl2vaPlan.active_recipe = "minimax_h3.fl2va";
  fl2vaPlan.recipe_state = videoState("minimax_h3.fl2va");
  fl2vaPlan.recipes["minimax_h3.ref2va"].bindings.reference_videos = [];
  render(<SegmentVideoPanel snapshot={fl2va} segment={segment} {...props} />);
  expect(screen.queryByLabelText("Ref2VA 参考视频")).toBeNull();
});

it("已选视频卡片可以按帧号从当前视频抽帧", async () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.video_plan!.segments[0];
  const segment = snapshot.director_script!.scenes
    .flatMap((scene) => scene.shots)
    .flatMap((shot) => shot.segments)
    .find((item) => item.id === plan.segment_id) as ShotSegment;
  const videoId = "f".repeat(32);
  plan.selected_asset_id = videoId;
  snapshot.assets.push({
    id: videoId,
    display_name: "已选片段.mp4",
    media_type: "video/mp4",
    image_category: null,
    byte_count: 4096,
    duration_seconds: 5.8,
    content_url: "/selected.mp4",
    is_in_use: false,
    usage_reasons: [],
    retains_derived_assets_on_delete: false,
    allowed_actions: ["video_frame"],
  });
  snapshot.generations = [{
    id: "e".repeat(32),
    kind: "video_frame",
    language: null,
    operation: "process",
    target_id: videoId,
    phase: "submission_uncertain",
    progress: 0,
    message: "上次提交没有建立可恢复任务。",
    prompt_text: "从资产中心提取视频实际尾帧。",
    input_asset_ids: [videoId],
    sample_text: null,
    seed: null,
    duration_seconds: null,
    output_asset_id: null,
    error_code: "transport_error",
    cancellation_requested: false,
    retry_of: null,
    dismissed: false,
    allowed_actions: [],
  }];
  const onExtractVideoFrame = vi.fn();

  render(
    <SegmentVideoPanel
      snapshot={snapshot}
      segment={segment}
      busy={false}
      dependenciesEditable
      preparing={false}
      onSave={vi.fn()}
      onSaveRecipe={vi.fn()}
      onGenerate={vi.fn()}
      onAttachCandidate={vi.fn()}
      onSelect={vi.fn()}
      onClearSelection={vi.fn()}
      onDismiss={vi.fn()}
      onUpscale={vi.fn()}
      onExtractVideoFrame={onExtractVideoFrame}
      onLoadVideoFrameInfo={() => Promise.resolve({ frame_count: 140, duration_seconds: 5.8 })}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "重新抽帧" }));
  const picker = await screen.findByRole("dialog", { name: "从当前视频抽帧" });
  expect(await within(picker).findByText(/可选范围 0-139/)).toBeInTheDocument();
  fireEvent.click(within(picker).getByRole("button", { name: "抽取第 139 帧" }));
  expect(onExtractVideoFrame).toHaveBeenCalledWith(videoId, 139);
});

it("输入已变化的视频候选仍可选择，只给出软提示", () => {
  const snapshot = structuredClone(
    fixture.continuity.production_snapshot,
  ) as unknown as StructuredDirectorSnapshot;
  const plan = snapshot.video_plan!.segments[0];
  plan.selected_asset_id = null;
  const segment = snapshot.director_script!.scenes
    .flatMap((scene) => scene.shots)
    .flatMap((shot) => shot.segments)
    .find((item) => item.id === plan.segment_id) as ShotSegment;
  const freshAsset = "1".repeat(32);
  const staleAsset = "2".repeat(32);
  snapshot.assets.push(
    videoAsset(freshAsset, "当前候选.mp4", 6),
    videoAsset(staleAsset, "过期候选.mp4", 6),
  );
  snapshot.generations = [
    {
      id: "3".repeat(32),
      kind: "segment_video",
      language: null,
      operation: "render",
      target_id: segment.id,
      phase: "succeeded",
      progress: 1,
      message: "基于当前输入生成。",
      prompt_text: "当前提示词。",
      input_asset_ids: [],
      sample_text: null,
      seed: null,
      duration_seconds: 6,
      output_asset_id: freshAsset,
      error_code: null,
      cancellation_requested: false,
      retry_of: null,
      dismissed: false,
      inputs_outdated: false,
      allowed_actions: ["select_segment_video", "dismiss_history"],
    },
    {
      id: "4".repeat(32),
      kind: "segment_video",
      language: null,
      operation: "render",
      target_id: segment.id,
      phase: "succeeded",
      progress: 1,
      message: "输入已变化的历史候选。",
      prompt_text: "旧提示词。",
      input_asset_ids: [],
      sample_text: null,
      seed: null,
      duration_seconds: 6,
      output_asset_id: staleAsset,
      error_code: null,
      cancellation_requested: false,
      retry_of: null,
      dismissed: false,
      inputs_outdated: true,
      allowed_actions: ["select_segment_video", "dismiss_history"],
    },
  ];
  const onSelect = vi.fn();

  render(
    <SegmentVideoPanel
      snapshot={snapshot}
      segment={segment}
      busy={false}
      dependenciesEditable
      preparing={false}
      onSave={vi.fn()}
      onSaveRecipe={vi.fn()}
      onGenerate={vi.fn()}
      onAttachCandidate={vi.fn()}
      onSelect={onSelect}
      onClearSelection={vi.fn()}
      onDismiss={vi.fn()}
      onUpscale={vi.fn()}
    />,
  );

  const freshCard = screen.getByText("基于当前输入生成。").closest("article") as HTMLElement;
  expect(within(freshCard).getByRole("button", { name: "选择候选" })).toBeEnabled();
  expect(within(freshCard).queryByText(/与当前计划不同/)).toBeNull();

  const staleCard = screen
    .getByText("输入已变化的历史候选。")
    .closest("article") as HTMLElement;
  const staleSelect = within(staleCard).getByRole("button", { name: "选择候选" });
  expect(staleSelect).toBeEnabled();
  expect(within(staleCard).getByText(/与当前计划不同/)).toBeInTheDocument();
  fireEvent.click(staleSelect);
  expect(onSelect).toHaveBeenCalledWith(segment.id, staleAsset);
});

it("本次视频时长直接显示 Core 预览值，超过十秒保持完整", () => {
  const { snapshot, plan, segment } = ref2vaVideoSnapshot();
  plan.recipe_state = { ...videoState("minimax_h3.ref2va"), duration_seconds: 17.2 };
  segment.duration_estimate_seconds = 20;
  render(<SegmentVideoPanel snapshot={snapshot} segment={segment} busy={false} dependenciesEditable preparing={false}
    onSave={vi.fn()} onSaveRecipe={vi.fn()} onGenerate={vi.fn()} onAttachCandidate={vi.fn()} onSelect={vi.fn()} onClearSelection={vi.fn()} onDismiss={vi.fn()} onUpscale={vi.fn()} />);
  expect(screen.getByText("17.2 秒 · 16:9")).toBeInTheDocument();
  expect(screen.getByText("超过 15 秒软约束，可能 OOM；仍可生成")).toBeInTheDocument();
});
