# 开发验证与媒体验收脚本（索引）

媒体探针仅在显式运行时调用对应 Provider；先查看脚本参数，使用明确授权的项目与输入。
这些脚本不管理软件开发任务，也不替代 Core 的生产状态。

## `scripts/harness/`（Agent harness，不属于产品 runtime）

三种用法与目录结构见 [harness/README.md](harness/README.md)：

- `harness/benchmark/`：确定性 fake driver（真实 MCP stdio + 真实 Core + 合成媒体），
  token 线上字节计量与防回归门禁；无模型、无网络。见
  [benchmark/README.md](harness/benchmark/README.md)。
- `harness/real_agent/`：Docker 真实 Agent 验收与正式 Web 构建验收（opt-in，须明确授权）。
- `harness/probes/`：合成 OS 隔离探针（opt-in，需要 Docker）。
- `harness/fixtures/`：共享确定性合成媒体与合成媒体 Provider。

## 顶层脚本

- `benchmark_project_storage.py` 使用临时合成项目测量单 JSON 与领域投影。
- `check_fixture_freshness.py`、`gen_web_contracts.py` 是 CI 与 `ci_local.sh` 的
  生成物新鲜度门禁。
- `metrics.py` 输出工程指标 JSON（模块规模、依赖、门禁耗时、Agent 驻留字节等，口径见各 `m*` 函数文档字符串）。
- `ref2va_acceptance.py`、`seedvr2_upscale_acceptance.py` 等脚本验证明确配置的媒体服务，不被普通离线测试自动调用。
- `ci_local.sh` 本地跑与 `.github/workflows/ci.yml` 等价的工程门禁；默认跳过 `slow`，`--full` 全跑。

真实模型或媒体请求须有相应授权；只回收本次创建的临时资源，不使用全局 prune。
回归所需的专业输入位于 `tests/fixtures/prompt_contracts/`，不依赖开发任务目录。
