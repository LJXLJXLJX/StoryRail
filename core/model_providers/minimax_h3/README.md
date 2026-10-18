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
`prompt_context.py` 将 Core 视频领域事实与输入标签转换成 H3 专业格式，并提供 `skills/h3-prompt-writing/` 的正文和参考资料。标签由 Core 统一编号。`context.shots` 按 Segment 覆盖顺序给出每个 Shot；Skill 据此写 `[Shot N] At MM:SS.mmm` 段内切镜软约束，首尾 Picture 只锚定首个 Shot 的开头与最后一个 Shot 的结尾。

含对白的 Ref2VA 提交由 Core 把已选 DialogueAudio WAV 按剧本顺序放在手工音频参考之前，并确定性把
“严格让角色说出参考音频的原始内容，音频完全相等。”及逐条 Audio→原台词映射加到提示词开头。插件只接收编译后的
RecipeRequest，不读取角色卡或自行生成对白。
