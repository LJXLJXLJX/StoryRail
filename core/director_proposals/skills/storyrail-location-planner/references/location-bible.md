# 地点设定方法

地点库是整部片子的“空间设定集”：先确定有哪些可以反复拍摄的物理空间，再写清每个空间里不会移动的东西。
它服务于跨镜头的背景一致，不负责讲剧情。

## 1. 按物理空间合并 Scene

- 先通读全部 Scene 的 `setting`、`summary` 和 Shot 动作，列出候选空间，再合并。
- 判断标准是“摄影机能否在同一组墙、地面与固定陈设之间拍到它们”。同一客厅的白天戏和夜戏是一个地点；
  客厅与相连的厨房若镜头会穿过门洞互相看见，可以作为一个室内地点；彼此看不见、要单独搭景的就分开。
- 名称用片中可识别的叫法（“林家客厅”“旧码头栈桥”），不要用“场景 3 地点”。
- 只出现一个镜头、背景完全虚化或纯色的空间可以不建地点，让该 Scene 保持未绑定；不要为了覆盖率硬造地点。
- 已有地点能覆盖的空间直接复用其 `id`，不要重复新建。

## 2. 变化建状态，不建新地点

同一空间在剧情中可见地变化时建状态（`states`），在 Scene 绑定里指定：

- 时间与光线：清晨、正午、黄昏、深夜、停电、烛光；
- 天气：雨夜、积雪；
- 布置与破坏：搬空后、布置成灵堂、打斗后一片狼藉、火灾后。

状态的 `description` 只写相对常态的差量（“窗外全黑，只有台灯亮，桌面散落文件”），不重复整体空间描述。
常态（剧本中最常出现的样子）不建状态，Scene 的 `state_id` 为 null 即表示常态。
室内与室外的划分看主图需要：能在一张环视全景里交代清楚的封闭或半封闭空间是 `interior`，
开阔街道、田野、海边等以一个主方向观看的空间是 `exterior`。

## 3. 固定空间描述

`description` 写结构、材质、尺度与风格：层高、墙面与地面材料、门窗位置关系、年代感。
只写不会移动的东西。人物、群众、剧情动作、可以拿起来的道具（杯子、信、手机）一律不写。

## 4. 室内：固定陈设与大致方位

- 列 4–12 个固定陈设（`fixtures`）：门、窗、壁炉、书架、床、吧台、楼梯、大型家具等，足以让观众认出“还是那个房间”。
- 每项给大致方位 `azimuth_deg`：把空间想成站在房间中央环视一周，0° 是全景正中（主要观看方向），顺时针增加，
  90° 在右侧，180° 在身后，270° 在左侧。方位是规划时的布局意图，主图选定后会由人按实际画面标定。
- 先定布局再定方位：主要对话发生在哪两个点位之间、门在哪一侧、主光从哪个窗来；相邻陈设方位至少相差约 20°，
  避免多个重点挤在同一方向。
- 陈设的 `description` 写外观（“深色胡桃木三层书架，摆满旧书”），不写方位文字，方位由 Core 编译进提示词。

## 5. 室外：地形、体量与主方向

室外地点不列大量陈设，`description` 写地形起伏、建筑体量与排布、道路或水岸走向，以及主观看方向能看到什么。
确实需要稳定识别的地标（灯塔、钟楼）可以作为少量陈设。

## 6. 主光

`key_light.description` 写主光来源与质感（“西侧落地窗的低角度暖色夕照，在地板上拉出长影”）；
`azimuth_deg` 与光源所在陈设或方向一致。主光是空间常态的光，状态的光线变化写在状态差量里。

## 7. 主图正文

`master_prompt_text` 是生成这张主图的静态环境正文：概括空间气质、材质、光线和风格，让陈设列表之外的空白处有依据。
不写人物、动作、图号、画幅、投影方式和陈设方位，这些由 Core 编译。

## 附录：`edit_locations` 操作字段

`edit_locations` 的顶层 `location_ids`、`scene_ids`、`shot_ids` 是本次允许改动的 scope，`operations` 是 1–100 个操作。
同一次调用内新建的项用 `key` 互引，回执 `data.created_ids` 给出 key → 正式 ID。

| op | 字段 |
|---|---|
| `create_location` | `key`、`name`、`kind`（`interior`/`exterior`）、`description` |
| `update_location` | `location_id`、`fields`：`name`、`kind`、`description`、`key_light`（`{description, azimuth_deg}` 或 null）、`master_prompt_text`、`master_reference_asset_ids` 中出现的项 |
| `delete_location` | `location_id`（仍被引用时拒绝并列出引用者） |
| `upsert_fixture` | `location_id`、`fixture`（已有 ID 整体替换，或新 key）、`name`、`description`、`azimuth_deg` |
| `delete_fixture` | `location_id`、`fixture_id` |
| `upsert_state` | `location_id`、`state`（ID 或 key）、`name`、`description` |
| `delete_state` | `location_id`、`state_id` |
| `create_view` | `location_id`、`key`、`fields`（必含 `name`、`purpose` 与一种朝向） |
| `update_view` | `view_id`、`fields`：`name`、`purpose`、`azimuth_deg`、`look_at_fixture_id`、`yaw_offset_deg`、`pitch_deg`、`hfov_deg`、`state_id`、`refine_prompt_text`、`reference_view_ids` 中出现的项 |
| `delete_view` | `view_id` |
| `calibrate` | `location_id`、`fixture_azimuths`（`{fixture_id: azimuth_deg}`）、`key_light_azimuth_deg`（null 表示不改） |
| `bind_scene` | `scene_id`、`location_id`（null 解除）、`state_id` |
| `bind_shot` | `shot_id`、`view_id`（null 解除） |
| `clear_master_selection` / `clear_view_selection` | `location_id` / `view_id` |

主图与视图的候选选择只有人类入口，Agent 只能清除选择。
