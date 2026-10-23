# 控制流

本文描述请求如何穿过系统：身份与授权、命令分发、幂等与 CAS、原子提交、Generation 生命周期、外部 proposal、
Keyframe 批次和重启恢复。数据结构见 [数据模型](data-model.md)，命令清单见 [命令目录](commands.md)。

## 1. 请求入口与身份

```mermaid
flowchart TB
    req[HTTP 请求] --> parse[server/http.py<br/>严格解析 · 拒绝 % 编码与 // 路径]
    parse --> mode{启动模式}
    mode -- 未配置策略 --> anon[匿名开发模式<br/>不得交给外部 Agent]
    mode -- 本机一键接入 / 自定义策略 --> auth[认证]
    auth -->|浏览器 cookie| human[human caller]
    auth -->|Bearer token 摘要比对| agentc[agent caller]
    human & agentc --> authorize[AccessPolicy.authorize<br/>路由 × 角色 × 能力 × 项目]
    authorize -->|拒绝| deny[401 unauthenticated / 403 scope_denied<br/>capability_denied / grant_required / external_mutation_disabled]
    authorize -->|通过| route[server/api.py 路由]
    route --> projects["/api/projects"]
    route --> sd["/api/projects/:id/structured-director/..."]
    route --> pg["/api/playground..."]
    route --> settings["/api/settings/..."]
```

- caller 由服务端签发：`id`、`role`（human / agent）、`project_ids`、`capabilities`、`expires_at`、精确 `grants`。
  请求正文永远不是身份来源，模型自报的角色、scope 或“用户已批准”都不授予任何能力。
- 能力：`project.read`、`project.mutate`、`project.propose`、`project.execute`、`playground.use`、
  `human.write`、`workspace.manage`、`diagnostics.read`。
- 授权规则摘要（`core/application/caller.py`）：

| 路由 | 允许 |
| --- | --- |
| `/api/settings/providers`、`/api/settings/providers/*` | human + `workspace.manage`，GET/PUT |
| `/api/projects`（列表、创建） | human + `workspace.manage` |
| 项目内 GET | human + `project.read`；agent 只能 GET Asset 内容 |
| 项目内 `POST .../commands`、`.../application/commands` | 读命令：`project.read`；agent 写命令：见第 3 节 |
| 项目内其它写路由 | human + `human.write`；agent 一律 `external_mutation_disabled` |
| `/api/playground*` | human + `human.write`；agent 只有 `playground.use` 且只能 `POST /api/playground/commands` 白名单命令 |

## 2. 命令信封与分发

所有类型化写入都以 `DirectorCommand` 进入 Core：

```json
{"name": "script.apply_operations", "expected_revision": 42, "idempotency_key": "…", "arguments": {}}
```

```mermaid
flowchart TB
    cmd[DirectorCommand] --> svc[Service.execute_director_command]
    svc --> isread{project.* 读命令<br/>run.get_status<br/>*.get_proposal?}
    isread -- 是 --> internal
    isread -- 否，且有 caller --> appcmd[execute_application_command<br/>外部/受保护入口]
    isread -- 否，无 caller<br/>（内部手工按钮路径） --> internal[_execute_internal_director_command]
    appcmd --> authz[authorize_command<br/>白名单 · execute 委托 · 精确 grant]
    authz --> kind{命令类别}
    kind -- generation.wait --> wait[动态观察分支<br/>不写回执]
    kind -- 同步领域写 --> atomic[execute_atomic_request]
    kind -- 生成 / 批次 / 装配 --> genreq[带持久回执的生成分支]
    internal --> k2{命令类别}
    k2 -- keyframe.*_batch --> batch[external_batches]
    k2 -- generation.* --> genobs[execute_generation_command]
    k2 -- animatic / final.assemble* --> media[execute_media_command]
    k2 -- 其余 --> registry[DirectorCommandRegistry<br/>按命令名查表：parser + Store 方法]
    atomic --> registry
    genreq --> service_methods[Service 生成用例<br/>media_submission]
```

Registry 用单一模块级命令表声明每个命令的 parser、Store handler 与 scope 规则；proposal、workflow 与领域命令都走同一
查表入口。parser 拒绝缺失字段、未声明字段、错误类型、无效枚举、重复或格式错误的 ID；Store 继续校验存在性、实体类型、
scope、邻接、业务状态与完整对象图。

**Web 手工按钮与 Agent 命令最终进入同一个类型化 handler**；UI 没有任何直接赋值状态的路径。

## 3. Agent 写入的授权判定

```mermaid
flowchart TB
    a[agent 写命令] --> r1{读命令且有 project.read?}
    r1 -- 是 --> ok([放行])
    r1 -- 否 --> r2{mutations_enabled 且有 project.mutate?}
    r2 -- 否 --> e1[external_mutation_disabled]
    r2 -- 是 --> r3{proposal submit/reject/cancel<br/>且有 project.propose?}
    r3 -- 是 --> ok2([放行；Core 再验证原 request 属于该 caller])
    r3 -- 否 --> r4{命令在 Agent 操作白名单?}
    r4 -- 否 --> e2[capability_denied]
    r4 -- 是 --> r5{有 project.execute 委托?}
    r5 -- 是 --> ok3([放行])
    r5 -- 否 --> r6{存在未过期 grant<br/>摘要 = sha256 name+arguments+expected_revision?}
    r6 -- 是 --> ok4([放行])
    r6 -- 否 --> e3[grant_required]
```

- Agent 操作白名单只包含编辑计划、单目标生成、批次、装配、Generation 观察/取消/重试/隐藏、proposal 请求、run 取消与
  旁白解绑与 Keyframe 候选采用；**不包含**其它候选采用、审核确认、Approval、重新开放、repair 或旧写路由。
- 本机一键接入为当前项目签发 12 小时的 `project.execute` 委托，覆盖整个白名单；没有委托的部署必须为每条命令签发精确 grant。
- 每次重放也重新授权；撤权后旧幂等键无法恢复权限。

## 4. 同步写命令：原子回执

```mermaid
sequenceDiagram
    participant A as Agent
    participant S as Service（_lock）
    participant R as Registry
    participant St as Store
    A->>S: command(name, expected_revision, idempotency_key, arguments)
    S->>St: read()
    S->>S: request_id = sha256(caller, project, key)<br/>digest = sha256(规范化命令 + caller 能力/grant)
    alt 同 request_id 已存在
        S->>S: digest 不同 → 拒绝（幂等键已用于不同请求）
        S-->>A: digest 相同 → 返回原回执，replay = true
    else 新请求
        S->>S: revision ≠ expected → revision_conflict（expected/current）
        S->>S: require_workflow_action（主流程门禁）
        S->>R: execute(command)，Store 写入被“捕获”而非落盘
        R->>St: 领域变换 → 捕获最终 document
        S->>St: 一次 _atomic_write：业务变化 + ApplicationRequest(committed, 回执)
        S-->>A: receipt + 紧凑 data + workflow
    end
```

- 业务变化与回执在**同一次**原子替换中落盘：要么都在，要么都不在。
- 同步命令只允许一次 Store 提交；嵌套应用事务被拒绝。
- 目标已处于请求状态时返回 `noop`，不推进业务内容。
- Agent 专用 `/application/commands` 的写响应只返回 workflow、完整回执、ApplicationRequest/replay 与紧凑目标 data，
  不附带全项目快照；人类 `/commands` 可在需要时附带 Web 快照。两者共用同一执行与回执。

### 回执（`CommandReceipt`）

`command_id`、`status`（succeeded / noop）、`old_revision`、`new_revision`、`changed_ids`、`invalidated`、`preserved`、
`decision_summary`、`applied_summary`、`assumptions`、`warnings`。最新主流程建议在响应顶层 `workflow`，而不是回执里。

### 脚本原子操作与覆盖校验

`script.apply_operations` 在一个显式 `scope.scene_ids` 内按顺序原子执行 1–100 项操作：`update_scene_fields`、
`insert_scene`、`move_scene`、`delete_scene`、`update_shot_fields`、`insert_shot`、`delete_shot`、
`update_segment_fields`、`insert_segment`、`move_segment`、`delete_segment`、`split_segment`、
`merge_adjacent_segments`。不支持单独移动 Shot；需要重排或跨 Scene 迁移 Shot 时走脚本 proposal 的 `replace_scene`
整卡替换，或在同一 patch 内删除并重新插入、同时补足覆盖。

- Segment 以 `scene_id` 为容器；已有 Scene 的 Segment 用 `shot_ids` 表达覆盖，新 Scene 的 Segment 用本 Scene
  新 `shots` 数组的 `shot_indexes`。
- `insert_shot` 必须且只能给出 `attach_to_segment_id`（并入已有 Segment 的覆盖）或 `new_segment`（新建一个只覆盖
  新 Shot 的 Segment）之一。
- `split_segment` 的 `first` / `second` 各自给出完整 `shot_ids`；在某个 Shot 内部拆分时两段共享该 Shot，第二段必须带
  `boundary_from_previous`。`merge_adjacent_segments` 只接受同一 Scene 中真实相邻的左右 Segment，合并后的 `shot_ids`
  必须是两段覆盖的并集。

整批操作先应用在内存草稿上，结束后构造完整 `DirectorScript` 做一次覆盖校验：每个 Segment 连续覆盖、按顺序拼接后
恰好覆盖全部 Shot，不跳过、不倒序、不重复，只允许相邻 Segment 共享边界 Shot；失败则整批拒绝并指出 Scene 与原因。
成功时同一次写入重建 Keyframe/视频绑定与生产基线。

## 5. 生成命令与 Generation 生命周期

### 提交

```mermaid
sequenceDiagram
    participant A as Agent / Web
    participant S as Service（_application_lock）
    participant St as Store
    participant P as Provider 插件
    participant X as 外部媒体服务
    A->>S: video.generate(segment_id)
    S->>St: 已有同 request_id?
    alt 已有且 phase = pending
        S->>St: 标记 uncertain（中断过），返回恢复信息，绝不再次提交
    end
    S->>S: CAS + 主流程门禁 + 输入校验
    S->>St: 写入 Generation(phase=submitting) + ApplicationRequest(pending, generation_ids)
    S->>P: submit(类型化请求 + 输入字节)
    alt Provider 接受
        P->>X: HTTP
        X-->>P: external_id
        S->>St: Generation → queued，记录 plugin_id / external_id<br/>ApplicationRequest → committed
    else 明确拒绝
        S->>St: Generation → failed(error_code)
    else 传输失败 / 响应无效
        S->>St: Generation → submission_uncertain；回执 uncertain
    end
    S-->>A: 回执（含全部 generation_ids）
```

关键规则：

- **先持久化、后调用**：Generation 以 `submitting` 落盘后才触网。进程若在提交窗口崩溃，重启时 Store 把所有
  `submitting` 迁移为 `submission_uncertain`，同时把 `pending` 回执标为 `uncertain`。
- **未知提交绝不自动重试**：`submission_uncertain` 只能由人或 Agent 先核查，再显式 `generation.retry`（由新 Generation 接替）
  或 `generation.dismiss`（放弃）。处理之前它占用目标、计入 `active_generation_count` 与 `task_discovery.active`，并阻止删除其输入；
  隐藏或已有 retry child 后即视为已处理，不再阻塞。判定集中在 `models/generation.py::unresolved_uncertain_ids`。
- 同一应用请求产生的多个 Generation（如批次一轮）全部记入同一回执；用原 key 重试只回放。
- Provider 网络调用不持有项目业务写锁。
- **Core 确定性工具**（抽帧 `VIDEO_FRAME`、全景取景 `PANO_VIEW`）走同一套 submit/observe/cancel/read_artifact 生命周期，
  `provider_snapshot` 为 null。全景取景先创建普通地点图片，以新图片为 target 并记录 `panorama_capture_request`；成功回调导入
  不可变 Asset 并直接设为该子图的选择。父全景图与角度只作为冻结 provenance，不形成活依赖。

### 观察与产物回收

```mermaid
flowchart TB
    trigger[触发：Web 轮询 POST .../generations/refresh<br/>或 Agent generation.wait] --> snap[固定本轮全部非终态 Generation ID]
    snap --> loop{逐个}
    loop --> c{cancellation_requested?}
    c -- 是 --> cancel[Provider.cancel] --> apply
    c -- 否 --> observe[Provider.observe（按 Generation 自己的 plugin_id 路由）] --> apply
    apply{结果}
    apply -- 同阶段进度 --> mem[只写内存观察缓存<br/>不推进 revision]
    apply -- 阶段变化 --> persist[transition_generation → 原子写入]
    apply -- succeeded --> import[下载产物 · 校验类型/大小/SHA-256/时长<br/>导入为不可变 Asset · 写 output_asset_id]
    import -- 校验失败 --> keep[artifact_import_failed：保留句柄<br/>等待同一 Generation，不新建任务]
    apply -- 单个 Provider 观察失败 --> skip[保留该 Generation 既有事实，继续批次]
    persist & import & mem & skip --> loop
    loop -- 完成 --> resp[返回一个最新快照]
```

- 本轮观察期间新产生的依赖任务留到下一轮，避免单轮无界扩展。
- **观察从不扩大生成授权**：单目标完成后只导入该目标产物，不触发任何其它目标；批次的下一波必须显式 continue。
- `generation.wait` 是动态观察：对明确的 Generation ID 集合最多等待约 18 秒（默认，每 2 秒一轮），
  在 MCP bridge 20 秒超时前返回 `wait_again`。Provider 事实无变化时不写 ApplicationRequest、不递增 revision；
  因此断连后可以安全再次 wait，但上一次响应不代表当前状态。wait 不校验 `expected_revision`，可以省略：Generation 回调本身
  会推进 revision，观察动作不应因此冲突。

### 取消、重试、隐藏

| 动作 | 前置 | 行为 |
| --- | --- | --- |
| `generation.cancel` | 非终态 | 先持久化 `cancellation_requested = true`，再调用 Provider；HTTP 失败时意图仍保留，后续观察沿原句柄继续确认取消 |
| `generation.retry` | `failed` / `cancelled` / `submission_uncertain` | Core 从**当前项目事实**重建 target、prompt、mode、seed、输入与参数，与原规范化签名逐项比较；任何业务输入变化都拒绝（新的相似生成不能伪装成重试）；通过则创建带 `retry_of` 的新 Generation；已有 retry child 时返回 noop |
| `generation.dismiss` | 未被当前业务对象采用 | 只隐藏候选卡片，不删除 Generation 或 Asset |

## 6. 外部 proposal 生命周期

引用库、脚本、地点、Keyframe 四类专业规划共用同一生命周期（`proposal_requests.py`），持久任务复用对应
kind 的 `DirectorRun`（`reference_proposal`、`script_proposal`、`location_plan`、`keyframe_plan`）。

```mermaid
stateDiagram-v2
    [*] --> awaiting_agent_submission: *.request_proposal<br/>冻结工作集（source_revision · scope · targets · 原始指令）
    awaiting_agent_submission --> awaiting_agent_submission: *.get_proposal（重读同一工作集）
    awaiting_agent_submission --> completed: *.submit_proposal<br/>source revision 未变 · 同一 run · 原 grant 有效
    awaiting_agent_submission --> cancelled: *.cancel_proposal
    awaiting_agent_submission --> rejected: *.reject_proposal(reason)
    awaiting_agent_submission --> workset_stale: 项目 revision 已越过 source_revision
    workset_stale --> cancelled: *.cancel_proposal（之后重新 request）
    awaiting_agent_submission --> failed
    completed --> [*]
    cancelled --> [*]
    rejected --> [*]
    failed --> [*]
```

- `awaiting_agent_submission` 表示**当前外部 Agent** 应基于冻结工作集撰写并显式 submit；Core 后台没有任何模型在跑。
- request 回执保存原始用户指令、scope、目标与完整 Core 工作集（`raw_user_instruction` 与 `core_facts` 分开）；
  get 与重放恢复同一输入，不会根据当前环境偷换工作集。
- submit/reject/cancel 需要 `project.propose`，并验证原 request 属于当前 caller、原 grant 未撤销；Agent 不能借
  request_id 接管其它 caller 的任务。拒绝与取消在 run 上都是 `cancelled` 终态，投影按回执 outcome 区分 `rejected` 与 `cancelled`。
- 迟到的 submit（已取消/拒绝/完成/过期）被拒绝。
- 已有引用库不能被首次请求覆盖；脚本 request 只用于无脚本的冷启动。
- 地点 request 是项目级 scope，要求已有结构化脚本（否则 409）；规划期间 `location_plan` run 锁住其它业务写入。submit 把 proposal
  编译为与 `location.apply_operations` 相同的操作（新建地点、陈设、状态与图片用局部 `key` 互引），在同一次提交里落库并结束 run；
  图片说明为空、来源不属于同一地点或 Scene/状态归属不合法时整体拒绝为 `invalid_proposal`。
- Keyframe 请求可读目标 Segment 所属完整 Scene 作上下文，但 proposal 只能覆盖原请求的 `target_ids`（Segment；给 Scene
  表示其全部 Segment）；触及跨范围共享边界时拒绝，并给出最小扩展范围让用户重新授权。
- 地点仍被 Scene 绑定时拒绝删除并列出引用者；地点图片没有 Shot/Keyframe 硬引用，删除条目只保留历史 Asset、Generation 与
  已生成的全景子图。地点修改不产生 Keyframe、视频或装配失效。
- 观察投影 `proposal_observation` 同时给出 `source_revision` 与本次 `observation_revision`，以及同一 request_id 的精确工具动作。

## 7. Keyframe 批次

```mermaid
sequenceDiagram
    actor U as 用户
    participant A as Agent
    participant C as Core
    participant P as 图片 Provider
    U->>A: “生成这个 Scene 的关键帧”
    A->>C: keyframe.generate_batch(targets)
    C->>C: 展开为已启用 Keyframe ID（去重共享槽位）<br/>空范围或任一无效目标 → 整批拒绝
    C->>C: 新建 DirectorRun(kind=director)<br/>authorization.generation_scopes = keyframe:<id>…<br/>cursor.pending_target_ids = 未提交目标
    loop 本轮依赖已满足的帧
        C->>P: 提交（逐个持久化 Generation）
    end
    C-->>A: batch_id + execution_run_id + 本轮提交 / 等待前置帧、参考关键帧选图或角色造型图的帧
    Note over C: 本轮提交结束 → 执行 run completed<br/>（≠ 批次完成）
    A->>C: generation.wait / read_run …
    U->>A: “继续生成关键帧”
    A->>C: keyframe.continue_batch(batch_id 或任一关联 run_id)
    C->>C: 沿最新一轮继续：新 execution_run_id，记录 root / previous run<br/>重新检查依赖，只提交新满足的帧
```

- 每个 start 建立独立稳定 `batch_id`；每轮使用新的 `execution_run_id`，在原回执中保存 root/previous 关联与原目标。
  continue 不能携带新范围，也不能凭目标相同合并两个独立批次。
- 依赖包括前置帧已有成功候选、参考关键帧与参考地点图片已有选中图（`dependency_kind = reference_keyframe` / `reference_location_image`），以及每个显式选择的角色造型已有造型图。未满足的帧留作等待项并写明原因；满足后同样需要
  显式 continue。地点图片不是 Keyframe 绑定或批次依赖；只有人类已加入 Segment 辅助参考的 Asset 才作为普通显式输入。
- 批次跳过已有成功候选或已选 Asset 的帧；要为这类帧追加候选，使用单帧 `keyframe.generate`。
- 空提示词的帧被拒绝；不存在内置 Planner 兜底补写。
- `batch_observation` 从原范围、各轮回执与当前 Generation 动态派生逐目标状态，区分：等待 Generation、等待显式 continue、
  依赖阻塞（例如 `dependency_kind = predecessor_keyframe`，`dependency_target_id` 为前置 Keyframe ID）、失败/取消/
  提交不确定、全部成功。读取从不提交下一波或自动重试。
- 中断时先读 request 与 run；原 run 未结束时必须先显式取消它，再以原 batch 身份继续，不扩大范围、不重复已有提交。

### 地点成套批次

`location.generate_set` 复用同一批次骨架（单活跃 run、`begin_production_instruction` 建立 `director` run、回执关联、`batch_observation`），
一个命令两种参数：`{target_ids: [image_id…]}` 启动，`{run_id}`（`batch_id` 或任一 `execution_run_id`）继续；MCP 都经
`media_batch`（`kind=location`）。范围持久化为 `location-image:<id>`，开始时校验图片存在且不重复。

```mermaid
flowchart TB
    start[start / continue] --> items[location_set_items：逐个独立图片分类]
    items --> ready{ready?}
    ready -- 是 --> g[按图片 kind 和显式参考图提交 generate / edit]
    ready -- 否 --> why[in_progress · awaiting_selection · selected ·<br/>failed · target_missing …]
    g & why --> done[本轮结束，执行 run completed<br/>继续须再次显式 generate_set(run_id)]
```

- 分类函数 `location_requests.location_set_items` 同时服务提交与观察；判定顺序与 Keyframe 批次一致：进行中 → 提交不确定 →
  已有成功候选（等待选择）→ 失败/取消不自动重试 → 前置校验。
- 批次只调用单项入口的锁内提交函数，seed、`provider_snapshot` 与重试签名逻辑与单项生成相同；全景取景不进入成套批次。
- 每轮结束自己的 run，不进入 `waiting_user`：等待的正是人类选择图片，活跃 run 会挡住选择。等待由观察 phase
  （`awaiting_selection`、`blocked_on_dependency`、`awaiting_explicit_continue`）表达；批次观察带 `batch_kind = location`，与 Keyframe 批次不混淆。
- 图片或所属地点被删除时该项报告 `target_missing`，范围不扩大。

## 8. DirectorRun 状态

```mermaid
stateDiagram-v2
    [*] --> running
    running --> waiting_user: 需要用户决定
    running --> waiting_jobs: 等待明确的 Generation ID 集合
    waiting_user --> running: run.resume
    waiting_jobs --> running: 集合内全部进入终态
    running --> completed
    running --> failed: 动作翻译/目标校验在提交前失败
    running --> cancelled: run.cancel
    waiting_user --> cancelled
    waiting_jobs --> cancelled
```

- 同一项目最多一个非终态 run；它与业务审核状态正交。
- `waiting_jobs` 只等待当前步骤明确给出的 Generation ID；建立后出现的无关任务不加入；
  `succeeded` / `failed` / `cancelled` / `submission_uncertain` 都算终态。
- 命令完成与 cursor/回执更新原子持久化；重启后跳过 `completed_command_ids`，已提交的 Provider 任务不会重发。
- `run.cancel` 只停止后续步骤并释放 active run；已提交的 Provider 任务、候选与 Asset 保留，不会被隐式取消。

## 9. 读取路径

| 读取 | 用途 | 特性 |
| --- | --- | --- |
| Web 快照（GET structured-director） | 人类导演台 | 完整快照 + `allowed_actions` + Asset 使用状态 + 内存进度 |
| `project.get_projection` / `read_story` | 故事语义投影 | 显式 scope；outline/scene/shot/segment 分层；默认长文本截至 240 字符（`text_mode=preview`），`extensions=["text"]` 取完整正文；`limit` 默认 30、最大 100 |
| `project.locate_story` | 把“场景 N－镜头 N”或“场景 N－片段 N”解析为稳定 ID | 只读 |
| `project.get_contract` / `get_workset` | 专业 Skill 与工作集 | 超过 64 KiB 自动切成 ≤ 24 KiB UTF-8 chunk；cursor 绑定 project/revision/capability/scope/targets/page size/内容 SHA-256，拼接后校验摘要 |
| `project.get_workflow_state` / `get_handoff` | 主流程与人类交接 | 见 [外部 Agent 接入](external-agents.md#主流程读取) |
| `project.get_request` / `run.get_status` | 恢复 | 只返回紧凑状态与恢复入口，不重复展开大型工作集 |
| `project.list_candidates` / `get_dependencies` / `preview_impact` | 候选、依赖、影响预览 | `preview_impact` 复用正式 parser 与影响计算，与同 revision 真实执行结果一致 |
| `project.get_asset_manifest` + Asset content | 实际媒体字节 | 仅 PNG/JPEG/WebP/WAV/MP3，单项 ≤ 8 MiB，核对 MIME/长度/SHA-256 |

- 只读命令可省略 `expected_revision` 读取最新快照；显式给出时精确读取，不匹配返回 expected/current。
- 通用读取受 128 KiB / 500 对象信封约束，超限明确报错要求缩页，不静默截断。
- 所有 cursor 绑定 revision 与完整查询；revision 或查询变化后必须从第一页重读。cursor 不是授权 token。

## 10. 启动与恢复

```mermaid
flowchart TB
    start[python -m server] --> lease[获取 .stories 单写租约]
    lease --> assemble[装配 Provider 插件与全局设置]
    assemble --> serve[开始服务]
    serve --> open[首次访问某项目 → 创建 Service]
    open --> recover[Store.recover_interrupted_submissions<br/>submitting → submission_uncertain]
    recover --> ready[项目就绪]
    ready --> agentreconnect[Agent 重连：read_workflow / handoff.task_discovery<br/>→ read_request / read_run 细查]
```

恢复原则：

1. 业务事实只从 `project.json` 恢复；外部 Agent 会话丢失不等于业务任务丢失。
2. 先读原 request / run / Generation，再决定下一步；丢响应只用**原参数、原 revision、原幂等键**重放取得 Core 原回执。
3. 写请求不得换 revision 自动重试；未知提交不得盲目重提。
4. 协议层取消（MCP 请求取消、进程退出）只终止等待，不是业务取消；业务取消必须显式调用对应命令。
