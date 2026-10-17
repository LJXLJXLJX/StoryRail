# 连接自己部署的模型服务

适用于在本机或局域网 GPU 机器上运行的开源模型（ComfyUI 工作流、官方推理脚本、自建推理服务等）。
做法分两半：**模型服务**负责加载模型、排队、推理，并通过一个小 HTTP API 暴露异步任务；**插件**留在 Core 里，
只把 `RecipeRequest` 翻译成这个 API。

仓库里的 `default_model_providers_implement/` 是作者自用的完整参考实现（Windows GPU 节点上的 H3、SeedVR2、
IndexTTS、Qwen Image 等，含任务存储、GPU 互斥调度、控制租约和计划任务安装脚本）。新服务可以照着它的结构写，
也可以完全独立实现，只要满足下面的 HTTP 约定。

## 推荐的 HTTP 约定

每个模型能力一组路由，路径用模型名开头，不做通用 RPC：

| 方法与路径 | 作用 | 响应 |
| --- | --- | --- |
| `POST /<model>/generations` | 提交任务，JSON 体是该模型的封闭字段集 | `202 {"generation_id": "<32 位十六进制>"}` |
| `GET /<model>/generations/<id>` | 查询 | `200 {"stage", "progress", "message", 产物描述?, "error_code"?, "retryable"?}` |
| `PUT /<model>/generations/<id>/abort` | 取消 | `202`；已结束返回 `409` |
| `GET /<model>/generations/<id>/<产物类型>/<artifact_id>` | 取回字节 | `200` 原始字节 |

产物描述在服务端算好：`{"id", "mime", "bytes", "sha256", "duration_seconds"?}`，插件直接转成
`ArtifactDescriptor`。`core/model_providers/stable_audio_3/provider.py` 就是对接这套约定的最小插件，可以直接照抄。

服务端要点：

- 请求体严格校验：未知字段、越界值直接 `400`，不要默默忽略；服务端不接受任意文件路径、Shell、URL 或模型路径，
  模型和权重位置由服务自己的配置决定。
- 任务状态落盘（任务目录或 SQLite 都可以），服务重启后 `GET` 仍能查到已完成任务和产物。
- 同一张 GPU 上的多个模型要串行或显式调度，避免互相挤爆显存；进度文案（“排队中：前面还有 N 个任务”）
  由服务生成，插件原样转交。
- 输出 Core 接受的格式（PNG/JPEG/WebP、WAV、MP4）；需要转码就在服务里用 FFmpeg 完成。

## 绑定地址与认证

- 只在本机使用时绑定 `127.0.0.1`，可以不加认证。
- 要让另一台机器上的 Core 访问时，绑定一个明确的 LAN 地址（不要 `0.0.0.0`），并强制
  `Authorization: Bearer <token>`；未带 Token 的请求一律 `401`。
- Token 放在 Git 忽略的位置（服务端本机状态目录；Core 一侧放 `var/secrets/` 或 `start.local.env`），
  插件按 remote-api.md 的方式从环境变量读取：`STORYRAIL_<PACKAGE 大写>_API_KEY`。
- 机器路径、盘符、SSH、共享盘等部署细节只写在服务的 README 和本机配置里，不进入插件或 Core 的协议字段。

## 启动与联调

1. 先单独启动模型服务，用 `curl` 走通“提交 → 查询 → 取回”。
2. `./start.sh --provider-plugin <package>=http://127.0.0.1:<port>`（或 LAN 地址）启动 StoryRail。
3. 在「Provider 设置」绑定能力，到 Playground 跑一次真实生成，确认进度、取消和产物都正常。
4. 想让 `start.sh` 一并启停自己的服务时，参考 `start.sh` 里 Mac Provider 与 Windows Provider 的写法，
   开关和地址放进 `start.local.env`。
