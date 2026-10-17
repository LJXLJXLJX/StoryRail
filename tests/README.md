# Tests

从仓库根目录运行 `.venv/bin/python -m pytest`。全部测试只在临时目录构造项目，使用合成媒体字节与 fake
Provider；不读写真实作品、不调用真实模型或媒体服务。合成媒体只证明协议与状态正确，不证明视觉或音质。

## 共享 fixture

- `structured_director_fixtures.py`：受控 Provider fake 与媒体样本，不包含测试类。
- `proposal_fixture_service.py`：用确定性 canned proposal 预置领域资料；只用于测试，不是产品执行器或 fallback。
- `keyframe_wave_fixtures.py`、`playground_fixtures.py`、`provider_factory.py`：Keyframe 波次、Playground 与 Provider 构造。
- `fixtures/prompt_contracts/`：专业输入与历史缺陷样本（原样保存并带 SHA-256），见其 README。
- `fixtures/mcp_project_tools.json`：项目 scope 下 `tools/list` 的逐字节基线。
- `golden_provider_requests.py` + `golden/provider_requests/`：真实插件经录制 transport 发出的外部服务请求黄金文件
  （媒体字节规范化为标签 + SHA-256）。`STORYRAIL_UPDATE_GOLDEN=1` 重录，只用于有意改变线上请求并经审查的提交。

## Provider 行为契约

[Provider 行为与自动化守护](provider-behavior-contract.md) 逐项列出当前能力绑定、视频、语音、图片、音频、
确定性工具、生命周期、Agent 与 Playground 规则的实现位置和测试；IndexTTS2.5 使用通用 recipe 接入。

## 按领域分组

| 领域 | 主要测试 |
| --- | --- |
| 持久化与分层 | `test_document_persistence_contract.py`（严格编解码、CAS、原子失败）、`test_layer_rules.py`、`test_domain_module_boundaries.py`、`test_core_structure.py`、`test_models_validation.py` |
| 结构化导演工作流 | `test_structured_director*.py`（项目/HTTP 基础、脚本、旁白、地点、Keyframe、Generation、恢复）、`test_scene_driver_invariants.py`、`test_dialogue_speaker_label.py`（对白说话者二选一）、`test_narration_review.py`、`test_keyframe_rebase.py`、`test_unlock_visual_revision.py` |
| 命令与失效 | `test_director_commands.py`、`test_command_registry_table.py`、`test_impact_preview.py`、`test_*_mutations.py`、`test_manual_command_paths.py` |
| 成片 | `test_final_scene_assembly.py`、`test_scene_final_overwrite.py`、`test_ffmpeg_*.py`、`test_video_candidate_duration.py` |
| 应用层与授权 | `test_application_access.py`（真实 loopback HTTP 的 caller gate、撤权、旧路由拒绝、第二 writer 租约）、`test_application_requests.py`（原子回执、重放、提交不确定不重发）、`test_project_execution_delegation.py`、`test_workflow_gates.py` |
| 外部 Agent 入口 | `test_external_reference_proposals.py`、`test_external_script_proposals.py`、`test_external_planning_proposals.py`、`test_external_production.py`（批次波次、中断回放、human-only 拒绝）、`test_external_workspace.py`、`test_professional_worksets.py`、`test_prompt_worksets.py` |
| MCP | `test_storyrail_mcp.py`（官方 SDK + 真实 stdio 子进程 + HTTP，含丢响应重放）、`test_production_tools.py`、`test_mcp_conditional_schema.py`、`test_mcp_proposal_action_schema.py`、`test_mcp_response_serialization.py`、`test_agent_response_bounds.py` |
| 错误契约 | `test_error_taxonomy.py`、`test_unified_error_contract.py` |
| 读取投影 | `test_semantic_projection.py`、`test_projection_consumers.py`、`test_storage_benchmark.py` |
| Provider 插件 | `test_golden_provider_requests.py`（项目旅程与 Playground 的线上请求逐字节不变）、`test_provider_settings.py`（manifest、能力绑定、插件设置与提交快照）、`test_provider_*.py`、`test_model_provider_contract.py`、各插件同名测试、`test_lane_dispatcher.py`、`test_resource_manager.py`、`test_controller_lease.py` |
| Playground | `test_playground_*.py`（含 `test_playground_boundaries.py` 依赖隔离守卫）、`test_storyrail_mcp_playground.py`、`test_gateway_playground_scope.py`、`test_local_connection_playground.py` |
| 本机接入 | `test_agent_onboarding.py`、`test_agent_launcher_playground.py`、`test_agent_public_proxy.py`、`test_agent_clipboard*.py`、`test_start_script.py` |
| 合同生成物 | `test_web_contract_generation.py`、`test_schema_gen.py`、`test_wire_field_contracts.py` |

## 端到端 oracle（`oracle/`）

`oracle/` 下每个测试固定一条跨模块不变量：完整旅程、精确失效、重启恢复、提交不确定、权限边界、MCP 线上形状、
Web dist、纯净安装和 token 基准（读取 `scripts/harness/benchmark/baselines/token-bench.json`）。

`test_architecture_acceptance.py` 在临时目录走完混合 TTS → 时序 → Keyframe → 视频 → 装配 → 选择 → Approval，
在 Provider 提交后重建 Service/Store，断言无重复提交、无自动选择/续批。Web 的 `mixed_approval_fixture.json`
来自同一流程快照，重建命令：

```bash
PYTHONPATH=.:tests .venv/bin/python tests/test_architecture_acceptance.py
```

随机 ID 与时间戳会变化；该 fixture 只用于 Web 严格 schema 消费。

## 默认跳过的测试

- `test_agent_onboarding_docker.py`：设置 `STORYRAIL_DOCKER_TESTS=1` 后运行，需要 Docker。
- `test_native_codex_mcp.py`：设置 `STORYRAIL_NATIVE_CODEX_TESTS=1` 后运行，需要已安装 Codex CLI，会产生真实 schema discovery 调用。

跳过项不能记为通过。真实 Agent 与 OS 隔离验收见 `scripts/harness/`。
