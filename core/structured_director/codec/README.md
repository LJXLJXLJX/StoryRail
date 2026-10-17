# codec/

L1 文档编解码包：原 `document_codec.py`（1557 行 / 48 对 parse/serialize）按域
拆分为本包，**纯移动**——解析语义、JSON key、错误消息、默认值处理逐字不变。

`__init__.py` 再导出 `serialize_document` / `_parse_document`。原
`core.structured_director.document_codec` 再导出 shim 已在合并后的收尾修复中删除；
唯一路径是本包。

## 域文件

- `reference.py`：引用库（角色卡、旁白身份、参考图）。
- `script.py`：结构化脚本（Scene/Shot/Segment/对白/边界）、CapabilityGap、
  PendingScriptEdit/PendingNarrationEdit。
- `narration.py`：按项目语言的旁白 Cue 与 zh / en 轨道。
- `location.py`：Location（地点）、固定陈设、状态变体、机位视图与地点库。
- `keyframe.py`：Keyframe、Segment 绑定、KeyframePlan。
- `video.py`：Segment 视频计划（图片/音频引用、模式、VideoPlan）。
- `final.py`：Scene 成片/全片装配计划与 FinalApproval。
- `generation.py`：ReferenceGeneration（含可选审计时间与 language）。
- `asset.py`：不可变 Asset。
- `run.py`：DirectorRun/Cursor/Receipt/Directive。
- `document.py`：`serialize_document` / `_parse_document` 顶层编排（schema
  版本与层解锁）。
- `_shared.py`：解析/序列化原语（_exact_object/_string/_integer/…）与
  `_object_list` 一族。

只依赖 models/（L0）、L1 公共词汇（schema、video_contracts、
project_settings、application.requests）与 stdlib。
