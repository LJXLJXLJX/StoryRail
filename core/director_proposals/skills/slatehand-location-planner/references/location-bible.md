# 地点设定方法

地点库是整部片子的空间设定集：先确定可以反复拍摄的物理空间，再保存稳定语义和按需生成的图片。它服务于跨 Scene 的
一致性，但不规定镜头从哪里拍，也不替 Keyframe 选择图片输入。

## 1. 按物理空间合并 Scene

- 通读 Scene 的 `setting`、`summary` 与 Shot 内容，判断摄影机是否仍在同一组墙面、地面、建筑或地形中。
- 同一客厅的白天与夜晚是一个地点；彼此不可见、需要单独搭景的空间分开。
- 名称使用片中可识别的叫法，不用“场景 3 地点”。已有地点能覆盖时复用其 ID。
- 一闪而过、完全虚化或抽象背景可以不建地点；Scene 允许不绑定地点。

## 2. 变化建状态

昼夜、天气、布置、破坏或停电等变化建立 `states`。状态说明只写相对常态的差量；常态不建状态，Scene 的
`state_id=null` 即表示常态。

## 3. 稳定空间事实

- `description` 写结构、尺度、材质、年代与风格。
- `fixtures` 写门窗、楼梯、大型家具、固定设备或地标；不保存相对于某张图的角度。
- `key_light.description` 写空间常态的主光来源与质感；某一状态独有的光线变化写进状态说明。
- 人物、群众、剧情动作和可随手移动的小道具不属于地点事实。

## 4. 独立图片

地点可有任意数量的独立图片，不需要先有“主图”。普通图片 `kind="image"`；只有确实需要环视空间并在查看器中手动取景时，
才创建 `kind="panorama"`。不同图片可以是建立画面、某个角落、材质细节、状态参考或用户认为有用的任何视角。

每张图片必须有强制 `description`，描述实际画面里可见的空间、陈设、光线和视角。`prompt_text` 是生成意图，不是图片说明。
图片生成后，用户或 Agent 应根据实际结果修订说明；全景取景生成的子图也必须在创建时填写说明。

全景图没有自动派生行为。用户点击全景图进入 3D 预览，调整 yaw、pitch、hfov 后点击取景，Core 创建一张普通图片并记录冻结的
`source`。子图的字节和说明从此独立，不因全景图换选或删除而变化。

## 5. Scene 绑定与生图语义

只有 Scene 保存 `location_id` 与可选 `state_id`。Shot 与 Keyframe 不绑定地点或地点图片。LLM 为 Keyframe 编写/生成画面时，
结合 Scene 的 setting、地点语义和叙事上下文自行构造空间；地点库图片不会自动成为图片输入。需要参考某张图时，应在相应的显式
参考图槽位中选择它，而不是依赖隐藏绑定。

## 附录：`edit_locations` 字段

顶层 scope 只有 `location_ids` 与 `scene_ids`；同次调用的新项使用局部 `key`，回执 `data.created_ids` 返回正式 ID。

| op | 字段 |
|---|---|
| `create_location` | `key`、`name`、`description` |
| `update_location` | `location_id`、`fields` 中出现的 `name`、`description`、`key_light`（`{description}` 或 null） |
| `delete_location` | `location_id`；仍被 Scene 绑定时拒绝 |
| `upsert_fixture` | `location_id`、`fixture`（已有 ID 或新 key）、`name`、`description` |
| `delete_fixture` | `location_id`、`fixture_id` |
| `upsert_state` | `location_id`、`state`（已有 ID 或新 key）、`name`、`description` |
| `delete_state` | `location_id`、`state_id`；仍被 Scene 使用时拒绝 |
| `create_image` | `location_id`、`key`、`fields`；必含 `name`、`kind`、`description`，可含 `prompt_text`、`reference_asset_ids`、`source` |
| `update_image` | `image_id`、`fields` 中出现的上述图片字段 |
| `delete_image` | `image_id`；保留历史 Asset 与 Generation，已生成的全景子图不随之删除 |
| `bind_scene` | `scene_id`、`location_id`（null 解除）、`state_id` |
| `clear_image_selection` | `image_id`；Agent 可清除选择，不能采用候选 |

`reference_asset_ids` 最多 5 张。`source` 只允许普通图片使用，形状为
`{panorama_image_id,yaw_deg,pitch_deg,hfov_deg}`。人类采用候选使用独立的 `location.select_image` 入口。
