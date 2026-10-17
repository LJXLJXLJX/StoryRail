import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ExternalAgentConnect } from "./ExternalAgentConnect";
import { copyText } from "./director_workspace/clipboard";
vi.mock("./director_workspace/clipboard", () => ({ copyText: vi.fn() }));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
it.each(["pi", "codex", "agy", "kimi", "dsh", "grok"])("generates a project-bound runnable %s command", async (agent) => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ command_prefix: "'/opt/Python Env/python' -m integrations.agent_launcher --socket '/private/control.sock' --core-port 8765", cwd: "/some/StoryRail user's" }) });
  vi.stubGlobal("fetch", fetcher);
  vi.mocked(copyText).mockResolvedValue(true);
  render(<ExternalAgentConnect target={{ kind: "project", projectId: "a".repeat(32) }} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("combobox", { name: "你使用什么 Agent？" }), { target: { value: agent } });
  const text = await screen.findByRole("textbox", { name: "启动命令" });
  expect(screen.getByText("你可以询问当前应该做什么。")).toBeInTheDocument();
  expect((text as HTMLTextAreaElement).value).toContain(`--agent ${agent}`);
  expect((text as HTMLTextAreaElement).value).not.toMatch(/--model|--provider|--non-interactive/);
  expect((text as HTMLTextAreaElement).value).toContain("--project '" + "a".repeat(32) + "'");
  expect((text as HTMLTextAreaElement).value).toContain("user'\\''s'");
  fireEvent.click(screen.getByRole("button", { name: "复制启动命令" }));
  await screen.findByRole("button", { name: "已复制启动命令" });
  expect(copyText).toHaveBeenCalledWith((text as HTMLTextAreaElement).value);
});
it("does not fabricate a command for unavailable deployment or another client", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  render(<ExternalAgentConnect target={{ kind: "project", projectId: "a".repeat(32) }} />);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "pi" } });
  await screen.findByRole("alert");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "other" } });
  await waitFor(() => expect(screen.queryByRole("button", { name: "复制启动命令" })).not.toBeInTheDocument());
});

it("keeps the full selectable command when clipboard permission is unavailable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ command_prefix: "python -m integrations.agent_launcher", cwd: "/StoryRail" }) }));
  vi.mocked(copyText).mockResolvedValue(false);
  render(<ExternalAgentConnect target={{ kind: "project", projectId: "b".repeat(32) }} />);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "pi" } });
  fireEvent.click(await screen.findByRole("button", { name: "复制启动命令" }));
  await screen.findByText("未能自动复制，请选中上方命令手动复制。");
  expect(screen.getByRole("textbox", { name: "启动命令" })).toHaveAttribute("readonly");
});

it("generates a playground-scoped runnable command without --project", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ command_prefix: "python -m integrations.agent_launcher --socket '/private/control.sock' --core-port 8765", cwd: "/StoryRail" }) }));
  vi.mocked(copyText).mockResolvedValue(true);
  render(<ExternalAgentConnect target={{ kind: "playground" }} />);
  fireEvent.change(screen.getByRole("combobox", { name: "你使用什么 Agent？" }), { target: { value: "pi" } });
  const text = await screen.findByRole("textbox", { name: "启动命令" });
  expect((text as HTMLTextAreaElement).value).toMatch(/--playground$/);
  expect((text as HTMLTextAreaElement).value).not.toContain("--project");
  expect((text as HTMLTextAreaElement).value).toContain("--agent pi");
});
