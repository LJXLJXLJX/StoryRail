# Structured Director

本目录拥有 StoryRail schema v36 项目的结构化导演领域：模型、编解码、领域变换、Store、读取投影、媒体提交、Service 与
HTTP contract。`project.json` 的创建、读取、校验、revision compare-and-swap 与原子替换都在这里完成，它是唯一的项目写者。

行为说明在产品说明书中：[数据模型](../../docs/data-model.md)、[生产工作流](../../docs/production-workflow.md)、
[控制流](../../docs/control-flow.md)、[数据流](../../docs/data-flow.md)、[命令目录](../../docs/commands.md)。本文只说明代码组织。

## 分层

由 `tests/test_layer_rules.py` 守卫，只允许向下依赖：

| 层 | 位置 | 职责 |
| --- | --- | --- |
| L0 | `models/` | 不可变值对象与不变量 |
| L1 | `codec/`、`schema.py`、`errors.py`、`video_contracts.py`、`video_inputs.py`、`candidate_eligibility.py`、`script_index.py` | 严格 JSON 编解码、schema 版本、共享错误、视频输入与候选可选性判定、脚本访问层 |
| L2 | `mutations/`、`*_mutations.py`、`generation_lifecycle.py`、`assembly_timeline.py`、`narration_timing.py`、`dialogue_timing.py`、`production_context.py`、`run_state.py`、`asset_metadata.py`、`planning_inputs.py` | 纯函数领域变换、失效传播、时序与装配时间线 |
| L3 | `store/` | 唯一持久化入口：CAS、完整校验、fsync、原子替换 |
| L4 | `reads/`、`prompt_worksets.py`、`keyframe_requests.py`、`location_requests.py`、`director_steps.py`、`manual_commands.py` | 只读投影与输入编译 |
| L5 | `proposal_requests.py`、`proposal_request_guard.py`、`planning_proposals.py`、`reference_proposals.py`、`script_proposals.py`、`location_proposals.py`、`workflow_commands.py`、`application_requests.py` | 命令、proposal 生命周期与授权回执 |
| L6 | `service.py`、`media_submission/`、`generation_observer.py`、`external_batches.py`、`keyframe_batches.py`、`location_batches.py`、`production_commands.py`、`provider_ports.py` | 应用编排与 Provider 交互 |
| L7 | `http_api.py`、`http_requests.py` | HTTP 分派、严格请求解析与错误翻译 |

同层或向上的例外 import 必须登记在测试的 `DIRECTION_WHITELIST` 并注明理由；模块级 import 图无环。

## 模块

**应用与命令**

- `service.py`：`StructuredDirectorService`，持有项目 Store、`ProviderRegistry` 与两把 asyncio 锁（领域写入 / 外部应用请求），
  组合下列协作者；不内联持久化细节。
- `application_requests.py`：外部命令的原子回执、同 key 回放、生成请求 pending/uncertain 恢复。
- `media_submission/dialogue.py`：逐句对白 TTS 提交；角色已有参考音色时使用同语言克隆，否则使用角色卡或临时说话者的音色描述做 Voice Design。
- `mutations/dialogue.py`：保存逐句克隆表演参数、由人类选择对白 WAV、保存 Segment 内发声起点，并以 WAV 真实时长校准 Segment 时长和失效下游视频。
- `production_commands.py`：生成、选择、装配等生产命令到 Service 用例的分发。
- `workflow_commands.py`：工作流确认（引用确认、脚本确认、视觉生产解锁）；解锁回执附未绑定地点提示。
- `manual_commands.py`：把 Web 手工编辑值对象翻译成与 Agent 相同的确定性命令（含地点语义、独立图片与人类选图）。
- `location_mutations.py`：地点库唯一 mutation：类型化操作、人类候选选择与删除引用检查。
- `errors.py`：命令、持久化与 HTTP 共享的领域错误类型。

**外部 proposal 与专业输入**

- `proposal_requests.py`：引用库、脚本、Keyframe、地点四类 proposal 共用的 request/get/submit/reject/cancel 生命周期。
- `proposal_request_guard.py`：proposal 请求的 caller 所有权与授权校验。
- `reference_proposals.py`、`script_proposals.py`：引用库与脚本冷启动的工作集、严格 parser 与 Store 调用。
- `planning_proposals.py`：Keyframe 规划的 proposal 处理。
- `location_proposals.py`：地点规划的项目级工作集与提交：proposal 编译成 `location.apply_operations` 的同一组操作，
  在 `LOCATION_PLAN` run 内经 `location_mutations.py` 原子落库（局部 key 映射、失效级联与手工编辑同源）并结束 run。
- `planning_inputs.py`：专业规划的纯输入构造（含局部 Keyframe 的完整 Scene 上下文、锁定节点与共享边界；地点规划的全部 Scene/Shot 与已有地点归属）。
- `prompt_worksets.py`：视频 recipe 与 Keyframe 专业工作集（实际 Provider 输入清单与 `<Picture N>` / `<Audio N>` / `<Video N>` 映射；对白 WAV 与手动 Audio 共用显式 recipe 列表，缺失引用阻止生成，视频另给已保存的 `recipe_inputs` 与当前 recipe 显式槽位的 `bindable_assets`），以及当前图片插件的提示词约定与随插件 Skill（`image_prompt_guide`）。

**生产**

- `keyframe_requests.py`：Keyframe 生成目标展开、角色/前置帧/辅助图输入编译与 instruction；预览与实际提交共源。
- `location_requests.py`：独立地点图片生成与全景取景的前置检查、实际输入映射、名额和提示词编译。
- `image_inputs.py`：单次图片调用的实际输入：按名额优先级去重、超过 `MAX_IMAGE_INPUTS`（5）时拒绝并列出被挤掉的输入、编辑底图排第一；Keyframe 与地点生成共用。
- `image_prompt_style.py`：按当前绑定图片插件的 `image_prompt` 约定解析输入图指代与画幅句；预览、工作集与提交共用。
- `image_inputs.py`：合并实际输入，工作集暴露 `asset_id`、`label`、`roles`，预览只展示来源信息。校验显式引用段数量、顺序和正文标签，不生成或重排引用说明、不把默认用途拼入提示词；既有纯正文仍可读取与生成。
- `video_inputs.py`：Segment 视频实际输入、输入签名、候选可选性、首帧抽取来源。
- `keyframe_batches.py`：Keyframe 波次执行（只提交前置帧、角色造型等显式依赖已满足的目标）。
- `location_batches.py`：地点图片成套生成批次（`location.generate_set`）的单轮执行：固定图片范围，复用单项入口提交；回调不续推进。
- `external_batches.py`：外部批次（Keyframe 波次与地点成套生成）的 start/continue、稳定 `batch_id` 与执行轮次关联。
- `director_steps.py`：确定性生产步骤与 Keyframe scope 硬约束。
- `generation_lifecycle.py`：Generation 重试签名、阶段与错误归类（不调用 Provider）。
- `candidate_eligibility.py`：候选可审核性的共源判定。
- `run_state.py`：DirectorRun 开始、唤醒与默认授权的对象变换。
- `production_context.py`：从快照构造只读生产上下文。
- `script_index.py`：脚本访问层：Scene 的 Segment 序列、Segment 覆盖的 Shot 与派生可见角色；
  只读遍历经它读取，不直接访问 Scene 的存储形状。
- `provider_ports.py`：各媒体能力的 Core 侧窄 Protocol。
- `asset_metadata.py`：媒体字节校验、时长读取与可读文件名（封装 `core/media_assets`）。

## 关键约束

- 只有 Store 读写 `project.json`；用例模块不调用原子写入细节，也不新建 Store 或 Registry。
- 手工按钮、Agent 命令与 proposal 应用共用同一套 L2 变换与 Store 方法，不存在第二条写路径。
- Generation 的百分比与同阶段进度只在 Store 的内存观察缓存中，不写 `project.json`；阶段、句柄、取消意图、错误与产物持久化。
- Scene 成片有稳定的“当前文件”：重新装配成功后原子替换当前文件，上一版改名为带内容哈希的归档，旧 Asset 仍指向归档字节。
- Provider 只接收任务所需的受控字节与参数；`.runtime/` 不参与业务决策；Windows、CUDA、盘符、SMB 与模型安装不进入本目录协议。
- 不包含旧 schema 迁移、shadow document、双写或数据库；schema 变化后通过正常创建入口建立新项目。

## 地点语义与独立图片

`location_mutations.py` 在一个事务中编辑地点、陈设、主光、状态、独立图片与 Scene 绑定。Shot 和 Keyframe 没有地点字段，
所以地点变化不传播生产失效；删除图片保留历史 Asset/Generation 与已经生成的全景子图。仍被 Scene 使用的地点或状态拒绝删除，
同目标非终态 Generation 仍阻止冲突修改。

`location_requests.py` 为每张图片编译生成：普通图跟随项目画幅，全景图固定 2:1 并加入等距柱状和左右无缝约束；
`reference_asset_ids` 是至多 5 张任意项目图片。成功回调只新增候选；人类通过 `location.select_image` 采用候选，
或直接把资产库已有图片设为当前地点图片。全景图仍校验 2:1；带冻结 `source` 的全景取景子图只接受自己的裁切产物。

全景图是唯一特殊类别。Web 用已选全景 Asset 打开 3D 查看器，用户调整 yaw/pitch/hfov、填写新图片名称与强制说明后调用
全景取景入口。Core 原子创建普通图片及冻结 `source`，提交 `PANO_VIEW`；成功回调直接选择确定性产物。父全景图后续变化不级联。

Keyframe Planner 工作集投影当前 Scene 的 `location_id` / `state_id`、地点语义和所有地点图片说明，帮助 Agent 自行写出空间；
图片不会自动进入 Keyframe Provider 输入。只有用户把某张地点图的已选 Asset 显式加入 Segment 辅助参考时才提交。

## 地点卡快照与批次

`reads/location_image.py` 为每个独立图片条目投影生产状态、候选、选图与 `allowed_actions`；Web 只消费投影，不猜状态机。
全景图在已有有效选图时开放预览/取景动作。图片说明是持久化必填事实，不从 prompt 或候选反推。

`location.generate_set` 固定一组地点图片 ID。单轮分类顺序为进行中/不确定、已选择、成功待选、失败或取消、可提交；只对可提交项
复用单项生成入口。全景取景不进入批次。每轮结束自己的 run，选择与回调不自动推进；显式 continue 保持原范围。

Segment 的其他图片由 `reference_image_mutations.py` 保存规划/人类绑定，`reference_image_requests.py` 编译实际生图输入，`media_submission/image.py` 只提交候选。生成与选择分离；视频只读取 recipe 输入簿。
