# 命令目录

所有类型化写入都以 `DirectorCommand {name, expected_revision, idempotency_key, arguments}` 进入 Core，经
`POST /api/projects/{id}/structured-director/commands`（人类）或 `.../application/commands`（外部 Agent）提交。
请求如何被授权、幂等与提交见 [控制流](control-flow.md)。

**调用方图例**：

| 标记 | 含义 |
| --- | --- |
| **R** | 只读，`project.read` 即可；不推进 revision |
| **A** | 在 Agent 操作白名单内：持 `project.execute` 委托或精确 grant 的 Agent 可调用，人类也可调用 |
| **P** | Agent 需 `project.propose`，且 Core 验证原 request 属于该 caller |
| **H** | 仅人类（`human.write`）；Agent 即使持 grant 也被拒绝 |

## 共同契约

- `arguments` 由命令专用 parser 严格解析：拒绝缺失字段、未声明字段、错误类型、无效枚举、重复或格式错误的 ID。
- `expected_revision` 是真正的 CAS 前置条件；`idempotency_key` 与规范化请求一一对应，同键不同请求被拒绝。
- 目标已处于请求状态时返回 `noop`，不推进 revision。
- 相互依赖的对象在一次 Store 事务内完成，只对最终对象图校验；失败不留半写状态。
- 失效只撤销已过期的当前选择、派生计划或 Approval，不删除历史。

## 读取

| 命令 | 调用方 | 结果 |
| --- | --- | --- |
| `project.get_projection` | R | 共源故事语义投影（outline / scene / shot / segment，显式 scope，分页） |
| `project.locate_story` | R | 把“场景 N”“场景 N－镜头 N”或“场景 N－片段 N”（片段在 Scene 内编号）解析为稳定 ID 与上下文 |
| `project.get_contract` | R | 某专业能力的完整 Skill 与参考正文及 SHA-256 |
| `project.get_workset` | R | 某专业能力在当前 revision 的事实工作集与输出 schema |
| `project.get_asset_manifest` | R | 实际媒体输入清单（Asset ID、MIME、长度、SHA-256） |
| `project.get_workflow_state` | R | 主流程投影（见 [外部 Agent 接入](external-agents.md#主流程读取)） |
| `project.get_handoff` | R | 人类入口、`allowed_actions` 与分页任务发现 |
| `project.get_request` | R | 按原 key 恢复本 caller 的应用回执 |
| `project.list_candidates` | R | 明确目标的当前可审核候选 |
| `project.get_dependencies` | R | 目标依赖摘要（仅供参考，不是提交校验） |
| `project.preview_impact` | R | 对一个完整严格命令做只读影响预览，与同 revision 真实执行一致 |
| `run.get_status` | R | DirectorRun 持久状态 |
| `{reference,script,location,keyframe}.get_proposal` | R | 原 proposal 请求的冻结工作集与当前观察 |

## 外部 proposal

四类专业规划共用 request → get → submit / reject / cancel 生命周期（见 [控制流 · 外部 proposal](control-flow.md#6-外部-proposal-生命周期)）。

| 命令 | 调用方 | 参数要点 |
| --- | --- | --- |
| `reference.request_proposal` | A | `raw_user_instruction`；仅当引用库尚未建立 |
| `script.request_proposal` | A | `raw_user_instruction`；要求引用已确认、尚无脚本 |
| `location.request_proposal` | A | `raw_user_instruction`；项目 scope，要求已有结构化脚本；增补地点库与 Scene/Shot 绑定，未列出的项不删除 |
| `keyframe.request_proposal` | A | `scene_ids`（上下文）+ 非空 `target_ids`（可写 Shot） |
| `*.submit_proposal` | P | `request_id`、`proposal`；草稿不含业务 ID，Core 分配 |
| `*.reject_proposal` | P | `request_id`、`reason` |
| `*.cancel_proposal` | P | `request_id` |

## 工作流确认

| 命令 | 调用方 | 效果 |
| --- | --- | --- |
| `reference.confirm_review` | H | 回执记录完整引用库 SHA-256；不生成脚本 |
| `script.confirm` | H | `narration_unlocked = true`，并尝试建立生产基线；已解锁时为 noop |
| `visual_production.unlock` | A | 生产基线就绪后解锁视觉生产（建立 Keyframe 与视频空卡，Keyframe 环境字段默认采用 Shot 的空间参考建议）；回执附 `location_advisory`，列出未绑定地点的 Scene 与未绑定视图的 Shot；解锁本身就是跳过地点规划 |

生产基线没有单独的确认命令：旁白层解锁后，每个改动脚本或旁白的命令都由 Core 在同一次写入里按真实音频校准并写入基线，
无法校准时基线保持失效，主流程返回 `reason = narration_timing_conflict` 的 `script.apply_operations`。

## 脚本

`script.apply_operations`（A）：在显式 `scope.scene_ids` 内按顺序原子执行 1–100 项操作。

| 操作 | 要点 |
| --- | --- |
| `update_scene_fields` | 只接受 `title`、`summary`、`setting` 的非空子集；保留 `driver`、Shot 与地点绑定；`setting` 变化按视觉上下文失效该 Scene 视频选择 |
| `insert_scene` | 必填 `title/summary/setting`；可选 `driver`（默认 drama）、新 `shots`、`move_shot_ids`（从已授权 Scene 迁入已有 Shot，保留其 Keyframe 绑定）、`narration_cue`；Narration Scene 必须带 Cue 且不能同时带 Shot，Drama Scene 不能带 Cue；新 Scene 在同一 patch 内视为已授权，ID 写入回执 |
| `move_scene` / `delete_scene` | 锚点必须在 scope 内；只能删除没有 Shot、旁白未选音频的 Scene |
| `update_shot_fields` / `insert_shot` / `move_shot` / `delete_shot` | `move_shot.target_scene_id` 可跨 Scene 迁移；Drama Scene 在 patch 结束时至少一个 Shot，拆合应在同一 patch 内完成迁移与删除 |
| `update_segment_fields` / `insert_segment` / `move_segment` / `delete_segment` | Segment 预计时长不短于 0.2 秒，不设上限 |
| `split_segment` | 调用方提供完整 `first`、`second` 内容并指定 `preserve_id`（first / second）；Core 不替用户补写正文 |
| `merge_adjacent_segments` | 只接受同一 Shot 中真实相邻的左右 Segment，提供完整 `merged` 并指定保留哪一侧 ID |

插入与移动用显式 `after_*_id`，`null` 表示移到容器首位；锚点必须存在于合法容器且不能自引用。新增 Shot/Segment 的 ID 由
Core 分配。操作完成后 Core 校验层级、非空 Shot、角色引用、旁白覆盖、Segment 边界与生产对象图，并重建 Keyframe/视频绑定。

`project.apply_repair_patch`（H）：缺少正式能力时的安全阀，不是通用写接口。只接受用户已授权、目标唯一、Scene scope 明确的
白名单字段（`set_fields`），每次真实修改写一条 `CapabilityGapAlert`（含反向 operation）。只涉及 Shot/Segment 字段时，Core 把它
规范化为 `script.apply_operations`，不记录缺口。不支持选择、Approval、Provider 提交、删除历史、任意路径或扩大 scope。

## 角色造型

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `reference.apply_look_operations` | A | 1–32 项操作：`add_look`（`character_id`、`name`、`appearance`、`usage`；只用于出镜角色，Core 分配造型 ID）、`update_look`（`look_id` + `name` / `appearance` / `usage` 的非空子集）；不删除造型、不失效已选设定图；内容未变为 noop |
| `reference.generate_look_sheet` | A | `look_id` + `identity_asset_ids`（0–4 张项目图片）；Core 编译设定图提示词并以 2:1 提交，只新增 `character_look_sheet` 候选；Agent 不能自带提示词 |
| 人类整卡保存 | H | `PUT characters/{id}` 携带 `looks`（只有 `id/name/appearance/usage`），新造型 `id` 为 null 由 Core 分配，其余 ID 必须是该卡已有造型，已有造型图沿用；删除造型只在这里完成，并剪除 Keyframe 对它的选择 |
| 设定图提示词 | H | `POST characters/{id}/looks/{look_id}/sheet-preview`（`identity_asset_ids`）只读返回 Core 编译的完整提示词；`sheet-generations` 可带 `prompt_text`（人类编辑过的完整提示词，原样提交），省略或 null 时由 Core 编译 |
| 造型图选择 | H | `POST characters/{id}/looks/{look_id}/select-sheet`（成功设定图候选）或 `/select-asset`（资产库已有图片）：写入 `selected_asset_id`；Keyframe 引用造型，不需要改写 |

## 旁白

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `narration.update_cue` | A | 修改 `zh` / `en` 子对象里的正文、`recipe_params`（按当前 speech recipe 声明校验、逐 recipe 合并）、seed，以及起止 Shot；只有实际变化才清除该语言音频选择与装配依赖 |
| `narration.generate` | A | `cue_id` + `language`（zh / en）；当前 `speech.synthesize` recipe 合成候选 |
| `narration.select_candidate` | H | 采用某语言候选 |
| `narration.clear_selection` | A | 解除某语言当前音频引用；Agent 只能在用户明确要求时调用，不授予采用其它候选的能力 |

## 地点

`location.apply_operations`（A）：在 `scope = {location_ids, scene_ids, shot_ids}` 内按顺序原子执行操作。scope 内 ID 必须存在；
地点级操作要求地点在 scope 内或由本 patch 新建，视图操作按所属地点判定，`bind_scene` / `bind_shot` 要求目标 Scene / Shot 在 scope 内。
同一 patch 新建的地点、陈设、状态、视图用局部 `key`（`[a-z][a-z0-9_-]{0,63}`，不能是 32 位 hex）互相引用，回执
`data.created_ids` 返回 key → 正式 ID。上限、角度范围、二选一朝向、无环等全部由地点模型校验；失效按
[数据模型 · 失效规则](data-model.md#失效规则)。

| 操作 | 要点 |
| --- | --- |
| `create_location` | `key`、`name`、`kind`（interior / exterior）、`description` |
| `update_location` | `fields` 是 `name`、`kind`、`description`、`master_prompt_text`、`master_reference_asset_ids`、`key_light`（`{description, azimuth_deg}` 或 null）的非空子集 |
| `delete_location` | Scene 仍绑定该地点时拒绝；其全部视图按 `delete_view` 规则处理，同时清空这些视图对 Shot 的软引用 |
| `upsert_fixture` / `delete_fixture` | `fixture` 为已有 ID（整体替换）或 key（新建）；`name`、`description`、`azimuth_deg` |
| `upsert_state` / `delete_state` | `state` 为已有 ID 或 key；`name`、`description` |
| `create_view` / `update_view` | `fields`：`name`、`purpose`、`azimuth_deg` 或 `look_at_fixture_id` + `yaw_offset_deg`、`pitch_deg`、`hfov_deg`、`state_id`、`refine_prompt_text`、`reference_view_ids`；create 必含 name、purpose 与一种朝向 |
| `delete_view` | 只被 Shot 软引用时允许删除，同一操作清空这些 Shot 的 `view_id`；被 Keyframe 或其它视图引用时拒绝并列出引用者 |
| `calibrate` | `fixture_azimuths`（陈设 ID → 方位）与 `key_light_azimuth_deg`；记录基于当前已选主图，不触发裁切 |
| `bind_scene` | `scene_id`、`location_id`、`state_id`（可空）；换地点时清空该 Scene 所有 Shot 的 `view_id` |
| `bind_shot` | `shot_id`、`view_id`（可空）；只记录给 Keyframe Planner 的空间参考建议，视图必须属于 Shot 所在 Scene 的地点，不改写已规划 Keyframe |
| `clear_master_selection` / `clear_view_selection` | 清除主图 / 视图的已选图，按失效规则级联 |

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `location.generate_master` | A | `location_id`；室内 2:1 全景、室外项目画幅；需先填写主图正文 |
| `location.generate_view` | A | `view_id`；要求主图已选、参考视图已选、朝向可解析。室内无有效裁切时只提交全景裁切，裁切完成后再次调用才提交细化；室外一步转向 |
| `location.generate_set` | A | `target_ids`（地点 ID）启动成套批次，或 `run_id`（`batch_id` 或任一 `execution_run_id`）继续；每轮只提交依赖已满足的项 |
| `location.select_master` | H | `location_id`、`asset_id`：只接受该地点成功、未隐藏的图片候选；室内还须是 2:1 PNG/JPEG、宽 1024–16384 |
| `location.select_view` | H | `view_id`、`asset_id`：只接受该视图成功、未隐藏的图片候选 |

人类 HTTP 另有：`POST locations/operations`、`POST locations/{id}/master/generate`、`POST locations/{id}/master/select`、
`POST locations/{id}/calibrate`、`POST location-views/{id}/generate`、`POST location-views/{id}/select`，都构造同一命令执行。

## Keyframe

`keyframe.apply_operations`（A）：1–100 项操作。Core 不相信调用方另报的 scope，而是从操作涉及的 Segment、Keyframe、Asset
反查完整受影响范围并校验授权。

| 操作 | 要点 |
| --- | --- |
| `set_activation` | 同时设置 Segment 首尾槽位是否启用 |
| `update_frame_fields` | 画面正文、可见角色、每个可见角色本帧使用的造型（`character_references`，`look_id` 或 null）、地点视图 `environment_view_id` 与 `environment_mode`（`edit/reference/none`）；`none` 的 `environment_none_reason` 可选（null 或最多 500 字，空白归一为 null） |
| `set_aux_references` | 替换 Segment 手工辅助图集合（≤4） |
| `bind_slot` | 把已有 Keyframe 绑定到某首帧或尾帧槽位 |
| `share_boundary` | 让真实相邻 Segment 的左尾与右首共享一个 Keyframe；可给 `source_keyframe_id` 复用现有对象及其血缘，否则 Core 从边界事实中挑选可复用对象，没有时才新建 |
| `split_boundary` | 拆开共享边界，明确克隆哪一侧以及是否复制当前选择 |
| `clear_selection` | 撤销当前候选选择 |

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `keyframe.generate` | A | 单个 `keyframe_id`；只提交该帧 |
| `keyframe.generate_batch` | A | 显式 Scene/Shot/Segment 范围；本轮只提交依赖已满足的帧 |
| `keyframe.continue_batch` | A | `batch_id` 或任一关联 `run_id`；不能带新范围 |
| `keyframe.select_candidate` | H | 采用候选 |

人类 HTTP 另有：保存首帧卡共享开关（`PUT segments/{id}/keyframe-boundary`）与“从上一 seg 抽取”（`POST keyframes/{id}/extract-frame`，
必须给 `frame_index`）。

## 视频

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `video.set_prompt` | A | 保存单 Segment 视频正文（≤ 20,000） |
| `video.update_recipe_inputs` | A | 原子保存 `prompt_text`、当前 recipe 的 `bindings`（槽位 → 有序 `{asset_id, description}`）与机制 `params`，整体替换当前 recipe 的输入簿；按 manifest 校验槽位、数量、媒体类型、时长、说明与唯一性，只接受本项目 Asset；人类与 Agent 同一路径 |
| `video.set_recipe` | A | 保存 `recipe_id`；Core 校验目标可用性及输入兼容性，保留各 recipe 的 book |
| `video.generate` | A | `segment_id`；纯程序动作，原样提交已保存正文 |
| `video.select_candidate` | H | 采用候选 |
| `video.clear_selection` | H | 撤销当前视频选择 |
| `video.upscale` | A | 对已选原视频提交 SeedVR2 超分 |

人类 HTTP 另有：把资产库 MP4 挂接为 Segment 候选（`attach`），重复挂接同一 Asset 为 noop，重新挂接已隐藏候选只恢复可见性。

## Generation 生命周期

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `generation.wait` | A | 动态观察明确的 Generation ID 集合，无变化时不写回执、不推进 revision；不校验、可省略 `expected_revision` |
| `generation.cancel` | A | 先持久化取消意图，再请求 Provider |
| `generation.retry` | A | 仅 `failed` / `cancelled` / `submission_uncertain`；当前业务输入必须与原规范化签名完全一致，新建带 `retry_of` 的 Generation |
| `generation.dismiss` | A | 隐藏候选卡片；被当前业务对象采用的媒体不能隐藏 |

## Scene 输出与最终成片

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `animatic.generate_scene` | A | 已审核旁白 + 已选 Keyframe 的动态分镜 |
| `final.assemble_scene` | A | 当前已选视频 + 所选语言旁白，渲染对应语言的 Scene 成片 |
| `final.assemble` | A | 拼接全部 Scene 成片（所选语言版本）；任一缺失或过期则拒绝并列出 |
| `final.select_candidate` | H | 按 Generation 采用某语言最终成片 |
| `final.clear_selection` | H | 撤销当前最终成片选择 |
| `final.approve` | H | 以精确 Asset 一次批准所选语言版本；要求本轮明确批准，且 Asset、Generation、装配与 revision 完全对应 |
| `final.reopen_production` | H | 清除当前装配与 Approval，回到视频审核位置；历史与内容层保留 |

候选选择、普通正面反馈与最终批准是三种不同权限。

## 领域 run

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `run.cancel` | A | 停止该 run 的后续步骤并释放 active run；不取消已提交的 Provider 任务 |
| `run.resume` | H | 让 `waiting_user` 的 run 回到 `running` |

## 人类专用 HTTP 资源

除命令外，人类界面还通过资源路由完成：项目创建/列表/删除、引用卡、造型图与音色、脚本表单保存、Asset 导入/删除/内容读取、
资产中心处理（`audio-trim`、`audio-effect`、`transcription`、`audio-remix`、`video-frame`、`audio-generations`）、
跨域资产复制、`generations/refresh` 观察、全局设置。它们与命令共享同一 Service、Store、CAS 与 Generation 规则，
不是第二套 authority。路由与实现的对应由 `tests/test_http_api_route_matrix.py` 守卫。
