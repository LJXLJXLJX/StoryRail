# core/playground

与项目平行、全局唯一的媒体实验工作区。只做一件事：让人和外部 Agent 用生产同一批媒体
Provider 做实验，产物进入 Playground 自己的资产库，需要时由人类复制到某个项目。

非目标：节点图与批量扫描、故事形状能力（旁白 TTS、Scene 成片、Animatic、全片装配）、
硬链接去重、候选与 Approval、多 Playground、项目 Agent 访问。

authority 是 `.stories/.playground/playground.json`（schema v2）与同目录的 `assets/`；项目
`project.json` schema 不变。

## 文件职责

- `models.py`（L0）：领域模型与自洽校验。
- `codec.py`（L1）：`playground.json` 严格编解码。
- `parameters.py`（L1）：所有模型根据 recipe 解析参数、seed 与输入标签，运行记录保存声明；确定性工具按固定参数契约解析。
- `errors.py`（L1）：可映射到 HTTP 的领域错误。
- `capabilities.py`（L2）：当前绑定插件的动态 recipe 目录、确定性工具目录（抽帧、全景裁切、混音、后处理、截取）、输入解析与请求构造；全景裁切范围与输入校验直接复用 `core/model_providers/contracts.py`。
- `lifecycle.py`（L2）：run 迁移、提交失败分类、重试链接、启动恢复。
- `usage.py`（L2）：Asset 占用判定。
- `store.py`（L3）：原子持久化与 Asset 文件管理；按 SHA-256 缓存图片是否满足全景裁切输入契约，供 `projection.py` 决定 `pano_view` 动作。
- `observer.py`（L6）：Provider 观察、取消与产物回收。
- `service.py`（L6）：锁内串行化写入的应用服务。

依赖规则（由 `tests/test_playground_boundaries.py` 守卫）：本包不得 import
`core.structured_director`、`core.project_workspaces`、`core.director_commands`、
`core.web_contracts`；反过来项目包也不得 import 本包。唯一同时接触两侧的是
`server/asset_transfer.py`。
