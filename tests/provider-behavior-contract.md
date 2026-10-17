# Provider 行为与自动化守护

本文列出当前插件与领域规则的实现位置和测试。规则编号用于稳定定位；项目 schema 为 v31，Playground 为 v2。

黄金请求 `golden/provider_requests/{project,playground}.json` 由 `test_golden_provider_requests.py` 逐字节校验；媒体字节规范化为标签、SHA-256 与字节数。协议或状态测试使用合成媒体，不代表真实推理或音质验收。

## 全局设置与能力绑定

实现：`core/model_providers/{registry,settings,manifest}.py`；`web/src/provider_settings/`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| A1 | 全局 image.generate / image.edit 能力可分别绑定 Codex、AGY 或 Qwen Image；设置持久化，只影响新提交。 | `core/model_providers/registry.py`、`settings.py` | `test_provider_settings.py::test_binding_persists_and_new_submissions_use_bound_plugin`、`::test_provider_settings_http_is_strict_and_persistent`、黄金 `settings.image_provider_agy` |
| A2 | 历史 Generation 按句柄 plugin_id 与版本回到原实现观察、取消和回收。 | `core/model_providers/registry.py`、`settings.py` | `test_provider_settings.py::test_history_routes_by_handle_after_global_switch`、`test_provider_registry.py` |
| A3 | 未知能力、未安装或不实现能力的插件、未知句柄均拒绝。 | `core/model_providers/registry.py`、`settings.py` | `test_provider_settings.py::test_binding_rejects_unknown_capability_plugin_and_handle`、`::test_binding_to_uninstalled_plugin_makes_capability_unavailable` |
| A4 | H3 实例设置声明 480p/720p/1080p、Hybrid 20 步/Turbo 8 步、SageAttention 和 SelfLift；严格字段与持久化。 | `core/model_providers/minimax_h3/manifest.py`、`render.py` | `test_provider_settings.py::test_settings_validation_is_exact_and_typed`、`::test_h3_preset_binds_base_model_and_steps`、`::test_provider_settings_http_is_strict_and_persistent`、黄金 `settings.h3_turbo_1080p` 与 Playground 480p/1080p 步骤 |
| A5 | H3 画布由插件按画幅/分辨率计算，采用 32 像素网格，边长 ≤1920、像素 ≤2.1M。 | `core/model_providers/minimax_h3/manifest.py`、`render.py` | `test_provider_settings.py::test_h3_render_canvas_tiers_follow_the_32_pixel_grid`、黄金（9:16/2:1/16:9 × 480p/720p/1080p 中的 6 组） |
| A6 | 项目与 Playground 共用实例设置，每次提交读取当前值；改设置不失效已有候选。 | `core/model_providers/registry.py`、`settings.py` | 黄金（改设置后新提交才变化）、`test_workflow_gates.py` |
| A7 | 仅人类可修改全局能力绑定与插件设置；Agent 只读。 | `server/api.py`、`core/application/caller.py` | `oracle/test_oracle_permission_boundary.py`（Agent PUT 设置 → `scope_denied`）、`test_application_access.py`（设置路由白名单） |
| A8 | Web Provider 设置页按 manifest 渲染绑定与完整设置，并说明只影响新任务。 | `web/src/provider_settings/ProviderSettingsControl.tsx` | `provider_settings/ProviderSettingsControl.test.tsx` |
| A9 | 无可用绑定时不开放对应入口，提交返回 provider_unavailable。 | `core/model_providers/registry.py`、`settings.py` | `test_playground_capabilities.py`、`test_http_api_route_matrix.py` |
| A10 | Generation 保存句柄版本，provider_snapshot 保存插件实例、recipe 与提交时生效设置。 | `core/model_providers/registry.py`、`settings.py` | 黄金项目测试断言 `provider` 快照、`test_provider_settings.py::test_snapshot_round_trips_and_rejects_unsorted_settings` |

## 视频

实现：`core/structured_director/{models/video.py,reads/video_recipes.py,media_submission/video.py}`；`core/model_providers/minimax_h3/`；`web/src/director_workspace/video.tsx`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| B1 | SegmentVideo 保存 active_recipe 与按 recipe 保存的 recipes 输入簿。 | `core/structured_director/models/video.py`；`core/model_providers/recipe.py` | `test_models_validation.py`、`test_document_persistence_contract.py`、`test_video_recipe_projection.py` |
| B2 | 默认视频 recipe 由 manifest.defaults 与 segment.has_dialogue 领域谓词决定；解锁、回改和重建一致。 | `core/model_providers/registry.py`；`core/structured_director/workflow_commands.py`、`script_mutations.py` | 黄金断言 `modes == {...}`、`test_workflow_gates.py` |
| B3 | 切换至相同 recipe 为 noop；改变 recipe 清除视频/超分选择并作废装配；活动任务阻止切换。 | `core/structured_director/store/domains/video.py`；`reads/video_recipes.py` | `test_director_commands.py::test_video_prompt_mode_and_clear_commands_preserve_history_and_scope`、`test_video_recipe_projection.py` |
| B4 | 已填的引用输入必须兼容目标 recipe；切换失败给出 Core 原因，Web 消费其选项。 | `core/structured_director/store/domains/video.py`；`reads/video_recipes.py` | `test_director_commands.py::test_video_set_plan_video_references_strict_persisted_and_mode_guarded`、`video.test.tsx`、`test_video_recipe_projection.py` |
| B5 | recipe 切换提供只读影响预览。 | `core/structured_director/reads/impact.py` | `test_impact_preview.py` |
| B6 | 引用槽位与机制参数属于各自 recipe，不作为 Segment 的模型专用字段。 | `core/structured_director/models/video.py`；`core/model_providers/recipe.py` | `test_models_validation.py`、`test_video_recipe_projection.py` |
| B7 | H3 Ref2VA 声明最多 4 张附加图、不重复、必填说明 ≤2000 字。 | `core/model_providers/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_director_commands.py`、`video.test.tsx`“Ref2VA 在首尾帧右侧…必填描述” |
| B8 | H3 Ref2VA 声明 0–8 条 WAV 参考音频、不重复、必填说明、不限时长。 | `core/model_providers/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_prompt_worksets.py::test_ref2va_submits_additional_images_without_reference_audio`、`::test_ref2va_reference_audio_has_no_duration_limit`、黄金 Playground `video.ref2va.no_audio` |
| B9 | H3 Ref2VA 声明 0–3 条 MP4 参考视频、2–15 秒、不重复、必填说明；不引入其音轨。 | `core/model_providers/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_workflow_gates.py::test_video_reference_gate_checks_mp4_duration_window`、`test_prompt_worksets.py::test_ref2va_submits_reference_videos_with_lineage`、`video.test.tsx`“Ref2VA 参考视频只列 2–15 秒 MP4…”、“达到 3 条上限…” |
| B10 | 输入媒体类型、时长或数量不满足 slot 声明时，Core 返回阻止原因。 | `core/structured_director/reads/dependencies.py`、`video_recipes.py` | `test_workflow_gates.py`、`test_video_recipe_projection.py` |
| B11 | Core 按 manifest 的槽位顺序与 namespace 编号；H3 Picture 连续编号，Audio/Video 各自从 1 起，与 Provider 顺序一致。 | `core/structured_director/reads/video_recipes.py`、`prompt_worksets.py`；`core/model_providers/recipe.py` | `test_prompt_worksets.py::test_video_labels_number_independently_and_map_to_provider_order`、`::test_single_boundary_labels_follow_actual_enabled_slot`、`test_playground_capabilities.py::test_ref2va_labels_match_production_mapping`、黄金（输入顺序）、`test_video_recipe_projection.py` |
| B12 | 启用的首尾帧从 Keyframe 计划取已选图；FL2VA 的 require_any 声明至少一帧，Ref2VA 不要求图片但全部媒体槽位至少一项。 | `core/structured_director/video_inputs.py`、H3 manifest 与默认实现 | `test_structured_director_keyframe.py`、`test_workflow_gates.py`、`test_playground_capabilities.py`、黄金（单帧/双帧/无图片） |
| B13 | 空提示词在持久化生成意图前拒绝；Core 原样提交已保存正文，不调用 Agent。 | `core/structured_director/media_submission/video.py` | `test_video_recipe_projection.py::test_empty_prompt_rejects_video_before_generation_intent`、黄金 `direction`/`prompt` 字段 |
| B14 | 视频时长取 Segment 的有限值且 ≥0.2 秒；H3 不设上限。 | `core/model_providers/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_provider_contracts.py::test_h3_requests_have_no_duration_upper_limit`、黄金 16.5 秒 |
| B15 | H3 hints 声明 15 秒软约束；工作集与 Web 提示可能 OOM，Core 不硬拦截。 | `core/structured_director/reads/video_recipes.py`、`prompt_worksets.py`；`core/model_providers/recipe.py` | `test_prompt_worksets.py::test_segment_over_soft_duration_limit_is_flagged_but_still_submitted` |
| B16 | 视频 seed 显式指定或按 Segment ID 派生；每 kind/target 递增，失败/取消/隐藏消耗种子，重试复用原值。 | `core/structured_director/generation_lifecycle.py`、`media_submission/video.py` | `test_structured_director_generation.py::test_seed_increments_per_target_and_kind_including_failed_attempts`、黄金（默认 seed 规则、重试 3001） |
| B17 | H3 插件固定 cfg 1.0 与输出音轨开关，项目和 Playground 一致。 | `core/model_providers/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | 黄金 |
| B18 | 输入签名覆盖 recipe、槽位、说明、提示词、时长与画幅；变化仅给 inputs_outdated 软提示，不阻止选择/超分/装配。 | `core/structured_director/video_inputs.py`、`candidate_eligibility.py` | `test_workflow_gates.py::test_input_changed_segment_video_candidate_stays_selectable_with_soft_hint` |
| B19 | Generation.input_asset_ids 按实际槽位顺序去重保存血缘。 | `core/structured_director/media_submission/video.py` | `test_prompt_worksets.py::test_ref2va_submits_reference_videos_with_lineage` |
| B20 | Keyframe 改选仅失效实际依赖的 Segment 视频、超分与装配。 | `core/structured_director/mutations/`；`reads/dependencies.py` | `oracle/test_oracle_invalidation.py` |
| B21 | 视频卡保留编辑授权、草稿保护、Core 首尾帧标签、声明式输入与候选列表。 | `web/src/director_workspace/video.tsx`；`core/structured_director/reads/video_recipes.py` | `video.test.tsx` 全部、`draft_protection.test.tsx` |
| B22 | Web 显示 Core 下发的完整本次视频时长。 | `web/src/director_workspace/video.tsx`；`core/structured_director/reads/video_recipes.py` | `video.test.tsx`“本次视频时长直接显示 Core 预览值，超过十秒保持完整”、黄金 16.5 秒 |
| B23 | 视频卡首尾帧与附加输入标签均来自 Core。 | `web/src/director_workspace/video.tsx`；`core/structured_director/reads/video_recipes.py` | `video.test.tsx`、`test_video_recipe_projection.py` |

## 语音

实现：`core/structured_director/{models/narration.py,media_submission/audio.py,media_submission/narration.py}`；`core/model_providers/breeze_tts2/`；`web/src/director_workspace/narration.tsx`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| C1 | 音色设计由 Core 提供 voice_description、sample_text 与 seed；描述映射 prompt 角色。 | `core/structured_director/media_submission/audio.py`；`web/src/asset_center/AssetCenter.tsx` | `test_golden_provider_requests.py`、`StructuredDirectorWorkspace.test.tsx` |
| C2 | 旁白身份中英各一套描述、参考 WAV 与完整文字稿；英文设计和候选按语言隔离。 | `core/structured_director/models/reference.py`、`media_submission/audio.py` | `test_golden_provider_requests.py`、`test_structured_director_narration.py` |
| C3 | 旁白 TTS 只用同语言参考音色；缺该语言音色或文字稿时拒绝。 | `core/structured_director/media_submission/narration.py` | `test_structured_director_narration.py` |
| C4 | 旁白轨道 recipe_params 保存机制参数；Breeze 的 performance_instruction 是 ≤200 字或 null 的 recipe 字段。 | `core/model_providers/breeze_tts2/manifest.py`、`provider.py` | `test_performance_instruction.py`、`test_recipe.py` |
| C5 | 改变某语言 recipe 参数失效该语言的已选音频。 | `core/structured_director/mutations/narration.py` | `test_performance_instruction.py::test_review_proposal_writes_instruction_and_invalidates_selection` |
| C6 | 旁白 seed 按语言各自递增，重试复用原值。 | `core/structured_director/media_submission/narration.py` | `test_structured_director_generation.py`、`test_golden_provider_requests.py` |
| C7 | 资产中心音色设计与克隆使用不同 recipe；互斥领域输入与未知字段严格拒绝。 | `core/structured_director/media_submission/audio.py`；`web/src/asset_center/AssetCenter.tsx` | `test_asset_audio_generation.py`、`StructuredDirectorWorkspace.test.tsx` |
| C8 | Breeze 插件固定 cfg_scale 4.0；正文 ≤20000、instruction ≤4000，克隆要求参考文字稿。 | `core/model_providers/breeze_tts2/manifest.py`、`provider.py` | `test_breeze_tts2_provider.py`、`test_recipe.py`、`test_golden_provider_requests.py` |
| C9 | Breeze 异步 API 明确返回 400/404/405/415 时回退官方同步 API，PCM 保存为可观察/回收的 WAV 句柄。 | `core/model_providers/breeze_tts2/manifest.py`、`provider.py` | `test_breeze_tts2_provider.py` |
| C10 | 旁白卡正文与 seed 是领域控件，机制参数按当前 speech recipe 的 editable_params 渲染。 | `web/src/director_workspace/narration.tsx`；`provider_settings/SettingField.tsx` | `director_workspace/narration.test.tsx`、`StructuredDirectorWorkspace.test.tsx`、`RunForm.test.tsx` |
| C11 | 选择角色参考音色不改写显式保存的视频音频引用。 | `core/structured_director/store/domains/reference.py` | `test_director_commands.py::test_reselecting_character_voice_does_not_change_explicit_audio_references` |

## 图片

实现：`core/structured_director/media_submission/image.py`、`image_prompt_style.py`；`core/model_providers/{codex_image,agy_image,qwen_image}/`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| D1 | Codex/AGY 插件固定图片 model，声明生图 ≤5 张参考、改图底图加 ≤4 张参考，接受 PNG/JPEG/WebP。 | `core/model_providers/codex_image/manifest.py`、`provider.py`；`agy_image/` | `test_provider_contracts.py::test_image_*`、黄金 |
| D2 | Keyframe 编译将输入图对应关系置顶，画幅只编译一次，edit 底图在首位。 | `core/structured_director/media_submission/image.py`；`core/structured_director/keyframe_requests.py` | `test_structured_director_keyframe.py`、`test_keyframe_semantics.py`、黄金 `keyframe.generate`（instruction 全文） |
| D4 | Keyframe 显式声明地点视图 edit/reference/none（建帧继承 Shot 视图写成显式值）、角色参考子集、辅助图和前置边界帧；名额顺序视图→角色参考→前置帧→辅助图，超过 5 张拒绝并列出被挤掉的输入；视图未选图时拒绝生成。 | `core/structured_director/media_submission/image.py`；`core/structured_director/keyframe_requests.py`、`image_inputs.py` | `test_keyframe_location_views.py`、`test_keyframe_character_references.py`、`test_structured_director_keyframe.py`、黄金 |
| D5 | 角色图生成支持参考图；产物必须显式 attach 才进入卡片。 | `core/structured_director/media_submission/image.py`；`core/structured_director/keyframe_requests.py` | `test_reference_library.py`、黄金 `character.image_generate` |
| D6 | 图片插件 manifest 的 `image_prompt` 约定决定输入图指代与画幅句：Qwen 用 `<imageN>`、单图称“图片”、不写画幅；未声明的插件保持默认中文编号与画幅句。约定必须覆盖每个图片 recipe 的全部槽位。 | `core/model_providers/manifest.py`；`core/structured_director/image_prompt_style.py`、`keyframe_requests.py` | `test_qwen_image_provider.py::test_keyframe_prompt_uses_plugin_labels_and_omits_aspect_sentence`、`::test_single_input_image_is_called_picture_without_label`、`::test_prompt_convention_must_cover_every_image_slot`、`::test_codex_image_generations_keep_no_seed` |
| D7 | 声明 Seed 角色的图片 recipe 由 Core 分配 seed：目标 ID 派生起点、同目标每次提交递增、重试沿用原值，并记录实际机制参数；未声明的插件不记 seed。 | `core/structured_director/media_submission/image.py`、`generation_lifecycle.py`、`models/validation/generation.py` | `test_qwen_image_provider.py::test_core_assigns_new_seed_per_submission_and_retry_keeps_it`、`test_models_validation.py` |
| D8 | Qwen 插件全局设置声明分辨率档位、CFG、步数与负向提示词；画布长边取档位、短边按比例对齐 32，显式宽高须同时填写；改图底图在输入首位；HTTP 请求、状态、取消、产物与句柄严格校验。 | `core/model_providers/qwen_image/` | `test_qwen_image_provider.py::test_canvas_*`、`::test_explicit_size_*`、`::test_edit_request_*`、`::test_invalid_size_*`、`::test_provider_wire_*` |
| D9 | Windows `qwen_image` 服务封闭请求、只解析任务目录内图片、固定节点白名单图与单调进度。 | `default_model_providers_implement/{request_builders.py,qwen_image_request.py,comfy_core/qwen_image.py,server.py,runners.py}` | `test_qwen_image_provider.py::test_prepare_*`、`::test_internal_request_*`、`::test_fixed_graph_*`、`::test_progress_*` |
| D10 | Keyframe 规划工作集交付当前图片插件约定与随插件 Skill（同名只附一次）。 | `core/structured_director/prompt_worksets.py`、`reads/professional_worksets.py`；`core/model_providers/qwen_image/plugin.py` | `test_qwen_image_provider.py::test_image_prompt_guide_delivers_skill_once` |
| D11 | 图片比例词汇在 Core、Mac 服务、Codex worker 与 MCP 一致；Keyframe 不带比例，造型设定图与室内地点主图固定 2:1。 | `core/model_providers/manifest.py`；`default_model_providers_implement/strict_json.py`、`codex_worker.py`；`integrations/storyrail_mcp/production_tools.py`；`models/validation/generation.py` | `test_image_aspect_ratios.py::test_aspect_ratio_vocabulary_is_identical_everywhere` |
| D12 | 造型是角色图的唯一单位：Keyframe 按造型选择（`look_id`，null 不提交）；单套默认、多套必须选择、所选造型无造型图时拒绝；删除造型剪除 Keyframe 选择；改选造型图不改写 Keyframe；整卡保存只改造型文字并沿用已有造型图。 | `core/structured_director/keyframe_requests.py`、`models/keyframe.py`、`mutations/reference.py`、`store/domains/asset.py` | `test_keyframe_character_references.py`、`test_character_looks.py::test_human_card_update_assigns_ids_keeps_images_and_rejects_invented_ids` |
| D13 | 地点主图：室内以 2:1 提交等距柱状全景（写明无人物、左右边缘无缝、陈设与主光按方位描述），室外跟随项目画幅；记录 `provider_snapshot`、按插件声明分配 seed、重试沿用；回调只保存候选，室内主图选择必须满足全景裁切输入契约。 | `core/structured_director/location_requests.py`、`media_submission/image.py`、`store/domains/location.py` | `test_location_generation.py::test_interior_master_*`、`::test_exterior_master_*`、`::test_master_retry_*`、黄金 `location.master_generate` |
| D14 | 地点视图：室内无与当前主图和几何一致的裁切时只提交 `pano_view`（冻结主图与绝对机位），回调快照仍为当前值才写 `crop_asset_id`；再次显式生成才提交细化 edit（底图=裁切图，参考=主图+参考视图已选图）；室外 edit 转向（底图=主图，Core 写转向角、俯仰与景别）；输入 ≤5 张，超出列出被挤掉的输入。 | `core/structured_director/location_requests.py`、`media_submission/image.py`、`media_submission/pano_view.py`、`mutations/generation.py` | `test_location_generation.py`、黄金 `location.view_crop` / `location.view_refine` / `location.view_turn` |
| D15 | 造型设定图：只接收造型 ID 与 ≤ 4 张显式身份参考，固定 2:1 提交；提示词由 Core 编译（主体描述在前；柔和浅灰底单一版式，不含只属于人的措辞，要求非人生物按真实生物绘制、不画所处环境），人类可预览并提交编辑过的完整提示词，画幅由画布保证的插件不写画幅与 4K 句，其余插件写；重试原样沿用提交时的提示词与身份参考；人类选择设定图候选或资产库图片作为造型图；Agent 可增改造型与生成，不能选择。 | `core/structured_director/character_look_requests.py`、`media_submission/image.py`、`mutations/generation.py`、`mutations/reference.py`；`core/application/caller.py`；`integrations/storyrail_mcp/production_tools.py` | `test_character_looks.py` |

## 超分、音频与识别

实现：`core/structured_director/media_submission/`；对应模型插件包；`core/media_assets/mp4_frames.py`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| E1 | 超分只对已选原视频提交，每 Segment 单次；SeedVR2 固定短边 720/长边 ≤1280；Scene 成片优先超分。 | `core/structured_director/media_submission/frames.py`；对应超分/抽帧实现 | `test_seedvr2_provider.py`、`test_final_scene_assembly.py`、黄金 `video.upscale` 与成片 clips |
| E2 | 项目音轨分离显式提交 voice 与 background 两个语义 stem；Playground 每次选一条。 | `core/structured_director/service.py`；`core/model_providers/demucs_audio/` | `test_video_audio_editor.py`、`test_video_audio_providers.py`、黄金 |
| E3 | 确定性混音增益 −100–24 dB，窗口起止成对提供。 | `core/model_providers/contracts.py`、`ffmpeg_audio_remix/` | `test_provider_contracts.py::test_audio_remix_request_*`、黄金 |
| E4 | Stable Audio 3 文生音频使用 prompt ≤1000、时长 1–380 秒与 seed，只供 Playground。 | `core/model_providers/stable_audio_3/`；`core/playground/capabilities.py` | `test_stable_audio_3_provider.py`、黄金 `audio.generate` |
| E5 | Whisper ASR 接受 WAV 与 auto/zh/en，同步返回文字，不产生 Asset。 | `core/model_providers/whisper_asr/`；`core/structured_director/service.py` | `test_whisper_asr_provider.py`、黄金 multipart |
| E6 | 抽帧按帧号 0…N−1（Core 从 MP4 读取），首帧卡产物仅作候选，不自动选择。 | `core/structured_director/media_submission/frames.py`；对应超分/抽帧实现 | `test_video_frame_extraction.py`、`test_mp4_frames.py`、黄金 |

## 确定性工具

实现：`core/structured_director/{assembly_timeline.py,media_submission/assembly.py,media_submission/animatic.py}`；对应 FFmpeg 工具包。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| F1 | 确定性 Scene/最终装配保持 0.1 秒共享边界 seam_blend、旁白对轨和中英各一版；设置页仅展示工具状态。 | `core/structured_director/media_submission/assembly.py`；`assembly_timeline.py` | `test_final_scene_assembly.py`、`test_ffmpeg_final_assembly.py`、黄金 `final.assembly` |
| F2 | Animatic 按已选关键帧平分 Segment 时长并使用成片旁白对轨。 | `core/structured_director/media_submission/animatic.py` | `test_ffmpeg_animatic.py`、黄金 `scene.animatic` |
| F3 | 全景裁切只接受 2:1（±1 像素）、宽 1024–16384 的 PNG/JPEG 等距柱状全景；yaw ∈ [0, 360) 自全景正中顺时针、pitch ∈ [−60, 60] 抬头为正、hfov ∈ [20, 120]、画幅限项目画幅，Core 契约与媒体服务各校验一次；输出长边 2048、v_fov 按透视公式换算，同输入逐字节相同。 | `core/model_providers/contracts.py`、`ffmpeg_pano_view/`；`default_model_providers_implement/ffmpeg_pano_view_worker.py`、`request_builders.py` | `test_provider_contracts.py::test_pano_view_request_*`、`test_ffmpeg_pano_view.py`（真实 v360 方位、画幅与 SHA-256 确定性、服务闭环） |

## 生成生命周期

实现：`core/structured_director/{generation_lifecycle.py,generation_observer.py,service.py}`；各插件实现。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| G1 | 生成意图先持久化；提交不确定不自动重发，重启按句柄恢复观察。 | `core/structured_director/generation_observer.py`；`generation_lifecycle.py` | `oracle/test_oracle_uncertain_submission.py`、`oracle/test_oracle_restart_recovery.py`、`test_structured_director_recovery.py` |
| G2 | 重试创建新 Generation，保留 retry_of 与原 seed。 | `core/structured_director/service.py::retry_generation`；`core/playground/service.py` | `test_asset_audio_generation.py::test_failed_generic_audio_generation_can_retry_same_request`、`test_external_production.py`、黄金 `video.retry_after_failure`、Playground `run.retry` |
| G3 | 观察故障隔离、不可达不丢句柄；明确拒绝为 failed。 | `core/structured_director/generation_observer.py`；`generation_lifecycle.py` | `test_structured_director_generation.py::test_refresh_*`、`::test_explicit_provider_rejection_is_failed_not_uncertain` |
| G4 | 所有插件拒绝 plugin_id 或版本不匹配的句柄。 | 各插件 `provider.py` 的句柄校验 | `test_model_provider_contract.py`、各插件测试 |

## Agent 契约

实现：`core/structured_director/prompt_worksets.py`；`core/director_proposals/`；`core/application/caller.py`；`integrations/storyrail_mcp/`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| H1 | video_prompt 工作集提供上下文、当前 recipe 声明、实际输入、说明标签、生效设置与 hints；专业格式由插件补充。 | `core/structured_director/prompt_worksets.py`；`core/model_providers/minimax_h3/prompt_payload.py` | `test_prompt_worksets.py::test_manifest_matches_actual_fake_provider_request_and_language`、`test_professional_worksets.py`、`test_semantic_projection.py`、`test_video_recipe_projection.py` |
| H2 | Agent 可保存视频提示词、切换 recipe、生成和超分；输入引用更新仍为人类操作，Core 校验白名单。 | `core/application/caller.py`；`core/director_commands/video_commands.py` | `test_director_commands.py`、`oracle/test_oracle_permission_boundary.py` |
| H3 | H3 的官方格式 Skill 与参考文本位于 minimax_h3 插件包。 | `core/model_providers/minimax_h3/skills/h3-prompt-writing/` | `test_h3_prompt_writer.py`、`test_consistency_contract.py` |
| H4 | Agent 服从用户指定的提示词语言；未指定时不增加语言约束。 | `core/director_proposals/skills/storyrail-video-prompt/`；插件 Skill | `test_prompt_worksets.py`（language） |
| H5 | MCP tools/list 的严格 schema 由逐字节基线守护。 | `integrations/storyrail_mcp/production_tools.py`；`tests/fixtures/mcp_project_tools.json` | `oracle/test_oracle_mcp_wire.py`、`test_storyrail_mcp.py` |

## Playground

实现：`core/playground/`；`core/model_providers/recipe.py`；`web/src/playground/forms/RecipeForm.tsx`。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| I1 | 模型入口及参数 schema 来自当前绑定 recipe；五项确定性工具保留固定声明。 | `core/playground/capabilities.py`、`parameters.py`；`core/model_providers/recipe.py` | `test_playground_capabilities.py`、`test_playground_commands.py`、`test_playground_recipe_catalog.py`、`RecipeForm.test.tsx` |
| I2 | Playground 使用与生产相同的 recipe 请求构造、范围和插件常量。 | `core/playground/capabilities.py`、`parameters.py`；`core/model_providers/recipe.py` | `test_playground_capabilities.py::test_resolve_request_builds_production_shaped_*`、黄金 Playground、`test_playground_recipe_catalog.py`、`RecipeForm.test.tsx` |
| I3 | Playground 输入预览与运行标签由 Core 按同一规则计算，Web 只读展示。 | `core/playground/service.py::preview_recipe_inputs`；`projection.py` | `test_playground_capabilities.py::test_ref2va_labels_match_production_mapping`、`RunForm.test.tsx`“Ref2VA 预览标签映射…”、`test_playground_recipe_catalog.py`、`RecipeForm.test.tsx` |
| I4 | RecipeForm 渲染所有模型参数/槽位，产物可按声明作为后续输入；确定性工具使用手写表单。 | `web/src/playground/forms/RecipeForm.tsx`；`web/src/playground/RunCard.tsx` | `RunForm.test.tsx`、`RunFeed.test.tsx`、`test_playground_recipe_catalog.py`、`RecipeForm.test.tsx` |
| I5 | 模型运行产物按 recipe.label 与 run 短 ID 命名。 | `core/playground/capabilities.py::run_output_label` | `test_playground_capabilities.py::test_run_output_labels_follow_capability_naming`、`test_playground_recipe_catalog.py`、`RecipeForm.test.tsx` |
| I6 | schema v2 的 run.capability 保存 recipe ID，并保存提交时 recipe 声明与 provider_snapshot。 | `core/playground/models.py`、`codec.py` | `test_playground_store.py`、`test_playground_models.py`、`test_playground_recipe_catalog.py`、`RecipeForm.test.tsx` |
| I7 | `image.pano_view` 参数范围复用生产全景裁切契约；只有 2:1 PNG/JPEG 全景 Asset 带 `pano_view` 动作，Web 选择器与“作为输入”只列出这些 Asset；产物是新 Asset，源 Asset 不变；四方向批量由 Web 逐条提交。 | `core/model_providers/contracts.py`；`core/playground/parameters.py`、`capabilities.py`、`store.py`、`projection.py`；`web/src/playground/forms/PanoViewForm.tsx` | `test_playground_capabilities.py::test_pano_view_*`、`test_playground_service.py::test_pano_view_*`、`test_ffmpeg_pano_view.py::test_playground_crops_four_directions_through_media_service`（真实 v360 四方向）、黄金 Playground `image.pano_view`、`RunForm.test.tsx`“全景裁切…”、`AssetPanel.test.tsx`、`RunFeed.test.tsx` |

## IndexTTS2.5

实现：`core/model_providers/indextts2/`；使用现有通用加载器、旁白提交与 RecipeForm。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| J1 | 插件包安装后声明声音克隆、语速 0.5–2 与八维情感 −1–1；无 Core 领域或 Web 专用实现。 | `core/model_providers/indextts2/` | `test_indextts2_provider.py::test_plugin_loads_playground_vector_form_and_preserves_historical_request`、`::test_narration_uses_new_plugin_without_domain_changes` |
| J2 | 模型 HTTP 请求体、五种状态、取消、回收、句柄与响应严格校验。 | `core/model_providers/indextts2/` | `test_indextts2_provider.py::test_observe_translates_all_phases`、`::test_invalid_observation_is_rejected`、`::test_cancel_artifact_and_handle_boundaries` |
| J3 | Windows 服务路由、封闭内部请求、63 位 seed 与中英语言映射。 | `default_model_providers_implement/{server.py,request_builders.py,indextts2_worker.py,runners.py}` | `test_indextts2_runtime.py` |
