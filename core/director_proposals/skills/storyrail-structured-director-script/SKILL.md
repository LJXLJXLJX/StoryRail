---
name: storyrail-structured-director-script
description: 创建或按用户要求修改可审核的 Scene、Shot、ShotSegment 完整草稿；不处理媒体生成和生产任务。
---

# StoryRail 结构化导演脚本

把已经确定的故事与导演选择组织成能直接审核的 Scene、Scene 级旁白 Cue、Shot 和显式 ShotSegment。保留上游决定，不重新
发明剧情；在脚本阶段先固化镜头功能、第一视觉重心、空间调度、连续性锚点、揭示路径和起止状态，不把这些导演判断
留给后续 Keyframe 或 H3 Skill 临场猜测。不要用抽象“电影感”填充镜头。

提交前同时遵守 `references/cinematic-director-intent.md`。它是脚本阶段的模型无关视觉导演意图契约；不要把其中的
Provider 字段、图片标签或 H3 时间语法提前写入脚本。drama Scene 还要遵守 `references/drama-scene-craft.md`：
情绪由距离、高度、画面权重、镜头对表演的反应和时间这些可见变化承担，不由形容词承担。

只返回 proposal：不要写项目文件，不要调用图片、视频或声音 Provider，不要选择候选、
批准脚本或创建生产任务。角色只能引用输入中提供的 ID；引用库外的临时或画外说话者不伪造 ID，对白写 `character_id: null` 加 `speaker_label`。每个 Scene 自己完整
描述本场环境，不创建或引用项目级场地。

编辑已有草稿时，以 Core 在本轮 `<core-script-context>` 中直接提供的受控事实为唯一当前版本。不得调用
read、bash、shell、jq 或其它发现工具，也不得读取项目目录。`outline` 只用于理解顺序和定位，只有 `scenes`
中的目标 Scene 才能作为正文事实；禁止返回完整草稿。
用显式 `replace_scene`、`insert_scene`、`delete_scene`、`move_scene` 操作表达修改；只改一个已有 Segment
时用 `replace_segment`，不要回抄整个 Scene；没有实际修改时返回空操作。
保留已有层级 ID，新建 Scene、NarrationCue、Shot 或 ShotSegment 的 `id` 必须为 null，不猜测正式 ID。

结构化脚本契约和质量门由 Core 与本 Skill 一起固定装入 Compiler instructions；直接遵守，不要再次读取文件。

## 工作顺序

生成初稿或回改一个以上 Scene 时按以下顺序，前四步只在内部完成：

1. 读完整导演方案，记下每段的目的、观众认知变化、必须揭示、必须保留和情绪功能；方案写明的以方案为准。
2. drama Scene 先做整场设计：按 `drama-scene-craft.md` 第 1 节回答这场戏是谁的、双方各想要什么、转折在哪、
   关系从什么状态进入到什么状态离开，并定下全场最重的镜头。
3. 再调度：按 `cinematic-director-intent.md` 第 3 节为每个 Scene 建立空间、角色路径、注意力和揭示顺序。
4. 沿调度和强度曲线决定切镜，每个新 Shot 只写一个 Segment，写出完整草稿。
5. 复查后再提交：逐 Scene 按 `quality-gate.md` 复查草稿，drama Scene 同时过 `drama-scene-craft.md` 第 9 节，重点看每个切镜能否说出理由、同空间只换角度的
   相邻 Shot、揭示是否早于导演方案、新 Shot 是否只有一个 Segment、跨 Shot 轴线与道具。发现问题先改草稿，
   再复查该 Scene。所用 Agent 支持独立上下文的子任务时，可只把导演方案、引用卡和草稿交给它复查。
   复查过程不写入 proposal。

只改单个 Segment 或少量文字时，只复查受影响的 Shot 及其相邻边界。
