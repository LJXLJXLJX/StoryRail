# StoryRail MCP

把固定 MCP 工具翻译成 Core HTTP 命令的窄 adapter。固定使用官方 Python SDK `mcp==2.2.0`（MIT），协商协议 `2026-07-28`；SDK 负责协议、
stdio 与取消，本包负责严格工具参数到 HTTP 命令的映射。它不启动 Core、不打开任何业务目录、不持有 Store。

工具清单、授权模型与 Agent 行为准则见 [外部 Agent 接入](../../docs/external-agents.md)；错误分类见 [错误契约](../../docs/error-contract.md)。

```sh
.venv/bin/python -m integrations.storyrail_mcp --core-origin http://127.0.0.1:8765 --token-file /protected/agent-token
```

这是受信启动配置，不是模型工具参数。`--debug` 把 `debug_prompt.md`（调试模式提示词，与工作区 AGENTS.md 共用）
放在 instructions 最前面，项目与 Playground scope 都支持。token 是专属限域 Agent Bearer，文件权限 0600；不得交给 adapter 人类或 Provider 凭据。必须连接启用了
caller 策略（本机一键接入或 `--access-policy-file`）的既有单写服务；未配置策略的匿名开发服务不能作为外部 Agent 后端。Core origin 固定于
启动配置，不跟随重定向或宿主代理。

## 文件

- `app.py`：工具模型、发布 schema 与分派；项目 scope 与 Playground scope 两个 server。
- `production_tools.py`：编辑、生成、批次、装配、Generation 管理等工具的严格嵌套 schema 与固定翻译（不 import Core/Store）。
- `playground_tools.py`：Playground scope 的 5 个工具。
- `bridge.py`：到 Core 的 HTTP 传输、错误信封映射与响应序列化。

## 项目 scope（默认）

`tools/list` 发布 28 个工具，逐字节基线是 `tests/fixtures/mcp_project_tools.json`。`read_human_handoff`、`read_workflow_state`、
`script_proposal`、`reference_proposal`、`location_proposal`、`keyframe_proposal` 仍可调用但不下发 schema；统一提交入口是
`submit_proposal`（`capability` 为 `script`、`reference_library`、`location` 或 `keyframe`）。submit 可直接内联 `proposal`；大型
proposal 可改用 `proposal_source={kind:"workspace_json", byte_count, sha256}`，adapter 只读取固定
`/workspace/proposals/<request_id>.json`，不接受模型提供路径。文件必须是 ≤1 MiB 的普通 UTF-8 JSON，大小和 SHA-256 完全匹配；
adapter 解析为对象后仍走同一 Core proposal 命令、revision CAS 和完整领域校验，文件本身不是项目事实。地点规划与引用库、脚本一样使用项目 scope：
`read_professional_workset` / `read_professional_contract` 的 `capability="location"` 不带 `scene_ids`，`location_proposal` 的 request
只有 `raw_user_instruction`，翻译为 `location.*_proposal`。`edit_script`、`edit_keyframes`、`edit_locations`、`edit_looks` 发布严格的操作 schema：
每个 `op` 分支同时公开嵌套字段形状、枚举和必填项，并由同一 runtime 模型校验；`edit_looks` 翻译为 `reference.apply_look_operations`，字段形状随 reference_library 契约
（`references/look-sheets.md`）下发；`edit_locations` 各操作的字段形状随 location 专业契约（`references/location-bible.md` 附录）下发。`edit_locations` 翻译为 `location.apply_operations`，顶层 `location_ids`、`scene_ids`
组成 scope；不提供地点图片候选选择。`select_keyframe_candidate` 翻译为 `keyframe.select_candidate`，是唯一的候选采用工具（只限该 Keyframe 的成功、未隐藏图片候选）。`generate_media` 的 `look_sheet` 翻译为 `reference.generate_look_sheet`（`identity_asset_ids` 为 0–4 张身份参考）；
`reference_image` 翻译为 `video.generate_reference_image`（`target_id` 为图片规划 ID）；`save_reference_image_plan`
以 Scene scope、Segment ID 和 0–3 槽位保存一张任意内容的其他图片规划，完整字段在 tools/list 下发，不生成、不选择。
`read_story` 的 Segment `selection` / `keyframe` / `video_prompt` 扩展返回 `video_inputs`，Keyframe 与视频专业工作集也给出
`video_inputs[]`：包含规划 ID、画面正文、选图状态与实际绑定；已绑定图片即使没有规划也可按 Asset ID 读取。
`location_image` / `panorama_capture` 分别翻译为 `location.generate_image` / `location.capture_panorama`。`media_batch` 的 `kind` 选择批次类型：`keyframe` 翻译为
`keyframe.generate_batch` / `keyframe.continue_batch`，`location` 翻译为 `location.generate_set`
（start 带 `target_ids` 固定地点图片范围，continue 带原 `batch_id` 或关联 `execution_run_id`）。

参数规则：

- 工具顶层与嵌套请求都拒绝未知字段；条件参数用公开 `oneOf` 表达，与 runtime 共用同一参数矩阵（`read_story` 的 level 分支、专业 workset
  的项目级/Scene 级能力、`media_batch` 的 kind/start/continue、`assemble_media` 的 scene/final、`manage_generation` 的 wait/单目标；wait 只观察，可省略 `expected_revision` 与 `idempotency_key`）。
- proposal 按 action 给出互斥字段分支；为兼容会把可选字段补成 null 的原生连接器，非当前 action 的 null 被归一为省略，非 null 越界值仍拒绝，
  且不会传入 Core。非法组合返回固定字段说明，不回显正文、凭据或本机路径。
- `submit_proposal` 的 submit 必须且只能提供 `proposal` 或 `proposal_source` 之一。工作区文件名由当前 `request_id` 确定，adapter
  拒绝 symlink、非普通文件、校验变化和非 object JSON；同一文件可配合同一 revision/idempotency key 重放。
- 读工具的幂等键由 MCP 生成（`mcp-read:<uuid>`）；写工具的 `idempotency_key` 必须由模型提供。
- 旁白固定中英双语：`edit_narration.fields` 的正文与合成参数放在 `zh` / `en` 子对象；`generate_media` 生成旁白必须指定 `language`；
  `edit_narration.fields.clear_selected_audio = "zh" | "en"` 独占一次调用并翻译为 `narration.clear_selection`。
- `save_video_prompt` 不带 `recipe_inputs` 与 `attach_dialogue_audio` 时翻译为 `video.set_prompt`；带任一项时翻译为
  `video.update_recipe_inputs`：正文整体保存，`bindings` 按槽位、`params` 按键合并（缺省为 `{}`），`attach_dialogue_audio: true`
  由 Core 合并本段已选对白 TTS。两种保存的回执 `data` 都是写入后的紧凑摘要（`prompt_chars`、`recipe_inputs`、
  `asset_inputs`、`prompt_problems`、`dialogue_audio.error/unbound_lines`），Agent 不必为确认保存重读工作集。发布 schema 只把 `recipe_inputs` 声明为 object，形状随
  `video_prompt` 工作集的 `recipe_inputs` 下发；runtime 模型仍严格校验 `{asset_id, description}` 绑定项并拒绝未知字段。

响应：

- Agent 写工具走 `/application/commands`，成功时返回 workflow、receipt、new revision、warnings、ApplicationRequest/replay 与紧凑目标 data，
  不夹带 Web 全项目快照。
- `/application/commands` 接受至多 2 MiB 的 JSON，以容纳 adapter 已验证、重组后的 ≤1 MiB proposal 与命令信封；其它普通 JSON 路由仍保持 64 KiB 上限。
- text content 始终是完整 JSON，`structured_content` 携带同一份数据；只读 text 的客户端（如 AGY）也能直接拿到结果。
- `read_media_input` 校验受控 Asset 后同时返回原生 image/audio 内容块，供模型实际看图或听音；JSON 保存媒体清单与校验信息，图片字节不混入正文。读取失败时只返回错误。
- 随当前绑定插件发布的提示词 Skill 全文只在 `read_professional_contract` 中（`plugin/` 资源，可用 `if_hash` 缓存）；工作集的
  `plugin_skills` 只是目录，单个 Segment 的视频工作集因此通常不分页。
- `read_professional_contract` / `read_professional_workset` 在完整 JSON 超过 64 KiB 时进入 `json_utf8_chunks` 模式，单页 ≤ 24 KiB；续读必须
  沿用同一 project/revision/capability/scope/target_ids/page_bytes 并携带 `next_cursor`，拼接后校验 `content_sha256` 再解析。
- `read_request` 查询 proposal request 时只返回紧凑状态与 `workset_recovery`；原始工作集用对应 proposal 的 get 恢复，最新事实用
  `read_professional_workset` 读取。
- `read_workflow` 返回的 `workflow.recommended_next_actions` 是不阻塞主流程的可选建议（如规划地点、继续地点成套批次）；
  读到后先向用户提议，收到明确指令再执行。

## 断连与恢复

- 断连不表示 Core 没提交。纯读取可省略 `expected_revision` 取得 latest，响应始终给出本次 observation revision。
- 重连先用 `read_workflow` 的 `task_discovery` 发现 active/recent run 与 Generation（默认全部 active 加最近 5 条 recent，
  更早历史经 `next_cursor`），再按同一 revision 细查。
- 写请求不得换 revision 自动重试；丢响应只用原参数、原 revision、原 key 重放取得 Core 原回执。
- `manage_generation(action="wait")` 每次都动态观察，不缓存固定回执；Provider 事实未变化时不写回执、不递增 revision。
- 协议层取消只终止等待；业务取消需要显式调用对应 cancel 工具，不把进程退出当作回滚，也不因恢复观察重新提交生成。

## Playground scope

`--scope playground`（由启动器在 Playground 连接下追加）只发布 5 个工具，全部翻译成 `POST /api/playground/commands` 的
`{"name", "idempotency_key", "arguments"}` 信封，工具表见 [Playground](../../docs/playground.md#agent)。这些工具不接受 `project_id`，
没有读取媒体字节的工具；项目 scope 的工具表、bridge URL/payload 与错误信封不受影响。
