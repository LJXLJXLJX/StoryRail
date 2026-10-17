import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type {
  PlaygroundAsset,
  PlaygroundCapabilityId,
  PlaygroundCapabilityInfo,
  PlaygroundRun,
} from "../api";
import { CapabilityList } from "./CapabilityList";
import recipeFixture from "../test/playground_recipes.json";
import { playgroundApi } from "./api";
import { RunForm } from "./RunForm";

const CAPABILITIES = recipeFixture.capabilities as PlaygroundCapabilityInfo[];
const CAPABILITY_IDS = CAPABILITIES.map((item) => item.id);

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
const imageAsset2 = asset("2", "image/jpeg", "图片二");
const wavAsset = asset("3", "audio/wav", "音频一");
const mp4Asset = asset("4", "video/mp4", "视频一");
const FIXTURE_ASSETS = [imageAsset, imageAsset2, wavAsset, mp4Asset];

const run: PlaygroundRun = {
  id: "a".repeat(32),
  capability: "minimax_h3.fl2va",
  capability_label: "首尾帧视频",
  phase: "submitting",
  progress: 0,
  message: "正在提交首尾帧视频任务。",
  parameters: {},
  input_asset_ids: [],
  seed: 42,
  plugin_id: null,
  plugin_version: null,
  external_id: null,
  output_asset_id: null,
  result: null,
  error_code: null,
  cancellation_requested: false,
  retry_of: null,
  note: null,
  dismissed: false,
  provider: null,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
  recovery: {
    failure_origin: null,
    retry_policy: "wait_same_generation",
    automatic_retry_allowed: false,
  },
  allowed_actions: ["cancel", "set_note"],
};

const receipt = {
  command_id: "c".repeat(64),
  status: "succeeded",
  old_revision: 1,
  new_revision: 2,
  decision_summary: "已提交实验。",
};

function okResponse(value: unknown): Response {
  return { ok: true, status: 200, json: async () => value } as Response;
}

function errorResponse(message: string, status: number): Response {
  return {
    ok: false,
    status,
    json: async () => ({
      error: {
        code: "invalid_request",
        message,
        recoverable: false,
        origin: "request",
        state_changed: false,
        retry_policy: "none",
        automatic_retry_allowed: false,
      },
    }),
  } as Response;
}

function Harness({
  initialCapability,
  assets = FIXTURE_ASSETS,
  onSubmitted = vi.fn(),
  images = [imageAsset.id, imageAsset2.id],
}: {
  initialCapability: PlaygroundCapabilityId;
  assets?: PlaygroundAsset[];
  onSubmitted?: (submitted: PlaygroundRun) => void;
  images?: string[];
}) {
  const [capability, setCapability] =
    useState<PlaygroundCapabilityId>(initialCapability);
  const queue = useRef([...images]);
  return (
    <div>
      <select
        aria-label="切换能力"
        value={capability}
        onChange={(event) =>
          setCapability(event.target.value as PlaygroundCapabilityId)
        }
      >
        {CAPABILITIES.map((item) => (
          <option key={item.id} value={item.id}>
            {item.label}
          </option>
        ))}
      </select>
      <RunForm
        capabilities={CAPABILITIES}
        assets={assets}
        selectedCapability={capability}
        onSubmitted={onSubmitted}
        onRequestAsset={(request) => {
          if (request.mediaKind === "image") {
            request.onPick(queue.current.shift() ?? imageAsset.id);
          } else if (request.mediaKind === "audio") {
            request.onPick(wavAsset.id);
          } else {
            request.onPick(mp4Asset.id);
          }
        }}
      />
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each(CAPABILITY_IDS)("%s 表单可以渲染", (capability) => {
  render(<Harness initialCapability={capability} />);
  expect(screen.getByText(capability)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "提交" })).toBeInTheDocument();
});

it("不可用的能力在列表中置灰并提示", () => {
  render(
    <CapabilityList
      capabilities={CAPABILITIES.map((item) =>
        item.id === "codex_image.generate"
          ? { ...item, available: false }
          : item,
      )}
      selected={null}
      onSelect={vi.fn()}
    />,
  );
  const button = screen.getByRole("button", { name: "生图" });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("title", "对应模型服务未配置。");
});

it("FL2VA 提交包含全部 6 个键，未选尾帧时为 null", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(okResponse({ receipt, data: { run } }));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness initialCapability="minimax_h3.fl2va" />);
  fireEvent.change(screen.getByRole("textbox", { name: "H3 提示词" }), {
    target: { value: "雨夜站台" },
  });
  fireEvent.click(screen.getByRole("button", { name: "从资产选择（首帧）" }));
  fireEvent.click(screen.getByRole("button", { name: "提交" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const body = JSON.parse(
    String((fetcher.mock.calls[0][1] as RequestInit).body),
  ) as { arguments: { parameters: Record<string, unknown> } };
  expect(Object.keys(body.arguments.parameters).sort()).toEqual([
    "aspect_ratio",
    "duration_seconds",
    "first_frame_asset_id",
    "last_frame_asset_id",
    "prompt",
    "seed",
  ]);
  expect(body.arguments.parameters.first_frame_asset_id).toBe(imageAsset.id);
  expect(body.arguments.parameters.last_frame_asset_id).toBeNull();
});

it("Ref2VA 预览标签映射，说明为空时禁用提交", async () => {
  render(<Harness initialCapability="minimax_h3.ref2va" />);
  fireEvent.change(screen.getByRole("textbox", { name: "H3 提示词" }), {
    target: { value: "角色走入雨中" },
  });
  fireEvent.click(screen.getByRole("button", { name: "从资产选择（首帧）" }));
  fireEvent.click(screen.getByRole("button", { name: "添加附加图片" }));
  fireEvent.click(
    screen.getByRole("button", { name: "从资产选择（附加图片 1）" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "添加参考音频" }));
  fireEvent.click(
    screen.getByRole("button", { name: "从资产选择（参考音频 1）" }),
  );
  await waitFor(() =>
    expect(screen.getByText("<Picture 2>")).toBeInTheDocument(),
  );
  expect(screen.getByText("<Audio 1>")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "提交" })).toBeDisabled();
});

it("时长不设上限，只拒绝短于 0.2 秒", () => {
  render(<Harness initialCapability="minimax_h3.fl2va" />);
  fireEvent.change(screen.getByRole("textbox", { name: "H3 提示词" }), {
    target: { value: "雨夜站台" },
  });
  const duration = screen.getByRole("spinbutton", { name: "时长（秒）" });
  expect(duration).not.toHaveAttribute("max");
  fireEvent.change(duration, { target: { value: "20" } });
  expect(
    screen.queryByText("时长（秒）不能小于 0.2。"),
  ).not.toBeInTheDocument();
  fireEvent.change(duration, { target: { value: "0.1" } });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "时长（秒）不能小于 0.2。",
  );
  expect(screen.getByRole("button", { name: "提交" })).toBeDisabled();
});

it("切换能力再切回来仍然保留草稿", () => {
  render(<Harness initialCapability="minimax_h3.fl2va" />);
  fireEvent.change(screen.getByRole("textbox", { name: "H3 提示词" }), {
    target: { value: "保留我" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "切换能力" }), {
    target: { value: "codex_image.generate" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "切换能力" }), {
    target: { value: "minimax_h3.fl2va" },
  });
  expect(screen.getByRole("textbox", { name: "H3 提示词" })).toHaveValue(
    "保留我",
  );
});

it("同步能力提交期间显示处理中…", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => new Promise(() => undefined)),
  );
  render(<Harness initialCapability="audio.trim" />);
  fireEvent.click(screen.getByRole("button", { name: "从资产选择（音频）" }));
  fireEvent.change(screen.getByRole("spinbutton", { name: "截取终点（秒）" }), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交" }));
  expect(
    await screen.findByRole("button", { name: "处理中…" }),
  ).toBeInTheDocument();
});

it("提交失败时显示 Core 返回的原始 message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(errorResponse("参数不合法：prompt。", 400)),
  );
  render(<Harness initialCapability="minimax_h3.fl2va" />);
  fireEvent.change(screen.getByRole("textbox", { name: "H3 提示词" }), {
    target: { value: "雨夜站台" },
  });
  fireEvent.click(screen.getByRole("button", { name: "从资产选择（首帧）" }));
  fireEvent.click(screen.getByRole("button", { name: "提交" }));
  expect(await screen.findByText("参数不合法：prompt。")).toBeInTheDocument();
});

it("声音克隆按 recipe 渲染、规范化表演参数并保留随机 seed", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(okResponse({ receipt, data: { run } }));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness initialCapability="breeze_tts2.clone" />);
  fireEvent.change(screen.getByLabelText("朗读文本"), {
    target: { value: "你好" },
  });
  fireEvent.change(screen.getByLabelText("参考音频文字稿"), {
    target: { value: "完整文字稿" },
  });
  fireEvent.change(screen.getByLabelText("表演指示"), {
    target: { value: " 克制 " },
  });
  expect(screen.getByLabelText("表演指示")).toHaveAttribute("maxlength", "200");
  fireEvent.click(
    screen.getByRole("button", { name: "从资产选择（参考音色）" }),
  );
  expect(screen.getByRole("button", { name: "随机" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "提交" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const body = JSON.parse(
    String((fetcher.mock.calls[0][1] as RequestInit).body),
  );
  expect(body.arguments.parameters).toEqual({
    text: "你好",
    voice_asset_id: wavAsset.id,
    reference_transcript: "完整文字稿",
    performance_instruction: "克制",
    seed: 42,
  });
});

// 标签 fixture 由 Core 生成，表单测试不实现 namespace 计数器。
beforeEach(() => {
  vi.spyOn(playgroundApi, "previewRecipeInputs").mockResolvedValue(
    recipeFixture.reference_preview,
  );
});

it("全景裁切：只请求 pano_view 资产，预设改写 yaw/hfov，提交五个键", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(okResponse({ receipt, data: { run } }));
  vi.stubGlobal("fetch", fetcher);
  const requests: Array<{ requiredAction?: string; mediaTypes?: string[] }> =
    [];
  render(
    <RunForm
      capabilities={CAPABILITIES}
      assets={FIXTURE_ASSETS}
      selectedCapability="image.pano_view"
      onSubmitted={vi.fn()}
      onRequestAsset={(request) => {
        requests.push(request);
        request.onPick(imageAsset.id);
      }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "从资产选择（全景）" }));
  expect(requests[0]?.requiredAction).toBe("pano_view");
  expect(requests[0]?.mediaTypes).toEqual(["image/png", "image/jpeg"]);
  fireEvent.click(screen.getByRole("button", { name: "左 270°" }));
  fireEvent.click(screen.getByRole("button", { name: "hfov 60°" }));
  fireEvent.change(screen.getByRole("spinbutton", { name: "俯仰 pitch" }), {
    target: { value: "-12.5" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "画面比例" }), {
    target: { value: "9:16" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const body = JSON.parse(
    String((fetcher.mock.calls[0][1] as RequestInit).body),
  ) as { arguments: { capability: string; parameters: unknown } };
  expect(body.arguments.capability).toBe("image.pano_view");
  expect(body.arguments.parameters).toEqual({
    image_asset_id: imageAsset.id,
    yaw_deg: 270,
    pitch_deg: -12.5,
    hfov_deg: 60,
    aspect_ratio: "9:16",
  });
});

it("全景裁切四个方向在 Web 侧依次提交，Core 没有批量接口", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(okResponse({ receipt, data: { run } }));
  vi.stubGlobal("fetch", fetcher);
  const onSubmitted = vi.fn();
  render(
    <Harness initialCapability="image.pano_view" onSubmitted={onSubmitted} />,
  );
  const batch = screen.getByRole("button", { name: "四个方向依次裁切" });
  expect(batch).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "从资产选择（全景）" }));
  fireEvent.click(batch);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4));
  const yaws = fetcher.mock.calls.map((call) => {
    const body = JSON.parse(String((call[1] as RequestInit).body)) as {
      name: string;
      arguments: { parameters: { yaw_deg: number; hfov_deg: number } };
    };
    expect(body.name).toBe("playground.submit_run");
    expect(body.arguments.parameters.hfov_deg).toBe(90);
    return body.arguments.parameters.yaw_deg;
  });
  expect(yaws).toEqual([0, 90, 180, 270]);
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
});
