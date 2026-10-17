# models/validation/

`StructuredDirectorDocument` 与 `ReferenceGeneration` 的跨域校验，按域分段：

- `document.py`：`validate_document(document)`，依次校验 identity、application_requests、capability_gaps、director_runs、
  status 与 layers、pending edits、Keyframe 解锁、脚本来源 revision、assets 与 generations、非出镜声音可见性、旁白选择、
  地点引用归属（Scene/Shot/Keyframe 与 Location/View）、Keyframe 计划、视频计划、最终装配与 Approval。
- `generation.py`：`validate_reference_generation(generation)`，分段校验公共字段、时间戳、kind/operation 契约、Provider 句柄、
  阶段与句柄一致性、生命周期字段。

校验顺序决定同一输入首先抛出的错误，修改时保持顺序稳定。本包只依赖 stdlib、`models/` 内部与 L1 schema；上层不得绕过它另建校验。
