# store/domains/

`StructuredDirectorStore` facade 的域 collaborator：每个域一个类，持有该域的 public Store 方法。facade 经 `__getattr__`
把 public 方法路由到这里；私有持久化助手定义在 `store/__init__.py`，域方法经 `_DomainBase.__getattr__` 回退解析。

- `project.py`：人类手工修改原始导演方案；只更新项目事实，不自动改写已有结构化内容。
- `reference.py` / `script.py`：引用库与脚本的 proposal、编辑、操作与 repair。
- `narration.py` / `run.py` / `generation.py` / `asset.py` / `final.py`：对应 L2 mutations 域。
- `keyframe.py` / `video.py`：Keyframe 计划与视觉解锁、视频生产。
- `location.py`：地点库编辑（`location.apply_operations`）与人类独立图片选择。

新增域：实现新域类，并在 `store/__init__.py` 的 `_domains` 元组与尾部导入中登记。
