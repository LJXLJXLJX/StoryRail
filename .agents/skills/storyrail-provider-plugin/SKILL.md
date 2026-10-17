---
name: storyrail-provider-plugin
description: 为 StoryRail 开发新的媒体 Provider 插件（生图、改图、视频、超分、TTS、音色设计、ASR、文生音频、音轨分离），无论是接入云端 API 还是连接自己本地部署的模型服务。用户想“接入某个模型/某家 API”“换一个视频/图片/语音模型”“把本地跑的模型接进 StoryRail”时使用。
---

# StoryRail Provider 插件开发

StoryRail 的每个媒体能力都由 Core 侧插件提供。插件是 `core/model_providers/<package>/` 下的一个 Python 包：
用 manifest 声明自己实现哪些 recipe、需要哪些输入，再把 Core 校验好的通用请求翻译成某个外部 HTTP API 的调用。
项目流程、候选选择和审核都与插件无关；插件只负责“提交任务 → 观察进度 → 取回字节”。

开始前先读本目录的 `references/plugin-contract.md`，它是插件与 Core 之间的完整契约。然后按接入方式读：

- 接入云端 API（需要 API Key、厂商托管模型）：`references/remote-api.md`；
- 连接自己部署的模型服务（本机或局域网 GPU）：`references/local-service.md`；
- 写代码时照抄 `references/templates.md` 的骨架，再按目标 API 修改。

## 工作顺序

1. **问清目标。** 接哪个模型、哪项能力（见契约的能力表）、云端还是本地、API 文档在哪里。
   拿到 API 文档后再动手，不要凭记忆猜接口字段。一个模型的“重新生成”和“基于底图编辑”请求语义不同时，
   分成两个 recipe，不要做成一个可选参数袋。
2. **对照能力表设计 manifest。** 先确定 Core 会填哪些语义角色（提示词、时长、首尾帧、参考图……），
   模型额外需要、但 Core 没有领域事实的参数，声明为无角色的机制参数；模型级、跨任务不变的选项声明为插件设置。
   不能发明新的 `Role`、`Capability` 或 `Widget`：它们是 Core 的封闭词汇，确实不够用时先停下来告诉用户，
   那是 Core 改动，不是插件改动。
3. **写严格的请求 DTO 与 Provider。** `to_request` 把 `RecipeRequest` 翻译成本插件的 frozen dataclass，
   在 `__post_init__` 里校验范围；Provider 实现 `submit_recipe` / `observe` / `cancel` / `read_artifact`
   （ASR 是同步的 `execute_recipe`）。外部响应逐字段严格校验，未知字段和缺字段都按 `invalid_response` 拒绝。
4. **写测试。** 用假 transport 覆盖：请求体逐字段断言、各阶段映射、失败与可重试判断、句柄归属检查、
   产物字节读取、manifest 能被 `PluginInstance` 接受。不访问真实网络、不加载模型。
5. **写 README 并登记。** 插件目录必须有简洁 README（能力、外部接口、凭据来源、限制）；在
   `core/model_providers/README.md` 与 `STRUCT.md` 登记；引入第三方文本或代码时登记 `THIRD_PARTY_NOTICES.md`。
6. **跑门禁，再真机试一次。** 跑 README 中的工程门禁；然后用
   `./start.sh --provider-plugin <package>=<endpoint>` 启动，在顶栏「Provider 设置」把能力绑定到新插件，
   先在 Playground 跑通一次真实生成，再进项目使用。真实调用会产生费用，先征得用户同意。

## 硬规则

- 插件实例 ID、manifest `plugin_id` 与包名三者相同；recipe ID 以 `<package>.` 为前缀。
- 插件不接触项目、Scene、Shot、候选或审核；只接收 `RecipeRequest` 里的受控字段和媒体字节。
  不把本机路径、项目语义 ID、任意 URL 或命令传给外部服务。
- 凭据只从环境变量或 Git 忽略的文件读取（例如写在 `start.local.env` 里），绝不进入代码、manifest、
  插件设置、日志、错误信息或测试夹具。插件设置会显示在页面上并写进每次 Generation 的快照，不能放密钥。
- 改变已提交请求的语义（字段含义、默认值、输出格式）时提升 `plugin_version`，并保留旧句柄的观察与取回能力，
  历史 Generation 按句柄里的 `plugin_id` 与版本回到原实现。
- 失败要明确：外部错误映射为 `ModelProviderError` 或 `failed` 观察，不静默降级到别的模型、参数或分辨率，
  不在插件里自动重试会产生费用的提交。
- 不修改 Core 的状态机、Role/Capability 词汇或其它插件来迁就新插件；需要时先向用户说明并单独讨论。
