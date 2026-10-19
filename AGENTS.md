# StoryRail 仓库协作说明

## 软件开发入口

开发 StoryRail 软件本身时，先读 [目录与依赖](STRUCT.md)、[文档索引](docs/README.md)、
[系统架构](docs/architecture.md) 和 [外部 Agent 接入](docs/external-agents.md)。
检查当前 Git 状态并保留无关工作；按本次任务范围实施，完成后运行 README 中的工程门禁。
软件开发记录与影视项目的业务状态严格隔离，不复用 `DirectorRun` 管理开发任务。

## 文档与施工记录

- `docs/` 是最终产品说明书：只描述系统**现在**是什么、怎么运转，技术细节、控制流与数据流必须讲清楚，
  优先用 mermaid 画图。不写决策过程、阶段/任务编号（R11、P6-T4 之类）、“后继修正”、验收记录或对比报告。
- 施工流程记录一律放 `wip/`：重构计划、任务卡、方案讨论、决策过程、验收记录、基准对比报告、QA 截图。
  工作完成后，把仍然有效的结论改写进 `docs/` 或代码目录 README，再删除对应的 `wip/` 内容。
  `wip/` 被 Git 忽略，只存在于本机，不进入仓库。
- 代码目录 README 与 `docs/` 同样只写现状。行为变化时直接改写受影响段落，不追加“补充/修正”段落。
- 测试或脚本读取的基线数据跟随使用方放在代码目录（例如 `scripts/harness/benchmark/baselines/`），不放 `docs/`。

当前为早期敏捷开发、单人维护：常规任务通过工程门禁后直接在 `main` 提交并推送，不另开分支或 PR；
只有长线大重构才切分支。提交和推送仍须用户要求。

创作 Agent 以及开发中接触真实作品的 coding Agent 均禁止绕过 Core 直接修改项目业务 authority。
唯一的用户主动、单 session、单项目、单操作 break-glass 规则与完整授权文本见
[业务状态保护](docs/business-state-protection.md)。文档中出现授权文本不代表已授权。
现有正式 `project.apply_repair_patch` 仍走 Core，不能与 direct-file bypass 混淆。

## 架构边界

执行由外部成熟 Agent 承担；完整业务入口与恢复通过 Core HTTP/MCP 提供。
内置 Pi/Codex Agent adapters、装配和依赖已删除，不重新引入内置执行器或隐藏 fallback。
Core authority、专业契约、领域 run/cursor 和媒体 Provider adapters 保留；名称含 Codex 的媒体插件是图片 Provider，不是 Agent runtime。

## 当前产品

StoryRail 从用户提供的完整 Markdown 导演方案开始。创建项目时写入项目名称、`16:9`、`9:16` 或 `2:1` 画面比例、必须选择的旁白语言和不可变的 `director_plan_markdown`，随后直接进入结构化导演台。系统保留引用库、结构化脚本、旁白审核、地点库、Segment 关键帧、视频、超分、最终装配和 Approval；不再包含 Creative Intake、剧情发展或导演方案讨论阶段。

另有一个与项目平行、全局唯一的 Playground：不含任何故事上下文，人和从 Playground 启动的外部 Agent 可以用
生产同一批 Provider 调试生图、改图、全景裁切、TTS、ASR、视频、超分、抽帧、音频分离/混音/后处理/截取。
Playground 不突破生产参数约束，也不包含候选选择、Approval 或故事能力。详见 [Playground](docs/playground.md)。

## 语言与命名

- Agent 说明、用户流程、错误解释和审核文本使用中文；
- API 字段、JSON key、事件名和代码标识符使用英文；
- Provider、Agent、Asset、Generation 等领域术语可保留英文。

## 事实来源

1. `.stories/<项目名>-<project_id>/project.json` 是唯一权威结构化状态，当前 schema 为 v35（Scene 下并列 `shots` 与 `segments`、Segment 以 `shot_ids` 记录覆盖的 Shot、旁白 Cue 不带 Shot 锚点、角色造型 `looks` 为角色图唯一单位、地点库保存 Scene 级语义绑定与独立图片而 Shot/Keyframe 不绑定地点、创建时选择中英文旁白语言、各启用语言一套音色、Keyframe 按帧选择角色造型、视频保存 `active_recipe` 与 `recipes` 输入簿，旁白保存 `recipe_params`，Generation 记录提交时的 `provider_snapshot`）。
   更早版本的 Segment 挂在 Shot 下，或没有英文旁白、只有一套旁白音色，无法无损转换，一律拒绝读取并提示新建项目。
   `workspace_layers` 持久化旁白、Keyframe、视频和成片内容层是否已经解锁；这些事实不由 Web
   根据全局状态猜测。
2. `title` 和 `aspect_ratio` 在创建时固化；`director_plan_markdown` 可由人类在导演台手工修改，Agent 无权修改。
   修改只更新原始方案与项目 revision，不自动改写或失效已有引用库、结构化脚本和媒体；需要反映到成片时仍须显式回改脚本。
3. `assets/` 按媒体类型与用途保存不可变媒体字节，JSON 只保存受控项目内相对路径和资产关系；文件名使用可读语义名称并附短哈希防冲突，不得跨边界传本机绝对路径。
4. 外部 Agent 的工作区和对话由外部管理，不是项目事实；Core 不读取这些文件。
5. Core 不创建厂商 `.runtime/` thread；历史诊断包不参与业务流程。
6. 不引入数据库、ORM、migration 或双写；Core 串行化写入、校验 revision 并原子替换 JSON。
7. 不兼容旧 schema，不增加旧项目或旧工作稿迁移分支；开发期破坏性变更后新建项目。
8. `.stories/.playground/playground.json` 是 Playground 的唯一权威状态（schema v2），`assets/` 规则同项目。
   Playground 与项目互不引用；跨域只能由人类复制 Asset，复制产生新的项目或 Playground Asset，项目 schema 不记录来源。

## 工作流边界

- `POST /api/projects` 只持久化项目，不能等待 Agent。Web 进入新页面后等待外部 Agent 通过正式入口提交引用库 proposal。
- Director 的引用库能力只读取完整 `director_plan_markdown`，提出需要跨镜头一致的角色卡和独立旁白身份；Core 分配 ID。
- 用户审核引用卡后显式生成结构化脚本。脚本 Agent 只读取原始导演方案、当前引用卡和必要的当前脚本。写脚本分两步：
  先设计 Shot 列表（镜头功能、构图、运镜、动作、声音与剪辑决定），再按打包规则把 Shot 装进 Segment；一个 Segment
  可覆盖多个连续 Shot（段内切镜），一个 Shot 可跨多个相邻 Segment（长镜头拆段），打包理由写入 `reply_markdown`。
- 创建项目必须选择 `narration_languages`：仅 `zh`、`en`，至少一个、不重复，创建后不可修改。
  每条 Cue 与旁白身份只建立所选语言的轨道、音色；未选语言字段为 null。各语言独立保存正文、seed、
  `recipe_params`、参考 WAV 与完整文字稿，并分别合成、审核、选择；英文是适合朗读的意译。
  只用同语言参考音色克隆。单语言以该音频的真实时长为基准；双语言以较长音频为基准，短的一条同起点提前结束。
  Scene 成片和最终成片只输出所选语言；双语言画面一致只换旁白，一次 Approval 批准所选语言全部版本。对白不做双语。
- Scene 显式声明 `driver`：`narration` 初稿只有一个语义原子的 Cue（不按标点数量判断），先完成 TTS 并选择真实音频，再规划 Shot / Segment；`drama` 先设计 Shot，不预设 Scene 总时长。旁白与对白按 Scene 互斥：Narration Scene 必须有旁白且不含对白，Drama Scene 不含旁白、对白可有可无，由 Core 的 Scene 模型强制；同一内容需要两者时拆成相邻 Scene。二者可在项目中混合。旁白回改清除音频选择、失效时序和装配，保留已有视觉设计。旁白层解锁后，Core 在每次脚本或旁白写入里自动按真实音频校准 Narration Scene 并建立生产基线，没有人工确认时序步骤；无法校准时基线保持失效并返回原因。
- 结构化脚本生成后始终使用同一个导演台页面；左侧导航为 Scene → Segment，Scene 页以“镜头设计”列表编辑 Shot，
  Segment 页显示覆盖区间与延续说明；后续内容层嵌在原层级，不再切换到旁白、地点、Keyframe、视频或成片专用页面；
  地点库是导演台内的浮层。
- 每个出镜角色有 1–8 套造型（`looks`：名称、外观、使用场合自由文本），引用库 proposal 一并提出，Core 分配 ID；
  Agent 经 `reference.apply_look_operations` 新增或修改造型，删除只由人类完成。造型是角色图的唯一单位：每套造型
  至多一张人类选定的造型图（`selected_asset_id`，来自设定图候选或资产库已有图片），角色卡不再有游离参考图。
  设定图：柔和浅灰底、固定 2:1，左侧四视角、右侧头部正面特写，只有一套版式：主体描述在前，版式不含只属于人的措辞，
  非人生物靠提示词约束按真实生物绘制、只画主体不画环境（不设形体标记字段）。提示词由 Core 从视觉描述与造型外观编译，
  人类可在生成前查看并编辑完整提示词（原样提交，重试沿用；Agent 不写设定图提示词），
  Codex/AGY 在提示词里写 4K 分辨率，Qwen 沿用全局档位。`reference.generate_look_sheet` 只接收造型 ID 与 ≤ 4 张
  显式身份参考，只新增候选；Keyframe 与普通地点图片使用项目画幅，造型设定图与地点全景图固定 2:1。
- 地点库（`location_library`）保存跨 Scene 共享的固定空间：Core 分配稳定 ID 的地点、固定陈设与主光、状态变体和彼此独立的图片。
  图片没有主图/视图层级，`kind=image|panorama`；每张图片必须由用户或 Agent 填写与生成提示词分离的实际内容纯文本说明。
  普通图跟随项目画幅，全景图固定 2:1。全景图是唯一特殊类别：点击后进入 3D 预览，用户调整 yaw/pitch/hfov 并显式创建普通子图；
  `PANO_VIEW` 产物直接选给子图，冻结来源只作 provenance，不形成活依赖。所有普通生成候选只有人类可以选择。
- 同一空间的昼夜、天气、布置或破坏变化建为状态，不建新地点。只有 Scene 绑定 `location_id` 与可选 `state_id`；Shot 与 Keyframe
  不保存地点或地点图片绑定。地点、状态、图片或 Scene 绑定变化不级联失效 Keyframe、视频、超分与装配；删除图片保留历史
  Asset/Generation 与已取景子图。Scene 仍绑定地点时拒绝删除；被 Scene 引用的状态仍拒绝删除；相关进行中或不确定任务阻止冲突修改。
- 地点规划只能由用户明确要求后经 `location` 专业能力提交 proposal（要求已有脚本，增补不删除）；成套生成用
  `location.generate_set` 固定范围、每轮只提交依赖已满足的项，选择或回调都不自动推进，继续须再次显式调用。
- 生产基线建立后，`read_workflow` 的 `recommended_next_actions` 给出规划地点、成套生成或继续地点批次等可选建议；
  它们永不进入 `required_next_actions`、不改变 `allowed_actions`。Agent 只向用户提议，收到明确指令才执行，用户说“推进”时
  不执行推荐动作。解锁视觉生产本身就是跳过地点规划，解锁后只保留在途地点批次的继续提示。
- 外部 Agent 可将可读的 `@功能名` 或自然语言请求映射到正式能力。Agent 必须将它映射成
  类型化动作；用户以自然语言明确要求同一功能时也必须直接映射，不能要求再次输入 `@功能名`。Core 仍
  校验状态和目标；功能提示本身不授予权限，也不自动执行。
- 每个 Segment 都有概念上的首尾 Keyframe 槽位。FL2VA 至少选择其中一个；Ref2VA 不要求首尾帧或任何图片，但图片、音频与视频参考合计至少有一个输入资产。先确定完整连续关系与整段视觉信息需求，再选择最少必要帧；只有单帧覆盖必要角色、场景和道具信息时才使用单帧，局部拉远揭示通常需要双帧。精确结束状态需要尾帧。相邻 Segment 的边界默认是两个独立 Keyframe（上一段尾帧、下一段首帧），程序不保证两者一致；
  用户或 Director 可以显式共享为同一个 Keyframe，共享后两侧启用状态仍各自决定。首帧卡提供“从上一 seg 抽取”：
  按帧号（默认最后一帧，范围 `0-(N-1)` 由 Core 从 MP4 读出）抽取上一段当前生效视频的一帧，产物只作为该首帧候选，
  不自动选择；需要后期处理时用户导入处理后的图片再选择。所有抽帧入口都按帧号工作，Core 不再维护“尾帧续接”状态。关键帧辅助参考图只用于关键帧生图，不会自动进入视频输入；视频卡按当前 recipe 的槽位声明显式保存参考。H3 Ref2VA 声明最多 4 张附加图片、每张必填描述；Core 按槽位顺序与标签 namespace 计算映射，专业工作集与实际 Provider 提交共用该映射。生产期脚本回改（合并、拆分、增删 Segment）后，Core 必须立即按当前脚本重建关键帧绑定：保留仍在的 Segment 原绑定与已选关键帧，新 Segment 立即获得独立的空首尾槽位，已删除 Segment 的槽位随之移除；显式共享的边界只在两侧仍紧邻时保留，否则复制为独立首帧；关键帧计划必须完整对应每个当前 Segment，由 Core 校验强制，不允许缺卡。
- Keyframe 不保存地点字段。Planner 工作集给出 Scene 的地点/状态、地点语义和地点图片的强制说明，LLM 据此结合 Shot 与叙事上下文
  自行建立画面；地点图片不自动进入 Provider 输入，也不构成生成依赖。只有用户把某张已选地点图片显式加入 Segment 辅助参考时才提交。
  输入名额顺序为可见角色参考 → 前置帧 → 辅助图，合计 ≤ 5 张，超额拒绝并列出被挤掉的输入；前置帧作为编辑底图时排第一。
- 角色实体唯一，同一角色可有多套造型（不同时期、服装或状态，各带使用场合）。每个 Keyframe 用 `character_references`
  为可见角色选择本帧使用的造型（`look_id`，null 表示不提交）；只有一套造型时默认使用，多套造型未选择时 Core 拒绝生成该帧，
  所选造型没有造型图时也拒绝。Keyframe 引用造型而不是图片，改选造型图不改写 Keyframe；删除造型时剪除对它的选择。
  手工弹窗与 Keyframe Planner 读写同一字段，工作集给出每套造型的 ID、名称、使用场合与是否已有造型图。
- Director 的 Keyframe Skill 与手工弹窗必须读写同一权威计划；重规划保留 Segment 手工辅助图，弹窗完整展示
  前置帧、可见角色参考与手工辅助图的实际提交映射。图片对应关系必须位于 instruction 顶部；
  画幅最多由 Core 固定编译一次，Agent 的画面正文不得重复画幅标签；输入图指代与是否写画幅句跟随当前图片插件
  manifest 的 `image_prompt` 约定（Qwen 用 `<imageN>`、画幅由画布保证）。声明 Seed 的图片插件由 Core 为每次提交分配 seed。
- 进入 Keyframe 或视频阶段只建立计划，不自动生成。生成必须由用户在 Director 对话中明确要求。
- Keyframe 卡片的单图生成按钮只提交该 Keyframe，成功回调只保存结果，不调用 Agent、不扫描或生成任何
  其它 Keyframe。批量按钮或 Director Agent 的显式批量动作每轮也只提交其授权范围内当前依赖已满足的
  Keyframe；前置完成后需要新的显式继续动作，不能用全项目自动补齐代替持久化批次范围。
- Keyframe 规划默认遵守用户指定范围；Planner 可读取目标 Segment 所属完整 Scene 作为连续性上下文，但 Core
  只能合并目标 Segment 的 Keyframe 子图，同 Scene 其他 Segment 也必须保留。只有明确要求全部规划时才遍历和
  合并完整项目；局部规划恢复时若目标范围丢失，必须无修改结束并要求用户重试，不能扩大为全量规划。
- 已有未隐藏成功候选或已选择候选的 Keyframe 是规划锁定节点；局部或全量重新规划都必须保留该 Segment
  的现有首尾绑定、提示词、候选和辅助参考。规划只能重建没有生成候选的 Segment，不得让历史 Generation
  因 Keyframe ID 被替换而从当前卡片解绑。
- Core 校验 Segment 视频时长为不短于 0.2 秒的有限值；插件可以声明自己的输入约束与软提示。当前 H3 插件以
  `hints.soft_duration_limit_seconds = 15` 提示默认本地部署的 OOM 风险，`video_prompt` 工作集给出
  `exceeds_soft_duration_limit`，不是 Core 时长上限。脚本阶段先设计 Shot 列表、再打包成 Segment：一个 Segment 可覆盖多个
  相邻 Shot（段内切镜），一个 Shot 也可跨多个相邻 Segment（长镜头拆段），不按固定 Shot 数或时长预先绑定。
  生成视频前 Agent 对超过软约束的 Segment 主动提醒风险并建议拆分点（自然动作状态、控制方式或连续性锚点），
  用户同意后再拆，坚持不拆则照常生成。这只是提示词约束，Core 不校验 Shot 的 Segment 数量。
- Segment 的 `active_recipe` 来自当前视频插件的 `defaults` 与 `segment.has_dialogue` 谓词；H3 默认无对白 FL2VA、
  有对白 Ref2VA。人类可切换 recipe，Core 保存输入簿并校验已有输入与目标 recipe 的兼容性。
  H3 Ref2VA 声明 0–4 张附加图片、0–8 条 WAV 参考音频、0–3 条 2–15 秒 MP4 参考视频；首尾帧都可为空且可完全不使用图片，但所有媒体槽位合计至少有一项，有引用时均不重复且必填说明；音频引用不会从角色卡
  自动推导，视频只作视觉参考、不引入其音轨。Core 按稳定顺序生成 Picture/Audio/Video 各自独立从 1 起的标签，
  并与 Provider 输入保持一致。切回 FL2VA 前必须清空其不支持的图片、音频和视频参考槽位。
  一个 Segment 覆盖多个 Shot 时，`video_prompt` 工作集给出 `context.shots`（按覆盖顺序，含构图、运镜、动作、声音、
  可见角色名与视图建议名）以及 `continues_from_previous_segment` / `continues_into_next_segment`；提示词用
  `[Shot N] At MM:SS.mmm` 写段内切镜，切点只是软约束，首尾 Picture 只锚定首末 Shot。
- 语义角色参数由 Core 根据领域事实填写；没有角色的机制参数按 recipe 保存。旁白使用 `recipe_params[recipe_id]`，
  视频使用 `recipes[recipe_id].params`；Web 按声明渲染控件，Agent 按 `speech_recipe` 或 `video_prompt` 工作集填写。
  Agent 与人类经同一 `video.update_recipe_inputs` 原子保存视频正文、当前 recipe 的参考素材绑定与机制参数，校验相同；
  Agent 只在用户明确要求时增删或替换绑定，未改动部分按工作集 `recipe_inputs` 原样回传。
  音色描述仍是领域字段，映射到 prompt 角色。Breeze 的表演指示和 IndexTTS2.5 的语速/情感向量属于各自插件机制参数。
- 每个媒体能力的插件绑定与实例设置是 Core 全局 Provider 设置，项目与 Playground 共用、只有人类可改；每次提交读取
  当前值并在 Generation 的 `provider_snapshot` 中记录，改设置不失效已有候选。连接由启动配置装配，实例 ID 等于包名、
  recipe ID 带插件前缀。H3 的基础模型预设、分辨率、SageAttention 和 SelfLift 都由它的 manifest 声明。
- 视频提示词由人类手工编辑，或由 Director Agent 显式使用当前插件声明的专业 Skill 优化（H3 为 `h3-prompt-writing`）。
  用户指定语言时必须服从，未指定时不增加语言约束；插件格式、标签与时间语法仍须保留。视频生成是纯程序动作：
  Core 校验后直接提交已保存正文，不调用 Agent、不重写正文；空提示词必须先填写或显式优化。
- Segment 视频候选的选择只要求“成功、未隐藏、属于该 Segment 且有 MP4 产物”，由用户决定选哪一条。
  候选生成时的关键帧、提示词或参考输入快照变化只作软提示（快照中的 `inputs_outdated`），不阻止选择，
  也不阻止超分、Scene 成片和最终装配使用它；不因此把已生成候选降级为不可选历史。
- 每个项目在外部 Agent 中使用 Director 职责；Core 不持有厂商会话。引用库、脚本、旁白、地点、Keyframe、视频提示词和生产检查都是它按需使用的 Skill/类型化能力，不拥有独立 Thread、对话、阶段或权限。Director 可以提出类型化的脚本回改、地点、Keyframe、Segment 视频或超分动作，但不能绕过 Core 校验、候选选择和审核。
- 阶段能力按 `workspace_layers` 累加；后续阶段继承前面已解锁能力。上游回改只失效相关产物和生产基线，不退回阶段、不重锁入口；历史 Asset/Generation 保留。Agent 工作期间仍锁定冲突写入，Approval 后仍须显式重新开放生产。
- 相邻 Segment（无论是否共享边界 Shot）默认硬切，仅边界 Keyframe identity 相同且两侧都启用才做 0.1 秒系统接缝融合（`seam_blend`），不是导演 dissolve；跨 Scene 使用同一规则。用户选择成片后仍需单独 Approval。
- Scene 成片是 Scene 内已审核 Segment 视频加旁白的确定性渲染结果；最终成片装配只按脚本顺序拼接各 Scene 成片的字节，不再读取原始 Segment 或重新混入旁白。每个 Scene 都必须存在基于当前 Segment 视频与旁白选择生成的 Scene 成片，缺失或过期的 Scene 阻止最终装配并一次列出；重新生成或删除 Scene 成片会作废已建立的装配计划。
- Scene Animatic 预览是旁白与关键帧就绪后由用户在 Scene 卡片手动触发的 Scene 级动态分镜：
  按脚本顺序展示所选关键帧图，首尾帧齐备的 Segment 内平分时长硬切，段间转场复用最终装配规则，
  旁白按成片同一算法精确对轨；它只读已有审核产物，不影响生产基线，历史版本保留、再点生成新版。

## 信任边界

- 从 Playground 页面启动的外部 Agent 只获得 `playground.use`，不获得任何项目；项目 Agent 不获得 Playground。
  Agent 不能跨域复制 Asset。
- 本机用户启动的外部 Agent 获得当前项目、有限期的 `project.execute` 委托，仅可调用既有 Agent 操作白名单。
  启动不发送任务，询问下一步只读取；具体执行等待用户指令，由外部 Agent 判断意图。Core 校验操作/状态/范围/版本，
  不以 Agent 自报正文授予能力，不开放候选选择、Approval、人类操作或直接项目文件写入。其它部署默认仍使用精确 grant。

- Agent 只能提交类型化 proposal；不能直接写项目文件、选择候选、批准、发布或调用 Provider。
- Web 只消费服务端资源、状态、影响预览和 `allowed_actions`；不得复制状态机或猜测下一步。
- 执行由外部成熟 Agent 承担；Core 不装配厂商 Agent runtime、SDK、CLI 或隐藏 fallback。专业契约位于 `core/director_proposals/`，领域 run/cursor 仍由 Core 持久化。
- Model Provider 是用户安装的 Core 侧插件。每个插件自行调用独立外部 HTTP API，并翻译成 Core 的 Generation 语义。
- 外部服务不实现公共工作流层，也不接收项目语义、任意文件路径、Shell、eval、任意 URL 或任意模型路径。
- Windows、CUDA、盘符、SMB 和模型安装细节不得进入共享领域协议。

## 工程门禁

- 请求与响应 schema 默认拒绝未声明字段；
- 幂等写入校验作用域、幂等键和规范化请求摘要；
- 状态迁移集中定义，路由、UI 和 Adapter 不得直接赋值；
- 任务、取消、游标和产物回收进度必须持久化；
- 重试创建新的 Generation 并保留 `retry_of`；
- 候选生成和候选选择必须分离；
- Asset 以 SHA-256、媒体类型和字节数校验，内容不可变；
- 每条领域规则需要自动化测试，不能测试时在路线图说明原因；
- 重要目录、入口或职责变化必须同步 `STRUCT.md`；
- `core/` 下每个有职责的源码目录必须有简洁 README；Skill 包用 `SKILL.md` 自述；
- 每个里程碑运行静态检查、全量测试（`./scripts/ci_local.sh --full`）、Web build 和 `git diff --check`；
  日常门禁默认跳过 `slow` 标记，合并分支或改动对应模块前必须跑全量；
- Web 删除项目只移入 `.stories/.trash/`。

## Windows 开发节点

- 部署用 SSH 别名、服务地址与 Windows 仓库路径写在 Git 忽略的 `start.local.env`，只用于部署、诊断和紧急维护，不是产品协议；
- 不得记录 SSH 私钥、SMB 密码或 Provider Token；
- LAN HTTP 服务必须绑定指定地址并认证；Token 只能保存在忽略的本机状态目录；
- `default_model_providers_implement/` 是作者自用部署的默认 Provider 实现，随仓库公开作参考，不属于 Core。

## 第三方内容

- 未经批准不引入 OpenMontage、其它项目代码、Skill 原文或 AGPL 内容；
- 公开思想必须重新表达并适配 StoryRail；引入或修改第三方材料时同步登记 `THIRD_PARTY_NOTICES.md`，
  按上游许可证附带协议全文与修改说明。
