# Core 主机闹钟

外部 Agent 经 MCP `ring_alarm` 提醒用户：项目 scope 翻译为 `alarm.ring`，Playground scope 翻译为
`playground.ring_alarm`，参数只有 1–200 字的 `message`。Core 在自己所在的 macOS 主机上循环播放
`Glass` 系统提示音，同时弹出原生对话框显示该文字；点“知道了”立即停止，最长响 120 秒。

- 不经过浏览器，不写 `project.json` 或 `playground.json`，没有幂等回执；只要求调用方能读当前项目或使用 Playground。
- 同一时刻只响一个闹钟，响铃期间再次调用返回 `already_ringing`，不叠加。
- 提示文字经 argv 传给 `osascript`，不拼进脚本源码。
- Core 主机不是 macOS 或缺少 `afplay` / `osascript` 时返回错误，Agent 应改为在对话中告知用户。
