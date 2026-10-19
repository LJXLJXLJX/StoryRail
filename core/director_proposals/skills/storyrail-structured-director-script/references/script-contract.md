# 结构化脚本契约

## Scene

Scene 是特定时间和空间中发生的一段戏。标题便于浏览；摘要只写实际事件；`setting` 完整写清本 Scene 的
地点、空间特征、时段、天气、灯光和环境状态。Scene 不引用项目级场地卡。

Scene 的 `driver` 必须明确为 `narration` 或 `drama`，同一项目可混合，两者均无固定 Scene 总时长。
两种 Scene 的声音来源互斥，Core 强制校验，违反时整份 proposal 被拒绝：

| driver | 旁白 Cue | 角色对白 `dialogue_lines` |
| --- | --- | --- |
| `narration` | 必须恰好一条 | 必须全部为空数组 |
| `drama` | 必须为空数组 | 按剧情需要，可有可无 |

一段内容既需要旁白又需要角色开口时，拆成相邻的 narration Scene 与 drama Scene，不能在同一 Scene 中混用；
也不要把旁白改写成角色对白、或把对白塞进旁白来绕过限制。

`narration`：正文是一个语义原子的旁白单元，通常接近一句完整旁白，不能用标点计数替代语义判断。
初稿仅返回一个 Cue 与空 `shots`、空 `segments`；Cue 没有 Shot 锚点，永远覆盖整个 Scene。
用户先生成、审核并选择项目所选语言的 TTS。后续根据 Core 提供的 `narration_timing.planning_duration_seconds` 规划
Shot 与 Segment（见下文 ShotSegment）。该值以所选语言已选音频中最长一条的真实时长为基础（`timing_language` 标明是
哪种语言）；当下一 Scene 也是 narration 时，Core 固定给当前
Scene 增加 `visual_tail_seconds=0.4` 的尾部画面缓冲。各 Segment 时长总和应等于规划时长，且缓冲只放在
最后一个 Shot 的结尾，不重复加到每个 Segment。任一语言音频未选择时不能规划 Shot timing，不按字符数估算最终时序。
后续规划的 Segment 只写画面动作，`dialogue_lines` 始终为空数组；画面中人物可以有口型以外的表演，但不说台词。
旁白正文回改只使该语言的音频选择失效，并使时序与装配失效；保留现有视觉设计，待新音频就绪后再调整时序。

`drama`：先按意图、画面、动作与表演设计 Shot，不预设 Scene 总时长；`narration_cues` 必须为空数组，
没有背景旁白。对白按剧情需要在 Segment 中声明，也可以完全没有对白；有真实语音时长时它约束 Shot 的最小时长。

旁白语言以工作集 `narration_languages` 为准。只为已选语言给出非空轨道，未选语言的 `zh` / `en` 必须为 null。
单语言只生成对应旁白与成片；双语言才产出中文版、英文版，画面共用，时间以较长音频为准。
`zh.text` 是中文正文；`en.text` 是适合英文朗读的意译，不逐字翻译、不增删信息、不写中文夹注。
双语言时尽量让两种朗读时长接近。不得根据原方案语言自行增加项目未选语言。

每条轨道提供可复现的 `seed` 与 `recipe_params`。读取工作集 `speech_recipe`，按其 `editable_params`
填写无语义角色的机制参数，用 recipe ID 作为对象键；没有表达要求时用声明的默认值或返回空对象。
例如 Breeze 可填写 `{"breeze_tts2.clone": {"performance_instruction": "语速稍慢，克制"}}`，
其可空文本上限为 200 字。其它插件遵守自己的声明，不复制 Breeze 字段。正文、语言、参考音色、文字稿与 seed
由 Core 按领域事实填充，不放进机制参数。它们只是首次试听 proposal，用户在审核阶段调整。
不要返回音频、Generation、真实时长或候选选择。

## Shot

Shot 是一个中间不存在剪辑的连续镜头。切镜必须创建新 Shot；Shot 没有时长上限。默认不切：只有连续
摄影无法完成导演目标时才新建 Shot（见 `cinematic-director-intent.md` 第 3 节）。分别写清：

- `composition`：景别、角度、主体位置和构图关系；
- `camera_movement`：摄影机运动，固定机位也要明确；
- `action`：整个连续镜头中的可见动作和表演；
- `audio_direction`：环境声和音效提示，不写角色对白或旁白。导演方案或用户明确写出的配乐、音乐入点就是明确要求，必须写进对应 Shot，注明“非画内配乐”与入点（例如“大提琴第一个长音在达里奥僵住时切入”）；方案没写时不要自行添加背景音乐意图，也不要写“无背景音乐”去否定方案。角色演奏、收音机、电视或手机播放的音乐属于画内声音，应写成可见事件；
- `transition_in`：V1 保留导演文字意图字段，不执行影视转场；默认返回 null。

`visible_character_ids` 只列画面中实际可见的引用库角色。

## ShotSegment

Segment 与 Shot 平级写在 `scenes[].segments[]`，Shot 本身没有 `segments` 字段。每个 Segment 用
`shot_indexes`（本 Scene `shots` 数组的序号）按顺序声明覆盖的 Shot：非空、不重复、连续，按顺序恰好覆盖本 Scene
全部 Shot；相邻 Segment 只允许共享边界 Shot（前一段最后一个 = 后一段第一个），共享即延续。
一个 Segment 可以覆盖多个相邻 Shot（段内切镜），一个 Shot 也可以跨多个相邻 Segment（长镜头拆段）。
改稿里的 `replace_scene` 同样用本 Scene 新 `shots` 数组的序号。

先设计 Shot 列表，再打包成 Segment。打包决定生产边界，不改变 Shot 设计：拆 Segment 不新增、不合并、不重写
Shot；同一 Shot 跨多个 Segment 时是同一连续镜头的生产切片。按以下规则打包：

- 每个 Segment 预计不超过 15 秒。长镜头预计超过时，拆成共享该 Shot 的相邻 Segment，边界落在可直接从上一段
  实际视频截帧续拍的稳定状态（站定、落脚、手停在物体上、运镜匀速段），前后各约半秒内画面不发生关键变化；
  多 Shot Segment 预计超过时，先在 Shot 边界拆开，再处理仍然超长的镜头。拆分不压缩动作或台词凑时长；仍
  超过时按真实节奏填写 `duration_estimate_seconds`，由 Director 在生成视频前提醒用户，用户同意后再拆。
- 同一空间、同一节拍内的紧密镜头组可以装进一个 Segment：对话正反打、反应镜头、插入特写。段内切镜只用于
  这类有明确剪辑理由的镜头组，实验前每个 Segment 不超过 3 个；不要为凑节拍虚构切镜，也不要把时间跳跃或
  视角主体切换塞进同一 Segment。
- 需要精确构图控制的镜头独占 Segment：建立镜头、关键揭示、全场最重的镜头、需要严格首尾状态的镜头。
- 相邻 Segment 共享边界 Shot 即延续同一镜头，后一段必须填写 `boundary_from_previous`，写清交接时刻的角色、
  摄影机、道具和光线状态；不共享边界 Shot 即剪辑，`boundary_from_previous` 必须为 null；第一个 Segment 为 null。
- 初稿与回改都在 `reply_markdown` 简述打包理由：哪些镜头组合并进一个 Segment、哪些长镜头拆成相邻 Segment、
  为什么。

改稿时保留已有 Segment 划分，只在用户明确要求时拆分或合并（`split_segment`、`merge_adjacent_segments`）。
在某个 Shot 内部拆分时，两段都包含该 Shot，后一段填写 `boundary_from_previous`；合并后的 `shot_ids` 为两段
覆盖的并集。每次拆分、合并或插入后都必须重新满足完整连续覆盖。

`duration_estimate_seconds` 只是节奏预估。Segment 的 `action` 写该分段负责的动作区间。角色对白写入
`dialogue_lines`，每句引用说话角色，`delivery` 写本句的潜台词（嘴上说的与真正想要的）和语气；
说话者可以在画外，此时不列入该 Shot 的 `visible_character_ids`。导演方案里不在引用库的说话者
（研究员、门外路人、广播等）写 `character_id: null` 与 `speaker_label`（≤ 60 字称呼），台词照常保留，
不要删掉，也不要挪进 `audio_direction`；是否入画在 Segment `action` 里写明。每个 Shot 至多一个开口说话的
可见角色；一个 Segment 覆盖多个 Shot 时这条规则分别作用于每个 Shot，台词在该 Shot 对应的段内区间说完，
不要在同一段内让两个可见人物在同一镜头里轮流开口。没有对白时返回空数组。旁白不是角色对白，不写入这里。
只有 drama Scene 的 Segment 可以有对白；narration Scene 的 Segment 一律返回空数组。

`DialogueLine` 自身有独立的 15 秒软上限：按自然语速、`delivery` 要求与必要停顿估算，任何一条
`dialogue_lines[].text` 本身预计超过 15 秒时，必须在自然语义或表演停顿处拆成连续的多条 DialogueLine，
使每条预计不超过 15 秒。拆分只改变对白行边界，不删减、概括或改写原文；各条沿用同一 `character_id`，或同一
`speaker_label`，并分别写清该段 `delivery`。这条规则与 Segment 时长约束相互独立：即使所在 Segment 可以加长、
或已经拆成多个 Segment，也不能保留一条预计超过 15 秒的 DialogueLine；拆 Segment 不能代替拆长对白。

当前默认本地 H3 对每个 Segment 有 15 秒软约束：超过可能（但不一定）OOM，Core 不会拒绝。这是生产阶段的
机器约束，不要写成故事或镜头里的创作事实，也不要为它切碎原本完整的动作。
Narration Scene 的 Segment 时长在 TTS 之后规划，Core 随写入按真实音频自动校准后该字段承载生产时长。
相邻 Segment 边界默认是独立 Keyframe。Scene 边界不决定切换；默认硬切，
仅显式共享边界 Keyframe identity 时由系统做 0.1 秒接缝融合，这不是导演 dissolve。


不要返回 Prompt、关键帧、模型、Provider、生成参数、候选、审核、顺序号、通用备注或未声明字段。

## 持续改稿

每次改稿都使用 Core 在本轮 `<core-script-context>` 中内联的只读事实。不要调用工具补读文件，不要依赖
Thread 中的旧脚本判断当前事实，也不要输出完整 state。结果必须是类型化局部操作：现有 Scene
使用 `replace_scene`，单个 Segment 使用 `replace_segment`，Scene 结构变化使用显式插入、删除或移动操作，
不能从结果缺失项推断删除。现有层级沿用输入 ID；新增层级返回 null ID；`replace_scene` / `replace_segment`
的 Segment 一律用本 Scene 新 `shots` 数组的序号表达覆盖。`reply_markdown` 只简要说明实际修改；新建或整体重写 drama Scene 时，每个 Scene 用一两句白话写导演阐述：
这场戏是谁的、转折在哪、最重的镜头是哪个。打包有变化时同时说明哪些镜头组合并进一个 Segment、哪些长镜头
拆成相邻 Segment、为什么。
