# reads/

只读投影层（L4）：在 `StructuredDirectorDocument` 快照上回答问题或试算命令影响，
不写项目、不 import `store`/`service`。

- 模块只读 document，绝不写项目、绝不持有 Store；
- 试算/投影逻辑复用 L0–L2（models/codec/mutations）与同包模块；
- 新增模块只允许 import models/codec/mutations（L0–L2）、同包 reads 模块与命令解析契约；
  需要 store 写能力说明分层错了，应上移到 service。

## 模块

- `read_tools.py`：reads 包 facade。`execute_project_read` 按 Scene、target、candidate、
  dependency、run、request、workset 等正式 read tool 名分发到各领域 reader；
  领域私有 reader 与参数/分页/结果界辅助在本模块与同包模块内复用。
- `common.py`：共享纯读辅助（`_exact_arguments`/`_id`/`_ids`/`_json_value`/
  `_asset_summary`/`_validate_result_bounds`/`ReadResultTooLarge`），叶子模块，
  供 read_tools 与同包模块模块级复用，避免互相 import 成环。
- `workflow_state.py`：同源主流程投影、可选推荐动作（`recommended_next_actions`）、引用审核摘要与阶段门禁
  （`workflow_state`/`location_binding_gaps`/`require_workflow_action`/`references_reviewed`/`reference_fingerprint`）。
- `video_recipes.py`：当前视频 recipe、兼容切换选项、槽位标签及生成时长的只读投影；目录由 Service 提供。
- `snapshot_view.py`：Web 权威快照、human `allowed_actions` 与资产使用原因投影。
- `location_image.py`：地点库的 Web 只读投影；复用地点批次分类与单项生成计划，
  返回每张独立图片的类型、说明、生成状态、候选、选图、全景取景能力和允许动作。
  删除、清除与选择通过一次性索引复用正式 mutation 的纯拒绝判定，不重建文档；
  全景字节校验由 Service 的只读接口访问 Store 的 SHA-256 进程缓存。
- `semantic_projection.py`：显式 Scene scope 的版本化共源故事投影与语义树。
- `professional_worksets.py`：`project.get_contract`/`project.get_workset` 分页专业工作集。
- `execution_reads.py`：handoff（workflow + allowed_actions + task discovery）、request 与
  asset manifest 只读衔接。
- `impact.py`：`preview_command_impact`，在 document 副本上试算正式命令的保守影响上界；
  `visual_production.unlock` 的预览附 `location_advisory`（未绑定地点的 Scene）。
- `dependencies.py`：关键帧依赖闭包的纯读派生（`_dependency`/`_get_dependencies`/
  `_selected_assets` 等），供 workflow_state、semantic_projection、read_tools 复用。
- `batch_observation.py`：外部批次纯读观察（`batch_observation`/`batch_observations`/
  `_owned_batch`/`owned_batch_id_for_run`），Keyframe 波次与地点成套生成共用回执/run 骨架；
  批次执行上下文（`BatchExecutionContext`/`current_batch_execution`）
  由 external_batches 设置、application_requests 读取，避免两者互相 import。
- `proposal_observation.py`：proposal 生命周期的纯读观察（run.get_status / request_read
  内联观察），供 workflow_state、execution_reads、read_tools 与 proposal_requests 复用。
