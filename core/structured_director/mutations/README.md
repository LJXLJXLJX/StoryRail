# mutations/

L2 领域变换纯函数：接收权威 `StructuredDirectorDocument`，执行校验与对象变换，返回变更后的 document（或携带完整回执的域结果）。
不做文件 I/O；revision CAS、编辑锁与原子写入由 `store/pipeline.py` 的 `commit_mutation` 统一负责。

- `narration.py`：旁白（保存/更新 Cue、清除选择、选择音频、proposal 应用）；时序校准由 `narration_timing.py` 在每次脚本写入里自动执行。
- `final.py`：进入成片阶段、最终成片候选选择与清除、Approval、重新开放生产。
- `generation.py`：Generation 目标校验、创建、状态更新、完成回收（地点视图裁切快照仍等于当前主图与几何时写入 `crop_asset_id`，否则只留历史）、启动时中断提交恢复。
- `asset.py`：导入校验、音频后处理/截取 Generation 构建、删除计划、参考图挂接。
- `reference.py`：角色造型新增与修改，以及写入造型图（`set_look_asset`，设定图候选与资产库图片两条选择入口共用）。
- `run.py`：DirectorRun cursor、进度、等待、恢复与取消。

脚本、Keyframe、repair 与视频字段的变换位于上一级的 `script_mutations.py`、`keyframe_mutations.py`、
`repair_mutations.py`、`video_mutations.py`，遵守同一纯函数规则。新的领域变换放本包。
