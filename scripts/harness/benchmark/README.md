# token benchmark 体系

确定性 fake Agent driver：**真实 MCP stdio 子进程 + 真实 Core（合成媒体 Provider）**，
不调用任何真实模型、不联网、不写仓库内业务状态。用途是把 Agent 每轮固定驻留与
读路径成本变成**可重复测量、可门禁**的数字。

## 结构

```text
scripts/harness/benchmark/
  scenarios/           # 6 个标准场景 JSON（reference/script/location/keyframe/h3/ref2va）
  fake_agent_driver.py # 真实 stdio 驱动 + 场景求值 + 确定性 bootstrap
  meter.py             # 计量口径：逐请求 input/output 字节、tools/list、契约/工作集分页
  report.py            # 报告生成 + 防回归门禁（写入/比较 baselines/token-bench.json）
  baselines/           # 冻结基线：token-bench.json（门禁读取）、agent-tokens-2026-09-11.json（scripts/metrics.py 读取）
```

## 场景脚本格式

每个场景 JSON 是 `{scenario, capability, bootstrap, summary, steps[]}`；`steps[]` 的 `action`：

| action | 语义 |
| --- | --- |
| `list_tools` | 调 `tools/list`，计量 `description + input_schema` 紧凑 JSON 总字节 |
| `call` | 调一个 MCP 工具，`arguments` 支持占位符 |
| `pages` | 按 `next_cursor` 分页读取，拼接 `content_chunk` 后解析；记录分页轮次 |
| `keyframe_submit` | 从最近一次 keyframe 工作集构造合法 `KeyframePlanProposal` 并 submit |
| `location_submit` | 从最近一次 location 工作集为每个 Scene 构造一个新地点与主机位视图，经 `submit_proposal` 提交并绑定全部 Shot |
| `wait` | `manage_generation(action="wait")`，同一幂等键重试直到 `wait_again=false` |

占位符语法：`$<step_id>.<path>`，路径支持 `a.b`、`a[0]`、`a[*].b`，以及 `+ <整数>`
（用于 `expected_revision` 自增）。步骤可用 `capture_ids` 把响应里的稳定 ID
（如 `keyframe_plan.keyframes[*].id`）抽成占位符给后续步骤使用。

`bootstrap` 声明合成项目起始状态；Bootstrap **只做人类审核动作**（引用库审核、
脚本确认；生产基线由 Core 随写入自动建立），Agent 侧工作一律经 MCP 工具完成：

| bootstrap | 状态 |
| --- | --- |
| `empty` | 只创建项目（引用库冷启动） |
| `ready` | 引用库已审核（结构化脚本待生成） |
| `timing` | 脚本已确认、生产基线已建立 |
| `unlocked` | 视觉生产已解锁（关键帧计划待规划） |
| `keyframes` | 关键帧计划已生成并选择候选（可进入 H3/Ref2VA） |

## 计量口径（`meter.py`）

- `input_bytes`：一次请求的 `json.dumps(arguments, separators=(",", ":"))` UTF-8 字节；
- `output_bytes`：该调用 `structured_content` 的紧凑 JSON 字节；
- `tools_list_bytes`：所有工具的 `description + input_schema` 紧凑 JSON 字节之和；
- `contract_read_bytes` / `workset_read_bytes`：对应工具全部请求与响应字节之和；
- `pagination_rounds`：分页读取实际请求次数（每次请求计一次，非分页读取为 1）；
- `wait_rounds`：`action="wait"` 调用次数；
- `total_wire_bytes = Σ(input_bytes + output_bytes)`：门禁比较量。

三者都不含传输框架开销，与 Core 的 `schema 总字节`、`契约字节` 口径一致。

## 用法

```bash
# 全量实测并重写冻结基线（baselines/token-bench.json）
.venv/bin/python scripts/harness/benchmark/report.py --write

# 只跑防回归门禁（pytest oracle 测试调用同一计量与比较；也可手动执行）
.venv/bin/python scripts/harness/benchmark/report.py --check

# 单场景，打印逐请求明细
.venv/bin/python scripts/harness/benchmark/fake_agent_driver.py --scenario h3 --json
```

门禁语义（`report.py` 顶部常量）：

- 每个标准场景 `total_wire_bytes ≤ 冻结值 × 1.0`（冻结值即当前状态本身，门禁只防回归，不要求继续下降）；
- `tools_list_bytes` 只记录、不设上限：工具 schema 应当写全以免 Agent 绕路，逐字节变化由 `tests/fixtures/mcp_project_tools.json` 把关。

有意改变 Agent 读写面（新增工具、契约正文变长等）时，用 `--write` 重写冻结值，并在提交说明里写清变化原因。

同一 pytest 进程内重复计量必须逐字节一致（`tests/oracle/test_oracle_token_benchmark.py`）。
