# Director Commands

本目录定义外部 Agent、Web 与 Core 之间稳定的类型化命令边界。完整命令清单见 [命令目录](../../docs/commands.md)，
分发与提交流程见 [控制流](../../docs/control-flow.md)。

## 职责

- `models.py`：`DirectorStep`、`DirectorCommand`、`CommandReceipt`、Keyframe 与 repair contract；
- `registry.py`：单一模块级命令表（parser + Store handler + scope 规则）、确定性分派与 repair 规范化；
- `script_operations.py`：脚本原子操作 parser；
- `narration_commands.py`：旁白 Cue 修改与解除选择 parser；
- `video_commands.py`：视频正文、recipe 输入、recipe 切换与解除选择 parser；
- `location_operations.py`：地点库编辑与 Scene/Shot 地点绑定（`location.apply_operations`）及人类主图/视图选择 parser；
- `generation_commands.py`：Generation 单目标与等待集合 parser；
- `final_commands.py`：Animatic、Scene 成片、最终成片选择与批准 parser；
- `run_commands.py`：DirectorRun 查询、恢复与取消 parser；
- `context_scope.py`：从消息与最近指代定位到轻量 ID 索引的只读辅助；不授予命令 scope 或 caller 权限。

所有 parser 都拒绝缺失字段与未声明字段。Registry 在命令 revision 上执行 scope、ID、领域关系与幂等校验；Store 以一次原子替换提交
最终对象图。相同目标状态返回 noop；真实变化通过回执报告 `changed_ids`、`invalidated`、`preserved`。

Registry 只负责确定性项目写入；proposal 与工作流确认（`reference.confirm_review`、`script.confirm`、
`visual_production.unlock`）也经同一查表入口委托给对应模块。Provider 提交、媒体导入与异步观察由 `StructuredDirectorService` 的类型化
handler 协调，回到同一 Store 与 Generation 规则。Web 按钮与 Agent 命令共享这些 handler，不存在 UI 直接写状态的路径。

`location.apply_operations` 是人类与 Agent 共用的地点编辑入口：15 种操作（地点、陈设、状态、视图的增改删，`calibrate`，`bind_scene`、`bind_shot`，`clear_master_selection`、`clear_view_selection`）；scope 同时声明 `location_ids`、`scene_ids`、`shot_ids`，同一 patch 新建的地点、陈设、状态和视图用局部 `key` 互相引用，回执 data 返回 `created_ids`（key → 正式 ID）。候选选择 `location.select_master` / `location.select_view` 只开放给人类，不在 Agent 操作白名单。

`video.update_recipe_inputs` 原子保存 Segment 视频正文、当前 recipe 的 `bindings` 与机制 `params`，人类与 Agent 共用同一 parser 与校验；`video.clear_selection` 仍只开放给人类。

`project.apply_repair_patch` 只处理没有正式命令覆盖、已授权且目标唯一的白名单字段，并持久化 `CapabilityGapAlert`；
只涉及 Shot/Segment 字段时由纯翻译函数转为 `script.apply_operations`，不递归分派。

DirectorRun 的等待集合只来自步骤明确给出的 `generation_ids`，不扫描项目中其它非终态 Generation；恢复使用持久 cursor 与已完成
command ID，避免重复写入或 Provider 提交。
