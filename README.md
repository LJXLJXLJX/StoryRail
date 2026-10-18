# StoryRail（镜序）

[English](README.en.md)

**让你常用的 AI Agent 当剧组，你当导演。** StoryRail 把一份完整的导演方案，做成镜头连贯、每一步都可审核、
改动可追溯的影片。

Agent 负责拆脚本、规划关键帧、写提示词和提交生成；StoryRail Core 掌管项目的全部事实：Agent 的每一次写入
都要经过它的校验，选哪条素材、成片是否通过，只能由你决定。

## 为什么是 StoryRail

### Agent 干活，Core 立规矩

很多 AI 视频 Agent 方案让 Agent 直接读写项目文件、自己调用模型 API，“先给我确认再生成”只写在提示词里。
Agent 记错了、理解偏了、上下文被压缩了，项目就可能被悄悄改坏，或者在你不知道的时候花掉生成费用。

StoryRail 把这些规则交给系统执行，不交给 Agent 自觉：

- **Agent 碰不到项目文件。** 它运行在非特权 Docker 容器里：只读根文件系统，看不到宿主 home、作品目录、
  源码和 Docker socket，也拿不到生图、视频、语音等生成服务的凭据，只能通过 MCP 网关调用 Core 开放的
  类型化操作。
- **每次写入都经过校验。** Agent 提交的是类型化 proposal 或命令；Core 校验版本号、授权范围、当前状态和
  领域规则，不满足就拒绝并说明原因。并发冲突、越权、过期的计划都写不进去。
- **生成和拍板分开。** Agent 只能在你明确要求时提交生成；采用哪条候选、审核确认、最终 Approval，
  只能由你在浏览器里完成，系统层面不给 Agent 这些权限。
- **改得动，找得回。** 上游一改，Core 只失效真正依赖它的下游选择与装配，其余保持不动；生成过的媒体和
  每次生成的输入快照永不删除。中断后按持久化的任务状态恢复，结果未知的提交不会自动重试，不会重复扣费。

### 镜头连贯是设计出来的

AI 视频做叙事，最难的是让同一个人、同一个房间在几十个镜头里保持一致。StoryRail 不靠提示词碰运气：

- **地点库：** 室内空间先生成一张 2:1 全景图，各机位视图由 Core 从全景确定性裁切后再细化，同一房间在
  不同镜头里结构一致；昼夜、天气、布置变化作为同一地点的状态，而不是新地点。
- **角色造型：** 每个角色可以有多套造型（不同时期、服装、状态），每个关键帧明确选择本帧用哪一套。
- **镜头边界：** 每段视频有首尾关键帧，相邻段可以共享同一边界帧，并在接缝处做短融合；也可以从上一段
  视频的任意一帧抽取作为下一段的首帧。
- **旁白定时：** 先合成并选定真实旁白音频，再按实际时长校准镜头；中英双语可以共用同一套画面。

### 自带 Agent，自选模型

- **Agent 用你已有的：** Pi、Codex CLI、Antigravity CLI、Kimi Code、DeepSeek Harness、Grok Build 一键接入，
  模型和账号都由 Agent 自己管理。换 Agent 不用换项目，同样的规则对所有 Agent 生效。
- **模型是插件：** 图片、视频、TTS、超分、ASR、音频处理都以插件接入，每项能力单独选择插件，可以跑在本地
  显卡上（例如 MiniMax H3 视频、Qwen Image、IndexTTS、SeedVR2）。插件在 Core 侧把外部 HTTP API 翻译成统一的
  生成语义，换模型不影响项目和 Agent。仓库自带 [`storyrail-provider-plugin`](.agents/skills/storyrail-provider-plugin/SKILL.md)
  Skill，让 Claude Code 或 Codex 帮你接入任意云端 API 或本地部署的模型。
- **项目就是文件夹：** 一个 `project.json` 加一个素材目录，没有数据库。素材按内容哈希校验、不可变，
  易于备份和迁移。

## 适合谁

- 想认真做多镜头叙事影片（剧情短片、旁白纪录片、漫剧），愿意自己做导演决定的个人创作者和小团队；
- 已经在用 AI 编程 Agent，希望它承担繁重工作、又不想让它失控的人；
- 能自己部署模型服务的进阶用户。

不太适合：想“一句话出片”的需求，或者不想碰本地部署的用户。目前的一键启动脚本面向 macOS；默认的视频与
语音模型服务运行在一台带 NVIDIA 显卡的 Windows 机器上。

## 工作方式

```text
写好导演方案（可用导入页的提示词和任意 AI 一起完成）
→ 建立角色、造型与声音引用库，由你确认
→ Agent 生成 Scene / Shot / Segment 结构化脚本
→ 合成并选定旁白，按真实时长校时
→ 可选：规划地点库，按需生成普通图或全景图；全景可在 3D 预览中手动取景
→ 规划关键帧并生成，由你挑选
→ 生成 Segment 视频与超分，由你挑选
→ 生成 Scene 成片与全片，由你 Approval
```

脚本生成后，旁白、地点库、关键帧、视频和成片都在同一个导演台里累加显示：左侧导航是 Scene → Segment，
Scene 页另有镜头设计列表。
还没有方案时，导入页提供「创作搭档提示词」，复制给你常用的 AI，从一个想法聊到完整方案；已有分镜表的，
用「方案整理提示词」整理成可导入的格式。

另有一个与项目隔离的 Playground，用生产同一批模型插件单独调试生图、改图、TTS、视频、超分和音频处理，
详见 [Playground](docs/playground.md)。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm --prefix web ci
./start.sh
```

`start.sh` 构建 Web，启动 Core、Web 与可用的本机模型服务，并打开已登录的页面；再次运行可重新打开页面，
Ctrl+C 同时停止全部服务。本机部署配置（Windows 模型服务地址、SSH 别名等）写在 Git 忽略的
`start.local.env`，模板见 `start.local.env.example`，变量说明见 [部署说明](docs/providers-and-deployment.md#startsh)。
自定义部署可用 `./start.sh --access-policy-file /path/to/policy.json` 改用独立的 caller 策略。

进入项目后点击 Logo 旁的「连接 Agent」，选择你使用的 Agent，把启动命令复制到终端即可。首次需要已安装
Docker Desktop 或 OrbStack。之后可以直接问 Agent“现在该做什么”；启动本身不会发送任务或改动项目。
详见 [外部 Agent 接入](docs/external-agents.md)。

顶栏「Provider 设置」为每项能力选择插件并调整插件设置，只影响之后提交的任务。默认模型服务的部署方式见
[`default_model_providers_implement/`](default_model_providers_implement/README.md)。

## 技术边界

- `.stories/<项目名>-<project_id>/project.json` 是唯一业务事实源（当前 schema v35），`assets/` 保存不可变媒体；
  更早版本不迁移，需新建项目。删除项目只移入 `.stories/.trash/`。
- Core 是 ID、revision、scope、授权、失效、血缘、幂等和状态迁移的唯一 authority；Web 只消费 Core 返回的
  状态与 `allowed_actions`，不复制状态机。
- Agent 通过 HTTP/MCP（25 个固定工具）读取有界投影和专业 Skill，只能提交类型化 proposal 或精确授权命令。
  StoryRail 不内置 Agent、不持有厂商会话，也没有隐藏 fallback。
- 模型 Provider 只由 Core 调用，只接收完成媒体任务所需的受控输入。

完整产品说明书见 [docs/](docs/README.md)；开发 StoryRail 本身从 [AGENTS.md](AGENTS.md) 与 [目录说明](STRUCT.md)
开始，业务保护规则见 [业务状态保护](docs/business-state-protection.md)。

## 工程门禁

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest -n auto
cd web && npm run typecheck && npm test && npm run build
git diff --check
```

`-m "not slow"` 是默认选择，跳过 `slow` 标记的重测试；合并分支或改动对应模块前运行
`./scripts/ci_local.sh --full` 全跑。等价的一键本地脚本：`./scripts/ci_local.sh`。push/PR 到 main 与
`refactor/**` 分支时 GitHub Actions（`.github/workflows/ci.yml`）跑同一套默认门禁。

## 文档

- [文档索引](docs/README.md)
- [产品概览](docs/product.md)
- [系统架构](docs/architecture.md)
- [数据模型](docs/data-model.md)
- [生产工作流](docs/production-workflow.md)
- [控制流](docs/control-flow.md)
- [数据流](docs/data-flow.md)
- [命令目录](docs/commands.md)
- [外部 Agent 接入](docs/external-agents.md)
- [媒体 Provider 与部署](docs/providers-and-deployment.md)
- [目录与依赖](STRUCT.md)

## 许可证与负责任使用

StoryRail 自身代码与文档以 [Apache License 2.0](LICENSE) 发布。随仓库分发的 MiniMax H3 与 Qwen Image
提示词 Skill 保留各自上游许可证，详见 [第三方来源说明](THIRD_PARTY_NOTICES.md)；所接入的模型与权重
同样受其发布方许可证约束，由使用者自行遵守。

StoryRail 是个人开源项目，按“原样”提供，不附带任何担保。请只用它创作你有权使用的内容：不要生成冒充真实
人物的深度伪造、未经许可使用他人肖像或声音、侵犯版权，或制作违法、欺诈、骚扰性质的内容。使用者对生成
内容及其传播承担全部责任。
