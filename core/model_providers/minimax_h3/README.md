# MiniMax H3

插件实例 `minimax_h3`：一份 manifest 声明 `minimax_h3.fl2va` 与 `minimax_h3.ref2va` 两个
`video.generate` recipe，二者共用实例设置。HTTP 翻译由包内 `fl2va/`、`ref2va/` 两个实现完成，历史 Generation 按它们各自的句柄 `plugin_id` 回到原实现。

- `manifest.py`：设置（基础模型预设 Hybrid V2 · 20 步 / Turbo V2 · 8 步、分辨率 480p/720p/1080p、
  SageAttention、SelfLift）、`soft_duration_limit_seconds = 15` 提示、两个 recipe 的槽位与参数，以及
  “有对白默认 Ref2VA”的默认规则；`render_settings` 把实例设置换算成提交时的画布与采样组合。
- `plugin.py`：`plugin_instance(endpoint, transport)` 构造可安装的插件实例。

设置只在全局 Provider 设置页由人类修改，项目与 Playground 共用；改设置只影响之后的提交，
每个 Generation 在 `provider_snapshot` 中记录提交时的设置。

`requests.py` 把通用 RecipeRequest 翻译为包内 `contracts.py` 的 DTO；`render.py` 只在插件内解释画布与采样设置。
`prompt_context.py` 将 Core 视频领域事实与输入标签转换成 H3 专业格式，`prompt_skills` 提供 `skills/h3-prompt-writing/` 的正文和参考资料，由 Core 经 `video_prompt` 专业契约交付。标签由 Core 统一编号。`context.shots` 按 Segment 覆盖顺序给出每个 Shot；Skill 据此写 `[Shot N] At MM:SS.mmm` 段内切镜软约束，首尾 Picture 只锚定首个 Shot 的开头与最后一个 Shot 的结尾。

含对白的 Ref2VA 提交由 Core 把已选 DialogueAudio WAV 按剧本顺序放在手工音频参考之前，提示词原样使用已保存正文。
插件只接收编译后的 RecipeRequest，不读取角色卡或自行生成对白。

`prompt_lint.py` 是插件的 `prompt_linter`：Core 构造 `video_prompt` 工作集时传入时长、实际输入标签和本段对白
（说话者、原台词、实际 Audio 标签），检查结果写进 `prompt_problems`。它只是降低 Agent 写错概率的软提示，
不进入依赖原因、不阻止生成。按官方 H3 结构检查：

- 段落：出现任一官方段名或本段有对白时，必须按 Ref2VA 六段 / Base 三段的官方顺序各写一次；Ref2VA 首段之前不能有文字，
  Base 只允许官方的首尾帧对齐句；
- 对白：每句台词只在描述段以 `(Sx) … <d>[Language] 原台词</d>` 写一次，`<d>` 闭合且不嵌套，语言标签与台词文字一致，
  `<scenetrans>` 拆开的两段合并为一句；台词原文不得出现在 `<d>` 之外的任何段；`<d>` 不得承载本段对白以外的内容；
- 说话者：一个说话者一个 `(Sx)`，没有台词的 `(Sx)` 视为多说话者歧义；
- 引用：只能引用本次实际输入的 Picture/Audio/Video 标签，用到的 `<Subject N>` 必须单独定义；对白音频须在
  `subject_definitions` 单独定义并沿用说话者 ID，`retention_analysis` 标为 `partially_copy` 且该段不写 `(Sx)`，
  `summary` 任务类型包含 `audio reuse`；所有复用关系标记取官方取值；
- 镜头：描述段从 `[Shot 1]` 起连续编号，后续镜头紧跟递增且早于视频结束的 `At MM:SS.mmm`。

无对白且不使用官方段名的自由正文只做 `<d>`、说话者与标签检查。
