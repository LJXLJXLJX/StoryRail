# 故事工作台

`StructuredDirectorWorkspace.tsx` 组合准备区、引用库、地点库与唯一故事工作台。
`StoryNavigation.tsx` 管理左侧 Scene → Segment 导航，Segment 标签按 `shot_ids` 显示覆盖的镜头（“镜头 1–2”，
与上一段共享边界 Shot 时附“（续）”），并展示 Core 提供的片段时长、视频 recipe 软时长上限
（`recipe_state.soft_duration_limit_seconds`）；Web 不重算这些规则。对白时长只读取已选 TTS WAV 的真实时长与校准结果。
Shot 在 Scene 页的“镜头设计”中列出，每行同时显示被哪些 Segment 覆盖；Segment 页顶部列出覆盖的 Shot 描述。
`script_index.ts` 是 Segment↔Shot 覆盖关系的只读查找，不复制 Core 的覆盖校验。
`NodeEditor.tsx` 暂存当前节点编辑输入，携带起点 project revision 保存，冲突保留草稿。Shot 编辑器只包含创作字段，
不保存地点或地点图片绑定。
Segment 编辑器用起始/结束镜头选择连续覆盖区间并写 `shot_ids`；与上一 Segment 共享边界 Shot 时显示并编辑
`boundary_from_previous`，不共享时说明这是剪辑边界。覆盖是否合法只由 Core 判断，保存失败原样显示服务端错误。
`script_structure.tsx` 提供 Scene 页的新增镜头入口（并入已有 Segment 或新建一个只覆盖它的 Segment，以 Scene 整卡保存，
新 Shot 不带地点字段）和 Segment 页的拆分/合并入口。拆分/合并提交 `script.apply_operations` 的
`split_segment` / `merge_adjacent_segments`，提交前用 `project.preview_impact` 展示服务端影响预览，确认后才写入；
拆分在 Shot 内部时两段共享该 Shot 且第二段必填延续说明；有对白时可按完整对白行选择分界，前后段原样回传稳定 ID，
保留生成候选和已选 TTS，仅由 Core 清空并重新校准发声起点。合并的 `shot_ids` 为两段并集。
**服务端是覆盖校验的唯一来源**：Web 只组装连续区间、消费快照、影响预览与 `allowed_actions`，不复制 Core 的覆盖校验规则。
`SceneMedia.tsx` 展示 Scene Animatic/成片与版本；其余媒体卡复用原有专业回调。
`script_draft.ts` 只提供新 Scene 的暂存输入（默认一个 Shot 与一个覆盖它的 Segment），正式 ID 仍由 Core 分配。
`keyframe.tsx` 的手动关键帧计划弹窗与 Keyframe Planner 读写同一组正文、可见角色和角色造型字段；地点语义由 Planner 工作集提供，
地点图片不会自动成为输入。“当前实际图片输入”只展示 Core 预览给出的角色参考、前置帧和手工辅助图及其 `input_roles` / `purpose`，
Web 不推断映射。
同一文件在首尾帧下方展示 Ref2VA“其他图片”：来源分为已选关键帧与资产库参考图，排除当前已启用边界，每张必填用途说明；它只写当前
recipe 的 `additional_images`，不进入 KeyframePlan，也不获得时间位置。`RecipeInputsControl.tsx` 的共享草稿 Provider
让该入口与视频卡共同编辑并原子保存同一份正文、bindings 和 params；视频卡不重复渲染图片槽位。

导航和正文使用 App 已有权威 snapshot，不叠加投影请求，不另存业务稿。
媒体选择和权限始终来自当前快照的 workspace_layers / allowed_actions。
Segment 的对白 TTS 卡片展示全部成功且未隐藏的候选：当前 Asset 明确标为“当前已选”，其余候选均可由人类试听后选择；
正文、音色或表演参数已变化时只显示 Core 的 `inputs_outdated` 软提示，不撤销选择入口。未被引用的候选可按
`allowed_actions` 隐藏；Web 不根据输入新旧过滤候选历史。整个对白 TTS 区可折叠并在标题展示已选进度；每句对白独立成可折叠卡片，
卡片标题保留序号、角色、音色路由与选择状态，展开后依次分为“对白与表演”“当前选择”“生成与候选”；候选列表也可单独折叠。
故事导航的每个 Segment 根据当前快照中的选择事实显示“待生成项目”：有对白但仍缺已选 TTS 时列出“对白 TTS”，仍缺已选视频时
列出“视频”（不以视频层是否已经解锁为门禁，以便提前暴露后续待办）；没有缺项时不显示该行。导航用稳定的颜色语义区分
视频软时长、待生成对白 TTS 与待生成视频；同一待生成行中的不同项目也分别着色，文字仍完整保留。项目概览提供全局
“按真实音频校准全部对白时长”：一次提交只校准已选齐全部对白 WAV 的 Segment，未选齐的 Segment 保持不变；Core 在一次
原子写入中按真实 WAV 时长加入基础停顿并更新对应 Segment 时长。
`location.tsx` 内的 `LocationLibrary` 在常驻工具栏“地点库”浮层中分级展示：入口页只列地点卡，点击后进入单个
地点详情，再查看其空间说明、状态与独立图片；新增地点使用独立浮窗，状态徽标只按 Core 的 `status` 着色；
`LocationBinding` 只嵌入当前 Scene，编辑地点与状态绑定。
`LocationEditor` 暂存编辑起点 revision；共用 `useLocationChange` 读取服务端影响预览，
确认后调用人类 HTTP 入口，预览过期时禁止保存，失败保留输入。
每张独立图片的权限、状态、生成文案与候选 ID 全部消费 Core snapshot。普通图与全景图都可任意选参考图生成；
图片“编辑”打开独立浮窗，参考图在项目资产库弹窗中多选，编辑浮窗展示已选缩略图并支持放大预览与移除；
全景图有选图时点击进入 Pannellum 3D 查看器，调整 yaw/pitch/hfov 后填写子图名称与强制说明并显式取景。
卡片复用 `references.tsx` 的卡片样式、`CardHeading`、`TextField/TextArea`、
`GenerationCandidateList`、`MultiImageAssetPickerDialog` 与 `ZoomableImage`。

隔离浏览器验收由 `scripts/harness/real_agent/workspace_browser_fixture.py` 服务正式 Core/HTTP 与 Web 构建，
图片/全景裁切使用合成 Provider，必须传仓库外的新目录，不接真实作品：

```sh
cd web && npm run build && cd ..
PYTHONPATH=.:tests .venv/bin/python scripts/harness/real_agent/workspace_browser_fixture.py \
  --stories-directory /tmp/storyrail-workspace-browser --port 18766
```

工具输出三个合成项目 ID；浏览器访问 `http://127.0.0.1:18766/`。
`--resume` 可恢复该工具建立的临时目录。合成 PNG 只用于交互/协议验证，不提供真实视觉验收结论。
