# Playground Web

`PlaygroundPage` 组合能力列表、参数表单与运行流；`usePlaygroundScheduler` 负责可见性感知轮询。
`forms/RecipeForm` 按当前绑定的 recipe 渲染全部模型表单（含向量、高级参数与声明式素材过滤）；确定性工具在 `forms/` 提供手写表单，`RunCard`/`CompareDrawer` 展示 run，`AssetPanel`/`CopyToProjectDialog` 处理资产与跨域复制。
输入标签预览来自 Core，链式输入目标来自 recipe slots。
`forms/PanoViewForm` 是全景裁切表单：带正前/右/后/左与 hfov 60/90 预设，素材选择器和“作为输入”只列出
`allowed_actions` 含 `pano_view` 的 2:1 全景；“四个方向依次裁切”由 `RunForm` 按 `batchVariants` 逐条提交，
不存在批量后端接口。
本目录只消费 Core 的 Playground 快照、错误和 `allowed_actions`，不推断 run 能做什么。

`AssetPanel` 是悬浮的独立窗口：标题栏可拖动（`clampOffset` 保证窗口至少有一部分留在视口内），窄屏下占满视口；
卡片统一为 4:3 媒体框，图片用 `ZoomableImage` 点击放大，音频用 `AssetAudioPlayer` 而不是会撑破卡片的原生
`<audio controls>`；资产列表只按 `allowed_actions` 决定能否勾选删除；
“全选”只勾选当前类型过滤下可删除的资产，“删除所选”的计数与删除范围同样只算当前可见的已勾选资产。
