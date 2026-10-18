---
name: storyrail-location-planner
description: 从完整结构化脚本规划跨 Scene 共享的地点语义、状态、固定陈设、可选独立图片和 Scene 绑定；不生成图片、不选择候选，也不把 Shot 或 Keyframe 绑定到地点图片。
---

# 地点规划

地点（Location）是跨 Scene 共享的固定物理空间。它保存空间描述、稳定陈设、主光、状态和一组彼此独立的图片。
图片不是“主图 → 视图”的树，也不绑定 Shot 或 Keyframe。全景图只是可以在 3D 查看器里取景的特殊图片；是否创建全景图、
是否从中取景都由用户按需决定，规划时不要为每个镜头主动派生视角。

## 何时使用

- 用户明确要求规划、重新规划或补充地点；或 Director 采纳 workflow 中“规划地点”这一推荐动作。
- “推进”“下一步”“继续”不等于规划地点。只读取 workflow、说明地点规划是可选项，等待用户明确选择。
- 只改少数字段、增删图片或清除选图时不发起规划，直接用 `edit_locations`。
- 地点规划不阻塞视觉生产；没有地点库或 Scene 未绑定地点时，Keyframe 与视频仍可继续。

## 入口

1. `read_professional_contract(capability="location")` 读本 Skill；`read_professional_workset(capability="location")`
   读 `director_plan_markdown`、完整 Scene/Shot 上下文、当前地点库、项目画幅与图片插件约定。
2. `submit_proposal(capability="location", payload={"action":"request","raw_user_instruction":用户原话})` 建立请求；
   返回的工作集不可变，规划期间冲突写入被锁定。
3. 设计后以 `action="submit"` 提交；放弃用 `action="cancel"`。工作集过期时取消后重新请求。

## 设计顺序

1. **地点与状态**：按物理空间合并 Scene；昼夜、天气、布置或破坏变化建状态，不复制地点。
2. **稳定事实**：写空间描述、固定陈设和主光。陈设不记录相对于某张图片的方位。
3. **可选图片**：只在用户需求或脚本一致性确有价值时规划图片。普通图片用 `kind="image"`；需要环视与后续手动取景时才用
   `kind="panorama"`。不要默认创建全景图，也不要预先派生镜头视图。
4. **Scene 绑定**：`scene_bindings` 只把 Scene 绑定到地点与可选状态。Shot 不保存地点或图片引用。
5. 自检后提交。

## 图片规则

- 每张地点图片都是独立条目，有自己的 `name`、`kind`、强制 `description`、可选 `prompt_text`、
  `reference_asset_ids` 与人类选定的候选。
- `description` 是人或 Agent 根据图片实际内容填写的纯文本说明，必须能让后来者不看生成提示词也理解画面；不得只复制
  `prompt_text`。规划还没有真实图片时，应明确写预期承载的画面内容，生成并审阅后再按实际结果修订。
- `prompt_text` 是下一次生成意图，和实际图片说明分离。只写静态环境，不写人物、剧情动作、图号或画幅标签。
- `reference_asset_ids` 可任意选择至多 5 张项目图片作为本次生图参考，不要求来自同一地点，也没有“主图”特权。
- `source` 只用于记录普通图片由全景取景而来的冻结来源 `{panorama_image_id,yaw_deg,pitch_deg,hfov_deg}`。
  通常由 Web 的全景查看器按钮创建，不应由 Planner 批量预造。取景结果生成后是独立图片，不随来源变化或删除而失效。
- 图片生成只新增候选；候选选择只有人类入口。全景取景是确定性处理，完成时直接给新建子图选中产物。

## proposal 规则

- proposal 是增补：未列出的地点、陈设、状态、图片和 Scene 绑定保持不变；规划不能删除。
- 列出的已有项使用正式 `id` 并给出完整值；新项使用同一 proposal 内唯一的局部 `key`。
- 图片 `source.panorama_image_id` 必须引用同一地点的全景图片，可使用正式 ID 或本 proposal 中的 key。
- Scene 的 `state_id` 必须属于它绑定的地点；`location_id=null` 时 `state_id` 也必须为 null。
- 修改图片的名称、说明、生成正文或参考图不会让既有候选失效；要改变采用结果，应生成新候选并由人类重新选择。

## 自检

- 同一物理空间是否只建一个地点；可见变化是否建成状态？
- 是否只写稳定空间事实，没有把人物、剧情动作或可移动小道具当成地点陈设？
- 图片是否真有复用价值，而不是为每个 Shot 机械建图？是否把全景图误当成必需根节点？
- 每张图片是否有具体、可读、与 `prompt_text` 分离的说明？
- 是否只绑定 Scene，没有给 Shot 或 Keyframe 发明地点图片字段？

提交后告诉用户：地点语义与可选图片计划已保存；图片必须由用户明确要求才生成，候选仍由用户选择，全景图不会自动派生子图。

具体字段见 [`references/location-bible.md`](references/location-bible.md)。
