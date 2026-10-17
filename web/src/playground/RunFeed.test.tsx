import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type {
  PlaygroundAsset,
  PlaygroundCapabilityId,
  PlaygroundCapabilityInfo,
  PlaygroundRun,
  PlaygroundRunPhase,
} from "../api";
import { RunCard, outputTargets } from "./RunCard";
import { RunFeed } from "./RunFeed";
import recipeFixture from "../test/playground_recipes.json";
import { RunForm, type RunFormHandle } from "./RunForm";

const LABELS: Record<
  PlaygroundCapabilityId,
  { label: string; execution: "async" | "sync" }
> = {
  "codex_image.generate": { label: "生图", execution: "async" },
  "codex_image.edit": { label: "改图", execution: "async" },
  "breeze_tts2.voice_design": { label: "音色设计 TTS", execution: "async" },
  "breeze_tts2.clone": { label: "声音克隆 TTS", execution: "async" },
  "whisper_asr.transcribe": { label: "语音转写", execution: "sync" },
  "minimax_h3.fl2va": { label: "首尾帧视频", execution: "async" },
  "minimax_h3.ref2va": { label: "参考视频", execution: "async" },
  "seedvr2_7b_sharp_fp8.upscale": { label: "视频超分", execution: "async" },
  "video.extract_frame": { label: "按帧号抽帧", execution: "async" },
  "demucs_audio.separate": { label: "人声/背景分离", execution: "async" },
  "stable_audio_3.generate": { label: "文生音频", execution: "async" },
  "audio.remix": { label: "音轨重新混音", execution: "async" },
  "audio.effect": { label: "音频后处理", execution: "sync" },
  "audio.trim": { label: "音频截取", execution: "sync" },
};

const CAPABILITIES = recipeFixture.capabilities as PlaygroundCapabilityInfo[];

function asset(
  seed: string,
  mediaType: PlaygroundAsset["media_type"],
  displayName: string,
): PlaygroundAsset {
  const id = seed.repeat(32).slice(0, 32);
  return {
    id,
    media_type: mediaType,
    byte_count: 10,
    sha256: seed.repeat(64).slice(0, 64),
    relative_path: `assets/imported/${seed}.bin`,
    duration_seconds: mediaType.startsWith("image/") ? null : 3,
    origin: { kind: "imported" },
    created_at: "2026-01-01T00:00:00+00:00",
    display_name: displayName,
    content_url: `/api/playground/assets/${id}/content`,
    is_in_use: false,
    usage_reasons: [],
    allowed_actions: ["copy_to_project", "delete"],
  };
}

const imageAsset = asset("1", "image/png", "图片一");
const wavAsset = asset("3", "audio/wav", "音频一");
const mp4Asset = asset("4", "video/mp4", "视频一");
const FIXTURE_ASSETS = [imageAsset, wavAsset, mp4Asset];
const missingAssetId = "f".repeat(32);

function runFixture(
  overrides: Partial<PlaygroundRun> & { capability: PlaygroundCapabilityId },
): PlaygroundRun {
  return {
    id: "a".repeat(32),
    capability_label: LABELS[overrides.capability].label,
    phase: "running" as PlaygroundRunPhase,
    progress: 0.5,
    message: "进行中",
    parameters: {},
    input_asset_ids: [],
    seed: 42,
    plugin_id: null,
    plugin_version: null,
    external_id: "task-1",
    output_asset_id: null,
    result: null,
    error_code: null,
    cancellation_requested: false,
    retry_of: null,
    note: null,
    dismissed: false,
    provider: null,
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:10+00:00",
    recovery: {
      failure_origin: null,
      retry_policy: "wait_same_generation",
      automatic_retry_allowed: false,
    },
    allowed_actions: ["set_note"],
    ...overrides,
  };
}

const receipt = {
  command_id: "c".repeat(64),
  status: "succeeded",
  old_revision: 1,
  new_revision: 2,
  decision_summary: "已更新实验。",
};

function okResponse(value: unknown): Response {
  return { ok: true, status: 200, json: async () => value } as Response;
}

function FeedHarness({ runs }: { runs: PlaygroundRun[] }) {
  const [capability, setCapability] =
    useState<PlaygroundCapabilityId>("minimax_h3.fl2va");
  const ref = useRef<RunFormHandle | null>(null);
  return (
    <div>
      <RunForm
        ref={ref}
        capabilities={CAPABILITIES}
        assets={FIXTURE_ASSETS}
        selectedCapability={capability}
        onSubmitted={vi.fn()}
        onRequestAsset={vi.fn()}
      />
      <RunFeed
        runs={runs}
        assets={FIXTURE_ASSETS}
        capabilities={CAPABILITIES}
        highlightRunId={null}
        onUseParameters={(target, parameters) => {
          setCapability(target);
          ref.current?.prefill(target, parameters);
        }}
        onUseAsInput={(target, assetId) => {
          setCapability(target.capability);
          ref.current?.fillSlot(target, assetId);
        }}
        onChanged={vi.fn()}
      />
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("只渲染 allowed_actions 允许的操作按钮", () => {
  const running = runFixture({
    id: "a".repeat(32),
    capability: "minimax_h3.fl2va",
    phase: "running",
    allowed_actions: ["cancel", "set_note"],
  });
  const failed = runFixture({
    id: "b".repeat(32),
    capability: "audio.trim",
    phase: "failed",
    error_code: "provider_error",
    allowed_actions: ["retry", "dismiss", "set_note"],
  });
  render(<FeedHarness runs={[running, failed]} />);
  const runningCard = screen.getByRole("article", { name: "首尾帧视频 实验" });
  expect(
    within(runningCard).getByRole("button", { name: "取消" }),
  ).toBeInTheDocument();
  expect(
    within(runningCard).queryByRole("button", { name: "重试" }),
  ).not.toBeInTheDocument();
  expect(
    within(runningCard).queryByRole("button", { name: "隐藏" }),
  ).not.toBeInTheDocument();
  const failedCard = screen.getByRole("article", { name: "音频截取 实验" });
  expect(
    within(failedCard).getByRole("button", { name: "重试" }),
  ).toBeInTheDocument();
  expect(
    within(failedCard).getByRole("button", { name: "隐藏" }),
  ).toBeInTheDocument();
  expect(
    within(failedCard).queryByRole("button", { name: "取消" }),
  ).not.toBeInTheDocument();
});

it("默认隐藏已隐藏的 run，过滤器只显示匹配项", () => {
  const hidden = runFixture({
    id: "a".repeat(32),
    capability: "codex_image.generate",
    phase: "succeeded",
    dismissed: true,
    allowed_actions: [],
  });
  const visible = runFixture({
    id: "b".repeat(32),
    capability: "audio.trim",
    phase: "succeeded",
    allowed_actions: [],
  });
  render(<FeedHarness runs={[hidden, visible]} />);
  expect(
    screen.queryByRole("article", { name: "生图 实验" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "显示已隐藏" }));
  expect(
    screen.getByRole("article", { name: "生图 实验" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "按能力过滤" }), {
    target: { value: "audio.trim" },
  });
  expect(
    screen.queryByRole("article", { name: "生图 实验" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("article", { name: "音频截取 实验" }),
  ).toBeInTheDocument();
});

it("全部隐藏只隐藏当前能力下允许隐藏的 run", async () => {
  const first = runFixture({
    id: "a".repeat(32),
    capability: "stable_audio_3.generate",
    phase: "succeeded",
    allowed_actions: ["dismiss", "set_note"],
  });
  const second = runFixture({
    id: "b".repeat(32),
    capability: "stable_audio_3.generate",
    phase: "failed",
    allowed_actions: ["retry", "dismiss", "set_note"],
  });
  const running = runFixture({
    id: "c".repeat(32),
    capability: "stable_audio_3.generate",
    phase: "running",
    allowed_actions: ["cancel", "set_note"],
  });
  const other = runFixture({
    id: "d".repeat(32),
    capability: "codex_image.generate",
    phase: "succeeded",
    allowed_actions: ["dismiss", "set_note"],
  });
  const runs = [first, second, running, other];
  const fetcher = vi
    .fn()
    .mockImplementation(async (_url, init: RequestInit) => {
      const { arguments: args } = JSON.parse(String(init.body)) as {
        arguments: { run_id: string };
      };
      const run = runs.find((item) => item.id === args.run_id);
      return okResponse({
        receipt,
        data: { run: { ...run, dismissed: true } },
      });
    });
  vi.stubGlobal("fetch", fetcher);
  const onChanged = vi.fn();
  render(
    <RunFeed
      runs={runs}
      assets={FIXTURE_ASSETS}
      capabilities={CAPABILITIES}
      highlightRunId={null}
      onUseParameters={vi.fn()}
      onUseAsInput={vi.fn()}
      onChanged={onChanged}
    />,
  );
  expect(screen.getByRole("button", { name: "全部隐藏 (3)" })).toBeEnabled();
  fireEvent.change(screen.getByRole("combobox", { name: "按能力过滤" }), {
    target: { value: "stable_audio_3.generate" },
  });
  fireEvent.click(screen.getByRole("button", { name: "全部隐藏 (2)" }));
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认隐藏" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  const calls = fetcher.mock.calls.map(
    ([, init]) =>
      JSON.parse(String((init as RequestInit).body)) as {
        name: string;
        arguments: Record<string, unknown>;
      },
  );
  expect(calls.map((call) => call.name)).toEqual([
    "playground.dismiss_run",
    "playground.dismiss_run",
  ]);
  expect(calls.map((call) => call.arguments.run_id)).toEqual([
    first.id,
    second.id,
  ]);
});

it("用这组参数预填表单，已删除的输入被清空并提示", () => {
  const run = runFixture({
    capability: "minimax_h3.fl2va",
    phase: "succeeded",
    parameters: {
      prompt: "旧提示词",
      aspect_ratio: "16:9",
      duration_seconds: 6,
      seed: 7,
      first_frame_asset_id: missingAssetId,
      last_frame_asset_id: null,
    },
    allowed_actions: [],
  });
  render(<FeedHarness runs={[run]} />);
  fireEvent.click(screen.getByRole("button", { name: "用这组参数" }));
  expect(
    screen.getByText("部分输入素材已删除，已清空对应槽位"),
  ).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "H3 提示词" })).toHaveValue(
    "旧提示词",
  );
  expect(screen.getAllByText("未选择")).toHaveLength(2);
});

it("作为输入把图片产物填进 FL2VA 首帧槽位", () => {
  const run = runFixture({
    capability: "codex_image.generate",
    phase: "succeeded",
    output_asset_id: imageAsset.id,
    allowed_actions: [],
  });
  render(<FeedHarness runs={[run]} />);
  fireEvent.click(screen.getByRole("button", { name: "作为输入 ▾" }));
  fireEvent.click(screen.getByRole("button", { name: "FL2VA · 首帧" }));
  expect(screen.getByText("minimax_h3.fl2va")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "清除（首帧）" })).toBeEnabled();
  expect(screen.getAllByText("图片一").length).toBeGreaterThan(0);
});

it("对比按钮在能力不同时禁用", () => {
  const first = runFixture({
    id: "a".repeat(32),
    capability: "minimax_h3.fl2va",
    phase: "succeeded",
    allowed_actions: [],
  });
  const second = runFixture({
    id: "b".repeat(32),
    capability: "audio.trim",
    phase: "succeeded",
    allowed_actions: [],
  });
  render(<FeedHarness runs={[first, second]} />);
  const checkboxes = screen.getAllByRole("checkbox", { name: /^对比 / });
  fireEvent.click(checkboxes[0]);
  fireEvent.click(checkboxes[1]);
  const button = screen.getByRole("button", { name: "对比所选 (2)" });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("title", "只有同一能力的实验可以对比。");
});

it("同能力对比的差异表只列出取值不同的键", () => {
  const first = runFixture({
    id: "a".repeat(32),
    capability: "minimax_h3.fl2va",
    phase: "succeeded",
    parameters: {
      prompt: "第一组",
      aspect_ratio: "16:9",
      duration_seconds: 6,
      seed: 1,
    },
    allowed_actions: [],
  });
  const second = runFixture({
    id: "b".repeat(32),
    capability: "minimax_h3.fl2va",
    phase: "succeeded",
    parameters: {
      prompt: "第二组",
      aspect_ratio: "16:9",
      duration_seconds: 6,
      seed: 1,
    },
    allowed_actions: [],
  });
  render(<FeedHarness runs={[first, second]} />);
  const checkboxes = screen.getAllByRole("checkbox", { name: /^对比 / });
  fireEvent.click(checkboxes[0]);
  fireEvent.click(checkboxes[1]);
  fireEvent.click(screen.getByRole("button", { name: "对比所选 (2)" }));
  const drawer = screen.getByRole("dialog", { name: "对比所选实验" });
  expect(
    within(drawer).getByRole("rowheader", { name: "prompt" }),
  ).toBeInTheDocument();
  expect(
    within(drawer).queryByRole("rowheader", { name: "aspect_ratio" }),
  ).not.toBeInTheDocument();
  expect(within(drawer).getByText("第一组")).toBeInTheDocument();
  expect(within(drawer).getByText("第二组")).toBeInTheDocument();
});

it("备注回车后发出 set_note 命令", async () => {
  const run = runFixture({
    capability: "minimax_h3.fl2va",
    phase: "running",
    allowed_actions: ["set_note"],
  });
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      okResponse({ receipt, data: { run: { ...run, note: "对比组A" } } }),
    );
  vi.stubGlobal("fetch", fetcher);
  const onChanged = vi.fn();
  render(
    <RunCard
      capabilities={CAPABILITIES}
      run={run}
      assets={FIXTURE_ASSETS}
      onUseParameters={vi.fn()}
      onUseAsInput={vi.fn()}
      onChanged={onChanged}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "备注" }));
  const input = screen.getByRole("textbox", { name: "实验备注" });
  fireEvent.change(input, { target: { value: "对比组A" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const body = JSON.parse(
    String((fetcher.mock.calls[0][1] as RequestInit).body),
  ) as { name: string; arguments: Record<string, unknown> };
  expect(body.name).toBe("playground.set_note");
  expect(body.arguments).toEqual({ run_id: run.id, note: "对比组A" });
  expect(onChanged).toHaveBeenCalled();
});

it("ASR 卡片显示转写文本", () => {
  const run = runFixture({
    capability: "whisper_asr.transcribe",
    phase: "succeeded",
    result: { transcript: "你好世界" },
    allowed_actions: [],
  });
  render(
    <RunCard
      capabilities={CAPABILITIES}
      run={run}
      assets={FIXTURE_ASSETS}
      onUseParameters={vi.fn()}
      onUseAsInput={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  expect(screen.getByText("你好世界")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "复制转写" })).toBeInTheDocument();
});

it("只有 Core 授予 pano_view 的图片产物才出现全景裁切输入目标", () => {
  const label = "全景裁切 · 全景";
  const labels = (item: PlaygroundAsset) =>
    outputTargets(item, CAPABILITIES).map((target) => target.label);
  expect(labels(imageAsset)).not.toContain(label);
  const panorama: PlaygroundAsset = {
    ...imageAsset,
    allowed_actions: ["copy_to_project", "pano_view"],
  };
  expect(labels(panorama)).toContain(label);
  expect(
    outputTargets(panorama, CAPABILITIES).find(
      (target) => target.label === label,
    ),
  ).toMatchObject({ capability: "image.pano_view", key: "image_asset_id" });
});
