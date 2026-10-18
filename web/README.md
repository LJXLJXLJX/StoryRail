# StoryRail Web

React + TypeScript + Vite 单页应用。首页导入完整导演方案并管理项目；项目打开后直接进入结构化导演台。Web 只消费 Core 的资源、进度、错误、
影响预览与 `allowed_actions`，不维护状态机、不推断依赖或权限。上传直接发送媒体字节，不把媒体编码进 JSON。

## 目录

| 位置 | 职责 |
| --- | --- |
| `App.tsx` / `AppView.tsx` | 项目列表、导入、路由与全局顶栏（任务进度、全局 Provider 设置、连接 Agent） |
| `api/` | `types.ts` 与 `validation.ts` 由 `scripts/gen_web_contracts.py` 从 Core 类型生成；`api.ts` 负责请求与错误翻译 |
| `director_workspace/` | 唯一故事工作台：层级导航、当前节点正文与媒体、各专业编辑器与候选 UI |
| `asset_center/` | 资产中心 |
| `playground/` | Playground 页面（独立于项目）；`forms/RecipeForm.tsx` 渲染模型槽位与参数 |
| `provider_settings/` | 全局能力绑定与实例设置；`SettingField.tsx` 供设置、旁白、资产音频与 recipe 表单共用 |
| `ExternalAgentConnect.tsx` | 「连接 Agent」面板：选择 Agent 并复制当前项目或 Playground 的启动命令 |
| `CreativePartnerPrompt.tsx` / `creativePrompts.ts` | 导入页可复制的创作搭档与方案整理提示词；`creative-partner-prompt.md`、`director-plan-convert-prompt.md` 共用 `director-plan-format.md` 交付格式 |

## 导演台

- 项目创建后立即进入导演台；引用库尚未建立时提示用户在外部 Agent 中整理引用。原始导演方案可只读查看。
- 结构化脚本生成后，旁白、Keyframe、视频与成片都嵌在同一个 Scene → Shot → Segment 层级里累加显示，不切换专用页面；
  地点库是常驻工具栏中的浮层，Scene 显示所绑定的地点与状态，Shot 显示所绑定视图的缩略图。
  导航与正文使用 App 已有的权威快照，不叠加投影请求。
- 局部保存携带编辑起点 project revision；失败或并发更新时保留草稿。视频生成依赖、recipe 与提示词正文位于同一个显式编辑区：进入编辑不修改 Core，
  保存提交完整草稿，放弃恢复服务端快照。对白、关键帧或参考关系变化后提示用户检查视频提示词，不自动重写正文。
- 人工保存内容字段后显示一致性提醒，可复制一段有边界的任务发给当前项目的 Agent；提醒是会话临时数据，不发送消息、不增加生产门禁。
- 图片引用预览在 revision 后台变化时保留上一版可读结果，直到相同输入的新预览返回，避免闪烁。
- 顶栏按 TTS、图片、视频汇总未隐藏 Generation 的“已结束/总任务”；已结束包含成功、失败、取消与提交结果未知，悬停区分。
- Segment 视频提交失败或结果未知时，视频卡持续显示失败环节、服务端原因与实际 seed，并提供回填 seed 与删除失败记录。
- 有活动任务时轮询 `generations/refresh` 推进 Provider 观察；闲置时低频读取快照；页面隐藏时暂停。

## 资产中心

图片分为角色参考、地点图片、全景取景图、Keyframe 与抽帧图；导入本地图片必须先选分类（全景取景图与抽帧图由 Core 生成，不接受导入）。音频与视频页导入 WAV/MP4，Core 从实际字节读取时长，
只登记为未绑定 Asset。音频栏目可按当前 voice.design / speech.synthesize recipe“创建音频”：领域输入提供描述、正文或参考 WAV/文字稿，机制参数按 editable_params 渲染，发送 recipe_params。
可对 WAV 截取或后处理（preset、strength、seed、起止时间），产出保留原文件的副本。每个 MP4 提供“处理音轨”：分离并预览人声与背景，
分别调节音量及其时间区间、即时试听、选择原始或处理后副本，再重新混音为新 MP4。使用状态与删除许可只看 Core 给出的 `usage_reasons` 与
`allowed_actions`。

## Playground

入口 `/?playground=1`。三栏：按图像/语音/视频/音频分组的能力列表、按 Core 目录声明渲染的参数表单（字段下方标注 wire 键名，支持定长向量）、运行流卡片（过滤、参数摘要、
产物预览、备注、重试/取消/隐藏，以及把产物“作为输入”送到其它能力）。顶部「资产」打开悬浮资产面板：导入、多选删除、查看来源、复制到项目
或从项目复制。素材筛选按 slot 媒体类型和时长约束，输入标签来自 Core 只读预览。复制到项目先读取目标 revision，遇到 `revision_conflict` 自动重读并重试一次。有活动 run 时每 1.25 秒刷新 Provider 状态，
闲置时每 10 秒读取快照，页面隐藏时暂停。规格见 [Playground](../docs/playground.md)。

## 开发

```text
cd web
npm run dev
```

开发时 Vite 把 `/api` 代理到 `127.0.0.1:8765`。仓库根目录的 `start.sh` 先构建生产 bundle，再用 Vite preview 提供页面与相同代理。
