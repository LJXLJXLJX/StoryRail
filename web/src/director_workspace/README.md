# 故事工作台

`StructuredDirectorWorkspace.tsx` 组合准备区、引用库、地点库与唯一故事工作台。
`StoryNavigation.tsx` 管理左侧 Scene → Segment 导航，Segment 标签按 `shot_ids` 显示覆盖的镜头（“镜头 1–2”，
与上一段共享边界 Shot 时附“（续）”），并展示 Core 提供的片段时长、视频 recipe 软时长上限
（`recipe_state.soft_duration_limit_seconds`）与 `dialogue_timing_warnings` 对白时长提示；Web 不重算这些规则。
Shot 在 Scene 页的“镜头设计”中列出，每行同时显示被哪些 Segment 覆盖；Segment 页顶部列出覆盖的 Shot 描述。
`script_index.ts` 是 Segment↔Shot 覆盖关系的只读查找，不复制 Core 的覆盖校验。
`NodeEditor.tsx` 暂存当前节点编辑输入，携带起点 project revision 保存，冲突保留草稿。Shot 编辑器含创作字段与
空间参考建议：`view_id` 选择器只列本 Scene 绑定地点的视图，未绑定地点时只能选择不使用。
Segment 编辑器用起始/结束镜头选择连续覆盖区间并写 `shot_ids`；与上一 Segment 共享边界 Shot 时显示并编辑
`boundary_from_previous`，不共享时说明这是剪辑边界。覆盖是否合法只由 Core 判断，保存失败原样显示服务端错误。
`script_structure.tsx` 提供 Scene 页的新增镜头入口（并入已有 Segment 或新建一个只覆盖它的 Segment，以 Scene 整卡保存，
新 Shot 可带 `view_id`）和 Segment 页的拆分/合并入口。拆分/合并提交 `script.apply_operations` 的
`split_segment` / `merge_adjacent_segments`，提交前用 `project.preview_impact` 展示服务端影响预览，确认后才写入；
拆分在 Shot 内部时两段共享该 Shot 且第二段必填延续说明，合并的 `shot_ids` 为两段并集。
**服务端是覆盖校验的唯一来源**：Web 只组装连续区间、消费快照、影响预览与 `allowed_actions`，不复制 Core 的覆盖校验规则。
`SceneMedia.tsx` 展示 Scene Animatic/成片与版本；其余媒体卡复用原有专业回调。
`script_draft.ts` 只提供新 Scene 的暂存输入（默认一个 Shot 与一个覆盖它的 Segment），正式 ID 仍由 Core 分配。
`keyframe.tsx` 的手动关键帧计划弹窗与 Keyframe Planner 读写同一组地点视图字段：
视图选择器只列所属 Segment 的 Scene 绑定地点的视图（名称、purpose、状态、Shot 绑定、未选图提示），
帧当前引用其它地点的视图时作为“当前值”保留并标明来源，Scene 未绑定地点时只能选择不使用并给出提示；
从不使用选回视图默认 `reference`，选择 `none` 时理由可选（最多 500 字，空白按 null 保存）。“当前实际图片输入”逐图展示 Core 预览给出的
底图/参考位置、`input_roles` 与 `purpose`，Web 不推断映射。
同一文件在首尾帧下方展示 Ref2VA“其他图片”：来源分为已选关键帧与资产库参考图，排除当前已启用边界，每张必填用途说明；它只写当前
recipe 的 `additional_images`，不进入 KeyframePlan，也不获得时间位置。`RecipeInputsControl.tsx` 的共享草稿 Provider
让该入口与视频卡共同编辑并原子保存同一份正文、bindings 和 params；视频卡不重复渲染图片槽位。

导航和正文使用 App 已有权威 snapshot，不叠加投影请求，不另存业务稿。
媒体选择和权限始终来自当前快照的 workspace_layers / allowed_actions。
`location.tsx` 内的 `LocationLibrary` 在常驻工具栏“地点库”浮层中以左侧地点索引 + 右侧详情展示：
详情按主图（含主光）→ 固定陈设 / 地点状态 → 机位视图卡分区，状态徽标只按 Core 的 `status` 着色；
`LocationBinding` 嵌入当前 Scene/Shot，展示地点/状态或 Shot 的空间参考建议并提供改绑；
删除视图的影响预览把“将清除的软引用 Shot”与失效内容分开列出。
`LocationEditor` 暂存编辑起点 revision；共用 `useLocationChange` 读取服务端影响预览，
确认后调用人类 HTTP 入口，预览过期时禁止保存，失败保留输入。
主图与视图的权限、状态、生成文案、有效裁切及候选 ID 全部消费 Core snapshot。
室内视图第一次点击只裁切，完成后按钮显示“第二步：细化视图”，再次显式点击才细化；
裁切底图只读并与已选视图并排，2:1 主图用横向滚动条带。
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
