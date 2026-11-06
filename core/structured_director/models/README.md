# models/

L0 领域模型：不可变 dataclass，构造即校验不变量。`__init__.py` 显式再导出全部 public 名字，统一从
`core.structured_director.models` 导入。字段语义见 [数据模型](../../../docs/data-model.md)。

## 域文件

- `reference.py`：角色卡（含非出镜声音与造型）、旁白身份与引用库。
- `script.py`：结构化脚本（Scene/Shot/Segment/对白/边界）、`PendingScriptEdit`、`CapabilityGap` 一族、生产基线场景校验。
- `narration.py`：项目所选语言旁白 Cue 与 `NarrationTrack`、`PendingNarrationEdit`。
- `location.py`：Location（地点）、固定陈设、状态变体、机位视图与地点库（视图依赖无环校验）。
- `keyframe.py`：Keyframe、Segment 绑定、`KeyframePlan`（前置图无环校验）；`blank_keyframe` 按 Segment 首/末覆盖 Shot 的视图写入建帧时的环境默认值。
- `video.py`：Segment 视频计划（模式、附加图片/参考音频/参考视频、`VideoPlan`）。
- `final.py`：Scene 成片（临时计划）、最终成片计划与 `FinalApproval`（按项目语言）。
- `generation.py`：`ReferenceGeneration` 与唯一状态迁移函数 `transition_generation`。
- `asset.py`：不可变 Asset、图片分类、使用原因与删除闭包（`asset_usage_reasons` / `asset_deletion_closure` 一族）。
- `run.py`：`DirectorRun` / Cursor / Authorization / Receipt / Directive。
- `document.py`：`WorkspaceLayers` 与 `StructuredDirectorDocument`（权威对象图）。
- `_shared.py`：ID/SHA/路径正则、校验原语、跨域枚举（状态、语言、Generation kind/operation/phase）与单次图片调用输入上限 `MAX_IMAGE_INPUTS`。
- `validation/`：文档与 Generation 的跨域校验函数，由 `__init__` 注入到对应 `__post_init__`。

域文件之间相对导入；仅用于注解的跨域引用放在 `TYPE_CHECKING` 下以避免运行时环。L0 只依赖 stdlib 与 L1 公共词汇
（schema、video_contracts、project_settings）。

`SegmentVideo.reference_images` 是可选的无时间位置图片规划，按 recipe 与槽位位置保存正文、用途、角色造型与显式生图参考。选中的图片唯一保存在 `recipes.bindings`；规划自身不保存另一份选图状态。项目 schema 保持 v35，缺省规划为空。
