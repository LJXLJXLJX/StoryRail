# Core

这里保存 StoryRail 的业务职责、厂商无关边界和具体模型插件。

- `director_proposals/`：外部 Agent 使用的专业 Skill/schema/workset 与 proposal 契约；
- `director_commands/`：稳定 Core command 契约、严格参数、影响预览与短执行回执；
- `audio_effects/`：不持有项目状态的确定性 WAV 截取、后处理 API、preset、DSP 与事件时间线；
- `media_assets/`：与项目和 Playground 都无关的媒体字节校验、时长读取、可读文件名与 MP4 帧数读取；
- `playground/`：与项目平行、全局唯一的媒体实验工作区（`playground.json` schema v2）；
- `project_workspaces/`：`.stories/` 项目容器、受控 ID 和可恢复删除；
- `structured_director/`：`project.json`、引用库、结构化脚本、参考媒体和原子写入边界；
- `model_providers/`：Core 接入具体媒体模型 API 的插件；
- `application/`：服务端签发的 caller、Agent 操作白名单、授权与请求身份；
- `project_settings/`：画幅等项目设置值对象；
- `web_contracts/`：由 Core 类型生成 Web 合同。

Project Workspace 只负责项目容器和有效 `project.json` 的发现；`structured_director/` 是当前唯一
`project.json` 写者。所有类型化命令都只能委托 Store 在 revision 上执行原子修改。
Core 不包含 Web UI、私有模型 Runtime，也不允许厂商 SDK 类型进入业务职责。产品说明书见 [`docs/`](../docs/README.md)，命令清单见 [命令目录](../docs/commands.md)。
