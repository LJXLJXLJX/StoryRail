# Director Proposals

本目录保存外部 Agent 与 Core 共享的纯专业输入、schema、parser、validator 和 Skill 资源；不执行模型或加载厂商 SDK。

- `reference_library.py`：角色卡与独立旁白身份 proposal；
- `script.py`：首次脚本、局部脚本回改和 Scene/Shot/Segment 输入；
- `narration.py`：旁白审核上下文与参数更新 proposal；
- `keyframe.py`：Keyframe 规划上下文、完整计划和 command operations proposal；环境字段三项均为 null 表示未声明，
  由 `keyframe_codec.resolve_keyframe_environment` 按 Segment 首/末覆盖 Shot 的视图继承（有视图 reference，无视图 none），显式 none 理由可选（空白归一为 null）；
- `location.py`：地点规划输入（每个 Scene 的全部 Shot 与可见角色名、已有地点归属与方位）和增补式 proposal：
  `locations[]`（每项给已有 `id` 或新建 `key`，含陈设、状态、视图）、`scene_bindings[]`、`shot_bindings[]`（Shot 的空间参考建议）。
  未列出的项不删除；列出的已有项整体替换；新建项用局部 key 互引，key 规则与 `location.apply_operations` 相同；
- `video_prompt.py`：模型无关的单 Segment 视频提示词 proposal。
- `compiler_intent.py`：严格的跨 lane 意图交接，保留用户原话、显式约束、Director 假设和类型化 scope。
  `core_facts` 只允许来源标记，不接收模型声称的项目事实；真正事实仍由上述能力专用输入类型提供。
  共享边界硬约束仅允许 Keyframe plan，Core 仍验证真实邻接、目标 scope 和最终 proposal。
  相邻 Segment 的边界默认是两个独立 Keyframe：Planner 的 frame_strategy 按原样生效，后一段独立首帧沿用上一段尾帧描述作为连续性起点；只有显式 `share_boundary` / `continues_from_previous` 才共享同一对象。

内部 intent 在需要嵌入 JSON 时作为对象发送，不把整份 JSON 二次转义为字符串；
普通手工用户文本仍是文本，不被自动解释为事实或命令。HTTP 与 project schema 照常严格校验。

这些类型只表达候选提案，不授予项目写权限。Core 仍在当前 revision、授权 scope 和领域不变量下校验后才能
写入 `project.json` 或提交 Provider。

各 `*_codec.py` 拥有严格 JSON schema、parser 和纯上下文编译。`location_codec.py` 按当前事实校验归属（Scene/Shot 存在、
已有项属于所在地点、Shot 视图属于所在 Scene 的地点、视图参考无环），对已选主图的地点拒绝改动陈设与主光方位（`null` 保持现值），
再按“被参考视图先落库”的顺序编译为 `location.apply_operations` 的同一组操作；落库、key 映射与失效级联只走地点库唯一 mutation。视频厂商的专业格式由当前插件负责，Core 工作集交付它的资源。
`professional_contracts.py` 只按六个固定能力读取 `skills/` 的 Skill 和参考资源，返回摘要，不接受任意路径。
六个能力 Skill 与共享的一致性复核 Skill 随 Core 发布；插件的专业 Skill 随插件发布。
