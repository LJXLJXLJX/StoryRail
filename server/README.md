# StoryRail Server

HTTP 装配连接 Project Workspace、Core application、媒体 Provider 和 Web 资源。Server 不包含任何 Agent backend、模型会话或厂商参数。部署拓扑见 [媒体 Provider 与部署](../docs/providers-and-deployment.md)。

`POST /api/projects` 只保存不可变标题、画幅和导演方案。后续外部 Agent 经 HTTP/MCP 提交严格 proposal/命令，Web 负责手工编辑、选择与 Approval；路由不直接修改业务事实。

`__main__.py` 按启动参数安装 Codex/AGY 图片、Demucs、Breeze TTS、Whisper、MiniMax H3、SeedVR2 与 Stable Audio 插件实例，并直接注册 FFmpeg 确定性工具；项目与 Playground 共用同一个 `ProviderRegistry`，其能力绑定与插件设置持久化在 `.stories/.runtime/providers.json`。`api.py` 提供 `/api/settings/providers`（仅人类可改）读取与修改绑定和插件设置；新提交走当前绑定，历史句柄仍按插件身份回到原实现。H3 渲染组合由 `minimax_h3` 插件设置换算，项目与 Playground 每次提交时读取当前值，改设置不失效已有候选。`provider_plugins.py` 支持 `--provider-plugin 包名=HTTP endpoint` 装配已安装的附加插件；新增模型沿用 recipe 协议和通用 Web 表单。SDK/CLI 不进入 Core；私有媒体服务独立部署。

## Breeze-TTS-2

StoryRail 的 Windows 默认 Provider 通过 `--breeze-endpoint` 连接同一受认证模型服务；Breeze runtime 由 `exclusive_gpu` 调度器按需启动，不会在开机时加载，也不会与 H3 同时驻留。它仍复用已有的 WSL 中已有的 `breeze-tts/.venv` 和模型目录，不会 clone、创建 venv、安装依赖或使用 Docker。手工启动官方 API 仅用于兼容旧部署：

```text
cd ~/ai/breeze-tts
.venv/bin/python -m breeze_infer.api ~/ai/models/Breeze-TTS-2 --host 0.0.0.0 --port 7860
```

随后 StoryRail Server 增加 `--breeze-endpoint http://<windows-lan-ip>:8791`。音色设计与声音克隆都走 Breeze TTS 2；Clone/Direction 请求必须保存参考音频完整文字稿。Breeze 只在真实任务期间启动，H3 请求进入队列时调度器先释放 Breeze；不应再注册独立的 `StoryRail Breeze TTS 2` 开机任务。

## Whisper ASR

`--whisper-endpoint` 连接本机 `whisper.cpp` server，为 Breeze Reference Voice 提供中英文自动转写候选。例如：

```text
whisper-server --host 127.0.0.1 --port 8793 \
  --model var/whisper-asr/ggml-large-v3-turbo-q5_0.bin \
  --language auto --flash-attn
```

再向 StoryRail Server 增加 `--whisper-endpoint http://127.0.0.1:8793`。`start.sh` 在发现
`whisper-server` 和上述默认模型文件时会自动完成这两步；也可通过
`STORYRAIL_WHISPER_SERVER`、`STORYRAIL_WHISPER_MODEL` 和 `STORYRAIL_WHISPER_ENDPOINT`
覆盖。服务只绑定回环地址。识别结果仅回填 Web 文本框，用户校对并提交 Breeze 后才进入业务状态；
Agent 没有 ASR 入口或自动转写提示。
`agent_timing.py` 为外部 Agent（`role=agent`）的项目与 Playground 命令写轻量计时日志 `.stories/.runtime/agent-timing.jsonl`：每行一条命令，
含调用方 ID、命令名、读取能力或 kind（`detail`）、状态、请求与响应字节数、Core 处理耗时 `core_ms`，以及上一次响应完成到本次请求到达的
`agent_ms`（Agent 自身思考、生成与传输耗时）。只记元数据，不记参数正文、响应正文或凭据；超过 8 MiB 时轮转为 `.prev.jsonl`，写入失败不影响请求。

`access.py` 的 `--access-policy-file` 提供受信 caller、项目 scope、有效期和精确 mutation grant；`writer.py` 锁定 stories inode，拒绝第二写服务和 symlink 祖先。

默认监听回环 `127.0.0.1:8765`。未配置策略的开发服务不能开放给外部 Agent。配置、正式入口与隔离要求见 [外部 Agent 接入](../docs/external-agents.md)。

`local_connection.py` 提供本机受信终端的 Unix 控制入口、一次性浏览器登录和单项目有限执行委托；连接不创建业务任务。
该入口与自定义策略互斥，不通过 HTTP 签发管理身份；不执行 Agent。默认启动与恢复见
[外部 Agent 接入](../docs/external-agents.md#一键接入流程)。
