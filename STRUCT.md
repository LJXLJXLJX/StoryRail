# StoryRail 目录与依赖

本文精确到文件（测试文件除外）。只做包导出的 `__init__.py` 不逐一列出；承担实际逻辑的
`__init__.py` 单独说明。重要目录、入口或职责变化必须同步本文。

## 依赖方向与分层

执行方向：外部成熟 Agent → MCP/HTTP → Core application/严格命令或 proposal → Store → `project.json`；
媒体生成经 Core → Model Provider adapters → 外部媒体 API。Web 使用同一 Core；Keyframe 候选 Agent 与人类都可采用，其它候选采用与 Approval 仍需
human 权限；明确撤回旁白音频可由 Agent 经窄命令解除引用。

`core/structured_director/` 内部分层（由 `tests/test_layer_rules.py` 守卫，只允许向下依赖）：

| 层 | 位置 | 职责 |
| --- | --- | --- |
| L0 | `models/` | 领域值对象与不变量校验 |
| L1 | `codec/` | 领域对象 ↔ 严格 JSON |
| L2 | `mutations/`、`*_mutations.py` | 纯函数领域变换与失效传播 |
| L3 | `store/` | 唯一持久化入口、revision CAS、原子替换 |
| L4 | `reads/` | 只读投影、影响预览与依赖评估 |
| L6 | `media_submission/` | Provider 请求构造、提交意图与句柄持久化 |
| 边缘 | `service.py`、`http_api.py` | 应用 facade 与 HTTP contract |

项目只需 `project.json` 与不可变 `assets/`。领域 run/cursor/回执在业务 authority 内；外部会话、工作区与
历史 `.runtime/` 不参与恢复事实读取。没有数据库、双写或旧 schema 迁移；当前 schema 为 v35
（Scene 下并列 Shot 与 Segment、Segment 以 `shot_ids` 记录覆盖的 Shot、一个 Segment 可覆盖多个相邻 Shot 且一个 Shot 可跨多个相邻 Segment、旁白 Cue 不带 Shot 锚点、造型为角色图唯一单位与造型设定图、地点库与 Scene/Shot/Keyframe 视图绑定（Shot 视图为软参考）、`workspace_layers` 持久化内容层、创建时选择旁白语言、每种启用语言一套旁白音色、Keyframe 按 Segment 建首尾槽位并按帧选择角色造型、视频保存 `active_recipe` 与按 recipe 隔离的输入簿、Generation 记录提交时的 Provider 快照），更早版本一律拒绝读取，需新建项目。

Core 不包含厂商 Agent adapter、会话、Director loop 或 Agent SDK 依赖；执行由外部成熟 Agent 承担。
Codex/AGY 图片 Provider 及私有图片服务是媒体插件，不是 Agent runtime。产品说明书见 [docs/](docs/README.md)。

## 根目录

- `AGENTS.md`：仓库协作说明、产品规则与工程门禁（Agent 与开发者的首要入口）。
- `README.md`：产品定位与核心优势、运行方式与工程门禁命令；`README.en.md` 为英文概览。
- `STRUCT.md`：本文，目录与文件职责。
- `LICENSE`：Apache License 2.0。
- `THIRD_PARTY_NOTICES.md`：第三方来源与许可证说明；随仓库分发的第三方 Skill 在各自目录附 `LICENSE` 与 `NOTICE`。
- `pyproject.toml`：Python 包、依赖、ruff 与 pytest 配置。
- `start.sh`：本机一键启动 Core/Web，并按开关自启动 Mac、Windows 媒体服务与 Whisper。
- `start.local.env.example`：`start.sh` 本机部署配置模板；实际配置 `start.local.env` 被 Git 忽略（`*.local.env`）。
- `.gitignore`：忽略构建产物、本机状态、`*.local.env` 与 `.stories/` 作品目录。
- `.github/workflows/ci.yml`：与 `scripts/ci_local.sh` 等价的远端门禁。
- `.agents/skills/`：面向开发者 coding Agent 的仓库 Skill；`.claude/skills` 是指向它的软链接。
  `storyrail-provider-plugin/` 指导开发新的媒体 Provider 插件（云端 API 或本地模型服务），含契约导读与经测试的代码骨架。

## core/ — 零运行时第三方依赖的产品 Core

- `core/README.md`：Core 的业务职责与边界总览。

### core/application/ — 调用方授权与持久请求回执

- `README.md`：Application 边界说明。
- `caller.py`：服务端授予的不可变 Caller/MutationGrant、Agent 操作白名单、认证授权与请求摘要。
- `requests.py`：持久化应用请求值对象与提交上下文。

### core/audio_effects/ — 确定性 WAV 截取与后处理

- `README.md`：音频后处理 API、preset 与 DSP 说明。
- `__init__.py`：公开 API 汇总导出。
- `__main__.py`：本地试听 CLI（对 WAV 套用 preset）。
- `models.py`：效果请求、电台参数、时间线事件与结果元数据。
- `presets.py`：preset 名称与参数解析、强度插值。
- `radio.py`：电台/对讲机效果的滤波、压缩、噪声与事件 DSP。
- `service.py`：效果应用入口、确定性记录与选区合并。
- `trim.py`：WAV 截取请求、元数据与实现。
- `wav_codec.py`：PCM WAV 解码与 16-bit 编码。

### core/director_commands/ — 严格命令契约与 Registry

- `README.md`：Director 命令边界说明。
- `__init__.py`：公开命令类型导出（惰性 `__getattr__`）。
- `models.py`：`DirectorCommand`、回执、Keyframe/repair 原子操作及其 parser。
- `registry.py`：命令名 → parser + Store 方法的注册表与执行入口。
- `context_scope.py`：会话目标的只读定位，不授予写入 scope。
- `final_commands.py`：Animatic、Scene 成片、成片候选选择与 Approval 参数。
- `generation_commands.py`：Generation 目标与 wait 参数。
- `narration_commands.py`：旁白 Cue 更新与解除选择参数。
- `run_commands.py`：领域 run 目标与恢复参数。
- `script_operations.py`：脚本 Scene/Shot/Segment 原子操作输入。
- `video_commands.py`：Segment 视频 recipe 输入、提示词、recipe 切换与撤销选择参数。
- `location_operations.py`：地点语义、独立图片、Scene 绑定与人类地点图片选择参数。
- `reference_commands.py`：角色造型新增 / 修改操作参数（`reference.apply_look_operations`）。

### core/director_proposals/ — 专业输入、schema、parser 与 validator

- `README.md`：专业契约目录说明。
- `__init__.py`：各域 proposal 与专业输入类型汇总导出。
- `compiler_intent.py`：类型化意图交接值对象，不是项目事实来源。
- `schema_gen.py`：从 dataclass 生成 proposal JSON Schema、按项目所选旁白语言约束轨道与音色字段并严格解析。
- `professional_contracts.py`：固定专业能力清单与随产品发布的契约读取；给出 Provider 目录时追加当前绑定插件的提示词 Skill（`plugin/` 资源）。
- `wire_fields.py`：脚本、镜头、旁白编辑字段的唯一名字集合。
- `reference_library.py` / `reference_library_codec.py`：引用库（角色卡、旁白身份）proposal 与 parser。
- `script.py` / `script_codec.py`：结构化脚本 proposal、parser 与回改上下文。
- `narration.py` / `narration_codec.py`：旁白审核 proposal 与 parser。
- `keyframe.py` / `keyframe_codec.py`：Keyframe 规划输入/输出、作用域校验、帧策略归一与编译为原子操作。
- `location.py` / `location_codec.py`：地点规划输入与增补式 proposal（局部 key 互引）、严格 parser，以及按当前事实校验归属后编译为 `location.apply_operations` 原子 patch。
- `video_prompt.py`：模型无关的视频提示词 proposal 与严格 parser。

#### core/director_proposals/skills/ — 专业 Skill 资源（纯 Markdown/YAML）

- `README.md`：Skill 资源索引。
- `consistency_instruction.md`：所有内容修改前的一致性工作规则（同时生成到 Web）。
- `storyrail-video-prompt/SKILL.md`：通用视频提示词入口，工作集交付当前插件的专业 Skill。
- `storyrail-consistency-review/SKILL.md`：修改一致性复核 Skill。
- `storyrail-keyframe-planner/SKILL.md`：Segment 关键帧规划 Skill。
- `storyrail-keyframe-planner/references/cinematic-keyframe-design.md`：关键帧设计与帧数选择参考。
- `storyrail-keyframe-planner/references/cinematic-frame-prompting.md`：关键帧画面正文写法。
- `storyrail-location-planner/SKILL.md`：从完整脚本规划地点库与 Scene/Shot 绑定的 Skill。
- `storyrail-location-planner/references/location-bible.md`：地点合并、状态、陈设与主光写法，附 `edit_locations` 操作字段。
- `storyrail-location-planner/references/view-coverage.md`：逐 Shot 机位视图覆盖、正反打、同机位共用与景别视角。
- `storyrail-narration-review/SKILL.md`：旁白审核 Skill。
- `storyrail-narration-review/references/parameter-contract.md`：旁白合成参数（recipe_params 与 seed）契约。
- `storyrail-reference-library/SKILL.md`：角色与声音引用准备 Skill。
- `storyrail-reference-library/references/card-contract.md`：卡片 proposal 契约（含造型字段）。
- `storyrail-reference-library/references/look-sheets.md`：造型增改操作字段与设定图生成方法。
- `storyrail-structured-director-script/SKILL.md`：结构化导演脚本 Skill。
- `storyrail-structured-director-script/references/script-contract.md`：Scene/Shot/Segment 脚本契约。
- `storyrail-structured-director-script/references/cinematic-director-intent.md`：导演视觉判断参考。
- `storyrail-structured-director-script/references/quality-gate.md`：脚本提交前质量门。
- `storyrail-structured-director-script/references/drama-scene-craft.md`：剧情戏的整场设计、情绪杠杆与对白覆盖。

### core/media_assets/ — 与项目和 Playground 都无关的媒体字节工具

- `README.md`：包的职责、无状态与依赖方向说明。
- `__init__.py`：公开 API 汇总导出。
- `media_bytes.py`：媒体字节签名与大小的校验，以及 WAV/MP4 时长读取。
- `filenames.py`：可读资产文件名规范化与上传素材的 label 推导。
- `mp4_frames.py`：从 MP4 box 读取视频轨帧数与时长。

### core/model_providers/ — 媒体能力契约与具体插件

- `README.md`：插件目录约定。
- `boundary.py`：插件句柄、观察结果、产物描述与错误类型。
- `contracts.py`：Core 确定性媒体工具的请求值对象。
- `manifest.py`：语义能力、语义角色、Widget 词汇、manifest DSL 与 `ProviderSnapshot`。
- `recipe.py`：通用 recipe 请求、媒体槽位线上形状、参数 schema 与按 recipe 保存的机制参数。
- `registry.py`：`ProviderRegistry`：已安装插件实例、全局能力绑定、插件设置与按绑定解析的提交准备。
- `image_prompt_skill.py`、`skills/storyrail-image-prompt-writing/SKILL.md`：项目与 Playground 共用的全局图片提示词规范、当前插件指代约定与插件 Skill 目录（`prompt_skill_index`），随图片工作集交付。
- `settings.py`：`.runtime/providers.json` 的严格读写与原子替换。
- `http.py`：插件共享的低级 HTTP 传输与响应校验。
- 每个插件子目录都有 `README.md`（用法与契约）、`provider.py`（请求翻译与 submit/observe/cancel/read_artifact）
  和导出用 `__init__.py`；可绑定的插件另有 `manifest.py`（recipe、槽位、参数、设置）与 `plugin.py`（`plugin_instance` 安装工厂）：
  - `agy_image/`：AGY 图片生成/编辑。
  - `codex_image/`：Codex 图片生成/编辑。
  - `breeze_tts2/`：Breeze TTS 2 音色设计与克隆/导演。
  - `indextts2/`：IndexTTS2.5 参考音色克隆，语速与八维情感由 manifest 声明。
  - `whisper_asr/`：whisper.cpp 参考音频转写。
  - `qwen_image/`：Qwen Image 2.1（NoctQ V4）备选生图/改图，`skills/qwen-image-prompt-writing/` 随插件发布（含官方提示词模板）。
  - `minimax_h3/`：MiniMax H3 插件；`manifest.py`、`plugin.py`、`requests.py`、`contracts.py`、`render.py`，以及 `fl2va/`、`ref2va/` HTTP 实现。
    `prompt_contract.py`、`prompt_codec.py`、`prompt_payload.py`、`prompt_context.py` 负责插件专业格式（`context.shots` 按 Segment 覆盖顺序写入段内切镜软约束），`skills/h3-prompt-writing/` 随插件发布，经 `prompt_skills` 由 `video_prompt` 契约交付。
  - `seedvr2_7b_sharp_fp8/`：SeedVR2 视频超分。
  - `demucs_audio/`：Demucs 人声/背景分离。
  - `stable_audio_3/`：Stable Audio 3 Medium 文生音频，目前只供 Playground。
  - `ffmpeg_audio_remix/`：视频音轨重新混音。
  - `ffmpeg_video_frame/`：按帧号抽帧。
  - `ffmpeg_pano_view/`：2:1 全景按机位确定性裁切为透视 PNG。
  - `ffmpeg_animatic/`：Scene Animatic 动态分镜。
  - `ffmpeg_final_assembly/`：Scene 成片与全片装配。
  - `mock/`：测试用 mock 生成。

### core/playground/ — 全局唯一的媒体实验工作区（schema v2）

- `README.md`：职责、非目标与依赖方向。
- `__init__.py`：公开类型与工具函数汇总导出。
- `models.py`：L0 领域模型与自洽校验（capability/phase 枚举、Asset、run、document）。
- `codec.py`：`playground.json` 的严格编解码（拒绝未知/缺失字段）。
- `parameters.py`：逐能力参数解析、规范化、输入推导与 Ref2VA 标签映射。
- `errors.py`：可映射到 HTTP 的 Playground 领域错误。
- `capabilities.py`：能力目录、输入解析与 Provider 请求构造。
- `lifecycle.py`：run 迁移表、提交失败分类、重试链接与启动恢复。
- `usage.py`：Asset 占用判定（未结束实验的输入）。
- `store.py`：原子持久化、Asset 去重写入与两阶段文件删除、观察缓存、全景裁切输入判定缓存。
- `observer.py`：Provider 观察、取消意图持久化与产物回收。
- `service.py`：锁内串行化写入的应用服务与 Provider 提交。
- `projection.py`：快照与 run/asset 投影、`allowed_actions` 与 Ref2VA 标签。
- `commands.py`：命令信封、请求摘要、持久幂等与命令分派。
- `http_api.py`：Playground HTTP 边缘（路由、请求校验与错误映射）。

### core/project_settings/ 与 core/project_workspaces/

- `project_settings/README.md`：创建时固化的项目设置说明。
- `project_settings/models.py`：`ProjectAspectRatio`（16:9 / 9:16 / 2:1）。
- `project_workspaces/README.md`：项目容器与回收站说明。
- `project_workspaces/store.py`：`.stories/<项目名>-<id>/` 创建、发现、列表与移入 `.trash`。

### core/web_contracts/ — Web 契约声明源

- `README.md`：生成流程说明。
- `snapshot_schema.py`：Core HTTP 快照与设置响应的 JSON Schema。
- `proposal_schema.py`：各 codec 输出 schema 的 TypeScript 类型标注。
- `ts_emit.py`：JSON Schema → TypeScript 类型与结构校验代码。

### core/structured_director/ — schema v35 结构化导演领域

- `README.md`：领域、Store、Service 与 HTTP contract 总览。
- `__init__.py`：公开 Store/Service/HTTP API 与模型（惰性导出）。
- `schema.py`：`PROJECT_SCHEMA_VERSION` 与兼容读取版本常量。
- `errors.py`：revision 冲突等共享领域错误。

应用边缘：

- `service.py`：`StructuredDirectorService` 应用 facade、人工操作入口与 Provider 装配。
- `http_api.py`：`StructuredDirectorHttpApi` 路由表、请求解析与错误策略。
- `http_requests.py`：请求体字段、类型解析与 `JsonResponse`。
- `application_requests.py`：外部应用命令执行，在 Store 提交点附加原子回执。
- `workflow_commands.py`：既有工作流方法的确定性命令入口。
- `production_commands.py`：确定性生产命令分发。
- `manual_commands.py`：UI 手工 Keyframe 值对象转为正式命令。
- `candidate_eligibility.py`：候选可审核性的只读判定。
- `script_index.py`：脚本访问层：Scene 的 Segment 序列与 Segment↔Shot 覆盖关系的只读遍历。

外部 Agent 规划与 run：

- `planning_inputs.py`：外部 Agent 使用的纯专业输入构造。
- `planning_proposals.py`：外部规划 proposal 的提交、复用 Store run 与专业编译。
- `proposal_requests.py`：引用库/脚本/Keyframe/地点外部请求生命周期。
- `proposal_request_guard.py`：proposal 请求的 caller 所有权校验。
- `reference_proposals.py`：首次引用库业务入口。
- `script_proposals.py`：脚本冷启动共用用例。
- `location_proposals.py`：地点规划的项目级工作集、proposal 编译与在规划 run 内的原子落库。
- `external_batches.py`：精确授权的外部批次（Keyframe 波次与地点成套生成）的 start/continue、稳定 batch_id 与执行轮次。
- `keyframe_batches.py`：单个 Keyframe 批次波次的依赖判断与提交。
- `location_batches.py`：地点成套生成批次（`location.generate_set`）的单轮执行：分类当前可提交项并经单项入口的内部提交函数提交。
- `director_steps.py`：确定性生产请求与 Keyframe 共享边界 scope 约束。
- `run_state.py`：DirectorRun 开始、唤醒与默认授权。
- `production_context.py`：Director/Compiler 的只读生产上下文 JSON。
- `prompt_worksets.py`：视频 recipe 的限域工作集、实际输入清单、已保存输入簿与可绑定 Asset；当前图片插件的提示词约定与 Skill。

领域变换（L2）：

- `script_mutations.py`：脚本物化、原子操作、生产期回改与关键帧/视频计划重建。
- `mutations/dialogue.py`：对白 TTS 候选选择、真实 WAV 时序校准与下游视频失效。
- `keyframe_mutations.py`：Keyframe 原子操作（激活、字段、辅助图、绑定、共享/拆分边界）与失效。
- `location_mutations.py`：地点语义、独立图片、Scene 绑定与人类图片选择；地点图片不绑定 Shot/Keyframe，不传播生产失效。
- `video_mutations.py`：Segment 视频计划/提示词/模式变换与校验。
- `repair_mutations.py`：受控 repair patch 与能力缺口报警。

媒体、时序与资产：

- `keyframe_requests.py`：Keyframe 生图的角色造型、前置帧、手工辅助图实际输入映射与提交预览。
- `reference_image_requests.py`：Segment 无时间位置参考图片的角色造型、显式生图输入与提示词编译。
- `reference_image_mutations.py`：参考图片规划及人类选图，保持 recipe 输入簿为唯一选图绑定来源。
- `character_look_requests.py`：造型设定图的身份参考校验、固定版式与提示词编译（固定 2:1，按插件约定写画幅与 4K）。
- `location_requests.py`：独立地点图片生成与全景取景的前置检查、输入映射、名额、提示词编译及批次分类。
- `image_inputs.py`：单次图片调用的输入名额（`MAX_IMAGE_INPUTS`）、优先级去重与超额拒绝；Keyframe 与地点生成共用。
- `image_prompt_style.py`：当前图片插件的输入图指代与画幅句约定。
- `video_contracts.py`：抽帧请求（帧号）与视频输入快照值对象。
- `video_inputs.py`：Segment 视频实际输入、显式对白音频引用草稿与生成门禁、候选适用性与首帧“从上一 seg 抽取”来源。
- `media_submission/dialogue.py`：逐句对白 TTS 提交；有参考音色强制克隆，无参考音色强制 Voice Design。
- `assembly_timeline.py`：Animatic、Scene 成片与全片装配时间线纯计算。
- `dialogue_timing.py`：TTS 前对白时长软提示，以及已选对白 WAV 的真实起点、时长和最晚结束时间投影。
- `narration_timing.py`：旁白 Scene 的尾部画面缓冲、视觉时长、所选语言时间基准（单语真实时长、双语较长一条）与生产基线校准（每次脚本写入自动执行）。
- `asset_metadata.py`：Generation 产物的可读文件名与位置（字节校验见 core/media_assets）。
- `generation_lifecycle.py`：Generation seed、retry 链接、请求签名与恢复判断。
- `generation_observer.py`：Provider 观察、取消意图持久化与产物回收。
- `provider_ports.py`：各媒体能力的 Core 侧窄 Protocol。

#### models/ — L0 领域模型

- `README.md`：拆包说明。
- `__init__.py`：全部模型汇总导出。
- `_shared.py`：枚举（Generation kind/phase/operation 等）与共享校验工具。
- `reference.py`：角色卡、造型（角色图唯一单位）、旁白身份与引用库。
- `script.py`：Scene、Shot、Segment、对白与导演脚本。
- `dialogue.py`：逐句对白音频选择、合成参数、发声起点与脚本 revision 绑定的生产计划。
- `narration.py`：旁白 Cue 与待处理旁白编辑。
- `location.py`：Location（地点）、固定陈设、状态变体、机位视图与地点库（含视图依赖无环校验）。
- `keyframe.py`：Keyframe、Segment 首尾绑定与 Keyframe 计划（含依赖无环校验）。
- `video.py`：Segment 视频计划、按 recipe 保存的媒体输入，以及无时间位置参考图片规划。
- `final.py`：成片装配计划、转场与最终 Approval。
- `generation.py`：`ReferenceGeneration` 与状态迁移。
- `asset.py`：Asset、图片分类、使用原因与删除闭包判定。
- `run.py`：DirectorRun、cursor、指令与命令回执。
- `document.py`：`StructuredDirectorDocument` 根对象与工作区层。
- `validation/README.md`：校验拆分说明。
- `validation/document.py`：文档级跨域校验（引用、计划与脚本一致性）。
- `validation/generation.py`：Generation 按 kind 的字段契约校验。

#### codec/ — L1 严格 JSON 编解码

- `README.md`：拆包说明。
- `__init__.py`：`serialize_document` / `_parse_document` 入口。
- `_shared.py`：严格字段与类型解析工具。
- `document.py`：根文档编解码与 schema 版本分派。
- `asset.py`、`final.py`、`generation.py`、`keyframe.py`、`location.py`、`narration.py`、
  `reference.py`、`run.py`、`script.py`、`dialogue.py`、`video.py`：对应域的 parse/serialize 函数对。

#### mutations/ — L2 纯函数变换

- `README.md`：约定说明。
- `asset.py`：资产登记、派生、删除与挂载。
- `final.py`：成片装配、批准与重开。
- `generation.py`：Generation 目标校验、创建、完成（含抽帧候选登记）、隐藏；设定图候选选为造型图。
- `narration.py`：旁白修改与失效。
- `reference.py`：角色造型新增与修改（Core 分配造型 ID）与写入造型图。
- `run.py`：DirectorRun 状态机。

#### store/ — L3 唯一持久化入口

- `README.md`：Store 说明。
- `__init__.py`：`StructuredDirectorStore` facade：读写、原子替换、revision CAS 与域路由。
- `_domains.py`：域 collaborator 装配。
- `pipeline.py`：统一 mutation commit pipeline。
- `domains/README.md`：域 collaborator 约定。
- `domains/project.py`、`asset.py`、`final.py`、`generation.py`、`keyframe.py`、`location.py`、`narration.py`、
  `reference.py`、`run.py`、`script.py`、`video.py`：对应域的 Store 写入方法。

#### reads/ — L4 只读投影

- `README.md`：只读层说明。
- `video_recipes.py`：视频 recipe 可用性、切换守护、完整时长与 Core 输入标签预览。
- `snapshot_view.py`：完整 Web 快照、`allowed_actions` 与生产可用性投影。
- `location_image.py`：独立地点图片卡的类型、说明、状态、候选、选图、全景取景能力与允许动作投影。
- `workflow_state.py`：主流程阶段、必需下一步、可选推荐动作与门禁投影。
- `semantic_projection.py`：人和 Agent 共源的故事投影；Segment 生产扩展包含其他图片规划、选图状态与实际媒体绑定。
- `professional_worksets.py`：专业能力工作集读取。
- `execution_reads.py`：外部恢复与人类审核衔接的最小状态。
- `read_tools.py`：`project.*` 只读命令分派。
- `impact.py`：命令影响预览（试算不落盘）。
- `dependencies.py`：生产依赖就绪评估。
- `batch_observation.py`：外部批次观察（Keyframe 波次与地点成套生成共用回执/run 骨架）。
- `proposal_observation.py`：外部 proposal 请求观察。
- `common.py`：只读层共享的参数校验与 JSON 投影工具。

#### media_submission/ — L6 媒体提交

- `README.md`：提交层说明。
- `__init__.py`：`MediaSubmissionUseCases` 组合各能力提交。
- `support.py`：画幅、音色设计入口与提交收尾共用逻辑。
- `image.py`：角色/Keyframe 生图与独立地点图片 generate/edit 提交。
- `pano_view.py`：全景查看器取景提交（冻结全景 Asset 与几何快照）。
- `narration.py`：旁白 TTS 提交。
- `audio.py`：资产中心通用音频与角色/旁白音色设计（Breeze TTS 2）提交。
- `video.py`：Segment 视频（FL2VA/Ref2VA）提交。
- `frames.py`：按帧号抽帧（首帧卡与资产中心）与超分提交。
- `animatic.py`：Scene Animatic 提交。
- `assembly.py`：Scene 成片与全片装配提交。

## storyrail_contracts/ — 零依赖共享 wire 契约

- `README.md`：约束说明。
- `errors.py`：Agent-facing HTTP/MCP 错误信封的唯一构造入口。
- `http_edge.py`：媒体上传路径与查询字段的边缘判定。

## server/ — HTTP 装配

- `provider_plugins.py`：按包名和 endpoint 装配附加 recipe 插件，校验包名与实例身份。

- `README.md`：Server 说明。
- `__main__.py`：服务启动入口（参数、Provider 装配、监听）。
- `api.py`：`/api/projects` 与 `/api/playground` 路由、Asset 内容与结构化导演台转发。
- `asset_transfer.py`：项目与 Playground 之间的人类跨域资产复制（唯一同时接触两侧 authority 的模块）。
- `http.py`：HTTP server、请求处理与响应类型。
- `access.py`：受信凭据装配。
- `request_context.py`：传输层只读请求上下文。
- `writer.py`：单写实例租约。
- `local_connection.py`：受信本机 Unix 控制入口与项目连接授权。
- `windows_runtime_lease.py`：对 Windows 媒体服务的控制租约心跳。

## integrations/ — 外围集成

- `README.md`：集成总览。
- `agent_launcher/README.md`：外部 Agent 启动脚本说明。
- `agent_launcher/__main__.py`：构建/复用通用 Agent 镜像、准备隔离容器、检测宿主本机 HTTP 代理并启动所选 Agent。
- `agent_launcher/PROMPT.md`：启动后的项目连接上下文提示。
- `agent_launcher/PLAYGROUND_PROMPT.md`：Playground scope 的启动上下文提示。
- `agent_launcher/Dockerfile`：一次安装全部六种 CLI 的通用 Agent 容器镜像。
- `agent_launcher/dsh-storyrail.cordis.yml`：DeepSeek Harness 的 MCP 配置片段。
- `agent_launcher/client.py`：外部工作区的固定 MCP 客户端；`start --debug` 写入调试模式提示词与标记。
- `agent_launcher/gateway.py`：隔离网络出口、固定 Google API 域名的宿主代理分流与 Core 路由。
- `agent_launcher/clipboard.py`：宿主终端按键触发的图片传输桥。
- `agent_launcher/clipboard_input.py`：容器内临时图片校验与剪贴板发布。
- `storyrail_mcp/README.md`：MCP adapter 说明。
- `storyrail_mcp/__main__.py`：stdio adapter 启动。
- `storyrail_mcp/app.py`：公开 25 个受控工具（外加旧别名），另有 Playground scope 的 5 个工具；大型 proposal 可从
  request ID 唯一确定的工作区 JSON 读取，校验大小与 SHA-256 后再走原 Core 命令。
- `storyrail_mcp/debug_prompt.md`：调试模式提示词（`--debug`），同时注入工作区 AGENTS.md 与 MCP instructions 最前面。
- `storyrail_mcp/playground_tools.py`：Playground scope 的 5 个工具输入模型与命令翻译。
- `storyrail_mcp/bridge.py`：固定地址的无状态 HTTP 翻译。
- `storyrail_mcp/production_tools.py`：生产工具输入 schema 与固定命令翻译，含 Segment 任意内容图片的单卡规划与生成入口。

## web/ — React + TypeScript + Vite 单页应用

- `README.md`：Web 说明。
- `index.html`、`vite.config.ts`、`package.json`、`package-lock.json`、`tsconfig*.json`：构建配置。
- `src/main.tsx`：挂载入口。
- `src/App.tsx`：公共入口 re-export。
- `src/AppView.tsx`：项目路由、Core 状态观察、人工操作与 `allowed_actions` 消费。
- `src/api.ts`：HTTP 客户端（项目、设置、结构化导演台全部接口）。
- `src/StructuredDirectorWorkspace.tsx`：外部 Agent 衔接与单一故事工作台组合。
- `src/ExternalAgentConnect.tsx`：Agent 选择与当前项目启动命令复制。
- `src/DismissibleDialog.tsx`：浮窗的统一 Esc 关闭入口，按显示层级处理嵌套窗口、portal 与顶栏面板。
- `src/provider_settings/SettingField.tsx`：全局设置与 recipe 共用的字段渲染器。
- `src/provider_settings/ProviderSettingsControl.tsx`：顶栏全局 Provider 设置（能力绑定与按 manifest widget 渲染的插件设置）。
- `src/CreativePartnerPrompt.tsx`：导入页创作搭档与方案整理两段提示词的复制入口。
- `src/creativePrompts.ts`：把共用交付格式拼入两段提示词。
- `src/creative-partner-prompt.md`：创作搭档提示词正文（交付格式为占位符）。
- `src/director-plan-convert-prompt.md`：方案整理提示词正文（交付格式为占位符）。
- `src/director-plan-format.md`：两段提示词共用的最终导演方案交付格式。
- `src/MarkdownText.tsx`：导演方案 Markdown 渲染。
- `src/styles.css`：全局样式。
- `src/vite-env.d.ts`：Vite 类型声明。
- `src/api/README.md`：契约生成说明。
- `src/api/location.ts`：地点操作、选择与影响预览的类型化人类请求。
- `src/api/script.ts`：Segment 拆分/合并操作、脚本整卡影响预览的类型化人类请求与解析。
- `src/api/types.ts`、`src/api/validation.ts`：由 `scripts/gen_web_contracts.py` 生成，勿手改。
- `src/api/schema_check.ts`：JSON Schema 子集运行时。
- `src/api/refine.ts`：手写跨字段不变量校验。
- `src/api/projection.ts`：故事投影类型与解析。
- `src/asset_center/AssetCenter.tsx`：资产浏览、导入、按帧号抽帧、通用音频生成、WAV 后处理、视频音轨编辑与 Playground 页签。
- `src/playground/README.md`：Playground 页面、表单、运行流与资产面板说明。
- `src/playground/PlaygroundPage.tsx`：Playground 路由页面、三栏组合、资产面板与 Agent 入口。
- `src/playground/api.ts`：Playground HTTP 客户端与快照/命令校验。
- `src/playground/usePlaygroundScheduler.ts`：可见性感知的 Playground 快照轮询。
- `src/playground/CapabilityList.tsx`：按媒体域分组的能力列表与可用性。
- `src/playground/RunForm.tsx`：recipe 与确定性工具表单、草稿、prefill/fillSlot 与提交。
- `src/playground/forms/common.tsx`：表单公共字段、输入槽与描述列表。
- `src/playground/forms/parameters.ts`：确定性工具的默认参数与客户端校验。
- `src/playground/forms/index.ts`：确定性工具到表单组件的注册表。
- `src/playground/forms/RecipeForm.tsx`：按 recipe 声明渲染参数和媒体槽位，规范化提交参数。
- `src/playground/forms/VideoExtractFrameForm.tsx`：按帧号抽帧表单。
- `src/playground/forms/PanoViewForm.tsx`：全景裁切表单（朝向/视场角预设，只选 `pano_view` 资产）。
- `src/playground/forms/AudioRemixForm.tsx`：音轨重新混音表单。
- `src/playground/forms/AudioEffectForm.tsx`：音频后处理表单。
- `src/playground/forms/AudioTrimForm.tsx`：音频截取表单。
- `src/playground/RunFeed.tsx`：运行流过滤、选择与对比入口。
- `src/playground/RunCard.tsx`：run 卡片、产物预览、备注与链式输入。
- `src/playground/CompareDrawer.tsx`：产物并排对比与参数差异表。
- `src/playground/AssetPanel.tsx`：资产悬浮独立窗口（可拖动标题栏）、导入/删除/跨域复制与选择模式。
- `src/playground/AssetAudioPlayer.tsx`：资产卡片内的紧凑音频播放器，宽度跟随卡片不溢出。
- `src/playground/CopyToProjectDialog.tsx`：复制到项目的项目/分类选择与 revision 重试。
- `src/playground/playground.css`：Playground 页面样式。
- `src/ImagePreview.tsx`：图片放大查看（缩略图触发器 + 深色全图浮层），导演台与 Playground 共用。
- `src/director_workspace/README.md`：工作台说明。
- `src/director_workspace/contracts.tsx`：工作台 props 与动作契约。
- `src/director_workspace/StoryReader.tsx`：Scene/Shot/Segment 阅读与各内容层组合；镜头设计列出覆盖片段，Segment 页列出覆盖镜头与结构修改入口。
- `src/director_workspace/StoryNavigation.tsx`：Scene → Segment 导航、覆盖标签与服务端时长/对白提示。
- `src/director_workspace/NodeEditor.tsx`：脚本节点编辑器；Shot 创作字段、Segment 覆盖区间与延续说明。
- `src/director_workspace/script_draft.ts`：新 Scene 草稿（一个 Shot + 一个覆盖它的 Segment）。
- `src/director_workspace/script_structure.tsx`：新增镜头（并入/新建 Segment）、拆分/合并 Segment 与服务端影响预览。
- `src/director_workspace/references.tsx`：角色卡、造型与造型图弹窗（生成设定图 / 从资产库选）、旁白卡与参考音色。
- `src/director_workspace/location.tsx`、`location.css`：同页地点库、独立图片编辑、Scene 绑定、任意参考图选择与服务端影响预览；全景图片打开 Pannellum 3D 查看器并显式创建子图。
- `src/director_workspace/PanoramaCameraEditor.tsx`：Pannellum 生命周期、全景相机交互，以及 `yaw` / `pitch` / `hfov` 与取景请求的双向同步。
- `web/third_party/pannellum/`：随 Web 分发的 Pannellum MIT 许可证与使用说明；运行时代码由 npm 锁定版本提供。
- `src/director_workspace/narration.tsx`：旁白 Cue 卡片。
- `src/director_workspace/keyframe.tsx`：Segment 首尾帧卡、Ref2VA 其他图片（已选关键帧 / 资产库参考图，排除当前已启用边界）、共享开关、“从上一 seg 抽取”与手动计划弹窗（正文、角色造型、实际提交映射）。
- `src/director_workspace/VideoReferenceImageCard.tsx`：四张无时间位置参考图片子卡片、规划弹窗、候选生成与显式选图。
- `src/director_workspace/RecipeInputsControl.tsx`、`video.tsx`：共享受保护的视频 recipe 草稿，以及 Segment 视频卡（模式、参考素材、候选、超分、抽帧）；首尾帧区与视频卡原子编辑同一份 recipe 输入簿。
- `src/director_workspace/SceneMedia.tsx`：Scene Animatic 与 Scene 成片。
- `src/director_workspace/final.tsx`：全片装配与 Approval。
- `src/director_workspace/generation.tsx`：Generation 候选、状态文案与采样计时。
- `src/director_workspace/shared.tsx`：共用组件（选图/选音频/选视频弹窗、抽帧弹窗、全图查看等）。
- `src/director_workspace/ConsistencyNotice.tsx`、`consistency.ts`：人工保存后的一致性提醒。
- `src/director_workspace/consistency_instruction.ts`：生成的一致性规则文本，勿手改。
- `src/director_workspace/draft_protection.ts`：未保存草稿保护。
- `src/director_workspace/useSnapshotScheduler.ts`：可见性感知的快照轮询。
- `src/director_workspace/clipboard.ts`：复制到剪贴板。
- `src/director_workspace/story_reader.css`：工作台样式。

## default_model_providers_implement/ — 默认媒体服务参考实现（独立部署，不属于 Core）

- `README.md`：部署、资源调度与各 worker 说明。
- `server.py`：HTTP 任务服务（submit/observe/cancel/artifact）与 runner 装配。
- `resource_manager.py`：单个 lane 的互斥/定并发调度、同族驻留、切换释放与排队位置。
- `lane_dispatcher.py`：进程内多 lane 路由（lane 内 FIFO 与并发上限，lane 间互不等待）。
- `runners.py`：常驻 JSONL runner 与各模型 runner 工厂。
- `controller_lease.py`：Core 控制租约与失联释放。
- `task_store.py`：任务记录持久化（`runtime-state.json`）。
- `request_builders.py`：各路由请求校验与任务目录写入。
- `strict_json.py`：严格 JSON 字段解析。
- `sampling_progress.py`：采样步速与剩余时间估算。
- `h3_request.py`：H3 runtime 内部请求 v5 的严格解析（任务目录内文件、20/8 步、Sage/SelfLift 开关、32 网格画布、17k+5 帧）。
- `comfy_core/README.md`、`comfy_core/runtime.py`、`comfy_core/worker.py`：固定图 Comfy Core 运行时（通用初始化与 H3 FL2VA/Ref2VA 执行）与 JSONL 入口（H3 或 Qwen Image）。
- `comfy_core/graph.py`：按 mode → 步数/权重 → 注意力 → SelfLift 现场构造并校验 H3 节点图。
- `comfy_core/qwen_image.py`：Qwen Image 2.1（NoctQ V4）固定节点图、进度映射与 Comfy Core 执行。
- `qwen_image_request.py`：Qwen Image runtime 内部请求的严格解析（任务目录内图片、32 网格画布）。
- `indextts2_worker.py`：IndexTTS2.5 独立 WSL JSONL worker，中英语言、语速与八维情感。
- `breeze_tts2_worker.py`：Breeze TTS 2 桥接 worker（按需拉起 WSL API）。
- `seedvr2_worker.py`：SeedVR2 超分常驻 worker。
- `codex_worker.py`、`agy_worker.py`：Codex / AGY 图片 worker（Mac）。
- `ffmpeg_video_frame_worker.py`：按帧号抽帧（Mac）。
- `ffmpeg_pano_view_worker.py`：全景透视裁切，FFmpeg `v360`（Mac）。
- `ffmpeg_animatic_worker.py`、`ffmpeg_final_assembly_worker.py`：Animatic 与成片装配渲染。
- `demucs_audio_worker.py`、`ffmpeg_audio_remix_worker.py`：音轨分离与重新混音（Mac）。
- `stable_audio_3_worker.py`：Stable Audio 3 Medium 一次性生成（Windows 服务通过 WSL 调用）。
- `requirements-codex-image.txt`：私有图片服务依赖。
- `macos/install_launch_agent.sh`、`macos/launch-agent.plist.template`、`macos/run_codex_server.sh`：Mac 媒体服务 LaunchAgent 安装与启动。
- `macos/install_demucs.sh`：Demucs 独立虚拟环境安装。
- `windows/install_scheduled_task.ps1`、`uninstall_scheduled_task.ps1`：Windows 计划任务安装与卸载。
- `windows/run_server.ps1`：Windows 服务启动。
- `windows/service_status.ps1`、`windows/stop_services.ps1`：状态查看与停止。
- `windows/run_breeze.ps1`：单独启动 Breeze API。
- `windows/configure_h3_defender_exclusions.ps1`：H3 权重的 Defender 排除项。
- `windows/run_ref2va_acceptance.ps1`：Ref2VA 真机验收。

## scripts/ — 开发工具与验收脚本

- `README.md`：脚本索引。
- `ci_local.sh`：本地一键工程门禁。
- `gen_web_contracts.py`：生成 Web 契约（`--check` 检查漂移）。
- `check_fixture_freshness.py`：Web fixture 新鲜度门禁。
- `check_doc_links.py`：文档相对链接检查。
- `metrics.py`：工程指标测量（模块规模、依赖、门禁耗时、Agent 驻留字节）。
- `benchmark_project_storage.py`：临时目录内的项目存储基准。
- `seedvr2_upscale_acceptance.py`、`ref2va_acceptance.py`：真实媒体服务验收。
- `harness/README.md`：开发期 harness 总入口（产品代码不得 import）。
- `harness/benchmark/README.md`：token benchmark 说明。
- `harness/benchmark/fake_agent_driver.py`：真实 MCP + 真实 Core 的确定性 fake Agent。
- `harness/benchmark/meter.py`：MCP 线上字节计量。
- `harness/benchmark/report.py`：benchmark 报告与防回归门禁。
- `harness/benchmark/scenarios/*.json`：reference / script / location / keyframe / h3 / ref2va 六个场景脚本。
- `harness/benchmark/baselines/token-bench.json`：token 防回归冻结值（oracle 测试与手动 `report.py --check` 读取）。
- `harness/benchmark/baselines/agent-tokens-2026-09-11.json`：历史 Agent 单轮 token 基线（`metrics.py` 读取）。
- `harness/fixtures/media.py`：确定性合成 PNG/WAV。
- `harness/fixtures/synthetic_media.py`：合成媒体 Provider 与 registry 装配。
- `harness/fixtures/candidates.py`：把已有项目图片按正式 Generation 生命周期登记为成功候选（fixture 选择视图用）。
- `harness/probes/README.md`：合成部署验收说明。
- `harness/probes/run.py`：受信宿主控制器（合成 Docker 资源）。
- `harness/probes/provision.py`：一次性合成 volume 初始化。
- `harness/probes/core_fixture.py`：合成 volume 的 Core 服务。
- `harness/probes/agent_probe.py`：Agent 内拓扑检查。
- `harness/probes/native_agent.py`：真实 Pi 原生工具验收（假模型）。
- `harness/probes/human_gateway.py`：临时 Chrome 验收页面。
- `harness/real_agent/README.md`：真实 Agent 验收说明（opt-in）。
- `harness/real_agent/run.py`：隔离资源共用工具。
- `harness/real_agent/external_run.py`：真实 Agent 验收控制器。
- `harness/real_agent/external_agent.py`：原生 Pi 启动器。
- `harness/real_agent/external_core.py`、`core_server.py`：只有合成 Provider 的验收 Core。
- `harness/real_agent/external_client.py`、`mcp_client.py`：验收用 MCP 客户端。
- `harness/real_agent/prompt_fixture.py`：原创合成项目。
- `harness/real_agent/workspace_browser_fixture.py`：仓库外临时项目的正式导演台浏览器验收夹具，合成图片/全景裁切 Provider。
- `harness/real_agent/meter_gateway.mjs`：宿主计量网关。
- `harness/real_agent/docker/Dockerfile`、`clean_install.Dockerfile` 及对应 `.dockerignore`：验收镜像。

## docs/ — 产品说明书

只描述当前产品行为与技术实现；施工过程记录放 `wip/`（见 AGENTS.md「文档与施工记录」）。

- `README.md`：文档索引、全局图与术语。
- `product.md`：产品定位、核心概念、能力、人工控制边界、非目标。
- `architecture.md`：进程与模块、分层、authority 划分、单写与并发、持久状态布局。
- `data-model.md`：`project.json` v34 实体关系、字段约束（含地点库、对白 TTS 与失效规则）、Asset 落盘、Generation、DirectorRun、ApplicationRequest。
- `production-workflow.md`：逐阶段的触发者、输入、产出与门禁。
- `control-flow.md`：身份授权、命令分发、原子回执、Generation 生命周期（含确定性工具）、proposal、Keyframe 与地点成套批次、恢复。
- `data-flow.md`：旁白时序、地点图片/Keyframe/H3 输入编译、Scene 成片与最终装配、失效传播、资产使用与删除。
- `commands.md`：全部 Core 命令与调用方。
- `external-agents.md`：本机一键接入、授权模型、隔离拓扑、MCP 工具、专业能力、主流程读取。
- `error-contract.md`：Agent 错误信封与恢复策略。
- `business-state-protection.md`：业务状态保护与 break-glass 规则。
- `playground.md`：Playground 规格。
- `providers-and-deployment.md`：Provider 插件、全局设置、默认部署拓扑、`start.sh` 与工程门禁。

`wip/`（按需存在，Git 忽略，只在本机）：进行中的施工记录（计划、任务卡、决策、验收、基准对比）；完成后结论并入 `docs/` 并删除。

## 其它

- `tests/provider-behavior-contract.md`：当前媒体插件与领域功能规则、实现位置及自动化守护。
- `tests/`：全量回归（`conftest.py` 公共工厂、`provider_factory.py`、`fixtures/` 与 `oracle/` 场景），不逐一列出。
