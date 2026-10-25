# 外部 Agent 启动脚本

命令可打开 Pi、Codex CLI、Antigravity CLI、Kimi Code、DeepSeek Harness 或 Grok Build，不发送初始消息、不创建任务。用户可以询问当前应该做什么。
本机受信启动为当前项目授予有限执行委托，Agent 等待用户具体指令后调用正式工具，无需手改策略文件。
委托有有效期、项目范围和操作白名单，不包含人类审核、选择或直接文件访问权限。

`__main__.py` 准备工作区与隔离网络。独立的 `storyrail-native-pi-profile` volume 首次导入用户的
Pi auth.json、models.json、settings.json，之后不覆盖，支持 Pi 原生模型切换、登录与 OAuth 刷新。
不再导出短期 Bearer，不设置 provider/model/thinking，不生成私有模型 catalog，不改写 retry 设置。
外部 profile 与宿主 profile 独立，不将容器刷新后的凭据覆盖回宿主；新增登录可以在外部 Pi 中完成。

## Playground scope（`--playground`）

从 Playground 页面复制的命令使用 `--playground`，与 `--project` 互斥，两者必须二选一；同时给出或都不给出时
启动器直接报错并要求重新复制启动命令。Playground 模式：

- 锁文件为 `<socket 目录>/playground.launch.lock`，同一时刻只允许一个 Playground Agent；
- 控制请求发送 `{"action": "connect_playground"}`，凭据只有 `playground.use`、`project_ids=[]`，有效期 30 天；
- Docker volume 为 `storyrail-<agent>-playground`，与任何项目工作区隔离；
- gateway 容器只设置 `STORYRAIL_SCOPE=playground`（不传 `PROJECT_ID`），只放行 `POST /api/playground/commands`；
- 工作区写入 `startup.json = {"scope": "playground"}`（不含 project_id）和来自 `/app/PLAYGROUND_PROMPT.md` 的
  `AGENTS.md`；
- MCP 启动参数追加 `--scope playground`，只发布 Playground 的 5 个工具，不向项目 Agent 暴露 Playground。

`prepare_build_context` 定义镜像内 `/app` 的完整布局：`integrations/storyrail_mcp`、`storyrail_contracts`、
`BUILD_CONTEXT_FILES`（含 `PROMPT.md` 与 `PLAYGROUND_PROMPT.md`），以及 `CORE_TEXT_FILES` 列出的 Core 纯文本
单一事实源（目前是 MCP instructions 引用的 `consistency_instruction.md`），不复制 Core 代码或作品。修改其中任一
文件都会改变 `agent_build_digest` 并触发镜像重建；构建上下文与摘要都忽略 `__pycache__`。
测试只用该布局隔离启动 MCP 并完成 initialize 握手。

六种 Agent 共用唯一镜像 `storyrail-external-agents:latest-v1`。首次构建一次安装全部 CLI：Pi、Codex、
DeepSeek Harness 与 Grok 通过官方 npm 包的 `@latest` 安装；AGY 与 Kimi Code 使用官方安装器的 latest
发布入口，保留 manifest 字节校验。选择不同 Agent 只改变启动命令、工作区卷和原生配置卷，直接复用同一镜像。
镜像构建使用跨项目、跨 Agent 的 `agents-image.build.lock`，等待锁后重新检查源码摘要。
普通源码变化会重建公共镜像，但复用位于源码 COPY 前的依赖安装层，不重新下载 CLI。
删除项目容器不会更新 CLI；需要更新全部 Agent 时，在连接命令末尾添加 `--update-agents`，此次构建
禁用层缓存以重新获取官方 latest。后续连接再次复用更新后的公共镜像，不在只读容器内升级。

`client.py` 仅准备项目 AGENTS.md 和无凭据的 startup.json，然后启动所选原生 Agent。它也提供固定 MCP 工具调用入口。
`--debug`（项目与 Playground 均可）让 `client.py start` 把 `/app/integrations/storyrail_mcp/debug_prompt.md` 放在 AGENTS.md
最前面并在 startup.json 写入 `"debug": true`；`client.py mcp` 读到该标记后给 adapter 追加 `--debug`。
`gateway.py` 只转发当前项目 Core 路径，并提供认证的公共 HTTPS CONNECT 隧道；拒绝非 443、私有/回环地址。
系统 DNS 返回非公网地址时，网关通过固定的 `https://1.1.1.1/dns-query` 重新解析 A 记录（标准 TLS 证书校验），
处理本机代理的 Fake-IP；只有全部结果均为公网 IP 才连接已校验的具体地址。解析失败仍拒绝，不能直接放行虚拟私网地址。
启动器优先读取 `HTTPS_PROXY`（兼容小写与 `HTTP_PROXY`）；变量未设置时，macOS 通过 `scutil --proxy`
读取当前启用的系统 HTTPS/HTTP 代理。只接受无认证的本机 HTTP 代理，向 gateway 传入端口，
由 `host.docker.internal` 访问；Agent 仍只拿到隔离 gateway 的认证代理地址。
`gateway.HOST_PROXY_TARGETS` 列出的固定 Google API 域名通过公网预检后，经宿主代理 CONNECT 原域名，
使 Clash 等代理按域名选择与宿主 AGY 相同的出口。此分支信任宿主代理对这些厂商域名的再次解析；
其它域名或 IP 仍连接已校验 IP、防止 DNS 重绑定。指定的宿主代理连接失败返回 502，不回退直连。
模型 TLS 端到端透传，StoryRail 不解析模型协议、不保存模型凭据、不筛选模型 ID，也不替代 Agent 刷新。

Agent 仍处于非特权只读容器、内部网络，不挂载宿主 home、作品或 Docker socket。
npm 缓存与安装日志使用可写的 `/tmp/npm-cache`，避免默认 `/.npm` 在只读根目录下失败；
Pi 扩展仍安装到持久 profile 的 `/pi/npm`，容器退出只清理缓存，不清理已安装扩展。
本机自建的私有网络模型服务不在默认网络权限内；需要单独明确的部署配置。

## Codex CLI

网页选择 Codex CLI，复制 `--agent codex` 命令到终端。使用通用镜像内的 `@openai/codex@latest`。
工作区为 `storyrail-codex-<project_id>`，原生配置单独保存在 `storyrail-native-codex-profile`（`CODEX_HOME=/codex`）。
同一项目的启动租约在所有 Agent 间共用，避免并发覆盖连接。

首次初始化只导入宿主 `CODEX_HOME`（默认 `~/.codex`）下文件形式的 `auth.json`，不导入配置、其它 MCP、插件、会话或项目文件。后续不覆盖容器内登录刷新结果，也不回写宿主。宿主使用系统钥匙串或没有缓存时，在容器 Codex 登录界面选择设备码；不读取系统钥匙串、不自动发起登录。

Codex 启动参数注册必需的原生 `storyrail` stdio MCP，由固定 `client.py mcp` 入口连接现有 adapter。参数不含 Token，不设置模型，不附带 prompt；模型选择与会话由 Codex 管理。公共 HTTPS 与项目 Core 路由沿用现有隔离网关，Codex 不获得宿主源码、作品、Provider 或 human 权限。

配置依据：[官方 MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)与[官方登录缓存/设备码说明](https://learn.chatgpt.com/docs/auth)。

## Antigravity CLI

网页选择 Antigravity CLI，复制 `--agent agy` 命令到终端。镜像构建时使用[官方安装器](https://antigravity.google/cli/install.sh)
解析 latest 并按官方 manifest 校验 SHA-512，安装在通用镜像内。工作区为
`storyrail-agy-<project_id>`，独立 HOME 保存于 `storyrail-native-agy-profile`。CLI 使用
`--dangerously-skip-permissions` 启动；权限仍受只读、非 root、无宿主工作区的容器边界约束。启动时只把固定的
StoryRail stdio MCP 合并进容器配置，不导入宿主的插件、MCP、会话、项目文件或系统钥匙串；首次连接在
容器 CLI 内完成登录，后续刷新仅保留在隔离配置卷。AGY 不接收初始 prompt、模型或执行模式参数，仍由用户
在原生 CLI 中选择模型并下达任务。隔离网络、当前项目 Core 白名单和人类审核边界与 Pi/Codex 相同。

Docker 回归：`STORYRAIL_DOCKER_TESTS=1 .venv/bin/python -m pytest tests/test_agent_onboarding_docker.py` 覆盖全部 Agent 空闲启动、原生 MCP 配置、stdio 实际读取，以及宿主与非授权 Core 路由拒绝；只使用合成身份，不验证真实账号登录或模型推理。

## Kimi Code

网页选择 Kimi Code，复制 `--agent kimi` 命令到终端。镜像构建时使用[官方安装器](https://code.kimi.com/kimi-code/install.sh)
解析 latest，并按官方 manifest 校验 SHA-256。工作区为
`storyrail-kimi-<project_id>`，独立 HOME 为 `KIMI_CODE_HOME=/kimi-code`，不导入宿主 Kimi 配置、凭据、插件或历史。
启动入口默认使用 `kimi --auto`（完全自动权限模式），并在隔离 profile 中写入唯一的 StoryRail stdio MCP
配置；首次连接需在容器 CLI 内完成登录，登录态保留在 `storyrail-native-kimi-profile` 卷。容器仍是非特权、只读根目录，
没有宿主工作区、Docker socket 或跨项目 Core 路由。

## DeepSeek Harness

网页选择 DeepSeek Harness，复制 `--agent dsh` 命令到终端。镜像构建时安装官方 `@deepseek-ai/dsh@latest`，工作区为
`storyrail-dsh-<project_id>`，原生配置保存在独立的 `storyrail-native-dsh-profile`（`DSH_HOME=/dsh`）。
官方 Harness 的交互入口是 Web profile；启动后仅向宿主 `127.0.0.1` 发布随机端口并自动打开浏览器，容器内 Web 服务仍绑定
回环地址。StoryRail MCP 通过固定的 `@deepseek-ai/dsh-mcp-client` stdio patch 注入，不读取宿主配置、凭据或其它 MCP。
启动时设置官方 `NARB_DISABLE_NATIVE_CACHE=1`，直接加载只读镜像内的原生模块，避免复制到禁止执行的 `/tmp`。

默认环境变量为 `DSH_PERMISSION_MODE=danger-full-access`，对应 Harness 的 `danger-full-access` 沙箱和 `never` 审批；
这只表示容器内会话不再逐次询问，外层仍是非特权、只读根、无宿主目录、无 Docker socket 的隔离容器。首次连接在
DeepSeek Harness Web UI 中配置 API 凭据，凭据只保存在隔离 profile。

## Grok Build

网页选择 Grok Build，复制 `--agent grok` 命令到终端。镜像构建时安装官方
`@xai-official/grok@latest`，工作区为 `storyrail-grok-<project_id>`，原生配置保存在独立的
`storyrail-native-grok-profile`（`GROK_HOME=/grok`）。启动时只替换隔离 profile 中名为
`storyrail` 的 stdio MCP，不读取或导入宿主 Grok 配置、凭据、插件、会话和项目文件。

Grok 以原生交互 TUI 空闲启动，不接收初始任务或固定模型。首次连接在隔离 CLI 中完成登录，登录态与后续
刷新只保留在 profile volume。外层仍使用非特权、只读根、内部网络、无宿主目录和无 Docker socket 的
统一隔离边界；当前项目 Core 路由与人类审核限制不变。

Mac 图片粘贴：复制图片后，在启动器终端按 Ctrl+V。宿主仅在此按键读取 PNG，最多 16 MiB。
Codex 分支经 docker exec stdin 写入容器 `/tmp` 的独占临时文件（权限 0600），X11 仅发布小型
`text/uri-list`，由 Codex 原生文件图片粘贴入口读取。文件留在当前容器临时目录，退出容器后回收。
Pi 保留 `image/png` 路径。容器回读图片和剪贴板内容，返回字节数与 SHA-256；宿主核对回执后才转发按键。
虚拟显示禁用 TCP，容器仍是非特权、只读根目录，不挂载宿主文件系统或 Docker socket。
失败时不转发粘贴，不将“docker exec 返回成功”当成图片已就绪。

回归 `test_agent_clipboard_native.py` 在无网络、合成登录和临时工作区中运行真实 Codex TUI，连续粘贴 512、2048、32、2048 像素 PNG，核对附件标记与 Codex 临时图片尺寸；不发 Enter，不调用模型。运行：
`STORYRAIL_DOCKER_TESTS=1 .venv/bin/python -m pytest tests/test_agent_clipboard.py tests/test_agent_clipboard_native.py`。

实现依据是 [Codex 0.154.0 原生图片粘贴](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/tui/src/clipboard_paste.rs)：
先读取剪贴板文件列表再读取像素。使用单个无尾随 CR 的 URI，适配其固定 arboard 3.6.1 的路径解析。
