# scripts/harness

开发期 Agent harness 的统一入口。不属于产品 runtime，产品代码不得 import 本包。

```text
scripts/harness/
  README.md      # 本文件：三种用法与接入矩阵
  benchmark/     # 确定性 fake driver：token 线上字节计量 + 防回归门禁
  real_agent/    # Docker 真实 Agent 验收（opt-in，需明确授权）
  probes/        # 合成 OS 隔离探针
  fixtures/      # 共享确定性 fixture：合成媒体字节、合成媒体 Provider、候选登记
```

三种用法：

1. **fake driver（默认，无模型、无网络）**：`scripts/harness/benchmark/report.py`。
   真实 MCP stdio 子进程 + 真实 loopback Core + 合成媒体 Provider，按场景脚本
   确定性驱动五个标准场景；明细见 [benchmark/README.md](benchmark/README.md)。
   进门禁：`tests/oracle/test_oracle_token_benchmark.py` + `scripts/ci_local.sh` +
   `.github/workflows/ci.yml`。
2. **真实 Agent 验收（opt-in，须仓库所有者明确授权）**：
   `scripts/harness/real_agent/`。Docker 隔离运行原生 Pi/Kimi，经真实模型网关计量；
   没有既有授权与凭据时不得运行。网关 `meter_gateway.mjs` 的 `config.mode` **必填**
   （`kimi_messages` / `openai_responses`），限额字段与 `--validate-config` 说明见
   [real_agent/README.md](real_agent/README.md)。
3. **OS 隔离探针（opt-in，需要 Docker）**：`scripts/harness/probes/`。
   合成项目 + 非特权容器验证 volume/UID/只读根/单写租约；见
   [probes/README.md](probes/README.md)。

共享 fixture：`fixtures/` 只提供确定性合成媒体字节、合成媒体 Provider，以及把已有图片登记为成功候选的
`candidates.py`（候选选择只接受目标自己的成功 Generation），
不读取项目语义、不调用真实媒体服务；`real_agent` 与 `benchmark` 都从这里取，
不再各自维护第二份实现。

## Agent 接入矩阵

MCP 结果的 text content 始终是完整 JSON，`structured_content` 携带同一份数据。
本表只记录**有证据**的验证状态；未复验的行保持「未验证」，不得当成通过。

| 客户端 | fake driver / 合成 Core 冒烟 | 真实模型 opt-in 读取路径 |
| --- | --- | --- |
| DeepSeek Harness | 已验证真实 headless MCP 读取消费 `structured_content` | 未验证（需仓库所有者授权） |
| Pi | 未验证 | 未验证（需授权 + 凭据） |
| Codex CLI | opt-in `STORYRAIL_NATIVE_CODEX_TESTS=1`，默认 skip | 未验证 |
| Kimi Code | `real_agent` 网关计量回归覆盖协议，未接真实模型 | 未验证 |
| AGY / Grok | 未验证 | 未验证 |

真实模型列只有在仓库所有者明确授权并实际运行 `real_agent/` 后才能改为已验证。

回归所需的专业输入保存在 `tests/fixtures/prompt_contracts/`，不依赖任何开发任务账本。
