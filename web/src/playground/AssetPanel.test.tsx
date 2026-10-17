import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type {
  PlaygroundAsset,
  ProjectAsset,
  ProjectSummary,
} from "../api";
import { parseStructuredDirectorSnapshot } from "../api/validation";
import mixedApprovalFixture from "../test/mixed_approval_fixture.json";
import { AssetPanel } from "./AssetPanel";

const project: ProjectSummary = {
  id: "a".repeat(32),
  title: "雨夜末班车",
  aspect_ratio: "16:9",
  updated_at: "2026-01-01T00:00:00+00:00",
  status: "active",
};

function playgroundAsset(
  seed: string,
  mediaType: PlaygroundAsset["media_type"],
  displayName: string,
  overrides: Partial<PlaygroundAsset> = {},
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
    ...overrides,
  };
}

const imageAsset = playgroundAsset("1", "image/png", "图片一");
const wavAsset = playgroundAsset("3", "audio/wav", "音频一");
const mp4Asset = playgroundAsset("4", "video/mp4", "视频一");
const copiedAsset = playgroundAsset("5", "audio/wav", "新素材");

const projectAsset: ProjectAsset = {
  id: "9".repeat(32),
  media_type: "audio/wav",
  image_category: null,
  byte_count: 1000,
  duration_seconds: 3,
  display_name: "项目音频",
  content_url: `/api/projects/${project.id}/structured-director/assets/${"9".repeat(32)}/content`,
  is_in_use: false,
  usage_reasons: [],
  retains_derived_assets_on_delete: false,
  allowed_actions: [],
};

const projectSnapshot = {
  ...parseStructuredDirectorSnapshot(mixedApprovalFixture),
  revision: 7,
  assets: [projectAsset],
};

function okResponse(value: unknown): Response {
  return { ok: true, status: 200, json: async () => value } as Response;
}

function errorResponse(
  message: string,
  status: number,
  code = "invalid_request",
): Response {
  return {
    ok: false,
    status,
    json: async () => ({
      error: {
        code,
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
  initialAssets = [],
  onChangeAssets = () => [],
  selection = null,
  onClose = vi.fn(),
}: {
  initialAssets?: PlaygroundAsset[];
  onChangeAssets?: () => PlaygroundAsset[];
  selection?: { mediaKind: "image" | "audio" | "video"; onPick: (assetId: string) => void } | null;
  onClose?: () => void;
}) {
  const [assets, setAssets] = useState(initialAssets);
  return (
    <AssetPanel
      assets={assets}
      selection={
        selection === null
          ? null
          : { mediaKind: selection.mediaKind, onPick: selection.onPick }
      }
      onClose={onClose}
      onChanged={() => setAssets((current) => [...current, ...onChangeAssets()])}
    />
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("多文件逐个上传，单个失败不影响其余文件", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(okResponse({ asset: wavAsset }))
    .mockResolvedValueOnce(errorResponse("不支持的文件类型。", 400))
    .mockResolvedValueOnce(okResponse({ asset: copiedAsset }));
  vi.stubGlobal("fetch", fetcher);
  const onChanged = vi.fn();
  render(<AssetPanel assets={[]} onClose={vi.fn()} onChanged={onChanged} />);
  fireEvent.change(screen.getByLabelText("选择要上传的素材"), {
    target: {
      files: [
        new File(["a"], "a.wav", { type: "audio/wav" }),
        new File(["b"], "b.wav", { type: "audio/wav" }),
        new File(["c"], "c.wav", { type: "audio/wav" }),
      ],
    },
  });
  expect(await screen.findByText("a.wav：上传成功")).toBeInTheDocument();
  expect(
    screen.getByText("b.wav：上传失败：不支持的文件类型。"),
  ).toBeInTheDocument();
  expect(screen.getByText("c.wav：上传成功")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(onChanged).toHaveBeenCalled();
});

it("被占用的资产不能勾选，删除遇到 409 显示规定文案", async () => {
  const inUse = playgroundAsset("6", "audio/wav", "占用中音频", {
    is_in_use: true,
    usage_reasons: [{ code: "unfinished_run_input", label: "未结束实验的输入" }],
    allowed_actions: ["copy_to_project"],
  });
  const deletable = playgroundAsset("7", "audio/wav", "可删除音频");
  render(
    <AssetPanel assets={[inUse, deletable]} onClose={vi.fn()} onChanged={vi.fn()} />,
  );
  expect(
    screen.getByRole("checkbox", { name: "选择 占用中音频" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 可删除音频" }));
  fireEvent.click(screen.getByRole("button", { name: "删除所选（1）" }));
  expect(
    screen.getByText("将删除 1 个 Playground 资产，确定继续？"),
  ).toBeInTheDocument();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(errorResponse("该资产正在被使用。", 409, "asset_in_use")),
  );
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(
    await screen.findByText(
      "该素材正被未结束的实验使用，请等待或取消相关实验后再删除。",
    ),
  ).toBeInTheDocument();
});

it("复制到项目：图片必须先选分类，请求体带项目快照的 expected_revision", async () => {
  const fetcher = vi.fn().mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === "/api/projects") return okResponse({ projects: [project] });
    if (url.endsWith("/structured-director")) return okResponse(projectSnapshot);
    if (url.endsWith("/copy-from-playground")) {
      return okResponse({ asset_id: "e".repeat(32), project_revision: 8 });
    }
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Harness initialAssets={[imageAsset]} />);
  fireEvent.click(screen.getByRole("button", { name: "复制到项目…" }));
  const dialog = await screen.findByRole("dialog", { name: "复制到项目" });
  await within(dialog).findByRole("option", { name: project.title });
  fireEvent.change(within(dialog).getByRole("combobox", { name: "目标项目" }), {
    target: { value: project.id },
  });
  const confirm = within(dialog).getByRole("button", { name: "确认复制" });
  expect(confirm).toBeDisabled();
  fireEvent.change(within(dialog).getByRole("combobox", { name: "图片分类" }), {
    target: { value: "keyframe" },
  });
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);
  expect(
    await screen.findByText(`已复制到《${project.title}》`),
  ).toBeInTheDocument();
  const copyCall = fetcher.mock.calls.find((call) =>
    String(call[0]).endsWith("/copy-from-playground"),
  );
  expect(copyCall).toBeDefined();
  expect(JSON.parse(String((copyCall?.[1] as RequestInit).body))).toEqual({
    asset_id: imageAsset.id,
    expected_revision: 7,
    image_category: "keyframe",
  });
});

it("revision_conflict 时重新读取 revision 并只重试一次", async () => {
  let revision = 7;
  let copyCalls = 0;
  let getCalls = 0;
  const revisions: number[] = [];
  const fetcher = vi.fn().mockImplementation(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/projects") return okResponse({ projects: [project] });
    if (url.endsWith("/structured-director")) {
      getCalls += 1;
      if (getCalls === 2) revision = 8;
      revisions.push(revision);
      return okResponse({ ...projectSnapshot, revision });
    }
    if (url.endsWith("/copy-from-playground")) {
      copyCalls += 1;
      if (copyCalls === 1) {
        return errorResponse("项目状态已变化。", 409, "revision_conflict");
      }
      expect(JSON.parse(String(init?.body))).toMatchObject({
        expected_revision: 8,
      });
      return okResponse({ asset_id: "e".repeat(32), project_revision: 9 });
    }
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Harness initialAssets={[wavAsset]} />);
  fireEvent.click(screen.getByRole("button", { name: "复制到项目…" }));
  const dialog = await screen.findByRole("dialog", { name: "复制到项目" });
  await within(dialog).findByRole("option", { name: project.title });
  fireEvent.change(within(dialog).getByRole("combobox", { name: "目标项目" }), {
    target: { value: project.id },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "确认复制" }));
  expect(
    await screen.findByText(`已复制到《${project.title}》`),
  ).toBeInTheDocument();
  expect(copyCalls).toBe(2);
  expect(revisions).toEqual([7, 8]);
});

it("项目资产页签复制到 Playground 后切回并高亮新 Asset", async () => {
  const fetcher = vi.fn().mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === "/api/projects") return okResponse({ projects: [project] });
    if (url.endsWith("/structured-director")) return okResponse(projectSnapshot);
    if (url.endsWith("/assets/copy-from-project")) {
      return okResponse({ asset: copiedAsset });
    }
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <Harness
      initialAssets={[]}
      onChangeAssets={() => [copiedAsset]}
    />,
  );
  fireEvent.click(screen.getByRole("tab", { name: "项目资产" }));
  fireEvent.change(await screen.findByRole("combobox", { name: "项目" }), {
    target: { value: project.id },
  });
  expect(await screen.findByText(/项目音频/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制到 Playground" }));
  const item = (await screen.findByText(/新素材/)).closest(
    ".playground-asset-item",
  );
  expect(item).not.toBeNull();
  expect(item as HTMLElement).toHaveClass("is-selected");
  const copyCall = fetcher.mock.calls.find((call) =>
    String(call[0]).endsWith("/assets/copy-from-project"),
  );
  expect(JSON.parse(String((copyCall?.[1] as RequestInit).body))).toEqual({
    project_id: project.id,
    asset_id: projectAsset.id,
  });
});

it("选择模式只显示兼容类型，点击后回填并关闭", () => {
  const onPick = vi.fn();
  const onClose = vi.fn();
  render(
    <Harness
      initialAssets={[imageAsset, wavAsset, mp4Asset]}
      selection={{ mediaKind: "audio", onPick }}
      onClose={onClose}
    />,
  );
  const dialog = screen.getByRole("dialog", { name: "选择素材" });
  expect(within(dialog).getByText(/音频一/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/图片一/)).not.toBeInTheDocument();
  expect(within(dialog).queryByText(/视频一/)).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "选择" }));
  expect(onPick).toHaveBeenCalledWith(wavAsset.id);
  expect(onClose).toHaveBeenCalled();
});

it("资产面板是悬浮独立窗口：模态容器 + 窗口主体 + 拖动标题栏", () => {
  render(<AssetPanel assets={[imageAsset]} onClose={vi.fn()} onChanged={vi.fn()} />);
  const dialog = screen.getByRole("dialog", { name: "Playground 资产" });
  expect(dialog).toHaveClass("playground-window");
  expect(dialog.closest(".playground-window-layer")).not.toBeNull();
  expect(within(dialog).getByRole("tab", { name: "Playground 资产" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  const head = dialog.querySelector(".playground-window-head");
  expect(head).not.toBeNull();
  fireEvent.pointerDown(head as Element, {
    pointerId: 1,
    button: 0,
    clientX: 100,
    clientY: 100,
  });
  expect(dialog).toHaveClass("is-dragging");
  fireEvent.pointerMove(head as Element, { pointerId: 1, clientX: 160, clientY: 130 });
  expect((dialog as HTMLElement).style.transform).toBe("translate(60px, 30px)");
  fireEvent.pointerUp(head as Element, { pointerId: 1 });
  expect(dialog).not.toHaveClass("is-dragging");
  // 标题栏上的按钮不触发拖动。
  fireEvent.pointerDown(screen.getByRole("button", { name: "关闭" }), {
    pointerId: 2,
    button: 0,
    clientX: 10,
    clientY: 10,
  });
  expect(dialog).not.toHaveClass("is-dragging");
});

it("图片可以点击放大，音频使用不溢出的紧凑播放器", () => {
  render(
    <AssetPanel
      assets={[imageAsset, wavAsset]}
      onClose={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "查看全图：图片一" }));
  const preview = screen.getByRole("dialog", { name: "图片一全图" });
  expect(within(preview).getByRole("img", { name: "图片一" })).toBeInTheDocument();
  fireEvent.click(within(preview).getByRole("button", { name: "关闭全图" }));
  expect(screen.queryByRole("dialog", { name: "图片一全图" })).toBeNull();

  // 音频卡片用自绘播放器，不再依赖会撑破卡片的原生 controls。
  const audioItem = screen.getByText("音频一").closest(".playground-asset-item");
  expect(audioItem).not.toBeNull();
  expect(
    within(audioItem as HTMLElement).getByRole("button", { name: "播放 音频一" }),
  ).toBeInTheDocument();
  expect(
    within(audioItem as HTMLElement).getByLabelText("音频一 播放进度"),
  ).toBeInTheDocument();
  expect(
    (audioItem as HTMLElement).querySelector("audio[controls]"),
  ).toBeNull();
});

it("全选只勾选当前过滤下可删除的资产，再点取消全选", () => {
  const inUse = playgroundAsset("6", "audio/wav", "占用中音频", {
    is_in_use: true,
    usage_reasons: [{ code: "unfinished_run_input", label: "未结束实验的输入" }],
    allowed_actions: ["copy_to_project"],
  });
  render(
    <AssetPanel
      assets={[imageAsset, wavAsset, mp4Asset, inUse]}
      onClose={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByRole("combobox", { name: "资产类型" }), {
    target: { value: "audio" },
  });
  fireEvent.click(screen.getByRole("button", { name: "全选" }));
  expect(screen.getByRole("checkbox", { name: "选择 音频一" })).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "选择 占用中音频" }),
  ).not.toBeChecked();
  expect(screen.getByRole("button", { name: "删除所选（1）" })).toBeEnabled();

  fireEvent.change(screen.getByRole("combobox", { name: "资产类型" }), {
    target: { value: "image" },
  });
  expect(screen.getByRole("button", { name: "删除所选（0）" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "全选" })).toBeEnabled();

  fireEvent.change(screen.getByRole("combobox", { name: "资产类型" }), {
    target: { value: "audio" },
  });
  fireEvent.click(screen.getByRole("button", { name: "取消全选" }));
  expect(
    screen.getByRole("checkbox", { name: "选择 音频一" }),
  ).not.toBeChecked();
});

it("全景裁切选择模式只列出 Core 授予 pano_view 的图片", () => {
  const onPick = vi.fn();
  const panorama = playgroundAsset("6", "image/png", "客厅全景", {
    allowed_actions: ["copy_to_project", "pano_view", "delete"],
  });
  render(
    <AssetPanel
      assets={[imageAsset, panorama]}
      selection={{
        mediaKind: "image",
        mediaTypes: ["image/png", "image/jpeg"],
        requiredAction: "pano_view",
        onPick,
      }}
      onClose={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  const dialog = screen.getByRole("dialog", { name: "选择素材" });
  expect(within(dialog).getByText(/客厅全景/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/图片一/)).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "选择" }));
  expect(onPick).toHaveBeenCalledWith(panorama.id);
});
