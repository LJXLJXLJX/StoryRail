---
name: storyrail-video-prompt
description: 根据当前视频 recipe 与实际输入优化单个 Segment 的视频提示词，并按用户要求保存 recipe 参考素材与机制参数。
---

先读取 `project.get_workset` 的 `video_prompt` 工作集。当前 recipe 声明可用槽位、机制参数、实例设置摘要与提示；插件随工作集提供专业 Skill 和参考资料。按这些资料组织正文，使用 Core 提供的实际引用标签，不自行编号、不推导未提交的媒体。

保持 Scene、Shot、Segment 已保存的导演意图。用户指定正文语言时服从，未指定时不增加语言约束。

## 保存

- 只改正文：`video.set_prompt`（MCP `save_video_prompt` 不带 `recipe_inputs`）。
- 绑定参考素材或填写机制参数：`video.update_recipe_inputs`（MCP `save_video_prompt` 带 `recipe_inputs`），正文与当前 recipe 的 `bindings`、`params` 一起整体替换。

都不生成媒体、不选择候选。用户明确要求生成时，再单独调用 `video.generate`。

## 参考素材与参数

- 只在用户本轮明确要求时绑定、替换或移除素材，或修改参数。以工作集 `recipe_inputs` 为起点，只改被要求的槽位或参数，其余原样回传；不擅自增删、重排已有绑定或改写其说明。
- 槽位以 `video_recipe.recipe.slots` 为准，只填首帧/尾帧以外的槽位；首尾帧由 Core 按已选关键帧填写，不写进 `bindings`。数量、媒体类型、时长与 `describe=required` 的必填说明都按槽位声明，说明写清这项素材的用途。
- `asset_id` 从 `bindable_assets` 选取，其 `slots` 列出它能进入的槽位；用户点名的其它本项目 Asset 也可以，由 Core 校验。不能引用 Playground Asset。
- `params` 只填 `video_recipe.editable_params` 声明的机制参数且键必须完整，没有声明时传 `{}`；时长、seed、画幅等带语义角色的参数由 Core 填写。
- 当前 recipe 没有所需槽位时先说明，经用户同意再用 `video.set_recipe` 切换；切到不支持某些槽位的 recipe 前必须先清空这些槽位。
- 绑定变化会让 Core 按槽位顺序重新编号 Picture/Audio/Video 标签：先带当前正文（`historical_prompt`）保存输入，重读工作集取得新的 `actual_provider_inputs` 标签，再写正文并保存。

## 时长提醒

脚本初次规划时一个 Shot 只有一个 Segment，超长 Segment 留到这里处理。工作集 `exceeds_soft_duration_limit` 为
true 时（`context.duration_seconds` 超过插件声明的 `soft_duration_limit_seconds`，当前 H3 为 15 秒），在优化
提示词或用户要求生成该 Segment 视频前主动提醒用户：说明时长和可能 OOM 的风险，建议拆成多个 Segment，并给出
建议的拆分点（自然动作的稳定状态、明确的控制方式变化或可复用的连续性锚点，可直接截帧续拍），同时说明拆分后
新 Segment 需要自己的关键帧和提示词。

这只是提醒，不是 Core 约束。用户同意后再用 `script.apply_operations` 的 `split_segment` 拆分，然后分别为各段
写提示词；用户选择不拆时照常保存或生成，不擅自拆分，也不拒绝提交。

工作集 `dialogue_timing.exceeds_duration` 为 true 时，台词按字数估算（`estimated_seconds`）念不完：同样先提醒
用户，建议加长 Segment 时长或在听者反应处拆分；不要为了塞进时长而删减、改写或加速台词。
