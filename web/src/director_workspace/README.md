# 故事工作台

`StructuredDirectorWorkspace.tsx` 组合准备区、引用库、地点库与唯一故事工作台。
`StoryNavigation.tsx` 管理左侧层级呈现；`StoryReader.tsx` 只挂载当前目标正文与媒体。
`NodeEditor.tsx` 暂存当前节点编辑输入，携带起点 project revision 保存，冲突保留草稿。
`SceneMedia.tsx` 展示 Scene Animatic/成片与版本；其余媒体卡复用原有专业回调。
`script_draft.ts` 只提供新 Scene 的暂存输入，正式 ID 仍由 Core 分配。
`keyframe.tsx` 的手动关键帧计划弹窗与 Keyframe Planner 读写同一组地点视图字段：
视图选择器只列所属 Segment → Shot → Scene 绑定地点的视图（名称、purpose、状态、Shot 绑定、未选图提示），
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
`LocationBinding` 嵌入当前 Scene/Shot，展示地点/状态或已选视图缩略图并提供改绑。
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
