import { useEffect, useRef, useState } from "react";
import { copyText } from "./director_workspace/clipboard";

export type ExternalAgentTarget =
  | { kind: "project"; projectId: string }
  | { kind: "playground" };

export function ExternalAgentEntry({ target }: { target: ExternalAgentTarget }) {
  const [open, setOpen] = useState(false);
  const entry = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    function closeOutside(event: PointerEvent) {
      if (event.target instanceof Node && !entry.current?.contains(event.target)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);
  return (
    <div className="external-agent-entry" ref={entry}>
      <button type="button" className="secondary-button" ref={trigger}
        aria-expanded={open} aria-controls="external-agent-panel"
        onClick={() => setOpen(!open)}>连接 Agent</button>
      {open ? <section id="external-agent-panel" className="external-agent-panel" aria-label="连接外部 Agent">
        <ExternalAgentConnect target={target} />
      </section> : null}
    </div>
  );
}

function quote(value: string): string {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

export function ExternalAgentConnect({ target }: { target: ExternalAgentTarget }) {
  const [agent, setAgent] = useState("");
  const [command, setCommand] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<boolean | null>(null);
  const projectId = target.kind === "project" ? target.projectId : null;
  const forPlayground = projectId === null;
  useEffect(() => {
    if (agent !== "pi" && agent !== "codex" && agent !== "agy" && agent !== "kimi" && agent !== "dsh" && agent !== "grok") return;
    let cancelled = false;
    setCommand("");
    setError("");
    setCopied(null);
    void fetch("/api/local-connection").then(async (response) => {
      if (!response.ok) throw new Error("请用项目的 start.sh 启动 StoryRail，然后回到这里重试。");
      const value: unknown = await response.json();
      if (typeof value !== "object" || value === null ||
          !("command_prefix" in value) || typeof value.command_prefix !== "string" ||
          !("cwd" in value) || typeof value.cwd !== "string" ||
          Object.keys(value).length !== 2 ||
          (projectId !== null && !/^[0-9a-f]{32}$/.test(projectId))) {
        throw new Error("启动信息不完整，请刷新页面重试。");
      }
      const scope = projectId === null ? "--playground" : `--project ${quote(projectId)}`;
      if (!cancelled) setCommand(`cd ${quote(value.cwd)} && ${value.command_prefix} --agent ${agent} ${scope}`);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "连接信息获取失败，请重试。");
    });
    return () => { cancelled = true; };
  }, [agent, projectId]);
  return (
    <div className="external-agent-connect">
      <label>
        <span>你使用什么 Agent？</span>
        <select value={agent} onChange={(event) => setAgent(event.target.value)}>
          <option value="">请选择</option>
          <option value="pi">Pi</option>
          <option value="codex">Codex CLI</option>
          <option value="agy">Antigravity CLI</option>
          <option value="kimi">Kimi Code</option>
          <option value="dsh">DeepSeek Harness</option>
          <option value="grok">Grok Build</option>
          <option value="other">其他 Agent</option>
        </select>
      </label>
      {agent === "other" ? <p>当前一键接入支持 Pi、Codex CLI、Antigravity CLI、Kimi Code、DeepSeek Harness 和 Grok Build。其他 Agent 的接入命令还在准备中。</p> : null}
      {agent === "pi" || agent === "codex" || agent === "agy" || agent === "kimi" || agent === "dsh" || agent === "grok" ? <>
        <p>你可以询问当前应该做什么。</p>
        {forPlayground
          ? <p>连接后，Agent 可以在 Playground 中按你的指令提交实验；候选选择与跨域复制仍由你完成。</p>
          : <p>连接后，Agent 可按你的指令处理当前项目；候选选择与最终审核仍由你完成。</p>}
        <p>复制命令，在这台电脑的终端粘贴运行即可打开 {agent === "codex" ? "Codex CLI" : agent === "agy" ? "Antigravity CLI" : agent === "kimi" ? "Kimi Code" : agent === "dsh" ? "DeepSeek Harness" : agent === "grok" ? "Grok Build" : "Pi"}。模型由你在 Agent 中选择和切换。首次运行需已安装 {agent === "codex" ? "Codex CLI" : agent === "agy" ? "Antigravity CLI" : agent === "kimi" ? "Kimi Code" : agent === "dsh" ? "DeepSeek Harness" : agent === "grok" ? "Grok Build" : "Pi"} 和 Docker Desktop。</p>
        {agent === "codex" ? <p>使用独立的 Codex 配置与会话。首次连接导入本机文件形式的登录缓存；没有可用缓存时，请在 Codex 中完成设备码登录。</p> : null}
        {agent === "agy" ? <p>使用独立的 Antigravity 配置与会话，不导入宿主插件或历史。首次连接请在 CLI 中完成登录，后续登录态保留在隔离配置卷。</p> : null}
        {agent === "kimi" ? <p>使用独立的 Kimi Code 配置与会话，不导入宿主凭据或历史。启动默认使用完全自动权限模式；首次连接请在 CLI 中完成登录，后续登录态保留在隔离配置卷。</p> : null}
        {agent === "dsh" ? <p>使用官方 DeepSeek Harness Web UI 与独立配置，不导入宿主凭据或历史。浏览器只通过本机地址访问；新会话默认使用完全权限且不询问，首次连接请在 Web UI 中配置模型凭据。</p> : null}
        {agent === "grok" ? <p>使用独立的 Grok Build 配置与会话，不导入宿主凭据或历史。首次连接请在隔离 CLI 中完成浏览器或设备码登录，后续登录态保留在独立配置卷。</p> : null}
        {error ? <p role="alert">{error}</p> : command ? <>
          <button type="button" onClick={async () => {
            try {
              setCopied(await copyText(command));
            } catch { setCopied(false); }
          }}>{copied ? "已复制启动命令" : "复制启动命令"}</button>
          <textarea aria-label="启动命令" readOnly rows={3} value={command}
            onFocus={(event) => event.currentTarget.select()} />
          <p role="status">{copied ? "已复制。打开 Agent 后，你可以询问当前应该做什么。" : copied === false ? "未能自动复制，请选中上方命令手动复制。" : "也可以选中上方命令手动复制。"}</p>
        </> : <p>正在准备启动命令…</p>}
      </> : null}
    </div>
  );
}
