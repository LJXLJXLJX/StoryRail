# store/

L3 持久化：schema v36 项目 JSON 的唯一读写入口，完整领域校验（L0 `models/validation`）与原子落盘
（revision compare-and-swap + fsync + `os.replace`）。

- `__init__.py`：`StructuredDirectorStore` facade。直接定义核心 public 方法（`path`、`exists`、`create_project`、`read`、
  `execute_director_read`、`observed_generation`、`update_generation`、`recover_interrupted_submissions`、`read_asset`）与持久化私有助手
  （`_atomic_write`、`_editable_document`、`_ingest_asset` 等）；其余 public 方法经 `__getattr__` 路由到 `domains/` 中同名同签名的方法。
- `pipeline.py`：统一写骨架 `commit_mutation(store, *, loader, mutator)`：loader 读取并做 CAS 与编辑期校验，mutator 做 L2 变换与回执，
  需要写入时调用一次 `_atomic_write`。`_atomic_write` 只在三处被调用：pipeline、`create_project`（独占创建）、
  `delete_assets`（文件暂存回滚必须包裹写入）。
- `change_journal.py`：变更日志。`_atomic_write` 落盘后把新文档的 codec JSON 拆成实体索引（`{实体 ID: digest}`），
  与上一版比较得到本次改动的实体键，记入按 project.json 路径进程内共享的日志（最近 1024 个 revision，只覆盖连续区间，
  断档即从断点重建）。实体 digest 不含子实体内容但含有序子实体 ID 列表；revision、`application_requests`、
  生产基线与各 plan 的 `source_script_revision` 等簿记/派生字段剥离；未登记的其余字段合成一个 `__project__` 键，
  新增字段因此默认与所有写入冲突。日志不是 authority，Core 重启即清空。
- `_domains.py`：项目设置及各业务域 collaborator 的集中装配。
- `domains/`：按域组织的 Store 方法（见其 README）。

`_atomic_write` 每次都重读磁盘版本，要求新 revision 恰好 +1、`workspace_layers` 不回退、环境库变化满足主流程门禁，
随后写临时文件、fsync、原子替换。应用请求事务期间写入会被捕获，与回执合并为一次落盘。

新增 public 方法：在对应域类中实现即可，无需改 facade。
