---
name: h3-prompt-writing
description: Write MiniMax H3 video generation prompts for T2VA, I2VA, FL2VA, L2VA, and Ref2VA. Use when rewriting multimodal requests into H3 prompt structures, composing integrated_multimodal_description, overall_soundscape, and non_diegetic_music, aligning keyframes, or defining reference labels for images, videos, and audio.
---

# H3 Prompt Writing

结构化导演脚本与已审核关键帧已经确定镜头目的、构图、人物调度、光线基线、连续性和起止状态。本 Skill
只把这些决定翻译为连续时间过程与官方 H3 格式，不重新导演镜头，不新增角色关系、景别、光源或剧情揭示。
如果脚本和关键帧不足以确定这些事实，应返回需要上游补充的信息，而不是用提示词自行补齐。

## Workflow

1. Identify the input mode: T2VA, I2VA, FL2VA, L2VA, or full-reference Ref2VA.
2. Read `references/cinematic-video-prompting.md` for StoryRail 的画面与调度规范（含单镜与多 Shot 段内切镜）。
3. For base text/keyframe modes, read `references/base-en.txt` and follow its final prompt structure.
4. For full-reference mode, read `references/ref-en.txt` and follow its six-section rewrite format.
5. Preserve the exact field names, section order, labels, and timing notation from the selected guide.

## Base Modes

- T2VA: build the full audiovisual timeline from text.
- I2VA: start from the first frame and develop forward from it.
- FL2VA: describe the continuous path between the first and last frames.
- L2VA: infer a plausible opening and converge to the supplied last frame.

Use `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music` in the order shown in `references/base-en.txt`.

## Full-Reference Mode

Ref2VA rewrites use `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, and `non_diegetic_music` in that order. Reference labels stay consistent across all sections.

Read `references/ref-en.txt` for label rules, retention analysis, and complete examples.

## Output Rules

- Follow the user-specified prompt language. If none is specified, choose the language from context without imposing a language requirement. Keep format fields, reference labels, relationship markers, and timing syntax unchanged; preserve dialogue, lyrics, and visible scene text verbatim in their original language.
- Describe each shot by composition, subjects, environment, actions, camera, sound, and the exact point where referenced content appears.
- Avoid plot summaries, unresolved reference labels, and timing that does not match the requested duration.

## StoryRail Ref2VA 参考素材绑定

手工绑定只在用户本轮明确要求时进行（例如“再参考这段环境声”“参考那条视频的运镜”），通过 `save_video_prompt` 的 `recipe_inputs` 保存；以工作集 `recipe_inputs` 为起点，未被要求的绑定原样保留。对白 TTS WAV 与其他参考共用 `recipe_inputs` 的显式音频列表。用户明确要求添加本段对白时，将 `dialogue_audio` 草稿或 `bindable_assets` 中已选对白保存到列表；未明确要求时不补齐。生成入口会拒绝缺失的对白引用，不会隐式注入音频。

- FL2VA 没有可显式绑定的槽位；需要参考素材时先经用户同意切到 `minimax_h3.ref2va`。切回 FL2VA 前必须先清空下列槽位。
- `additional_images`：最多 4 张图片，例如角色参考图、用户显式选择的地点图片；说明写它定义的主体或环境。
- `reference_audios`：最多 3 条 WAV（官方 ComfyUI 节点上限）；对白超过 3 句的 Segment 需拆分，或由用户决定只绑定其中几句。已选对白 TTS 按剧本顺序占用前面的 Audio 标签；其余名额才用于用户显式添加的音色、环境声或原声参考。系统对白音频来自 DialoguePlan，不从角色卡参考音色直接推导。
- `reference_videos`：最多 3 条 2–15 秒 MP4，只参考画面；说明运镜、节奏或动作用途。
- 每项说明必填且 Asset 不重复；Ref2VA 可无图片，但五类媒体槽至少一项；`params` 传 `{}`。
- 绑定变化后正文要引用新标签时，重读工作集，用新的 `actual_provider_inputs` 标签写正文。

## StoryRail 对白写法

Core 原样提交已保存正文，不在正文前后追加任何文字。插件按下列规则检查已保存正文，工作集 `prompt_problems`
列出发现的问题；它只是提示、不阻止生成，保存后应重读并修正到为空。工作集 `prompt_dialogue` 按剧本顺序给出每句对白的
`speaker`、原台词 `text` 与实际绑定的 `audio_label`（未绑定为 null）；`dialogue_timing` 给出已选 WAV 的真实时长、
起点和最晚结束时间，时间设计必须服从这些事实，视频时长不得短于最后一句对白结束时间。

- 每句台词在全文只出现一次，位置固定在 `detailed_description` 对应镜头里：`<Subject N> (Sx) 动作与语气……说：<d>[Chinese] 原台词</d>`。
  `<d>` 内只放语言标签与逐字原台词，中文台词用 `[Chinese]`，英文用 `[English]`；说话者描述、动作、语气写在 `<d>` 外。
- `subject_definitions`、`summary`、`retention_analysis`、`overall_soundscape`、`non_diegetic_music` 只用 `<Audio N>` 与 `(Sx)`
  指代这句对白，不写台词原文，也不用引号转述或改写复述；参考音频说明里的“说话内容”只供识别，不抄进正文。
- 对白音频的固定写法：
  - `subject_definitions` 单独一行定义：`<Audio N> 是 <Subject M> (Sx) 的对白音频。`
  - `summary` 的任务类型包含 `audio reuse`（例如 `[keyframe completion + audio reuse]`）。
  - `retention_analysis` 写 `<Audio N>: partially_copy - …`：已选 TTS WAV 的原信号放进这句对白的时间窗，其余时间和环境声由模型生成。
    它不是整条成片音轨，不用 `fully_copy`；也不是只借音色重新念台词，不用 `reference`。这一段不写 `(Sx)`。
  - 用户显式添加的音色参考才写 `reference`，环境声原样复用按实际情况写 `partially_copy`，都不能当成对白音频。
- 说话者 ID 按目标视频中实际发声顺序分配，一个说话者一个 ID，跨镜头沿用；不同说话者不能共用 ID。
  没有台词的角色不分配 `(Sx)`：他们的咆哮、斥责、喘息、哭声写成非语言音效（例如“灰狼压低身体发出低沉的咆哮”），
  不写成带引号的词语，也不写 `<d>`。`<d>` 只承载 `prompt_dialogue` 中的台词，不新增台词。
- 同一句台词跨段内切镜时用 `<scenetrans>` 拆成前后两个 `<d>`，两侧都带语言标签并沿用同一 `(Sx)`，拼起来仍是原台词。

## StoryRail 独立旁白隔离

StoryRail 的 Scene 旁白由独立 TTS 音频资产承载，并在 Scene/Final Assembly 阶段由 Core/FFmpeg 后期定位混入。它不是 H3、I2VA、FL2VA 或 Ref2VA 视频模型的生成音频输入。

- 绝不把剧本旁白、解说词或 narrator 文本写入 `<d>...</d>`，也不要写成 `says in an off-screen voiceover`、"解说员以画外音叙述" 或任何其它画外音指令。
- `<d>...</d>` 只允许承载当前 Segment 明确指定、确实由画面角色表演的剧情对白或演唱；不要把 Scene 旁白伪装成角色对白。
- `on_screen` 是 Segment 覆盖的全部 Shot 的并集：`true` 表示说话者在段内至少一个 Shot 可见，具体在哪一镜入画按该 Shot 的 `visible_character_names` 落实；`false` 是同一空间内画外角色的剧情对白，不是旁白，按 `references/cinematic-video-prompting.md` 第 5 节写成画外说话者，画面中的听者双唇闭合；`null` 是引用库外的临时说话者（`character_name` 是称呼），是否入画以 Segment `action` 为准。
- `<d>` 中的台词逐字照抄 `dialogue[].text`，不改写、不纠错、不增删。
- 没有明确剧情对白时，必须明确写出人物双唇全程闭合、全片无开口、无对白、无画外音配音；这不等于禁止呼吸、喘息或其它非语言拟音。
- `overall_soundscape` 只描述环境声、动作拟音和非语言人声（例如呼吸、喘息、喊叫的非词语声）；必须根据画面动作和环境写出具体音效，除非用户明确要求全片完全静音，不得写成 `N/A` 或省略音效。末尾的人声声明按 Segment 区分：
  - `dialogue` 非空：声明“除上述对白外无其它人类语音”，不写 `<d>` 标签或台词原文，不写“全片无人类语音”；
  - `dialogue` 为空：声明“全片无人类语音，保持纯净环境音”；只有 `scene.driver` 为 `narration` 时再加“预留后期主旁白音频叠加通道”，drama Scene 不写这句。
- 默认禁止生成非画内背景音乐（BGM、score、audience-only music）：只有 `user_direction` 或 Shot `audio_direction` 明确写出配乐或音乐入点时，才按其写入 `non_diegetic_music`（脚本的 `audio_direction` 来自导演方案或用户的明确要求）；否则 `non_diegetic_music` 必须为 `N/A`，不得从“电影感”、情绪或风格描述推断音乐需求。只有画内角色演奏、收音机、电视或手机播放的音乐才作为画内事件写入 `integrated_multimodal_description`，不等同于 BGM。
- 不因历史提示词中已有旁白而保留它；历史正文与当前独立旁白架构冲突时，删除视频模型旁白并保留视觉动作和环境声。

## StoryRail 画面与调度规范

完整规则见 `references/cinematic-video-prompting.md`；它与关键帧正文工程同源，只描述已确定的可见状态如何连续变化。

- 先看 `context.shots` 的数量。只有一项时，Segment 是连续镜头：4 秒以上写 2~3 个连续阶段（起势 → 物理交互与阻力 → 落点或悬念），不虚构段内切镜，也不为凑节拍硬写切镜。
- 有多项时，按数组顺序写 `[Shot 1]`、`[Shot 2] At MM:SS.mmm …`。切点按各 Shot 的构图、动作与 `duration_seconds` 的比例估算；它只是软约束：Core 不按 Shot 切视频、不记录段内切点，生成后切点漂移仍是合格候选，由人挑选或重生成，不因此判定失败。
- 首尾 Picture 只锚定第一个 Shot 的开头与最后一个 Shot 的结尾；中间 Shot 的人物身份、服装与空间关系靠参考图与已批准关键帧维持。Ref2VA 时优先建议用户为可见角色绑定造型图，但只在用户明确要求时修改绑定。
- 同一个 Segment 的段内切镜数当前不超过 3 个；需要更多切镜时先向用户说明并建议拆成多个 Segment。
- 每个 `shots[]` 带 `visible_character_names`；由它决定该镜谁入画。空间以已批准关键帧、Shot 描述和 Scene 地点语义为准，不存在 Shot 级地点图片绑定。
- `segment.continues_from_previous_segment` / `continues_into_next_segment` 表示相邻 Segment 共享边界 Shot（延续同一镜头）：开头或结尾沿用同一空间、人物状态与光线，不重新建立场景；两者都为 false 时按独立剪辑处理。
- 同一句台词跨越段内剪辑时用 `<scenetrans>` 连接两侧并写明音频连续；具体写法以官方 guide 为准。
- 运镜按官方 Motion Type + Amplitude + Speed 写清，节拍与 `duration_seconds` 匹配，结尾落在可剪辑状态。
- 年代、实体与材质按已确认设定正向锚定；最容易被替换的实体可在正文尾部写与已确认设定一致的排除句，但不得新增用户没有要求的排除项。空泛形容词不得代替可见事实。
- 关键帧阶段已决定的景别与空间关系不在视频提示词里重新发明；视频只描述连续变化。

## 提交前核对

- 用户本轮明确指定的正文语言优先于历史提示词和示例语言；只保留固定字段、标签、关系标记、时间语法及原文对白。不要因示例是英文而把中文要求输出为英文。
- `actual_provider_inputs.allowed_asset_reference_labels` 只限制实际 Picture/Video/Audio 素材。Ref2VA 的 `<Subject N>` 是从实际素材派生的可见主体，不是新的图片输入；必须在 `subject_definitions` 定义其来源和特征，不能只定义 Picture/Audio 便省略主体。声音映射须指向相应主体/说话者，不能虚构未提供的参考资产。
- `pictures` 中 `role=described_reference` 的 Picture 是用户显式参考图；按其 `description` 和原标签落实用途，不臆造时间锚点。
- 无对白时 `audios` 可为空；含对白时，以 `prompt_dialogue[].audio_label` 识别已选 TTS WAV，不假设它们位于列表开头。其他项按 `description` 区分音色与原声复用，不能默认都是角色音色。
- `videos` 可为空，不得虚构；按 `description` 引用画面用途，不提交音轨。
- 首尾 Picture 的精确时间取 `pictures[].time_seconds`；无 Picture 时不写图片标签或对齐句。`context.shots` 只有一项时不要写切镜；多项时 `[Shot 1]` 不带切镜时间，后续切镜才用 `[Shot N] At MM:SS.mmm, ...`，切点是按 Shot 设计与总时长估算的软约束，不要求与生成结果逐帧一致。Base 模式沿用对应 guide 的对齐句。
- 逐项保留用户明确的排除要求（例如无字幕、无水印、无新增角色、无对白或无背景旁白），在最终正文的相关画面/声音字段写清；不能只写在内部分析、工作集或摘要中，也不能用“不改剧情”等泛化表述代替。未要求的排除项不自动新增。
- 完成以上核对后才提交；保存后重读工作集确认 `prompt_problems` 为空。这些规则不授权改写用户已保存的正文，生成仍直接使用当前已保存提示词。
