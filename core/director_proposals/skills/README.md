# 专业 Skill 资源

六个通用能力（引用库、脚本、旁白、地点、Keyframe、视频提示词）的纯 Markdown/YAML 资源，由 professional_contracts 固定映射读取。
各目录的 SKILL.md 是入口，方法细节放在各自 `references/`；不包含 Agent 执行器或会话状态。

地点规划入口 `storyrail-location-planner` 只在用户明确要求规划地点（或 Director 采纳推荐的规划地点动作）时使用，
“推进/下一步”不等于规划地点；`references/location-bible.md` 讲地点合并、状态、陈设与主光，并附 `edit_locations` 各操作的字段形状，
`references/view-coverage.md` 讲按实际复用价值积累独立地点图片；不为 Shot 机械预建视图。普通图与全景图都可选，
每张图片必须维护与生成提示词分离的实际内容说明，全景图只在用户需要时通过 3D 查看器手动取景。

六个专业能力共同提供 `shared/storyrail-consistency-review/SKILL.md`（正文及 SHA-256），通过 `read_professional_contract` 读取。它是内容修改的共享工作原则，不是第七个生产阶段：Agent 修改前预检授权范围内联动，提交后重读核对；只读校对不修改，超范围先说明。人工保存提醒只复制有边界的任务，不发送消息或增加生产门禁。

Agent 启动提示、MCP instructions 和 Web 校对任务里的一致性说明，以本文件为唯一事实源；
加载器只引用 `consistency_instruction.md` 或 `read_professional_contract(include=["consistency-review"])`，
不在这三处各自改写新的规则。`read_professional_contract` 默认返回专业 Skill 与参考；地点与 Keyframe 还附带
`global/storyrail-image-prompt-writing/SKILL.md`，其唯一源文件位于 `core/model_providers/skills/`，是跨图片插件的强制写作规范；
需要共享校对原则时必须显式传 `include=["consistency-review"]`。

`storyrail-keyframe-sequence` 是 Keyframe 契约附带的生产执行 Skill（资源名 `production/storyrail-keyframe-sequence/SKILL.md`）：
用户要求连续生成多个 Segment 的关键帧时，按依赖与锚点帧排序、逐帧看图审核、诊断重试、选图或原样复用已选帧后再推进批次。
它不产生 proposal、不新增 Core 门禁，画面决定仍以 planner 为准。

Keyframe 入口 `storyrail-keyframe-planner` 读取 Scene 地点、状态与地点图片说明来理解空间，但不输出地点图片绑定；只有人类显式加入
Segment 辅助参考的 Asset 才进入生图。`references/cinematic-keyframe-design.md` 讲从 Shot 自行推导空间与正反打背景，
`references/cinematic-frame-prompting.md` 讲如何把地点事实写进静态画面正文。

视频入口 `storyrail-video-prompt` 读取当前 recipe 工作集与 `context.shots`（多 Shot Segment 的段内切镜按顺序写成软约束，首尾 Picture 只锚定首末 Shot）；H3 专业 Skill 位于 `core/model_providers/minimax_h3/skills/`，随插件通过工作集交付。
