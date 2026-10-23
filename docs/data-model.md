# 数据模型

`.stories/<项目名>-<project_id>/project.json` 是项目唯一权威结构化状态，当前 `schema_version = 36`。
更早版本按开发期规则不迁移，一律拒绝读取，需要新建项目。代码位置：
`core/structured_director/models/`（值对象与不变量）、`codec/`（严格 JSON）、`schema.py`（版本号）。

所有模型都是不可变 dataclass，构造时即校验；JSON 解码拒绝未声明字段与缺失字段。ID 统一是 32 位小写十六进制，
由 Core 分配；Agent 与 Web 都不能自造 ID。

## 实体关系总览

```mermaid
erDiagram
    DOCUMENT ||--|| REFERENCE_LIBRARY : reference_library
    DOCUMENT ||--o| DIRECTOR_SCRIPT : director_script
    DOCUMENT ||--|| LOCATION_LIBRARY : location_library
    DOCUMENT ||--o| KEYFRAME_PLAN : keyframe_plan
    DOCUMENT ||--o| VIDEO_PLAN : video_plan
    DOCUMENT ||--o| FINAL_ASSEMBLY : final_assembly
    DOCUMENT ||--o| FINAL_APPROVAL : final_approval
    DOCUMENT ||--o{ ASSET : assets
    DOCUMENT ||--o{ GENERATION : generations
    DOCUMENT ||--o{ DIRECTOR_RUN : director_runs
    DOCUMENT ||--o{ APPLICATION_REQUEST : application_requests

    REFERENCE_LIBRARY ||--o{ CHARACTER_CARD : characters
    REFERENCE_LIBRARY ||--o| NARRATOR : narrator
    NARRATOR ||--|| VOICE_ZH : zh
    NARRATOR ||--|| VOICE_EN : en

    DIRECTOR_SCRIPT ||--|{ SCENE : scenes
    SCENE ||--o{ SHOT : shots
    SCENE ||--o{ SEGMENT : segments
    SCENE ||--o| NARRATION_CUE : "narration_cues (≤1)"
    SEGMENT }o--|{ SHOT : shot_ids
    SEGMENT ||--o{ DIALOGUE_LINE : dialogue_lines
    NARRATION_CUE ||--|| TRACK_ZH : zh
    NARRATION_CUE ||--|| TRACK_EN : en

    LOCATION_LIBRARY ||--o{ LOCATION : locations
    LOCATION ||--o{ LOCATION_IMAGE : images
    SCENE }o--o| LOCATION : location_id

    KEYFRAME_PLAN ||--|{ KEYFRAME : keyframes
    KEYFRAME_PLAN ||--|{ SEGMENT_KEYFRAMES : "segments (每个 Segment 一条)"
    SEGMENT_KEYFRAMES }o--|| KEYFRAME : start_keyframe_id
    SEGMENT_KEYFRAMES }o--|| KEYFRAME : end_keyframe_id
    KEYFRAME }o--o| KEYFRAME : predecessor_keyframe_id
    KEYFRAME }o--o{ KEYFRAME : reference_keyframe_ids

    VIDEO_PLAN ||--|{ SEGMENT_VIDEO : "segments (每个 Segment 一条)"
    FINAL_ASSEMBLY ||--|{ FINAL_CLIP : "clips (每个 Scene 一条)"

    GENERATION }o--o{ ASSET : input_asset_ids
    GENERATION |o--o| ASSET : output_asset_id
    GENERATION |o--o| GENERATION : retry_of
```

`SEGMENT_KEYFRAMES` 与 `SEGMENT_VIDEO` 通过 `segment_id` 一对一对应当前脚本中的每个 Segment；Core 在每次脚本
回改后立即重建这两份计划，保证不缺卡、不多卡。

## 文档根（`StructuredDirectorDocument`）

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `schema_version` | int | 固定 36 |
| `project_id` | id | 项目 ID |
| `revision` | int ≥ 1 | 项目 revision；每次持久写入恰好 +1，是全部 CAS 的基准 |
| `title` / `aspect_ratio` | 创建时固化 | 没有修改 API |
| `director_plan_markdown` | 非空 Markdown | 最多 50,000 字符；只允许人类经 Core 手工修改。修改只推进项目 revision，不自动改写或失效已有结构化内容与媒体 |
| `narration_languages` | 数组 | 必填，`["zh"]`、`["en"]` 或 `["zh", "en"]`；创建后不可修改 |
| `status` | 枚举 | 主要审核位置（见下） |
| `workspace_layers` | 4 个布尔 | 已解锁内容层，单调累加 |
| `reference_library` | 对象 | 角色卡与旁白身份 |
| `director_script` | 对象或 null | 结构化脚本与生产基线 |
| `pending_script_edit` / `pending_narration_edit` | 对象或 null | 进行中的脚本/旁白编辑请求原文 |
| `location_library` | 对象 | 地点库：地点、固定陈设、状态与机位视图 |
| `keyframe_plan` / `video_plan` | 对象或 null | 视觉生产解锁后建立 |
| `final_assembly` / `final_approval` | 对象或 null | 最终成片计划与批准 |
| `assets` / `generations` | 列表 | 全部媒体与生成历史 |
| `capability_gap_alerts` | 列表 | `project.apply_repair_patch` 的审计记录 |
| `director_runs` / `director_directives` | 列表 | 领域长任务与其用户原话 |
| `application_requests` | 列表 | 外部写命令的持久幂等回执 |

### `status` 与 `workspace_layers`

```mermaid
stateDiagram-v2
    [*] --> awaiting_reference_proposal: POST /api/projects
    awaiting_reference_proposal --> reviewing_references: 引用库 proposal 提交
    reviewing_references --> reviewing_script: 脚本 proposal 提交
    reviewing_script --> reviewing_narration: script.confirm<br/>narration_unlocked
    reviewing_narration --> reviewing_videos: 解锁视觉生产<br/>keyframes_unlocked + videos_unlocked
    reviewing_videos --> reviewing_final: 进入成片装配<br/>final_assembly_unlocked
    reviewing_final --> approved: final.approve
    reviewing_final --> reviewing_videos: final.reopen_production
    approved --> reviewing_videos: final.reopen_production
```

`status` 只表示“用户主要停在哪一层审核”。真正决定能力的是 `workspace_layers`：

| 层 | 何时置 true | 约束 |
| --- | --- | --- |
| `narration_unlocked` | `script.confirm` | — |
| `keyframes_unlocked` | 解锁视觉生产 | 不能早于旁白层 |
| `videos_unlocked` | 解锁视觉生产（与 Keyframe 同时） | 不能早于 Keyframe 层 |
| `final_assembly_unlocked` | 首次进入成片装配 | 不能早于视频层 |

Store 拒绝任何让某层从 true 变回 false 的写入。上游回改只清掉过期的选择、生产基线或装配计划，状态停在最深已解锁层
（`review_status`），不会退回。因此“状态是 `reviewing_final`”不代表“当前一定有有效成片”。
`reviewing_keyframes` 是保留的枚举值，当前流程直接从旁白进入视频审核位置。地点库不是内容层：项目创建起即可编辑，
解锁视觉生产本身就是跳过地点规划。

## 引用库

| 实体 | 关键字段与约束 |
| --- | --- |
| `CharacterCard` | `name`（项目内大小写不敏感唯一）；`visual_description` 非空 = 可见角色，**null = 非出镜声音**（此时 `voice_description` 必填、`looks` 必须为空，不能出现在任何可见角色列表、不能生成人像）；`looks` ≤ 8 套，是角色图的唯一来源；`voice_description` ≤ 500；`voice_reference_asset_id` + `voice_reference_transcript`（克隆所需完整文字稿） |
| `CharacterLook` | 角色的一套造型：Core 分配的 `id`（全库唯一）、`name`（≤ 100，同一角色内唯一）、`appearance`（服装、发型、配饰、身体状态，≤ 2000）、`usage`（使用场合，≤ 1000）、`selected_asset_id`（人类选定的造型图，图片 Asset 或 null） |
| `NarratorProfile` | 独立旁白身份，ID 不得与角色卡重复；`name` + 所选语言各一套 `NarratorVoice`（`zh` / `en`，未选语言为 null）；无旁白时为 null |
| `NarratorVoice` | 单一语言的旁白音色：`voice_description` 必填（≤ 500）；`voice_reference_asset_id`（WAV）+ `voice_reference_transcript`（克隆所需完整文字稿）。中文 Cue 只用 `zh` 克隆、英文 Cue 只用 `en` 克隆，缺哪种语言的参考音色或文字稿就不能合成该语言 |

对白说话者二选一：`character_id` 指向引用库角色（可以是非出镜声音，如广播、电话），或 `character_id = null` 加
`speaker_label`（≤ 60 字称呼）与必填 `voice_description`（≤ 500），表示引用库外的临时或画外说话者；视频工作集里
`on_screen = null`，是否入画以 Segment `action` 为准。每句 `DialogueLine` 由 Core 分配全项目唯一的稳定 `id`。
引用库角色有参考音色时，对白 TTS 强制使用同一角色的参考 WAV 和完整文字稿克隆；没有参考音色时使用角色卡的
`voice_description` 做 Voice Design；引用库外说话者使用该句的 `voice_description` 做 Voice Design。

## 结构化脚本

```mermaid
classDiagram
    class DirectorScript {
      revision: int
      source_reference_revision: int
      production_baseline_revision: int?
      production_baseline_scenes: Scene[]?
      scenes: Scene[1..100]
    }
    class Scene {
      id
      title ≤300
      summary ≤4000
      setting ≤4000
      driver: narration | drama
      location_id?
      state_id?
      narration_cues[0..1]
      shots[]
      segments[]
    }
    class Shot {
      id
      visible_character_ids[]
      composition · camera_movement · action
      audio_direction
      transition_in?
      view_id?
    }
    class ShotSegment {
      id
      shot_ids[1..]
      duration_estimate_seconds min 0.2
      action ≤4000
      dialogue_lines[]: DialogueLine
      boundary_from_previous?
    }
    class SegmentBoundary {
      reason: model_constraint | continuity_anchor | control_boundary | failure_cost
      continuity_instruction
    }
    class DialogueLine {
      id
      character_id? | speaker_label
      voice_description?
      text
      delivery
    }
    DirectorScript "1" *-- "1..100" Scene
    Scene "1" *-- "0..*" Shot
    Scene "1" *-- "0..*" ShotSegment
    ShotSegment "*" ..> "1..*" Shot : shot_ids
    ShotSegment "1" *-- "0..1" SegmentBoundary
    ShotSegment "1" *-- "0..*" DialogueLine
```

- 全项目最多 100 个 Scene、1,000 个 Shot、2,000 个 Segment；Scene、Shot、Segment、DialogueLine、Cue 的 ID 全局唯一。
- Shot 是创作层描述，Segment 是生产原子。`segment.shot_ids` 是本 Scene `shots` 中按顺序连续的一段，非空不重复；
  依次拼接全部 Segment 的 `shot_ids`（相邻 Segment 共享的边界 Shot 只算一次）必须恰好等于 `shots`，不跳过、不倒序、
  不重复覆盖。一个 Segment 可覆盖多个 Shot，一个 Shot 可跨多个相邻 Segment。
- 相邻 Segment 共享边界 Shot（前一段最后一个 = 后一段第一个）即延续同一镜头，后一段必须带 `boundary_from_previous`，
  说明为什么在此切开与如何保持连续；不共享即剪辑，`boundary_from_previous` 必须为 null；Scene 第一个 Segment 为 null。
- `shots` 与 `segments` 同时为空或同时非空。

```mermaid
flowchart LR
    s1[Shot 1] --- s2[Shot 2] --- s3[Shot 3] --- s4[Shot 4]
    g1["Segment 1<br/>shot_ids: [s1, s2]<br/>段内切镜"] --> g2["Segment 2<br/>shot_ids: [s3]<br/>剪辑边界"]
    g2 --> g3["Segment 3<br/>shot_ids: [s3, s4]<br/>共享边界 s3，续接同镜头"]
```
- `driver = narration`：必须恰好一条 Cue，覆盖整个 Scene 的全部 Segment；所有 Segment 的 `dialogue_lines` 必须为空；
  在真实 TTS 之前可以没有 Shot 与 Segment。
- `driver = drama`：至少一个 Shot；`narration_cues` 必须为空，对白可有可无。
- 旁白与对白互斥由 `Scene` 模型构造时强制校验，任何写入路径（proposal、`script.apply_operations`、手工保存）产生
  违规 Scene 都会整体拒绝。
- `production_baseline_revision` 与 `production_baseline_scenes` 同时存在或同时为 null。旁白层解锁后，Core 在每次脚本/旁白写入
  里自动校准并写入它们，表示“这一版脚本的时序已经按真实音频校准”；无法校准时保留上一次的值，因而与 `revision` 不等。
  视觉生产、装配都要求 `production_baseline_revision == revision`。

### 旁白 Cue

| 字段 | 说明 |
| --- | --- |
| `id` | Cue ID；Cue 永远覆盖所在 Scene 的全部 Segment，没有 Shot 锚点 |
| `zh` / `en` | 已选语言为非空 `NarrationTrack`，未选语言为 null |
| `NarrationTrack.text` | 正文 ≤ 4,000；英文是适合朗读的意译 |
| `NarrationTrack.seed` | 0 … 2⁶³−1 |
| `NarrationTrack.recipe_params` | recipe ID → 机制参数；当前 speech recipe 的 editable_params 声明类型、范围与默认值 |
| `NarrationTrack.selected_audio_asset_id` | 该语言当前采用的音频 |

所选语言分别合成、审核、选择。单语言取该音频的真实时长，双语言取已选音频中较长的一条，算法见 [数据流](data-flow.md#旁白时序)。

### 对白 TTS 计划

`DialoguePlan` 与当前 `DirectorScript.revision` 严格绑定，每条 `DialogueLine` 恰好对应一条 `DialogueAudio`：

| 字段 | 说明 |
| --- | --- |
| `dialogue_line_id` | 当前脚本中的稳定 DialogueLine ID |
| `seed` | TTS / Voice Design seed |
| `recipe_params` | 当前克隆 recipe 的机制参数，由 Provider manifest 渲染和校验；例如 Breeze 的表演指示包含语气、情绪、语速与停顿。Voice Design 路由不接受克隆参数 |
| `selected_audio_asset_id` | 人类从该句成功、未隐藏的候选中选定的 WAV；生成后输入变化只作软提示 |
| `start_seconds` | 该 WAV 在 Segment 内的真实发声起点；任一句重新选音频或正文/音色变化时整段清空 |

Core 按剧本顺序校验 WAV 不重叠，并要求 `Segment.duration_estimate_seconds` 不短于最后一句对白结束时间。对白音频全部选择且
时序校准后，Core 才允许生成该 Segment 视频。脚本回改会按稳定 DialogueLine ID 重建计划：完整原句即使被分配到新的
Segment 也保留生成候选与已选音频，只清空发声起点；正文、说话者、音色描述发生变化时才清除该句的选择与时序。
历史 Asset 与 Generation 始终保留。

## 地点库

地点（Location）是跨 Scene 共享的固定空间。同一空间的昼夜、天气、布置或破坏变化是状态（LocationState），不是新地点。
每个地点可保存一组扁平、彼此独立的图片（LocationImage）；没有必需主图，也没有从主图派生视图的层级。
Shot 与 Keyframe 不引用地点图片。代码位置：`models/location.py`。

```mermaid
erDiagram
    LOCATION_LIBRARY ||--o{ LOCATION : "locations (≤200)"
    LOCATION ||--o{ FIXTURE : "fixtures (≤40)"
    LOCATION ||--o| KEY_LIGHT : key_light
    LOCATION ||--o{ LOCATION_STATE : "states (≤10)"
    LOCATION ||--o{ LOCATION_IMAGE : "images (≤200)"
    LOCATION_IMAGE }o--o| LOCATION_IMAGE : "frozen panorama source"
    SCENE }o--o| LOCATION : location_id
    SCENE }o--o| LOCATION_STATE : state_id
```

地点、陈设、状态和图片 ID 都由 Core 分配，在项目内全局唯一。

### Location

| 字段 | 约束 |
| --- | --- |
| `id`、`name` | name 1–200 字；改名不失效 |
| `description` | 固定空间：结构、材质、固定陈设、风格；≤ 4,000 |
| `fixtures[]` | `{id, name ≤200, description ≤2,000}`；只放固定陈设，不放人物或临时道具 |
| `key_light` | `{description ≤1,000}` 或 null |
| `states[]` | `{id, name ≤200, description ≤2,000}`；description 写相对固定空间的可见差量 |
| `images[]` | ≤ 200；见下表 |

### LocationImage

| 字段 | 约束 |
| --- | --- |
| `id`、`name` | name 1–200 字 |
| `kind` | `image`：普通地点图，跟随项目画幅；`panorama`：2:1 等距柱状全景，可进入 3D 查看器 |
| `description` | 1–4,000 字；人或 Agent 根据实际画面填写的强制纯文本说明，不等同于生成提示词 |
| `prompt_text` | ≤ 19,000；下一次生成正文，可空 |
| `reference_asset_ids` | 0–5 张任意项目图片，稳定有序且不重复 |
| `selected_asset_id` | 人类从该图片条目的成功、未隐藏候选中选择；全景取景子图完成时由 Core 直接选中确定性产物 |
| `source` | 仅普通图片可有：`{panorama_image_id,yaw_deg,pitch_deg,hfov_deg}`；记录创建时来源，不形成活依赖 |

Scene 保存可选 `location_id` / `state_id`，state 必须属于该 Location；没有 Location 时 state 必须为空。Shot 与 Keyframe
没有地点字段。Keyframe Planner 工作集把当前 Scene 的地点、状态和图片说明作为语义上下文，但 Provider 图片输入仍只来自角色造型、
前置帧和人类显式加入的辅助图。

`location.apply_operations` 以原子 patch 编辑地点事实。名称、说明、图片计划、参考图或选图变化都不级联失效 Keyframe、视频、
超分或装配；删除图片也不删除历史 Asset/Generation 或已取景子图。删除仍被 Scene 绑定的 Location、仍被 Scene 使用的 State 会拒绝。
活动中的同目标 Generation 仍阻止冲突编辑。

## Keyframe 计划

| 实体 | 字段与约束 |
| --- | --- |
| `Keyframe` | `id`；`owner_segment_id`；`predecessor_keyframe_id`（时间上前一个边界帧，图必须无环）；`prompt_text` ≤ 18,000；`visible_character_ids`；`character_references`（`[{character_id, look_id}]`：只针对本帧可见角色、每角色一项，`look_id` 必须是该角色当前造型；`look_id = null` = 不提交该角色图；未列出时只有一套造型默认使用它，多套造型必须显式选择才能生成；所选造型没有造型图时不能生成）；`selected_asset_id`；`reference_keyframe_ids`（0–4 个其它 Keyframe，不含自身、不重复；写入时每个都必须已有选中图，生成时解析为它们**当前**的选中图并以“参考关键帧”角色提交；被参考帧撤销选择后本帧不能生成，批次等待；被参考帧被移除时引用随写入剪除，读取时引用必须存在） |
| `SegmentKeyframes` | `segment_id`；`start_keyframe_id` ≠ `end_keyframe_id`；`start_enabled` / `end_enabled`（默认都关闭）；`reference_asset_ids` 手工辅助图 ≤ 4 张 |

- Keyframe 计划以 Segment 为单位：当前脚本的每个 Segment 恰好一条 `SegmentKeyframes`，脚本回改后 Core 立即重建，
  不允许缺卡或多卡。
- 每个 Segment 都有概念上的首尾槽位；实际视频只需启用并选择其中至少一个。
- 相邻 Segment 的边界默认是两个独立 Keyframe。**显式共享**表示左段 `end_keyframe_id` 与右段 `start_keyframe_id`
  指向同一个 Keyframe 对象（同一条 Asset/Generation 血缘），两侧启用状态各自独立。
- 新建计划时，每个 Segment 的尾帧以首帧为 `predecessor`。

## 视频计划

`SegmentVideo`（每个 Segment 一条）：

| 字段 | 约束 |
| --- | --- |
| `prompt_text` | 视频提示词 ≤ 20,000；生成前必须非空，提交时还校验 recipe 的 prompt 参数约束 |
| `active_recipe` | 当前视频 recipe ID；未配置 Provider 时为 null |
| `recipes` | recipe ID → `{bindings, params}`；每个槽位保存有序 `{asset_id, description}` 数组，机制参数按 recipe 隔离 |
| `selected_asset_id` | 当前采用的原视频 |
| `upscaled_asset_id` | 超分结果；必须以已选原视频为前提 |

首尾帧由 Core 从 Keyframe 的启用与选择事实填写，不进入显式 bindings。旁白、对白和 Segment 时长仍是领域事实。
含对白的 Segment 只能使用带参考音频槽位的 recipe；Core 把已选 DialogueAudio WAV 按剧本顺序放在手工音频绑定之前，
它们不写入 `recipes.bindings`。H3 提交时 Core 在正文开头确定性加入“严格让角色说出参考音频的原始内容，音频完全相等。”
及每个 Audio 标签到原始台词的逐句映射。
新视频卡按当前绑定插件的 manifest defaults 与 `segment.has_dialogue` 谓词选择 recipe；没有安装视频插件时不指定默认模型。
切换 recipe 保留每个 recipe 的输入与参数，清除当前视频和超分选择并失效相关装配；同值切换为 noop。
若当前显式输入的角色或约束不受目标 recipe 支持，必须先移除这些输入。卸载插件后历史输入仍保留，可选择新的可用 recipe。

H3 插件的 `minimax_h3.ref2va` 声明附加图 0–4 张、WAV 音频 0–8 条、MP4 视频 0–3 条（2–15 秒），各槽位内资产唯一且必填说明。
`minimax_h3.fl2va` 不接受这些显式引用。约束来自插件 manifest，不是 Segment 模型的固定字段。
Web 快照另有只读 `recipe_state`：当前可用性、切换选项及原因、完整生成时长、软时长提示和 Core 计算的输入标签。


## 成片

```mermaid
classDiagram
    class FinalAssemblyPlan {
      source_script_revision
      clips: FinalAssemblyClip[]
      selected_zh_asset_id?
      selected_en_asset_id?
    }
    class FinalAssemblyClip {
      scene_id
      zh_asset_id
      en_asset_id
      transition_from_previous: null | seam_blend
    }
    class FinalApproval {
      zh_asset_id · zh_generation_id
      en_asset_id · en_generation_id
      source_script_revision
      approved_project_revision
    }
    FinalAssemblyPlan *-- FinalAssemblyClip
```

- 最终成片计划按脚本顺序每个 Scene 一条 clip，引用该 Scene 所选语言当前有效的 **Scene 成片 Asset**，未选语言为 null；
  首个 clip 的 `transition_from_previous` 必须为 null。
- 所选语言各自选择候选；一次 Approval 绑定所选语言全部精确 Asset、Generation、脚本 revision 与批准后的项目 revision。
- Scene 成片本身没有持久计划对象：`SceneAssemblyPlan` 只在渲染时临时构建，是否“当前有效”由 Generation 输入血缘判定。

## Asset

| 字段 | 约束 |
| --- | --- |
| `id` | Core 分配 |
| `media_type` | `image/png`、`image/jpeg`、`image/webp`、`audio/wav`、`video/mp4` |
| `byte_count` | 视频 ≤ 2 GiB，其它 ≤ 64 MiB |
| `sha256` | 64 位十六进制，导入与读取都校验 |
| `relative_path` | 受控项目内相对路径（下表），文件名是可读语义名 + `-<sha256 前 10 位>` |
| `duration_seconds` | WAV/MP4 从实际字节读取；视频插件可回报实测时长 |

```text
assets/
├── images/
│   ├── library/          通用导入
│   ├── characters/       → image_category = character_reference
│   ├── locations/
│   │   └── captures/     → panorama_capture（只能由全景取景产生，不接受导入）
│   │                      其它地点图 → location_image
│   ├── keyframes/        → keyframe
│   └── video-frames/     → video_frame（只能由抽帧产生，不接受导入）
├── audio/
│   ├── voice-references/ narration/ generated/ effects/ trims/ stems/ imported/
└── videos/
    ├── segments/ upscaled/ scene-final/ final/ animatics/ audio-remixes/ imported/
```

内容不可变：同一 Asset 的字节永不改写。唯一例外是 Scene 成片的“当前文件”机制——重新装配成功后，
Core 原子替换该 Scene 的稳定当前文件名，并把上一版文件改名为带内容哈希的归档名，旧 Asset 记录指向归档文件，
字节与 SHA-256 不变。

## Generation

```mermaid
stateDiagram-v2
    [*] --> submitting: 创建（持久化后才调用 Provider）
    submitting --> queued: Provider 接受
    submitting --> failed: Provider 明确拒绝
    submitting --> submission_uncertain: 传输/响应无法确认<br/>或进程在提交窗口中断
    queued --> running
    queued --> succeeded
    running --> succeeded: 产物校验并导入为 Asset
    queued --> failed
    running --> failed
    queued --> cancelled
    running --> cancelled
    succeeded --> [*]
    failed --> [*]
    cancelled --> [*]
    submission_uncertain --> [*]
```

迁移表在 `models/generation.py::transition_generation` 中集中定义，其它代码不能直接赋值 `phase`。

| 字段 | 语义 |
| --- | --- |
| `kind` / `operation` / `target_id` | 生成什么、怎么生成、属于哪个业务目标 |
| `prompt_text`、`recipe_params`、`sample_text` | 实际提交的提示词；按 recipe 保存的机制参数；参考音频文字稿 |
| `input_asset_ids` | **有序**输入血缘，顺序就是提交给 Provider 的顺序 |
| `seed` | 实际使用的 seed；装配类为 null |
| `plugin_id` / `plugin_version` / `external_id` | 由哪个插件、以什么外部句柄执行；历史任务永远按自己的 `plugin_id` 路由 |
| `provider_snapshot` | 提交时绑定的插件实例、recipe、生效设置与摘要（如 `minimax_h3` · `minimax_h3.ref2va` · “Turbo V2 · 8 步 · 1080p”）；只供追溯与候选卡展示，不参与失效判断。Core 确定性工具（装配、Animatic、抽帧、混音）为 null |
| `output_asset_id` / `duration_seconds` | 产物与时长 |
| `error_code` / `message` / `progress` | 终态错误与最近观察 |
| `cancellation_requested` | 取消意图已持久化，等待 Provider 确认 |
| `retry_of` | 显式重试链 |
| `dismissed` | 从候选列表隐藏；不删除记录或 Asset |
| `language` | 仅 `narrator_voice`、`narration_audio`、`scene_final_video`、`final_video` 为 `zh` / `en`，其余必须为 null |
| `video_frame_request` | 抽帧来源视频、帧号、帧数、来源 Segment |
| `aspect_ratio` | 图片比例；角色参考图可指定 `IMAGE_ASPECT_RATIOS` 中的比例，造型设定图与地点全景图为 `2:1`，其余为 null（跟随项目画幅）；重试沿用 |
| `panorama_capture_request` | 仅 `panorama_capture`：全景 Asset、yaw、pitch、hfov 与项目画幅的冻结快照，进入重试签名 |
| `video_input_snapshot` | Segment 视频提交时的输入签名与首尾帧 Asset，用于判定 `inputs_outdated` 软提示 |
| `created_at` / `updated_at` | Generation 自身的 UTC 生命周期时间 |

### Kind 与 operation

| kind | operation | target | 说明 |
| --- | --- | --- | --- |
| `character_look_sheet` | generate | 造型 | 造型设定图；`input_asset_ids` 是身份参考，`prompt_text` 是实际提交的完整提示词（Core 编译或人类编辑），重试原样沿用 |
| `character_voice` | voice_design | 角色卡 | 参考音色设计 |
| `narrator_voice` | voice_design | 旁白身份（带 `language`） | 该语言的旁白参考音色设计；采用后只替换同语言的 `NarratorVoice` |
| `narration_audio` | synthesize | Cue（带 `language`） | 旁白 TTS |
| `generated_audio` | voice_design / synthesize | 项目 | 资产中心通用音频，不绑定任何节点 |
| `audio_effect`、`audio_trim` | process | 源 Asset | Core 本地同步处理，记录为隐藏 Generation |
| `video_audio_voice`、`video_audio_background` | separate | 源视频 | 成对创建，共享规范化 `batch_id` |
| `video_audio_remix` | remix | 源视频 | 两条 WAV 各自增益后重新封装 MP4 |
| `location_image` | generate / edit | 地点图片 | 普通图跟随项目画幅，全景图固定 2:1；输入为该条目显式保存的任意图片参考 |
| `panorama_capture` | process | 新建普通地点图片 | 从已选全景图确定性取景；必须带 `panorama_capture_request`，成功时直接选中产物 |
| `keyframe_image` | generate / edit / attach | Keyframe | `attach` 用于把抽帧产物登记为候选 |
| `video_frame` | process | 源视频 | 按帧号抽帧，产物型，不是候选 |
| `segment_video` | render / attach | Segment | `render` 记录 1–17 个输入、时长不短于 0.2 秒；`attach` 从资产库挂接 MP4，无输入、无 seed |
| `video_upscale` | upscale | Segment | 恰好一个源视频输入 |
| `scene_animatic` | assemble | Scene | Scene 动态分镜预览 |
| `scene_final_video` | assemble | Scene（带 `language`） | Scene 成片 |
| `final_video` | assemble | 项目（带 `language`） | 最终成片 |

## 领域长任务（`DirectorRun`）

| 字段 | 语义 |
| --- | --- |
| `kind` | `reference_proposal`、`script_proposal`、`location_plan`、`keyframe_plan`（四类外部 proposal 请求）；`director`（Keyframe 批次或地点成套生成的一轮执行）；`script_edit`、`narration_edit` |
| `status` | `running`、`waiting_user`、`waiting_jobs`、`completed`、`failed`、`cancelled` |
| `goal` | 用户原始目标（原话另存 `DirectorDirective`） |
| `authorization` | `edit_scopes`、`generation_scopes`（如 `keyframe:<id>`、`location:<id>`）、候选选择策略（恒为 `explicit_only`）、`final_approval` |
| `cursor` | `step`、`pending_target_ids`（尚未提交的目标）、`waiting_generation_ids`（只在 `waiting_jobs` 时非空） |
| `completed_command_ids` / `command_receipts` | 已完成命令及短回执，二者一一对应，用于恢复时跳过已执行步骤 |
| `waiting_reason` | 等待态必填，非等待态必须为空 |

同一项目最多一个非终态 run。

## 外部请求回执（`ApplicationRequest`）

| 字段 | 语义 |
| --- | --- |
| `request_id` | `sha256(caller_id, project_id, idempotency_key)`，幂等命名空间 |
| `request_digest` | 规范化命令名、参数、`expected_revision`、caller 角色/项目/能力/grant 的摘要 |
| `phase` | `pending`（已登记、尚未拿到结果）→ `committed`；中断后变为 `uncertain` |
| `result_revision` / `receipt_json` | 成功后的 revision 与完整回执，二者同时存在 |
| `generation_ids` | 这次请求创建的全部 Generation |

引用库人工确认也以 `reference.confirm_review` 回执的形式存在：回执数据里保存完整 `reference_library` 的 SHA-256；
引用内容一变，摘要不再匹配，就需要重新确认。

## 能力缺口审计（`CapabilityGapAlert`）

`project.apply_repair_patch` 每次真实修改都写一条：缺失的正式命令名、用户请求摘要、目标与 Scene scope、
规范化 operation 与反向 operation、前后 revision、发生次数与开闭状态。白名单字段只有
Scene `title/summary/setting`、Shot `composition/camera_movement/action/audio_direction/transition_in`、
Segment `duration_estimate_seconds/action`。

## Segment 无时间位置参考图片

`video_plan.segments[].reference_images` 为可选图片规划数组，未建立时为空且可省略。
每项保存 Core 分配的 `id`、`recipe_id`、`slot_index`（0–3）、`prompt_text`、`description`、
`visible_character_ids`、`character_references` 和 `reference_asset_ids`。它没有视频时间位置，也不保存独立选图状态；
实际提交的视频图片仍唯一来自 `recipes[recipe_id].bindings`。同一 recipe 的槽位位置不重复。
生成记录使用 `video_reference_image` kind，产物存于 `assets/images/video-references/`，回调只新增候选。
人类从候选或项目 Asset 选图时，Core 原子更新对应 recipe 输入簿；未填前面的槽位不占媒体名额。

边界规划 proposal 支持 `none/start/end/both`，合法策略由当前 recipe 的媒体槽位和 `require_any` 派生。
关闭端点不需要正文，已有正文与历史候选保留；角色进出不会自动把单帧改为双帧。
主流程对支持无边界帧的 recipe 不要求关键帧，媒体输入是否齐备由视频依赖检查回答。
