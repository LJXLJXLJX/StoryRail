# 专业 Skill 资源

六个通用能力（引用库、脚本、旁白、地点、Keyframe、视频提示词）的纯 Markdown/YAML 资源，由 professional_contracts 固定映射读取。
各目录的 SKILL.md 是入口，方法细节放在各自 `references/`；不包含 Agent 执行器或会话状态。

地点规划入口 `storyrail-location-planner` 只在用户明确要求规划地点（或 Director 采纳推荐的规划地点动作）时使用，
“推进/下一步”不等于规划地点；`references/location-bible.md` 讲地点合并、状态、陈设与主光，并附 `edit_locations` 各操作的字段形状，
`references/view-coverage.md` 讲逐 Shot 的视图覆盖。主图与视图正文只写静态环境，图号、画幅与全景写法由 Core 按图片插件编译。

六个专业能力共同提供 `shared/storyrail-consistency-review/SKILL.md`（正文及 SHA-256），通过 `read_professional_contract` 读取。它是内容修改的共享工作原则，不是第七个生产阶段：Agent 修改前预检授权范围内联动，提交后重读核对；只读校对不修改，超范围先说明。人工保存提醒只复制有边界的任务，不发送消息或增加生产门禁。

Agent 启动提示、MCP instructions 和 Web 校对任务里的一致性说明，以本文件为唯一事实源；
加载器只引用 `consistency_instruction.md` 或 `read_professional_contract(include=["consistency-review"])`，
不在这三处各自改写新的规则。`read_professional_contract` 默认只返回专业 Skill 与参考；
需要共享校对原则时必须显式传 `include=["consistency-review"]`。

Keyframe 入口 `storyrail-keyframe-planner` 的「地点视图的使用」规定：视图是软参考，环境三项写 null 即继承 Shot 视图作为空间参考提交，
也可按本帧朝向自由改选本 Scene 地点的视图或用 `none`（理由可选），改写不需理由；`edit` 只在用户明确要求严格贴合时使用；
正文不重述视图已有的陈设。
`references/cinematic-keyframe-design.md` 讲机位与视图的对应和正反打背景，`references/cinematic-frame-prompting.md` 讲各使用方式下的正文分工。

视频入口 `storyrail-video-prompt` 读取当前 recipe 工作集；H3 专业 Skill 位于 `core/model_providers/minimax_h3/skills/`，随插件通过工作集交付。
