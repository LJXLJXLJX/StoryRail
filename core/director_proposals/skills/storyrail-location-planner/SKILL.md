---
name: storyrail-location-planner
description: 从完整结构化脚本一次规划地点库：按物理空间合并 Scene、为同一空间的变化建状态、列固定陈设与主光，逐 Shot 设计机位视图并提交 Scene/Shot 绑定；不生成图片、不选择候选。
---

# 地点规划

地点（Location）是跨 Scene 共享的固定物理空间。一个地点有一张主图（室内是 2:1 等距柱状全景，室外是项目画幅），
若干固定陈设、可见状态，以及供 Shot 绑定的机位视图。本 Skill 把整部脚本读成“有哪些空间、每个镜头从哪里看向哪里”，
一次提交为 proposal；图片生成与选图都在提交之后由用户另行决定。

## 何时使用

- 用户明确要求规划、重新规划或补充地点；或 Director 采纳 workflow 中“规划地点”这一推荐动作。
- “推进”“下一步”“继续”不等于规划地点。此时只读取 workflow，向用户说明可选动作，等用户明确选择。
- workflow 的 `recommended_next_actions` 都是不阻塞主流程的可选建议：读到后向用户提议（说明收益与可选性），
  收到明确指令再执行，不自行发起规划、成套生成或批次继续。
- 推荐只在解锁视觉生产之前出现；解锁本身就是跳过，此后 workflow 不再推荐规划与成套生成，
  只保留在途地点批次的继续提示。
- 只改一两个字段、删除、标定、解除选择时不发起规划，直接用 `edit_locations`（字段形状见
  [`references/location-bible.md`](references/location-bible.md) 附录）。

## 入口

1. `read_professional_contract(capability="location")` 读本 Skill；`read_professional_workset(capability="location")`
   读当前事实：`director_plan_markdown`、`scenes`（每个 Scene 带全部 Shot 的构图、运镜、动作、可见角色名和当前绑定）、
   `location_library`（含 `master_selected`、`calibrated`、视图 `has_crop` / `has_selected_image`）、`aspect_ratio`、`image_prompt`。
2. `submit_proposal(capability="location", payload={"action": "request", "raw_user_instruction": 用户原话})` 建立请求；
   返回的工作集不可变，规划期间项目其它写入被锁定。
3. 按下文顺序设计后 `submit_proposal(capability="location", payload={"action": "submit", "request_id", "proposal"})`。
   放弃时 `action="cancel"`；项目变化导致工作集过期时先取消再重新请求。

## 设计顺序

1. **地点与状态**：按物理空间合并 Scene，判断哪些差异是同一空间的状态。方法见 [`references/location-bible.md`](references/location-bible.md)。
2. **陈设与主光**：室内列 4–12 个固定陈设并给大致方位，室外写地形、建筑体量与主方向；写主光。
3. **视图覆盖**：逐 Shot 判断镜头朝哪、身后是什么，设计最少而够用的视图。方法见 [`references/view-coverage.md`](references/view-coverage.md)。
4. **绑定**：`scene_bindings` 把 Scene 绑到地点（与状态），`shot_bindings` 把 Shot 绑到所在 Scene 地点的视图。
5. **自检**后提交。

## proposal 规则

- **增补语义**：未列出的地点、陈设、状态、视图和绑定保持不变，不会被删除。规划不能删除任何东西。
- **完整项**：列出的每一项都是完整项。已有项给正式 `id` 并整体替换，所以修改已有项时要把它不变的字段也照原样给出；
  新建项给局部 `key`（小写字母开头的 `[a-z0-9_-]`），同一 proposal 内唯一。
- **局部键互引**：视图的 `look_at_fixture_id`、`state_id`、`reference_view_ids` 只能引用同一地点的项；
  绑定的 `location_id`、`state_id`、`view_id` 可以是正式 ID，也可以是本 proposal 新建项的 key。Core 落库时映射为正式 ID。
- **方位**：已有陈设与主光的 `azimuth_deg` 给 `null` 表示保持现值。已选主图的地点以人工标定为准，规划不能改动其方位。
- **失效**：修改已有视图的几何、细化正文、参考视图或状态，会按地点失效规则清除该视图及下游 Keyframe 的选择；
  只是想看看效果时不要改已有视图，新建一个。

## 正文只写静态环境

- `master_prompt_text`、`refine_prompt_text` 只写空间本身：结构、材质、陈设外观、光线质感、时代与风格。
- 不写人物、群众、剧情动作、临时道具，也不写图号、画幅、“全景/等距柱状”等投影说明和陈设的方位度数；
  这些由 Core 按图片插件 manifest 的 `image_prompt` 与陈设方位统一编译。
- 室内视图的细化由 Core 固定编译空间扭曲与清晰度修复指令，不使用 `refine_prompt_text`，室内视图留空；它只用于室外转向正文。
  正文不用景别词“全景”（会被当成全景投影），写“远景”。
- `image_prompt.plugin_skills` 非空时，正文组织方式遵守随插件发布的专业 Skill。

## 视图朝向

全景标定（选定主图后由人确认陈设实际方位）完成前，`look_at_fixture_id + yaw_offset_deg` 定义的视图无法裁切。
现阶段视图一律用 `azimuth_deg` 定义，方位与同一地点陈设的大致方位保持一致。标定后可以改用相对陈设定义，
让视图自动跟随标定，但不要默认使用。

## 自检

- 同一物理空间是否只建了一个地点；时间、光线、破坏、布置变化是否建成状态而不是新地点？
- 室内陈设是否 4–12 个、各有大致方位，且彼此方位不冲突；是否混入了人物或临时道具？
- 每个绑定地点的 Shot 是否都有视图；正反打是否成对（方位相差约 180°）；同机位的多个 Shot 是否共用视图？
- `hfov_deg` 是否与景别匹配；每个地点的视图数是否以覆盖为准（通常 3–8 个）？
- 正文是否只有静态环境，没有图号、画幅、人物与动作？

提交后告诉用户：地点与绑定已保存，主图与视图需要用户明确要求才会生成，候选由用户选择。
