---
name: storyrail-structured-director-script
description: 创建或按用户要求修改可审核的 Scene、Shot、ShotSegment 完整草稿；先设计 Shot 再打包成 Segment，不处理媒体生成和生产任务。
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
提交连接若公开 `proposal_source`，大型初稿可以先写入连接指定的固定工作区 JSON，再只用字节数与 SHA-256 引用提交；
这只是出站传输方式，不能读取旧文件作为项目事实，也不能据此绕过完整 proposal 校验或最终原子提交。

## 工作顺序

生成初稿或回改一个以上 Scene 时按以下顺序，前六步只在内部完成：

1. 读完整导演方案，记下每段的目的、观众认知变化、必须揭示、必须保留和情绪功能；方案写明的以方案为准。
   同时按 `quality-gate.md`「方案覆盖」列出方案清单：每个节拍、每句台词及说话者、画面中的可见文字与插入镜头、
   伏笔与回收、声音与配乐入点、片名或字幕卡，以及方案给出的时间码或时长。
2. drama Scene 先做整场设计：按 `drama-scene-craft.md` 第 1 节回答这场戏是谁的、双方各想要什么、转折在哪、
   关系从什么状态进入到什么状态离开，并定下全场最重的镜头。
3. 再调度：按 `cinematic-director-intent.md` 第 3 节为每个 Scene 建立空间、角色路径、注意力和揭示顺序。
4. **设计 Shot 列表**：沿调度和强度曲线决定切镜，只决定创作层的镜头内容与边界。沿用最少切镜原则，drama Scene
   同时按 `drama-scene-craft.md` 第 5 节判断切点；合并镜号只合并摄影，不删内容。这一步不决定生产分段。
5. **打包成 Segment**：按 `script-contract.md` 的 ShotSegment 打包规则把 Shot 列表装进 Segment。一个 Segment
   可以覆盖多个相邻 Shot（段内切镜，只用于同空间、同一节拍的紧密镜头组，实验前不超过 3 个），一个 Shot 也可以
   跨多个相邻 Segment（长镜头拆段，边界落在可截帧续拍的稳定状态）；需要精确构图控制的镜头独占 Segment；每个
   Segment 预计不超过 15 秒。确定覆盖关系、共享边界与 `boundary_from_previous`、各段时长和 `action` 区间。
   同时逐条检查 `dialogue_lines`：任何一条对白本身按自然语速、语气和停顿预估超过 15 秒时，必须在自然语义边界
   拆成连续的多条 DialogueLine，并保持原文、说话者和顺序；这是对白行自身的约束，拆 Segment 不能代替拆长对白。
   方案清单的每一项都落到具体 Segment 的 `action`、`dialogue_lines` 或覆盖 Shot 的 `audio_direction`。
6. 复查后再提交：逐 Scene 按 `quality-gate.md` 复查草稿，drama Scene 同时过 `drama-scene-craft.md` 第 9 节，
   重点看每个切镜能否说出理由、同空间只换角度的相邻 Shot、揭示是否早于导演方案、覆盖是否完整连续、段内切镜
   是否确有剪辑理由且不超上限、精确构图镜头是否独占 Segment、跨 Shot 轴线与道具。发现问题先改草稿，再复查该
   Scene。所用 Agent 支持独立上下文的子任务时，可只把导演方案、引用卡和草稿交给它复查。复查过程不写入 proposal。
7. `reply_markdown` 按 Scene 写出方案时长与脚本合计时长、打包理由（哪些镜头组合并成一个 Segment、哪些长镜头
   拆成相邻 Segment、为什么）；有意删减或合并的方案内容逐条列出并说明原因，没有删减时明确写“无删减”。
   提交后用 `read_story` 读 Segment 层，`dialogue_timing.exceeds_duration` 为 true 的 Segment 加长
   `duration_estimate_seconds` 或按用户要求拆分，不压缩台词。

只改单个 Segment 或少量文字时，只复查受影响的 Shot、覆盖它的全部 Segment 及相邻边界。
