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
| `project.get_details` | R | 专业工作集索引之外的完整详情：`keyframe` / `location` / `location_image` / `character` 按 1–20 个 ID 读取，`director_plan` 读取原始导演方案全文 |
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
| `keyframe.request_proposal` | A | `scene_ids`（上下文）+ 非空 `target_ids`（可写 Segment；也可给 Scene 表示其全部 Segment） |
| `*.submit_proposal` | P | `request_id`、`proposal`；草稿不含业务 ID，Core 分配 |
| `*.reject_proposal` | P | `request_id`、`reason` |
| `*.cancel_proposal` | P | `request_id` |

## 工作流确认

| 命令 | 调用方 | 效果 |
| --- | --- | --- |
| `reference.confirm_review` | H | 回执记录完整引用库 SHA-256；不生成脚本 |
| `script.confirm` | H | `narration_unlocked = true`，并尝试建立生产基线；已解锁时为 noop |
| `visual_production.unlock` | A | 生产基线就绪后解锁视觉生产（建立 Keyframe 与视频空卡，首帧默认取 Segment 首个覆盖 Shot 的视图、尾帧取末个覆盖 Shot 的视图）；回执附 `location_advisory`，列出未绑定地点的 Scene 与未绑定视图的 Shot；解锁本身就是跳过地点规划 |

生产基线没有单独的确认命令：旁白层解锁后，每个改动脚本或旁白的命令都由 Core 在同一次写入里按真实音频校准并写入基线，
无法校准时基线保持失效，主流程返回 `reason = narration_timing_conflict` 的 `script.apply_operations`。

## 脚本

`script.apply_operations`（A）：在显式 `scope.scene_ids` 内按顺序原子执行 1–100 项操作。

| 操作 | 要点 |
| --- | --- |
| `update_scene_fields` | 只接受 `title`、`summary`、`setting` 的非空子集；保留 `driver`、Shot、Segment 与地点绑定；`setting` 变化按视觉上下文失效该 Scene 视频选择 |
| `insert_scene` | 必填 `title/summary/setting`；可选 `driver`（默认 drama）、本 Scene 的新 `shots` 与 `segments`（Segment 用 `shot_indexes` 覆盖新 Shot）、`narration_cue`；Narration Scene 必须带 Cue 且不能同时带 Shot/Segment，Drama Scene 不能带 Cue；新 Scene 在同一 patch 内视为已授权，ID 写入回执 |
| `move_scene` / `delete_scene` | 锚点必须在 scope 内且不能自引用；Scene 旁白已选音频时拒绝删除，需先解除音频选择 |
| `update_shot_fields` | 只改创作字段（可见角色、构图、运镜、动作、声音、转场意图）；视图建议走地点操作 |
| `insert_shot` | 只插入 Shot；必须且只能给出 `attach_to_segment_id`（并入已有 Segment 的覆盖）或 `new_segment`（新建只覆盖它的 Segment）之一，插入位置必须与所并入/新建的覆盖区间相容 |
| `delete_shot` | 同一 patch 内从覆盖它的全部 Segment 移除；任一 Segment 因此失去全部 Shot 时整批拒绝 |
| `update_segment_fields` | 可改 `shot_ids`、时长、`action`、对白与 `boundary_from_previous`；时长不短于 0.2 秒，不设上限；对白数组改写时，显式 ID 优先，未带 ID 但内容完全未变的对白沿用原 ID 与已选 TTS，只有新增或改写的对白失效 |
| `insert_segment` / `move_segment` / `delete_segment` | 以 `scene_id` 为容器；覆盖用 `shot_ids`，移动用 `after_segment_id` |
| `split_segment` | 提供完整 `first`、`second` 并指定 `preserve_id`（first / second）；两段各自给 `shot_ids`，在某个 Shot 内部拆分时两段共享该 Shot，第二段必须带 `boundary_from_previous`；其 `reason` 只允许 `model_constraint`、`continuity_anchor`、`control_boundary`、`failure_cost`；内容完全未变的对白跨两段保留原 ID 与已选 TTS |
| `merge_adjacent_segments` | 只接受同一 Scene 中真实相邻的左右 Segment，提供完整 `merged` 并指定保留哪一侧 ID；合并后的 `shot_ids` 必须是两段覆盖的并集；内容完全未变的对白保留原 ID 与已选 TTS |

插入与移动用显式 `after_*_id`，`null` 表示移到容器首位；锚点必须存在于合法容器且不能自引用。新增 Shot/Segment 的 ID 由
Core 分配。不支持单独移动 Shot：重排或跨 Scene 迁移 Shot 时，用脚本 proposal 的 `replace_scene` 整卡替换，或在同一 patch 内
删除并重新插入、同时补足覆盖。整批操作结束后 Core 做一次完整覆盖校验，并校验角色引用、旁白互斥与生产对象图，失败整批拒绝；成功时同一次写入重建 Keyframe/视频绑定与生产基线。

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
| `narration.update_cue` | A | 修改 `zh` / `en` 子对象里的正文、`recipe_params`（按当前 speech recipe 声明校验、逐 recipe 合并）与 seed；Cue 覆盖整个 Scene，没有起止 Shot 字段。只有实际变化才清除该语言音频选择与装配依赖 |
| `narration.generate` | A | `cue_id` + `language`（zh / en）；当前 `speech.synthesize` recipe 合成候选 |
| `narration.select_candidate` | H | 采用某语言候选 |
| `narration.clear_selection` | A | 解除某语言当前音频引用；Agent 只能在用户明确要求时调用，不授予采用其它候选的能力 |

## 对白 TTS

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| 对白表演参数保存 | H | 按 `dialogue_line_id` 保存当前 `speech.synthesize` recipe 的机制参数；参数变化会清除该句已选音频、整段时序与下游视频选择 |
| `dialogue.generate` | A | 为单条 `dialogue_line_id` 提交 WAV 候选；角色有参考音色时强制 `speech.synthesize` 克隆，否则强制 `voice.design` |
| `dialogue.generate_batch` | H | Web 批量按钮只为当前未选且没有在途任务的 DialogueLine 逐条提交；不选择候选、不自动校准时序 |
| 对白候选选择 | H | 接受属于该 DialogueLine 的成功、未隐藏 WAV；正文、音色或表演参数变化只作软提示，不阻止人类试听后选择；选择任一句会清空该 Segment 全部起点并失效视频选择 |
| `dialogue.set_timing` | A | `segment_id` + 全部 DialogueLine 的 `starts` + `duration_seconds`；按真实 WAV 时长拒绝重叠，并要求 Segment 时长不短于最后一句结束时间 |

## 地点

`location.apply_operations`（A）：在 `scope = {location_ids, scene_ids}` 内按顺序原子执行操作。scope 内 ID 必须存在；
地点级操作要求地点在 scope 内或由本 patch 新建，图片操作按所属地点判定，`bind_scene` 要求目标 Scene 在 scope 内。
同一 patch 新建的地点、陈设、状态、图片用局部 `key`（`[a-z][a-z0-9_-]{0,63}`，不能是 32 位 hex）互相引用，回执
`data.created_ids` 返回 key → 正式 ID。

| 操作 | 要点 |
| --- | --- |
| `create_location` | `key`、`name`、`description` |
| `update_location` | `fields` 是 `name`、`description`、`key_light`（`{description}` 或 null）的非空子集 |
| `delete_location` | Scene 仍绑定该地点时拒绝；历史图片 Asset、Generation 与全景取景子图保留 |
| `upsert_fixture` / `delete_fixture` | `fixture` 为已有 ID（整体替换）或 key（新建）；`name`、`description` |
| `upsert_state` / `delete_state` | `state` 为已有 ID 或 key；`name`、`description` |
| `create_image` / `update_image` | `fields`：`name`、`kind`（image / panorama）、强制 `description`、`prompt_text`、`reference_asset_ids`（≤5）、可选冻结 `source`；create 必含前三项 |
| `delete_image` | 删除地点中的图片条目；历史 Asset/Generation 与已生成子图保留 |
| `bind_scene` | `scene_id`、`location_id`、`state_id`（可空） |
| `clear_image_selection` | 清除该独立地点图片的已选图，不级联 Keyframe/视频 |

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `location.generate_image` | A | `image_id`；普通图跟随项目画幅，全景图固定 2:1；使用该条目保存的任意显式图片参考 |
| `location.capture_panorama` | A/H | `image_id`（全景）、新子图 `name` / 强制 `description`、yaw/pitch/hfov；创建普通图片并提交确定性取景 |
| `location.generate_set` | A | `target_ids`（地点图片 ID）启动批次，或 `run_id` 继续；全景取景不进入批次 |
| `location.select_image` | H | `image_id`、`asset_id`：可采用该图片条目成功且未隐藏的候选，或直接采用项目资产库中的图片；全景图仍校验 2:1，全景取景子图只接受自己的裁切产物 |

人类 HTTP 另有：`POST locations/operations`、`POST location-images/{id}/generate`、`POST location-images/{id}/select`、
`POST location-images/{id}/capture`，都构造同一命令执行。

## Keyframe

`keyframe.apply_operations`（A）：1–100 项操作。Core 不相信调用方另报的 scope，而是从操作涉及的 Segment、Keyframe、Asset
反查完整受影响范围并校验授权。

| 操作 | 要点 |
| --- | --- |
| `set_activation` | 同时设置 Segment 首尾槽位是否启用 |
| `update_frame_fields` | 画面正文、可见角色、每个可见角色本帧使用的造型（`character_references`，`look_id` 或 null）、参考的其它 Keyframe（`reference_keyframe_ids`，0–4 个，整体替换，每个都必须已有选中图且不能是自身）、参考的地点图片条目（`reference_location_image_ids`，0–4 个，整体替换，只限已有选中图的普通图片）；不含地点绑定。正文、造型或参考变化会清除本帧选择 |
| `set_aux_references` | 替换 Segment 手工辅助图集合（≤4） |
| `bind_slot` | 把已有 Keyframe 绑定到某首帧或尾帧槽位 |
| `share_boundary` | 让真实相邻 Segment 的左尾与右首共享一个 Keyframe；可给 `source_keyframe_id` 复用现有对象及其血缘，否则 Core 从边界事实中挑选可复用对象，没有时才新建 |
| `split_boundary` | 拆开共享边界，明确克隆哪一侧以及是否复制当前选择 |
| `clear_selection` | 撤销当前候选选择 |

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `keyframe.generate` | A | 单个 `keyframe_id`；只提交该帧 |
| `keyframe.generate_batch` | A | `target_ids` 为显式、不重复、已启用的 Keyframe 集合；本轮只提交依赖已满足的帧 |
| `keyframe.continue_batch` | A | `batch_id` 或任一关联 `run_id`；不能带新范围 |
| `keyframe.select_candidate` | A/H | Agent 以 `keyframe_id` + `generation_id` 采用该帧成功、未隐藏且产出图片的 `keyframe_image` 或抽帧候选；人类也可直接采用项目图片。双方写同一字段，任一方随时可改选 |

人类 HTTP 另有：保存首帧卡共享开关（`PUT segments/{id}/keyframe-boundary`）与“从上一 seg 抽取”（`POST keyframes/{id}/extract-frame`，
必须给 `frame_index`）。

## 视频

| 命令 | 调用方 | 要点 |
| --- | --- | --- |
| `video.set_prompt` | A | 保存单 Segment 视频正文（≤ 20,000） |
| `video.update_recipe_inputs` | A | 原子保存 `prompt_text`、当前 recipe 的 `bindings`（槽位 → 有序 `{asset_id, description}`）与机制 `params`，按槽位、按键合并进当前 recipe 的输入簿（给出的槽位整体替换、空列表清空，未给出的保留）；可选 `attach_dialogue_audio: true` 按“一键添加本段对白 TTS”规则合并已选对白 WAV（缺句或超额整次拒绝）；按 manifest 校验槽位、数量、媒体类型、时长、说明与唯一性，只接受本项目 Asset；人类与 Agent 同一路径。多 Shot Segment 的正文按覆盖顺序读取工作集 `context.shots` |
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

候选选择、普通正面反馈与最终批准是三种不同权限；只有 Keyframe 候选选择对 Agent 开放。

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

## Segment 其他图片

`video.save_reference_image_plan` 以 Scene scope、Segment ID 和 `slot_index`（0–3）保存当前 recipe
的一张无时间位置参考图规划，包含画面正文、用途说明、可见角色/造型与显式生图参考；Core 分配稳定规划 ID。
图片内容可为任意画面，不限定来源或题材；MCP 同名 `save_reference_image_plan` 提供单卡规划入口，无角色时角色数组为空。
`video.generate_reference_image` 只接收该 `image_id`，通过当前图片 Provider 生成独立候选，回调不改视频输入。
`video.select_reference_image` 是人类操作，以 Scene scope、Segment ID、槽位序号、项目 `asset_id` 和
实际内容/参考用途说明原子更新当前 recipe 的图片输入；`asset_id=null` 移除该图片。未填的槽位不占提交名额。
`read_story` 的 Segment `selection` / `keyframe` / `video_prompt` 扩展返回 `video_inputs`，其中包含规划 ID、正文、选图状态与实际图片绑定；
Keyframe 与视频专业工作集提供同一 `video_inputs[]`。规划与生成可由 Agent 明确调用，视频参考图候选采用保留给人类；Agent 的通用 recipe 输入写入不能采用尚未经人类选入的参考图候选。
