---
name: storyrail-video-prompt
description: 根据当前视频 recipe 与实际输入优化单个 Segment 的视频提示词，并按用户要求保存 recipe 参考素材与机制参数。
---

先读取 `project.get_workset` 的 `video_prompt` 工作集。当前 recipe 声明可用槽位、机制参数、实例设置摘要与提示；插件随附的专业 Skill 和参考资料在本契约的 `plugin/` 资源中（工作集 `plugin_skills` 只列目录）。按这些资料组织正文，使用 Core 提供的实际引用标签，不自行编号、不推导未提交的媒体。

保持 Scene、覆盖 Shot、Segment 已保存的导演意图。用户指定正文语言时服从，未指定时不增加语言约束。

## 多 Shot Segment

`context.shots` 是该 Segment 覆盖的 Shot（按顺序），可能只有一项，也可能有多项。

- 只有一项：Segment 是连续镜头，不虚构段内切镜；需要切镜时与用户讨论拆 Segment。
- 多项：正文按顺序写 `[Shot 1]`、`[Shot 2] At MM:SS.mmm …`。切点按各 Shot 的构图、动作与 `duration_seconds` 的比例估算，只是软约束：Core 不按 Shot 切视频、不记录段内切点，生成后切点漂移仍是合格候选，不要求重生成。
- 首尾 Picture 只锚定第一个 Shot 的开头与最后一个 Shot 的结尾；中间 Shot 的人物与空间靠参考图维持。Ref2VA 时优先建议用户为可见角色绑定造型图，但只在用户明确要求时改绑定。
- 同一句台词跨越段内剪辑时用 `<scenetrans>`。
- 段内 Shot 数当前不超过 3 个；更多切镜先建议拆 Segment。

## 保存

- 只改正文：`video.set_prompt`（MCP `save_video_prompt` 不带 `recipe_inputs`）。
- 绑定参考素材或填写机制参数：`video.update_recipe_inputs`（MCP `save_video_prompt` 带 `recipe_inputs`），与正文原子保存。
  `bindings` 与 `params` 按槽位、按键合并：给出的槽位整体替换（空列表表示清空），未给出的槽位与参数保持原样。
- 含对白的 Segment：每句对白须已选 TTS 才能生成；未加入参考音频不阻止生成，但视频不会用到这些对白音频，
  工作集 `dialogue_audio.unbound_lines` 列出未加入的台词。通常保存时带 `attach_dialogue_audio: true`，Core 按与 Web“一键添加本段对白 TTS”
  相同的规则把已选 WAV 按剧本顺序放在参考音频最前，覆盖本句旧 WAV 并保留其他手动参考；缺任一句 TTS 或超出名额时整次拒绝。
- 两种保存的回执 `data` 都是写入后的摘要：`prompt_chars`、合并后的 `recipe_inputs`、实际提交标签 `asset_inputs`、
  插件 linter 的 `prompt_problems` 与 `dialogue_audio.unbound_lines`。确认保存结果直接读它，不要为确认而重读工作集。

都不生成媒体、不选择候选。用户明确要求生成时，再单独调用 `video.generate`。

## 参考素材与参数

- 工作集 `video_inputs[]` 给出当前 Segment 的其他图片计划与实际媒体绑定；图片可以是任意画面内容，不限角色、地点或关键帧。按 `reference_inputs[].asset_id` 用 `read_media_input` 审看已绑定图片；未选中的规划与候选不能冒充实际视频输入。需要单独规划或生成其他图片时，使用 `save_reference_image_plan` 与 `generate_media(kind="reference_image")`；看图后用 `select_reference_image` 选入对应卡片（来源可为本卡候选、关键帧已选图或任一项目图片），人类可随时改选。
- 除对白 TTS 外，只在用户本轮明确要求时绑定、替换或移除素材，或修改参数。只提交被要求的槽位或参数；改某个槽位时以工作集 `recipe_inputs` 中该槽位为起点，不擅自增删、重排已有绑定或改写其说明。
- 槽位以 `video_recipe.recipe.slots` 为准，只填首帧/尾帧以外的槽位；首尾帧由 Core 按已选关键帧填写，不写进 `bindings`。数量、媒体类型、时长与 `describe=required` 的必填说明都按槽位声明，说明写清这项素材的用途。
- `asset_id` 从 `bindable_assets` 选取，其 `slots` 列出它能进入的槽位；用户点名的其它本项目 Asset 也可以，由 Core 校验。不能引用 Playground Asset。
- `params` 只填 `video_recipe.editable_params` 声明的机制参数，只给要改的键，不改时传 `{}`；时长、seed、画幅等带语义角色的参数由 Core 填写。
- 当前 recipe 没有所需槽位时先说明，经用户同意再用 `video.set_recipe` 切换；切到不支持某些槽位的 recipe 前必须先清空这些槽位。
- 绑定变化会让 Core 按槽位顺序重新编号 Picture/Audio/Video 标签。正文需要引用新标签时，先带当前正文（`historical_prompt`）保存输入，从回执 `data.asset_inputs` 取得新标签，再写正文并保存。
- Core 原样提交已保存正文，不前置任何对白约束。对白写法由插件 Skill 规定（H3 见 `h3-prompt-writing` 的“StoryRail 对白写法”），
  工作集 `prompt_dialogue` 给出每句台词与实际 `audio_label`；添加或重排对白 TTS 会改变 Audio 标签，之后要重读工作集并按新标签改写正文。
  保存后重读工作集，`prompt_problems` 列出插件检查出的格式问题；它只是提示，不阻止生成，但应先按提示修正正文再请求生成。

## 时长提醒

超长 Segment 留到这里处理。工作集 `exceeds_soft_duration_limit` 为
true 时（`context.duration_seconds` 超过插件声明的 `soft_duration_limit_seconds`，当前 H3 为 15 秒），在优化
提示词或用户要求生成该 Segment 视频前主动提醒用户：说明时长和可能 OOM 的风险，建议拆成多个 Segment，并给出
建议的拆分点（自然动作的稳定状态、明确的控制方式变化或可复用的连续性锚点，可直接截帧续拍），同时说明拆分后
新 Segment 需要自己的关键帧和提示词。

这只是提醒，不是 Core 约束。用户同意后再用 `script.apply_operations` 的 `split_segment` 拆分，然后分别为各段
写提示词；拆分不改变 Shot 设计，拆出的相邻 Segment 共享边界 Shot 时是延续同一镜头，两段都要给出覆盖的
`shot_ids` 并在后一段填写 `boundary_from_previous`；因视频模型 15 秒软约束拆分时，`reason` 使用
`model_constraint`。用户选择不拆时照常保存或生成，不擅自拆分，也不拒绝提交。

对白句数超过当前 recipe 参考音频名额（当前 H3 为 3 条）时，工作集 `dialogue_audio.error` 给出提示，
`attach_dialogue_audio` 会整次拒绝。生成前主动提醒用户并建议在台词之间或 Shot 边界用 `split_segment` 拆分，
`reason` 使用 `model_constraint`；用户不拆时，按用户指定只绑定其中几句，未绑定的台词不会进入视频。

有对白时只认工作集 `dialogue_timing` 的真实 WAV 时序；未就绪不猜秒数。真实结束时间超过 Segment 时长时建议
加长或拆分，不删减、改写或加速台词。
