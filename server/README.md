# Slatehand Server

HTTP 装配连接 Project Workspace、Core application、媒体 Provider 和 Web 资源。Server 不包含任何 Agent backend、模型会话或厂商参数。部署拓扑见 [媒体 Provider 与部署](../docs/providers-and-deployment.md)。

`POST /api/projects` 只保存不可变标题、画幅和导演方案。后续外部 Agent 经 HTTP/MCP 提交严格 proposal/命令，Web 负责手工编辑、选择与 Approval；路由不直接修改业务事实。

`__main__.py` 读取一个或多个 `--provider-dir`，由 `provider_bundles.py` 读取各目录的 `slatehand-provider.toml`、检查 `requires`、导入 bundle 工厂，按目录顺序安装插件实例；bundle 服务在绑定端口后、开始响应前按序 `start()`（失败或启动期间中断时逆序关闭已启动的服务并退出），退出时逆序 `close()`。Server 不 import 任何具体插件。随后经 `core/media_tools` 在找到本机 ffmpeg 时注册确定性工具；项目与 Playground 共用同一个 `ProviderRegistry`，其能力绑定与插件设置持久化在 `.stories/.runtime/providers.json`。`api.py` 提供 `/api/settings/providers`（仅人类可改）读取与修改绑定和插件设置；新提交走当前绑定，历史句柄仍按插件身份回到原实现。插件设置在项目与 Playground 每次提交时读取当前值并记入快照，改设置不失效已有候选。新增模型只需另加一个 Provider 目录，沿用 recipe 协议和通用 Web 表单。SDK/CLI 不进入 Core；私有媒体服务独立部署。

`agent_timing.py` 为外部 Agent（`role=agent`）的项目与 Playground 命令写轻量计时日志 `.stories/.runtime/agent-timing.jsonl`：每行一条命令，
含调用方 ID、命令名、读取能力或 kind（`detail`）、状态、请求与响应字节数、Core 处理耗时 `core_ms`，以及上一次响应完成到本次请求到达的
`agent_ms`（Agent 自身思考、生成与传输耗时）。只记元数据，不记参数正文、响应正文或凭据；超过 8 MiB 时轮转为 `.prev.jsonl`，写入失败不影响请求。

`access.py` 的 `--access-policy-file` 提供受信 caller、项目 scope、有效期和精确 mutation grant；`writer.py` 锁定 stories inode，拒绝第二写服务和 symlink 祖先。

默认监听回环 `127.0.0.1:8765`。未配置策略的开发服务不能开放给外部 Agent。配置、正式入口与隔离要求见 [外部 Agent 接入](../docs/external-agents.md)。

`local_connection.py` 提供本机受信终端的 Unix 控制入口、一次性浏览器登录和单项目有限执行委托；连接不创建业务任务。
该入口与自定义策略互斥，不通过 HTTP 签发管理身份；不执行 Agent。默认启动与恢复见
[外部 Agent 接入](../docs/external-agents.md#一键接入流程)。
