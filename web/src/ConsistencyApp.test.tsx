import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import fixture from "./test/story_reader_fixture.json";
const project = { ...fixture.continuity.project, status: "active", updated_at: "2026-09-13T00:00:00Z" };
function state() {
  const value = structuredClone(fixture.continuity.production_snapshot);
  delete (value as { director_messages?: unknown }).director_messages;
  value.allowed_actions = [...new Set([...value.allowed_actions, "edit_script"])];
  return value;
}
function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
beforeEach(() => { window.history.replaceState(null, "", "/"); Element.prototype.scrollIntoView = vi.fn(); window.scrollTo = vi.fn(); });
afterEach(() => vi.restoreAllMocks());
async function openEditor() {
  fireEvent.click(await screen.findByRole("button", { name: "打开" }));
  fireEvent.click(await screen.findByRole("button", { name: /场景 2 ·/ }, { timeout: 5000 }));
  fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
}
// 该用例顺序触发三次保存与两次会话提示，单文件运行约 2.3s；全量 vitest 并发跑 14 个
// 测试文件时 CPU 争用会把真实等待放大到默认 5000ms 之上。这里显式放宽超时，
// 断言与行为保持原样（测试卫生修复，不是产品行为变更）。
it(
  "失败保留草稿不提醒；成功后关闭、再次保存从新的旧值开始；回首页清除",
  async () => {
    let current = state(), fail = true;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (String(url) === "/api/projects") return response({ projects: [project] });
      if (init?.method === "PUT") {
        if (fail)
          return response(
            {
              error: {
                code: "failure",
                message: "合成失败",
                recoverable: true,
                origin: "core_domain",
                state_changed: false,
                retry_policy: "change_business_state_or_request",
                automatic_retry_allowed: false,
              },
            },
            500,
          );
        // 编辑器只回传可编辑字段；旁白时长与时间基准是 Core 的只读投影，这里沿用原值。
        const previousScenes = current.director_script.scenes;
        const scenes = (JSON.parse(String(init.body)).scenes as typeof previousScenes).map((scene) => ({
          ...scene,
          narration_cues: previousScenes.find((item) => item.id === scene.id)?.narration_cues ?? [],
        })) as typeof previousScenes;
        current = { ...current, revision: current.revision + 1, director_script: { ...current.director_script, scenes } };
      }
      return response(current);
    });
    render(<App />); await openEditor();
    expect(screen.getByRole("button", { name: "保存脚本修改" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("本 Scene 时空与环境 *"), { target: { value: "清晨测试" } });
    expect(screen.queryByLabelText("内容修改提醒")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
    await screen.findAllByText(/合成失败/);
    expect(screen.queryByLabelText("内容修改提醒")).not.toBeInTheDocument();
    expect(screen.getByLabelText("本 Scene 时空与环境 *")).toHaveValue("清晨测试");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
    await screen.findByLabelText("内容修改提醒");
    fireEvent.click(screen.getByRole("button", { name: "关闭提醒" }));
    expect(screen.queryByLabelText("内容修改提醒")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑这一段" }));
    fireEvent.change(screen.getByLabelText("本 Scene 时空与环境 *"), { target: { value: "黄昏测试" } });
    fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
    await screen.findByLabelText("内容修改提醒");
    fireEvent.click(screen.getByRole("button", { name: /所有项目/ }));
    expect(screen.queryByLabelText("内容修改提醒")).not.toBeInTheDocument();
  },
  20000,
);
it("外部轮询修改正文不冒充人工保存", async () => {
  vi.useFakeTimers();
  try {
    let current = state();
    vi.spyOn(globalThis, "fetch").mockImplementation(async url => response(String(url) === "/api/projects" ? { projects: [project] } : current));
    render(<App />);
    // 初次渲染只依赖 fetch mock 的 promise（microtask），act 冲刷即可，不用真实轮询。
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "打开" }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /场景 2 ·/ }));
    current = structuredClone(current); current.revision++; current.director_script.scenes[1].setting = "外部 Agent 的最新正文";
    // 无活跃 Generation 时统一调度器间隔 5s；fake timers 直接推进，消灭真实等待。
    await act(async () => { await vi.advanceTimersByTimeAsync(5100); });
    expect(screen.getByText("外部 Agent 的最新正文")).toBeInTheDocument();
    expect(screen.queryByLabelText("内容修改提醒")).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
it("离开项目后的迟到保存响应不建立提示或覆盖首页", async () => {
  const current = state();
  let complete: (value: Response) => void = () => {};
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    if (String(url) === "/api/projects") return response({ projects: [project] });
    if (init?.method === "PUT") return new Promise<Response>(resolve => { complete = resolve; });
    return response(current);
  });
  render(<App />); await openEditor();
  fireEvent.change(screen.getByLabelText("本 Scene 时空与环境 *"), { target: { value: "迟到正文" } });
  fireEvent.click(screen.getByRole("button", { name: "保存脚本修改" }));
  fireEvent.click(screen.getByRole("button", { name: /所有项目/ }));
  const updated = structuredClone(current); updated.revision++; updated.director_script.scenes[1].setting = "迟到正文";
  complete(response(updated));
  await screen.findByRole("button", { name: "打开" });
  expect(screen.queryByLabelText("内容修改提醒")).not.toBeInTheDocument();
});
