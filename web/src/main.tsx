import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("缺少 StoryRail 页面根节点。");
}

async function start() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const ticket = fragment.get("storyrail-login");
  if (ticket) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    try {
      const response = await fetch("/api/local-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket }),
      });
      if (!response.ok) throw new Error("连接已过期，请重新启动 StoryRail 页面。");
    } catch {
      root!.textContent = "连接未完成，请重新启动 StoryRail 页面后重试。";
      return;
    }
  }
  createRoot(root!).render(<StrictMode><App /></StrictMode>);
}
void start();
