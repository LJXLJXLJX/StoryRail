import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ManifestField, ProviderSettingsView } from "../api";
import { ProviderSettingsControl } from "./ProviderSettingsControl";

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function field(overrides: Partial<ManifestField> & Pick<ManifestField, "key" | "widget" | "label">): ManifestField {
  return {
    default: null,
    nullable: false,
    advanced: false,
    options: [],
    minimum: null,
    maximum: null,
    max_length: null,
    min_length: null,
    dimension: null,
    component_labels: [],
    role: null,
    help: "",
    ...overrides,
  };
}

const h3Settings = { preset: "hybrid_v2", resolution: "720p", sage_attention: true, selflift: true };

function view(overrides: Partial<ProviderSettingsView> = {}): ProviderSettingsView {
  return {
    capabilities: [
      {
        id: "image.generate",
        label: "生图",
        bound_plugin_id: "codex_image",
        candidates: [
          { plugin_id: "codex_image", label: "Codex 图片" },
          { plugin_id: "agy_image", label: "AGY 图片" },
        ],
        message: null,
      },
      {
        id: "video.upscale",
        label: "视频超分",
        bound_plugin_id: null,
        candidates: [],
        message: "没有已安装的插件实现该能力。",
      },
    ],
    plugins: [
      {
        plugin_id: "minimax_h3",
        plugin_version: 1,
        label: "MiniMax H3",
        endpoint: "http://h3",
        manifest: {
          plugin_id: "minimax_h3",
          plugin_version: 1,
          label: "MiniMax H3",
          settings: [
            field({
              key: "preset",
              widget: "preset",
              label: "基础模型",
              default: "hybrid_v2",
              options: [
                { id: "hybrid_v2", label: "DaSiWa Hybrid V2 · 20 步" },
                { id: "turbo_v2", label: "Turbo V2 · 8 步" },
              ],
            }),
            field({
              key: "resolution",
              widget: "enum",
              label: "分辨率",
              default: "720p",
              options: [
                { id: "480p", label: "480p" },
                { id: "720p", label: "720p" },
                { id: "1080p", label: "1080p" },
              ],
            }),
            field({ key: "sage_attention", widget: "toggle", label: "SageAttention", default: true }),
            field({ key: "selflift", widget: "toggle", label: "SelfLift", default: true }),
          ],
          hints: { soft_duration_limit_seconds: 15 },
          recipes: [],
          defaults: {},
          image_prompt: null,
        },
        settings: h3Settings,
        settings_summary: "DaSiWa Hybrid V2 · 20 步 · 720p · Sage · SelfLift",
        settings_error: null,
      },
    ],
    tools: [{ id: "final_assembly", label: "成片装配", available: true }],
    ...overrides,
  };
}

afterEach(() => vi.restoreAllMocks());

function open() {
  const summary = screen.getByText("Provider 设置");
  const details = summary.closest("details") as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}

it("Esc 关闭顶栏设置并将焦点还给入口", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response(view()));
  render(<ProviderSettingsControl />);
  open();
  const input = await screen.findByRole("combobox", { name: "基础模型" });
  input.focus();
  fireEvent.keyDown(input, { key: "Escape" });
  const summary = screen.getByText("Provider 设置");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(summary).toHaveFocus();
});

it("展开时才读取设置，并按 manifest widget 渲染插件设置与能力绑定", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(view()));
  render(<ProviderSettingsControl />);
  expect(fetcher).not.toHaveBeenCalled();
  open();
  const h3 = await screen.findByRole("region", { name: "MiniMax H3 设置" });
  expect(fetcher).toHaveBeenCalledWith("/api/settings/providers", undefined);
  expect(within(h3).getByRole("combobox", { name: "基础模型" })).toHaveValue("hybrid_v2");
  expect(within(h3).getByRole("checkbox", { name: "SelfLift" })).toBeChecked();
  expect(screen.getByText("没有已安装的插件实现该能力。")).toBeInTheDocument();
  expect(screen.getByText("成片装配 · 可用")).toBeInTheDocument();
  expect(screen.getByText(/只影响之后新提交的任务/)).toBeInTheDocument();
});

it("修改设置提交完整设置对象，切换绑定提交能力与插件", async () => {
  const turbo = { ...h3Settings, preset: "turbo_v2" };
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(view()))
    .mockResolvedValueOnce(response(view()))
    .mockResolvedValueOnce(response(view()));
  render(<ProviderSettingsControl />);
  open();
  const preset = await screen.findByRole("combobox", { name: "基础模型" });
  fireEvent.change(preset, { target: { value: "turbo_v2" } });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(fetcher).toHaveBeenNthCalledWith(
    2,
    "/api/settings/providers/plugins/minimax_h3",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ settings: turbo }) }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "生图插件" }), {
    target: { value: "agy_image" },
  });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(fetcher).toHaveBeenNthCalledWith(
    3,
    "/api/settings/providers/bindings",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ capability: "image.generate", plugin_id: "agy_image" }),
    }),
  );
});

it("onChanged 只在写成功后触发，读取设置不触发", async () => {
  const onChanged = vi.fn();
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(view()))
    .mockResolvedValueOnce(response(view()));
  render(<ProviderSettingsControl onChanged={onChanged} />);
  open();
  await screen.findByRole("combobox", { name: "生图插件" });
  expect(onChanged).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("combobox", { name: "生图插件" }), {
    target: { value: "agy_image" },
  });
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
});

it("显示 Core 返回的错误且不吞掉已读取的设置", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(view()))
    .mockResolvedValueOnce(
      response(
        {
          error: {
            code: "invalid_request",
            message: "分辨率的取值不受支持。",
            recoverable: false,
            origin: "core_parser",
            state_changed: false,
            retry_policy: "fix_arguments_and_retry",
            automatic_retry_allowed: false,
          },
        },
        400,
      ),
    );
  render(<ProviderSettingsControl />);
  open();
  fireEvent.change(await screen.findByRole("combobox", { name: "分辨率" }), {
    target: { value: "1080p" },
  });
  expect(await screen.findByText("分辨率的取值不受支持。")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "基础模型" })).toBeInTheDocument();
});
